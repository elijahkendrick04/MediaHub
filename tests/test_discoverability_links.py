"""tests/test_discoverability_links.py — orphaned surfaces are now reachable
from navigation (audit findings C-3 and C-7).

C-3: Drafts (where every free-text / spotlight / preview output lands) had no
link from the nav, home, or Create hub. C-7: the consent registry and the
athlete-rights (DSR) tracker — the two pages a safeguarding officer needs most
— were reachable only by typing the URL.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="t", display_name="Test club", brand_voice_summary="Friendly."))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "t"})
        yield c


def test_drafts_reachable_from_create_hub(client):
    body = client.get("/make").get_data(as_text=True)
    assert 'href="/drafts"' in body, "Create hub must link to Drafts (C-3)"


def test_drafts_reachable_from_account_menu(client):
    # The account menu renders on every signed-in page (here: the home shell).
    body = client.get("/make").get_data(as_text=True)
    assert body.count('href="/drafts"') >= 1
    # And the menu item label is present.
    assert ">Drafts<" in body


def test_club_data_reachable_from_account_menu(client):
    """C-4: the club-data tools (records, ask-the-data, data hub) are surfaced
    from the account menu on every signed-in page, not buried in Settings."""
    body = client.get("/make").get_data(as_text=True)
    assert "/settings/clubdata" in body, "Club data must be linked from the account menu (C-4)"
    assert ">Club data<" in body


def test_consent_and_dsr_reachable_from_settings_privacy(client):
    body = client.get("/settings/privacy").get_data(as_text=True)
    assert "/organisation/consent" in body, "consent registry must be linked (C-7)"
    assert "/organisation/athlete-rights" in body, "athlete-rights/DSR must be linked (C-7)"
