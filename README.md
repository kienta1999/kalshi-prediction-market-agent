# kalshi-prediction-market-agent

An edge-based trading agent for [Kalshi financial markets](https://kalshi.com/category/financials).
Claude is the reasoning engine (via Claude Code skills); the Python modules are thin,
single-purpose data tools that print JSON. Order sizing and exits are deterministic helpers
— no LLM judgment in the money-moving paths beyond the documented decision points.

## How it works

Four flows:

| Flow                | Trigger                        | Engine      | What it does                                                                                                                                                                                                                    |
| ------------------- | ------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`/invest`**       | manual (Claude Code skill)     | Claude      | Finds open financial markets, classifies each into a routing category, pulls technical/fundamental/news/probability signals, estimates true probability, bets where the estimate beats the price _and_ a catalyst justifies it. |
| **Sell (TP/SL)**    | cron, every 2h in market hours | pure Python | Take-profit / stop-loss on open positions. No AI.                                                                                                                                                                               |
| **`/self-improve`** | manual (Claude Code skill)     | Claude      | Joins decision + sell logs to Kalshi settlement ground-truth, checks calibration, rewrites `logs/lessons.md` (the playbook `/invest` reads each run). Learns from **actual logged trades**.                                     |
| **`/backtest`**     | manual (Claude Code skill)     | Claude      | Replays the quant core against **real settled markets** with real intraday prices, scores calibration + simulated P&L, and interprets the JSON. Validates the **model** (not the news layer).                                   |

`/invest` only _opens_ positions (up to a cap of 20 concurrent); the sell cron owns all exits.

### Key finding from backtesting

On real settled daily markets, the probability model is **well-calibrated** with an intraday
spot — **but trading the raw model-vs-market gap loses money**. Kalshi's order book is more
efficient than the model, so the biggest "edges" are mostly model error (adverse selection).
**A price-only edge is necessary but not sufficient; a real bet needs a news catalyst the
market hasn't priced.** Per-asset calibration differs sharply: **S&P (KXINXU) is the best
series** (skill +0.41), crypto is good-but-distorted (ETH > BTC), and **Nasdaq (KXNASDAQ100U)
is genuinely below baseline** (skill −0.31) — avoid trading it. All encoded in
`logs/lessons.md` and the `/invest` routing.

The price model only covers index + crypto (yfinance-mapped). Kalshi's ~1,000 "single-stock"
markets are earnings/KPI events (production, GMV, subscribers), **not** share-price thresholds,
so they aren't price-backtestable — they go through the news/event layer (`news_backtest.py`).

## Modules

| File              | Role                                                                                                                                                                                                                                                                                                                                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config.py`       | Parses the mixed-format credential file (regex for UUID + PEM block), exposes constants (`CAP=20`, `KELLY_FRACTION=0.5`, `MAX_TRADE_FRACTION=0.10`, `FEE_BUFFER_CENTS=3`, `TP_FRACTION=0.75`, `SL_FRACTION=0.40`, `CRON_INTERVAL_MINUTES=120`), the prefix-aware `SERIES_TO_YF` ticker map (`resolve_yf_symbol`), and `classify_market` (routes each market to crypto/index/single_stock/ipo/macro/rates_fx/other). |
| `kalshi.py`       | Signed REST client (RSA-PSS over `timestamp+method+path`) + CLI: `balance`, `positions`, `series`, `financial-markets` (tags each market with a `category` + `yf_symbol`; `--all` scans every financial series, `--category` filters one bucket), `market`, `settled`, `candlesticks`, `order`. Normalizes the modern `_dollars`/`_fp` fixed-point fields to integer cents.                                         |
| `technical.py`    | yfinance: RSI, MACD, ATR, MA50/MA200, Bollinger Bands.                                                                                                                                                                                                                                                                                                                                                              |
| `fundamentals.py` | yfinance: PE, PEG, debt/equity, free cash flow, EPS, revenue growth.                                                                                                                                                                                                                                                                                                                                                |
| `probability.py`  | Lognormal model-implied `P(close >/< strike)` = `N(d2)` from realized vol + days-to-expiry. Uses the latest **intraday** spot (falls back to daily close; reports `spot_source`), or an explicit `--spot`. Supports `--strike`+`--dir` (threshold) and `--floor`+`--cap` (range).                                                                                                                                   |
| `news.py`         | Returns links only (yfinance news + Google News RSS, deduped). Claude reads article bodies via WebFetch.                                                                                                                                                                                                                                                                                                            |
| `sizing.py`       | Half-Kelly → integer contract count, capped at 10% of bankroll per trade. A calculator, not a decision-maker.                                                                                                                                                                                                                                                                                                       |
| `paper_score.py`  | Scoreboard for the paper portfolios (`logs/*-paper.json`): joins every paper trade to Kalshi settlement, reports calibration (agent Brier vs market-implied Brier → `skill_vs_market`) and hypothetical P&L, overall / per-category / per-portfolio. `--write` fills the `actual_outcome`/`actual_p_yes` placeholders in the logs. Out-of-sample by construction.                                                   |
| `journal.py`      | Central JSONL logging: `log-decision` (every market evaluated, trade and skip), `log-sell` (every cron eval), plus `read_*` / `join_outcomes` helpers. Dry-run rows are excluded from learning.                                                                                                                                                                                                                     |
| `sell_cron.py`    | APScheduler daemon. TP: `(bid-entry) >= 0.75*(100-entry)`; SL: `(entry-bid) >= 0.40*entry`. Sells via an opposing limit-IOC order at the live bid.                                                                                                                                                                                                                                                                  |
| `backtest.py`     | Replays the probability model + edge filter + sizing against real settled Kalshi markets (real intraday prices via candlesticks, real outcomes). Tests the deterministic core only — not Claude's news judgment, which can't be backtested without hindsight.                                                                                                                                                       |

Skills live in `.claude/skills/invest/SKILL.md`, `.claude/skills/self-improve/SKILL.md`,
and `.claude/skills/backtest/SKILL.md`.

## Roadmap / next steps

The deterministic quant core is well-tested. The **news→bet judgment** is the part that
matters most and is hardest to test — and by nature, can only be tested out-of-sample: any
historical market the model "remembers" is contaminated, so the only honest measure is forward
calibration (log predictions now, score at settlement). `news_backtest.py` already gives an
uncontaminated single-ticker test (blind package → fresh sub-agent → score vs outcome) for
post-Aug-2025 events; the gaps below are about making that systematic.

Ranked by value:

1. ~~**Paper-log scoreboard** (`paper_score.py`)~~ — **done (2026-06-10)**: scores every
   `logs/*-paper.json` against settlement (calibration + hypothetical P&L, agent-vs-market
   Brier), fills the `actual_outcome`/`actual_p_yes` placeholders with `--write`, and is
   wired into `/self-improve` Step 1. As of 2026-06-10 all 17 paper trades are still pending
   (earliest resolutions Jun–Sep 2026) — rerun as they settle.
2. **Batch news-backtest runner** — loop `news_backtest.py` over settled 2026 event markets and
   aggregate Brier score / calibration, segmented by category (IPO timing vs earnings-comps vs
   AI-race). Ground truth grows as 2026 events resolve (SpaceX Jul 1, Chipotle Aug 21, MCD Sep 4…).
3. **Log-write validation** — schema-check the `/invest` paper/decision write path so a malformed
   portfolio can't be emitted silently (the kind of bug that orphaned half a paper log once).
4. **Sell-side testing** — `sell_cron.py` exit logic (TP/SL) is the least-tested module; no
   backtest of when to close vs hold.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Credentials (Kalshi API Key ID + RSA private key) go in `kalshi-prediction-market-agent.txt`
at the project root. **This file is gitignored and must never be committed.**

## Usage

Run every Python tool via the venv from the project root:

```bash
# Data tools (work anywhere — not geo-restricted)
.venv/bin/python technical.py AAPL
.venv/bin/python fundamentals.py AAPL
.venv/bin/python news.py AAPL --days 7
.venv/bin/python probability.py --ticker ^GSPC --strike 6000 --dir above --expiry 2026-06-30
.venv/bin/python sizing.py --p 0.65 --ask 50 --balance 100000   # -> 200 contracts

# Kalshi reads (verified working from this environment; order placement is US-only)
.venv/bin/python kalshi.py balance
.venv/bin/python kalshi.py financial-markets                 # mappable index/crypto series
.venv/bin/python kalshi.py financial-markets --all           # every financial series (heavy)
.venv/bin/python kalshi.py financial-markets --category ipo  # one routing bucket
.venv/bin/python kalshi.py settled --series KXBTCD
.venv/bin/python kalshi.py --dry-run order --ticker <T> --action buy --side yes --count 10 --price 47

# Score the paper portfolios against settlement (the news->bet scoreboard)
.venv/bin/python paper_score.py            # report only
.venv/bin/python paper_score.py --write    # also fill actual_outcome placeholders

# Backtest the quant core against real settled markets (real intraday prices, no lookahead)
.venv/bin/python backtest.py --all-series --use-daily --per-series 150   # full price universe (index+crypto)
.venv/bin/python backtest.py --series KXBTCD,KXETHD,KXINXU --use-daily   # a subset

# Backtest the NEWS/event layer (IPO/macro) via a blind sub-agent — see /backtest skill
.venv/bin/python news_backtest.py --ticker KXIPOSPACEX-26JUL01 --decision-date 2026-05-15 --query "SpaceX IPO"

# Sell daemon
.venv/bin/python sell_cron.py --once --dry-run   # evaluate, place nothing
.venv/bin/python sell_cron.py                     # run forever on schedule
```

In Claude Code: `/invest` to find and place bets, `/self-improve` to learn from settled
trades, `/backtest` to validate the model against real settled markets.

## Dry-run mode

Kalshi **reads** (balance, positions, markets, settled markets, candlesticks) are verified
working from outside the US; **order placement** is the geo-restricted path. Dry-run still lets
you exercise the whole flow without moving money — and works fully offline if reads are blocked:

- `--dry-run` (or `KALSHI_DRY_RUN=1`) on any CLI — order calls print the request body and return
  a simulated fill; nothing is POSTed.
- Reads fall back to `fixtures/` (or force with `--use-fixtures`), so the whole `/invest` chain
  is exercisable offline.
- yfinance / news / probability are not geo-restricted, so the analysis is genuine — only the
  Kalshi account/order layer is simulated.
- Dry-run rows are tagged `dry_run: true` and ignored by `/self-improve`.

## Going live (in the US)

1. `.venv/bin/python kalshi.py balance` — auth smoke test (proves signing/headers/base-URL).
2. `.venv/bin/python kalshi.py financial-markets` — real open markets.
3. `/invest` with `--dry-run` on orders — inspect the proposed bet table.
4. Drop `--dry-run`, place one small live bet, confirm the fill, then start `sell_cron.py`.

Initial session: claude --resume b060f89c-1079-4428-8bb8-da2238fe4f70
Improve backtest: claude --resume d47e670f-f08d-441a-a0df-a72a1e8ab6a6
Deploy first 50$: claude --resume 6f978d22-5558-4add-ae74-90fa43da190d
