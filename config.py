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


def resolve_yf_symbol(series_ticker: str) -> str | None:
    """Map a Kalshi series_ticker to a yfinance symbol, or None if unknown."""
    if not series_ticker:
        return None
    return SERIES_TO_YF.get(series_ticker.upper())


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
