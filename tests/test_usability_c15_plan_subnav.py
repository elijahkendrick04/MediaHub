"""C-15 — the five planner sub-views share one navigation strip.

/plan offered only Calendar + Performance; Board and Grid were reachable only
from calendar-toolbar buttons; analytics linked back only to /plan. All five
pages (Plan, Calendar, Board, Grid, Performance) now render the same shared
sub-nav strip from one helper, with the current view marked, replacing the
ad-hoc per-page link subsets.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture()
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


_PAGES = {
    "/plan": "/plan",
    "/plan/calendar": "/plan/calendar",
    "/plan/board": "/plan/board",
    "/plan/grid": "/plan/grid",
    "/plan/analytics": "/plan/analytics",
}
_ALL_LINKS = ("/plan", "/plan/calendar", "/plan/board", "/plan/grid", "/plan/analytics")


def _subnav(html: str) -> str:
    m = re.search(r'<nav aria-label="Plan views".*?</nav>', html, re.S)
    assert m, "shared plan sub-nav not found"
    return m.group(0)


@pytest.mark.parametrize("path", list(_PAGES))
def test_every_planner_page_renders_the_full_subnav(client, path):
    html = client.get(path).get_data(as_text=True)
    nav = _subnav(html)
    for target in _ALL_LINKS:
        assert f'href="{target}"' in nav, f"{path} sub-nav missing link to {target}"


@pytest.mark.parametrize("path", list(_PAGES))
def test_active_view_is_marked(client, path):
    html = client.get(path).get_data(as_text=True)
    nav = _subnav(html)
    active = re.findall(r'<a class="btn primary" href="([^"]+)" aria-current="page"', nav)
    assert active == [_PAGES[path]]


def test_ad_hoc_link_subsets_replaced(client):
    # The calendar toolbar keeps only month navigation; its old partial
    # Grid/Board/Performance buttons are gone (the sub-nav carries them now).
    cal = client.get("/plan/calendar").get_data(as_text=True)
    nav_bar = re.search(r'<div class="mh-cal-nav">.*?</div>', cal, re.S).group(0)
    assert "Grid preview" not in nav_bar
    assert "/plan/board" not in nav_bar
    assert "/plan/analytics" not in nav_bar
    assert "Back to the ranked plan" not in cal

    plan = client.get("/plan").get_data(as_text=True)
    assert "Open calendar &rarr;" not in plan

    grid = client.get("/plan/grid").get_data(as_text=True)
    assert "Open the calendar &rarr;" not in grid

    board = client.get("/plan/board").get_data(as_text=True)
    assert "Open the calendar &rarr;" not in board

    analytics = client.get("/plan/analytics").get_data(as_text=True)
    assert "Back to the plan &rarr;" not in analytics
