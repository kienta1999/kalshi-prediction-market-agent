"""Central JSONL logging for the agent's decisions and sells, plus read/join
helpers consumed by /self-improve. The invest skill and sell cron never
hand-roll the log format -- they go through here.

CLI (used by the invest skill):
  python journal.py log-decision --json '{...}'
  python journal.py log-sell --json '{...}'
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path, record: dict) -> None:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    record.setdefault("ts", _now())
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_decision(record: dict) -> None:
    _append(config.DECISIONS_LOG, record)


def log_sell(record: dict) -> None:
    _append(config.SELLS_LOG, record)


def _read_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def read_decisions(include_dry_run: bool = False) -> list[dict]:
    rows = _read_jsonl(config.DECISIONS_LOG)
    return rows if include_dry_run else [r for r in rows if not r.get("dry_run")]


def read_sells(include_dry_run: bool = False) -> list[dict]:
    rows = _read_jsonl(config.SELLS_LOG)
    return rows if include_dry_run else [r for r in rows if not r.get("dry_run")]


def join_outcomes(settlement: dict | None = None) -> list[dict]:
    """Join each traded decision to its exit (sells.jsonl) and, if provided, the
    market's settlement result. `settlement` maps ticker -> 'yes'|'no'.

    Returns rows the self-improve skill analyzes for calibration: predicted
    `p_yes` vs realized YES/NO, plus realized P&L from the exit.
    """
    sells_by_ticker: dict[str, dict] = {}
    for s in read_sells():
        sells_by_ticker.setdefault(s.get("ticker"), s)  # first exit wins

    settlement = settlement or {}
    joined = []
    for d in read_decisions():
        if d.get("decision") != "trade":
            continue
        ticker = d.get("ticker")
        sell = sells_by_ticker.get(ticker)
        result = settlement.get(ticker)
        joined.append({
            "ticker": ticker,
            "category": d.get("category"),
            "model_p": d.get("model_p"),
            "p_yes": d.get("p_yes"),
            "entry_cents": (d.get("order") or {}).get("entry_cents"),
            "exit_cents": (sell or {}).get("exit_cents"),
            "pnl_cents": (sell or {}).get("pnl_cents"),
            "exit_action": (sell or {}).get("action"),
            "settlement": result,                       # 'yes'|'no'|None
            "correct": (None if result is None
                        else (result == "yes") == (d.get("p_yes", 0) >= 0.5)),
        })
    return joined


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Append/read the agent trade journal")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("log-decision", "log-sell"):
        sp = sub.add_parser(name)
        sp.add_argument("--json", required=True, help="record as a JSON object")
    sub.add_parser("read-decisions")
    sub.add_parser("read-sells")
    args = p.parse_args(argv)

    if args.cmd in ("log-decision", "log-sell"):
        try:
            record = json.loads(args.json)
        except json.JSONDecodeError as exc:
            print(f"invalid --json: {exc}", file=sys.stderr)
            return 1
        (log_decision if args.cmd == "log-decision" else log_sell)(record)
        print(json.dumps({"ok": True, "logged": args.cmd}))
    elif args.cmd == "read-decisions":
        print(json.dumps(read_decisions(include_dry_run=True), indent=2, default=str))
    elif args.cmd == "read-sells":
        print(json.dumps(read_sells(include_dry_run=True), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
