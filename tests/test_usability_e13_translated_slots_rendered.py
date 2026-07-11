"""E-13 — every translated slot renders before approval, not just the caption.

The audit found the /translate route persists caption + alt_text + headline +
subhead variants via ``ws.set_translation(...)``, but the UI rendered only
``jj.slots.caption`` (and set ``dir`` only on that one span) — so a translated
alt text / headline / subhead rode into approval and export unreviewed: a
human-approval bypass.

This file pins the fix:

  * ``_render_stored_translations`` renders EVERY slot a saved variant
    carries — caption, alt text, headline, subhead — each with a plain label
    and its own ``dir`` attribute, all ``_h``-escaped; a variant with no
    caption but a saved alt text still renders (previously dropped);
  * unknown slot keys still render (labelled from the key) so nothing a
    variant carries can skip review;
  * the review row (/review — BEFORE approval) shows the card's saved
    translations;
  * the pack/Content-builder page still shows them on load (all slots now);
  * the on-demand translate JS renders every returned slot with per-slot
    labels and dir, not only ``jj.slots.caption``.
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
# Fixtures (modelled on tests/test_usability_h10_edit_card_caption.py)
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


_FULL_VARIANT = {
    "language": "cy",
    "language_label": "Cymraeg",
    "rtl": False,
    "slots": {
        "caption": "Torrodd Tamsin PB newydd!",
        "alt_text": "Tamsin yn nofio yn y ras derfynol",
        "headline": "Aur i Tamsin",
        "subhead": "200m IM mewn amser gorau personol",
    },
}


# --------------------------------------------------------------------------- #
# 1. The stored-translations helper renders EVERY slot, labelled, own dir
# --------------------------------------------------------------------------- #
class TestStoredTranslationsAllSlots:
    def _card(self, variant, lang="cy"):
        return {"workflow": {"translations": {lang: variant}}}

    def test_all_four_slots_render_with_plain_labels(self, world):
        html = world.wm._render_stored_translations(self._card(_FULL_VARIANT))
        for text in _FULL_VARIANT["slots"].values():
            assert text in html
        for label in ("Caption", "Alt text", "Headline", "Subhead"):
            assert label in html
        assert "Cymraeg" in html
        assert "Saved translations" in html

    def test_each_slot_span_carries_its_own_dir(self, world):
        variant = dict(_FULL_VARIANT, rtl=True, language_label="العربية")
        html = world.wm._render_stored_translations(self._card(variant, lang="ar"))
        # One dir="rtl" per slot span — not only on the caption.
        assert html.count('dir="rtl"') == 4

    def test_variant_without_caption_still_renders_other_slots(self, world):
        # Previously a variant with no caption text contributed NOTHING —
        # a saved alt text / headline / subhead silently skipped review.
        variant = {
            "language_label": "Cymraeg",
            "rtl": False,
            "slots": {"alt_text": "Disgrifiad amgen", "headline": "Aur i Tamsin"},
        }
        html = world.wm._render_stored_translations(self._card(variant))
        assert "Disgrifiad amgen" in html
        assert "Alt text" in html
        assert "Aur i Tamsin" in html
        assert "Headline" in html

    def test_unknown_slot_key_still_renders(self, world):
        variant = {"rtl": False, "slots": {"cta_line": "Dewch i gefnogi"}}
        html = world.wm._render_stored_translations(self._card(variant))
        assert "Dewch i gefnogi" in html
        assert "Cta line" in html  # label derived from the key

    def test_every_slot_is_escaped(self, world):
        variant = {
            "rtl": False,
            "slots": {
                "caption": "<script>a</script>",
                "alt_text": "<img onerror=x>",
                "headline": "<b>bold</b>",
                "subhead": "<i>it</i>",
            },
        }
        html = world.wm._render_stored_translations(self._card(variant))
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert "<img" not in html and "&lt;img" in html
        assert "<b>" not in html and "<i>" not in html

    def test_empty_variants_render_nothing(self, world):
        assert world.wm._render_stored_translations({}) == ""
        assert world.wm._render_stored_translations(self._card({"slots": {}})) == ""
        assert world.wm._render_stored_translations(self._card({"slots": {"caption": "  "}})) == ""


# --------------------------------------------------------------------------- #
# 2. /review shows the saved translation slots BEFORE approval
# --------------------------------------------------------------------------- #
class TestReviewRowShowsSavedTranslations:
    def test_queued_card_renders_all_saved_slots(self, world):
        pid = _save_org(world)
        _seed_run(world, "e13run0001", profile_id=pid)
        world.wm._get_wf_store().set_translation("e13run0001", "s1", "cy", _FULL_VARIANT)
        html = _client(world, pid).get("/review/e13run0001").get_data(as_text=True)
        assert "Saved translations" in html
        for text in _FULL_VARIANT["slots"].values():
            assert text in html
        for label in ("Alt text", "Headline", "Subhead"):
            assert label in html

    def test_untranslated_card_renders_no_saved_translations_block(self, world):
        pid = _save_org(world)
        _seed_run(world, "e13run0002", profile_id=pid)
        html = _client(world, pid).get("/review/e13run0002").get_data(as_text=True)
        assert "Saved translations" not in html

    def test_rtl_variant_slots_each_carry_dir_on_review(self, world):
        pid = _save_org(world)
        _seed_run(world, "e13run0003", profile_id=pid)
        variant = dict(_FULL_VARIANT, rtl=True, language_label="العربية")
        world.wm._get_wf_store().set_translation("e13run0003", "s1", "ar", variant)
        html = _client(world, pid).get("/review/e13run0003").get_data(as_text=True)
        assert html.count('dir="rtl"') >= 4


# --------------------------------------------------------------------------- #
# 3. The pack / Content-builder page shows every slot on load
# --------------------------------------------------------------------------- #
class TestPackPageShowsAllSlots:
    def test_approved_card_renders_all_saved_slots(self, world):
        from mediahub.workflow.status import CardStatus

        pid = _save_org(world)
        _seed_run(world, "e13run0010", profile_id=pid)
        ws = world.wm._get_wf_store()
        ws.set_status("e13run0010", "s1", CardStatus.APPROVED)
        ws.set_translation("e13run0010", "s1", "cy", _FULL_VARIANT)
        html = _client(world, pid).get("/pack/e13run0010").get_data(as_text=True)
        assert "Saved translations" in html
        for text in _FULL_VARIANT["slots"].values():
            assert text in html
        for label in ("Alt text", "Headline", "Subhead"):
            assert label in html


# --------------------------------------------------------------------------- #
# 4. The on-demand translate JS renders every returned slot (source-level)
# --------------------------------------------------------------------------- #
class TestTranslateResponseJs:
    def test_caption_only_render_is_gone(self):
        # The old handler rendered exactly one slot and dropped the rest.
        assert "jj.slots.caption) || ''" not in _WEB_SRC

    def test_every_slot_renders_with_labels_and_per_slot_dir(self, world):
        js = world.wm._card_creative_js()
        # A label map covering all four persisted slots…
        assert "alt_text:'Alt text'" in js
        assert "headline:'Headline'" in js
        assert "subhead:'Subhead'" in js
        # …iterated over every key the response carries (unknown keys included)…
        assert "Object.keys(jj.slots || {})" in js
        # …with the dir attribute stamped per slot span.
        m = re.search(r"slotKeys\.forEach\(function\(k\)\{(.*?)\}\);", js, re.S)
        assert m, "the per-slot render loop must exist"
        assert "dir=" in m.group(1)
        # The bilingual-pair phrasing stays (pinned by the 1.24 tests too).
        assert "saved with this card" in js
