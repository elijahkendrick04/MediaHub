"""Finding #59 — season standards packs + per-profile important_standards must
reach qual-hit detection.

The W.4 selector standards_for_profile() unions quals.json with season packs
and honours ClubProfile.important_standards. Before the fix the pipeline loaded
standards with the raw load_registry(), so a club that had picked a subset of
standards still had EVERY standard run against it (and season packs were never
loaded at all).

This drives the real run_pipeline_v4 far enough to reach the standards step,
intercepts the exact `standards` list handed to the deterministic V3 detector,
and asserts the profile's important_standards filter was applied. Tiny synthetic
JSON meet — no corpus ZIP/PDF. Fully deterministic; no LLM.
"""
from __future__ import annotations

import json

import pytest


class _StopAfterStandards(RuntimeError):
    pass


def test_pipeline_applies_important_standards_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "profiles"))

    import mediahub  # noqa: F401  triggers legacy-name shim registration
    import mediahub.pipeline.pipeline_v4 as p
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.standards.packs import all_standards

    loaded_ids = [getattr(s, "standard_id", "") for s in all_standards()]
    # This test distinguishes "all standards" from "filtered subset"; it only has
    # signal if at least two standards exist and both known ids are present.
    if not ({"BUCS_LC_2026_27_CT", "AGB_CHAMPS_2026_CT"} <= set(loaded_ids)):
        pytest.skip("expected baseline quals.json standards not present")

    save_profile(
        ClubProfile(
            profile_id="tclub",
            display_name="Test Club",
            club_codes=["TST"],
            important_standards=["BUCS_LC_2026_27_CT"],
        )
    )

    captured: dict = {}

    def _fake_detect_v3(**kwargs):
        captured["ids"] = [
            getattr(s, "standard_id", "") for s in kwargs.get("standards", [])
        ]
        raise _StopAfterStandards

    monkeypatch.setattr(p, "detect_v3", _fake_detect_v3)

    blob = json.dumps(
        {
            "meet": "Synthetic Open 2026",
            "results": [
                {"place": 1, "name": "Ada Lovelace", "club": "TST",
                 "event": "100 Free", "time": "1:02.34"},
            ],
        }
    ).encode()

    with pytest.raises(_StopAfterStandards):
        p.run_pipeline_v4(
            file_bytes=blob,
            filename="synthetic.json",
            profile_id="tclub",
            fetch_pbs=False,
        )

    ids = captured.get("ids")
    assert ids is not None, "detector was never reached — pipeline changed shape"
    # The profile picked exactly one standard: only that one may run.
    assert "BUCS_LC_2026_27_CT" in ids
    assert "AGB_CHAMPS_2026_CT" not in ids, (
        "important_standards filter ignored — all standards still fed to detection "
        f"(got {ids})"
    )
    assert set(ids) == {"BUCS_LC_2026_27_CT"}
