"""Score the accumulating paper portfolios (logs/*-paper.json) against Kalshi
settlement ground-truth.

For every trade in every paper log we fetch the market's settlement result,
then report calibration (the agent's p_yes vs realized YES/NO, Brier-scored
against the market-implied probability) and hypothetical P&L. This is the
scoreboard for the news->bet judgment that backtest.py cannot test: the
predictions were logged before the outcomes existed, so it is out-of-sample
by construction.

Usage:
  python paper_score.py                 # report (prints JSON)
  python paper_score.py --write         # also fill actual_outcome/actual_p_yes
                                        # placeholders in the paper logs
  python paper_score.py --use-fixtures  # offline (fixture settlement data)
"""

import argparse
import json
import sys
from pathlib import Path

import config
from kalshi import KalshiClient, KalshiError

SETTLE_CHUNK = 20  # tickers per get_settled call


def load_paper_files(logs_dir: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(logs_dir.glob("*-paper.json")):
        try:
            out.append((path, json.loads(path.read_text())))
        except json.JSONDecodeError as exc:
            print(f"skipping malformed {path.name}: {exc}", file=sys.stderr)
    return out


def fetch_settlement(client: KalshiClient, tickers: list[str]) -> dict[str, str]:
    """ticker -> 'yes'|'no' for markets that have settled. Absent = pending."""
    results: dict[str, str] = {}
    for i in range(0, len(tickers), SETTLE_CHUNK):
        chunk = tickers[i:i + SETTLE_CHUNK]
        try:
            page = client.get_settled(",".join(chunk))
        except KalshiError as exc:
            print(f"settlement fetch failed for {chunk[0]}..: {exc}", file=sys.stderr)
            continue
        for m in page.get("markets", []):
            if m.get("result") in ("yes", "no"):
                results[m["ticker"]] = m["result"]
    return results


def entry_cost_cents(trade: dict) -> int | None:
    """Cents paid per contract for the side actually bought."""
    if trade.get("side") == "yes":
        return trade.get("yes_ask")
    if trade.get("no_ask") is not None:
        return trade.get("no_ask")
    ya = trade.get("yes_ask")
    return None if ya is None else 100 - ya  # fallback: no quoted no_ask


def score_trade(trade: dict, result: str | None) -> dict:
    realized_yes = None if result is None else (1 if result == "yes" else 0)
    p_yes = trade.get("p_yes")
    yes_ask = trade.get("yes_ask")
    market_p = None if yes_ask is None else yes_ask / 100
    entry = entry_cost_cents(trade)
    count = trade.get("count") or 0

    row = {
        "ticker": trade.get("ticker"),
        "category": trade.get("category"),
        "side": trade.get("side"),
        "confidence": trade.get("confidence"),
        "p_yes": p_yes,
        "market_p_yes": market_p,
        "entry_cents": entry,
        "count": count,
        "stake_cents": trade.get("stake_cents"),
        "resolve_by": trade.get("resolve_by"),
        "result": result,
    }
    if realized_yes is None:
        row["status"] = "pending"
        return row

    row["status"] = "settled"
    row["won"] = result == trade.get("side")
    if p_yes is not None:
        row["brier"] = round((p_yes - realized_yes) ** 2, 4)
    if market_p is not None:
        row["market_brier"] = round((market_p - realized_yes) ** 2, 4)
    if entry is not None and count:
        row["pnl_cents"] = count * (100 - entry) if row["won"] else -count * entry
    return row


def summarize(rows: list[dict]) -> dict:
    settled = [r for r in rows if r["status"] == "settled"]
    scored = [r for r in settled if "brier" in r and "market_brier" in r]
    summary = {
        "n_trades": len(rows),
        "n_settled": len(settled),
        "n_pending": len(rows) - len(settled),
    }
    if not settled:
        return summary

    summary["n_won"] = sum(1 for r in settled if r.get("won"))
    summary["pnl_cents"] = sum(r.get("pnl_cents", 0) for r in settled)
    staked = sum(r.get("stake_cents") or 0 for r in settled)
    if staked:
        summary["roi_on_settled_stake"] = round(summary["pnl_cents"] / staked, 4)
    if scored:
        brier = sum(r["brier"] for r in scored) / len(scored)
        market = sum(r["market_brier"] for r in scored) / len(scored)
        summary["brier"] = round(brier, 4)
        summary["market_brier"] = round(market, 4)
        # positive skill = the agent's p_yes beats the market price as a forecast
        summary["skill_vs_market"] = round(market - brier, 4)
    return summary


def by_category(rows: list[dict]) -> dict:
    cats: dict[str, list[dict]] = {}
    for r in rows:
        cats.setdefault(r.get("category") or "unknown", []).append(r)
    return {c: summarize(rs) for c, rs in sorted(cats.items())}


def write_back(path: Path, doc: dict, settlement: dict[str, str]) -> int:
    """Fill actual_outcome/actual_p_yes placeholders for settled trades."""
    filled = 0
    for trade in doc.get("trades", []):
        result = settlement.get(trade.get("ticker"))
        if result and trade.get("actual_outcome") is None:
            trade["actual_outcome"] = result
            trade["actual_p_yes"] = 1.0 if result == "yes" else 0.0
            filled += 1
    if filled:
        path.write_text(json.dumps(doc, indent=2) + "\n")
    return filled


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Score paper portfolios vs Kalshi settlement")
    p.add_argument("--write", action="store_true",
                   help="fill actual_outcome/actual_p_yes in the paper logs")
    p.add_argument("--use-fixtures", action="store_true", help="offline fixture reads")
    p.add_argument("--dry-run", action="store_true", help="fixture fallback on read failure")
    args = p.parse_args(argv)

    files = load_paper_files(config.LOGS_DIR)
    if not files:
        print(json.dumps({"error": f"no *-paper.json files in {config.LOGS_DIR}"}))
        return 1

    tickers = sorted({t["ticker"] for _, doc in files
                      for t in doc.get("trades", []) if t.get("ticker")})
    client = KalshiClient(dry_run=args.dry_run or None, use_fixtures=args.use_fixtures)
    settlement = fetch_settlement(client, tickers)

    portfolios, all_rows = [], []
    for path, doc in files:
        rows = [score_trade(t, settlement.get(t.get("ticker")))
                for t in doc.get("trades", [])]
        all_rows.extend(rows)
        entry = {
            "file": path.name,
            "date": doc.get("date"),
            "bankroll_cents": doc.get("bankroll_cents"),
            "deployed_cents": doc.get("total_deployed_cents"),
            **summarize(rows),
        }
        if args.write:
            entry["placeholders_filled"] = write_back(path, doc, settlement)
        portfolios.append(entry)

    print(json.dumps({
        "summary": summarize(all_rows),
        "by_category": by_category(all_rows),
        "portfolios": portfolios,
        "trades": all_rows,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
