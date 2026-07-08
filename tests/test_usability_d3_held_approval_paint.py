"""D-3 — a single-card approve that the server HELD for another approver must
not keep claiming "Approved ✓".

With a group-approver rule the API records the vote and answers
``{ok:true, status:'queue', reason:<text>}`` — the card is still queued. The
per-card success handler used to ignore the returned status, so the optimistic
"Approved ✓" paint stood and the card silently reverted on the next reload.
This guards the handler now repainting to the server's actual status and
toasting the held-for-approval reason.
"""

from __future__ import annotations

import pytest

ORG = "d3-org"


@pytest.fixture
def page_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="D3 SC"))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c.get("/free-text").get_data(as_text=True)


def test_success_handler_reads_returned_status(page_html):
    # The handler now derives the applied status from the server response.
    assert "(result && result.status) || status" in page_html


def test_held_card_repaints_and_toasts_reason(page_html):
    # When the applied status differs from the requested one, repaint to the
    # server's truth and surface the held-for-approval reason.
    assert "applied !== status" in page_html
    assert "paintState(applied)" in page_html
    assert "still held for another approver" in page_html
