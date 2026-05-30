"""Fundamental metrics for a ticker via yfinance. Prints JSON.

Only meaningful for single-stock / earnings-horizon equity markets; the invest
skill skips this for index, macro, crypto, and rates markets.

Usage: python fundamentals.py AAPL
"""

import argparse
import json


def _g(info: dict, *keys):
    for k in keys:
        v = info.get(k)
        if v is not None:
            return v
    return None


def compute(ticker: str) -> dict:
    import yfinance as yf

    info = yf.Ticker(ticker).info or {}
    if not info.get("symbol") and not info.get("shortName"):
        return {"ticker": ticker, "error": "no fundamental data (index/crypto/unknown?)"}
    return {
        "ticker": ticker,
        "name": _g(info, "shortName", "longName"),
        "sector": info.get("sector"),
        "market_cap": info.get("marketCap"),
        "pe_trailing": _g(info, "trailingPE"),
        "pe_forward": _g(info, "forwardPE"),
        "peg": _g(info, "trailingPegRatio", "pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "free_cash_flow": info.get("freeCashflow"),
        "operating_cash_flow": info.get("operatingCashflow"),
        "eps_trailing": info.get("trailingEps"),
        "eps_forward": info.get("forwardEps"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "return_on_equity": info.get("returnOnEquity"),
        "analyst_target_mean": info.get("targetMeanPrice"),
        "recommendation": info.get("recommendationKey"),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Fundamental metrics (JSON)")
    p.add_argument("ticker")
    args = p.parse_args(argv)
    try:
        out = compute(args.ticker)
    except Exception as exc:  # noqa: BLE001
        out = {"ticker": args.ticker, "error": str(exc)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
