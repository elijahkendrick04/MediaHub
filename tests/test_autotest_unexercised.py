"""A4 (Tier A): an artifact from a flow we DIDN'T exercise this sweep is
judge-ineligible, so a page that is empty only because we skipped its flow can
never become a finding (the AUTOTEST_SIGNUP=0 false-positive class).

These extend the council-mandated de-contamination scheme (RENDERED_PAGE /
TESTER_CONTROL / TESTER_SUMMARY) with a fourth, judge-ineligible kind —
preserving its single-implementation property (one filter_artifacts). They assert
on ground truth (the filtered bag / the prompt body), never on a model verdict.
"""
from __future__ import annotations

from autotest import run, semantic


# --- effective_provenance + the NOT_EXERCISED kind --------------------------
def test_unexercised_artifact_resolves_to_not_exercised():
    meta = {"signup_text": {"exercised": False, "skipped_reason": "signup disabled"}}
    assert semantic.effective_provenance("signup_text", meta) == semantic.NOT_EXERCISED
    # base class is untouched for an exercised / unmarked artifact:
    assert semantic.effective_provenance("signup_text", {}) == semantic.RENDERED_PAGE
    assert semantic.effective_provenance("signup_text", None) == semantic.RENDERED_PAGE


def test_exercised_true_keeps_base_class():
    meta = {"home_text": {"exercised": True}}
    assert semantic.effective_provenance("home_text", meta) == semantic.RENDERED_PAGE


def test_not_exercised_is_in_no_allowed_set_not_even_all_provenance():
    assert semantic.NOT_EXERCISED not in semantic.ALL_PROVENANCE
    arts = {"signup_text": "h"}
    meta = {"signup_text": {"exercised": False}}
    # Even a fully-permissive charter (ALL_PROVENANCE) drops an unexercised artifact.
    assert semantic.filter_artifacts(arts, semantic.ALL_PROVENANCE, meta) == {}


def test_filter_drops_unexercised_regardless_of_base_kind():
    arts = {"home_text": "h", "flow_result": "x", "export_json": "{}"}
    meta = {"home_text": {"exercised": False}, "flow_result": {"exercised": False}}
    # RENDERED_PAGE (home_text) and TESTER_CONTROL (flow_result) both dropped when unexercised.
    out = semantic.filter_artifacts(arts, semantic.ALL_PROVENANCE, meta)
    assert "home_text" not in out and "flow_result" not in out


def test_filter_meta_none_preserves_original_behaviour():
    arts = {"home_text": "h", "flow_result": "x", "pages": "200 /"}
    # The 2-arg call (the existing de-contamination tests) is unchanged.
    only_rendered = semantic.filter_artifacts(arts, frozenset({semantic.RENDERED_PAGE}))
    assert set(only_rendered) == {"home_text"}


# --- _derive_meta: export-derived summaries inherit the export's flag --------
def test_derive_meta_propagates_export_flag_to_summaries():
    raw = {"export_json": {"exercised": False, "skipped_reason": "no content"}}
    derived = semantic._derive_meta(raw)
    for k in ("content_summary", "content_pack", "meet_summary"):
        assert derived[k]["exercised"] is False
    # and a direct passthrough key maps to itself:
    assert semantic._derive_meta({"signup_text": {"exercised": False}})["signup_text"]["exercised"] is False


# --- END-TO-END: the AUTOTEST_SIGNUP=0 false-positive can't be authored ------
def test_signup_disabled_artifact_never_reaches_user_brain(monkeypatch):
    captured = {}

    def fake_ask(system, user, max_tokens=0):
        captured["user"] = user
        return '{"issues":[]}'

    import autotest.cli_llm as cli
    monkeypatch.setattr(cli, "ask", fake_ask)
    # signup_text is empty-by-absence (we ran with signup disabled). Mark it
    # unexercised exactly as run.reconcile_artifact_meta would.
    raw = {"home_text": "MediaHub home", "review_text": "review body", "export_json": {"cards": []}}
    arts = semantic._build_artifacts(raw)          # signup_text becomes "" here
    meta = semantic._derive_meta({"signup_text": {"exercised": False}})
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    semantic._run_charter(ub, arts, meta)
    # The user_brain prompt must NOT contain a sign-up section at all (dropped),
    # so the judge cannot flag the empty sign-up page it never ran.
    assert "## signup_text" not in captured["user"]
    # the genuinely-exercised pages ARE still present:
    assert "## home_text" in captured["user"] and "## review_text" in captured["user"]


def test_exercised_empty_page_still_reaches_the_judge(monkeypatch):
    # A genuinely-empty page from a flow that DID run stays judge-eligible.
    captured = {}
    import autotest.cli_llm as cli
    monkeypatch.setattr(cli, "ask", lambda system, user, max_tokens=0: captured.update(user=user) or '{"issues":[]}')
    raw = {"home_text": "h", "signup_text": "", "review_text": "r", "export_json": {"cards": []}}
    arts = semantic._build_artifacts(raw)
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    semantic._run_charter(ub, arts, {})   # nothing marked unexercised
    assert "## signup_text" in captured["user"]   # present (blank) but exercised → kept


# --- run.Tester.reconcile_artifact_meta -------------------------------------
class _FakeTester:
    """Minimal stand-in to exercise reconcile_artifact_meta without a browser."""
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.artifact_meta = {}
    reconcile_artifact_meta = run.Tester.reconcile_artifact_meta


def test_reconcile_marks_absent_canonical_keys_unexercised():
    t = _FakeTester({"home_text": "h", "review_text": "r", "export_json": {"cards": [1]}})
    t.reconcile_artifact_meta()
    # signup_text absent → marked unexercised; the present ones are NOT marked.
    assert t.artifact_meta["signup_text"]["exercised"] is False
    assert "home_text" not in t.artifact_meta
    assert "export_json" not in t.artifact_meta


def test_reconcile_does_not_override_explicit_mark():
    t = _FakeTester({"home_text": "h"})
    t.artifact_meta["signup_text"] = {"exercised": True, "note": "explicit"}
    t.reconcile_artifact_meta()
    assert t.artifact_meta["signup_text"] == {"exercised": True, "note": "explicit"}
