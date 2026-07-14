"""tests/test_empty_states_polished.py — sponsors and collections use the
polished shared empty state, not a bare grey line (audit finding D-34).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client(web_module):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    app = web_module.create_app()
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
