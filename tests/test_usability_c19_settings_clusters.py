"""C-19 — Settings is grouped into four headed clusters, not a flat wall.

The landing used to render ~17 undifferentiated tiles in one grid. It now
renders four headed clusters in a fixed order — Your club, Content & brand,
Account & billing, System — with the two "Coming soon" placeholders (J-10)
collapsed into a muted compact strip at the very bottom. The twin tiles get
clearly differentiated copy, the "Pricing & plans" tile is gone (the pricing
page itself stays, linked from inside the billing section), and the hero is
retitled from "Operations & data" to plain "Settings".
"""

from __future__ import annotations

import re

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


@pytest.fixture
def settings_html(client):
    return client.get("/settings").get_data(as_text=True)


# The full tile inventory for a non-operator: every tile survives the
# regrouping (nothing dropped except the Pricing tile, asserted separately).
CLUSTERS = {
    "club": ["Organisation &amp; brand", "Team members", "Sponsors", "Club data", "Activity"],
    "content": ["Brand platform", "Templates", "Typography &amp; fonts", "Audio &amp; voiceover"],
    "account": ["Account", "Billing &amp; plan"],
    "system": ["System status", "AI governance", "Privacy &amp; data"],
    "soon": ["Auto scheduling", "Autonomy"],
}


def test_hero_says_settings(settings_html):
    assert "<h1>Settings</h1>" in settings_html
    # The old "Operations & data" hero title is gone.
    assert "Operations &amp;" not in settings_html


def test_four_headed_clusters_render_in_order(settings_html):
    heads = re.findall(
        r'<h2 class="mh-settings-cluster-head"[^>]*>([^<]+)</h2>', settings_html
    )
    assert heads == [
        "Your club",
        "Content &amp; brand",
        "Account &amp; billing",
        "System",
        "Coming soon",
    ]
    # ...and the section anchors appear in the same document order.
    idx = [
        settings_html.index(f'id="mh-settings-{key}"')
        for key in ("club", "content", "account", "system", "soon")
    ]
    assert idx == sorted(idx)


def test_every_surviving_tile_present_exactly_once(settings_html):
    all_titles = [t for titles in CLUSTERS.values() for t in titles]
    for title in all_titles:
        assert settings_html.count(f'<h3 style="margin:0">{title}</h3>') == 1, (
            f"tile {title!r} should appear exactly once"
        )
    # No extra tiles snuck in (non-operator: 16 tile anchors in total).
    anchors = re.findall(r'class="mh-template mh-glow-border', settings_html)
    assert len(anchors) == len(all_titles)


def test_each_tile_sits_in_its_cluster(settings_html):
    """Every tile renders inside its own cluster's section, not a neighbour's."""
    bounds = {
        key: settings_html.index(f'id="mh-settings-{key}"')
        for key in ("club", "content", "account", "system", "soon")
    }
    ends = list(bounds.values())[1:] + [len(settings_html)]
    for (key, start), end in zip(bounds.items(), ends):
        section = settings_html[start:end]
        for title in CLUSTERS[key]:
            assert f'<h3 style="margin:0">{title}</h3>' in section, (
                f"tile {title!r} missing from the {key!r} cluster"
            )


def test_coming_soon_strip_is_compact_and_last(settings_html):
    strip_at = settings_html.index('class="mh-settings-soon-strip"')
    # The strip sits below all four working clusters.
    assert settings_html.index('id="mh-settings-system"') < strip_at
    strip = settings_html[strip_at:]
    assert "Auto scheduling" in strip
    assert "Autonomy" in strip
    # J-10 badges and links survive the collapse.
    assert strip.count('<span class="mh-template-soon-badge">Coming soon</span>') == 2
    assert 'class="mh-template mh-glow-border mh-template-soon"' in strip
    assert "/settings/scheduling" in strip
    assert "/settings/autonomy" in strip
    # The strip items are muted placeholders: no "Open" CTA inside the strip.
    assert ">Open</span>" not in strip


def test_twin_tiles_have_differentiated_copy(settings_html):
    # Organisation & brand = the club's identity...
    assert "identity — name, colours, logos and voice" in settings_html
    # ...Brand platform = kits & governance.
    assert "token locks and approvers" in settings_html


def test_pricing_tile_gone_but_page_linked_from_billing(client, settings_html):
    # The second pricing tile is gone from Settings...
    assert "Pricing &amp; plans" not in settings_html
    # ...but the pricing page itself stays.
    assert client.get("/pricing").status_code == 200
    # ...and the billing section carries the replacement link.
    client.post(
        "/signup",
        data={"email": "u@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    billing_html = client.get("/billing").get_data(as_text=True)
    assert "See plans &amp; pricing &rarr;" in billing_html
    assert 'href="/pricing"' in billing_html
