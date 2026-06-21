"""Deterministic Take-Profit / Stop-Loss daemon. No AI.

For each open position: derive the average entry from cost basis, fetch the live
bid, and apply hardcoded rules:
  - Take Profit: current gain >= TP_FRACTION of max possible gain
  - Stop Loss:   current loss >= SL_FRACTION of cost basis
On a trigger it places an opposing limit-IOC sell at the current bid. Every
evaluation is logged to sells.jsonl via journal.

Usage:
  python sell_cron.py --once --dry-run     # evaluate once, place nothing
  python sell_cron.py                       # run forever, every CRON_INTERVAL min
"""

import argparse
import sys

import config
import journal
from kalshi import KalshiClient, normalize_market, position_count


def _cents_from_dollars(v) -> int | None:
    try:
        return round(float(v) * 100)
    except (TypeError, ValueError):
        return None


def _exposure_cents(pos: dict) -> int | None:
    if pos.get("market_exposure_dollars") is not None:
        return _cents_from_dollars(pos["market_exposure_dollars"])
    if pos.get("market_exposure") is not None:  # legacy integer cents
        return int(pos["market_exposure"])
    return None


def evaluate_position(client: KalshiClient, pos: dict) -> dict:
    """Return a decision record (logged) describing TP/SL action for one position."""
    ticker = pos.get("ticker")
    count = int(position_count(pos))
    if count == 0:
        return {"ticker": ticker, "action": "hold", "outcome": "hold",
                "reason": "no open contracts"}

    side = "yes" if count > 0 else "no"
    exposure = _exposure_cents(pos)
    if not exposure:
        return {"ticker": ticker, "action": "hold", "outcome": "hold",
                "reason": "no cost basis"}
    entry = exposure / abs(count)  # average entry in cents

    nm = normalize_market(client.get_market(ticker).get("market", {}))
    bid = nm["yes_bid"] if side == "yes" else nm["no_bid"]
    if bid is None:
        return {"ticker": ticker, "action": "hold", "outcome": "hold",
                "reason": "no live bid"}

    gain = bid - entry                       # per-contract, cents
    max_gain = 100 - entry
    tp = gain >= config.TP_FRACTION * max_gain
    sl = (entry - bid) >= config.SL_FRACTION * entry

    action = "TP" if tp else ("SL" if sl else "hold")
    record = {
        "ticker": ticker, "side": side, "count": abs(count),
        "entry_cents": round(entry, 2), "exit_cents": bid,
        "pnl_cents": round(gain * abs(count), 2),
        "pnl_pct": round(gain / entry * 100, 2) if entry else None,
        "action": action,
        "outcome": "gain" if gain > 0 else ("loss" if gain < 0 else "hold"),
    }
    if config.DRY_RUN or client.dry_run:
        record["dry_run"] = True

    if action in ("TP", "SL"):
        resp = client.create_order(ticker, action="sell", side=side,
                                   count=abs(count), price_cents=bid)
        record["order"] = resp
    return record


def run_once(client: KalshiClient) -> list[dict]:
    # Only manage the agent's financial positions. Any non-finance bet sharing
    # the account (e.g. sports placed by hand) is skipped so this never auto-sells
    # something the agent did not buy.
    raw = client.get_positions().get("market_positions", [])
    positions = client.financial_positions(raw)
    skipped = len(raw) - len(positions)
    results = []
    for pos in positions:
        rec = evaluate_position(client, pos)
        journal.log_sell(rec)
        results.append(rec)
        flag = "[dry-run] " if rec.get("dry_run") else ""
        print(f"{flag}{rec['ticker']}: {rec['action']} "
              f"(entry {rec.get('entry_cents')}c, bid {rec.get('exit_cents')}c, "
              f"pnl {rec.get('pnl_cents')}c)")
    if skipped:
        print(f"(skipped {skipped} non-finance/flat position(s))")
    if not results:
        print("no open financial positions")
    return results


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="TP/SL sell daemon")
    p.add_argument("--once", action="store_true", help="evaluate once and exit")
    p.add_argument("--dry-run", action="store_true", help="place nothing")
    p.add_argument("--use-fixtures", action="store_true")
    p.add_argument("--interval", type=int, default=config.CRON_INTERVAL_MINUTES,
                   help="minutes between checks (daemon mode)")
    args = p.parse_args(argv)

    client = KalshiClient(dry_run=args.dry_run or None, use_fixtures=args.use_fixtures)

    if args.once:
        run_once(client)
        return 0

    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="US/Eastern")
    # every `interval` minutes during US market hours (9:30-16:00 ET, Mon-Fri)
    sched.add_job(lambda: run_once(client), "cron", day_of_week="mon-fri",
                  hour="9-16", minute=f"*/{args.interval}")
    print(f"sell_cron started: every {args.interval}min, 9-16 ET, Mon-Fri "
          f"(dry_run={client.dry_run})", file=sys.stderr)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
