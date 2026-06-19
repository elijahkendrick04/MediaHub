"""End-to-end: PBs from the club's own accumulating results history, no network.

Upload meet 1 (a swimmer's first recorded swim) → no PB (honest cold start).
Upload meet 2 where she goes faster → the engine confirms a PB against her OWN
earlier result from meet 1 — with ``fetch_pbs=False`` (the web is never touched).
This is the scalable baseline: returning swimmers get accurate PBs for free.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for p in (_ROOT / "src", _ROOT / "legacy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _results_text(meet_name: str, date: str, effy_time: str) -> bytes:
    return (
        f"{meet_name}\n"
        f"Event 101  Girls 200 LC Meter Freestyle\n"
        f"Name                  AaD Club            Finals Time\n"
        f"1 Effy Johnson         15 Brighton Dolph  {effy_time}\n"
        f"2 Mia Carter           14 Brighton Dolph  2:58.00\n"
    ).encode("utf-8")


def _pb_headlines(run):
    rr = run.recognition_report or {}
    return [
        (ra.get("achievement", {}) or {}).get("headline", "")
        for ra in rr.get("ranked_achievements", [])
        if "pb" in (ra.get("achievement", {}) or {}).get("type", "")
    ]


def test_second_upload_confirms_pb_from_history(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    common = dict(
        profile_id=None,
        club_filter="Brighton Dolph",
        use_pb_cache=True,
        fetch_pbs=False,  # NO web — PBs must come from accumulated history alone
    )

    # Meet 1: Effy's first recorded 200 Free. No prior history → no PB.
    run1 = run_pipeline_v4(
        file_bytes=_results_text("Winter Open", "2026-01-10", "2:51.20"),
        filename="winter.txt", run_id="hist-e2e-1", **common,
    )
    assert run1.error is None
    assert _pb_headlines(run1) == [], "first upload has no prior history → no PB"

    # Meet 2: she swims 2:49.40 — faster than her own 2:51.20 from meet 1.
    run2 = run_pipeline_v4(
        file_bytes=_results_text("County Champs", "2026-02-15", "2:49.40"),
        filename="county.txt", run_id="hist-e2e-2", **common,
    )
    assert run2.error is None
    pbs = _pb_headlines(run2)
    assert any("Effy Johnson" in h for h in pbs), (
        f"second upload should confirm a PB from history, got {pbs}"
    )

    # And the headline "weekend at a glance" PB tally is no longer 0.
    from mediahub.web.weekend_glance import build_weekend_glance

    glance = build_weekend_glance(
        {
            "recognition_report": run2.recognition_report,
            "meet": {"name": "County Champs"},
            "our_swim_count": run2.our_swim_count,
        }
    )
    assert glance is not None and glance.n_pbs >= 1


def test_reupload_same_meet_is_not_a_pb(tmp_path, monkeypatch):
    """Re-uploading the SAME meet must not turn a swim into a PB against itself."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    common = dict(profile_id=None, club_filter="Brighton Dolph", use_pb_cache=True, fetch_pbs=False)
    args = dict(file_bytes=_results_text("Winter Open", "2026-01-10", "2:51.20"), filename="w.txt")

    run1 = run_pipeline_v4(run_id="reup-1", **args, **common)
    run2 = run_pipeline_v4(run_id="reup-2", **args, **common)  # identical meet again
    assert run1.error is None and run2.error is None
    assert _pb_headlines(run2) == [], "same meet re-uploaded is never its own PB baseline"
