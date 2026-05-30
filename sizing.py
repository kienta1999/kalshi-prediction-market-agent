"""Half-Kelly position sizing -> integer contract count. Prints JSON.

This is a calculator, not a decision-maker. Claude decides direction, the
probability `p`, whether there is edge, and trade/skip. This module only turns
`p` + price + balance into a safe, capped, whole-contract count.

Usage: python sizing.py --p 0.65 --ask 50 --balance 100000   # balance in cents
"""

import argparse
import json

import config


def contract_count(p: float, ask_cents: int, bankroll_cents: int,
                   kelly: float = config.KELLY_FRACTION,
                   cap_frac: float = config.MAX_TRADE_FRACTION,
                   fee_buffer: int = config.FEE_BUFFER_CENTS) -> dict:
    ask = int(ask_cents)
    edge = p * 100 - ask  # fair value (cents) minus what we pay
    if not (1 <= ask <= 99):
        return {"count": 0, "reason": "ask out of range", "edge_cents": round(edge, 2)}
    if edge <= fee_buffer:
        return {"count": 0, "reason": "edge below fee buffer", "edge_cents": round(edge, 2)}
    f_star = edge / (100 - ask)              # full-Kelly fraction
    stake_frac = min(kelly * f_star, cap_frac)
    stake_cents = stake_frac * bankroll_cents
    count = int(stake_cents // ask)          # floor to whole contracts
    return {
        "count": count,
        "edge_cents": round(edge, 2),
        "kelly_fraction": round(f_star, 4),
        "stake_fraction": round(stake_frac, 4),
        "stake_cents": int(count * ask),
        "capped": stake_frac >= cap_frac,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Half-Kelly contract sizing (JSON)")
    p.add_argument("--p", type=float, required=True, help="Claude's P(yes), 0-1")
    p.add_argument("--ask", type=int, required=True, help="market ask in cents (1-99)")
    p.add_argument("--balance", type=int, required=True, help="bankroll in cents")
    p.add_argument("--kelly", type=float, default=config.KELLY_FRACTION)
    p.add_argument("--cap-frac", type=float, default=config.MAX_TRADE_FRACTION)
    args = p.parse_args(argv)
    out = contract_count(args.p, args.ask, args.balance,
                         kelly=args.kelly, cap_frac=args.cap_frac)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
