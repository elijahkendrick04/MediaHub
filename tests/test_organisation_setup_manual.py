"""Manual-mode organisation setup — /organisation/setup/manual.

The setup page offers an explicit choice: AI build (capture from links)
or manual build (dropdowns + pickers for everything the system needs,
no AI calls, no inference). These tests pin the manual route's contract:
profile created with exactly what was picked, colours land on
brand_palette_manual (the user-override slot), and the profile counts
as ready without any AI capture having run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(client, web_module):
    import mediahub.web.club_profile as cp

    return client, web_module, cp


def _post_manual(c, **overrides):
    form = {
        "display_name": "Harbour City Swim Club",
        "org_type": "swimming_club",
        "country": "United Kingdom",
        "governing_body": "Swim England",
        "caption_tone": "data-led",
        "platforms": ["instagram", "facebook"],
        "tone_notes": "Proud but understated. First names. Thank the officials.",
        "manual_primary": "#0a2540",
        "manual_secondary": "#f4d58d",
        "manual_accent": "#d4ff3a",
    }
    form.update(overrides)
    return c.post("/organisation/setup/manual", data=form)


class TestManualSetup:
    def test_creates_ready_profile_without_ai(self, app_client):
        c, wm, cp = app_client
        resp = _post_manual(c)
        assert resp.status_code == 302

        profs = cp.list_profiles()
        assert len(profs) == 1
        p = profs[0]
        assert p.display_name == "Harbour City Swim Club"
        assert p.org_type == "swimming_club"
        assert p.country == "United Kingdom"
        assert p.tone == "data-led"
        assert p.caption_tone == "data-led"
        assert sorted(p.platforms) == ["facebook", "instagram"]
        assert p.brand_palette_manual["primary"] == "#0a2540"
        assert p.brand_palette_manual["secondary"] == "#f4d58d"
        assert p.brand_palette_manual["accent"] == "#d4ff3a"
        # Legacy mirrors follow the manual picks.
        assert p.brand_primary == "#0a2540"
        assert p.brand_secondary == "#f4d58d"
        # No AI ran: nothing extracted, no voice summary — yet the
        # profile is usable because the palette was confirmed by a human.
        assert not p.brand_palette_extracted
        assert not p.brand_voice_summary
        assert p.is_ready()

    def test_fourth_colour_only_when_opted_in(self, app_client):
        c, wm, cp = app_client
        _post_manual(c, manual_use_fourth="1", manual_fourth="#112233")
        p = cp.list_profiles()[0]
        assert p.brand_palette_use_fourth is True
        assert p.brand_palette_manual["fourth"] == "#112233"

    def test_no_fourth_by_default(self, app_client):
        c, wm, cp = app_client
        _post_manual(c, manual_fourth="#112233")  # picker value but box unticked
        p = cp.list_profiles()[0]
        assert p.brand_palette_use_fourth is False
        assert "fourth" not in p.brand_palette_manual

    def test_invalid_colour_dropped_not_guessed(self, app_client):
        c, wm, cp = app_client
        _post_manual(c, manual_accent="not-a-colour")
        p = cp.list_profiles()[0]
        assert "accent" not in p.brand_palette_manual
        assert p.brand_palette_manual["primary"] == "#0a2540"

    def test_unknown_tone_and_platform_rejected(self, app_client):
        c, wm, cp = app_client
        _post_manual(c, caption_tone="sarcastic", platforms=["instagram", "myspace"])
        p = cp.list_profiles()[0]
        assert p.tone == "warm-club"  # safe default, never an invented tone
        assert p.platforms == ["instagram"]

    def test_blank_name_redirects_without_creating(self, app_client):
        c, wm, cp = app_client
        resp = c.post("/organisation/setup/manual", data={"display_name": "  "})
        assert resp.status_code == 302
        assert cp.list_profiles() == []

    def test_setup_page_offers_both_modes(self, app_client):
        c, wm, cp = app_client
        html = c.get("/organisation/setup").get_data(as_text=True)
        assert "AI build" in html
        assert "Manual build" in html
        assert "/organisation/setup/manual" in html
        assert "mh-setup-manual-panel" in html
