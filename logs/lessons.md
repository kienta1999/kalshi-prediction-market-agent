# Trading Lessons (curated by /self-improve)

This file is read by `/invest` at the start of every run and applied as guidance.
It is **rewritten** (not appended) by `/self-improve` from logged outcomes +
Kalshi settlement ground-truth. Keep it tight — only durable, evidence-backed
heuristics belong here.

> Source note: 6 backtest rounds, all on KXBTCD + KXETHD (the only two series
> the backtest tool can evaluate). 9 other series were probed — all returned 0
> tradeable markets due to timing constraints, no settled history, or no
> yfinance mapping. These lessons apply specifically to short-dated BTC/ETH
> daily price-threshold markets. Not yet from live trades.

## Backtestable universe

Only **KXBTCD** (BTC-USD) and **KXETHD** (ETH-USD) produce enough settled
markets with intraday data for meaningful backtesting (~82–90 per round within
the 60-day intraday window). Every other series fails:
- Index/Nasdaq dailies (KXINXU, KXNASDAQ100U): S&P/NDX settlement at 4pm ET
  falls outside the usable yfinance 5-min intraday window.
- Year-end range markets (KXINXY, KXNASDAQ100Y): haven't settled yet.
- Comparison and BTC-vs-Gold markets: no settled history yet.
- KXNASDAQ100: 3 markets evaluated, all far-OTM (model_p < 0.02), no trades.

**Implication for /invest:** index and Nasdaq price markets have no backtested
calibration reference. Treat model_p for those as untested and require a
stronger news catalyst before acting.

## Calibration (BTC/ETH daily markets)

Overall Brier 0.113 vs baseline 0.248, skill +0.54. Severely non-uniform:

| model_p range | n  | model pred | realized YES | Corrected p_yes |
|---|---|---|---|---|
| 0.0 – 0.2 | 43 | 0.09 | 0.00 | model_p × 0.5 |
| 0.2 – 0.4 | 42 | 0.30 | **0.12** | **model_p × 0.4** |
| 0.4 – 0.6 | 36 | 0.51 | **0.72** | **model_p + 0.22** |
| 0.6 – 0.8 | 42 | 0.69 | **0.93** | **model_p + 0.24** |
| 0.8 – 1.0 |  9 | 0.89 | 0.89 | model_p (calibrated) |

**Always compute edge from corrected p_yes, never from raw model_p.**

## Directional filter — confirmed across 20 sample trades

The calibration distortion is directional. Raw model edge for the *wrong side*
is consistently negative real-edge:

- **Every NO bet where model_p was 0.4–0.8 lost** (resolved YES; true p_yes
  ~0.72–0.93). Samples: p=0.48 NO→lost 34¢, p=0.54 NO→lost 37¢, p=0.59 NO→lost 28¢.
- **YES bets where model_p was 0.4–0.6 won when they hit** (true p_yes ~0.72).
  Samples: p=0.40→+77¢, p=0.50→+74¢, p=0.51→+52¢.
- **YES bets in 0.2–0.4 at cheap asks (~8–17¢) have marginal positive corrected
  edge** (true p_yes ~0.12; edge = 12 − ask). At ask=8¢ edge is +4¢ (tight but
  real). At ask=17¢ edge is −5¢ (skip). Don't treat this as a blanket YES ban —
  use the corrected probability.

**Practical rule:**

| model_p | Corrected p_yes | Take YES if | Take NO if |
|---|---|---|---|
| 0.2–0.4 | model_p × 0.4 | yes_ask < corrected × 100 | no_ask < (1−corrected) × 100 |
| 0.4–0.8 | model_p + 0.22 | yes_ask < corrected × 100 | rarely — corrected p_no is ~8–28%, need no_ask < that |
| 0.8–1.0 | model_p | either side normally | either side normally |

In practice for 0.4–0.8: corrected p_yes is 0.72–0.93, so NO is only worth
buying if no_ask < 8–28¢. That's rare — most NO asks in this range are 30–60¢.
Skip NO bets in this zone almost always.

- Never anchor on a **daily close** for a sub-day market. Always confirm
  `probability.py` reports `spot_source: intraday`.

## Signal patterns

- **Model edge is necessary but NOT sufficient.** Raw model gap trades lost money
  across all 6 rounds (ROI −29% to −49%). **Only take a price-market bet when a
  news catalyst justifies the edge.** Corrected edge + catalyst = minimum bar.
- The bigger the model/market disagreement with **no news to explain it**, the more
  likely the market is right. Skip it.
- ROI worsened over rounds as BTC trended down. Downtrend regimes increase
  coin-flip noise on near-ATM daily markets — raise the edge threshold in
  trending markets.

## Per-series

- **ETH > BTC.** ETH: Brier skill 0.589, ROI −33%. BTC: skill 0.487, ROI −49%.
  Prefer ETH when both have similar opportunities.
- Intraday data caps at ~90 markets per series (~60 days). `--per-series` above
  100 adds nothing.

## Sizing / edge-filter

- Compute corrected edge = `corrected_p_yes × 100 − ask`. Use corrected_p_yes
  from the table above, not raw model_p.
- Skip if corrected edge ≤ 5¢.
- Require a **news catalyst** for price markets in addition to corrected positive
  edge.
- IPO / macro / event markets: no quant anchor, size conservatively, news only.
