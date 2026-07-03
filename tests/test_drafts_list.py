"""Regression coverage for the /drafts list route.

A stub pack's ``created_at`` is always written as an ISO string by
``save_pack`` (see ``club_platform/stub_pack_store.py``), but ``list_packs``
reads it back with a bare ``dict.get`` and applies no type check — so a
hand-edited, migrated, or otherwise malformed pack record whose
``created_at`` isn't a string used to blow up ``stub_packs_list`` with an
unhandled ``TypeError`` (int/None aren't subscriptable), 500ing the whole
Drafts page instead of just skipping the bad timestamp.
"""

from __future__ import annotations

import json

import pytest

ORG = "drafts-org"


@pytest.fixture
def app_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="Drafts SC"))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _pin(c):
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG


def test_drafts_list_renders_normal_pack(app_org):
    from mediahub.club_platform.stub_pack_store import save_pack

    save_pack(
        "free_text",
        {"free_text": "Great swim today!"},
        [{"platform": "instagram", "caption": "Nice swim", "confidence": 0.8}],
        profile_id=ORG,
    )
    with app_org.test_client() as c:
        _pin(c)
        r = c.get("/drafts")
        assert r.status_code == 200


def test_drafts_list_survives_non_string_created_at(app_org, tmp_path):
    # Simulate a malformed/legacy pack record on disk — bypasses save_pack
    # entirely so created_at can carry a type save_pack would never write.
    packs_dir = tmp_path / "stub_packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    (packs_dir / "malformed1.json").write_text(
        json.dumps(
            {
                "pack_id": "malformed1",
                "profile_id": ORG,
                "created_at": 1234567890,
                "stub_type": "free_text",
                "title": "Malformed timestamp draft",
                "form_data": {},
                "cards": [],
            }
        )
    )
    with app_org.test_client() as c:
        _pin(c)
        r = c.get("/drafts")
        assert r.status_code == 200
        assert "Malformed timestamp draft" in r.get_data(as_text=True)
