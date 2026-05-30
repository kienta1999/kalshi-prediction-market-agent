---
name: self-improve
description: Learn from past Kalshi trades and rewrite the trading playbook. Reads the decision + sell logs, joins them to Kalshi settlement ground-truth, checks calibration (predicted probability vs realized outcomes), finds which signal patterns preceded wins vs losses, and rewrites logs/lessons.md with concrete heuristics that /invest applies. Use when the user says "self-improve", "learn from trades", "review performance", or "kalshi:self-improve".
---

# Kalshi Self-Improve

You are the learning loop. Turn raw trade logs into a tight, evidence-backed playbook that makes future `/invest` runs better. **Run Python via `.venv/bin/python` from the project root.**

## Step 1 — Gather history
- `.venv/bin/python journal.py read-decisions` → all logged decisions (each has `model_p`, `p_yes`, `category`, `signals`, `decision`, `order`).
- `.venv/bin/python journal.py read-sells` → all exits (entry/exit/pnl/action/outcome).
- Ignore rows with `"dry_run": true` — no real outcomes to learn from.
- If there is little/no real history, say so and stop (don't invent lessons).

## Step 2 — Get ground-truth
Collect the tickers from traded decisions, then:
`.venv/bin/python kalshi.py settled --tickers <comma-separated tickers>` → each settled market's `result` (`yes`/`no`).

Build a `ticker -> result` map. This is the truth signal: did YES actually happen?

## Step 3 — Join & analyze
Join decisions ⋈ sells ⋈ settlement by ticker. For each traded market you now have: predicted `p_yes`, the `model_p` anchor, the signal snapshot, the realized exit P&L, and the settled YES/NO result.

Analyze:
- **Calibration:** bucket predictions (e.g. 50-60%, 60-70%, 70-80%, ...) and compare predicted probability to realized YES-rate. Compute a rough Brier score. Are you overconfident? Systematically biased in a category (e.g. macro)?
- **Model vs. you:** when your `p_yes` drifted far from `model_p`, did that drift help or hurt? If drift consistently hurts, trust the model more.
- **Signal patterns:** which `signals` values preceded wins vs losses (e.g. "RSI>75 entries lost money", "trades against the 200-MA underperformed")?
- **Edge filter / sizing:** were small-edge trades (just above the fee buffer) net losers? Is half-Kelly too aggressive given realized variance?

## Step 4 — Rewrite the playbook
**Rewrite** `logs/lessons.md` (do not append — keep it tight and pruned). Each lesson must be concrete, actionable by `/invest`, dated, and backed by what you saw in the data. Drop stale or contradicted lessons. Structure:
- `## Calibration notes` — e.g. "Shrink macro `p_yes` toward 0.5 by ~10pts (overconfident: predicted 72%, realized 55% over N trades, 2026-06)."
- `## Signal patterns` — e.g. "Skip crypto YES when RSI14 > 80 (0/4 winners)."
- `## Sizing / edge-filter adjustments` — e.g. "Raise fee buffer to 5c for sub-1-day markets (3c trades net-negative after fees)."

Keep it short enough to load into every invest run. Prefer a handful of high-confidence rules over many weak ones.

## Step 5 — Report
Summarize for the user: number of settled trades analyzed, calibration finding, hit rate, total realized P&L, and the key lessons you wrote. Note sample-size caveats where N is small.
