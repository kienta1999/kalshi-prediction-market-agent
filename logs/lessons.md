# Trading Lessons (curated by /self-improve)

This file is read by `/invest` at the start of every run and applied as guidance.
It is **rewritten** (not appended) by `/self-improve` from logged outcomes +
Kalshi settlement ground-truth. Keep it tight — only durable, evidence-backed
heuristics belong here.

> Source note: 4 backtest rounds, 163–172 markets per round, BTC/ETH daily,
> May 2026. ROI worsened round-over-round (−29% → −42%), consistent with
> adverse selection in a trending/volatile regime. Not yet from live trades.

## Calibration

Overall Brier 0.113 vs baseline 0.248, skill +0.54 — the model ranks well.
Calibration is severely non-uniform:

| model_p range | n  | model pred | realized YES | verdict |
|---|---|---|---|---|
| 0.0 – 0.2 | 43 | 0.09 | 0.00 | Slightly overconfident |
| 0.2 – 0.4 | 42 | 0.30 | **0.12** | **Severely overconfident — model is 2.5× too high** |
| 0.4 – 0.6 | 36 | 0.51 | **0.72** | **Severely underconfident — true p is +21 points higher** |
| 0.6 – 0.8 | 42 | 0.69 | **0.93** | **Severely underconfident — true p is +24 points higher** |
| 0.8 – 1.0 |  9 | 0.89 | 0.89 | Well calibrated |

**Corrected probabilities for price markets:**
- `model_p` in 0.2–0.4 → true p_yes ≈ **model_p × 0.4** (e.g., 0.30 → ~0.12)
- `model_p` in 0.4–0.6 → true p_yes ≈ **model_p + 0.22** (e.g., 0.50 → ~0.72)
- `model_p` in 0.6–0.8 → true p_yes ≈ **model_p + 0.24** (e.g., 0.69 → ~0.93)
- `model_p` outside these ranges → use with light adjustment only

## Directional filter — the most important rule

The calibration bias has a **directional consequence**: the model systematically
picks the **wrong side** in the 0.4–0.8 zone whenever it sees NO edge. Confirmed
across 20 sample trades:

- **Every NO bet where model_p was 0.4–0.8 resolved YES and lost** (samples at
  p=0.48, 0.54, 0.59 all lost; the market's true p_yes is 0.70–0.93 in that range).
- **YES bets where model_p was 0.4–0.6 won when they hit** (p=0.40→win, 0.50→win,
  0.51→win, 0.50→win) because true p_yes is actually ~0.72.
- **YES bets in 0.2–0.4 are a systematic trap** — lost 4 of 6, and the 2 wins were
  statistical luck against a true p_yes of only ~0.12.

**Apply this filter on every price-market bet:**

| model_p zone | Allowed side | Forbidden side |
|---|---|---|
| 0.2 – 0.4 | **NO only** | ~~YES~~ (true p_yes ~0.12, you're overpaying) |
| 0.4 – 0.8 | **YES only** | ~~NO~~ (true p_yes ~0.72–0.93, NO is negative EV) |
| 0.8 – 1.0 | Either | — (well calibrated) |
| 0.0 – 0.2 | NO preferred | YES only if ask is < 5¢ |

In practice: when the model sees raw edge for the *forbidden* side, skip the trade
entirely — the edge is an artifact of the calibration distortion, not real.

- Never anchor on a **daily close** for a sub-day market. Always confirm
  `probability.py` reports `spot_source: intraday`.

## Signal patterns

- **Model edge is necessary but NOT sufficient.** Raw model-vs-market gap trades
  lost money across all 4 rounds (ROI −29% to −42%, BTC worst at −49%). The
  Kalshi book is more efficient; largest "edges" are mostly model error. **Only
  take a price-market bet when a news catalyst justifies an edge the market hasn't
  priced.**
- The bigger the model/market disagreement with **no news to explain it**, the more
  likely the market is right. Skip it.
- ROI is worsening over rounds (−29% → −42%), consistent with the current BTC
  downtrend regime making near-ATM daily markets more coin-flip-like. Don't fight
  the trend with the model alone.

## Per-series notes

- **ETH > BTC.** ETH: Brier skill 0.589, ROI −33%. BTC: skill 0.487, ROI −49%.
  Both are negative — but ETH is less bad. When two similar opportunities exist,
  prefer ETH.
- **KXINXU (SPX daily) never produces tradeable quotes.** KXNDQDIRY has no
  yfinance mapping. For index exposure, use KXINXY year-end range markets and
  reason from technicals + news only.
- **Intraday data caps at ~90 markets per series** (~60 days back). `--per-series`
  above 100 adds nothing.

## Sizing / edge-filter

- **Apply the directional filter before sizing.** If model_p puts the trade on the
  forbidden side, skip regardless of edge size.
- Edge filter is **5¢ minimum** after directional correction. The corrected edge
  is: `(true_p_yes × 100) − ask`, where true_p_yes uses the corrections above.
- For price markets, require **a news catalyst** in addition to corrected positive
  edge. Raw model edge without catalyst has consistently lost money.
- IPO / macro / rates / event markets have no quant anchor — size conservatively,
  only on a clear news/consensus read.
