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
- `.venv/bin/python kalshi.py financial-markets` → normalized, tradeable, volume-sorted markets, each tagged with a routing `category` and `yf_symbol`. Default = mappable index/crypto series. Add `--all` to scan every financial series (IPO/macro/single-stock/rates — heavy, many calls), `--series A,B` for specific series, or `--category <name>` to filter to one bucket.
- Take the top candidates by volume (liquidity = realistic fills). Analyzing ~15-30 is plenty; you only have `slots` to fill. Spread across categories so you are not all-in on one underlying.

## Step 4 — Per-market analysis (classify, then route)
Each market already carries a `category` (from `config.classify_market`). Route tools by it. **Only the first three categories have a quantitative anchor (a `yf_symbol` + a price strike); the rest are news-reasoning only and cannot be backtested — treat their estimates as lower-confidence.**

| `category` | Quant anchor? | Tools to run |
|---|---|---|
| `crypto` | yes (`yf_symbol`) | probability + technical + news |
| `index` | yes (`yf_symbol`) | probability + technical + news |
| `single_stock` | yes, **if** it's a real security | **confirm the underlying first** → probability + technical + **fundamentals** + news; if it's a numeric event (e.g. launch counts), drop to news only |
| `ipo` | no | news only (filings, S-1 chatter, exchange notices) |
| `macro` (CPI, Fed, jobs, GDP) | no | news only — consensus/forecasts |
| `rates_fx` | no | news only |
| `other` | no | news only |

- **`single_stock` is a coarse bucket:** a numeric strike on a non-index/crypto series is *usually* a company price market but sometimes a numeric event. Confirm what the underlying is and infer its yfinance symbol from the title before trusting probability/fundamentals; if it isn't a tradeable security, treat as news-only.
- **Resolve the yfinance symbol:** use the market's `yf_symbol` field when present (index/crypto). For single stocks, infer the symbol from the title. For `ipo`/`macro`/`rates_fx`/`other` there is no symbol — reason from news only.
- **Model edge is necessary but NOT sufficient (backtest finding):** on pure price markets the lognormal model is well-calibrated but has **no tradeable edge over Kalshi's order book** — model-vs-market disagreements are mostly model error (adverse selection), so trading the raw model gap loses money. Only take a price-market bet when a *news catalyst* justifies an edge the market hasn't priced; treat `model_p` as a sanity check, not a signal on its own.
- **Strike & expiry:** the normalized market gives `floor_strike`, `cap_strike`, `strike_type`, and `close_time`. Threshold markets have one strike (use `--strike` + `--dir above/below` per `strike_type`); range markets have both (use `--floor` + `--cap`).
- Run the routed tools:
  - `.venv/bin/python probability.py --ticker <yf> --strike <K> --dir above --expiry <YYYY-MM-DD>` (or `--floor/--cap` for ranges) → `model_p` anchor. Uses the latest **intraday** spot (check `spot_source`). For same-day markets `days_to_expiry=0` collapses the model to "is spot already past the strike," so lean on technicals/news for the actual call.
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
