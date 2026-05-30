"""Backtest the deterministic core (probability model + edge filter + sizing)
against REAL settled Kalshi markets.

For each settled market we:
  1. read its real strike, open/close time, and YES/NO settlement (ground truth);
  2. pull historical candlesticks and take the first genuinely tradeable quote as
     the decision point (entry price the agent would have faced);
  3. estimate the underlying spot + vol from yfinance using ONLY data before the
     decision date (no lookahead), compute model_p, edge, and a half-Kelly size;
  4. score the simulated trade and model calibration against the real outcome.

This tests the quantitative core on real prices and real outcomes. It does NOT
replay Claude's discretionary news/technical adjustment (that can't be backtested
without hindsight), so treat it as a floor on the full pipeline, not the ceiling.

Usage:
  .venv/bin/python backtest.py
  .venv/bin/python backtest.py --series KXBTCD,KXINXU --per-series 200
"""

import argparse
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

import config
from kalshi import KalshiClient, _num
from probability import _annual_vol, _p_above

TRADING_DAYS = 252
VOL_WINDOW = 252
SECONDS_PER_YEAR = 365 * 24 * 3600
TRADEABLE_LO, TRADEABLE_HI = 5, 95   # only "decide" where a real two-sided quote existed
FEE_BUFFER = config.FEE_BUFFER_CENTS


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _yf_history(symbol: str) -> pd.DataFrame:
    df = yf.Ticker(symbol).history(period="2y", auto_adjust=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _yf_intraday(symbol: str) -> pd.DataFrame:
    """5-minute bars, ~60 days back, indexed in UTC. Gives the spot the agent
    would actually have seen at an intraday decision time."""
    df = yf.Ticker(symbol).history(period="60d", interval="5m", auto_adjust=True)
    if df.empty:
        return df
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_convert("UTC") if idx.tz is not None else idx.tz_localize("UTC")
    return df


def _spot_and_vol(daily: pd.DataFrame, intraday: pd.DataFrame, decision_dt: datetime):
    """Spot = last intraday bar strictly before the decision timestamp (no
    lookahead); vol = trailing VOL_WINDOW daily log-returns. Returns (None, None)
    if no intraday bar exists before the decision (market older than the 60d
    intraday window) so we skip rather than fall back to a stale daily close."""
    cutoff = pd.Timestamp(decision_dt.date())
    prior = daily.loc[daily.index < cutoff, "Close"].dropna()
    if len(prior) < 30:
        return None, None
    sigma = _annual_vol(prior.iloc[-VOL_WINDOW:])
    dts = pd.Timestamp(decision_dt).tz_convert("UTC")
    bars = intraday.loc[intraday.index < dts, "Close"].dropna() if not intraday.empty else []
    if len(bars) == 0:
        return None, None
    return float(bars.iloc[-1]), sigma


def _decision_quote(candles: list[dict]):
    """First candle whose yes_ask close is genuinely tradeable. Returns
    (decision_ts, yes_ask_cents, no_ask_cents)."""
    for c in candles:
        ya = c.get("yes_ask", {}).get("close_dollars")
        yb = c.get("yes_bid", {}).get("close_dollars")
        if ya is None or yb is None:
            continue
        yes_ask = round(float(ya) * 100)
        yes_bid = round(float(yb) * 100)
        if TRADEABLE_LO <= yes_ask <= TRADEABLE_HI and yes_bid < yes_ask:
            no_ask = 100 - yes_bid
            return c["end_period_ts"], yes_ask, no_ask
    return None, None, None


def backtest_market(client: KalshiClient, m: dict, daily: pd.DataFrame,
                    intraday: pd.DataFrame) -> dict | None:
    stype = m.get("strike_type")
    if stype not in ("greater", "less"):
        return None                                   # skip range/other for now
    strike = m.get("floor_strike") if stype == "greater" else m.get("floor_strike")
    if strike is None:
        return None
    open_ts, close_ts = _ts(m["open_time"]), _ts(m["close_time"])
    result = m.get("result")
    if result not in ("yes", "no"):
        return None

    candles = client.get_candlesticks(m["series_ticker"], m["ticker"],
                                      open_ts, close_ts, 1)
    dec_ts, yes_ask, no_ask = _decision_quote(candles)
    if dec_ts is None:
        return None

    decision_dt = datetime.fromtimestamp(dec_ts, tz=timezone.utc)
    s0, sigma = _spot_and_vol(daily, intraday, decision_dt)
    if s0 is None:
        return None
    t = max(close_ts - dec_ts, 0) / SECONDS_PER_YEAR
    p_above = _p_above(s0, strike, sigma, t)
    p_yes = p_above if stype == "greater" else 1 - p_above

    realized_yes = 1 if result == "yes" else 0
    edge_yes = p_yes * 100 - yes_ask
    edge_no = (1 - p_yes) * 100 - no_ask

    # pick the side with the larger positive edge over the fee buffer
    side, edge, entry = None, max(edge_yes, edge_no), None
    if edge_yes >= edge_no and edge_yes > FEE_BUFFER:
        side, edge, entry = "yes", edge_yes, yes_ask
    elif edge_no > edge_yes and edge_no > FEE_BUFFER:
        side, edge, entry = "no", edge_no, no_ask

    pnl = None
    if side == "yes":
        pnl = (100 - entry) if realized_yes else -entry
    elif side == "no":
        pnl = (100 - entry) if not realized_yes else -entry

    return {
        "ticker": m["ticker"], "stype": stype, "strike": strike,
        "p_yes": round(p_yes, 4), "yes_ask": yes_ask, "no_ask": no_ask,
        "result": result, "realized_yes": realized_yes,
        "edge": round(edge, 2), "traded": side is not None,
        "side": side, "entry": entry, "pnl": pnl,
        "horizon_h": round((close_ts - dec_ts) / 3600, 2),
    }


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"evaluated": 0}
    ps = np.array([r["p_yes"] for r in rows])
    ys = np.array([r["realized_yes"] for r in rows])
    brier = float(np.mean((ps - ys) ** 2))
    base = float(ys.mean())
    brier_base = float(np.mean((base - ys) ** 2))
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0001]
    buckets = []
    for lo, hi in zip(edges, edges[1:]):
        mask = (ps >= lo) & (ps < hi)
        if mask.sum() == 0:
            continue
        buckets.append({"bucket": f"{lo:.1f}-{min(hi,1.0):.1f}", "n": int(mask.sum()),
                        "pred": round(float(ps[mask].mean()), 3),
                        "realized": round(float(ys[mask].mean()), 3)})
    traded = [r for r in rows if r["traded"]]
    wins = [r for r in traded if r["pnl"] > 0]
    total_pnl = sum(r["pnl"] for r in traded)
    total_cost = sum(r["entry"] for r in traded)
    return {
        "evaluated": len(rows),
        "model": {"brier": round(brier, 4), "brier_baseline": round(brier_base, 4),
                  "skill_vs_baseline": round(1 - brier / brier_base, 4) if brier_base else None,
                  "base_rate_yes": round(base, 4), "calibration": buckets},
        "trading": {
            "trades": len(traded),
            "hit_rate": round(len(wins) / len(traded), 4) if traded else None,
            "total_pnl_cents": round(total_pnl, 1),
            "total_cost_cents": round(total_cost, 1),
            "roi_pct": round(100 * total_pnl / total_cost, 2) if total_cost else None,
            "avg_edge_cents": round(float(np.mean([r["edge"] for r in traded])), 2) if traded else None,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest vs real settled Kalshi markets")
    ap.add_argument("--series", default="KXBTCD,KXINXU,KXETHD",
                    help="comma-separated Kalshi series tickers")
    ap.add_argument("--per-series", type=int, default=150,
                    help="most-recent settled markets to test per series")
    ap.add_argument("--show", type=int, default=0, help="print N sample trade rows")
    args = ap.parse_args(argv)

    client = KalshiClient()
    all_rows, per_series = [], {}
    for st in args.series.split(","):
        sym = config.resolve_yf_symbol(st)
        if not sym:
            print(f"# {st}: no yfinance mapping, skipping", flush=True)
            continue
        hist = _yf_history(sym)
        intraday = _yf_intraday(sym)
        settled = client.get_settled_markets(st, max_pages=3)
        settled = [m for m in settled if m.get("status") in ("settled", "finalized")]
        # mirror the live agent: only liquid markets, most-traded first
        settled = [m for m in settled if (_num(m.get("volume_fp")) or 0) > 0]
        settled.sort(key=lambda m: _num(m.get("volume_fp")) or 0, reverse=True)
        settled = settled[: args.per_series]
        rows = []
        for m in settled:
            m.setdefault("series_ticker", st)
            try:
                r = backtest_market(client, m, hist, intraday)
            except Exception as exc:  # noqa: BLE001
                r = None
            if r:
                rows.append(r)
        per_series[st] = summarize(rows)
        per_series[st]["yf_symbol"] = sym
        per_series[st]["settled_seen"] = len(settled)
        all_rows.extend(rows)
        print(f"# {st} ({sym}): {len(settled)} settled, {len(rows)} with tradeable quote",
              flush=True)

    out = {"overall": summarize(all_rows), "per_series": per_series}
    if args.show:
        out["samples"] = all_rows[: args.show]
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
