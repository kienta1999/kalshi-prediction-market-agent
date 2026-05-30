"""Model-implied probability that a price finishes above/below/between strikes.

Treats a price-threshold market as an option: under a lognormal random walk with
~zero drift over a short horizon, P(S_T > K) = N(d2). Gives the invest skill a
quantitative anchor to compare against the market price; news/technicals adjust
around it.

Usage:
  python probability.py --ticker ^GSPC --strike 6000 --dir above --expiry 2026-06-05
  python probability.py --ticker ^GSPC --floor 5800 --cap 6000 --expiry 2026-06-05
"""

import argparse
import json
import math
from datetime import date, datetime

import numpy as np
import yfinance as yf

TRADING_DAYS = 252


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _annual_vol(close) -> float:
    log_ret = np.log(close / close.shift(1)).dropna()
    return float(log_ret.std() * math.sqrt(TRADING_DAYS))


def _years_to_expiry(expiry: str):
    exp = datetime.fromisoformat(expiry).date()
    days = (exp - date.today()).days
    return max(days, 0) / 365.0, days


def _p_above(s0: float, k: float, sigma: float, t: float) -> float:
    if t <= 0:
        return 1.0 if s0 > k else 0.0
    if sigma <= 0:
        return 1.0 if s0 > k else 0.0
    d2 = (math.log(s0 / k) - 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    return _norm_cdf(d2)


def compute(ticker: str, expiry: str, strike: float | None = None,
            direction: str = "above", floor: float | None = None,
            cap: float | None = None, period: str = "1y") -> dict:
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if df.empty or len(df) < 30:
        return {"ticker": ticker, "error": "insufficient price history"}
    close = df["Close"]
    s0 = float(close.iloc[-1])
    sigma = _annual_vol(close)
    t, days = _years_to_expiry(expiry)

    out = {
        "ticker": ticker, "spot": round(s0, 4), "annual_vol": round(sigma, 4),
        "days_to_expiry": days, "expiry": expiry,
    }
    if floor is not None and cap is not None:  # range market
        p = _p_above(s0, floor, sigma, t) - _p_above(s0, cap, sigma, t)
        out.update({"model": "between", "floor": floor, "cap": cap,
                    "model_p": round(max(0.0, min(1.0, p)), 4)})
    else:
        if strike is None:
            return {"ticker": ticker, "error": "provide --strike or --floor/--cap"}
        p_above = _p_above(s0, strike, sigma, t)
        p = p_above if direction == "above" else 1 - p_above
        out.update({"model": direction, "strike": strike,
                    "model_p": round(p, 4)})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Lognormal threshold probability (JSON)")
    p.add_argument("--ticker", required=True)
    p.add_argument("--expiry", required=True, help="YYYY-MM-DD or ISO datetime")
    p.add_argument("--strike", type=float, default=None)
    p.add_argument("--dir", dest="direction", choices=["above", "below"], default="above")
    p.add_argument("--floor", type=float, default=None)
    p.add_argument("--cap", type=float, default=None)
    p.add_argument("--period", default="1y")
    args = p.parse_args(argv)
    # normalize ISO datetime down to date string for parsing
    expiry = args.expiry[:10]
    try:
        out = compute(args.ticker, expiry, strike=args.strike, direction=args.direction,
                      floor=args.floor, cap=args.cap, period=args.period)
    except Exception as exc:  # noqa: BLE001
        out = {"ticker": args.ticker, "error": str(exc)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
