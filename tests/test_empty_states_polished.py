"""tests/test_empty_states_polished.py — sponsors and collections use the
polished shared empty state, not a bare grey line (audit finding D-34).
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="t", display_name="Test club", brand_voice_summary="Hi"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "t"
    return c


def test_sponsors_empty_state_is_polished(client):
    body = client.get("/sponsors").get_data(as_text=True)
    assert "mh-emptystate" in body, "sponsors must use the shared empty state (D-34)"
    assert "No sponsors yet" in body


def test_collections_empty_state_is_polished(client):
    body = client.get("/collections").get_data(as_text=True)
    assert "mh-emptystate" in body, "collections must use the shared empty state (D-34)"
    assert "No collections yet" in body
