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
- `.venv/bin/python kalshi.py positions --financial-only` → `count` = open **financial** positions. **Always use `--financial-only`.** The account may also hold sports or other non-finance bets; those are this agent's responsibility neither to count nor to touch, and `--financial-only` excludes them so they never eat into your slot budget. (Plain `kalshi.py positions` shows everything, for reference only.)
- Compute slot cap from bankroll: `slot_cap = min(40, max(10, bankroll_dollars // 250))`. The $250 divisor is a rough average position size — actual bets are sized by half-Kelly and will vary widely (a high-edge trade gets much more than a marginal one). The formula just sets a diversification ceiling. Examples: $2.5k → 10 slots, $5k → 20, $10k → 40, $20k+ → still 40 (half-Kelly naturally sizes up each bet as bankroll grows).
- `slots = slot_cap - financial_open_positions`. If `slots <= 0`, stop and report "at position cap". (Only finance positions count: e.g. with a 10-slot cap, 2 finance + 7 sports open = 8 slots free, not 1.)
- **Slots are a ceiling, not a target.** If only 6 markets have genuine edge today, place 6 trades. Never scrape weak opportunities to fill unused slots — scan again tomorrow.

## Step 3 — Candidate markets
- **Always run `--all`** to scan the full universe. `--all` spans every Kalshi category in `config.SCAN_CATEGORIES` — **financials, crypto, commodities, economics, science/technology** — covering IPO, earnings, macro, single-stock, rates, FX, crypto (incl. daily BTC/ETH), index, commodities (oil/gas/metals), and tech events (AI model races, GPU prices, product launches). This is heavy (~3 min, many API calls); use `--series A,B` or `--category <name>` to narrow only when a specific theme was requested.
- **Finance only — skip curiosities.** Kalshi cross-files non-finance markets into these categories (aliens, math prizes, disease/pandemic counts, moon landings, foreign politics, sports/entertainment). `config.is_finance_relevant` already drops the obvious ones from the scan, but if any survive, **do not trade them** — the user only wants finance-related bets (price moves, rates, earnings, M&A, IPOs, company/AI-industry outcomes with a financial read). If a market's resolution has no financial meaning, skip it regardless of edge.
- Take the top candidates by volume (liquidity = realistic fills). Analyzing ~15-30 is plenty; you only have `slots` to fill.
- **Diversify across underlyings and categories.** A portfolio of 20 all-in on BTC is not 20 bets — it is one bet repeated. Aim for at least 3 distinct categories in the final trade list.
- **Commodities** (oil/gas/metals) currently have **no yfinance mapping**, so they route as `rates_fx`/`single_stock` → news-only; treat them as lower-confidence event markets unless you confirm a symbol.

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
- Run ALL routed tools — do not skip any:
  - `.venv/bin/python probability.py --ticker <yf> --strike <K> --dir above --expiry <YYYY-MM-DD>` (or `--floor/--cap` for ranges) → `model_p` anchor. Uses the latest **intraday** spot (check `spot_source`). For same-day markets `days_to_expiry=0` collapses the model to "is spot already past the strike," so lean on technicals/news for the actual call.
  - `.venv/bin/python technical.py <yf>` — always run for any market with a `yf_symbol`. For earnings/operational markets, use as a sentiment check: stock falling while operational metrics are strong is a yellow flag worth explaining.
  - `.venv/bin/python fundamentals.py <yf>` — always run for single-stock and earnings markets. Revenue growth and margins directly inform whether operational thresholds (comp sales, margins) are likely to be met.
  - `.venv/bin/python news.py <yf or "free text"> --days 7` → news links.
  - **Run these in parallel** (multiple Bash calls in one message) to save time — but never skip one to go faster.
- **Read the news — no skipping:** use `WebFetch` on the most relevant links to read the actual articles. If `WebFetch` returns 400/403 (Google News RSS links commonly fail), immediately run `WebSearch` with a direct query to find the article on the publisher's site and fetch that URL instead. Do NOT cite a headline as a catalyst without having read the article body. Presenting unread headlines as evidence is worse than no evidence — it creates false confidence.

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
Skip anything with `edge_cents <= 5`. Rank the rest by edge; for the top `slots`:

**Correlation cap: at most 3 trades on the same underlying.** Group by `series_ticker` (for price markets) or by shared underlying concept (e.g., all "Anthropic IPO" markets, all BTC strikes). If the top-ranked list has more than 3 from the same group, drop the extras and fill those slots from the next-best edge in a different group. This prevents one thesis (BTC goes down, Claude loses the AI race) from consuming the whole portfolio.
- `.venv/bin/python sizing.py --p <p_yes> --ask <yes_ask> --balance <remaining_cents>` → `count`. Skip if `count == 0`.
- Decrement remaining balance by `count * yes_ask` so you don't over-deploy across the run.
- Place: `.venv/bin/python kalshi.py order --ticker <t> --action buy --side yes --count <count> --price <yes_ask>` (add `--dry-run` if dry).
- Update that market's logged decision row's `order` with `{count, entry_cents, client_order_id}` (re-log is fine).

## Step 7 — Report
Print a table of EVERY market evaluated: ticker | category | model_p | p_yes | yes_ask | edge | decision | count. Then a short summary: bets placed, total deployed, slots used, and your top reasoning highlights.
