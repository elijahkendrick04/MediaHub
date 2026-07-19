"""H-9 — every saved-draft card can edit its caption inline.

The free-text quick path promised "edit the caption … from there", but draft
cards offered only Copy caption / Create graphic, and the caption/assist APIs
400 `unsupported_type` for non-spotlight packs. Saved-draft cards now carry an
"Edit caption" affordance revealing a textarea + Save that persists through
the pack store (plain persistence, no AI), tenant-gated like the sibling
caption endpoints.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    save_profile(ClubProfile(profile_id="club-b", display_name="Club B"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def _save_pack(profile_id="club-a", source="quick"):
    from mediahub.club_platform.stub_pack_store import save_pack

    return save_pack(
        "free_text",
        {"free_text": "Sam swam a huge PB", "source": source},
        [{"platform": "Instagram", "caption": "Huge PB for Sam!", "confidence": None}],
        profile_id=profile_id,
    )


def test_draft_page_offers_caption_editing(client):
    pack = _save_pack()
    view = client.get(f"/drafts/{pack['pack_id']}").get_data(as_text=True)
    assert ">Edit caption</button>" in view
    assert 'class="stub-cap-editor"' in view
    assert ">Save caption</button>" in view
    assert f"/api/drafts/{pack['pack_id']}/card/0/caption/save" in view


def test_save_persists_the_edited_caption(client):
    from mediahub.club_platform.stub_pack_store import load_pack

    pack = _save_pack()
    pid = pack["pack_id"]
    r = client.post(
        f"/api/drafts/{pid}/card/0/caption/save",
        json={"caption": "Rewritten by hand — even better."},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["caption"] == "Rewritten by hand — even better."

    rec = load_pack(pid)
    assert rec["cards"][0]["caption"] == "Rewritten by hand — even better."
    # Other card fields survive the edit.
    assert rec["cards"][0]["platform"] == "Instagram"

    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    assert "Rewritten by hand" in view


def test_empty_caption_is_rejected(client):
    from mediahub.club_platform.stub_pack_store import load_pack

    pack = _save_pack()
    pid = pack["pack_id"]
    r = client.post(f"/api/drafts/{pid}/card/0/caption/save", json={"caption": "   "})
    assert r.status_code == 400
    assert r.get_json()["error"] == "empty_caption"
    assert load_pack(pid)["cards"][0]["caption"] == "Huge PB for Sam!"


def test_bad_card_index_404s(client):
    pack = _save_pack()
    r = client.post(f"/api/drafts/{pack['pack_id']}/card/9/caption/save", json={"caption": "x"})
    assert r.status_code == 404


def test_foreign_org_cannot_edit(client):
    from mediahub.club_platform.stub_pack_store import load_pack

    pack = _save_pack(profile_id="club-a")
    pid = pack["pack_id"]
    with client.session_transaction() as s:
        s["active_profile_id"] = "club-b"
    r = client.post(f"/api/drafts/{pid}/card/0/caption/save", json={"caption": "stolen"})
    assert r.status_code == 404
    assert load_pack(pid)["cards"][0]["caption"] == "Huge PB for Sam!"


def test_copy_caption_reads_the_live_caption():
    # The Copy caption button reads the card's live (possibly just-edited)
    # caption from the DOM, falling back to the embedded literal.
    from mediahub.club_platform.stubs import render_cards_html

    html = render_cards_html(
        {"cards": [{"platform": "Instagram", "caption": "Original"}]},
        back_url="/x",
        title="Draft",
        pack_id="abc123",
        status_api_base="/api/drafts/abc123/card",
    )
    assert 'querySelector(".mh-card-caption")' in html
    assert "capEl.textContent" in html
