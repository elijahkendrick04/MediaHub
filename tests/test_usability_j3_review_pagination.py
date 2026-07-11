"""J-3 — Server-side pagination on the review queue (25 cards per page).

The audit found a 249-card meet rendered every ranked achievement into one
~70,000px page, and the thumbnail loader (2 concurrent fetches, 6 retries)
permanently gave up on deep rows with "Renderer busy".

This file pins the fix:

  * ``?page=N`` slices the rank-ordered list server-side, 25 rows per page;
  * pager controls (Prev / "Page N of M" / Next) render top AND bottom and
    preserve the active ``?wf=`` filter;
  * out-of-range / malformed ``?page=`` clamps safely;
  * runs of 25 cards or fewer render exactly as before — no pager;
  * tab counts, the stat block and the progress strip stay computed from the
    FULL run state (not the visible page), and the live recount works from a
    server-rendered baseline + on-page delta;
  * "Why this card" lazy URLs keep using the FULL-list achievement index;
  * "Approve all in queue" operates on the FULL queue via the server-embedded
    ``#mh-queued-ids`` list (covered in depth by test_usability_d2_*).
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Fixtures (modelled on tests/test_ui_2_4_clientside_tabs.py)
# --------------------------------------------------------------------------- #
@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    return types.SimpleNamespace(app=app, wm=wm, tmp=tmp_path)


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


def _ranked(n):
    """n distinct rank-ordered achievements with collision-proof names."""
    return [
        {
            "rank": i + 1,
            "quality_band": "strong",
            "priority": round(1.0 - i * 0.001, 3),
            "achievement": {
                "swim_id": f"sw{i:03d}",
                "swimmer_name": f"Swimmer {i:03d}",
                "event": "100m Freestyle",
                "headline": f"PB for Swimmer {i:03d}",
                "type": "pb",
                "confidence": 0.9,
                "confidence_label": "high",
            },
        }
        for i in range(n)
    ]


def _seed_run(world, run_id, *, profile_id, n_cards):
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Long Course Meet"},
        "recognition_report": {"ranked_achievements": _ranked(n_cards)},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _review(world, run_id, pid, query=""):
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c.get(f"/review/{run_id}{query}").get_data(as_text=True)


def _pagers(html):
    return re.findall(r'<nav class="mh-review-pager".*?</nav>', html, re.S)


def _ach_list(html):
    """Just the rendered card rows — the swimmer/event dropdown filters are
    (correctly) built from the FULL ranked list, so name assertions about the
    visible page must not scan the whole document."""
    m = re.search(r'<div id="ach-list".*?</form>', html, re.S)
    return m.group(0) if m else ""


# --------------------------------------------------------------------------- #
# 1. Small runs are untouched — no pager, every card rendered
# --------------------------------------------------------------------------- #
class TestSmallRunUnchanged:
    def test_25_cards_render_on_one_page_with_no_pager(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3small001", profile_id=pid, n_cards=25)
        html = _review(world, "j3small001", pid)
        # No pager ELEMENT renders (the page JS always ships a
        # '.mh-review-pager' selector so f-count can detect page scope, so
        # match the <nav>, not the bare class name).
        assert _pagers(html) == []
        for i in (0, 12, 24):
            assert f"Swimmer {i:03d}" in html


# --------------------------------------------------------------------------- #
# 2. Big runs slice at 25, ordered by rank
# --------------------------------------------------------------------------- #
class TestSlicing:
    def test_page_1_renders_top_25_only(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3big00001", profile_id=pid, n_cards=60)
        html = _review(world, "j3big00001", pid)
        rows = _ach_list(html)
        assert "Swimmer 000" in rows and "Swimmer 024" in rows
        assert "Swimmer 025" not in rows
        assert html.count('class="ach-row"') == 25

    def test_page_2_renders_the_next_25(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3big00002", profile_id=pid, n_cards=60)
        rows = _ach_list(_review(world, "j3big00002", pid, "?page=2"))
        assert "Swimmer 025" in rows and "Swimmer 049" in rows
        assert "Swimmer 024" not in rows and "Swimmer 050" not in rows

    def test_last_page_holds_the_remainder(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3big00003", profile_id=pid, n_cards=60)
        html = _review(world, "j3big00003", pid, "?page=3")
        assert html.count('class="ach-row"') == 10
        assert "Swimmer 059" in _ach_list(html)

    def test_out_of_range_and_malformed_pages_clamp(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3big00004", profile_id=pid, n_cards=60)
        # Too high clamps to the last page …
        html = _review(world, "j3big00004", pid, "?page=99")
        assert "Page 3 of 3" in html and "Swimmer 059" in _ach_list(html)
        # … zero/negative/garbage clamp to page 1.
        for q in ("?page=0", "?page=-4", "?page=banana"):
            html = _review(world, "j3big00004", pid, q)
            assert "Swimmer 000" in _ach_list(html), q

    def test_why_card_urls_keep_full_list_indices(self, world):
        """api_why_card looks up by position in the FULL ranked list — page 2's
        first row must fetch /why/25, not /why/0."""
        pid = _save_org(world)
        _seed_run(world, "j3big00005", profile_id=pid, n_cards=60)
        html = _review(world, "j3big00005", pid, "?page=2")
        assert "/why/25" in html
        assert "/why/0?" not in html and '/why/0"' not in html


# --------------------------------------------------------------------------- #
# 3. Pager controls — top AND bottom, filters preserved
# --------------------------------------------------------------------------- #
class TestPagerControls:
    def test_pager_renders_top_and_bottom(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3pager001", profile_id=pid, n_cards=60)
        pagers = _pagers(_review(world, "j3pager001", pid))
        assert len(pagers) == 2
        for p in pagers:
            assert "Page 1 of 3" in p

    def test_prev_next_states_and_targets(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3pager002", profile_id=pid, n_cards=60)
        p1 = _pagers(_review(world, "j3pager002", pid))[0]
        assert 'aria-disabled="true"' in p1  # Prev is disabled on page 1
        assert "page=2" in p1  # Next points at page 2
        p2 = _pagers(_review(world, "j3pager002", pid, "?page=2"))[0]
        # Prev drops the page param (page 1 is the canonical URL) …
        assert 'href="/review/j3pager002"' in p2
        # … and Next points at page 3.
        assert "page=3" in p2

    def test_pager_preserves_the_wf_filter(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3pager003", profile_id=pid, n_cards=60)
        p = _pagers(_review(world, "j3pager003", pid, "?wf=queue"))[0]
        assert "wf=queue" in p and "page=2" in p


# --------------------------------------------------------------------------- #
# 4. Counts stay FULL-run-state; the recount works from baseline + delta
# --------------------------------------------------------------------------- #
class TestFullStateCounts:
    def test_tab_counts_and_strip_are_run_wide_on_every_page(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "j3count001", profile_id=pid, n_cards=60)
        # Approve a page-1 card and reject a page-3 card.
        ws = world.wm._get_wf_store()
        ws.set_status("j3count001", "sw000", CardStatus.APPROVED)
        ws.set_status("j3count001", "sw059", CardStatus.REJECTED)

        html = _review(world, "j3count001", pid, "?page=2")
        assert '<span class="count" id="mh-wf-tabcount-all">60</span>' in html
        assert '<span class="count" id="mh-wf-tabcount-queue">58</span>' in html
        assert '<span class="count" id="mh-wf-tabcount-approved">1</span>' in html
        assert '<span class="count" id="mh-wf-tabcount-rejected">1</span>' in html
        assert 'data-wf-total="60"' in html

    def test_strip_carries_the_recount_baselines(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3count002", profile_id=pid, n_cards=60)
        html = _review(world, "j3count002", pid, "?page=2")
        assert 'data-wf-base-queue="60"' in html
        assert 'data-wf-base-approved="0"' in html
        assert 'data-wf-base-rejected="0"' in html

    def test_rows_remember_their_rendered_status(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3count003", profile_id=pid, n_cards=30)
        html = _review(world, "j3count003", pid)
        assert 'data-status="queue" data-status-initial="queue"' in html

    def test_recount_js_uses_baseline_plus_delta(self):
        """Source-level: the live recount must not shrink run-wide counts to
        the visible page — it starts from data-wf-base-* and applies only the
        delta of on-page status changes."""
        assert "data-wf-base-" in _WEB_SRC
        assert "statusInitial" in _WEB_SRC


# --------------------------------------------------------------------------- #
# 5. "Approve all in queue" sees the whole queue, not the visible page
# --------------------------------------------------------------------------- #
class TestApproveAllFullQueue:
    def test_embedded_queued_ids_cover_every_page(self, world):
        pid = _save_org(world)
        _seed_run(world, "j3queue001", profile_id=pid, n_cards=60)
        html = _review(world, "j3queue001", pid, "?page=2")
        m = re.search(
            r'<script type="application/json" id="mh-queued-ids">(.*?)</script>', html, re.S
        )
        assert m, "the full queued-id list must be embedded"
        ids = json.loads(m.group(1))
        assert len(ids) == 60
        assert ids[0] == "sw000" and ids[-1] == "sw059"

    def test_embedded_list_excludes_already_decided_cards(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "j3queue002", profile_id=pid, n_cards=60)
        ws = world.wm._get_wf_store()
        ws.set_status("j3queue002", "sw010", CardStatus.APPROVED)
        ws.set_status("j3queue002", "sw040", CardStatus.REJECTED)
        html = _review(world, "j3queue002", pid)
        m = re.search(
            r'<script type="application/json" id="mh-queued-ids">(.*?)</script>', html, re.S
        )
        ids = json.loads(m.group(1))
        assert len(ids) == 58
        assert "sw010" not in ids and "sw040" not in ids

    def test_approve_all_reconciles_in_page_decisions(self):
        """JS-2 (source-level): the embedded queued-id list is a render-time
        snapshot — cards approved/rejected on this page since render must be
        subtracted before the confirm message and the POST, or the button
        over-counts. Each row's live data-status is the source of truth."""
        assert "var decidedNow = {{}};" in _WEB_SRC
        assert "if (chk && chk.value && row.dataset.status !== 'queue') decidedNow[chk.value] = 1;" in _WEB_SRC
        assert "ids = ids.filter(function(id){{ return !decidedNow[id]; }});" in _WEB_SRC
        # The reconciliation happens BEFORE the "nothing to approve" guard and
        # the confirm-message maths.
        assert _WEB_SRC.index("decidedNow[chk.value] = 1") < _WEB_SRC.index(
            "No cards in the queue to approve."
        )


# --------------------------------------------------------------------------- #
# 6. Client JS stays honest about page scope (JS-1)
# --------------------------------------------------------------------------- #
class TestPaginatedClientHonesty:
    def test_tab_empty_state_consults_the_run_wide_count(self):
        """With only this page's rows in the DOM, a tab whose rows are all on
        other pages must say "None on this page" (the run-wide badge is
        non-zero) — "Queue clear" is reserved for a run-wide count of 0."""
        assert "mh-wf-tabcount-' + (wf || 'all')" in _WEB_SRC
        assert "None on this page" in _WEB_SRC
        assert "live on other pages" in _WEB_SRC
        # The celebratory copy survives, but only behind the run-wide guard.
        assert "Queue clear" in _WEB_SRC
        assert _WEB_SRC.index("runWide > 0") < _WEB_SRC.index("t.textContent = 'Queue clear'")

    def test_f_count_says_on_this_page_when_paginated(self):
        assert "var pageScoped = !!document.querySelector('.mh-review-pager');" in _WEB_SRC
        assert "(pageScoped ? ' on this page' : '')" in _WEB_SRC

    def test_tab_click_preserves_the_page_param(self):
        """Rewriting ?wf= must not drop ?page=N — a reload jumped to page 1."""
        assert "var qs = new URLSearchParams(location.search);" in _WEB_SRC
        assert "qs.set('wf', val)" in _WEB_SRC
        # The old pathname-only rewrite (which dropped every other param) is gone.
        assert "location.pathname + (val ? ('?wf='" not in _WEB_SRC
