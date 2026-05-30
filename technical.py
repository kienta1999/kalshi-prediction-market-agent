"""Technical indicators for a ticker via yfinance. Prints JSON.

Usage: python technical.py AAPL [--period 6mo]
"""

import argparse
import json
import sys

import numpy as np
import yfinance as yf


def _rsi(close, period: int = 14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig


def _atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = np.maximum(high - low, np.maximum((high - prev_close).abs(),
                                           (low - prev_close).abs()))
    return tr.rolling(period).mean()


def _last(series):
    s = series.dropna()
    return None if s.empty else round(float(s.iloc[-1]), 4)


def compute(ticker: str, period: str = "1y") -> dict:
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if df.empty or len(df) < 30:
        return {"ticker": ticker, "error": "insufficient price history"}
    close, high, low = df["Close"], df["High"], df["Low"]
    macd, sig, hist = _macd(close)
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    price = _last(close)
    return {
        "ticker": ticker,
        "price": price,
        "rsi14": _last(_rsi(close)),
        "macd": _last(macd),
        "macd_signal": _last(sig),
        "macd_hist": _last(hist),
        "ma50": _last(ma50),
        "ma200": _last(ma200),
        "above_ma50": (price > _last(ma50)) if _last(ma50) else None,
        "above_ma200": (price > _last(ma200)) if _last(ma200) else None,
        "bollinger_upper": _last(bb_mid + 2 * bb_std),
        "bollinger_lower": _last(bb_mid - 2 * bb_std),
        "atr14": _last(_atr(high, low, close)),
        "pct_change_5d": round(float(close.pct_change(5).iloc[-1] * 100), 2)
        if len(close) > 5 else None,
        "pct_change_20d": round(float(close.pct_change(20).iloc[-1] * 100), 2)
        if len(close) > 20 else None,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Technical indicators (JSON)")
    p.add_argument("ticker")
    p.add_argument("--period", default="1y")
    args = p.parse_args(argv)
    try:
        out = compute(args.ticker, args.period)
    except Exception as exc:  # noqa: BLE001 - yfinance raises many things
        out = {"ticker": args.ticker, "error": str(exc)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
