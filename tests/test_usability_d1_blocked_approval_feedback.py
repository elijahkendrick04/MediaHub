"""D-1 — a blocked approval must surface the server's plain-English reason, not
the raw gate code, and must not pile a contradictory "try again" toast on top
of a permanent safeguarding block.

The server already answers consent / brand-lock / open-task gates with
``{error:<code>, reason:<human text>}`` (covered by test_consent_gating). This
guards the *client* half the audit flagged: ``mhWorkflowSet`` used to build its
toast from ``o.body.error||o.body.message`` (showing "consent_blocked" raw) and
then let the generic catch fire "Could not save — reverted. Try again." — wrong
advice for a block that can never succeed. It also had no path to resolve an
open-task block from the review page.
"""

from __future__ import annotations

import pytest

ORG = "d1-org"


@pytest.fixture
def page_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="D1 SC"))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    # The workflow + toast JS lives in the global layout, present on every page.
    return c.get("/free-text").get_data(as_text=True)


def test_workflow_toast_prefers_human_reason_over_raw_code(page_html):
    # The reason (plain English) must be preferred; the old raw-code fallback
    # "o.body.error || o.body.message" as the primary message is gone.
    assert "body.reason || body.message" in page_html
    assert "o.body.error || o.body.message" not in page_html
    # The dishonest "Workflow update failed: <code>" prefix is gone.
    assert "Workflow update failed: " not in page_html


def test_gate_block_suppresses_generic_retry_toast(page_html):
    # A 4xx-with-code is flagged as a deliberate gate block…
    assert "err.gate" in page_html
    # …and the generic "Try again" toast is now conditional on it NOT being a
    # handled gate block (was previously unconditional).
    assert "err.handled || err.gate" in page_html
    assert "Could not save — reverted. Try again." in page_html  # still there for network errors


def test_tasks_open_offers_builder_deeplink(page_html):
    assert "tasks_open" in page_html
    assert "Open in builder" in page_html
    assert "/pack/' + encodeURIComponent(runId)" in page_html


def test_transient_server_error_stays_retryable(page_html):
    # A 5xx / transient failure is NOT a gate: mhWorkflowSet only marks
    # err.handled inside the isGate branch, so the caller still shows the
    # retryable "reverted — try again" toast (review-workflow fix).
    assert "if (isGate) {" in page_html
    assert "err.handled = true;  // already toasted" in page_html
    # err.handled is no longer set unconditionally for every error response.
    assert (
        "err.handled = true;   // already toasted — the caller must not double-toast"
        not in page_html
    )


def test_toast_supports_optional_action_link(page_html):
    # MH.toast gained a backward-compatible 4th action param that renders a
    # trusted same-origin anchor.
    assert "MH.toast = function(message, type, ms, action)" in page_html
    assert "mh-toast-action" in page_html
