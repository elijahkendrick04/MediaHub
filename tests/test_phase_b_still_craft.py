"""Phase B — still-graphic craft (M7–M14).

Covers photo-aware art direction (archetype partition + photo facts), the
per-archetype photo mode, the wired grading stack, crop-intent execution, the
true duotone/halftone treatments, real data weight (stat chips + honest
proportional PB bars), the layered-depth archetypes, badge anchors, and the
cutout matte gate with its honest fallback.
"""

from __future__ import annotations

import base64
import io
import re

import pytest
from PIL import Image

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import (
    apply_design_spec,
    generate as gen_brief,
)
from mediahub.creative_brief.design_spec import normalise
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        accent_colour="#F2C14E",
        short_name="TSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _item(**raw_facts):
    ach = {
        "swimmer_name": "Eira Hughes",
        "event_name": "200m Freestyle",
        "result_time": "2:08.41",
    }
    if raw_facts:
        ach["raw_facts"] = raw_facts
    return {"id": "ci-1", "post_angle": "individual_pb", "achievement": ach}


def _brief(item=None, *, seed=0, photo_facts=None):
    return gen_brief(
        item or _item(),
        _eval(),
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        variation_seed=seed,
        photo_facts=photo_facts,
    )


def _photo(tmp_path, name="athlete.jpg", size=(400, 600)):
    """A busy-background action-ish photo (JPEG, no alpha)."""
    p = tmp_path / name
    im = Image.new("RGB", size, (18, 60, 150))
    # texture so gradient saliency has signal
    for x in range(0, size[0], 24):
        for y in range(0, size[1], 24):
            im.paste(Image.new("RGB", (12, 12), (240, 230, 200)), (x, y))
    # a person-ish dark blob upper-centre
    im.paste(Image.new("RGB", (110, 110), (30, 20, 15)), (size[0] // 2 - 55, 60))
    im.paste(Image.new("RGB", (170, 260), (200, 60, 40)), (size[0] // 2 - 85, 165))
    im.save(p, "JPEG", quality=90)
    return p


def _person_cutout(tmp_path, name="cutout.png", size=(400, 600)):
    """A person-ish silhouette (head + torso) on transparency — a good matte."""
    p = tmp_path / name
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    from PIL import ImageDraw

    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse((w * 0.38, h * 0.08, w * 0.62, h * 0.26), fill=(200, 150, 120, 255))
    d.rectangle((w * 0.30, h * 0.26, w * 0.70, h * 1.0), fill=(180, 40, 40, 255))
    im.save(p)
    return p


def _render_html(monkeypatch, tmp_path, brief, *, athlete_path=None, out="card", **kw):
    """Assemble the card HTML through the real render_brief with the
    Chromium screenshot stubbed."""
    import mediahub.graphic_renderer.render as R

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    res = R.render_brief(
        brief,
        output_dir=tmp_path / out,
        size=(1080, 1350),
        athlete_path=athlete_path,
        brand_kit=_brand(),
        **kw,
    )
    return captured["html"], res


# --------------------------------------------------------------------------- #
# M7 — photo partition + photo-aware picks
# --------------------------------------------------------------------------- #


def test_photo_partition_derived_from_templates():
    photo = archetypes.photo_archetypes()
    typeled = archetypes.type_archetypes()
    everything = set(archetypes.list_archetypes())
    assert photo | typeled == everything
    assert not (photo & typeled)
    # spot checks against the templates themselves
    assert "full_bleed_photo_lower_third" in photo
    assert "spotlight_disc" in photo
    assert "big_number_dominant" in typeled
    assert "mega_surname_bleed" in typeled
    for name in photo:
        raw = (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
        assert "{{ATHLETE_IMG_BLOCK}}" in raw or "{{ATHLETE_IMG_VAR}}" in raw


def test_photo_mode_registry_covers_every_archetype():
    for name in archetypes.list_archetypes():
        mode = archetypes.photo_mode(name)
        assert mode in ("photo", "cutout"), name
    # window/full-bleed archetypes show the ORIGINAL photograph
    for name in (
        "full_bleed_photo_lower_third",
        "magazine_cover",
        "photo_passepartout",
        "duo_athlete_split",
        "split_diagonal_hero",
        "broadcast_scorebug",
        "contact_sheet",
        "stat_stack_sidebar",
        "triptych_progression",
        "timeline_progression",
        "ticker_strip",
        "full_height_portrait_split",
    ):
        assert archetypes.photo_mode(name) == "photo", name
    # layering archetypes keep the cutout
    for name in ("spotlight_disc", "relay_collage", "poster_name_behind", "band_break"):
        assert archetypes.photo_mode(name) == "cutout", name


def test_pickers_respect_a_subset_pool_deterministically():
    pool = sorted(archetypes.photo_archetypes())
    assert archetypes.pick_archetype(7, pool) == pool[7 % len(pool)]
    assert archetypes.pick_archetype(7, pool) == archetypes.pick_archetype(7, pool)
    # avoiding walks within the subset only
    first = archetypes.pick_archetype_avoiding(7, [], pool)
    second = archetypes.pick_archetype_avoiding(7, [first], pool)
    assert first in pool and second in pool and second != first
    # no subset → the historic full-library pick, byte-identical
    assert archetypes.pick_archetype(7) == archetypes.list_archetypes()[
        7 % len(archetypes.list_archetypes())
    ]


def test_generator_partition_photo_less_never_photo_led(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    for seed in range(14):
        b = _brief(seed=seed, photo_facts={"has_photo": False})
        assert b.layout_template in archetypes.type_archetypes(), b.layout_template


def test_generator_partition_photo_prefers_photo_led(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    facts = {
        "has_photo": True,
        "asset_type": "athlete_action",
        "orientation": "portrait",
        "person_photo_count": 3,
    }
    for seed in range(14):
        b = _brief(seed=seed, photo_facts=facts)
        assert b.layout_template in archetypes.photo_archetypes(), b.layout_template


def test_generator_without_facts_is_photo_blind(monkeypatch):
    # Legacy callers (photo_facts=None) keep the historic full-library pick.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    b = _brief(seed=5)
    assert b.layout_template == archetypes.pick_archetype(5)


def test_director_prompt_carries_photo_facts():
    from mediahub.creative_brief.ai_director import _design_spec_user_prompt, _photo_context

    line = _photo_context(
        {
            "has_photo": True,
            "asset_type": "athlete_action",
            "orientation": "portrait",
            "person_photo_count": 4,
        }
    )
    assert "portrait" in line and "athlete action" in line and "4 person photos" in line
    none_line = _photo_context({"has_photo": False})
    assert "none available" in none_line and "type-led" in none_line
    prompt = _design_spec_user_prompt("summary", "brand", "angle", [], {"has_photo": False})
    assert "PHOTO: none available" in prompt
    # legacy callers: no facts, no PHOTO line — byte-identical prompt
    assert "PHOTO" not in _design_spec_user_prompt("summary", "brand", "angle", [])


def test_candidate_compliance_photo_fit_term():
    from mediahub.content_pack_visual.integration import _candidate_compliance

    brief = _brief()
    brief.layout_template = "full_bleed_photo_lower_third"
    spec = normalise(
        {"archetype": "full_bleed_photo_lower_third"},
        archetypes=archetypes.list_archetypes(),
        token_roles=["primary", "accent"],
    )
    with_photo = _candidate_compliance(
        brief, _brand(), spec, lockups=[], sponsor_name="", has_photo=True
    )
    without = _candidate_compliance(
        brief, _brand(), spec, lockups=[], sponsor_name="", has_photo=False
    )
    assert with_photo["photo_fit"] == 1.0
    assert without["photo_fit"] == 0.0
    legacy = _candidate_compliance(brief, _brand(), spec, lockups=[], sponsor_name="")
    assert "photo_fit" not in legacy


def test_brief_records_photo_mode(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    b = _brief(seed=0, photo_facts={"has_photo": True})
    assert b.photo_mode == archetypes.photo_mode(b.layout_template)
    spec = normalise(
        {"archetype": "spotlight_disc"},
        archetypes=archetypes.list_archetypes(),
        token_roles=["primary", "accent"],
    )
    apply_design_spec(b, spec)
    assert b.photo_mode == "cutout"


# --------------------------------------------------------------------------- #
# M8 — per-archetype photo mode at render time
# --------------------------------------------------------------------------- #


def _inlined_photo_bytes(html: str) -> bytes:
    m = re.search(r'class="athlete-cutout" src="data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)"', html)
    if m is None:
        m = re.search(
            r"--mh-athlete-img:url\('data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)'\)", html
        )
    assert m, "no inlined athlete photo found"
    return base64.b64decode(m.group(1))


def test_photo_mode_archetype_renders_the_original(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    photo = _photo(tmp_path)
    calls = []
    monkeypatch.setattr(
        R,
        "_athlete_cutout_with_note",
        lambda p, profile_id="default": calls.append(p) or (p, None),
    )
    brief = _brief()
    brief.layout_template = "full_bleed_photo_lower_third"
    brief.photo_adjust = "none"  # isolate the mode decision from the grade
    html, res = _render_html(monkeypatch, tmp_path, brief, athlete_path=str(photo))
    # the ORIGINAL bytes are inlined and the cutout pipeline never ran
    assert calls == []
    assert _inlined_photo_bytes(html) == photo.read_bytes()


def test_cutout_mode_archetype_runs_the_cutout(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    photo = _photo(tmp_path)
    cut = _person_cutout(tmp_path)
    monkeypatch.setattr(
        R, "_athlete_cutout_with_note", lambda p, profile_id="default": (cut, None)
    )
    brief = _brief()
    brief.layout_template = "spotlight_disc"
    brief.photo_adjust = "none"
    html, res = _render_html(monkeypatch, tmp_path, brief, athlete_path=str(photo))
    assert _inlined_photo_bytes(html) == cut.read_bytes()


def test_matte_fallback_marks_photo_flat_and_traces(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    photo = _photo(tmp_path)
    note = "cutout rejected (shredded matte) — using original photo"
    monkeypatch.setattr(
        R, "_athlete_cutout_with_note", lambda p, profile_id="default": (p, note)
    )
    brief = _brief()
    brief.layout_template = "poster_name_behind"
    brief.photo_adjust = "none"
    html, res = _render_html(monkeypatch, tmp_path, brief, athlete_path=str(photo))
    assert 'class="pnb mh-photo-flat"' in html
    assert note in res.visual.safety_notes


# --------------------------------------------------------------------------- #
# M9 — the wired grading stack
# --------------------------------------------------------------------------- #


def test_mood_maps_to_photo_recipe(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_PHOTO_ADJUST", raising=False)
    b = _brief()
    assert b.photo_adjust == "natural"
    for mood, preset in (
        ("celebratory", "punchy"),
        ("explosive", "punchy"),
        ("stoic", "editorial"),
        ("precise", "editorial"),
        ("calm", "soft"),
        ("warm", "soft"),
        ("neutral", "natural"),
    ):
        spec = normalise(
            {"archetype": "big_number_dominant", "mood": mood},
            archetypes=archetypes.list_archetypes(),
            token_roles=["primary", "accent"],
        )
        bb = _brief()
        apply_design_spec(bb, spec)
        assert bb.photo_adjust == preset, mood


def test_env_preset_overrides_the_neutral_default(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_PHOTO_ADJUST", "vivid")
    assert _brief().photo_adjust == "vivid"
    # a keyed mood is a deliberate per-card direction — it still wins
    spec = normalise(
        {"archetype": "big_number_dominant", "mood": "stoic"},
        archetypes=archetypes.list_archetypes(),
        token_roles=["primary", "accent"],
    )
    b = _brief()
    apply_design_spec(b, spec)
    assert b.photo_adjust == "editorial"


def test_recipe_signature_salts_the_asset_cache(tmp_path):
    from mediahub.graphic_renderer import render_cache

    p = _photo(tmp_path)
    render_cache.clear()
    a = render_cache.asset_data_uri(p, loader=lambda q: "A", salt="recipe:aaa")
    b = render_cache.asset_data_uri(p, loader=lambda q: "B", salt="recipe:bbb")
    assert a == "A" and b == "B"  # different grades of one file never collide
    assert render_cache.asset_data_uri(p, loader=lambda q: "X", salt="recipe:aaa") == "A"
    render_cache.clear()


def test_graded_render_records_the_grade_and_changes_bytes(monkeypatch, tmp_path):
    photo = _photo(tmp_path)
    brief = _brief()
    brief.layout_template = "full_bleed_photo_lower_third"
    assert brief.photo_adjust == "natural"
    html, res = _render_html(monkeypatch, tmp_path, brief, athlete_path=str(photo), out="graded")
    assert any(n.startswith("photo adjusted (natural)") for n in res.visual.safety_notes)
    assert _inlined_photo_bytes(html) != photo.read_bytes()  # pixels really graded


# --------------------------------------------------------------------------- #
# M10 — crop intent + true treatments
# --------------------------------------------------------------------------- #


def test_crop_intent_default_is_byte_identical(monkeypatch, tmp_path):
    photo = _photo(tmp_path)
    base = _brief()
    base.layout_template = "full_bleed_photo_lower_third"
    base.photo_adjust = "none"
    html_a, _ = _render_html(monkeypatch, tmp_path, base, athlete_path=str(photo), out="a")
    for intent in ("", "original", "full_bleed", "wide_action"):
        b = _brief()
        b.layout_template = "full_bleed_photo_lower_third"
        b.photo_adjust = "none"
        b.crop_intent = intent
        html_b, _ = _render_html(
            monkeypatch, tmp_path, b, athlete_path=str(photo), out=f"i_{intent or 'none'}"
        )
        assert html_b == html_a, intent


def test_crop_intent_centered_and_tight(monkeypatch, tmp_path):
    photo = _photo(tmp_path)
    b = _brief()
    b.layout_template = "full_bleed_photo_lower_third"
    b.photo_adjust = "none"
    b.crop_intent = "centered"
    html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out="c")
    assert "--mh-photo-pos:50% 50%;" in html
    assert "--mh-photo-scale" not in html

    t = _brief()
    t.layout_template = "full_bleed_photo_lower_third"
    t.photo_adjust = "none"
    t.crop_intent = "tight_portrait"
    html_t, _ = _render_html(monkeypatch, tmp_path, t, athlete_path=str(photo), out="t")
    m = re.search(r"--mh-photo-scale:([\d.]+);", html_t)
    assert m and 1.05 <= float(m.group(1)) <= 1.31
    assert "transform: scale(var(--mh-photo-scale, 1))" in html_t


def test_manual_crop_override_beats_crop_intent(monkeypatch, tmp_path):
    photo = _photo(tmp_path)
    b = _brief()
    b.layout_template = "full_bleed_photo_lower_third"
    b.photo_adjust = "none"
    b.crop_intent = "centered"
    html, _ = _render_html(
        monkeypatch, tmp_path, b, athlete_path=str(photo), photo_pos_override="left top"
    )
    assert "--mh-photo-pos:left top;" in html
    assert "--mh-photo-pos:50% 50%;" not in html


def test_duotone_emits_role_computed_filter_defs(monkeypatch, tmp_path):
    from mediahub.graphic_renderer.render import (
        _hex_to_rgb,
        darken,
        resolved_role_vars_for_brief,
    )

    photo = _photo(tmp_path)
    b = _brief()
    b.layout_template = "full_bleed_photo_lower_third"
    b.photo_adjust = "none"
    b.photo_treatment = "duotone"
    html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out="duo")
    assert 'filter id="mh-duotone"' in html
    assert "feComponentTransfer" in html
    assert "filter: url(#mh-duotone)" in html
    # the legacy CSS approximation must not stack on top
    assert "mix-blend-mode: luminosity" not in html
    # table values computed from THIS card's resolved roles
    roles = resolved_role_vars_for_brief(b, _brand())
    shadow_r = _hex_to_rgb(darken(roles["--mh-primary"], 0.30))[0] / 255
    highlight_r = _hex_to_rgb(roles["--mh-accent"])[0] / 255
    assert f'tableValues="{shadow_r:.4f} {highlight_r:.4f}"' in html


def test_halftone_emits_dot_mask_scaled_by_strength(monkeypatch, tmp_path):
    photo = _photo(tmp_path)

    def _one(strength, out):
        b = _brief()
        b.layout_template = "full_bleed_photo_lower_third"
        b.photo_adjust = "none"
        b.photo_treatment = "halftone"
        b.decoration_strength = strength
        html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out=out)
        m = re.search(r"mask-size: (\d+)px", html)
        assert m, "halftone mask missing"
        assert "circle cx=" in html  # style-pack dot geometry
        return int(m.group(1))

    assert _one(0.1, "h1") < _one(0.9, "h2")  # dots scale with decoration strength


def test_untreated_card_carries_no_filter_defs(monkeypatch, tmp_path):
    photo = _photo(tmp_path)
    b = _brief()
    b.layout_template = "full_bleed_photo_lower_third"
    b.photo_adjust = "none"
    html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out="plain")
    assert "mh-duotone" not in html and "mask-size" not in html


# --------------------------------------------------------------------------- #
# M11 — data weight
# --------------------------------------------------------------------------- #


def test_hero_stat_options_extended_from_measured_facts():
    b = _brief(
        _item(
            drop_seconds=1.42,
            prev_pb_time="2:09.83",
            age_group="13-14",
            points="612",
            season_best="2:08.90",
            split_time="29.84",
        )
    )
    opts = b.hero_stat_options
    assert opts["pb_delta"] == "−1.42s on PB"
    assert opts["age_group"] == "age group 13-14"
    assert opts["points"] == "612 pts"
    assert opts["season_best"] == "season best 2:08.90"
    assert opts["split_time"] == "split 29.84"
    assert b.text_layers["prev_pb_time"] == "2:09.83"
    # nothing measured → nothing offered
    bare = _brief(_item())
    assert "age_group" not in bare.hero_stat_options
    assert "prev_pb_time" not in bare.text_layers


def test_secondary_stats_render_as_chips(monkeypatch, tmp_path):
    b = _brief(_item(drop_seconds=1.42, age_group="13-14", points="612"))
    spec = normalise(
        {
            "archetype": "editorial_numbers_grid",
            "hero_stat": "pb_delta",
            "secondary_stats": ["age_group", "points", "placing"],
        },
        archetypes=archetypes.list_archetypes(),
        token_roles=["primary", "accent"],
    )
    apply_design_spec(b, spec)
    assert b.secondary_stats == ["age_group", "points"]  # placing unmeasured → dropped
    html, _ = _render_html(monkeypatch, tmp_path, b, out="chips")
    assert 'class="mh-stat-chips"' in html
    assert "Age group" in html and "13-14" in html
    assert "Points" in html and "612" in html


def test_empty_secondary_stats_collapse(monkeypatch, tmp_path):
    b = _brief(_item(drop_seconds=1.42))
    b.layout_template = "editorial_numbers_grid"
    html, _ = _render_html(monkeypatch, tmp_path, b, out="nochips")
    assert "mh-stat-chips" not in html


def test_pb_bars_are_mathematically_proportional(monkeypatch, tmp_path):
    b = _brief(_item(drop_seconds=1.42, prev_pb_time="2:09.83"))
    b.layout_template = "editorial_numbers_grid"
    html, _ = _render_html(monkeypatch, tmp_path, b, out="bars")
    assert 'class="mh-pb-bars"' in html
    m = re.search(r'width:([\d.]+)%;height:26px;\s*background:var\(--mh-accent\)', html)
    assert m, "new-time bar missing"
    expected = (2 * 60 + 8.41) / (2 * 60 + 9.83) * 100
    assert abs(float(m.group(1)) - expected) < 0.11
    assert "width:100.0%" in html  # the previous-PB bar is the full axis
    assert "bars proportional to real times" in html


def test_pb_bars_refuse_unverifiable_times(monkeypatch, tmp_path):
    # a prev "PB" that is not a parseable race time → no bars, never a guess
    b = _brief(_item(drop_seconds=1.42, prev_pb_time="about 2:10"))
    b.layout_template = "editorial_numbers_grid"
    html, _ = _render_html(monkeypatch, tmp_path, b, out="nobars")
    assert "mh-pb-bars" not in html


def test_parse_time_seconds():
    from mediahub.graphic_renderer.render import _parse_time_seconds

    assert _parse_time_seconds("59.21") == pytest.approx(59.21)
    assert _parse_time_seconds("1:02.34") == pytest.approx(62.34)
    assert _parse_time_seconds("2:09.8") == pytest.approx(129.8)
    for junk in ("", "fast", "1:02", "1:02.345", "59", None):
        assert _parse_time_seconds(junk) is None


# --------------------------------------------------------------------------- #
# M12 — layered-depth archetypes
# --------------------------------------------------------------------------- #


def test_layered_archetypes_registered_with_notes():
    names = archetypes.list_archetypes()
    for name in ("poster_name_behind", "band_break"):
        assert name in names
        assert (archetypes.V2_DIR / f"{name}.notes.md").exists()
        assert archetypes.director_note(name)
        assert archetypes.photo_mode(name) == "cutout"


def test_poster_name_behind_layers_and_depth(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    photo = _photo(tmp_path)
    cut = _person_cutout(tmp_path)
    monkeypatch.setattr(
        R, "_athlete_cutout_with_note", lambda p, profile_id="default": (cut, None)
    )

    def _one(strength, out):
        b = _brief(_item(drop_seconds=1.42))
        b.layout_template = "poster_name_behind"
        b.photo_adjust = "none"
        b.decoration_strength = strength
        html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out=out)
        return html

    html = _one(0.2, "pnb1")
    # plane order: name plane (z1) under athlete (z2) under band (z3)
    assert html.index("pnb__name-plane") < html.index("pnb__athlete") < html.index("pnb__band")
    m = re.search(r"--mh-cutout-depth:[^;]*drop-shadow\(0 (\d+)px", html)
    assert m
    strong = _one(0.9, "pnb2")
    m2 = re.search(r"--mh-cutout-depth:[^;]*drop-shadow\(0 (\d+)px", strong)
    assert int(m2.group(1)) > int(m.group(1))  # depth scales with decoration strength


def test_band_break_places_band_from_alpha_bbox(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    photo = _photo(tmp_path)
    cut = _person_cutout(tmp_path)
    monkeypatch.setattr(
        R, "_athlete_cutout_with_note", lambda p, profile_id="default": (cut, None)
    )
    b = _brief(_item(drop_seconds=1.42))
    b.layout_template = "band_break"
    b.photo_adjust = "none"
    html, _ = _render_html(monkeypatch, tmp_path, b, athlete_path=str(photo), out="bb")
    m = re.search(r"--mh-band-top:([\d.]+)%", html)
    assert m and 50.0 <= float(m.group(1)) <= 74.0
    # the one-copy carry + the two planes
    assert "--mh-athlete-img:url(" in html
    assert 'class="bb__body"' in html and 'class="bb__head"' in html


def test_layered_archetypes_render_clean_with_long_name(monkeypatch, tmp_path):
    import mediahub.graphic_renderer.render as R

    cut = _person_cutout(tmp_path)
    monkeypatch.setattr(
        R, "_athlete_cutout_with_note", lambda p, profile_id="default": (cut, None)
    )
    item = _item()
    item["achievement"]["swimmer_name"] = "Aleksandra Vandersloot-Chamberlain"
    for name in ("poster_name_behind", "band_break"):
        b = _brief(item)
        b.layout_template = name
        b.photo_adjust = "none"
        html, _ = _render_html(
            monkeypatch, tmp_path, b, athlete_path=str(cut), out=f"long_{name}"
        )
        assert "{{" not in html and "}}" not in html
        assert "VANDERSLOOT-CHAMBERLAIN" in html.upper()


# --------------------------------------------------------------------------- #
# M13 — badge anchors
# --------------------------------------------------------------------------- #


def _badge_overlay(family: str) -> str:
    from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
    from mediahub.graphic_renderer.sprint_hooks import icon_overlay as IO

    brief = _brief(_item(drop_seconds=1.42))  # PB → ribbon badge
    ctx = RenderHookCtx(
        brief=brief, width=1080, height=1350, family=family, format_name="feed_portrait", is_v2=True
    )
    return IO.apply("<html><body></body></html>", ctx)


def test_badges_anchor_away_from_colliding_furniture():
    # full-bleed: brand block owns top-right → badges left, below the kicker
    fb = _badge_overlay("full_bleed_photo_lower_third")
    assert re.search(r'style="position:absolute;top:140px;left:54px', fb)
    # magazine cover: below the (possibly two-line) masthead, over the photo
    # well's clear top-left — the right rail owns the area under the dateline
    mc = _badge_overlay("magazine_cover")
    assert re.search(r'style="position:absolute;top:224px;left:54px', mc)
    # duo: data-bay logo stack owns top-right → left, under the kicker
    duo = _badge_overlay("duo_athlete_split")
    assert re.search(r"top:138px;left:54px", duo)
    # passepartout: club lockup owns top-right → left, under the kicker
    pp = _badge_overlay("photo_passepartout")
    assert re.search(r"top:140px;left:54px", pp)


def test_unmapped_family_keeps_the_historic_top_right():
    out = _badge_overlay("big_number_dominant")
    assert re.search(r'style="position:absolute;top:54px;right:54px', out)


def test_no_badge_cards_stay_byte_identical():
    from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
    from mediahub.graphic_renderer.sprint_hooks import icon_overlay as IO

    brief = _brief(_item())  # nothing badge-worthy… except PB label
    brief.confidence_label = "STRONG SWIM"
    brief.text_layers["achievement_label"] = "STRONG SWIM"
    brief.inspiration_pattern_id = "x"
    brief.primary_hook = "STRONG SWIM"
    ctx = RenderHookCtx(
        brief=brief,
        width=1080,
        height=1350,
        family="full_bleed_photo_lower_third",
        format_name="feed_portrait",
        is_v2=True,
    )
    html = "<html><body></body></html>"
    assert IO.apply(html, ctx) == html


# --------------------------------------------------------------------------- #
# M14 — matte gate + honest fallback
# --------------------------------------------------------------------------- #


def _save_rgba(tmp_path, name, painter, size=(200, 300)):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    painter(im)
    p = tmp_path / name
    im.save(p)
    return p


def test_matte_gate_accepts_a_clean_person_matte(tmp_path):
    from mediahub.graphic_renderer.matte import assess_matte

    good = _person_cutout(tmp_path, "good.png")
    v = assess_matte(good)
    assert v.ok, v.reason


def test_matte_gate_rejects_bad_mattes(tmp_path):
    from mediahub.graphic_renderer.matte import assess_matte
    from PIL import ImageDraw

    # near-empty matte (< 8% coverage)
    def _speck(im):
        ImageDraw.Draw(im).ellipse((10, 10, 22, 22), fill=(255, 0, 0, 255))

    v = assess_matte(_save_rgba(tmp_path, "empty.png", _speck))
    assert not v.ok and "covers only" in v.reason

    # background kept (> 85% coverage)
    def _full(im):
        ImageDraw.Draw(im).rectangle((2, 2, 197, 297), fill=(0, 0, 255, 255))

    v = assess_matte(_save_rgba(tmp_path, "full.png", _full))
    assert not v.ok and "background not removed" in v.reason

    # shredded matte: many disconnected islands
    def _shred(im):
        d = ImageDraw.Draw(im)
        for x in range(10, 190, 34):
            for y in range(10, 290, 34):
                d.ellipse((x, y, x + 14, y + 14), fill=(200, 40, 40, 255))

    v = assess_matte(_save_rgba(tmp_path, "shred.png", _shred))
    assert not v.ok and "shredded" in v.reason

    # fully-opaque output — no matte was produced at all
    opaque = tmp_path / "opaque.png"
    Image.new("RGB", (100, 100), (10, 10, 10)).save(opaque)
    v = assess_matte(opaque)
    assert not v.ok and "no usable alpha" in v.reason


class _FakeRemover:
    name = "fake"
    model = "u2net_human_seg"

    def __init__(self, produce):
        self._produce = produce

    def remove(self, src, dst):
        self._produce(dst)
        return str(dst)


def test_cutout_gate_falls_back_honestly_and_caches_the_verdict(tmp_path, monkeypatch):
    import mediahub.graphic_renderer.render as R
    import mediahub.media_ai.providers as providers

    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    src = _photo(tmp_path, "swimmer.jpg")

    calls = {"n": 0}

    def _produce_shred(dst):
        calls["n"] += 1
        # a deterministic speck-field: high coverage, thousands of disconnected
        # islands, and (deliberately) enough entropy to exceed the size floor.
        im = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        px = im.load()
        for y in range(300):
            for x in range(200):
                if (x * 7 + y * 13 + (x * y) % 11) % 9 == 0:
                    px[x, y] = ((x * 37) % 255, (y * 53) % 255, 40, 255)
        im.save(dst)

    monkeypatch.setattr(providers, "get_bg_remover", lambda: _FakeRemover(_produce_shred))
    path, note = R._athlete_cutout_with_note(src, profile_id="p1")
    assert str(path) == str(src)  # the ORIGINAL ships
    assert note and "shredded" in note and "original photo" in note
    # the verdict is persisted — a bad matte is measured once, not re-matted
    path2, note2 = R._athlete_cutout_with_note(src, profile_id="p1")
    assert calls["n"] == 1
    assert str(path2) == str(src) and note2 and "rejected" in note2


def test_cutout_cache_filename_carries_the_model(tmp_path, monkeypatch):
    import mediahub.graphic_renderer.render as R
    import mediahub.media_ai.providers as providers

    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    src = _photo(tmp_path, "swimmer2.jpg")

    def _produce_good(dst):
        from PIL import ImageDraw

        im = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((70, 20, 130, 80), fill=(200, 150, 120, 255))
        d.rectangle((55, 80, 145, 300), fill=(180, 40, 40, 255))
        im.save(dst)

    monkeypatch.setattr(providers, "get_bg_remover", lambda: _FakeRemover(_produce_good))
    path, note = R._athlete_cutout_with_note(src, profile_id="p1")
    assert note is None
    assert "__cutout__u2net_human_seg.png" in str(path)
    # the mask-only lookup finds it without re-running the remover
    assert R._existing_cutout_for(src, profile_id="p1") == path


def test_default_rembg_model_is_human_seg(monkeypatch):
    from mediahub.media_ai.providers.rembg_local import RembgLocalRemover, default_model

    monkeypatch.delenv("MEDIAHUB_CUTOUT_MODEL", raising=False)
    assert default_model() == "u2net_human_seg"
    assert RembgLocalRemover().model == "u2net_human_seg"
    monkeypatch.setenv("MEDIAHUB_CUTOUT_MODEL", "u2net")
    assert RembgLocalRemover().model == "u2net"


# --------------------------------------------------------------------------- #
# STILLS-4a / PHOTOS-8 — format-aware, mask-steered still focus
# --------------------------------------------------------------------------- #


def test_still_focus_uses_the_render_ratio_and_pins_4_5(tmp_path):
    from mediahub.graphic_renderer.render import _v2_photo_position
    from mediahub.graphic_renderer.saliency import focus_position

    photo = _photo(tmp_path)
    # 1080×1350 must be byte-identical to the historic hardcoded "4:5"
    assert _v2_photo_position(photo, 1080, 1350) == focus_position(photo, "4:5")
    # other formats resolve their own ratio (story slides on its own axis)
    assert _v2_photo_position(photo, 1080, 1920) == focus_position(photo, "9:16")
    assert _v2_photo_position(photo, 1080, 1080) == focus_position(photo, "1:1")


def test_still_focus_steers_by_cutout_mask_when_available(tmp_path):
    from mediahub.graphic_renderer.render import _v2_photo_position
    from mediahub.graphic_renderer.saliency import focus_position_with_mask

    photo = _photo(tmp_path)
    cut = _person_cutout(tmp_path)
    assert _v2_photo_position(photo, 1080, 1350, cut) == focus_position_with_mask(
        photo, cut, "1080:1350"
    )
