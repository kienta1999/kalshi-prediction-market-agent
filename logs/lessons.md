# Trading Lessons (curated by /self-improve)

This file is read by `/invest` at the start of every run and applied as guidance.
It is **rewritten** (not appended) by `/self-improve` from logged outcomes +
Kalshi settlement ground-truth. Keep it tight — only durable, evidence-backed
heuristics belong here.

> Source note: lessons below come from two backtest rounds (163–166 markets,
> BTC/ETH daily, May 2026, `backtest.py`). Not yet from live trades — refresh
> from live outcomes once they accumulate.

## Calibration notes

Overall Brier 0.121 vs baseline 0.248, skill +0.51 — the model ranks well.
But **calibration is not uniform across the probability range**:

| model_p range | n  | model pred | realized YES | verdict |
|---|---|---|---|---|
| 0.0 – 0.2 | 42 | 0.08 | 0.00 | Slightly overconfident |
| 0.2 – 0.4 | 41 | 0.31 | **0.15** | **Severely overconfident — model is 2× too high** |
| 0.4 – 0.6 | 37 | 0.50 | **0.73** | **Severely underconfident — add ~23 points** |
| 0.6 – 0.8 | 38 | 0.69 | **0.92** | **Severely underconfident — add ~23 points** |
| 0.8 – 1.0 | 8  | 0.89 | 0.88 | Well calibrated |

**Practical adjustments when estimating p_yes for price markets:**
- `model_p` in **0.2–0.4**: treat true probability as roughly **half** the model value. A model edge buy at p_yes=0.30 with ask=20¢ is in reality a −5¢ losing trade.
- `model_p` in **0.4–0.8**: add **~20–25 points** to get closer to true probability. A model reading of 0.50 is more like 0.73 in practice.
- `model_p` below 0.2 or above 0.8: model is reasonably calibrated, use with light adjustment only.

**Never trust raw model-edge in the 0.2–0.4 range** — these are systematically losing bets regardless of what the edge calculation says.

- Never anchor on a **daily close** for a sub-day market. A day-old spot over a
  1-hour horizon is ~1.7σ of noise. Always confirm `probability.py` reports
  `spot_source: intraday`.

## Signal patterns

- **Model edge is necessary but NOT sufficient.** Trading the raw model-vs-market
  gap LOST money (ROI −29% overall, −39% on BTC, −16% on ETH) despite good
  calibration. The Kalshi book is more efficient than the model, so the largest
  "edges" are mostly model error (adverse selection). **Only take a price-market
  bet when a news catalyst justifies an edge the market hasn't priced** — treat
  `model_p` as a sanity check, not a standalone signal.
- The bigger the model/market disagreement with **no news to explain it**, the
  more likely the market is right and you are wrong. Skip it.

## Per-series notes

- **ETH > BTC for the quant core.** ETH: Brier skill 0.557, ROI −16%. BTC: Brier
  skill 0.451, ROI −39%. When two similar opportunities exist across both, prefer
  ETH.
- **KXINXU (SPX daily) never produces tradeable quotes** — out of the trading
  window every time. Skip it in backtests; use KXINXY (year-end range markets)
  instead for S&P exposure and reason from technicals + news only.
- **Intraday data caps at ~83 markets per series** (~60 days back). Running
  `--per-series` above 100 adds nothing. Default 150 is fine; the binding
  constraint is data availability, not the flag.

## Sizing / edge-filter adjustments

- **The 0.2–0.4 model_p zone is a trap.** Never size a bet whose raw `model_p`
  falls here without a strong independent catalyst — the calibration correction
  alone turns most of these into losing trades.
- For price markets, require **both** a positive edge **and** a catalyst before
  sizing; otherwise skip. This is the single most important rule.
- Edge filter is 5¢ (raised from 3¢). Tighter filter compensates for the
  calibration overconfidence in the 0.2–0.4 range.
- IPO / macro / rates / event markets have **no quant anchor** — size them
  conservatively (low confidence) and only on a clear news/consensus read.
