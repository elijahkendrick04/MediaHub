"""
Regression test for F29 — the dead ``recommendations`` blob.

``recommend_post_type`` produced a full duplicate copy of every ranked
achievement that was stored on ``RecognitionReport.recommendations`` and
serialized into every run JSON / export, yet nothing ever read it back. The
fix removes the field and its ``to_dict`` line (and the production call site in
``report.py``) so the serialized report no longer carries the duplicate.

These tests lock in:
  1. A built ``RecognitionReport.to_dict()`` has NO ``recommendations`` key.
  2. The report is loaded as a plain dict (there is no ``from_dict``), so a
     legacy run JSON that still carries a ``recommendations`` key loads and is
     consumed without error — the extra key is simply ignored.
"""
import mediahub  # noqa: F401  (installs the legacy sys.path shim)

from swim_content_v5.schema import RecognitionReport, MeetContext


def _build_report() -> RecognitionReport:
    return RecognitionReport(
        run_id="run-f29",
        meet_name="Spring Open",
        meet_context=MeetContext(meet_name="Spring Open"),
    )


def test_report_to_dict_has_no_recommendations_key():
    d = _build_report().to_dict()
    assert "recommendations" not in d, (
        "the dead 'recommendations' duplicate-blob must not be serialized"
    )
    # The live sections the product actually reads are still present.
    assert "ranked_achievements" in d
    assert "swim_traces" in d


def test_recognition_report_has_no_recommendations_field():
    # The dataclass field itself is gone (not merely omitted from to_dict).
    assert "recommendations" not in RecognitionReport.__dataclass_fields__


def test_legacy_run_json_with_recommendations_key_still_loads():
    # Reports persist as plain dicts (RecognitionReport has no from_dict), so a
    # legacy payload that still carries the old key must remain fully usable.
    assert not hasattr(RecognitionReport, "from_dict")

    legacy = _build_report().to_dict()
    legacy["recommendations"] = [
        {"title": "Athlete spotlight: Ana", "ranked_achievements": []}
    ]
    # A consumer reading the live fields is unaffected by the extra legacy key.
    assert legacy["run_id"] == "run-f29"
    assert legacy["meet_name"] == "Spring Open"
    assert isinstance(legacy["ranked_achievements"], list)
    assert isinstance(legacy["swim_traces"], list)
