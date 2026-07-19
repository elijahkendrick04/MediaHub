"""G-1 — Rejected cards get a first-class tab, live count and filter.

The audit found rejection was a dead-end state: the bulk bar offered Reject,
but the filter tabs were All/Queue/Approved only, ``?wf=rejected`` fell back
to "show all", the stat block omitted rejected, and the live recount wrote to
a ``mh-wf-n-rejected`` element that existed nowhere. The home marketing mock
also promised Edit/Reject buttons on every card that the real per-card flow
(Approve / Re-queue / Inspect) does not have.

This file pins the fix:

  * a "Rejected" tab with a stable live-count id and a real ``?wf=rejected``
    href / server-side filter;
  * the rejected count in the stat block (``mh-wf-n-rejected``) so the live
    recount has a target;
  * the CSS rule that makes the Rejected tab actually hide other cards;
  * bulk "Re-queue" works on a rejected selection (server + bulk-bar button);
  * the home marketing mock shows the REAL actions;
  * deliberately NO per-card Reject button (owner decision: fewer buttons
    per row — reject stays a bulk-bar action).
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
from tests._helpers import web_surface_src

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = web_surface_src()


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_ui_2_4_clientside_tabs.py)
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


def _client(world, pid):
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c


def _review(world, run_id, pid, query=""):
    return _client(world, pid).get(f"/review/{run_id}{query}").get_data(as_text=True)


def _wf_nav(html: str) -> str:
    m = re.search(
        r'<nav class="mh-tabs"[^>]*aria-label="Filter cards by workflow status".*?</nav>',
        html,
        re.S,
    )
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- #
# 1. The Rejected tab is first-class
# --------------------------------------------------------------------------- #
class TestRejectedTab:
    def test_tab_renders_with_stable_count_id_and_href(self, world):
        pid = _save_org(world)
        _seed_run(world, "g1run00001", profile_id=pid)
        nav = _wf_nav(_review(world, "g1run00001", pid))
        assert 'data-wf-filter-to="rejected"' in nav
        assert 'id="mh-wf-tabcount-rejected"' in nav
        assert 'href="/review/g1run00001?wf=rejected"' in nav

    def test_wf_rejected_is_a_real_filter_not_show_all(self, world):
        pid = _save_org(world)
        _seed_run(world, "g1run00002", profile_id=pid)
        html = _review(world, "g1run00002", pid, "?wf=rejected")
        assert '<div id="ach-list" data-wf-filter="rejected">' in html
        # The Rejected tab is the selected one.
        nav = _wf_nav(html)
        m = re.search(r'data-wf-filter-to="rejected"\s+aria-selected="(\w+)"', nav)
        assert m and m.group(1) == "true"

    def test_filter_css_rule_ships(self, world):
        pid = _save_org(world)
        _seed_run(world, "g1run00003", profile_id=pid)
        html = _review(world, "g1run00003", pid)
        assert '#ach-list[data-wf-filter="rejected"] .ach-row:not([data-status="rejected"])' in html

    def test_counts_reflect_rejected_state(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "g1run00004", profile_id=pid)
        world.wm._get_wf_store().set_status("g1run00004", "s1", CardStatus.REJECTED)

        html = _review(world, "g1run00004", pid)
        nav = _wf_nav(html)
        assert '<span class="count" id="mh-wf-tabcount-rejected">1</span>' in nav
        assert '<span class="count" id="mh-wf-tabcount-queue">1</span>' in nav
        # The rejected card carries data-status="rejected" so the CSS filter
        # moves it into the Rejected view — and it is still in the DOM.
        assert 'data-status="rejected"' in html
        assert "Tamsin Veldt" in html


# --------------------------------------------------------------------------- #
# 2. The stat block includes Rejected (the recount's mh-wf-n-rejected orphan)
# --------------------------------------------------------------------------- #
class TestStatBlock:
    def test_rejected_stat_renders_with_live_id(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "g1run00010", profile_id=pid)
        world.wm._get_wf_store().set_status("g1run00010", "s2", CardStatus.REJECTED)
        html = _review(world, "g1run00010", pid)
        assert 'id="mh-wf-n-rejected">1</div>' in html

    def test_recount_js_updates_the_rejected_tab_count(self):
        """Source-level: mhRecountReview must feed the new tab badge too, so a
        live reject/re-queue keeps the Rejected tab honest without a reload."""
        assert "set('mh-wf-n-rejected', nRejected);" in _WEB_SRC
        assert "set('mh-wf-tabcount-rejected', nRejected);" in _WEB_SRC

    def test_tab_sync_has_a_rejected_empty_hint(self):
        assert "No rejected cards" in _WEB_SRC
        # JS-1: on a paginated run the "No rejected cards" hint only shows
        # when the run-wide tab count is 0 — when rejected cards exist on
        # other pages the honest hint is "None on this page" (guard first).
        assert _WEB_SRC.index("runWide > 0") < _WEB_SRC.index("No rejected cards")


# --------------------------------------------------------------------------- #
# 3. Bulk Re-queue works on a rejected selection
# --------------------------------------------------------------------------- #
class TestBulkRequeue:
    def test_bulk_bar_offers_requeue(self, world):
        pid = _save_org(world)
        _seed_run(world, "g1run00020", profile_id=pid)
        html = _review(world, "g1run00020", pid)
        m = re.search(r'<button[^>]*data-mh-bulk="requeue"[^>]*>', html)
        assert m, "bulk bar must render a Re-queue button"
        assert 'value="queue"' in m.group(0)

    def test_bulk_requeue_moves_rejected_cards_back_to_queue(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "g1run00021", profile_id=pid)
        ws = world.wm._get_wf_store()
        ws.set_status("g1run00021", "s1", CardStatus.REJECTED)
        ws.set_status("g1run00021", "s2", CardStatus.REJECTED)

        c = _client(world, pid)
        r = c.post(
            "/api/runs/g1run00021/cards/bulk-status",
            json={"status": "queue", "ids": ["s1", "s2"]},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["n_ok"] == 2
        assert all(item["status"] == "queue" for item in body["results"])
        states = ws.load("g1run00021")
        assert states["s1"].status == CardStatus.QUEUE
        assert states["s2"].status == CardStatus.QUEUE

    def test_bulk_js_maps_requeue_to_queue_status(self):
        """Source-level: the shared bulk-bar JS must paint a re-queued card
        back to 'queue' (not a bogus 'requeue' status) and toast 'Re-queued'."""
        assert "action === 'requeue' ? 'queue'" in _WEB_SRC
        assert "'Re-queued'" in _WEB_SRC


# --------------------------------------------------------------------------- #
# 4. No per-card Reject button (owner decision: fewer buttons per row)
# --------------------------------------------------------------------------- #
class TestNoPerCardReject:
    def test_wf_actions_have_no_reject_button(self, world):
        pid = _save_org(world)
        _seed_run(world, "g1run00030", profile_id=pid)
        html = _review(world, "g1run00030", pid)
        assert 'data-mh-wf="rejected"' not in html


# --------------------------------------------------------------------------- #
# 5. The home marketing mock shows the real actions
# --------------------------------------------------------------------------- #
class TestMarketingMock:
    def test_mock_actions_match_the_real_review_row(self, world):
        html = world.wm._hero_product_demo()
        m = re.search(r'<div class="mh-demo-acts">(.*?)</div>', html)
        assert m, "the review scene's action strip must render"
        acts = m.group(1)
        # H-10 renamed the row's drawer button "Inspect" -> "Edit card"; the
        # mock mirrors the real actions. B-4 slimmed the QUEUED row (which is
        # what the mock's review scene shows) to Approve + Edit card —
        # Re-queue only appears once a card is decided.
        assert "Edit card" in acts
        assert "Re-queue" not in acts
        assert "Approve" in acts
        assert "Reject" not in acts
        assert ">Edit<" not in acts
