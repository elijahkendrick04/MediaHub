"""J-10 — the two placeholder Settings tiles must read as "Coming soon" before
the click.

"Auto scheduling" and "Autonomy" occupied two full tiles with the same weight
and the same "Open →" CTA as working features; clicking either cost a page load
to reach a single placeholder card. Both tiles now carry a visible "Coming soon"
badge and a muted CTA, while the other tiles still say "Open".
"""

from __future__ import annotations

import pytest

from mediahub.web.club_profile import ClubProfile, save_profile


@pytest.fixture
def settings_html(client):
    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return client.get("/settings").get_data(as_text=True)


def test_coming_soon_tiles_badged(settings_html):
    assert '<span class="mh-template-soon-badge">Coming soon</span>' in settings_html
    # Exactly the two placeholder tiles get the badge markup (the CSS selector,
    # inlined on the page, is excluded by matching the class attribute form).
    assert settings_html.count('class="mh-template-soon-badge"') == 2
    # …and both carry the muted tile class.
    assert 'class="mh-template mh-glow-border mh-template-soon"' in settings_html


def test_working_tiles_still_open(settings_html):
    # The grid still has "Open" CTAs on the working tiles.
    assert ">Open</span>" in settings_html
    # …and the two placeholders show "Coming soon" as their CTA.
    assert ">Coming soon</span>" in settings_html
