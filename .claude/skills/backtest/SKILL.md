---
name: backtest
description: Backtest the quantitative core (probability model + edge filter + sizing) against real settled Kalshi markets. Runs backtest.py, which replays the model as-of each market's open using real intraday prices (no lookahead) and scores calibration + simulated P&L against real settlement. Interprets the JSON into findings. Use when the user says "backtest", "do backtest", "test the model on past trades", or "kalshi:backtest".
---

# Kalshi Backtest

Two separate pipelines depending on market type. Run both when doing a full backtest session.

**Run all Python via `.venv/bin/python` from the project root.**

## Coverage ceiling (read first)

The price model (Pipeline A) only works where there is a continuous tradeable
underlying with a yfinance price — that is **index + crypto only** (the series in
`config.SERIES_TO_YF`: ^GSPC, ^NDX, ^DJI, BTC-USD, ETH-USD).

Kalshi has ~1,000 "single-stock" markets, but they are **earnings/KPI events**
(production units, GMV, subscribers, comp-sales %), NOT share-price thresholds.
There is no "Will Apple close above $250" market. So single stocks are **not**
price-backtestable — they belong to Pipeline B (news). Do not try to map
single-stock series to yfinance symbols; the strike is a business metric.

So "backtest everything" on the price side = `--all-series` (index + crypto).
Everything else is Pipeline B, which is manual per-market.

## Data-integrity guard

`backtest.py` flags a series as `data_suspect` (and excludes it from the overall
aggregate) when its price feed looks broken: a **degenerate feed** (daily close
~flat over 30 days — a synthetic/geo-degraded source, common when running outside
the US), or a **scale mismatch** (spot wildly off the strikes). If you see
`data_warnings` in the output, the FEED is the problem, not the model — re-run
from a clean US data source. **Never write a `data_suspect` series' calibration
into lessons.md.** Note: a series that is genuinely bad on a *correct* feed (e.g.
Nasdaq) is NOT flagged — the guard catches broken data, not a weak model.

---

## Pipeline A — Price model backtest (`backtest.py`)

Validates the **deterministic lognormal core** on price-threshold markets
(BTC, ETH, S&P 500). Fully automated, no LLM judgment involved.

**Scope:** Only works for markets with a `yf_symbol` and a numeric price
strike. Cannot cover IPO / macro / AI-race / event markets — those have no
price formula. Treat results as a floor on the full pipeline.

### Step A1 — Run it
```
# the full mappable price universe (index + crypto), with the data guard on:
.venv/bin/python backtest.py --all-series --use-daily --per-series 150 --show 8

# or a specific subset:
.venv/bin/python backtest.py --series KXBTCD,KXETHD,KXINXU --use-daily --per-series 150
```
- `--all-series`: backtest EVERY series in `config.SERIES_TO_YF`. Series with no
  settled markets in-window just report 0 and are skipped.
- `--series`: comma-separated subset when you want specific underlyings.
- Pass `--use-daily` when any equity/index series is included (the same-day-close
  fallback covers decision times with no prior intraday bar).
- `--per-series N`: settled markets to test (default 150; effective cap ~90–120
  due to the 60-day intraday window — higher values add nothing).
- `--show N`: print N sample trade rows for side-by-side spot-checking.

**KXNASDAQ100U: genuinely bad — skip for trading.** Verified 2026-05-31 against a
CORRECT ^NDX feed (spot ~30,333 vs strikes ~30,270): Brier skill **−0.31**, hit
rate 44%, ROI −35% over 120 markets. This is a real model failure, not a data
artifact (the data guard did NOT flag it). Likely cause: NDX is concentrated in
~7 mega-cap tech names, so a single-day lognormal misprices its fatter, jumpier
tails. By contrast KXINXU (S&P) on the same run: skill **+0.41**, hit 67%, ROI
−1%. Trade S&P, not Nasdaq.

How it works: for each settled market, takes the first genuinely tradeable
Kalshi quote as the decision point, reads the spot from 5-min intraday bars
**strictly before** that timestamp (no lookahead), computes `model_p`, picks
the side with positive corrected edge over 5¢, and scores vs real settlement.

### Step A2 — Interpret the JSON
- **Check `data_warnings` FIRST.** Any series listed there is excluded from the
  overall aggregate and its numbers are untrustworthy — fix the feed, don't
  theorize about the model.
- **Calibration:** `brier` vs `brier_baseline`, `skill_vs_baseline` (>0 = beats
  guessing). Walk the calibration buckets — apply the per-asset corrections
  from `logs/lessons.md` (BTC/ETH have a severe S-curve distortion; S&P is
  nearly flat across 0.2–0.8; Nasdaq is below baseline — don't trade it).
- **Trading:** `trades`, `hit_rate`, `roi_pct`. A good Brier with negative ROI
  = model ranks well but has no edge over the order book (adverse selection).
- **Per-series:** check `spot_source_daily` / `spot_source_intraday` counts —
  `daily` rows used a same-day-close fallback and are slightly lower confidence.
  Flag series returning 0 tradeable markets.

### Step A3 — Caveats
- 60-day intraday window only; skews to current regime.
- `spot_source` is `"intraday"` when a 5-min bar exists before the decision
  timestamp, else `"daily"` (same-day-close fallback, only with `--use-daily`).
  In practice equity/index daily markets open after the 4pm close and usually get
  a real intraday bar — do not assume "S&P = daily".
- Running outside the US degrades the yfinance index feed; the data guard flags it.
- News/catalyst layer is untested here — price edge alone loses money.

---

## Pipeline B — News assessment backtest (`news_backtest.py`)

Validates the **news/event judgment layer** on IPO, macro, AI-race, and other
event markets. Uses a **fresh sub-agent** (no session context = no lookahead)
to estimate probability from pre-decision news only, then scores vs outcome.

**Why sub-agent, not inline:** a fresh agent inherits no current prices and no
outcome revealed in the main conversation, which removes the biggest leakage
source. It is *best-effort blind*, not guaranteed clean: the sub-agent still runs
on the real current date and WebSearch `before:`/`after:` operators are
unreliable, so some post-decision info can leak. Treat a single result as noisy;
trust the trend across many. For events before the Aug 2025 training cutoff,
training-data leakage is likely — flag or skip those.

**Model requirement: always use Sonnet or Opus for the sub-agent — never Haiku.**
News assessment requires critical reading, timeline reasoning, and calibrated
probability estimation. Haiku is not reliable enough for this task.

### Step B1 — Prepare the blind package
```
.venv/bin/python news_backtest.py \
  --ticker <KALSHI_TICKER> \
  --decision-date YYYY-MM-DD \
  --query "<news search terms>" \
  --days-before 21
```
This outputs `{"blind": {...}, "ground_truth": {...}}`.
- `blind` contains: market question, Kalshi price at decision date, pre-decision
  news headlines, and instructions for the sub-agent. **No outcome included.**
- `ground_truth` contains the actual resolution (withheld from sub-agent).
- Choose `--decision-date` at least 7 days before settlement so there's real
  uncertainty. Markets already at >90¢ or <10¢ are not interesting to assess.

### Step B2 — Spawn the sub-agent (Sonnet or Opus)
Spawn a fresh `Agent` with `model="sonnet"` or `model="opus"` and pass it
the `blind` section as the entire prompt context. Include this preamble:

> "You are making a Kalshi prediction market trading decision. Today's date
> is [decision_date]. You have no knowledge of events after this date.
> Use WebSearch to find news articles from BEFORE [decision_date] only.
> Based on what you find, output JSON: {p_yes, confidence, rationale}"

The sub-agent should use WebSearch with explicit date constraints in the query
(e.g., `"SpaceX IPO before:2026-04-15"`) to prevent fetching future news.

### Step B3 — Score
Once the market settles, run:
```
.venv/bin/python news_backtest.py --score \
  --ticker <TICKER> \
  --sub-agent-p <float> \
  --market-p <float> \
  --result yes|no
```
Key metric: `agent_beats_market` (True if sub-agent Brier < market Brier).
If the sub-agent consistently beats the market price, the news layer has real
edge. If it matches or loses, the market is already efficient — rely on price.

**Persistence:** a `--score` call WITH `--result` appends the row to
`logs/news_backtest.jsonl` automatically (pre-resolution calls without `--result`
are not logged). That file is the accumulating calibration record for Step B4 —
inspect with `cat logs/news_backtest.jsonl` or aggregate Brier across rows.

### Step B4 — Feed forward
Once `logs/news_backtest.jsonl` has 10+ scored rows, update `logs/lessons.md` with:
- Whether the sub-agent systematically over/under-estimates specific event types
  (IPO timing, earnings beats, AI race outcomes, product launches)
- Which news signals were most predictive
- Calibration vs the market price across event categories

---

## Step 4 — Report & feed forward (both pipelines)
Summarize: markets evaluated, calibration verdict, trading verdict, per-series
notes, caveats. If findings contradict or extend `logs/lessons.md`, update it
directly so `/invest` applies the lessons next run. Keep the two pipelines
distinct in the report — price calibration and news calibration are separate
feedback loops.
