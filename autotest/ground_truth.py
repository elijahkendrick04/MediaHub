"""Ground-truth regression oracle (LLM Council 2026-06-01).

The finder's live-prod sweep has NO ground truth: it judges whatever runs happen
to exist on prod, so it cannot tell a real defect from correct behaviour — the
"0 cards" empty state was flagged as a bug because there was no known-correct
answer to compare against. The Council's root fix: a controlled, SEEDED check
with a KNOWN input and a KNOWN-good output — a deterministic regression oracle.

This ACTIVATES the (previously dormant) golden-baseline mechanism. The committed
``baseline.py`` diff only fires for a ``golden`` cold run, but CI runs the finder
in ``live`` mode so it never triggered — and the seeded "Autotest" org doesn't
match the sample meet, so that path produced an empty pack anyway. Here we run the
canonical sample meet through the REAL pipeline with a club that IS in it (so the
full parse → detect → rank → cards path runs), then:
  * assert STRUCTURAL invariants ``baseline.py`` can't (no crash, exact parser
    count, club actually matched, the V5→V3 bridge holds, a known swimmer
    surfaces) — these catch parser/matcher/bridge regressions, and
  * delegate the card/achievement COUNT-magnitude regression to the council's
    conservative, human-blessed ``baseline.check`` (one shared golden baseline,
    no duplicate logic).

A mismatch is a FALSIFIABLE, REPRODUCIBLE finding — the signal the live-prod
sweep can never give. Only deterministic outputs are asserted (counts, names),
never AI captions, which legitimately vary with provider availability.
"""
from __future__ import annotations

from pathlib import Path

from autotest import baseline
from autotest.report import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / baseline.GOLDEN_INPUT
_ROUTE = "(ground-truth oracle)"


def _skip(title: str, actual: str, evidence: str) -> list[Finding]:
    return [Finding(category="ground_truth_skipped", severity="info", title=title,
                    route=_ROUTE, expected="the ground-truth oracle can run",
                    actual=actual, evidence=evidence, is_bug=False)]


def check() -> list[Finding]:
    """Run the canonical sample meet through the pipeline and assert the output
    matches the committed golden baseline. Returns regression findings (empty ==
    healthy). Never raises — infra gaps (missing PDF/baseline) record a non-bug
    info, not a false regression."""
    if not SAMPLE.exists():
        return _skip("Ground-truth oracle skipped — sample meet missing",
                     f"{SAMPLE.name} missing", str(SAMPLE))
    base = baseline.load_baseline()
    club = base.get("club_filter")
    if not base or not club:
        return _skip("Ground-truth oracle skipped — golden baseline missing club_filter",
                     "no club_filter in golden-baseline.json", str(baseline.BASELINE_PATH))

    repro = [f"run_pipeline_v4 on {SAMPLE.name} with club_filter={club!r}; "
             f"compare to autotest/baseline/golden-baseline.json"]
    evidence = (f"Canonical sample meet {SAMPLE.name} + club {club!r}; committed golden "
                f"baseline. This is a DETERMINISTIC, reproducible regression — not a "
                f"live-prod guess.")
    try:
        from mediahub.pipeline.pipeline_v4 import run_pipeline_v4
        run = run_pipeline_v4(file_bytes=SAMPLE.read_bytes(), filename=SAMPLE.name,
                              profile_id=None, club_filter=club,
                              use_pb_cache=True, fetch_pbs=False,
                              run_id="autotest_ground_truth")
    except Exception as exc:
        return [Finding(category="ground_truth_regression", severity="high",
                        title="Pipeline raised on the canonical sample meet", route=_ROUTE,
                        expected="the known sample meet processes cleanly",
                        actual=f"{type(exc).__name__}: {exc}", evidence=str(exc)[:500],
                        suspect="src/mediahub/pipeline/pipeline_v4.py", repro=repro)]

    findings: list[Finding] = []

    def _bug(title: str, expected: str, actual: str, *, sev: str = "high", suspect: str = "") -> None:
        findings.append(Finding(
            category="ground_truth_regression", severity=sev, title=title, route=_ROUTE,
            expected=expected, actual=actual, evidence=evidence, suspect=suspect, repro=repro))

    if run.error:
        _bug("Canonical sample meet failed to process",
             "the known sample meet processes without error",
             f"run.error = {run.error}", suspect="src/mediahub/pipeline/pipeline_v4.py")
        return findings  # nothing else is meaningful once the run errored

    rr = getattr(run, "recognition_report", None) or {}
    ranked = rr.get("ranked_achievements") or []
    cards = run.cards or []
    parsed = getattr(run, "parsed_swim_count", None)
    ours = getattr(run, "our_swim_count", None)

    # --- STRUCTURAL invariants (what baseline.py's count-diff can't catch) ----
    # Parser determinism — a fixed PDF must parse to a fixed swim count (exact).
    if base.get("parsed_swim_count") is not None and parsed != base["parsed_swim_count"]:
        _bug("Parser regression: sample-meet swim count changed",
             f"parsed_swim_count == {base['parsed_swim_count']}",
             f"parsed_swim_count == {parsed}", suspect="src/mediahub/interpreter/ (parser)")
    # Club matching — a club known to be in the meet must be represented.
    if not ours or ours <= 0:
        _bug("Club-matching regression: 0 swims matched a club known to be in the meet",
             "our_swim_count > 0", f"our_swim_count == {ours}",
             suspect="club filter / interpreter")
    # V5->V3 bridge — one card per ranked achievement (the empty-pack guard lives
    # in baseline.check below; this catches a partial/broken bridge).
    if cards and len(cards) != len(ranked):
        _bug("V5->V3 bridge regression: card count != ranked-achievement count",
             "len(cards) == len(ranked_achievements)",
             f"{len(cards)} cards vs {len(ranked)} ranked achievements",
             suspect="src/mediahub/pipeline/pipeline_v4.py (bridge)")
    # Detection sanity — at least one baseline swimmer still surfaces (grounded).
    names = {n for c in cards for n in (getattr(c, "swimmer_names", None) or [])}
    known = base.get("known_swimmers") or []
    if cards and known and not (names & set(known)):
        _bug("Detection drift: none of the baseline swimmers appear on any card",
             f"at least one of {known[:3]} present", "none of the baseline swimmers found",
             sev="medium", suspect="recognition_swim detectors")

    # --- COUNT-magnitude regression — reuse the council-designed conservative diff
    #     (alarm below an absolute floor or under 60% of the human-blessed baseline,
    #     plus the improvement-drift note). This is the empty-pack ("0 cards") guard.
    metrics = {"cards": len(cards), "export_ok": True,
               "achievements": rr.get("n_achievements")
               if rr.get("n_achievements") is not None else len(ranked)}
    count_finding = baseline.check(metrics, completed=True, golden=True)
    if count_finding is not None:
        findings.append(count_finding)
    return findings
