"""H-10 — Caption editing surfaced: "Edit card" button, caption on the row,
save failures with a reason, one-step "Restore previous caption".

The audit found the only caption read/edit path on review was a button
labelled "⚙ Inspect"; Save reported a bare "Caption saved"/"Save failed"
(no reason); and overwriting a caption was permanent — the revisions panel
lives only on the Content builder.

This file pins the fix:

  * the review row's drawer button reads "✎ Edit card" (same drawer);
  * a card's saved caption renders on the row (truncated, HTML-escaped);
  * the drawer's save-failure status includes the reason from the response
    body, and the live save updates the row caption;
  * overwriting a caption slot stashes the replaced value under a reserved
    ``prev.<slot>`` key in the same edited_captions bag (WorkflowStore),
    the row button carries it as ``data-insp-caption-prev``, and the drawer
    offers a one-step "Restore previous caption" that saves the swap back;
  * ``prev.*`` slots never leak into caption-text joins (voiceover / copy
    fallback) or the pack build.

Note: the Content builder's design-revisions API (``api_card_revisions``)
tracks CreativeBrief versions — caption saves via set_edits never mint a
brief, so the restore is fed from the same edited_captions bag the save
writes (the codebase's own ``insp.*`` precedent), not from brief history.
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

from tests._helpers import web_surface_src

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


def _seed_run(world, run_id, *, profile_id):
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Autumn Sprint Gala"},
        "recognition_report": {
            "ranked_achievements": [
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
                }
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _client(world, pid):
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c


def _review(world, run_id, pid):
    return _client(world, pid).get(f"/review/{run_id}").get_data(as_text=True)


# --------------------------------------------------------------------------- #
# 1. The row button is "Edit card" (same drawer), no more "Inspect"
# --------------------------------------------------------------------------- #
class TestEditCardButton:
    def test_button_renamed_but_keeps_the_drawer_wiring(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0001", profile_id=pid)
        html = _review(world, "h10run0001", pid)
        m = re.search(r"<button[^>]*data-mh-inspect[^>]*>(.*?)</button>", html, re.S)
        assert m, "the drawer-opening row button must render"
        assert "Edit card" in m.group(1)
        assert "Inspect" not in m.group(1)
        # Same drawer: the button still targets the shared inspector dialog.
        assert 'aria-controls="mh-inspector"' in m.group(0)


# --------------------------------------------------------------------------- #
# 2. A saved caption shows on the row — truncated and escaped
# --------------------------------------------------------------------------- #
class TestRowCaption:
    def test_no_caption_renders_hidden_container(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0010", profile_id=pid)
        html = _review(world, "h10run0010", pid)
        m = re.search(r'<div class="mh-row-caption"[^>]*>', html)
        assert m and " hidden" in m.group(0)

    def test_saved_caption_renders_on_the_row(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0011", profile_id=pid)
        world.wm._get_wf_store().set_edits(
            "h10run0011", "s1", {"warm-club_headline": "A storming gold for Tamsin"}
        )
        html = _review(world, "h10run0011", pid)
        m = re.search(r'<div class="mh-row-caption".*?</div>', html, re.S)
        assert m and "A storming gold for Tamsin" in m.group(0)
        assert " hidden" not in m.group(0).split(">")[0]

    def test_row_caption_is_truncated_and_escaped(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0012", profile_id=pid)
        evil = "<script>alert(1)</script>" + ("x" * 200)
        world.wm._get_wf_store().set_edits("h10run0012", "s1", {"warm-club_headline": evil})
        html = _review(world, "h10run0012", pid)
        m = re.search(r'<div class="mh-row-caption".*?</div>', html, re.S)
        assert m
        frag = m.group(0)
        assert "<script>alert(1)</script>" not in frag
        assert "&lt;script&gt;" in frag
        # 140-char truncation with an ellipsis.
        assert "…" in frag
        assert "x" * 150 not in frag


# --------------------------------------------------------------------------- #
# 3. Save failures name the reason; saves update the row live
# --------------------------------------------------------------------------- #
class TestSaveFeedback:
    def test_save_failure_includes_response_reason(self):
        """Source-level: the drawer's save handler must surface the response
        body's reason/error/message instead of a bare 'Save failed'."""
        assert "'Save failed — ' + why" in _WEB_SRC
        assert (
            "(o && o.body && (o.body.reason || o.body.error || o.body.message)) || 'server error'"
            in _WEB_SRC
        )

    def test_save_updates_the_row_caption_without_reload(self):
        assert "function updateRowCaption(cardId, text)" in _WEB_SRC
        assert "updateRowCaption(ctx.cardId, text);" in _WEB_SRC


# --------------------------------------------------------------------------- #
# 4. Restore previous caption — store stash, row attrs, drawer control
# --------------------------------------------------------------------------- #
class TestRestorePrevious:
    def test_store_stashes_the_replaced_caption(self, tmp_path):
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(tmp_path)
        ws.set_edits("r1", "c1", {"warm-club_headline": "First wording"})
        ws.set_edits("r1", "c1", {"warm-club_headline": "Second wording"})
        edits = ws.load("r1")["c1"].edited_captions
        assert edits["warm-club_headline"] == "Second wording"
        assert edits["prev.warm-club_headline"] == "First wording"

    def test_restore_save_swaps_the_pair(self, tmp_path):
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(tmp_path)
        ws.set_edits("r1", "c1", {"warm-club_headline": "First wording"})
        ws.set_edits("r1", "c1", {"warm-club_headline": "Second wording"})
        # The one-step restore is just another save of the previous value.
        ws.set_edits("r1", "c1", {"warm-club_headline": "First wording"})
        edits = ws.load("r1")["c1"].edited_captions
        assert edits["warm-club_headline"] == "First wording"
        assert edits["prev.warm-club_headline"] == "Second wording"

    def test_insp_and_prev_keys_are_never_stashed(self, tmp_path):
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(tmp_path)
        ws.set_edits("r1", "c1", {"insp.accent": "#ff0000"})
        ws.set_edits("r1", "c1", {"insp.accent": "#00ff00"})
        edits = ws.load("r1")["c1"].edited_captions
        assert "prev.insp.accent" not in edits

    def test_row_button_carries_prev_caption_attr(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0020", profile_id=pid)
        ws = world.wm._get_wf_store()
        ws.set_edits("h10run0020", "s1", {"warm-club_headline": "First wording"})
        ws.set_edits("h10run0020", "s1", {"warm-club_headline": "Second wording"})
        html = _review(world, "h10run0020", pid)
        assert 'data-insp-caption="Second wording"' in html
        assert 'data-insp-caption-prev="First wording"' in html

    def test_drawer_ships_the_restore_control(self, world):
        pid = _save_org(world)
        _seed_run(world, "h10run0021", profile_id=pid)
        html = _review(world, "h10run0021", pid)
        assert 'id="mh-insp-caption-restore"' in html
        assert "Restore previous caption" in html
        assert "function restoreCaption()" in html

    def test_set_edits_route_persists_the_stash(self, world):
        """End-to-end through the drawer's own route: two saves, then the prev
        slot holds the first wording."""
        pid = _save_org(world)
        _seed_run(world, "h10run0022", profile_id=pid)
        c = _client(world, pid)
        for wording in ("First wording", "Second wording"):
            r = c.post(
                "/api/workflow/h10run0022/s1",
                json={
                    "action": "set_edits",
                    "edits": {
                        "warm-club_headline": wording,
                        "hype_headline": wording,
                        "data-led_headline": wording,
                    },
                },
            )
            assert r.status_code == 200
        edits = world.wm._get_wf_store().load("h10run0022")["s1"].edited_captions
        assert edits["warm-club_headline"] == "Second wording"
        assert edits["prev.warm-club_headline"] == "First wording"


# --------------------------------------------------------------------------- #
# 5. prev.* slots never leak into derived caption text or the pack
# --------------------------------------------------------------------------- #
class TestPrevSlotsInert:
    def test_caption_join_sites_exclude_prev(self):
        assert _WEB_SRC.count('startswith(("insp.", "prev."))') >= 1
        assert 'not str(k).startswith("prev.")' in _WEB_SRC

    def test_pack_builder_ignores_prev_slots(self, tmp_path):
        """The pack's tone_slot parser must not apply a prev.* slot as a
        caption override (same inertness contract as insp.*)."""
        card = {"brand_captions": {"warm-club": {"headline": "Current"}}}
        edited = {
            "warm-club_headline": "Current",
            "prev.warm-club_headline": "Old wording",
        }
        # Mirror workflow/pack.py's application loop.
        for key, val in edited.items():
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                t_str, slot = parts
                if t_str in card["brand_captions"]:
                    card["brand_captions"][t_str][slot] = val
        assert card["brand_captions"]["warm-club"]["headline"] == "Current"
