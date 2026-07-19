"""B-4 — each review row carried ~9–13 interactive controls.

Owner decision — slim the default row:
  * Default (queued) row controls: Approve + "✎ Edit card" + the
    "Why this card?" disclosure. That's it.
  * Re-queue renders only on DECIDED cards (approved/rejected/edited) —
    on a queued row it ships with the `hidden` attribute (there is
    nothing to undo yet). The optimistic painters flip `hidden` with the
    card's status, so undo appears without a reload, and
    `.btn[data-mh-wf][hidden]` CSS makes `hidden` beat the .btn flex
    display.
  * The three emoji reactions move INSIDE the "ranking & evidence"
    disclosure (still functional — the global reaction JS is delegated).
  * Row checkboxes are hidden by default; a "Select" toggle in the bulk
    bar stamps .mh-select-on onto #ach-list to reveal them. "Approve all
    in queue" needs no checkboxes and stays always-visible.
  * Every wf data attribute (data-status, data-status-initial,
    data-mh-label-*) stays intact — the recount/tab machinery reads them.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import uuid

import pytest
from tests._helpers import web_surface_src

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = web_surface_src()


@pytest.fixture
def env(tmp_path, client, web_module):
    wm = web_module
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-b4-" + uuid.uuid4().hex[:8]
    achs = []
    for i, sid in enumerate(["s1", "s2"]):
        achs.append(
            {
                "rank": i + 1,
                "quality_band": "elite",
                "priority": 0.9,
                "achievement": {
                    "swim_id": sid,
                    "swimmer_name": f"Swimmer {i}",
                    "event": "100m Freestyle",
                    "headline": "New PB",
                    "type": "pb",
                },
                "factors": [],
            }
        )
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Spring Open"},
                "cards": [],
                "recognition_report": {"ranked_achievements": achs, "n_achievements": 2},
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    c = client
    r = c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code == 200
    yield {"client": c, "run_id": run_id, "wm": wm}


def _approve(env, card_id: str) -> None:
    from mediahub.workflow.status import CardStatus

    env["wm"]._get_wf_store().set_status(env["run_id"], card_id, CardStatus.APPROVED)


def _review(env) -> str:
    r = env["client"].get(f"/review/{env['run_id']}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _row(html: str, card_id: str) -> str:
    """The .ach-row chunk for one card."""
    starts = [m.start() for m in re.finditer(r'<div class="ach-row"', html)]
    for s in starts:
        end = html.find('<div class="ach-row"', s + 10)
        chunk = html[s : end if end > 0 else s + 40000]
        if f'value="{card_id}"' in chunk:
            return chunk
    raise AssertionError(f"no .ach-row found for {card_id}")


def _requeue_btn(chunk: str) -> str:
    m = re.search(r'<button[^>]*data-mh-wf="queue"[^>]*>', chunk)
    assert m, "Re-queue button element must stay in the DOM (keyboard 'u' + JS reveal)"
    return m.group(0)


# --------------------------------------------------------------------------- #
# 1. Re-queue only on decided cards
# --------------------------------------------------------------------------- #
class TestRequeueOnlyOnDecidedCards:
    def test_queued_row_requeue_is_hidden(self, env):
        html = _review(env)
        btn = _requeue_btn(_row(html, "s1"))
        assert " hidden" in btn

    def test_approved_row_requeue_is_visible(self, env):
        _approve(env, "s2")
        html = _review(env)
        btn = _requeue_btn(_row(html, "s2"))
        assert " hidden" not in btn

    def test_hidden_beats_the_btn_flex_display(self, env):
        """.btn sets display:inline-flex (an author rule), which would
        override the UA [hidden] rule — the explicit CSS must win."""
        html = _review(env)
        assert ".btn[data-mh-wf][hidden] { display: none; }" in html

    def test_optimistic_painters_flip_hidden_with_status(self):
        # The global per-card painter in _layout…
        assert "b.hidden = (st === 'queue')" in _WEB_SRC
        # …and the bulk-bar painter both reveal/hide Re-queue live.
        assert "b.hidden = (status === 'queue')" in _WEB_SRC

    def test_dimmed_but_rendered_state_is_gone(self):
        """The old server-side dimming helper (opacity 0.55 on the action
        matching the current state) is replaced by the hidden attribute."""
        assert "_disabled_attrs" not in _WEB_SRC

    def test_marketing_mock_mirrors_the_queued_row(self, env):
        html = env["wm"]._hero_product_demo()
        m = re.search(r'<div class="mh-demo-acts">(.*?)</div>', html)
        assert m
        assert "Re-queue" not in m.group(1)


# --------------------------------------------------------------------------- #
# 2. Reactions live inside the "ranking & evidence" disclosure
# --------------------------------------------------------------------------- #
class TestReactionsInsideDisclosure:
    def test_reactions_render_after_the_disclosure_summary(self, env):
        row = _row(_review(env), "s1")
        assert "mh-reactions" in row  # still functional
        assert row.find("mh-reactions") > row.find("How the ranking added up")

    def test_reactions_not_in_the_decision_row(self, env):
        row = _row(_review(env), "s1")
        wf_actions = row.split('class="wf-actions"', 1)[1].split("<details", 1)[0]
        assert "mh-reactions" not in wf_actions

    def test_trace_link_kept_alongside(self, env):
        row = _row(_review(env), "s1")
        assert "/api/trace/" in row or "trace" in row.lower()


# --------------------------------------------------------------------------- #
# 3. Slim decision row: Approve + Edit card only (queued card)
# --------------------------------------------------------------------------- #
class TestSlimDecisionRow:
    def test_queued_row_decision_controls(self, env):
        row = _row(_review(env), "s1")
        wf_actions = row.split('class="wf-actions"', 1)[1].split("<details", 1)[0]
        assert 'data-mh-wf="approved"' in wf_actions  # Approve
        assert "Edit card" in wf_actions  # ✎ Edit card
        # The only other button element is the hidden Re-queue.
        visible_buttons = [
            b for b in re.findall(r"<button[^>]*>", wf_actions) if " hidden" not in b
        ]
        assert len(visible_buttons) == 2, visible_buttons

    def test_wf_data_attributes_intact(self, env):
        html = _review(env)
        assert 'data-status="queue" data-status-initial="queue"' in html
        assert "data-mh-label-approve=" in html
        assert "data-mh-label-approved=" in html
        assert 'data-mh-wf-target="s1"' in html

    def test_approved_row_keeps_download(self, env):
        _approve(env, "s2")
        assert "/card/s2/download" in _row(_review(env), "s2")


# --------------------------------------------------------------------------- #
# 4. Checkboxes are opt-in via the Select toggle
# --------------------------------------------------------------------------- #
class TestSelectMode:
    def test_select_toggle_in_the_bulk_bar(self, env):
        html = _review(env)
        bar = html.split('id="mh-rv-bulkbar"', 1)[1].split("</div>", 1)[0]
        assert 'id="mh-rv-select-toggle"' in bar

    def test_checkboxes_hidden_until_select_mode(self, env):
        html = _review(env)
        # The row checkboxes stay in the DOM (the bulk-approve fallback and
        # the no-JS form read them)…
        assert 'class="mh-row-check"' in html
        # …but with JS present they only show once .mh-select-on is stamped.
        assert "html.mh-js #ach-list:not(.mh-select-on) .mh-row-check-wrap" in html

    def test_bar_shows_its_toggle_even_when_empty(self, env):
        """The shared bulk-bar JS adds .is-empty at 0 selected, which the
        shared CSS hides — the review bar overrides that so the Select
        toggle stays reachable."""
        html = _review(env)
        assert "html.mh-js #mh-rv-bulkbar.is-empty { display: flex; }" in html

    def test_selection_controls_gated_on_select_mode(self, env):
        html = _review(env)
        for part in (".mh-bulkbar-all", ".mh-bulkbar-count", ".mh-bulkbar-actions"):
            assert f"html.mh-js #mh-rv-bulkbar:not(.mh-select-on) {part}" in html

    def test_no_js_page_keeps_the_old_behaviour(self, env):
        """Without JS (no html.mh-js) the checkboxes and full bar render as
        before; only the (inert) toggle button is hidden."""
        html = _review(env)
        assert "html:not(.mh-js) #mh-rv-select-toggle { display: none; }" in html

    def test_toggle_js_clears_selection_on_exit(self):
        assert "mh-rv-select-toggle" in _WEB_SRC
        assert "classList.toggle('mh-select-on', on)" in _WEB_SRC
        # Leaving select mode unchecks everything and notifies the shared
        # bulk-bar JS via a bubbled change event.
        assert "dispatchEvent(new Event('change', {{bubbles: true}}))" in _WEB_SRC

    def test_approve_all_in_queue_stays_always_visible(self, env):
        html = _review(env)
        assert 'id="mh-bulk-approve"' in html
        assert "Approve all in queue" in html
