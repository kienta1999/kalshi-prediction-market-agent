"""Thin signed REST client for the Kalshi trading API, plus a JSON-printing CLI.

Auth: RSA-PSS(SHA-256, salt=DIGEST_LENGTH) over `timestamp_ms + METHOD + path`,
where `path` includes the `/trade-api/v2` prefix and EXCLUDES the query string.

Dry-run: order writes never hit the network (they print + return a simulated
fill). Reads attempt the live API and fall back to fixtures on failure, which
lets the whole flow run outside the US where the API is geo-blocked.
"""

import argparse
import base64
import json
import sys
import time
import uuid
from urllib.parse import urlencode

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

import config


class KalshiError(RuntimeError):
    pass


def _cents(dollar_str) -> int | None:
    """'0.6200' -> 62 (integer cents). None passes through."""
    if dollar_str is None:
        return None
    try:
        return round(float(dollar_str) * 100)
    except (TypeError, ValueError):
        return None


def _num(fp) -> float | None:
    try:
        return float(fp)
    except (TypeError, ValueError):
        return None


def position_count(pos: dict) -> float:
    """Signed open-contract count for a position row.

    The live API reports it as `position_fp` (a float-as-string, e.g. "5.00",
    "-8.00"); older/fixture rows use an integer `position`. Read whichever is
    present so flat-vs-open and YES-vs-NO checks work against both schemas.
    """
    v = pos.get("position_fp")
    if v is None:
        v = pos.get("position")
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def normalize_market(m: dict) -> dict:
    """Flatten the modern `_dollars`/`_fp` market shape into clean integer-cent
    prices plus the fields the agent actually reasons over."""
    yes_bid = _cents(m.get("yes_bid_dollars"))
    yes_ask = _cents(m.get("yes_ask_dollars"))
    no_bid = _cents(m.get("no_bid_dollars"))
    no_ask = _cents(m.get("no_ask_dollars"))
    return {
        "ticker": m.get("ticker"),
        "series_ticker": m.get("series_ticker"),
        "event_ticker": m.get("event_ticker"),
        "title": m.get("title"),
        "subtitle": m.get("subtitle") or m.get("yes_sub_title"),
        "status": m.get("status"),
        "close_time": m.get("close_time"),
        "strike_type": m.get("strike_type"),
        "floor_strike": m.get("floor_strike"),
        "cap_strike": m.get("cap_strike"),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": no_bid,
        "no_ask": no_ask,
        "last_price": _cents(m.get("last_price_dollars")),
        "volume": _num(m.get("volume_fp")),
        "volume_24h": _num(m.get("volume_24h_fp")),
        "open_interest": _num(m.get("open_interest_fp")),
        "liquidity": _num(m.get("liquidity_dollars")),
    }


def is_tradeable(nm: dict) -> bool:
    """A normalized market worth analyzing: a two-sided book that isn't pinned
    to the 0/100 extreme (those carry no realistic edge)."""
    ya, yb = nm.get("yes_ask"), nm.get("yes_bid")
    if ya is None or yb is None:
        return False
    return 1 <= ya <= 99 and 0 <= yb <= 99 and yb < ya and ya > 1


class KalshiClient:
    def __init__(self, base_url: str | None = None, dry_run: bool | None = None,
                 use_fixtures: bool = False, timeout: int = 15):
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.dry_run = config.DRY_RUN if dry_run is None else dry_run
        self.use_fixtures = use_fixtures
        self.timeout = timeout
        self.session = requests.Session()
        self._key_id = config.get_api_key_id()
        self._private_key = config.get_private_key()

    # --- auth ----------------------------------------------------------------
    def _headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        message = (ts + method.upper() + path).encode("utf-8")
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "Content-Type": "application/json",
        }

    # --- core request --------------------------------------------------------
    def _request(self, method: str, endpoint: str, params: dict | None = None,
                 body: dict | None = None, _retries: int = 3) -> dict:
        path = config.API_PREFIX + endpoint  # signed path: NO query string
        url = self.base_url + endpoint
        if params:
            params = {k: v for k, v in params.items() if v is not None}
            if params:
                url = f"{url}?{urlencode(params)}"
        headers = self._headers(method, path)
        data = json.dumps(body) if body is not None else None

        backoff = 0.5
        for attempt in range(_retries):
            try:
                resp = self.session.request(
                    method, url, headers=headers, data=data, timeout=self.timeout
                )
            except requests.RequestException as exc:
                raise KalshiError(f"network error: {exc}") from exc
            if resp.status_code == 429:  # no Retry-After header -> own backoff
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code >= 400:
                raise KalshiError(f"{resp.status_code} {method} {endpoint}: {resp.text}")
            return resp.json() if resp.content else {}
        raise KalshiError(f"rate-limited after {_retries} attempts: {method} {endpoint}")

    def _read(self, method: str, endpoint: str, fixture: str,
              params: dict | None = None) -> dict:
        """A read that falls back to a fixture when the live API is unreachable."""
        if self.use_fixtures:
            return self._fixture(fixture)
        try:
            return self._request(method, endpoint, params=params)
        except KalshiError as exc:
            if self.dry_run:
                print(f"[dry-run] live read failed ({exc}); using fixture {fixture}",
                      file=sys.stderr)
                return self._fixture(fixture)
            raise

    @staticmethod
    def _fixture(name: str) -> dict:
        path = config.FIXTURES_DIR / name
        if not path.exists():
            raise KalshiError(f"fixture missing: {path}")
        return json.loads(path.read_text())

    # --- read endpoints ------------------------------------------------------
    def get_balance(self) -> dict:
        return self._read("GET", "/portfolio/balance", "balance.json")

    def get_positions(self) -> dict:
        return self._read("GET", "/portfolio/positions", "positions.json")

    def financial_series_set(self) -> set[str]:
        """Series tickers in the agent's financial universe.

        Union of (a) what Kalshi files under ``category=Financials`` and (b) any
        series the agent has itself traded (read from the decisions log). (b)
        catches finance series that Kalshi may file under a different category
        (e.g. macro/CPI under "Economics") but that /invest does trade. Anything
        not in this set — sports, weather, politics — is treated as non-finance.
        """
        out = {s.get("ticker") for s in self.get_financial_series().get("series", [])
               if s.get("ticker")}
        try:
            import journal
            out |= {config.series_of_ticker(d.get("ticker"))
                    for d in journal.read_decisions(include_dry_run=True)
                    if d.get("ticker")}
        except Exception:  # log unreadable -> just rely on the API set
            pass
        return {s for s in out if s}

    def financial_positions(self, positions: list[dict] | None = None) -> list[dict]:
        """Open positions restricted to the financial universe.

        Drops flat (zero-contract) rows and any position whose series is not
        financial (e.g. sports bets sharing the account). This is the boundary
        that keeps slot-counting and the TP/SL daemon finance-only.
        """
        if positions is None:
            positions = self.get_positions().get("market_positions", [])
        fin = self.financial_series_set()
        out = []
        for p in positions:
            if position_count(p) == 0:  # flat / closed
                continue
            series = config.series_of_ticker(p.get("ticker"))
            if config.is_financial_series(series, fin):
                out.append(p)
        return out

    def get_series_by_category(self, category: str) -> list[dict]:
        """Series filed under one Kalshi /series `category` (e.g. "Crypto")."""
        r = self._read("GET", "/series", "series.json",
                       params={"category": category})
        return (r or {}).get("series") or []

    def get_financial_series(self, categories: tuple[str, ...] | None = None) -> dict:
        """Series across every category in the agent's financial universe.

        Unions and de-dupes the series listed under each of
        ``config.SCAN_CATEGORIES`` (crypto, commodities, economics, financials,
        science). Kept returning the ``{"series": [...]}`` shape so existing
        callers are unchanged. An unknown/empty category just contributes nothing.
        """
        cats = categories or config.SCAN_CATEGORIES
        seen: set[str] = set()
        out: list[dict] = []
        for cat in cats:
            for s in self.get_series_by_category(cat):
                t = s.get("ticker")
                if t and t not in seen:
                    seen.add(t)
                    out.append(s)
        return {"series": out}

    def list_markets(self, series_ticker: str | None = None, status: str = "open",
                     tickers: str | None = None, limit: int = 200,
                     cursor: str | None = None) -> dict:
        return self._read(
            "GET", "/markets", "markets.json",
            params={"series_ticker": series_ticker, "status": status,
                    "tickers": tickers, "limit": limit, "cursor": cursor},
        )

    def _all_markets(self, series_ticker: str, status: str = "open",
                     max_pages: int = 5) -> list[dict]:
        """Page through every market in a series (the book can exceed one page)."""
        out, cursor = [], None
        for _ in range(max_pages):
            page = self.list_markets(series_ticker=series_ticker, status=status,
                                     limit=1000, cursor=cursor)
            out.extend(page.get("markets", []))
            cursor = page.get("cursor")
            if not cursor:
                break
        return out

    def get_market(self, ticker: str) -> dict:
        if self.use_fixtures:
            return {"market": self._fixture_market(ticker)}
        try:
            return self._request("GET", f"/markets/{ticker}")
        except KalshiError as exc:
            if self.dry_run:
                print(f"[dry-run] live get_market failed ({exc}); using fixture",
                      file=sys.stderr)
                return {"market": self._fixture_market(ticker)}
            raise

    def _fixture_market(self, ticker: str) -> dict:
        """Find a market by ticker in markets.json (so fixture prices vary per
        ticker), falling back to the single market.json fixture."""
        try:
            for m in self._fixture("markets.json").get("markets", []):
                if m.get("ticker") == ticker:
                    return m
        except KalshiError:
            pass
        return self._fixture("market.json").get("market", {})

    def get_settled(self, tickers: str) -> dict:
        return self._read("GET", "/markets", "settled.json",
                          params={"tickers": tickers, "status": "settled"})

    def get_settled_markets(self, series_ticker: str, max_pages: int = 10) -> list[dict]:
        """Enumerate settled markets for a series (paginated). Used by the
        backtest to get real strikes, close times, and YES/NO ground-truth."""
        out, cursor = [], None
        for _ in range(max_pages):
            page = self.list_markets(series_ticker=series_ticker, status="settled",
                                     limit=1000, cursor=cursor)
            out.extend(page.get("markets", []))
            cursor = page.get("cursor")
            if not cursor:
                break
        return out

    def get_candlesticks(self, series_ticker: str, ticker: str, start_ts: int,
                         end_ts: int, period_interval: int = 60) -> list[dict]:
        """Historical OHLC of yes_ask/yes_bid for one market. period_interval in
        minutes (1, 60, or 1440). Lets the backtest read the price an agent would
        have faced at decision time."""
        r = self._request(
            "GET", f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            params={"start_ts": start_ts, "end_ts": end_ts,
                    "period_interval": period_interval})
        return r.get("candlesticks", [])

    def financial_markets(self, series: list[str] | None = None,
                          tradeable_only: bool = True,
                          category: str | None = None) -> list[dict]:
        """Normalized open markets for the given financial series, each tagged
        with a routing `category` and `yf_symbol` (None for event markets).

        Defaults to the series we can map to a yfinance symbol (index/crypto),
        which keeps this to a handful of API calls and a tractable candidate set.
        Pass an explicit `series` list (or scan all via the CLI `--all`) to widen
        across IPO/macro/rates/single-stock markets. `category` filters the
        result to one routing bucket (see config.classify_market).
        """
        if series is None:
            series = list(config.SERIES_TO_YF.keys())
        seen, out = set(), []
        for st in series:
            for m in self._all_markets(st, status="open"):
                m.setdefault("series_ticker", st)
                nm = normalize_market(m)
                if nm["ticker"] in seen:
                    continue
                if tradeable_only and not is_tradeable(nm):
                    continue
                if not config.is_finance_relevant(nm["title"]):
                    continue
                nm["category"] = config.classify_market(
                    nm["series_ticker"], nm["title"], nm["strike_type"])
                nm["yf_symbol"] = config.resolve_yf_symbol(nm["series_ticker"])
                if category and nm["category"] != category:
                    continue
                seen.add(nm["ticker"])
                out.append(nm)
        out.sort(key=lambda x: (x.get("volume") or 0), reverse=True)
        return out

    # --- order placement -----------------------------------------------------
    ORDER_ENDPOINT = "/portfolio/events/orders"  # V2 (legacy /portfolio/orders -> 410)

    def _enforce_event_cap(self, ticker: str, count: int, price_cents: int) -> None:
        """Refuse a buy that pushes one event's total cost past MAX_EVENT_FRACTION
        of the portfolio.

        All strikes of a ladder share an event_ticker and settle on the same
        catalyst, so their exposure is summed and capped as ONE position. This is
        a hard gate with no override flag: it exists precisely because the prose
        version of this rule was rationalized around (Tesla Q2 ladder, 2026-07-01).
        Sells are never gated (reducing risk is always allowed). Fails closed:
        if balance/positions can't be read, the order is refused.
        """
        event = config.event_ticker_of(ticker)
        new_cost = int(count) * int(price_cents)
        try:
            bal = self.get_balance()
            positions = self.get_positions().get("market_positions", [])
        except Exception as e:
            raise KalshiError(
                f"event-cap check could not read balance/positions ({e}); "
                "refusing buy order (fail-closed)") from e
        existing = 0
        for pos in positions:
            if config.event_ticker_of(pos.get("ticker")) != event:
                continue
            existing += _cents(pos.get("market_exposure_dollars")) or 0
        bankroll = bal.get("portfolio_value")
        if not bankroll:
            bankroll = (bal.get("balance") or 0) + sum(
                _cents(p.get("market_exposure_dollars")) or 0 for p in positions)
        cap = int(config.MAX_EVENT_FRACTION * bankroll)
        if existing + new_cost > cap:
            room = max(0, cap - existing)
            max_count = room // int(price_cents) if price_cents else 0
            raise KalshiError(
                f"EVENT EXPOSURE CAP: {event} already has ${existing / 100:.2f} at "
                f"risk; this order adds ${new_cost / 100:.2f}, cap is "
                f"${cap / 100:.2f} ({config.MAX_EVENT_FRACTION:.0%} of "
                f"${bankroll / 100:.2f} portfolio). One catalyst = one position's "
                f"worth of risk — a strike ladder is not diversification. "
                f"Max additional count at {price_cents}c: {max_count}. "
                f"Do not work around this by resizing to the limit AND adding "
                f"other markets on the same catalyst.")

    def create_order(self, ticker: str, action: str, side: str, count: int,
                     price_cents: int, time_in_force: str = "immediate_or_cancel",
                     client_order_id: str | None = None) -> dict:
        """Place a limit order via Kalshi's V2 order endpoint.

        The V2 book is single-sided on the YES leg: `side` is "bid" (buy YES) or
        "ask" (sell YES), with a single decimal-dollar `price` string and a
        decimal-string `count`. We keep the agent's familiar (action,
        side=yes/no, price_cents) interface and translate to the YES leg:

            buy  yes  -> bid at  price_cents/100
            sell yes  -> ask at  price_cents/100
            buy  no   -> ask at (100 - price_cents)/100   # sell YES == buy NO
            sell no   -> bid at (100 - price_cents)/100

        `price_cents` is the price of the *chosen* side (e.g. no_ask for buy-no),
        so a buy-no at 23c becomes a sell-YES (ask) at 0.77.
        """
        coid = client_order_id or str(uuid.uuid4())
        price_cents = int(price_cents)
        if action == "buy":
            self._enforce_event_cap(ticker, count, price_cents)
        if side == "yes":
            book_side, yes_price = ("bid" if action == "buy" else "ask"), price_cents
        elif side == "no":
            book_side, yes_price = ("ask" if action == "buy" else "bid"), 100 - price_cents
        else:
            raise KalshiError(f"invalid side {side!r} (expected yes|no)")
        if not (1 <= yes_price <= 99):
            raise KalshiError(f"price out of range: yes-leg {yes_price}c")

        body = {
            "ticker": ticker,
            "side": book_side,
            "count": f"{int(count)}.00",
            "price": f"{yes_price / 100:.4f}",
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": coid,
        }

        if self.dry_run:
            print(f"[dry-run] WOULD POST {self.ORDER_ENDPOINT}: {json.dumps(body)}",
                  file=sys.stderr)
            return {"dry_run": True, "order": {**body, "status": "simulated"}}
        return self._request("POST", self.ORDER_ENDPOINT, body=body)


# --- CLI ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kalshi client CLI (prints JSON)")
    p.add_argument("--dry-run", action="store_true", help="never POST orders; fixture fallback")
    p.add_argument("--use-fixtures", action="store_true", help="force fixture reads (offline)")
    p.add_argument("--base-url", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance")
    pos = sub.add_parser("positions")
    pos.add_argument("--financial-only", action="store_true",
                     help="only open positions in the financial universe "
                          "(excludes sports and other non-finance bets); adds a `count`")
    sub.add_parser("series")
    fm = sub.add_parser("financial-markets")
    fm.add_argument("--series", default=None,
                    help="CSV of series tickers to scan (default: mappable index/crypto series)")
    fm.add_argument("--all", action="store_true",
                    help="scan every financial series (heavy; many API calls)")
    fm.add_argument("--category", default=None,
                    help="filter to one routing category: crypto/index/single_stock/ipo/macro/rates_fx/other")
    fm.add_argument("--include-untradeable", action="store_true")
    gm = sub.add_parser("market"); gm.add_argument("ticker")
    se = sub.add_parser("settled"); se.add_argument("--tickers", required=True)
    od = sub.add_parser("order")
    od.add_argument("--ticker", required=True)
    od.add_argument("--action", choices=["buy", "sell"], required=True)
    od.add_argument("--side", choices=["yes", "no"], required=True)
    od.add_argument("--count", type=int, required=True)
    od.add_argument("--price", type=int, required=True, help="limit price in cents (1-99)")
    od.add_argument("--client-order-id", default=None)

    args = p.parse_args(argv)
    client = KalshiClient(base_url=args.base_url, dry_run=args.dry_run or None,
                          use_fixtures=args.use_fixtures)

    if args.cmd == "balance":
        out = client.get_balance()
    elif args.cmd == "positions":
        if args.financial_only:
            fin = client.financial_positions()
            out = {"market_positions": fin, "count": len(fin)}
        else:
            out = client.get_positions()
    elif args.cmd == "series":
        out = [{"ticker": s.get("ticker"), "title": s.get("title"),
                "category": s.get("category")}
               for s in client.get_financial_series().get("series", [])]
    elif args.cmd == "financial-markets":
        if args.all:
            # Discover series across every category in the agent's universe
            # (config.SCAN_CATEGORIES: financials, crypto, commodities,
            # economics, science), then union with the hardcoded mappable set so
            # the daily index/crypto series are always present even if an API
            # category listing omits them.
            discovered = {s.get("ticker")
                          for s in client.get_financial_series().get("series", [])
                          if s.get("ticker")}
            series = sorted(discovered | set(config.SERIES_TO_YF.keys()))
        elif args.series:
            series = [s.strip() for s in args.series.split(",") if s.strip()]
        else:
            series = None
        out = client.financial_markets(series=series,
                                       tradeable_only=not args.include_untradeable,
                                       category=args.category)
    elif args.cmd == "market":
        out = normalize_market(client.get_market(args.ticker).get("market", {}))
    elif args.cmd == "settled":
        out = client.get_settled(args.tickers)
    elif args.cmd == "order":
        out = client.create_order(args.ticker, args.action, args.side, args.count,
                                  args.price, client_order_id=args.client_order_id)
    else:  # pragma: no cover
        p.error(f"unknown command {args.cmd}")

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
