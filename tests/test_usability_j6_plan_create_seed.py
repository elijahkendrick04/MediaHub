"""J-6 — the plan's "Create →" seeds the free-text tool with the ranked idea.

The plan hero promised "open the right tool with that idea", but create_link
was a bare url_for(...) — every tool opened blank. Now: items whose target is
the free-text surface carry the idea as ?seed=<title — reason>, the free-text
landing prefills its textarea from that param (escaped, capped at 500 chars),
other tools keep plain links, and the hero copy says only what's true.
"""

from __future__ import annotations

import re
from urllib.parse import unquote_plus

import html as _htmllib

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


_PLAN = {
    "sport": "swimming",
    "sport_display": "Swimming",
    "generated_at": "2026-07-01T10:00:00+00:00",
    "horizon_days": 14,
    "source_counts": {"own": 1, "external": 0, "direct": 1},
    "notes": [],
    "items": [
        {
            "post_type": "free_text",
            "title": "County recap",
            "score": 80,
            "implemented": True,
            "sources_used": ["own"],
            "reasons": ["Three swimmers set PBs at the county meet"],
        },
        {
            "post_type": "event_preview",
            "title": "Preview the gala",
            "score": 60,
            "implemented": True,
            "sources_used": ["direct"],
            "reasons": ["You told us the gala is on the 12th"],
        },
    ],
}


def _plan_html(client, monkeypatch):
    import mediahub.content_engine.planner as planner

    monkeypatch.setattr(planner, "load_latest_plan", lambda pid: dict(_PLAN))
    return client.get("/plan").get_data(as_text=True)


def test_free_text_create_link_carries_the_idea(client, monkeypatch):
    html = _plan_html(client, monkeypatch)
    hrefs = [
        _htmllib.unescape(m)
        for m in re.findall(r'href="([^"]+)"', html)
        if "seed=" in m
    ]
    assert hrefs, "no Create link carried a seed"
    seeded = unquote_plus(hrefs[0])
    assert seeded.startswith("/free-text?")
    assert "County recap" in seeded
    assert "Three swimmers set PBs at the county meet" in seeded


def test_other_tools_keep_plain_links(client, monkeypatch):
    html = _plan_html(client, monkeypatch)
    # The event-preview item links straight to its form with no seed param.
    assert re.search(r'href="/weekend-preview"', html)


def test_hero_copy_is_honest(client, monkeypatch):
    html = _plan_html(client, monkeypatch)
    assert "with that idea" not in html
    assert "free-text ideas arrive pre-filled" in html


def test_free_text_landing_prefills_from_seed(client):
    page = client.get(
        "/free-text", query_string={"seed": "County recap — Three swimmers set PBs"}
    ).get_data(as_text=True)
    m = re.search(r'<textarea id="ft-prompt"[^>]*>([^<]*)</textarea>', page)
    assert m, "prompt textarea not found"
    assert "County recap" in _htmllib.unescape(m.group(1))
    assert "Three swimmers set PBs" in _htmllib.unescape(m.group(1))


def test_seed_is_escaped_and_capped(client):
    long_seed = "x" * 600 + '<script>alert(1)</script>'
    page = client.get("/free-text", query_string={"seed": long_seed}).get_data(
        as_text=True
    )
    assert "<script>alert(1)</script>" not in page
    m = re.search(r'<textarea id="ft-prompt"[^>]*>([^<]*)</textarea>', page)
    assert m
    # Capped server-side at 500 characters (so the script tag never made it in).
    assert len(_htmllib.unescape(m.group(1))) <= 500
