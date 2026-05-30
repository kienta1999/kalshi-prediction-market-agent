---
name: backtest
description: Backtest the quantitative core (probability model + edge filter + sizing) against real settled Kalshi markets. Runs backtest.py, which replays the model as-of each market's open using real intraday prices (no lookahead) and scores calibration + simulated P&L against real settlement. Interprets the JSON into findings. Use when the user says "backtest", "do backtest", "test the model on past trades", or "kalshi:backtest".
---

# Kalshi Backtest

You validate the **deterministic core** (probability model + edge filter + sizing)
against real settled Kalshi markets. **Run Python via `.venv/bin/python` from the
project root.**

**Scope — be honest about it up front.** This tests only the quant core on
**price-threshold** markets (index/crypto/single-stock with a `yf_symbol`). It does
**NOT** test Claude's news/technical judgment (that can't be backtested without
hindsight), and it cannot cover event markets (IPO/macro/rates) at all — those have
no price model. Treat results as a floor on the core, not the full pipeline.

## Step 1 — Run it
- Default: `.venv/bin/python backtest.py` → BTC/ETH/SPX daily series.
- Options: `--series KXBTCD,KXETHD,KXINXU` (Kalshi series tickers, must map to a
  yfinance symbol), `--per-series N` (most-traded settled markets to test, default
  150), `--show N` (print N sample trade rows for spot-checking).
- It needs live Kalshi reads (settled markets + candlesticks) and yfinance intraday
  data, so it must run with real API access (US), not `--use-fixtures`.

How it works (so you can explain/caveat correctly): for each settled market it
takes the first genuinely tradeable quote as the decision point, reads the spot
from 5-min intraday bars **strictly before** that timestamp (no lookahead),
computes `model_p`, picks the side with positive edge over the fee buffer, sizes it,
and scores P&L + calibration against the real YES/NO settlement.

## Step 2 — Interpret the JSON
Report, don't just dump. Pull out:
- **Calibration:** `brier` vs `brier_baseline` and `skill_vs_baseline` (>0 = beats
  guessing the base rate). Walk the `calibration` buckets — is `model` pred close to
  what `happened`? Note systematic over/under-confidence and in which range.
- **Trading:** `trades`, `hit_rate`, `total_pnl_cents`, `roi_pct`. **A good Brier
  with a negative ROI is the key signal** — it means the model ranks well but has no
  edge over the order book (adverse selection: the biggest model/market gaps are
  model error). Call that out explicitly when you see it.
- **Per-series:** which underlyings the model handles better (indices usually beat
  crypto). Flag any series with 0 tradeable markets (e.g. SPX hourly often finds
  none in-window).

## Step 3 — Caveats (always state these)
- Sample size and that markets are the most recent (intraday data only goes ~60 days
  back), so it skews to current regime.
- Confirm `spot_source` is intraday — a stale daily close silently wrecks short-
  horizon probabilities.
- The news/catalyst layer is untested; a price-only edge is necessary but not
  sufficient (see `logs/lessons.md`).

## Step 4 — Report & optionally feed forward
Summarize: markets evaluated, calibration verdict, trading verdict, per-series
notes, caveats. If the findings are durable and contradict or extend
`logs/lessons.md`, offer to run **`/self-improve`** (or update lessons directly) so
`/invest` applies them. Backtest = validate the model on real markets; self-improve
= learn from actually-logged live trades. Keep them distinct.
