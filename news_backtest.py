"""Blind news-assessment backtest for event markets (IPO, macro, AI race, etc.).

Prepares a BLIND PACKAGE — market question + Kalshi price + pre-decision news
headlines — with the actual resolution withheld. The calling agent spawns a
fresh sub-agent with the blind package and records its probability estimate.
That estimate is then scored against the real outcome.

Why sub-agent, not inline Claude:
  A fresh sub-agent has no current-session context, so it cannot see today's
  prices, today's news, or any outcome revealed during the main conversation.
  For 2026 events (after the Aug 2025 training cutoff), this gives a genuinely
  uncontaminated assessment. For events before Aug 2025, training-data leakage
  remains — flag those results clearly.

Usage:
  # Prepare a blind package (prints JSON; pipe to file or read inline)
  .venv/bin/python news_backtest.py \\
      --ticker KXIPOSPACEX-26JUL01 \\
      --decision-date 2026-05-01 \\
      --query "SpaceX IPO Starship" \\
      --days-before 21

  # Score a sub-agent estimate against ground truth
  .venv/bin/python news_backtest.py --score \\
      --ticker KXIPOSPACEX-26JUL01 \\
      --sub-agent-p 0.12 \\
      --market-p 0.98

Workflow (called from the Claude agent conversation):
  1. Run with --ticker + --decision-date + --query  → blind_package JSON
  2. Spawn a fresh sub-agent with the blind package as the only context
  3. Sub-agent returns: {"p_yes": float, "confidence": str, "rationale": str}
  4. Run with --score to compute calibration delta and log it
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from kalshi import KalshiClient, _num
from news import fetch as news_fetch


def _ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _get_market_price_near(client: KalshiClient, series: str, ticker: str,
                           decision_date: str) -> dict | None:
    """Return the Kalshi YES ask/bid closest to decision_date from candlesticks."""
    dec_dt = datetime.fromisoformat(decision_date).replace(tzinfo=timezone.utc)
    # fetch candles around the decision window (open=decision_date-1d, close=+1d)
    from datetime import timedelta
    open_ts = int((dec_dt - timedelta(days=1)).timestamp())
    close_ts = int((dec_dt + timedelta(days=1)).timestamp())
    try:
        candles = client.get_candlesticks(series, ticker, open_ts, close_ts, 60)
    except Exception:
        return None
    # find the candle closest to (but not after) decision_date
    target = int(dec_dt.timestamp())
    best = None
    for c in candles:
        ts = c.get("end_period_ts", 0)
        if ts <= target:
            ya = c.get("yes_ask", {}).get("close_dollars")
            yb = c.get("yes_bid", {}).get("close_dollars")
            if ya is not None:
                best = {
                    "ts": ts,
                    "yes_ask": round(float(ya) * 100),
                    "yes_bid": round(float(yb) * 100) if yb else None,
                }
    return best


def prepare(ticker: str, decision_date: str, query: str,
            days_before: int = 14) -> dict:
    """Build the blind package. Outcome is fetched but NOT included in output."""
    from datetime import timedelta
    client = KalshiClient()

    # find the market across all settled + active
    series = "-".join(ticker.split("-")[:1]) if "-" in ticker else ticker
    # try to derive series from ticker prefix
    parts = ticker.split("-")
    series = parts[0]

    market = None
    # try active market first via get_market
    try:
        resp = client.get_market(ticker)
        market = resp.get("market") if resp else None
    except Exception:
        pass
    # then search settled
    if market is None:
        try:
            settled = client.get_settled_markets(series, max_pages=2)
            market = next((m for m in settled if m.get("ticker") == ticker), None)
        except Exception:
            pass

    if market is None:
        return {"error": f"Market {ticker} not found"}

    result = market.get("result")  # ground truth — withheld from blind package
    title = market.get("title", ticker)
    subtitle = market.get("subtitle", "")
    close_time = market.get("close_time", "")
    yes_ask_at_decision = None

    price_info = _get_market_price_near(client, series, ticker, decision_date)
    if price_info:
        yes_ask_at_decision = price_info["yes_ask"]

    # fetch pre-decision news
    dec_dt = datetime.fromisoformat(decision_date).replace(tzinfo=timezone.utc)
    after_dt = dec_dt - timedelta(days=days_before)
    news = news_fetch(
        query, days=days_before, is_query=True,
        before=decision_date,
        after=after_dt.strftime("%Y-%m-%d"),
    )

    blind = {
        "blind_package": True,
        "ticker": ticker,
        "decision_date": decision_date,
        "market_question": title,
        "market_subtitle": subtitle,
        "market_closes": close_time,
        "yes_ask_at_decision": yes_ask_at_decision,
        "news_window": f"{after_dt.strftime('%Y-%m-%d')} to {decision_date}",
        "news_count": news["count"],
        "news_headlines": [
            {"title": lnk["title"], "published": lnk.get("published"),
             "url": lnk["url"]}
            for lnk in news["links"][:30]  # cap at 30 headlines
        ],
        "instructions": (
            "You are making a trading decision. Today's date is "
            f"{decision_date}. Based ONLY on the information above "
            "(market question, price, and news headlines from before today), "
            "estimate the probability that this market resolves YES. "
            "Do not use any knowledge of events after this date. "
            "Reply with JSON only: "
            '{\"p_yes\": <float 0-1>, \"confidence\": \"low|med|high\", '
            '\"rationale\": \"<one paragraph>\"}'
        ),
    }

    # ground truth stored separately for scoring — caller uses --score after
    ground_truth = {
        "ticker": ticker,
        "decision_date": decision_date,
        "result": result,
        "yes_ask_at_decision": yes_ask_at_decision,
        "market_p_yes": (yes_ask_at_decision / 100.0
                         if yes_ask_at_decision is not None else None),
    }

    return {"blind": blind, "ground_truth": ground_truth}


def score(ticker: str, sub_agent_p: float, market_p: float,
          result: str | None = None) -> dict:
    """Compute calibration for one sub-agent estimate."""
    realized = None if result is None else (1 if result == "yes" else 0)
    brier_agent = ((sub_agent_p - realized) ** 2) if realized is not None else None
    brier_market = ((market_p - realized) ** 2) if realized is not None else None
    return {
        "ticker": ticker,
        "sub_agent_p": sub_agent_p,
        "market_p": market_p,
        "result": result,
        "realized": realized,
        "brier_agent": round(brier_agent, 4) if brier_agent is not None else None,
        "brier_market": round(brier_market, 4) if brier_market is not None else None,
        "agent_beats_market": (brier_agent < brier_market
                               if brier_agent is not None and brier_market is not None
                               else None),
        "edge_vs_market": (round((sub_agent_p - market_p) * 100, 1)
                           if market_p is not None else None),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Blind news-assessment backtest")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--decision-date",
                    help="YYYY-MM-DD — the date the agent 'decides' (no lookahead past this)")
    ap.add_argument("--query", default="",
                    help="Free-text news search query (e.g. 'SpaceX IPO Starship')")
    ap.add_argument("--days-before", type=int, default=14,
                    help="How many days of news before decision-date to include")
    ap.add_argument("--score", action="store_true",
                    help="Score mode: provide --sub-agent-p and --market-p")
    ap.add_argument("--sub-agent-p", type=float,
                    help="Probability returned by the blind sub-agent")
    ap.add_argument("--market-p", type=float,
                    help="Market's implied probability at decision date (yes_ask/100)")
    ap.add_argument("--result",
                    help="Actual market result: yes or no (for scoring)")
    args = ap.parse_args(argv)

    if args.score:
        if args.sub_agent_p is None or args.market_p is None:
            print("--score requires --sub-agent-p and --market-p", file=sys.stderr)
            return 1
        out = score(args.ticker, args.sub_agent_p, args.market_p, args.result)
    else:
        if not args.decision_date:
            print("--decision-date required", file=sys.stderr)
            return 1
        out = prepare(args.ticker, args.decision_date, args.query, args.days_before)

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
