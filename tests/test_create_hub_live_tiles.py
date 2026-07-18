"""tests/test_create_hub_live_tiles.py — Live meet and Season wraps are live,
linked Create tiles, not disabled "Coming soon" tiles (findings C-5 / C-6).

Both /live and /wraps are fully-built, working pages, but the Create hub
rendered them as greyed-out "Coming soon" tiles with href="#" — the only place
they were mentioned — so volunteers concluded the features didn't exist and the
pages were reachable only by typing the URL.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def make_client(app):
    app.config["ENFORCE_ORG_GATE"] = True
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="t", display_name="Test club", brand_voice_summary="Friendly.")
    )
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "t"})
        yield c


def test_live_and_wraps_tiles_link_through(make_client):
    body = make_client.get("/make").get_data(as_text=True)
    # The tiles now link to the real pages...
    assert 'href="/live"' in body, "Live meet tile must link to /live (C-5)"
    assert 'href="/wraps"' in body, "Season wraps tile must link to /wraps (C-6)"
    # ...with an "Open" CTA, not the dead "Soon".
    assert "Open Live meet" in body
    assert "Open Season wraps" in body


def test_tiles_are_not_disabled_coming_soon(make_client):
    body = make_client.get("/make").get_data(as_text=True)
    # No disabled 'Coming soon' Live/Wraps tile remains (the honest fallback
    # only fires when the route is genuinely absent, which it isn't here).
    assert 'onclick="return false"' not in body or "Coming soon" not in body
