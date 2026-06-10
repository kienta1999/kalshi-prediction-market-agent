# Trading Lessons (curated by /self-improve)

This file is read by `/invest` at the start of every run and applied as guidance.
It is **rewritten** (not appended) by `/self-improve` from logged outcomes +
Kalshi settlement ground-truth. Keep it tight — only durable, evidence-backed
heuristics belong here.

> Source note: 7 backtest rounds across BTC/ETH/S&P/Nasdaq daily markets
> (424 total markets evaluated after bug fix unlocking equity series).
> Not yet from live trades — refresh from live outcomes once they accumulate.

## Backtestable universe

| Series | Asset | Markets | ROI | Brier skill | Use? |
|---|---|---|---|---|---|
| KXBTCD | BTC-USD | ~90/round | −42% | +0.48 | Yes — with corrections |
| KXETHD | ETH-USD | ~80/round | −30% | +0.59 | Yes — preferred over BTC |
| KXINXU | ^GSPC | ~105/round | **−6%** | +0.43 | **Yes — nearly breakeven** |
| KXNASDAQ100U | ^NDX | 120 | −35% | **−0.31** | **No — genuinely below baseline** |

Run default backtests as: `backtest.py --all-series --use-daily`
(`--all-series` = the full mappable price universe; index + crypto only.)

KXNASDAQ100U is genuinely bad — **verified 2026-05-31 on a CORRECT ^NDX feed**
(spot ~30,333 matching strikes ~30,270; the data guard did NOT flag it): Brier
skill −0.31, hit rate 44%, ROI −35% over 120 markets. This is a real model
failure, not a data artifact. (An earlier "wrong-S&P-scale-feed bug" hypothesis
was FALSE and is discarded.) Likely cause: NDX is concentrated in ~7 mega-cap
tech names, so its fatter, jumpier tails are mispriced by a single-day lognormal.
Don't trade KXNASDAQ100U on the price model.

S&P (KXINXU) by contrast is the best price series — verified same run: skill
+0.41, hit 67%, ROI −1% over 109 markets. Its spot is usually a real intraday
bar (markets open ~8pm ET, after the 4pm close); the `spot_source: daily`
fallback is rare. Don't assume "S&P = stale daily close."

## Calibration — DIFFERENT by asset class

**BTC and ETH share a severe S-curve distortion:**

| model_p | BTC realized | ETH realized | Corrected p_yes |
|---|---|---|---|
| 0.0–0.2 | 0.00 | 0.00 | model_p × 0.5 |
| 0.2–0.4 | **0.10** | **0.15** | **model_p × 0.4** |
| 0.4–0.6 | **0.61–0.73** | **0.79–0.85** | **model_p + 0.22** |
| 0.6–0.8 | **0.96** | **0.86** | **model_p + 0.24** |
| 0.8–1.0 | 1.00 | 0.86 | model_p (calibrated) |

**S&P 500 (KXINXU) is nearly well-calibrated — different corrections apply:**

| model_p | S&P realized | Verdict | Correction |
|---|---|---|---|
| 0.0–0.2 | 0.10 | Slightly underconfident | add ~5 points |
| 0.2–0.4 | 0.22 | Good (pred 0.29) | minor adjust |
| 0.4–0.6 | 0.56 | Good (pred 0.49) | minor adjust |
| 0.6–0.8 | 0.70 | **Perfectly calibrated** | none |
| 0.8–1.0 | **0.86** | **Overconfident (pred 0.94)** | **subtract 8 points** |

The S-curve distortion does NOT apply to S&P. The only meaningful correction
is: **when model_p > 0.8 for S&P, treat true p_yes as model_p − 0.08.**
Those overconfident high-p trades are the main source of S&P's −6% ROI.
If filtered out, S&P likely breaks even or is slightly profitable.

**Always compute edge from corrected p_yes, not raw model_p.**

## Directional filter (crypto only)

Applies to BTC and ETH. Does NOT apply to S&P (which is well-calibrated
across 0.2–0.8).

| model_p | BTC/ETH: Take | BTC/ETH: Skip | S&P: Take |
|---|---|---|---|
| 0.0–0.2 | NO preferred | ~~YES~~ | Either (mild adjustment) |
| 0.2–0.4 | NO only | ~~YES~~ | Either (minor adjust) |
| 0.4–0.8 | YES only | ~~NO~~ | Either (well calibrated) |
| 0.8–1.0 | Either | — | YES/NO with −8pt correction |

For crypto in 0.4–0.8: corrected p_yes is 0.72–0.93, so NO only worth
buying if no_ask < 7–28¢ (rare). Effectively skip all NO bets there.

## Signal patterns

- **Model edge is necessary but NOT sufficient** for crypto. All crypto series
  lost money without a news catalyst. For S&P the model edge is more reliable
  (−6% ROI, 62% hit rate) but still requires a catalyst to be confident.
- The bigger the model/market gap with no news explanation, the more likely
  the market is right. Skip it.
- For S&P specifically: the high-probability trades (model_p > 0.8) are the
  losers. Focus on mid-range S&P markets (model_p 0.4–0.8) which are calibrated.

## Per-series notes

- **ETH > BTC** for crypto. Similar calibration shape, but ETH Brier skill
  0.59 vs BTC 0.48. Prefer ETH when opportunities are similar.
- **S&P (KXINXU) is the best-performing series** (skill +0.41, hit 67%, ROI −1%,
  verified 2026-05-31). Include it in every backtest run with `--use-daily`.
- **KXNASDAQ100U: avoid.** Skill −0.31 on a verified-correct ^NDX feed — a real
  model failure (mega-cap concentration → fat tails), not a data artifact.
- **Always check `data_warnings`** in backtest output: a `data_suspect` series
  has a broken feed (flat/degenerate, or spot wildly off the strikes — e.g. a
  geo-degraded feed run outside the US) and its numbers must not be trusted.
- Intraday data caps at ~90 markets for crypto, ~105–149 for equity (~60d).
  `--per-series` above 150 adds nothing.

## Sizing / edge-filter

- For **crypto**: apply directional filter first; compute corrected edge
  = corrected_p_yes × 100 − ask; skip if corrected edge ≤ 5¢.
- For **S&P**: compute edge normally but subtract 8 points from model_p when
  model_p > 0.8 before computing edge; skip model_p > 0.8 NO bets entirely.
- Require a **news catalyst** for all price-market bets in addition to
  corrected positive edge.
- IPO / macro / event markets: no quant anchor, size conservatively, news only.
- Keep the ≤5¢-edge skip even at high conviction (2026-06-10: Musk-$1T YES at
  90 with p≈0.94 was correctly skipped at +4¢ — right thesis, no room).

## Event-market interim observations (mark-to-market, NOT settlement-verified)

> Source: `paper_score.py --mark` 2026-06-10 on the 17 pre-Jun-10 paper trades.
> 0/22 paper trades settled; these are unrealized marks at the bid (wide spreads
> overstate losses). Treat as provisional process rules, not calibration facts.
> Re-derive from settlement once markets resolve (first wave: Jun–Sep 2026).

Book stood at **−24% unrealized** (−$398 on $1,649 deployed). The losers share
one shape — **fading market consensus on narrative, not hard facts**:

- KXIPO-26-ANTHROPIC NO@23 → YES ran to 91 (mark 9). Faded a rising IPO market;
  the 2026 IPO wave (SpaceX priced, OpenAI S-1 filed) was knowable.
- KXLLM1-A (Claude best AI) NO@37 → YES 64→72. Faded momentum twice.
- KXMCD comps YES@22 → 11; KXCMG-REST YES@51 → 25. Model-style disagreements
  with the market on KPI thresholds, no dated catalyst.
- SpaceX-IPO NO@3 (p_no 0.12 tail bet) → 0. Tail lottery, behaved as priced.

Provisional rules (applied in the 2026-06-10 run):

1. **Event bets need a hard dated fact** (filing date, regulatory clock,
   reported production/comps numbers), not disagreement with consensus.
2. **Don't re-fade momentum**: a >10–15¢ move against the thesis with no
   contradicting hard news is information — stand aside, don't double the fade.
3. **Sub-10¢ tail bets**: expect total loss; size to what you'd burn.
4. Diversify event theses; the May 30 book concentrated in "AI-race/IPO
   skepticism" and one correlated narrative drove most of the drawdown.
