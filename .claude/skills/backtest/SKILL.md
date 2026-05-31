---
name: backtest
description: Backtest the quantitative core (probability model + edge filter + sizing) against real settled Kalshi markets. Runs backtest.py, which replays the model as-of each market's open using real intraday prices (no lookahead) and scores calibration + simulated P&L against real settlement. Interprets the JSON into findings. Use when the user says "backtest", "do backtest", "test the model on past trades", or "kalshi:backtest".
---

# Kalshi Backtest

Two separate pipelines depending on market type. Run both when doing a full backtest session.

**Run all Python via `.venv/bin/python` from the project root.**

---

## Pipeline A — Price model backtest (`backtest.py`)

Validates the **deterministic lognormal core** on price-threshold markets
(BTC, ETH, S&P 500). Fully automated, no LLM judgment involved.

**Scope:** Only works for markets with a `yf_symbol` and a numeric price
strike. Cannot cover IPO / macro / AI-race / event markets — those have no
price formula. Treat results as a floor on the full pipeline.

### Step A1 — Run it
```
.venv/bin/python backtest.py --series KXBTCD,KXETHD,KXINXU --use-daily --per-series 150 --show 8
```
- `--series`: comma-separated Kalshi series tickers with yfinance mappings.
  Default series: **KXBTCD, KXETHD, KXINXU** (BTC, ETH, S&P daily).
  Add `--use-daily` whenever KXINXU is in the list (equity series need it).
  **Skip KXNASDAQ100U** — Brier skill −0.13, worse than baseline with daily spot.
- `--per-series N`: settled markets to test (default 150; cap at ~90–105 due
  to 60-day intraday data window — higher values add nothing).
- `--show N`: print N sample trade rows for side-by-side spot-checking.

How it works: for each settled market, takes the first genuinely tradeable
Kalshi quote as the decision point, reads the spot from 5-min intraday bars
**strictly before** that timestamp (no lookahead), computes `model_p`, picks
the side with positive corrected edge over 5¢, and scores vs real settlement.

### Step A2 — Interpret the JSON
- **Calibration:** `brier` vs `brier_baseline`, `skill_vs_baseline` (>0 = beats
  guessing). Walk the calibration buckets — apply the per-asset corrections
  from `logs/lessons.md` (BTC/ETH have a severe S-curve distortion; S&P is
  nearly flat across 0.2–0.8).
- **Trading:** `trades`, `hit_rate`, `roi_pct`. A good Brier with negative ROI
  = model ranks well but has no edge over the order book (adverse selection).
- **Per-series:** check `spot_source` counts — flag any `daily` fallbacks as
  lower-confidence. Flag series returning 0 tradeable markets.

### Step A3 — Caveats
- 60-day intraday window only; skews to current regime.
- Confirm `spot_source: intraday` for crypto; S&P uses previous-day close
  tagged as `intraday` (market opens at 8pm ET, prior bars are within window).
- News/catalyst layer is untested here — price edge alone loses money.

---

## Pipeline B — News assessment backtest (`news_backtest.py`)

Validates the **news/event judgment layer** on IPO, macro, AI-race, and other
event markets. Uses a **fresh sub-agent** (no session context = no lookahead)
to estimate probability from pre-decision news only, then scores vs outcome.

**Why sub-agent, not inline:** a fresh agent inherits no current prices, no
today's news, and no outcome revealed in the main conversation. For 2026 events
(after the Aug 2025 training cutoff) this gives a genuinely uncontaminated read.
For events before Aug 2025, training-data leakage is possible — flag those.

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

### Step B4 — Feed forward
After 10+ scored assessments, update `logs/lessons.md` with:
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
