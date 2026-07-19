"""Merged-capability wiring — R1.5 accents, R1.10 photo grades, G1.8 mesh.

A PR audit found three merged capabilities whose trigger tokens no production
code path ever emitted. These tests pin the bridges that make them reachable
honestly:

  * **R1.5 accents** — every ``design_spec.ACCENT_TREATMENTS`` token is
    executed by BOTH surfaces (still: ``render._accent_decoration_html``;
    motion: ``StoryCard.tsx``'s inline switch or a ``sprint/accents/<token>.tsx``
    registry file), and ``apply_design_spec`` maps the director's
    ``accent_treatment`` onto ``brief.accent_style`` so the tokens actually
    flow brief → props.
  * **R1.10 photo grades** — the new ``design_spec.PHOTO_TREATMENTS``
    vocabulary reaches ``brief.photo_treatment`` (guarded: never overrides a
    structural "no-photo"/"frame" decision), where the still's
    ``_photo_treatment_css`` and the motion ``photo_filters`` layer already
    implement it in lock-step.
  * **G1.8 gradient mesh** — a style pack whose ground lever is
    ``gradient_mesh`` sets the brief's ``background_style`` opt-in token, so
    the ``gradient_mesh_bg`` render hook paints the real brand-role mesh.
    Explicit caller choices are never overridden; the bare token is reverted
    when a mood re-key moves the card off a mesh pack.
"""

from __future__ import annotations

import re

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import ai_director
from mediahub.creative_brief.design_spec import (
    ACCENT_TREATMENTS,
    DEFAULT_PHOTO_TREATMENT,
    PHOTO_TREATMENTS,
    design_spec_json_schema,
    normalise,
)
from mediahub.creative_brief.generator import (
    CreativeBrief,
    _sync_background_style_with_pack,
    apply_design_spec,
)
from mediahub.graphic_renderer import style_packs as sp
from mediahub.graphic_renderer.render import (
    _accent_decoration_html,
    _background_pattern_for,
    _photo_treatment_css,
)
from mediahub.graphic_renderer.archetypes import TOKEN_ROLES, list_archetypes
from mediahub.visual import motion


BRAND = BrandKit(
    profile_id="wire",
    display_name="Wiring SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="WSC",
)

_COMP = motion.REMOTION_DIR / "src" / "compositions"


def _bare_brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_wire",
        content_item_id="swim-wire-1",
        profile_id="wire",
        achievement_summary="Eira Hughes — 100m Freestyle — 1:01.00",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template="individual_hero",
        inspiration_pattern_id="p1",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="default",
        text_layers={"result_value": "1:01.00"},
        palette={"primary": "#0E2A47", "secondary": "#C9A227", "accent": "#C9A227"},
        format_priority=["feed_portrait"],
        hero_stat_options={"pb_delta": "−0.42s on PB"},
    )
    base.update(over)
    return CreativeBrief(**base)


def _spec(**over):
    raw = {
        "archetype": list_archetypes()[0],
        "colour_roles": {
            "ground": "primary",
            "surface": "surface",
            "headline": "on_primary",
            "accent": "accent",
        },
        "focal_element": "big_number",
        "crop_intent": "centered",
        "hero_stat": "pb_delta",
        "secondary_stats": [],
        "headline_hook": "WIRED",
        "accent_treatment": "minimal",
        "logo_lockup": "icon",
        "mood": "electric",
        "motion_intent": "fade_in",
        "rationale": "wiring test",
    }
    raw.update(over)
    return normalise(raw, archetypes=list_archetypes(), token_roles=list(TOKEN_ROLES))


# ---------------------------------------------------------------------------
# R1.5 — accent vocabulary is executed on BOTH surfaces (parity by token)
# ---------------------------------------------------------------------------

R15_PACK = {
    "thick_stripe",
    "thin_stripe",
    "double_stripe",
    "side_rail",
    "large_brackets",
    "small_brackets",
    "bracket_frame",
    "corner_tabs",
    "offset_badge",
}


def test_r15_pack_is_in_the_director_vocabulary():
    missing = R15_PACK - set(ACCENT_TREATMENTS)
    assert not missing, f"R1.5 accents absent from ACCENT_TREATMENTS: {sorted(missing)}"


def _motion_accent_tokens() -> set[str]:
    """Tokens the motion side executes: StoryCard's inline switch cases plus
    every registered sprint accent file (filename == token)."""
    src = (_COMP / "StoryCard.tsx").read_text()
    start = src.index("function accentDecoration(")
    body = src[start:]
    body = body[: body.index("\nfunction ", 1)]
    inline = set(re.findall(r'case\s+"([^"]+)":', body))
    files = {p.stem for p in (_COMP / "sprint" / "accents").glob("*.tsx")}
    return inline | files


def test_every_accent_treatment_token_has_a_motion_execution():
    executed = _motion_accent_tokens()
    for token in ACCENT_TREATMENTS:
        assert token in executed, f"{token!r} has no motion execution path"


def test_every_accent_treatment_token_has_a_still_execution():
    """Every non-"minimal" token must draw real accent-coloured geometry."""
    for token in ACCENT_TREATMENTS:
        html = _accent_decoration_html(token, "#FFD700", 1080, 1920, 0.5)
        if token == "minimal":
            assert html == ""
            continue
        assert html, f"{token!r} renders nothing on the still engine"
        assert "#FFD700" in html, f"{token!r} must paint in the accent colour"
        assert "position:absolute" in html
        assert "pointer-events:none" in html


def test_still_accents_scale_with_canvas_not_fixed_pixels():
    small = _accent_decoration_html("thick_stripe", "#FFD700", 540, 960, 0.5)
    large = _accent_decoration_html("thick_stripe", "#FFD700", 1080, 1920, 0.5)
    assert small != large, "accent geometry must derive from canvas size"


def test_still_accents_respect_zero_strength():
    for token in sorted(R15_PACK | {"diagonal_underline"}):
        assert _accent_decoration_html(token, "#FFD700", 1080, 1920, 0.0) == ""


def test_apply_design_spec_maps_accent_treatment_onto_the_brief():
    brief = _bare_brief()
    apply_design_spec(brief, _spec(accent_treatment="corner_tabs"))
    assert brief.accent_style == "corner_tabs"
    assert "|corner_tabs|" in brief.variation_signature  # audit/dedupe trail


def test_accent_token_flows_to_motion_props():
    brief = _bare_brief()
    apply_design_spec(brief, _spec(accent_treatment="offset_badge"))
    props = motion._card_to_props(
        {"id": "swim-wire-1", "achievement": {"swimmer_name": "Eira Hughes"}},
        brief=brief.to_dict(),
        brand_kit=BRAND,
    )
    assert props["accentStyle"] == "offset_badge"


def test_director_prompt_offers_the_accent_pack():
    prompt = ai_director._design_spec_system_prompt(
        list_archetypes(), list(TOKEN_ROLES)
    )
    for token in sorted(R15_PACK | {"diagonal_underline"}):
        assert token in prompt, f"{token!r} missing from the director prompt"


# ---------------------------------------------------------------------------
# R1.10 — photo grades: vocabulary + guarded mapping + both-surface execution
# ---------------------------------------------------------------------------


def test_photo_treatments_vocabulary_and_default():
    assert PHOTO_TREATMENTS == ("cutout", "duotone", "halftone", "vignette", "wash", "sticker")
    assert DEFAULT_PHOTO_TREATMENT in PHOTO_TREATMENTS
    # Structural decisions are NOT art direction — never offered to the model.
    assert "no-photo" not in PHOTO_TREATMENTS
    assert "frame" not in PHOTO_TREATMENTS


def test_normalise_coerces_photo_treatment():
    assert _spec(photo_treatment="duotone").photo_treatment == "duotone"
    assert _spec(photo_treatment=" HALFTONE ").photo_treatment == "halftone"
    assert _spec(photo_treatment="sepia-dream").photo_treatment == "cutout"
    assert _spec().photo_treatment == "cutout"  # absent field → clean default


def test_schema_carries_photo_treatment_enum():
    schema = design_spec_json_schema(
        archetypes=list_archetypes(), token_roles=list(TOKEN_ROLES)
    )
    assert schema["properties"]["photo_treatment"]["enum"] == list(PHOTO_TREATMENTS)
    assert "photo_treatment" in schema["required"]


def test_spec_to_dict_carries_photo_treatment():
    assert _spec(photo_treatment="vignette").to_dict()["photo_treatment"] == "vignette"


def test_apply_design_spec_grades_the_default_photo_path():
    brief = _bare_brief()
    apply_design_spec(brief, _spec(photo_treatment="duotone"))
    assert brief.photo_treatment == "duotone"
    assert "duotone" in brief.image_treatment  # phrase stays in step


def test_apply_design_spec_never_overrides_a_structural_treatment():
    for structural in ("no-photo", "frame"):
        brief = _bare_brief(photo_treatment=structural)
        before_phrase = brief.image_treatment
        apply_design_spec(brief, _spec(photo_treatment="vignette"))
        assert brief.photo_treatment == structural
        assert brief.image_treatment == before_phrase


def test_apply_design_spec_clean_cutout_leaves_the_brief_untouched():
    brief = _bare_brief()
    apply_design_spec(brief, _spec(photo_treatment="cutout"))
    assert brief.photo_treatment == "cutout"
    assert brief.image_treatment == "cutout"


def test_each_grade_is_executed_by_both_surfaces():
    """Still: a CSS grade; motion: the photo_filters layer names the token."""
    layer_src = (_COMP / "sprint" / "layers" / "photo_filters.tsx").read_text()
    for grade in ("duotone", "halftone", "vignette"):
        assert _photo_treatment_css(grade, {"accent": "#FFF"}), grade
        assert f'"{grade}"' in layer_src, grade


def test_photo_grade_flows_to_motion_props():
    brief = _bare_brief()
    apply_design_spec(brief, _spec(photo_treatment="halftone"))
    props = motion._card_to_props(
        {"id": "swim-wire-1", "achievement": {"swimmer_name": "Eira Hughes"}},
        brief=brief.to_dict(),
        brand_kit=BRAND,
    )
    assert props["photoTreatment"] == "halftone"


def test_director_prompt_offers_the_photo_grades():
    prompt = ai_director._design_spec_system_prompt(
        list_archetypes(), list(TOKEN_ROLES)
    )
    assert "photo_treatment" in prompt
    for grade in ("duotone", "halftone", "vignette"):
        assert grade in prompt


# ---------------------------------------------------------------------------
# G1.8 — the style-pack ground lever triggers the real gradient-mesh engine
# ---------------------------------------------------------------------------


def _pack_with_ground(ground: str) -> sp.StylePack:
    for pack in sp.list_style_packs():
        if pack.ground == ground:
            return pack
    raise AssertionError(f"no pack with ground={ground!r} in the catalog")


def test_mesh_ground_pack_sets_the_hook_token():
    brief = _bare_brief(style_pack=_pack_with_ground("gradient_mesh").id)
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "gradient_mesh"


def test_non_mesh_pack_keeps_the_default_background():
    brief = _bare_brief(style_pack=_pack_with_ground("vignette").id)
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "water"


def test_explicit_background_choice_is_never_overridden():
    brief = _bare_brief(
        style_pack=_pack_with_ground("gradient_mesh").id, background_style="clean"
    )
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "clean"
    # A mode-suffixed explicit opt-in survives a re-key onto a non-mesh pack.
    brief = _bare_brief(
        style_pack=_pack_with_ground("vignette").id,
        background_style="gradient_mesh:radial",
    )
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "gradient_mesh:radial"


def test_rekey_off_a_mesh_pack_reverts_the_bare_token():
    brief = _bare_brief(style_pack=_pack_with_ground("gradient_mesh").id)
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "gradient_mesh"
    brief.style_pack = _pack_with_ground("flat").id
    _sync_background_style_with_pack(brief)
    assert brief.background_style == "water"


def test_apply_design_spec_keeps_pack_and_mesh_token_in_step():
    """The mood re-key inside apply_design_spec must re-run the sync so the
    signature/audit trail always reflects the final pack."""
    brief = _bare_brief(style_pack=_pack_with_ground("gradient_mesh").id)
    apply_design_spec(brief, _spec())
    want = "gradient_mesh" if _pack_ground(brief.style_pack) == "gradient_mesh" else "water"
    assert brief.background_style == want
    assert f"|{brief.background_style}|" in brief.variation_signature


def _pack_ground(pack_id: str) -> str:
    pack = sp.style_pack_from_id(pack_id)
    return pack.ground if pack else ""


def test_mesh_token_reaches_the_render_hook_end_to_end():
    from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
    from mediahub.graphic_renderer.sprint_hooks import gradient_mesh_bg as hook

    brief = _bare_brief(style_pack=_pack_with_ground("gradient_mesh").id)
    _sync_background_style_with_pack(brief)
    html = "<html><body><div>card</div></body></html>"
    out = hook.apply(
        html,
        RenderHookCtx(
            brief=brief,
            width=1080,
            height=1350,
            family="big_number_dominant",
            format_name="feed_portrait",
            is_v2=True,
        ),
    )
    assert "mh:gradient-mesh G1.8" in out, "the hook must fire for a mesh-pack brief"
    assert "data:image/svg+xml;base64," in out


def test_mesh_token_takes_no_pattern_tile():
    from mediahub.graphic_renderer.render import _bg_clean_data_uri

    clean = _bg_clean_data_uri()
    assert _background_pattern_for("gradient_mesh") == clean
    assert _background_pattern_for("gradient_mesh:conic") == clean
    assert _background_pattern_for("mesh") == clean
    # the default is untouched
    assert _background_pattern_for("water") != clean
