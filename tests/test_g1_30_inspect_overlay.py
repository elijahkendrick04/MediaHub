"""G1.30 — render debug/inspection overlay + design-explainability sidecar.

Covers the two new files:
  * ``graphic_renderer/inspect.py`` — explainability dict, HTML read-back
    parsers (fitted sizes, saliency focus), the saliency crop-box delegate, the
    visual overlay, and the on-disk sidecar.
  * ``graphic_renderer/sprint_hooks/inspect_overlay.py`` — the auto-discovered
    render hook and, critically, its **byte-identical-when-off** guarantee.
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from mediahub.creative_brief.generator import CreativeBrief
from mediahub.graphic_renderer import inspect as ins
from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    _discover,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import inspect_overlay as hook

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
SAMPLE_HTML = (
    "<html><head><style>:root{--mh-photo-pos:50% 28%}</style></head><body>"
    '<div class="hero" style="font-size:180px;font-weight:900">SMITH</div>'
    '<div class="event" style="font-size:64px">100m FLY</div>'
    '<div class="result" style="font-size:64px">1:02.34</div>'
    '<div class="meta" style="font-size:24px">City Champs</div>'
    "</body></html>"
)


def _brief(**over) -> CreativeBrief:
    base = dict(
        id="cb_g130",
        content_item_id="swim-g130-1",
        profile_id="g130-club",
        achievement_summary="Aderyn Vaughan — 100m Butterfly — 1:02.34",
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
        why_this_design="Hero crop on the swimmer; amber accent on navy reads the PB first.",
        text_layers={"result_value": "1:02.34"},
        palette={"primary": "#0E2A47", "secondary": "#C9A227", "accent": "#C9A227"},
        format_priority=["story"],
        style_pack="editorial_bold",
        background_style="water",
        accent_style="brackets",
        typography_pair="anton-inter",
        composition="right",
        photo_treatment="cutout",
        decoration_strength=0.5,
        mood="triumphant",
        motion_intent="kinetic_type",
        colour_role_assignment={"ground": "secondary"},
        hero_stat_options={"pb_delta": "−0.42s on PB", "placing": "2nd"},
        variation_signature="sig-g130",
    )
    base.update(over)
    return CreativeBrief(**base)


def _ctx(brief=None, **over) -> RenderHookCtx:
    params = dict(
        brief=brief if brief is not None else _brief(),
        width=1080,
        height=1920,
        family="individual_hero",
        format_name="story",
        is_v2=True,
    )
    params.update(over)
    return RenderHookCtx(**params)


@pytest.fixture(autouse=True)
def _no_inspect_env(monkeypatch):
    """Every test starts with the operator toggle OFF unless it sets it."""
    monkeypatch.delenv(ins.INSPECT_ENV, raising=False)


# --------------------------------------------------------------------------- #
# Registry discovery + opt-in gate
# --------------------------------------------------------------------------- #
def test_hook_is_auto_discovered_and_runs_late():
    names = [n for _, n, _ in _discover()]
    assert "inspect_overlay" in names
    # Runs after decorative hooks (gradient mesh ships at ORDER 20) so it sees
    # the finished card and sits on top.
    assert hook.ORDER == 95


def test_disabled_hook_is_byte_identical():
    # Assert on our hook directly: the shared registry now carries sibling
    # sprint hooks (icon overlay, depth-of-field, …) that legitimately fire on
    # some briefs, so a whole-registry diff would not isolate our guarantee.
    assert hook.apply(SAMPLE_HTML, _ctx()) == SAMPLE_HTML


def test_env_toggle_enables_overlay(monkeypatch):
    monkeypatch.setenv(ins.INSPECT_ENV, "1")
    out = apply_render_hooks(SAMPLE_HTML, _ctx())
    assert 'class="mh-inspect-overlay"' in out
    assert 'id="mh-inspect-data"' in out
    assert out.count("</body>") == 1  # injected before the single close, not duplicated


def test_brief_attribute_enables_overlay_without_env():
    brief = _brief()
    brief.inspect_overlay = True  # per-card opt-in (dataclass has no slots)
    out = apply_render_hooks(SAMPLE_HTML, _ctx(brief=brief))
    assert "mh-inspect-overlay" in out


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("nope", False),
    ],
)
def test_env_truthiness_matrix(monkeypatch, value, expected):
    monkeypatch.setenv(ins.INSPECT_ENV, value)
    assert ins.inspect_enabled(_ctx()) is expected


def test_inspect_enabled_tolerates_missing_brief():
    assert ins.inspect_enabled(_ctx(brief=None)) is False


# --------------------------------------------------------------------------- #
# HTML read-back parsers
# --------------------------------------------------------------------------- #
def test_parse_fitted_sizes_orders_desc_dedupes_and_counts():
    sizes = ins.parse_fitted_sizes(SAMPLE_HTML)
    px = [f.px for f in sizes]
    assert px == sorted(px, reverse=True)  # largest first
    assert px == [180.0, 64.0, 24.0]  # 64 de-duplicated
    by_px = {f.px: f for f in sizes}
    assert by_px[64.0].count == 2  # two elements at 64px
    assert by_px[180.0].sample == "SMITH"  # carries a representative sample


def test_parse_fitted_sizes_empty_html():
    assert ins.parse_fitted_sizes("") == []


def test_parse_focus_position_percentages():
    f = ins.parse_focus_position(SAMPLE_HTML)
    assert f is not None
    assert (f.x_pct, f.y_pct) == (50.0, 28.0)
    assert f.raw == "50% 28%"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("center 28%", (50.0, 28.0)),
        ("left top", (0.0, 0.0)),
        ("right bottom", (100.0, 100.0)),
        ("center", (50.0, 50.0)),
        ("bottom", (50.0, 100.0)),
        ("left", (0.0, 50.0)),
        ("75% 10%", (75.0, 10.0)),
    ],
)
def test_parse_focus_position_keywords_and_shorthand(value, expected):
    html = f"<body><div style='--mh-photo-pos:{value}'></div></body>"
    f = ins.parse_focus_position(html)
    assert f is not None
    assert (f.x_pct, f.y_pct) == expected


def test_parse_focus_position_object_position_fallback():
    html = "<body><img style='object-position: 30% 70%'></body>"
    f = ins.parse_focus_position(html)
    assert f is not None
    assert (f.x_pct, f.y_pct) == (30.0, 70.0)


def test_parse_focus_position_absent_returns_none():
    assert ins.parse_focus_position("<body><p>no photo here</p></body>") is None


# --------------------------------------------------------------------------- #
# crop_box_for — saliency delegate
# --------------------------------------------------------------------------- #
def _solid_image(tmp_path, size=(800, 600)):
    p = tmp_path / "athlete.png"
    img = Image.new("RGB", size, (20, 40, 80))
    # a bright patch so the gradient-energy centroid is well-defined
    for x in range(500, 620):
        for y in range(120, 240):
            img.putpixel((x, y), (240, 200, 40))
    img.save(p)
    return p


def test_crop_box_for_delegates_to_saliency_within_bounds(tmp_path):
    img = _solid_image(tmp_path)
    crop = ins.crop_box_for(img, width=1080, height=1920)  # 9:16 portrait crop
    assert crop is not None
    x, y, w, h = crop
    assert 0 <= x and 0 <= y and w > 0 and h > 0
    assert x + w <= 800 and y + h <= 600  # within the source image


def test_crop_box_for_missing_image_is_none():
    assert ins.crop_box_for(None, width=1080, height=1920) is None
    assert ins.crop_box_for("/no/such/file.png") is None


# --------------------------------------------------------------------------- #
# Explainability sidecar dict
# --------------------------------------------------------------------------- #
def test_design_explainability_shape_and_values():
    data = ins.design_explainability(SAMPLE_HTML, _ctx())
    assert data["schema"] == ins.SCHEMA

    card = data["card"]
    assert card["brief_id"] == "cb_g130"
    assert card["format"] == "story"
    assert (card["width"], card["height"]) == (1080, 1920)
    assert card["archetype"] == "individual_hero"
    assert card["is_v2"] is True

    design = data["design"]
    assert design["style_pack"] == "editorial_bold"
    assert design["typography_pair"] == "anton-inter"
    assert design["background_style"] == "water"
    assert design["motion_intent"] == "kinetic_type"
    assert design["palette"]["primary"] == "#0E2A47"
    assert design["colour_role_assignment"] == {"ground": "secondary"}
    assert design["variation_signature"] == "sig-g130"

    assert data["why_this_design"].startswith("Hero crop")

    layout = data["layout"]
    assert layout["focus_position"] == {"x_pct": 50.0, "y_pct": 28.0, "raw": "50% 28%"}
    assert layout["fitted_size_range"] == {"min": 24.0, "max": 180.0, "count": 3}
    assert layout["crop_box"] is None  # no image supplied


def test_design_explainability_includes_crop_box_with_image(tmp_path):
    img = _solid_image(tmp_path)
    data = ins.design_explainability(SAMPLE_HTML, _ctx(), image_path=img)
    crop = data["layout"]["crop_box"]
    assert crop is not None
    assert set(crop) == {"x", "y", "w", "h"}
    assert crop["w"] > 0 and crop["h"] > 0


def test_explainability_is_json_serialisable():
    data = ins.design_explainability(SAMPLE_HTML, _ctx())
    # round-trips cleanly through json (no exotic types leak in)
    assert json.loads(json.dumps(data)) == data


# --------------------------------------------------------------------------- #
# Visual overlay
# --------------------------------------------------------------------------- #
def test_overlay_embeds_script_safe_json_matching_data():
    data = ins.design_explainability(SAMPLE_HTML, _ctx())
    overlay = ins.build_overlay_html(data, _ctx())
    start = overlay.index('id="mh-inspect-data">') + len('id="mh-inspect-data">')
    end = overlay.index("</script>", start)
    payload = overlay[start:end]
    # nothing in the payload can terminate the <script> or be read as markup
    assert "<" not in payload and ">" not in payload and "&" not in payload
    # …yet it is still valid JSON equal to the source data (\\u003c etc. decode)
    assert json.loads(payload) == data
    assert overlay.count("</script>") == 1


def test_overlay_escapes_brief_text():
    brief = _brief(why_this_design="<script>alert(1)</script> & <b>bold</b>")
    data = ins.design_explainability(SAMPLE_HTML, _ctx(brief=brief))
    overlay = ins.build_overlay_html(data, _ctx(brief=brief))
    # the panel region (before the JSON sidecar) must not carry raw markup
    panel = overlay.split('<script type="application/json"', 1)[0]
    assert "<script>alert(1)</script>" not in panel
    assert "&lt;script&gt;" in panel  # HTML-escaped instead


def test_overlay_is_non_interactive_and_on_top():
    data = ins.design_explainability(SAMPLE_HTML, _ctx())
    overlay = ins.build_overlay_html(data, _ctx())
    assert "pointer-events:none" in overlay
    # above the demo watermark (z-index 9999) and any sprint effect
    assert f"z-index:{ins._Z}" in overlay
    assert ins._Z > 9999


def test_overlay_draws_focus_crosshair_only_when_photo_present():
    with_focus = ins.build_overlay_html(ins.design_explainability(SAMPLE_HTML, _ctx()), _ctx())
    assert ins._MARK in with_focus  # amber crosshair stroke

    no_photo_html = "<body><div style='font-size:40px'>x</div></body>"
    without = ins.build_overlay_html(ins.design_explainability(no_photo_html, _ctx()), _ctx())
    assert ins._MARK not in without  # no focus → no crosshair


def test_overlay_palette_swatch_is_sanitised():
    brief = _brief(palette={"primary": "red;}</style><script>x", "secondary": "#C9A227"})
    data = ins.design_explainability(SAMPLE_HTML, _ctx(brief=brief))
    overlay = ins.build_overlay_html(data, _ctx(brief=brief))
    panel = overlay.split('<script type="application/json"', 1)[0]
    assert "</style><script>" not in panel
    assert "#888888" in panel  # clamped to the safe fallback colour
    assert "background:#C9A227" in panel  # a valid hex passes through


# --------------------------------------------------------------------------- #
# render_inspect_overlay — injection behaviour
# --------------------------------------------------------------------------- #
def test_render_inspect_overlay_is_idempotent():
    once = ins.render_inspect_overlay(SAMPLE_HTML, _ctx())
    twice = ins.render_inspect_overlay(once, _ctx())
    assert twice == once  # already inspected → unchanged
    assert once.count('id="mh-inspect-data"') == 1


def test_render_inspect_overlay_is_deterministic():
    a = ins.render_inspect_overlay(SAMPLE_HTML, _ctx())
    b = ins.render_inspect_overlay(SAMPLE_HTML, _ctx())
    assert a == b


def test_render_inspect_overlay_without_body_appends():
    fragment = "<div style='font-size:50px'>hi</div>"
    out = ins.render_inspect_overlay(fragment, _ctx())
    assert out.startswith(fragment)
    assert "mh-inspect-overlay" in out


def test_render_inspect_overlay_tolerates_non_string():
    assert ins.render_inspect_overlay(None, _ctx()) is None  # type: ignore[arg-type]
    assert ins.render_inspect_overlay("", _ctx()) == ""


# --------------------------------------------------------------------------- #
# On-disk sidecar
# --------------------------------------------------------------------------- #
def test_write_sidecar_roundtrips(tmp_path):
    data = ins.design_explainability(SAMPLE_HTML, _ctx())
    out = tmp_path / "nested" / "card.json"
    written = ins.write_sidecar(out, data)
    assert written == out and out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == data
