"""G-6 — draft cards get labelled Approve / Re-queue buttons, not a
click-to-cycle pill.

Stub draft cards used to show a tiny pill whose text was the raw status word
("queue"/"approved"), toggling on click and resetting only via a right-click
gesture — undiscoverable, and unavailable on touch. The pill is now a
read-only humanised badge ("In queue" / "Approved" / "Rejected") and the
state changes through an explicit labelled button in the card's action row
(Approve while queued or rejected, Re-queue once approved), wired to the same
persisted status endpoint. The right-click gesture is gone.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app):
    """Isolated app via the shared conftest fixtures (no ``importlib.reload``)
    with a saved, active ``club-a`` profile — #130 fixture-sprawl migration."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "club-a"
        yield c


def _save_pack(profile_id="club-a"):
    from mediahub.club_platform.stub_pack_store import save_pack

    return save_pack(
        "free_text",
        {"free_text": "Sam swam a huge PB"},
        [
            {"platform": "Instagram", "caption": "Huge PB for Sam!", "confidence": None},
            {"platform": "Stories", "caption": "What a swim.", "confidence": None},
        ],
        profile_id=profile_id,
    )


def test_render_uses_badge_and_labelled_buttons():
    from mediahub.club_platform.stubs import render_cards_html

    html = render_cards_html(
        {
            "cards": [
                {"platform": "Instagram", "caption": "Queued card", "status": "queue"},
                {"platform": "Stories", "caption": "Approved card", "status": "approved"},
                {"platform": "Facebook", "caption": "Rejected card", "status": "rejected"},
            ]
        },
        back_url="/x",
        title="Draft",
        pack_id="abc123",
        status_api_base="/api/drafts/abc123/card",
    )
    # Old interaction gone: no pill control, no right-click reset.
    assert "stub-wf-pill" not in html
    assert "contextmenu" not in html
    assert "Right-click" not in html
    # Status is a read-only badge with humanised labels.
    assert 'class="stub-wf-badge"' in html
    assert "In queue" in html
    assert "Approved" in html
    assert "Rejected" in html
    # Raw enum words never render as a control's face.
    assert ">queue</button>" not in html
    # Explicit labelled controls: Approve for queue/rejected, Re-queue once approved.
    assert html.count(">Approve</button>") == 2
    assert html.count(">Re-queue</button>") == 1
    # Buttons post to the same persisted status endpoint the pill used.
    assert 'data-url="/api/drafts/abc123/card/0/status"' in html


def test_unsaved_render_has_no_workflow_controls():
    from mediahub.club_platform.stubs import render_cards_html

    html = render_cards_html(
        {"cards": [{"platform": "Instagram", "caption": "One-shot"}]},
        back_url="/x",
        title="Draft",
    )
    assert "stub-wf-btn" not in html
    assert "stub-wf-badge" not in html


def test_draft_page_serves_buttons_and_status_roundtrip(client):
    pack = _save_pack()
    pid = pack["pack_id"]

    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    assert 'class="stub-wf-badge"' in view
    assert "In queue" in view
    assert ">Approve</button>" in view
    assert "contextmenu" not in view

    # The button's POST target still persists the status.
    r = client.post(f"/api/drafts/{pid}/card/0/status", data={"status": "approved"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "approved"

    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    assert "Approved" in view
    assert ">Re-queue</button>" in view

    # Re-queue sends it back.
    r = client.post(f"/api/drafts/{pid}/card/0/status", data={"status": "queue"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "queue"
