"""P6.2 — the spec-patch contract (assistant/patch.py).

The deterministic heart of the copilot: parse model output into a bounded
SpecPatch, then apply only valid ops to a *copy* of the brief, rejecting
out-of-vocabulary ops and illegible colour-role changes with reasons.
"""

from __future__ import annotations

from mediahub.assistant.patch import OP_KINDS, apply_patch, parse_patch
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


# ---------------------------------------------------------------------------
# parse_patch — drop, never guess
# ---------------------------------------------------------------------------


def test_parse_drops_unknown_op_kinds():
    patch = parse_patch({"ops": [{"kind": "set_mood", "mood": "bold"}, {"kind": "delete_everything"}]})
    assert [o.kind for o in patch.ops] == ["set_mood"]


def test_parse_accepts_bare_list_and_dict():
    assert len(parse_patch([{"kind": "set_hook", "text": "x"}]).ops) == 1
    assert len(parse_patch({"ops": [{"kind": "set_hook", "text": "x"}]}).ops) == 1


def test_parse_garbage_is_empty():
    assert parse_patch(None).ops == []
    assert parse_patch("nope").ops == []
    assert parse_patch({"ops": "notalist"}).ops == []


def test_all_advertised_op_kinds_round_trip():
    # Every op kind the tool advertises must parse (kept in lock-step).
    for kind in OP_KINDS:
        assert parse_patch({"ops": [{"kind": kind}]}).ops[0].kind == kind


# ---------------------------------------------------------------------------
# apply_patch — validation + no mutation
# ---------------------------------------------------------------------------


def test_applies_valid_text_and_vocab_ops():
    src = _brief()
    patch = parse_patch(
        {
            "ops": [
                {"kind": "set_headline", "text": "SEASON BEST"},
                {"kind": "set_hook", "text": "UNDER A MINUTE"},
                {"kind": "set_mood", "mood": "triumphant"},
                {"kind": "set_archetype", "archetype": "big_number_dominant"},
                {"kind": "set_motion_intent", "motion_intent": "count_up"},
                {"kind": "set_accent_treatment", "treatment": "ribbon"},
                {"kind": "set_format", "format": "ig_square"},
                {"kind": "set_tone", "tone": "hype"},
            ]
        }
    )
    res = apply_patch(src, patch, brand_kit=None)
    assert len(res.applied) == 8 and not res.rejected
    b = res.brief
    assert b.text_layers["headline_line1"] == "SEASON BEST"
    assert b.primary_hook == "UNDER A MINUTE"
    assert b.mood == "triumphant"
    assert b.layout_template == "big_number_dominant"
    assert b.motion_intent == "count_up"
    assert b.accent_style == "ribbon"
    assert b.format_priority[0] == "feed_square"  # ig_square → render name
    assert b.tone == "hype"


def test_rejects_out_of_vocabulary_with_reasons():
    src = _brief()
    patch = parse_patch(
        {
            "ops": [
                {"kind": "set_mood", "mood": "not_a_mood"},
                {"kind": "set_archetype", "archetype": "does_not_exist"},
                {"kind": "set_format", "format": "nope"},
                {"kind": "set_tone", "tone": "shouty"},
                {"kind": "set_colour_role", "slot": "weird", "role": "primary"},
                {"kind": "set_headline", "text": ""},
            ]
        }
    )
    res = apply_patch(src, patch, brand_kit=None)
    assert not res.applied
    assert len(res.rejected) == 6
    reasons = " ".join(why for _, why in res.rejected)
    assert "mood" in reasons and "layout" in reasons and "format" in reasons


def test_source_brief_is_never_mutated():
    src = _brief()
    apply_patch(src, parse_patch({"ops": [{"kind": "set_headline", "text": "NEW"}]}), brand_kit=None)
    assert src.text_layers["headline_line1"] == "OLD"
    assert src.layout_template == "split_diagonal_hero"


def test_changed_brief_gets_a_new_id():
    src = _brief()
    res = apply_patch(src, parse_patch({"ops": [{"kind": "set_mood", "mood": "bold"}]}), brand_kit=None)
    assert res.brief.id != src.id and res.brief.id.startswith("cb_")


def test_unchanged_brief_keeps_id():
    src = _brief()
    res = apply_patch(src, parse_patch({"ops": [{"kind": "set_mood", "mood": "bogus"}]}), brand_kit=None)
    assert res.brief.id == src.id  # nothing applied → not a new version


def test_colour_role_applied_when_legible():
    src = _brief()
    res = apply_patch(
        src,
        parse_patch({"ops": [{"kind": "set_colour_role", "slot": "accent", "role": "secondary"}]}),
        brand_kit=None,
    )
    # palette here is legible, so the role assignment lands.
    assert res.applied and res.brief.colour_role_assignment.get("accent") == "secondary"


def test_illegible_colour_role_is_rejected_and_reverted(monkeypatch):
    # Force the legibility gate to fail; the op must be rejected and the
    # assignment left untouched (never paint illegibly).
    import mediahub.assistant.patch as patch_mod

    monkeypatch.setattr(patch_mod, "_colour_roles_legible", lambda brief, bk: False)
    src = _brief()
    res = apply_patch(
        src,
        parse_patch({"ops": [{"kind": "set_colour_role", "slot": "headline", "role": "accent"}]}),
        brand_kit=None,
    )
    assert not res.applied and res.rejected
    assert "legib" in res.rejected[0][1].lower()
    assert not res.brief.colour_role_assignment.get("headline")


def test_clear_photo_sets_no_photo():
    res = apply_patch(_brief(), parse_patch({"ops": [{"kind": "clear_photo"}]}), brand_kit=None)
    assert res.brief.photo_treatment == "no-photo"


def test_partial_apply_keeps_good_drops_bad():
    src = _brief()
    res = apply_patch(
        src,
        parse_patch(
            {"ops": [{"kind": "set_mood", "mood": "bold"}, {"kind": "set_mood", "mood": "xxx"}]}
        ),
        brand_kit=None,
    )
    assert len(res.applied) == 1 and len(res.rejected) == 1
    assert res.brief.mood == "bold"


def test_summary_mentions_applied_and_skipped():
    res = apply_patch(
        _brief(),
        parse_patch({"ops": [{"kind": "set_mood", "mood": "bold"}, {"kind": "set_mood", "mood": "x"}]}),
        brand_kit=None,
    )
    s = res.summary()
    assert "applied" in s and "skipped" in s
