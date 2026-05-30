"""Configuration, credential parsing, and tunable constants for the Kalshi agent.

The credential file ships in a non-standard format: a custom
``-----Begin API key id-----`` wrapper around the UUID, followed by a real PEM
``-----BEGIN RSA PRIVATE KEY-----`` block. We parse both defensively.
"""

import os
import re
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_pem_private_key

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
CREDENTIAL_FILE = Path(
    os.environ.get("KALSHI_CREDENTIAL_FILE", ROOT / "kalshi-prediction-market-agent.txt")
)
FIXTURES_DIR = ROOT / "fixtures"
LOGS_DIR = ROOT / "logs"
DECISIONS_LOG = LOGS_DIR / "decisions.jsonl"
SELLS_LOG = LOGS_DIR / "sells.jsonl"
LESSONS_FILE = LOGS_DIR / "lessons.md"

# --- API endpoints -----------------------------------------------------------
# Production trading host. If the account is provisioned on the legacy host,
# set KALSHI_BASE_URL to the external-api variant below.
BASE_URL = os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
# Fallbacks for reference:
#   https://external-api.kalshi.com/trade-api/v2   (legacy prod)
#   https://demo-api.kalshi.co/trade-api/v2        (sandbox)
API_PREFIX = "/trade-api/v2"  # must be part of the signed path

# --- Run mode ----------------------------------------------------------------
# Dry-run never POSTs orders and falls back to fixtures when the live API is
# unreachable (e.g. geo-blocked outside the US). Toggle via env or per-CLI flag.
DRY_RUN = os.environ.get("KALSHI_DRY_RUN", "0") not in ("0", "", "false", "False")

# --- Strategy constants ------------------------------------------------------
CAP = 20                 # max concurrent open positions
KELLY_FRACTION = 0.5     # half-Kelly
MAX_TRADE_FRACTION = 0.10  # never stake more than 10% of bankroll on one market
FEE_BUFFER_CENTS = 3     # require at least this much edge (cents) to clear fees
TP_FRACTION = 0.75       # take profit at 75% of max possible gain
SL_FRACTION = 0.40       # stop loss when down 40% of cost basis
CRON_INTERVAL_MINUTES = 120  # TP/SL check cadence

# --- Ticker mapping ----------------------------------------------------------
# Kalshi series_ticker -> yfinance symbol. Pins the cryptic codes to the exact
# yfinance symbol format so data pulls do not silently fail. Claude handles the
# long tail (single stocks); macro markets have no price ticker (-> None).
SERIES_TO_YF = {
    "KXINX": "^GSPC",
    "KXINXU": "^GSPC",
    "KXINXD": "^GSPC",
    "KXINXW": "^GSPC",
    "KXINXY": "^GSPC",
    "KXNASDAQ100": "^NDX",
    "KXNASDAQ100U": "^NDX",
    "KXDJI": "^DJI",
    "KXBTC": "BTC-USD",
    "KXBTCD": "BTC-USD",
    "KXETH": "ETH-USD",
    "KXETHD": "ETH-USD",
}


# Prefix families for the index/crypto series (Kalshi appends suffixes like
# U/D/W/Y/100Y to the same underlying), so symbol resolution is prefix-aware.
_YF_PREFIXES = (
    ("KXNASDAQ100", "^NDX"),
    ("KXNASDAQ", "^NDX"),
    ("KXDJI", "^DJI"),
    ("KXINX", "^GSPC"),
    ("KXSPX", "^GSPC"),
    ("KXBTC", "BTC-USD"),
    ("KXETH", "ETH-USD"),
)


def resolve_yf_symbol(series_ticker: str) -> str | None:
    """Map a Kalshi series_ticker to a yfinance symbol, or None if unknown.
    Tries the exact map first, then the known index/crypto prefix families."""
    if not series_ticker:
        return None
    st = series_ticker.upper()
    if st in SERIES_TO_YF:
        return SERIES_TO_YF[st]
    for prefix, sym in _YF_PREFIXES:
        if st.startswith(prefix):
            return sym
    return None


# --- Market classification ---------------------------------------------------
# Routes each market to the right analysis tools in /invest. Only price-threshold
# and single-stock markets have a quantitative anchor (probability.py); the rest
# are news-reasoning-only (and not backtestable). Order matters: most specific
# first.
_CRYPTO_SERIES = ("KXBTC", "KXETH")
_INDEX_SERIES = ("KXINX", "KXNASDAQ", "KXDJI", "KXSPX")
_MACRO_KW = ("cpi", "inflation", "ppi", "payroll", "jobs", "unemployment", "gdp",
             "recession", "fed", "fomc", "rate decision", "interest rate", "jobless")
_RATES_FX_KW = ("usd", "eur", "gbp", "jpy", "aud", "cad", "yuan", "yen", "euro",
                "treasury", "yield", "10-year", "2-year", "fx", "dollar")
_IPO_KW = ("ipo", "go public", "public offering", "debut", "direct listing")


def classify_market(series_ticker: str | None, title: str | None = None,
                    strike_type: str | None = None) -> str:
    """Bucket a market into a routing category from its series ticker + title.

    Returns one of: crypto, index, single_stock, ipo, macro, rates_fx, other.
    `crypto`/`index`/`single_stock` carry a price strike -> quant anchor applies;
    `ipo`/`macro`/`rates_fx`/`other` are event markets -> news reasoning only.
    """
    st = (series_ticker or "").upper()
    t = (title or "").lower()

    if st.startswith(_CRYPTO_SERIES) or resolve_yf_symbol(st) in ("BTC-USD", "ETH-USD"):
        return "crypto"
    if st.startswith(_INDEX_SERIES) or resolve_yf_symbol(st) in ("^GSPC", "^NDX", "^DJI"):
        return "index"
    if st.startswith("KXIPO") or any(k in t for k in _IPO_KW):
        return "ipo"
    if any(k in t for k in _MACRO_KW):
        return "macro"
    if any(k in t for k in _RATES_FX_KW) or st.endswith(("USDQ", "USDM")):
        return "rates_fx"
    # A numeric strike on a non-index/crypto series is *usually* a single-stock
    # price market, but can be a numeric event (e.g. SpaceX launch counts).
    # /invest must confirm the underlying + infer the yfinance symbol before
    # trusting the quant/fundamental tools; if it is not a security, treat as news.
    if strike_type in ("greater", "less", "between") and st.startswith("KX"):
        return "single_stock"
    return "other"


# --- Credential parsing ------------------------------------------------------
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PEM_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)


def _read_credentials() -> tuple[str, bytes]:
    """Return (api_key_id, pem_bytes) parsed from the credential file."""
    text = CREDENTIAL_FILE.read_text()
    uuid_match = _UUID_RE.search(text)
    pem_match = _PEM_RE.search(text)
    if not uuid_match:
        raise ValueError(f"No API key id (UUID) found in {CREDENTIAL_FILE}")
    if not pem_match:
        raise ValueError(f"No PEM private key block found in {CREDENTIAL_FILE}")
    return uuid_match.group(0), pem_match.group(0).encode("utf-8")


@lru_cache(maxsize=1)
def get_api_key_id() -> str:
    return _read_credentials()[0]


@lru_cache(maxsize=1)
def get_private_key() -> rsa.RSAPrivateKey:
    _, pem = _read_credentials()
    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("Credential file does not contain an RSA private key")
    return key
