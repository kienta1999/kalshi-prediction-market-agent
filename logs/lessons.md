# Trading Lessons (curated by /self-improve)

This file is read by `/invest` at the start of every run and applied as guidance.
It is **rewritten** (not appended) by `/self-improve` from logged outcomes +
Kalshi settlement ground-truth. Keep it tight — only durable, evidence-backed
heuristics belong here.

> Source note: the lessons below come from a **backtest** of the deterministic
> core (probability model + edge filter + sizing) on ~160 real settled BTC/ETH
> daily markets with real intraday prices (2026-05, `backtest.py`), not yet from
> live trades. Refresh from live outcomes once they accumulate.

## Calibration notes
- With an **intraday** spot the lognormal model is well-calibrated (Brier 0.126 vs
  0.249 baseline, skill +0.49 over 159 markets). It is mildly **underconfident in
  the mid-range**: when it says 0.4–0.8, realized YES ran ~0.75–0.95. Nudge a
  middling `model_p` (0.4–0.8) on short-dated index/crypto a few points toward the
  decisive side rather than treating 0.5 as a coin flip.
- Never anchor on a **daily close** for a sub-day market. A day-old spot over a
  1-hour horizon is ~1.7σ of noise and produced ~4% probabilities for at-the-money
  strikes. Always confirm `probability.py` reports `spot_source: intraday`.

## Signal patterns
- **A model edge is necessary but NOT sufficient.** Trading the raw model-vs-market
  gap LOST money (ROI −15%, hit rate 17%) despite good calibration. The Kalshi book
  is more efficient than the model, so the largest "edges" are mostly model error
  (adverse selection). **Only take a price-market bet when a news catalyst justifies
  an edge the market hasn't priced** — treat `model_p` as a sanity check, not a
  standalone signal.
- The bigger the model/market disagreement with **no news to explain it**, the more
  likely the market is right and you are wrong. Skip it.

## Sizing / edge-filter adjustments
- A 3¢ edge buffer is far too loose for these markets — pure-model edges above it
  were net-negative. For price markets, require **both** a positive edge **and** a
  catalyst before sizing; otherwise skip.
- IPO / macro / rates / event markets have **no quant anchor and cannot be
  backtested** — size them conservatively (low confidence) and only on a clear
  news/consensus read.
