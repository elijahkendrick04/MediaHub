"""Tests for roadmap **G1.21** — depth-of-field background-blur photo treatment.

The treatment ships as an isolated sprint render-hook
(``graphic_renderer/sprint_hooks/depth_of_field.py``): when a brief opts in, it
softens the photographic background layers and keeps the athlete cutout sharp.

Three layers of coverage:
  * Unit  — the hook's ``apply`` as a pure HTML string transform (no browser).
  * Seam  — the auto-discovery registry runs it end-to-end and stays a no-op for
            ordinary briefs (existing renders byte-identical).
  * Render — a real ``render_brief`` Playwright render proves the CSS lands in
             the finished card and changes the pixels (skipped without Chromium).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import depth_of_field as dof

MARKER = 'id="mh-dof"'

# A representative finished card: a cutout subject over an AI background and a
# user background photo, with the shared CSS *rules* inlined (so the test also
# proves class-name-in-CSS does not false-trigger the photo-presence gate).
CARD_HTML = (
    "<html><head><style>"
    ".athlete-cutout{display:block}.bg-ai{opacity:.55}.bg-photo{inset:0}"
    "</style></head><body>"
    "<div class=\"canvas\">"
    "<div class=\"bg-ai\" style=\"--ai-bg: url('data:image/png;base64,AAAA')\"></div>"
    "<div class=\"bg-photo\" style=\"background-image:url('data:image/png;base64,BBBB')\"></div>"
    "<img class=\"athlete-cutout\" src=\"data:image/png;base64,CCCC\" alt=\"x\" />"
    "</div></body></html>"
)

# A card with the CSS rules present but NO real photo element/URI.
TEXT_ONLY_HTML = (
    "<html><head><style>"
    ".athlete-cutout{}.bg-ai{}.bg-photo{}"
    "</style></head><body><div class=\"canvas\">"
    "<div class=\"bg-ai\" style=\"--ai-bg: url('')\"></div>"
    "<h1>WEEKEND RECAP</h1>"
    "</div></body></html>"
)


class _Brief:
    """A minimal CreativeBrief-shaped object."""

    def __init__(self, photo_treatment="cutout", background_style="water", decoration_strength=0.5):
        self.photo_treatment = photo_treatment
        self.background_style = background_style
        self.decoration_strength = decoration_strength


def _ctx(brief, width=1080, height=1350):
    return RenderHookCtx(
        brief=brief,
        width=width,
        height=height,
        family="individual_hero",
        format_name="feed_portrait",
        is_v2=False,
    )


def _blur_px(html: str) -> int:
    m = re.search(r"blur\((\d+)px\)", html)
    assert m, "no blur() radius found in injected CSS"
    return int(m.group(1))


# --------------------------------------------------------------------------- #
# Unit — opt-in / opt-out                                                      #
# --------------------------------------------------------------------------- #


def test_opt_out_leaves_html_byte_identical():
    """A brief that does not request DOF must return the HTML unchanged."""
    out = dof.apply(CARD_HTML, _ctx(_Brief()))
    assert out == CARD_HTML


def test_opt_in_via_photo_treatment_injects_block():
    out = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="depth_of_field")))
    assert MARKER in out
    assert "blur(" in out
    # Background layers softened, subject kept crisp with separation.
    assert ".bg-photo,.bg-ai{" in out
    assert ".athlete-cutout{" in out
    assert "drop-shadow(" in out


def test_opt_in_via_background_style_alias():
    """The README seam pattern keys off background_style — honour that too."""
    out = dof.apply(CARD_HTML, _ctx(_Brief(background_style="dof")))
    assert MARKER in out


@pytest.mark.parametrize(
    "token",
    [
        "depth_of_field",
        "dof",
        "background_blur",
        "blur_background",
        "blurred_background",
        "bokeh",
        "Depth Of Field",  # spaces normalised
        "depth-of-field",  # hyphens normalised
        "DOF",  # case normalised
    ],
)
def test_all_dof_tokens_trigger(token):
    assert MARKER in dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment=token)))


@pytest.mark.parametrize("token", ["cutout", "vignette", "duotone", "frame", "halftone", "no-photo", ""])
def test_existing_treatments_never_trigger(token):
    """The six real photo_treatment values must stay byte-identical."""
    assert dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment=token))) == CARD_HTML


# --------------------------------------------------------------------------- #
# Unit — safety / determinism                                                  #
# --------------------------------------------------------------------------- #


def test_idempotent_second_pass_is_noop():
    once = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="depth_of_field")))
    twice = dof.apply(once, _ctx(_Brief(photo_treatment="depth_of_field")))
    assert once == twice
    assert twice.count(MARKER) == 1


def test_deterministic_same_inputs_same_output():
    a = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof")))
    b = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof")))
    assert a == b


def test_no_photo_card_is_noop_even_when_requested():
    """Nothing photographic to act on → honest no-op, no dead CSS, no darkening."""
    assert dof.apply(TEXT_ONLY_HTML, _ctx(_Brief(photo_treatment="depth_of_field"))) == TEXT_ONLY_HTML


def test_real_ai_bg_alone_triggers_but_empty_does_not():
    only_ai = (
        "<html><body><div class=\"canvas\">"
        "<div class=\"bg-ai\" style=\"--ai-bg: url('data:image/png;base64,ZZ')\"></div>"
        "</div></body></html>"
    )
    empty_ai = only_ai.replace("data:image/png;base64,ZZ", "")
    assert MARKER in dof.apply(only_ai, _ctx(_Brief(photo_treatment="dof")))
    assert dof.apply(empty_ai, _ctx(_Brief(photo_treatment="dof"))) == empty_ai


def test_no_external_urls_or_cdn_introduced():
    out = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="depth_of_field")))
    injected = out.replace(CARD_HTML.replace("</body>", ""), "")
    assert "http://" not in injected
    assert "https://" not in injected
    assert "googleapis" not in injected and "gstatic" not in injected


def test_non_string_html_returned_unchanged():
    assert dof.apply(None, _ctx(_Brief(photo_treatment="dof"))) is None  # type: ignore[arg-type]


def test_none_brief_is_noop():
    assert dof.apply(CARD_HTML, _ctx(None)) == CARD_HTML


def test_appends_when_no_body_close_tag():
    frag = (
        "<div class=\"canvas\"><img class=\"athlete-cutout\" src=\"data:,x\" /></div>"
    )
    out = dof.apply(frag, _ctx(_Brief(photo_treatment="dof")))
    assert out.startswith(frag) and MARKER in out


# --------------------------------------------------------------------------- #
# Unit — deterministic blur sizing                                            #
# --------------------------------------------------------------------------- #


def test_blur_scales_with_canvas_short_edge():
    small = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof"), width=540, height=675))
    large = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof"), width=1080, height=1350))
    assert _blur_px(small) < _blur_px(large)


def test_blur_scales_with_decoration_strength():
    low = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof", decoration_strength=0.0)))
    high = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof", decoration_strength=1.0)))
    assert _blur_px(low) < _blur_px(high)


@pytest.mark.parametrize("w,h", [(1080, 1080), (1080, 1350), (1080, 1920), (1920, 1080), (4000, 4000)])
def test_blur_stays_within_tasteful_bounds(w, h):
    out = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof"), width=w, height=h))
    assert 12 <= _blur_px(out) <= 30


def test_format_invariant_perceptual_blur():
    """Same short edge (1080) ⇒ same blur across square / portrait / story."""
    sizes = [(1080, 1080), (1080, 1350), (1080, 1920)]
    radii = {_blur_px(dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof"), width=w, height=h))) for w, h in sizes}
    assert len(radii) == 1


# --------------------------------------------------------------------------- #
# Unit — targeting                                                            #
# --------------------------------------------------------------------------- #


def test_full_bleed_hero_photo_is_not_blurred():
    """`.hero-photo` is the subject-bearing full-bleed image — never softened."""
    out = dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="depth_of_field")))
    style = out[out.find(MARKER):]
    assert "hero-photo" not in style


def test_dict_brief_supported():
    out = dof.apply(CARD_HTML, _ctx({"photo_treatment": "depth_of_field", "decoration_strength": 1.0}))
    assert MARKER in out
    # decoration_strength read from the dict (not the 0.5 default) → max-band blur.
    dict_blur = _blur_px(out)
    obj_blur = _blur_px(dof.apply(CARD_HTML, _ctx(_Brief(photo_treatment="dof", decoration_strength=1.0))))
    assert dict_blur == obj_blur


# --------------------------------------------------------------------------- #
# Seam — auto-discovery registry                                              #
# --------------------------------------------------------------------------- #


def test_registry_discovers_depth_of_field():
    from mediahub.graphic_renderer.sprint_hooks import _discover

    discovered = {name: order for order, name, _fn in _discover()}
    assert "depth_of_field" in discovered
    assert discovered["depth_of_field"] == dof.ORDER == 40


def test_module_contract_apply_is_callable():
    assert callable(dof.apply)
    assert isinstance(dof.ORDER, int)


def test_registry_runs_hook_when_opted_in():
    out = apply_render_hooks(CARD_HTML, _ctx(_Brief(photo_treatment="depth_of_field")))
    assert MARKER in out


def test_registry_is_noop_for_ordinary_brief():
    """The seam must stay byte-identical for every non-DOF render."""
    assert apply_render_hooks(CARD_HTML, _ctx(_Brief())) == CARD_HTML


# --------------------------------------------------------------------------- #
# Render — real Playwright pipeline (skipped without Chromium)                #
# --------------------------------------------------------------------------- #


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        with sync_playwright() as p:
            try:
                b = p.chromium.launch(args=["--no-sandbox"])
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


render_only = pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")


def _scene_png(path: Path) -> Path:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1080, 1350), (20, 40, 80))
    d = ImageDraw.Draw(img)
    for i in range(0, 1080, 40):
        d.line([(i, 0), (i, 1350)], fill=(80, 140, 220), width=2)
    for cx, cy, r, c in [(300, 400, 140, (255, 180, 40)), (800, 900, 180, (240, 90, 120))]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    img.save(path)
    return path


def _make_brief(layout: str):
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    brand = BrandKit(
        profile_id="test",
        display_name="Riverside Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="RSC",
    )
    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="meet_recap",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="RECAP",
        explain="ok",
    )
    item = {"id": "ci-1", "post_angle": "meet_recap", "achievement": {"meet_name": "Manchester Open"}}
    brief = gen_brief(item, ev, brand, profile_id="test", meet_name="Manchester Open")
    brief.layout_template = layout
    return brief, brand


@render_only
def test_render_brief_injects_dof_css_and_produces_png(tmp_path: Path):
    from mediahub.graphic_renderer.render import render_brief

    brief, brand = _make_brief("text_led_recap")
    brief.photo_treatment = "depth_of_field"
    bgp = _scene_png(tmp_path / "scene.png")
    res = render_brief(
        brief,
        output_dir=tmp_path / "dof",
        size=(1080, 1350),
        format_name="feed_portrait",
        brand_kit=brand,
        bg_photo_path=str(bgp),
    )
    assert MARKER in res.html
    assert "blur(" in res.html
    out = Path(res.visual.file_path)
    assert out.exists() and out.stat().st_size > 30_000
    with open(out, "rb") as fh:
        assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


@render_only
def test_render_brief_default_is_byte_identical_to_pre_hook(tmp_path: Path):
    """An ordinary brief must render with NO DOF marker — seam stays invisible."""
    from mediahub.graphic_renderer.render import render_brief

    brief, brand = _make_brief("text_led_recap")
    bgp = _scene_png(tmp_path / "scene.png")
    res = render_brief(
        brief,
        output_dir=tmp_path / "plain",
        size=(1080, 1350),
        format_name="feed_portrait",
        brand_kit=brand,
        bg_photo_path=str(bgp),
    )
    assert "mh-dof" not in res.html


@render_only
def test_dof_changes_pixels_vs_plain(tmp_path: Path):
    """The treatment must actually alter the render, not just the markup."""
    from mediahub.graphic_renderer.render import render_brief

    bgp = _scene_png(tmp_path / "scene.png")

    brief_p, brand = _make_brief("text_led_recap")
    plain = render_brief(
        brief_p, output_dir=tmp_path / "p", size=(1080, 1350),
        format_name="feed_portrait", brand_kit=brand, bg_photo_path=str(bgp),
    )
    brief_d, _ = _make_brief("text_led_recap")
    brief_d.photo_treatment = "depth_of_field"
    blurred = render_brief(
        brief_d, output_dir=tmp_path / "d", size=(1080, 1350),
        format_name="feed_portrait", brand_kit=brand, bg_photo_path=str(bgp),
    )
    assert Path(plain.visual.file_path).read_bytes() != Path(blurred.visual.file_path).read_bytes()
