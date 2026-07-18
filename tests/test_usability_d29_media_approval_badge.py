"""D-29 — the media library must show and let you undo photo approval.

Bulk "Approve" set approval_status='approved' (weighting the photo picker) but
the table had no approval column, so after the toast faded approved and draft
photos looked identical — and there was no unapprove action. The table now
carries a Draft/Ready badge (updated in place after a bulk mark), an "Unapprove"
bulk action, and the button reads "Mark ready for cards".
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def env(client, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    client.post("/api/organisation/active", data={"profile_id": "org-test"})
    return {"client": client, "tmp": tmp_path}


def _seed_asset(tmp_path, approval_status="draft"):
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    p = tmp_path / f"{uuid.uuid4().hex[:6]}.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
    asset = MediaAsset(
        id="",
        filename="p.jpg",
        path=str(p),
        type="athlete_photo",
        profile_id="org-test",
        permission_status="approved_by_club",
        approval_status=approval_status,
        safe_for_minors=True,
    )
    return get_store().save(asset).id


def _status(aid):
    from mediahub.media_library.store import get_store

    return get_store().get(aid).approval_status


def test_draft_badge_and_new_buttons_render(env):
    _seed_asset(env["tmp"], approval_status="draft")
    html = env["client"].get("/media-library").get_data(as_text=True)
    assert "<th>Status</th>" in html
    assert "data-mh-approval" in html
    assert ">Draft</span>" in html
    # The renamed, unambiguous button + the new undo action.
    assert "Mark ready for cards" in html
    assert 'data-mh-bulk="unapprove"' in html
    assert "/api/media-library/bulk-unapprove" in html


def test_bulk_approve_marks_ready_badge(env):
    aid = _seed_asset(env["tmp"], approval_status="draft")
    r = env["client"].post("/api/media-library/bulk-approve", json={"ids": [aid]})
    assert r.status_code == 200 and r.get_json()["n_ok"] == 1
    assert _status(aid) == "approved"
    html = env["client"].get("/media-library").get_data(as_text=True)
    assert ">Ready</span>" in html


def test_bulk_unapprove_reverts_to_draft(env):
    aid = _seed_asset(env["tmp"], approval_status="approved")
    r = env["client"].post("/api/media-library/bulk-unapprove", json={"ids": [aid]})
    assert r.status_code == 200 and r.get_json()["n_ok"] == 1
    assert _status(aid) == "draft"


def test_bulk_unapprove_empty_selection_400(env):
    r = env["client"].post("/api/media-library/bulk-unapprove", json={"ids": []})
    assert r.status_code == 400


def test_bulk_unapprove_foreign_asset_not_touched(env):
    """A photo owned by another org is never demoted through this session."""
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    p = env["tmp"] / "other.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
    other = (
        get_store()
        .save(
            MediaAsset(
                id="",
                filename="other.jpg",
                path=str(p),
                type="athlete_photo",
                profile_id="org-other",
                approval_status="approved",
            )
        )
        .id
    )
    r = env["client"].post("/api/media-library/bulk-unapprove", json={"ids": [other]})
    assert r.status_code == 200
    assert all(not x["ok"] for x in r.get_json()["results"])
    assert _status(other) == "approved"
