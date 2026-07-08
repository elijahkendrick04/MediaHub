"""U.2 — every state designed across the primary flow.

Pins the four U.2 deliverables (presentation-only; the deterministic engine,
AI surfaces and explainability logic are untouched):

  D1  the single honest "AI provider not configured" banner — one shared
      helper so the copy/styling can't drift across the three surfaces that
      promise AI output (review + both content builders)
  D2  the pipeline-error state on /review — a terminally-failed run shows the
      honest reason instead of a misleading "(unknown meet) / No standout
      swims" empty page, and the builders redirect to it
  D3  the parse-uncertainty / flag-for-review surface — machine codes mapped
      to plain English, error-severity flags led out, "+N more" when truncated
  D4  the server→client success/error toast bridge — a redirecting POST (e.g.
      a run deleted) finally confirms itself instead of a silent reload
"""
import json
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.media_ai import llm as _llm


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_review_empty_state_club_match.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(webmod, "RUNS_DIR", runs, raising=False)
    app = webmod.app
    app.config["TESTING"] = True  # disables CSRF enforcement (see _csrf_enforced)
    with app.test_client() as c:
        yield c


def _write_run(run_id, payload):
    (webmod.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _review_body(client, run_id, expect=200):
    resp = client.get(f"/review/{run_id}")
    assert resp.status_code == expect, f"/review/{run_id} → {resp.status_code}"
    return resp.get_data(as_text=True)


# A truthy recognition report with nothing ranked — the run WAS judged so the
# route reaches the normal page (rather than the "no report yet" branch).
_JUDGED_EMPTY = {"ranked_achievements": [], "n_achievements": 0, "n_swims_analysed": 0}


# =========================================================================== #
# D1 — the shared honest AI-unavailable banner
# =========================================================================== #
def test_ai_banner_blank_when_provider_available(monkeypatch):
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    assert webmod._ai_unavailable_banner() == ""


def test_ai_banner_renders_when_unavailable(monkeypatch):
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    html = webmod._ai_unavailable_banner()
    assert "AI provider not configured" in html
    assert 'role="status"' in html              # announced to AT
    assert "mh-ai-unavailable" in html          # stable hook
    assert "<svg" in html                       # designed: carries the warn glyph
    # Default copy is the full (review) variant.
    assert "ranker reasoning" in html


def test_ai_banner_custom_detail_overrides_body(monkeypatch):
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    html = webmod._ai_unavailable_banner(webmod._AI_UNAVAILABLE_DETAIL_PACK)
    assert "AI provider not configured" in html
    assert "ranker reasoning" not in html       # the narrower builder copy
    assert "Captions and" in html


def test_ai_banner_probe_failure_never_blocks_page(monkeypatch):
    def _boom():
        raise RuntimeError("provider probe exploded")

    monkeypatch.setattr(_llm, "is_available", _boom)
    # A probe failure must degrade to no banner, never to a 500.
    assert webmod._ai_unavailable_banner() == ""


def test_ai_banner_copy_defined_once_dry():
    """The rendered strap markup lives only in the shared helper, and every
    surface goes through it — so the copy/styling can never drift back apart
    (the pre-U.2 state had three hand-inlined, already-divergent copies)."""
    src = Path(webmod.__file__).read_text(encoding="utf-8")
    strap = '<span class="strap" style="color:var(--warn)">AI provider not configured</span>'
    assert src.count(strap) == 1, "the banner strap is hand-inlined somewhere again"
    # def line + at least the three primary-flow call sites all route through it.
    assert src.count("_ai_unavailable_banner(") >= 4


def test_review_shows_one_ai_banner_when_unavailable(client, monkeypatch):
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    _write_run("ban1", {
        "file_name": "meet.hy3", "meet": {"name": "Spring Open"}, "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 10, "our_swim_count": 5, "club_filter": "X",
        "parse_warnings": [],
    })
    body = _review_body(client, "ban1")
    assert body.count("mh-ai-unavailable") == 1   # exactly one, not per-card


def test_review_no_ai_banner_when_available(client, monkeypatch):
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    _write_run("ban2", {
        "file_name": "meet.hy3", "meet": {"name": "Spring Open"}, "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 10, "our_swim_count": 5, "club_filter": "X",
        "parse_warnings": [],
    })
    body = _review_body(client, "ban2")
    assert "mh-ai-unavailable" not in body


# =========================================================================== #
# D2 — the pipeline-error state
# =========================================================================== #
def _failed_run(run_id="failed1"):
    _write_run(run_id, {
        "file_name": "broken.hy3",
        "error": "HY3 decode failed: invalid header at byte 0",
        "meet": {},
        "cards": [],
        "recognition_report": {},
        "parse_warnings": [
            {"code": "decode_failed", "message": "Could not decode the HY3 file.",
             "severity": "error"},
        ],
    })
    return run_id


def test_review_surfaces_pipeline_error_honestly(client):
    body = _review_body(client, _failed_run())
    assert "finish processing this run" in body          # the honest headline
    assert "Processing failed" in body                   # eyebrow
    assert "HY3 decode failed" in body                   # the actual reason, shown
    assert "Try another file" in body                    # a way forward


def test_failed_run_does_not_show_misleading_empty_state(client):
    body = _review_body(client, _failed_run("failed2"))
    # The old behaviour: a confusing near-empty review page.
    assert "No standout swims" not in body
    assert "No swims matched your club" not in body
    assert "Review queue" not in body                    # normal eyebrow suppressed


def test_failed_run_error_text_is_escaped(client):
    _write_run("xss1", {
        "file_name": "x.hy3",
        "error": "<script>alert(1)</script> boom",
        "meet": {}, "cards": [], "recognition_report": {}, "parse_warnings": [],
    })
    body = _review_body(client, "xss1")
    assert "<script>alert(1)</script>" not in body       # never raw
    assert "&lt;script&gt;" in body                       # escaped


def test_content_pack_redirects_failed_run_to_review(client):
    r = client.get(f"/pack/{_failed_run('failed3')}", follow_redirects=False)
    assert r.status_code == 302
    assert "/review/failed3" in r.headers["Location"]


def test_grouped_pack_redirects_failed_run_to_review(client):
    r = client.get(f"/pack/{_failed_run('failed4')}/grouped", follow_redirects=False)
    assert r.status_code == 302
    assert "/review/failed4" in r.headers["Location"]


def test_configure_missing_club_is_designed_error_not_deadend(client):
    # Stage a temp upload so the POST reaches the club-required validation.
    rid = "cfg123"
    d = webmod.RUNS_DIR / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "upload_meta.json").write_text(json.dumps({"clubs": ["A", "B"]}), encoding="utf-8")
    (d / "input.bin").write_bytes(b"dummy")
    r = client.post("/upload/configure", data={"run_id": rid}, follow_redirects=False)
    assert r.status_code == 400                       # a real validation status
    body = r.get_data(as_text=True)
    assert "Pick a club to feature" in body
    assert "Back to configure" in body               # a way out, not a dead-end
    assert "mh-emptystate" in body                   # the designed state, not a bare card


def test_healthy_run_is_not_treated_as_failed(client):
    # A normal judged-empty run (no top-level error) still renders the queue.
    _write_run("ok1", {
        "file_name": "meet.hy3", "meet": {"name": "Spring Open"}, "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 40, "our_swim_count": 40, "club_filter": "X",
        "parse_warnings": [],
    })
    body = _review_body(client, "ok1")
    assert "finish processing this run" not in body
    assert "Review queue" in body


# =========================================================================== #
# D3 — humanised, severity-weighted parse notes
# =========================================================================== #
def test_humanise_known_code():
    assert webmod._humanise_parse_code("course_inferred") == "Course length inferred"
    assert webmod._humanise_parse_code("no_results") == "No results found"


def test_humanise_unknown_code_is_titlecased_not_raw():
    out = webmod._humanise_parse_code("some_brand_new_code")
    assert out == "Some brand new code"
    assert "_" not in out


def test_humanise_empty_code():
    assert webmod._humanise_parse_code("") == "Parse note"
    assert webmod._humanise_parse_code(None) == "Parse note"


def test_parse_notes_empty_is_blank():
    assert webmod._parse_notes_card([]) == ""
    assert webmod._parse_notes_card(None) == ""


def test_parse_notes_humanises_and_keeps_raw_code():
    html = webmod._parse_notes_card([
        {"code": "course_inferred", "message": "Course inferred as LC.", "severity": "info"},
    ])
    assert "Parse notes" in html
    assert "We never silently guess" in html
    assert "Course length inferred" in html      # friendly label, bolded
    assert "Course inferred as LC." in html       # the message
    assert "course_inferred" in html              # raw code retained for support


def test_parse_notes_errors_lead_under_needs_attention():
    html = webmod._parse_notes_card([
        {"code": "course_inferred", "message": "ok", "severity": "info"},
        {"code": "no_results", "message": "nothing parsed", "severity": "error"},
    ])
    assert "Needs your attention" in html
    assert "Inferred &amp; ambiguous" in html
    # The error block is rendered before the inferred block.
    assert html.index("Needs your attention") < html.index("Inferred &amp; ambiguous")
    assert "No results found" in html


def test_parse_notes_truncates_with_more_count():
    many = [
        {"code": f"orphan_swim", "message": f"swim {i}", "severity": "info"}
        for i in range(20)
    ]
    html = webmod._parse_notes_card(many)
    assert "+8 more" in html                       # 20 − 12 cap


def test_parse_notes_singular_more_label():
    many = [
        {"code": "orphan_swim", "message": f"s{i}", "severity": "info"}
        for i in range(13)
    ]
    html = webmod._parse_notes_card(many)
    assert "+1 more note " in html                 # singular, not "notes"


def test_review_renders_humanised_parse_notes(client):
    _write_run("warned1", {
        "file_name": "meet.hy3", "meet": {"name": "Spring Open"}, "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 50, "our_swim_count": 10, "club_filter": "X",
        "parse_warnings": [
            {"code": "course_inferred", "message": "Course inferred as LC.", "severity": "info"},
            {"code": "pb_enrichment_failed", "message": "PB lookup timed out.", "severity": "warn"},
        ],
    })
    body = _review_body(client, "warned1")
    assert "Parse notes" in body
    assert "Course length inferred" in body
    assert "PB history lookup incomplete" in body
    assert "We never silently guess" in body


# =========================================================================== #
# D4 — the success/error toast bridge
# =========================================================================== #
def test_flash_toast_outside_request_context_is_noop():
    # Called with no active request (e.g. a background task) — must not raise.
    webmod._flash_toast("nothing here")  # no exception == pass


def test_toast_message_set_via_textcontent_not_innerhtml(client):
    """MH.toast must inject its (server-echoed) message via textContent, never
    concatenate it into innerHTML — otherwise a filename/caption/error string
    is a DOM XSS sink."""
    body = client.get("/").get_data(as_text=True)
    assert "MH.toast = function" in body
    # The message slot is captured and filled by textContent (D-1 refactored the
    # inline querySelector into a `msgSlot` local; the XSS-safe contract holds).
    assert "t.querySelector('.mh-toast-msg')" in body
    assert "msgSlot.textContent" in body
    # The old raw-concat sink is gone.
    assert "min-width:0\">' + message + '</div>'" not in body


def test_run_delete_js_shows_failure_toast():
    """A failed delete (run already gone in another tab, 404/400 → HTML → {})
    must surface an honest error toast, not look like a dead click on Activity /
    My Season / Settings."""
    js = webmod._RUN_DELETE_JS
    # Both the !j.ok branch and the network .catch of each handler toast.
    assert js.count("Could not delete — reload and try again.") >= 4
    assert "'error'" in js


def test_delete_run_flash_confirms_once(client, monkeypatch):
    # Resolve ownership as a legacy untagged run and stub the real deletion so
    # the test exercises only the redirect + flash bridge.
    monkeypatch.setattr(webmod, "_run_owner_profile_id", lambda rid: "")
    monkeypatch.setattr(webmod, "_delete_run", lambda rid: True)

    r = client.post("/privacy/run/delme/delete", data={}, follow_redirects=True)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "MH.toast(" in body
    assert "Run deleted." in body

    # One-shot: a fresh page no longer carries the toast.
    body2 = client.get("/").get_data(as_text=True)
    assert "Run deleted." not in body2


def test_ajax_delete_returns_json_without_flash(client, monkeypatch):
    monkeypatch.setattr(webmod, "_run_owner_profile_id", lambda rid: "")
    monkeypatch.setattr(webmod, "_delete_run", lambda rid: True)
    r = client.post(
        "/privacy/run/delme/delete",
        data={}, headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "deleted": "delme"}


def test_flash_message_is_json_encoded_safe():
    """The bridge must encode the message so it can't break out of the JS
    string / inject markup, even though all current callers pass plain text."""
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_request_context("/"):
        webmod._flash_toast('"></script><b>x</b>', "success")
        html = webmod._layout("T", "<p>body</p>")
    assert "</script><b>x</b>" not in html         # never raw in the document
    assert "MH.toast(" in html
