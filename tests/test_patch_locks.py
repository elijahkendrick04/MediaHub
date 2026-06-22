"""Roadmap 1.18 build 3 — element locks enforced at patch time (assistant.patch).

A locked element refuses the matching copilot op before it touches the brief,
while unlocked ops still apply — so a lock holds even against the assistant.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.assistant.patch import apply_patch, parse_patch
from mediahub.creative_brief.generator import CreativeBrief


def _brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_src",
        content_item_id="swim_1",
        profile_id="club",
        achievement_summary="",
        objective="",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="data-led",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={"headline_line1": "OLD"},
        palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"},
        format_priority=["story"],
    )
    base.update(over)
    return CreativeBrief(**base)


def test_locked_headline_refuses_set_headline():
    src = _brief()
    patch = parse_patch({"ops": [{"kind": "set_headline", "text": "CHANGED"}]})
    res = apply_patch(src, patch, locked_elements={"headline"})
    assert res.applied == []
    assert len(res.rejected) == 1
    assert "locked" in res.rejected[0][1].lower()
    # brief unchanged (no new version minted)
    assert res.brief.text_layers.get("headline_line1") == "OLD"


def test_unlocked_headline_still_applies():
    src = _brief()
    patch = parse_patch({"ops": [{"kind": "set_headline", "text": "CHANGED"}]})
    res = apply_patch(src, patch, locked_elements=set())
    assert len(res.applied) == 1
    assert res.brief.text_layers.get("headline_line1") == "CHANGED"


def test_lock_one_element_others_still_apply():
    src = _brief()
    patch = parse_patch(
        {
            "ops": [
                {"kind": "set_headline", "text": "CHANGED"},  # locked → rejected
                {"kind": "set_mood", "mood": "bold"},  # unlocked → applied
            ]
        }
    )
    res = apply_patch(src, patch, locked_elements={"headline"})
    kinds_applied = [o.kind for o in res.applied]
    kinds_rejected = [o.kind for o, _ in res.rejected]
    assert "set_mood" in kinds_applied
    assert "set_headline" in kinds_rejected


def test_clear_photo_blocked_when_photo_locked():
    src = _brief()
    patch = parse_patch({"ops": [{"kind": "clear_photo"}]})
    res = apply_patch(src, patch, locked_elements={"photo"})
    assert res.applied == []
    assert any("locked" in why.lower() for _, why in res.rejected)


def test_no_locks_param_is_backward_compatible():
    src = _brief()
    patch = parse_patch({"ops": [{"kind": "set_headline", "text": "CHANGED"}]})
    res = apply_patch(src, patch)  # no locked_elements kwarg
    assert len(res.applied) == 1
