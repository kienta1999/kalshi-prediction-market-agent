---
name: invest
description: Analyze Kalshi financial markets and place edge-based bets. Fetches open financial markets, classifies each, pulls technical/fundamental/news/probability signals, estimates true probability, finds markets where the estimate beats the price, sizes with half-Kelly, and places limit-IOC orders. Use when the user says "invest", "find bets", "trade Kalshi", or "kalshi:invest".
---

# Kalshi Invest

You are the reasoning engine for a Kalshi financial-markets trading agent. The Python files are thin data tools; YOU make every judgment (direction, probability, edge, trade/skip). Sizing and order placement are deterministic helpers.

**Run all Python via the project venv:** `.venv/bin/python <tool> ...` from the project root.

**Dry-run:** if the user asks for a dry-run (or you are outside the US / the live API is blocked), pass `--dry-run` to `kalshi.py` calls and add `"dry_run": true` to every logged decision. Nothing will be POSTed.

## Step 1 — Load lessons
Read `logs/lessons.md`. Apply its heuristics to every probability estimate and trade/skip decision below. If it says you were miscalibrated somewhere, adjust.

## Step 2 — Budget
- `.venv/bin/python kalshi.py balance` → bankroll (cents).
- `.venv/bin/python kalshi.py positions` → count open `market_positions`.
- `slots = 20 - open_positions`. If `slots <= 0`, stop and report "at position cap".

## Step 3 — Candidate markets
- `.venv/bin/python kalshi.py financial-markets` → normalized, tradeable, volume-sorted markets (default = mappable index/crypto series). Add `--all` to scan every financial series (heavy) or `--series A,B` to target specific ones.
- Take the top candidates by volume (liquidity = realistic fills). Analyzing ~15-30 is plenty; you only have `slots` to fill.

## Step 4 — Per-market analysis (classify, then route)
For each candidate, classify from `series_ticker` + `title`:

| Category | Tools to run |
|---|---|
| Index/stock threshold (short-dated) | probability + technical + news |
| Single-stock / earnings-horizon | probability + technical + **fundamentals** + news |
| Macro/econ (CPI, Fed, jobs, GDP) | news only |
| Crypto threshold | probability + technical + news |
| Rates/FX | news only |

- **Resolve the yfinance symbol:** the `financial-markets` output's `series_ticker` maps via the table in `config.py` (e.g. KXINXU→^GSPC, KXBTCD→BTC-USD). For single stocks, infer the symbol from the title. For macro markets there is no symbol — reason from news only.
- **Strike & expiry:** the normalized market gives `floor_strike`, `cap_strike`, `strike_type`, and `close_time`. Threshold markets have one strike (use `--strike` + `--dir above/below` per `strike_type`); range markets have both (use `--floor` + `--cap`).
- Run the routed tools:
  - `.venv/bin/python probability.py --ticker <yf> --strike <K> --dir above --expiry <YYYY-MM-DD>` (or `--floor/--cap` for ranges) → `model_p` anchor.
  - `.venv/bin/python technical.py <yf>`
  - `.venv/bin/python fundamentals.py <yf>` (only for single-stock/earnings)
  - `.venv/bin/python news.py <yf or "free text"> --days 7` → news links.
- **Read the news:** use the `WebFetch` tool on the most relevant links to read the actual articles. (Use Playwright MCP only if WebFetch fails on a page.)

## Step 5 — Estimate & decide
For each market produce: `p_yes` (your probability YES resolves true, 0-1), `confidence` (low/med/high), and a one-paragraph `rationale`.
- **Start from `model_p`** where available; adjust for momentum (technical), valuation/earnings (fundamentals), and catalysts (news). Explain any large drift from the model.
- For macro markets you have no model anchor — reason from consensus/forecasts in the news.
- Edge: `edge_cents = p_yes*100 - yes_ask`. (For a NO bet, mirror with `no_ask` and `1 - p_yes`.)

**Log every market** (trade AND skip):
```
.venv/bin/python journal.py log-decision --json '{"ticker":"...","series":"...","title":"...","category":"...","yes_ask":N,"yes_bid":N,"model_p":X,"p_yes":Y,"edge_cents":Z,"confidence":"...","decision":"trade|skip","rationale":"...","signals":{"rsi":..,"macd":..,"pe":..,"top_headlines":[...]},"dry_run":<true if dry>}'
```

## Step 6 — Size & place (top `slots` by edge)
Skip anything with `edge_cents <= 3` (fee buffer). Rank the rest by edge; for the top `slots`:
- `.venv/bin/python sizing.py --p <p_yes> --ask <yes_ask> --balance <remaining_cents>` → `count`. Skip if `count == 0`.
- Decrement remaining balance by `count * yes_ask` so you don't over-deploy across the run.
- Place: `.venv/bin/python kalshi.py order --ticker <t> --action buy --side yes --count <count> --price <yes_ask>` (add `--dry-run` if dry).
- Update that market's logged decision row's `order` with `{count, entry_cents, client_order_id}` (re-log is fine).

## Step 7 — Report
Print a table of EVERY market evaluated: ticker | category | model_p | p_yes | yes_ask | edge | decision | count. Then a short summary: bets placed, total deployed, slots used, and your top reasoning highlights.
