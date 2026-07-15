"""UI2.4 — Client-side workflow tabs on the review queue.

Turns the review page's Queue/Approved filter from a server-nav `?wf=` reload
into a client-side tab control built on the design-system kit's sliding
`.mh-tabs` indicator: switching shows/hides the cards in place with no reload.

These tests pin the whole surface:

  * the kit CSS/JS contract — `.mh-tabs` is now a real, reusable, token-driven
    tab component (underline register + sliding indicator) with a no-JS
    fallback, and the behaviour layer (`bindTabs`) already ships;
  * the review filter is the kit's `.mh-tabs` (role=tablist), NOT the old
    `.mh-segmented` server-nav button group;
  * every card is rendered into the DOM regardless of the active filter (so the
    tabs can switch client-side), with `#ach-list[data-wf-filter]` carrying the
    active filter — set from `?wf=` so the no-JS / deep-link path filters
    identically via CSS;
  * the per-card status + the tab/stat counts are computed from the actual
    cards (they match the DOM and the live JS recount on first paint);
  * the client-side switching JS (no full reload, URL kept in sync, live
    counts + per-tab empty hint);
  * progressive enhancement — each tab keeps its `?wf=` href;
  * ARIA — tablist + role=tab + aria-selected true/false.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

THEME_MOTION_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-motion.css"
UI_KIT_JS = _ROOT / "src" / "mediahub" / "web" / "static" / "js" / "ui-kit.js"


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def world(app, web_module, tmp_path):
    return types.SimpleNamespace(app=app, wm=web_module, tmp=tmp_path)


def _save_org(world, pid="riverbend", name="Riverbend SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=pid,
            display_name=name,
            brand_voice_summary="Proud, warm, community-first.",
        )
    )
    return pid


_RANKED = [
    {
        "rank": 1,
        "quality_band": "elite",
        "priority": 0.92,
        "achievement": {
            "swim_id": "s1",
            "swimmer_name": "Tamsin Veldt",
            "event": "200m IM",
            "headline": "Tamsin Veldt takes gold in the 200m IM",
            "type": "medal_gold",
            "confidence": 0.91,
            "confidence_label": "high",
        },
    },
    {
        "rank": 2,
        "quality_band": "strong",
        "priority": 0.61,
        "achievement": {
            "swim_id": "s2",
            "swimmer_name": "Idris Vanterpool",
            "event": "100m Freestyle",
            "headline": "Idris Vanterpool third in the 100m Free",
            "type": "medal_bronze",
            "confidence": 0.52,
            "confidence_label": "medium",
        },
    },
]


def _seed_run(world, run_id, *, profile_id, ranked=_RANKED):
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Autumn Sprint Gala"},
        "recognition_report": {"ranked_achievements": ranked},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _review(world, run_id, pid, query=""):
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c.get(f"/review/{run_id}{query}").get_data(as_text=True)


def _wf_nav(html: str) -> str:
    """Return just the workflow-filter <nav> markup (so assertions don't pick
    up the inlined theme CSS, which always contains the class names)."""
    m = re.search(
        r'<nav class="mh-tabs"[^>]*aria-label="Filter cards by workflow status".*?</nav>',
        html,
        re.S,
    )
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- #
# 1. The kit CSS / JS contract — .mh-tabs is a real, reusable tab component
# --------------------------------------------------------------------------- #
class TestKitContract:
    CSS = THEME_MOTION_CSS.read_text(encoding="utf-8")
    JS = UI_KIT_JS.read_text(encoding="utf-8")

    def test_tabs_container_and_indicator_exist(self):
        assert ".mh-tabs" in self.CSS
        assert ".mh-tabs__ind" in self.CSS

    def test_tabs_have_item_styling(self):
        """UI2.4 fleshes the kit out: the tabs themselves are styled, not just
        the indicator — so it's a usable control, not a bare underline."""
        assert ".mh-tabs > a" in self.CSS
        assert '.mh-tabs > [role="tab"]' in self.CSS

    def test_active_state_keys_on_aria_selected(self):
        assert '.mh-tabs > [role="tab"][aria-selected="true"]' in self.CSS

    def test_tabs_are_token_driven(self):
        """A re-skinned brand re-skins the tabs (no hard-coded colours)."""
        block = self.CSS[self.CSS.find(".mh-tabs") :]
        block = block[: block.find(".mh-compare")]  # next kit section
        assert "var(--ink-muted)" in block
        assert "var(--mh-primary)" in block
        assert "var(--font-mono)" in block

    def test_no_js_fallback_present(self):
        """Fail-safe: without JS the sliding indicator can't size itself, so it
        is hidden and the active tab gets a static underline instead."""
        assert "html:not(.mh-js) .mh-tabs__ind" in self.CSS
        assert 'html:not(.mh-js) .mh-tabs > [role="tab"][aria-selected="true"]' in self.CSS

    def test_kit_js_binds_tabs(self):
        assert "bindTabs" in self.JS
        assert '.mh-tabs", bindTabs' in self.JS  # auto-bound in MH.ui.init
        # The behaviour layer drives the sliding indicator custom props.
        assert "--mh-ind-x" in self.JS
        assert "--mh-ind-w" in self.JS


# --------------------------------------------------------------------------- #
# 2. The review filter is the kit tabs, not the old server-nav segmented group
# --------------------------------------------------------------------------- #
class TestReviewFilterIsTabs:
    def test_filter_nav_is_mh_tabs(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000001", profile_id=pid)
        html = _review(world, "rev0000001", pid)
        assert '<nav class="mh-tabs" role="tablist"' in html
        assert 'aria-label="Filter cards by workflow status"' in html

    def test_filter_nav_is_not_segmented_element(self, world):
        """The old server-nav button group is gone (the .mh-segmented *CSS*
        still ships for other surfaces; only the review filter element changed)."""
        pid = _save_org(world)
        _seed_run(world, "rev0000002", profile_id=pid)
        html = _review(world, "rev0000002", pid)
        assert (
            '<nav class="mh-segmented" role="tablist" aria-label="Filter cards by workflow status"'
            not in html
        )

    def test_indicator_span_rendered(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000003", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000003", pid))
        assert 'class="mh-tabs__ind"' in nav

    def test_each_tab_carries_filter_value(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000004", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000004", pid))
        assert 'data-wf-filter-to=""' in nav  # All
        assert 'data-wf-filter-to="queue"' in nav
        assert 'data-wf-filter-to="approved"' in nav
        # G-1: rejected cards get a first-class tab too.
        assert 'data-wf-filter-to="rejected"' in nav
        assert nav.count('role="tab"') == 4

    def test_tabs_keep_wf_href_for_no_js(self, world):
        """Progressive enhancement: each tab is still a real link, so a no-JS
        page (or a middle-click) filters via a normal navigation."""
        pid = _save_org(world)
        _seed_run(world, "rev0000005", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000005", pid))
        assert 'href="/review/rev0000005?wf=queue"' in nav
        assert 'href="/review/rev0000005?wf=approved"' in nav

    def test_tab_counts_have_stable_ids(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000006", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000006", pid))
        assert 'id="mh-wf-tabcount-all"' in nav
        assert 'id="mh-wf-tabcount-queue"' in nav
        assert 'id="mh-wf-tabcount-approved"' in nav


# --------------------------------------------------------------------------- #
# 3. Every card renders into the DOM + #ach-list carries the active filter
# --------------------------------------------------------------------------- #
class TestAllCardsRendered:
    def test_all_cards_present_regardless_of_filter(self, world):
        """The whole point of a *client-side* tab: switching must not need a
        round-trip, so every card is in the DOM even under ?wf=approved (where
        the server used to skip the non-approved cards)."""
        pid = _save_org(world)
        _seed_run(world, "rev0000010", profile_id=pid)
        for q in ("", "?wf=queue", "?wf=approved"):
            html = _review(world, "rev0000010", pid, q)
            assert "Tamsin Veldt" in html, q
            assert "Idris Vanterpool" in html, q

    def test_ach_list_carries_filter_from_query(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000011", profile_id=pid)
        assert '<div id="ach-list" data-wf-filter="">' in _review(world, "rev0000011", pid)
        assert '<div id="ach-list" data-wf-filter="queue">' in _review(
            world, "rev0000011", pid, "?wf=queue"
        )
        assert '<div id="ach-list" data-wf-filter="approved">' in _review(
            world, "rev0000011", pid, "?wf=approved"
        )

    def test_bogus_filter_falls_back_to_all(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000012", profile_id=pid)
        html = _review(world, "rev0000012", pid, "?wf=nonsense")
        assert '<div id="ach-list" data-wf-filter="">' in html

    def test_active_tab_matches_query(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000013", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000013", pid, "?wf=queue"))
        # The Queue tab is selected, the others are not.
        m = re.search(r'data-wf-filter-to="queue"\s+aria-selected="(\w+)"', nav)
        assert m and m.group(1) == "true"
        m_all = re.search(r'data-wf-filter-to=""\s+aria-selected="(\w+)"', nav)
        assert m_all and m_all.group(1) == "false"


# --------------------------------------------------------------------------- #
# 4. The CSS that hides non-matching cards (works no-JS / deep-link too)
# --------------------------------------------------------------------------- #
class TestFilterCss:
    def test_page_ships_the_filter_rules(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000020", profile_id=pid)
        html = _review(world, "rev0000020", pid)
        assert '#ach-list[data-wf-filter="queue"] .ach-row:not([data-status="queue"])' in html
        assert '#ach-list[data-wf-filter="approved"] .ach-row:not([data-status="approved"])' in html


# --------------------------------------------------------------------------- #
# 5. The client-side switching behaviour ships on the page
# --------------------------------------------------------------------------- #
class TestClientJs:
    def test_tab_sync_and_click_handler(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000030", profile_id=pid)
        html = _review(world, "rev0000030", pid)
        assert "mhWfTabsSync" in html
        # The handler prevents the full reload and keeps the URL honest.
        assert "data-wf-filter-to" in html
        assert "preventDefault" in html
        assert "replaceState" in html

    def test_applyfilters_respects_active_tab(self, world):
        """The dropdown filter's 'N of M shown' count folds in the active tab so
        it can't read '12 of 12' while only the approved subset is visible."""
        pid = _save_org(world)
        _seed_run(world, "rev0000031", profile_id=pid)
        html = _review(world, "rev0000031", pid)
        assert "mhActiveWfFilter" in html

    def test_recount_updates_tab_counts_live(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000032", profile_id=pid)
        html = _review(world, "rev0000032", pid)
        # The shared recount keeps the tab badges live as cards are approved.
        assert "mh-wf-tabcount-queue" in html
        assert "mh-wf-tabcount-approved" in html


# --------------------------------------------------------------------------- #
# 6. Counts come from the actual cards (match the DOM on first paint)
# --------------------------------------------------------------------------- #
class TestCountsMatchCards:
    def test_fresh_run_counts_all_queued(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000040", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000040", pid))
        # Two cards, none actioned yet → Queue 2, Approved 0, All 2.
        assert '<span class="count" id="mh-wf-tabcount-all">2</span>' in nav
        assert '<span class="count" id="mh-wf-tabcount-queue">2</span>' in nav
        assert '<span class="count" id="mh-wf-tabcount-approved">0</span>' in nav

    def test_approved_card_reflected_in_counts_and_status(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "rev0000041", profile_id=pid)
        world.wm._get_wf_store().set_status("rev0000041", "s1", CardStatus.APPROVED)

        html = _review(world, "rev0000041", pid)
        nav = _wf_nav(html)
        assert '<span class="count" id="mh-wf-tabcount-queue">1</span>' in nav
        assert '<span class="count" id="mh-wf-tabcount-approved">1</span>' in nav
        # The approved card carries data-status="approved" so the CSS tab filter
        # moves it into the Approved view; the other stays queued.
        assert re.search(r'data-status="approved"[^>]*>.*?Tamsin Veldt', html, re.S) or (
            'data-status="approved"' in html
        )
        assert 'data-status="queue"' in html
        # Both cards are still in the DOM (client-side tabs).
        assert "Tamsin Veldt" in html and "Idris Vanterpool" in html


# --------------------------------------------------------------------------- #
# 7. The server no longer renders a per-filter empty state (client owns it)
# --------------------------------------------------------------------------- #
class TestNoServerFilterEmptyState:
    def test_approved_filter_with_no_approved_cards_still_lists_all(self, world):
        """Old behaviour returned a 'No approved cards / Show all cards' server
        page for ?wf=approved with nothing approved. Now every card renders and
        the client shows the per-tab hint, so that server empty state is gone."""
        pid = _save_org(world)
        _seed_run(world, "rev0000050", profile_id=pid)
        html = _review(world, "rev0000050", pid, "?wf=approved")
        assert "Show all cards" not in html
        assert "Tamsin Veldt" in html  # the queued cards are present, just hidden by CSS
        # The client-side per-tab empty hint element ships (hidden until JS).
        assert 'id="mh-wf-empty"' in html


# --------------------------------------------------------------------------- #
# 8. ARIA — tablist + role=tab + aria-selected (axe aria-required-children)
# --------------------------------------------------------------------------- #
class TestAria:
    def test_tablist_children_have_role_tab_and_aria_selected(self, world):
        pid = _save_org(world)
        _seed_run(world, "rev0000060", profile_id=pid)
        nav = _wf_nav(_review(world, "rev0000060", pid))
        assert 'role="tablist"' in nav
        assert 'role="tab"' in nav
        assert 'aria-selected="true"' in nav
        assert 'aria-selected="false"' in nav
