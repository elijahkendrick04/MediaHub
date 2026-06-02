# Judge calibration set (A5)

This folder holds the **human-labelled ground truth** used to measure whether the
LLM council is trustworthy — turning "is the council over-flagging?" into a number
(precision / recall) instead of a vibe. See the methodology and sources in
[`docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md`](../../docs/autotest/AUTOTEST_BENCHMARK_AND_GAPS.md)
(Tier A5).

## Files

- **`labels.jsonl`** — one JSON object per line, the human verdict on past findings:
  ```json
  {"fingerprint": "e883e6f0bbc7", "category": "semantic:functional", "title": "…", "label": "real"}
  ```
  - `label` is **`real`** (a genuine defect worth fixing) or **`noise`** (a false
    positive / over-flag).
  - `fingerprint` ties the label to a ledger entry, so `autotest/metrics.py` can read
    the council's verdict for the same finding and compare.
  - An optional `source` field marks provenance. A draft from the auto-seeder is
    stamped `"source": "auto-seed (review me)"`. **Remove or change that field when a
    human has reviewed the row** — only then does it count as *curated*.
- **`precision.json`** — generated, do not hand-edit. The published precision/recall
  the live system reads (`report.py`). It stays `null` until enough rows are curated.

## How a human curates it

1. **Seed a draft** from the current ledger (clear cases only — council-demoted /
   blind-spot → `noise`, verified-fixed → `real`/`noise` from its note):
   ```bash
   python -m autotest.metrics --seed
   ```
2. **Review every row.** Open `autotest/reports/BUGS.md` / `ledger.json`, decide
   `real` vs `noise` yourself, fix any mislabel, and drop the `"auto-seed"` marker on
   rows you've confirmed. **Add the cases where you DISAGREE with the council** —
   those are the whole point. An un-reviewed set that just mirrors the council reads
   as precision 1.0 by construction (the "blind trust" the report warns against), so
   it is deliberately NOT published until ≥ `AUTOTEST_CALIBRATION_MIN_CURATED`
   (default 20) rows are curated.
3. **Recompute:**
   ```bash
   python -m autotest.metrics
   ```
   This writes `precision.json` and `autotest/reports/METRICS.md`, and prints the
   `🔬 Judge trust` line into the CI step summary.

## What the number does

Once published (enough curated rows), the measured precision:

- prints the **`🔬 Judge trust`** line at the top of `BUGS.md`, and
- **scales the A1 confirm gate** — low precision → the loop demands *more* confirming
  sweeps before a subjective finding opens (`report.effective_confirm_sweeps`), so a
  council you can't yet trust can't flood the open list.

Target (per the report): treat the council as trustworthy triage at **precision ≥ 0.8**;
below **0.6** (coin-flip territory) demote the judges to advisory-only.

> Curate deliberately. This set is the oracle that judges the judges — keep it honest,
> grow it over time (the report suggests ~50–100 rows), and never auto-advance it.
