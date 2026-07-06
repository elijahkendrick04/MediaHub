#!/usr/bin/env python3
"""FIND hardening (council baseline-diff) — catch SILENT primary-flow regressions.

The semantic subagents only flag what they think to look for. A real meet that
used to yield 12 content cards now yielding 3 is invisible: 3 cards looks
superficially fine, so nothing flags it. This pins a KNOWN-GOOD baseline of a
few STABLE structural metrics for ONE fixed golden input (the bundled MISM PDF,
cold seeded org) and diffs every sweep against it.

Council design (the most failure-prone of the five actions — so deliberately
minimal and conservative):
  * ONE fixed golden input, cold only (live data varies too much to baseline).
  * STABLE structural metrics only: cards (the keystone), achievements, export_ok.
  * Regression = below an absolute floor OR < REGRESSION_FRAC of baseline.
  * The baseline is COMMITTED to git (the CI container is ephemeral) and is
    HUMAN-BLESSED ONLY. It is NEVER auto-advanced: the same judges that miss a
    silent regression cannot be trusted to certify the baseline is safe to move
    (a 12->10->8 gradual collapse would be absorbed). On a sustained improvement
    we emit a low-severity DRIFT note suggesting the operator raise it via PR --
    we do not write it ourselves.
  * Infra guard: an INCOMPLETE golden run (crash/timeout) must NOT fire a
    regression -- that's an infra hiccup, not degraded output. The caller passes
    completed=False and we skip.
  * A regression is ONE high-severity finding with a STABLE fingerprint (stable
    title, no date) so the fix loop picks it up without re-filing it each sweep.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from autotest.report import Finding

BASELINE_PATH = Path(__file__).resolve().parent / "baseline" / "golden-baseline.json"
GOLDEN_INPUT = "sample_data/MISM-2024-Results.pdf"

# < this fraction of baseline = a regression (0.6 -> a >40% drop).
REGRESSION_FRAC = float(os.environ.get("AUTOTEST_BASELINE_REGRESSION_FRAC", "0.6"))
# Below this absolute value = a regression regardless of baseline.
ABS_FLOORS = {"cards": 1, "achievements": 1}
_COUNT_METRICS = ("cards", "achievements")
# A sustained improvement worth blessing: current >= baseline * this AND > floor.
DRIFT_FACTOR = float(os.environ.get("AUTOTEST_BASELINE_DRIFT_FACTOR", "1.5"))
# Stable titles -> stable fingerprints -> one ledger entry that updates, not N dupes.
_REGRESSION_TITLE = "Golden-input primary-flow regression vs committed baseline"
_DRIFT_TITLE = "Golden-input baseline drift -- consider raising the committed baseline"


def load_baseline() -> dict:
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check(metrics: dict | None, *, completed: bool, golden: bool) -> Finding | None:
    """Diff cold golden-input `metrics` against the COMMITTED baseline.

    Returns a high-severity Finding on a regression, a low-severity (non-bug)
    DRIFT note on a sustained improvement, else None. Never writes the baseline
    (human-PR only). Skips (None) for non-golden inputs, incomplete runs, or
    absent metrics -- it must never false-fire."""
    if not golden or not completed or not metrics:
        return None

    base = load_baseline()
    if not base:
        return None                     # no committed baseline yet -> nothing to diff

    regressions: list[str] = []
    for key in _COUNT_METRICS:
        cur, prev = metrics.get(key), base.get(key)
        if cur is None or prev is None:
            continue
        cur = int(cur)
        if cur < ABS_FLOORS.get(key, 0) or cur < prev * REGRESSION_FRAC:
            regressions.append(f"{key} {prev}->{cur}")

    if base.get("export_ok") and metrics.get("export_ok") is False:
        regressions.append("export_ok True->False")

    if regressions:
        return Finding(
            category="baseline:regression", severity="high", title=_REGRESSION_TITLE,
            route=GOLDEN_INPUT,
            expected=f"At least the committed baseline for the fixed golden input: {base}.",
            actual=f"This sweep regressed: {', '.join(regressions)} (metrics={metrics}).",
            evidence=(
                "The fixed golden input (bundled MISM PDF on a cold seeded org) dropped below "
                "the committed, human-blessed baseline. This is the kind of SILENT regression "
                "the semantic subagents don't flag because the output still looks superficially "
                f"valid. Threshold: below an absolute floor or under {int(REGRESSION_FRAC * 100)}% "
                "of baseline. The baseline is never auto-lowered, so this reflects a real drop."))

    # Sustained improvement -> suggest (don't perform) a human baseline bump.
    drifts = [f"{k} {base[k]}->{metrics[k]}" for k in _COUNT_METRICS
              if base.get(k) is not None and metrics.get(k) is not None
              and metrics[k] >= max(base[k] * DRIFT_FACTOR, ABS_FLOORS.get(k, 0) + 1)]
    if drifts:
        return Finding(
            category="baseline:drift", severity="low", is_bug=False, title=_DRIFT_TITLE,
            route=GOLDEN_INPUT,
            expected=f"Committed baseline {base}",
            actual=f"The golden input now consistently produces more: {', '.join(drifts)}.",
            evidence=("The golden run is materially better than the committed baseline. Consider "
                      "raising autotest/baseline/golden-baseline.json via PR so future "
                      "regressions are caught against the higher bar. NOT auto-applied -- the "
                      "baseline only moves by deliberate human review (anti-circularity)."))
    return None
