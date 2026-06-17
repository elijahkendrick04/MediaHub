"""Tests for the gradient-mesh background engine (roadmap G1.8).

Three layers, mirroring the build:

* **Engine** (``graphic_renderer.gradient_mesh``) — deterministic, brand-keyed,
  APCA-safe SVG generation. Pure; no Playwright.
* **Render hook** (``sprint_hooks.gradient_mesh_bg``) — the opt-in HTML transform
  and the byte-identical no-op guarantee. Pure string work; no Playwright.
* **Integration** — real Playwright renders proving the mesh actually paints and
  stays deterministic. Skipped when Chromium is unavailable.

The recurring assertion across all three is the G1.8 contract: *deterministic*
(same inputs → byte-identical output), *brand-keyed* (every colour derives from
the resolved ``--mh-*`` roles), and *APCA-gated* (the headline ink stays legible
over the whole field — the mesh can never be a legibility regression).
"""
from __future__ import annotations

import base64
import re
import xml.dom.minidom as minidom
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediahub.graphic_renderer.gradient_mesh import (
    MESH_MODES,
    MeshRoles,
    build_mesh_svg,
    mesh_data_uri,
    mesh_mode_for_seed,
)
from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import gradient_mesh_bg as hook
from mediahub.quality.compliance import LC_LARGE, is_legible

# A navy ground with a *light* gold accent and white ink — the classic legibility
# hazard (white-on-gold fails APCA, so the engine's clamp must pull the accent
# back). Plus its inverse, a light-yellow ground with dark ink.
_DARK = {
    "--mh-primary": "#0A2540",
    "--mh-surface": "#05121F",
    "--mh-secondary": "#101820",
    "--mh-accent": "#F4B400",
    "--mh-on-primary": "#FFFFFF",
}
_LIGHT = {
    "--mh-primary": "#FFCC00",
    "--mh-surface": "#7F6600",
    "--mh-secondary": "#FFE066",
    "--mh-accent": "#101820",
    "--mh-on-primary": "#0B0B0C",
}

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def _hexes(svg: str) -> set[str]:
    return {h.upper() for h in _HEX.findall(svg)}


# ===========================================================================
# Engine — structure & validity
# ===========================================================================

@pytest.mark.parametrize("mode", MESH_MODES)
def test_build_mesh_svg_is_wellformed_xml(mode: str):
    svg = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="card-1")
    # Parses as XML (a malformed mesh would silently break the CSS background).
    minidom.parseString(svg)
    assert svg.startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert f'data-mh-mesh="{mode}"' in svg
    assert 'width="1080"' in svg and 'height="1350"' in svg
    assert 'viewBox="0 0 1080 1350"' in svg


@pytest.mark.parametrize("mode", MESH_MODES)
def test_base_rect_is_brand_primary(mode: str):
    # The SVG must be a complete ground on its own: its base rect is the brand
    # primary, so swapping it in for a flat ground is seamless.
    svg = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="x")
    assert '<rect width="1080" height="1350" fill="#0A2540"' in svg


def test_modes_are_structurally_distinct():
    seed = "same-seed"
    lin = build_mesh_svg(_DARK, 1080, 1350, mode="linear", seed=seed)
    rad = build_mesh_svg(_DARK, 1080, 1350, mode="radial", seed=seed)
    con = build_mesh_svg(_DARK, 1080, 1350, mode="conic", seed=seed)
    assert "<linearGradient" in lin
    assert rad.count("<radialGradient") >= 3  # several blobs
    assert "<linearGradient" not in rad
    # Conic is SVG-faceted into many wedge paths (no native conic in SVG 1.1).
    assert con.count("<path") >= 24
    assert lin != rad != con


@pytest.mark.parametrize("mode", MESH_MODES)
def test_multi_stop_gradients(mode: str):
    # "multi-stop" is in the roadmap line — each gradient family carries ≥3 stops
    # (linear/radial) or sweeps through ≥4 colours (conic).
    svg = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="s")
    if mode in ("linear", "radial"):
        assert svg.count("<stop") >= 3
    else:  # conic interpolates a colour ramp across its wedges
        assert len(_hexes(svg)) >= 4


# ===========================================================================
# Engine — determinism (same inputs → byte-identical; seed varies output)
# ===========================================================================

@pytest.mark.parametrize("mode", MESH_MODES)
def test_deterministic_same_inputs(mode: str):
    a = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="card-9", intensity=0.6)
    b = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="card-9", intensity=0.6)
    assert a == b


@pytest.mark.parametrize("mode", MESH_MODES)
def test_seed_changes_geometry(mode: str):
    a = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="card-A")
    b = build_mesh_svg(_DARK, 1080, 1350, mode=mode, seed="card-B")
    assert a != b


def test_mesh_mode_for_seed_is_deterministic_and_in_range():
    for seed in ("a", "b", "c", "card-17", 42, 0):
        m = mesh_mode_for_seed(seed)
        assert m in MESH_MODES
        assert mesh_mode_for_seed(seed) == m  # stable
    # Across many seeds, every mode is reachable (the picker isn't degenerate).
    seen = {mesh_mode_for_seed(f"seed-{i}") for i in range(60)}
    assert seen == set(MESH_MODES)


def test_auto_mode_resolves_to_a_real_mode():
    svg = build_mesh_svg(_DARK, 1080, 1350, mode="auto", seed="z")
    m = re.search(r'data-mh-mesh="(\w+)"', svg)
    assert m and m.group(1) in MESH_MODES
    # auto is stable for a given seed
    assert build_mesh_svg(_DARK, 1080, 1350, mode="auto", seed="z") == svg


def test_unknown_mode_falls_back_to_auto():
    svg = build_mesh_svg(_DARK, 1080, 1350, mode="nonsense", seed="z")
    expected = build_mesh_svg(_DARK, 1080, 1350, mode="auto", seed="z")
    assert svg == expected


# ===========================================================================
# Engine — the APCA safety property (the core guarantee)
# ===========================================================================

@pytest.mark.parametrize("roles", [_DARK, _LIGHT], ids=["dark-ground", "light-ground"])
@pytest.mark.parametrize("mode", MESH_MODES)
def test_every_mesh_colour_keeps_headline_legible(roles, mode):
    # The whole point of the APCA clamp: no matter the mode, intensity or brand,
    # the headline ink stays legible (Lc ≥ LC_LARGE) over EVERY colour the mesh
    # paints — so the mesh can never break the card.
    ink = roles["--mh-on-primary"]
    for intensity in (0.15, 0.5, 0.9):
        svg = build_mesh_svg(roles, 1080, 1350, mode=mode, seed="c", intensity=intensity)
        unsafe = [hx for hx in _hexes(svg) if not is_legible(ink, hx, min_lc=LC_LARGE)]
        assert not unsafe, f"{mode}@{intensity} unsafe stops: {unsafe}"


def test_clamp_never_regresses_below_the_flat_ground():
    # A brand whose own ink barely clears the floor still gets a varied mesh: the
    # clamp only requires the mesh be no worse than the flat brand ground.
    roles = {
        "--mh-primary": "#0E5BFF",
        "--mh-surface": "#072D7F",
        "--mh-secondary": "#101820",
        "--mh-accent": "#0E5BFF",
        "--mh-on-primary": "#FFFFFF",
    }
    svg = build_mesh_svg(roles, 1080, 1350, mode="radial", seed="c", intensity=0.8)
    cols = _hexes(svg)
    assert len(cols) >= 3, "clamp collapsed the whole field to one colour"


# ===========================================================================
# Engine — robustness (junk input, sizes, injection safety)
# ===========================================================================

def test_roles_from_junk_falls_back_without_crashing():
    roles = MeshRoles.from_role_vars(
        {"--mh-primary": "not-a-colour", "--mh-on-primary": None}
    )
    assert re.fullmatch(r"#[0-9A-F]{6}", roles.primary)
    assert re.fullmatch(r"#[0-9A-F]{6}", roles.on_primary)


def test_no_injection_from_malicious_role_values():
    # A role carrying CSS/SVG metacharacters must never reach the markup — the
    # engine normalises every colour to #RRGGBB or a safe fallback.
    roles = {
        "--mh-primary": '#000"/><script>x</script>',
        "--mh-accent": "url(evil);}",
        "--mh-on-primary": "#FFFFFF",
        "--mh-surface": "#111111",
        "--mh-secondary": "#222222",
    }
    svg = build_mesh_svg(roles, 1080, 1350, mode="radial", seed="x")
    minidom.parseString(svg)  # still valid XML
    assert "<script" not in svg and "url(evil" not in svg
    assert 'fill="' in svg


def test_empty_roles_uses_safe_defaults():
    svg = build_mesh_svg({}, 1080, 1350, mode="linear", seed="x")
    minidom.parseString(svg)
    assert svg.count("<stop") >= 3


@pytest.mark.parametrize("w,h", [(1, 1), (1080, 1080), (1920, 1080), (1080, 1920), (3, 7)])
def test_arbitrary_sizes(w: int, h: int):
    svg = build_mesh_svg(_DARK, w, h, mode="conic", seed="s")
    minidom.parseString(svg)
    assert f'width="{w}"' in svg and f'height="{h}"' in svg


def test_intensity_out_of_range_is_clamped_not_crashing():
    for bad in (-5.0, 99.0, "junk", None):
        svg = build_mesh_svg(_DARK, 1080, 1350, mode="radial", seed="s", intensity=bad)
        minidom.parseString(svg)


def test_intensity_changes_the_field():
    lo = build_mesh_svg(_DARK, 1080, 1350, mode="radial", seed="s", intensity=0.2)
    hi = build_mesh_svg(_DARK, 1080, 1350, mode="radial", seed="s", intensity=0.85)
    assert lo != hi


# ===========================================================================
# Engine — data URI
# ===========================================================================

def test_mesh_data_uri_decodes_to_the_svg():
    uri = mesh_data_uri(_DARK, 1080, 1350, mode="linear", seed="s")
    assert uri.startswith('url("data:image/svg+xml;base64,') and uri.endswith('")')
    b64 = uri[len('url("data:image/svg+xml;base64,'):-2]
    svg = base64.b64decode(b64).decode("utf-8")
    assert svg == build_mesh_svg(_DARK, 1080, 1350, mode="linear", seed="s")


def test_mesh_data_uri_is_deterministic():
    a = mesh_data_uri(_DARK, 1080, 1350, mode="conic", seed="s", intensity=0.5)
    b = mesh_data_uri(_DARK, 1080, 1350, mode="conic", seed="s", intensity=0.5)
    assert a == b


# ===========================================================================
# Render hook — discovery, opt-in/opt-out, determinism
# ===========================================================================

def _brief(background_style="gradient_mesh", **over):
    base = dict(
        id="card-7",
        content_item_id="ci-7",
        variation_signature="sig-7",
        palette={"primary": "#0A2540", "secondary": "#101820", "accent": "#F4B400"},
        background_style=background_style,
        decoration_strength=0.5,
        colour_role_assignment={},
        text_layers={},
    )
    base.update(over)
    return SimpleNamespace(**base)


def _ctx(brief, *, is_v2=True, family="big_number_dominant"):
    return RenderHookCtx(
        brief=brief, width=1080, height=1350, family=family,
        format_name="feed_portrait", is_v2=is_v2,
    )


_HTML = "<html><head><style></style></head><body><div class=\"bn\">hi</div></body></html>"


def test_hook_is_discovered_with_order():
    found = {name: order for order, name, _ in
             __import__("mediahub.graphic_renderer.sprint_hooks", fromlist=["_discover"])._discover()}
    assert "gradient_mesh_bg" in found
    assert hook.ORDER == 20


@pytest.mark.parametrize("bg", ["water", "halftone", "clean", "", "diagonal"])
def test_opt_out_is_byte_identical(bg):
    # The 🟢 ISOLATED guarantee: any non-trigger brief leaves the HTML untouched.
    out = hook.apply(_HTML, _ctx(_brief(bg)))
    assert out == _HTML


def test_seam_is_byte_identical_when_not_triggered():
    # Same guarantee, but exercised through the real auto-discovery seam.
    out = apply_render_hooks(_HTML, _ctx(_brief("water")))
    assert out == _HTML


@pytest.mark.parametrize("trigger", ["gradient_mesh", "gradient-mesh", "mesh", "GRADIENT_MESH"])
def test_opt_in_injects_mesh(trigger):
    out = hook.apply(_HTML, _ctx(_brief(trigger)))
    assert out != _HTML
    assert "mh:gradient-mesh G1.8" in out
    assert "data-mh-mesh-bg=" in out
    assert 'background-image:url("data:image/svg+xml;base64,' in out
    assert "!important" in out
    assert out.index("<style data-mh-mesh-bg") < out.index("</body>")


@pytest.mark.parametrize("mode", list(MESH_MODES))
def test_mode_suffix_forces_mode(mode):
    out = hook.apply(_HTML, _ctx(_brief(f"gradient_mesh:{mode}")))
    assert f'data-mh-mesh-bg="{mode}"' in out
    # the embedded SVG carries the same mode
    b64 = re.search(r"base64,([^\"]+)\"\)", out).group(1)
    assert f'data-mh-mesh="{mode}"' in base64.b64decode(b64).decode()


def test_unknown_mode_suffix_falls_back_to_seed_mode():
    # An unknown suffix resolves to the seed-picked concrete mode — identical to
    # asking for the mesh with no suffix at all — and the marker reports that real
    # mode (never the literal "auto"), for honest explainability.
    no_suffix = hook.apply(_HTML, _ctx(_brief("gradient_mesh")))
    unknown = hook.apply(_HTML, _ctx(_brief("gradient_mesh:wat")))
    assert unknown == no_suffix
    marked = re.search(r'data-mh-mesh-bg="(\w+)"', unknown).group(1)
    assert marked in MESH_MODES


def test_selector_order_follows_is_v2():
    v2 = hook.apply(_HTML, _ctx(_brief(), is_v2=True))
    v1 = hook.apply(_HTML, _ctx(_brief(), is_v2=False))
    v2_sel = re.search(r"<style data-mh-mesh-bg=\"\w+\">([^{]+)\{", v2).group(1)
    v1_sel = re.search(r"<style data-mh-mesh-bg=\"\w+\">([^{]+)\{", v1).group(1)
    assert v2_sel.strip().startswith("body > div:first-child")
    assert v1_sel.strip().startswith(".canvas .bg-gradient")
    # both shapes are always covered (harmless when one is absent)
    for sel in (v2_sel, v1_sel):
        assert "body > div:first-child" in sel
        assert ".bg-primary" in sel and ".bg-gradient" in sel


def test_hook_is_deterministic():
    a = hook.apply(_HTML, _ctx(_brief()))
    b = hook.apply(_HTML, _ctx(_brief()))
    assert a == b


def test_same_card_same_mesh_independent_of_random_brief_id():
    # The seed is keyed to the stable card identity, not brief.id (a fresh uuid
    # each generation). So one card reloads to the identical mesh even when its
    # brief.id differs, and different cards get different meshes.
    one = hook.apply(_HTML, _ctx(_brief(id="cb_aaaa", content_item_id="ci-X")))
    two = hook.apply(_HTML, _ctx(_brief(id="cb_bbbb", content_item_id="ci-X")))
    other = hook.apply(_HTML, _ctx(_brief(id="cb_aaaa", content_item_id="ci-Y")))
    assert one == two  # same card, different random brief.id → identical mesh
    assert one != other  # different card → different mesh


def test_decoration_strength_changes_intensity():
    calm = hook.apply(_HTML, _ctx(_brief(decoration_strength=0.0)))
    loud = hook.apply(_HTML, _ctx(_brief(decoration_strength=1.0)))
    assert calm != loud


def test_seed_falls_back_when_id_absent():
    # No id/sig → a stable digest of the palette keeps it deterministic, no crash.
    b = _brief()
    del b.id
    del b.content_item_id
    del b.variation_signature
    out1 = hook.apply(_HTML, _ctx(b))
    out2 = hook.apply(_HTML, _ctx(_brief(id=None, content_item_id=None, variation_signature=None)))
    assert "data-mh-mesh-bg=" in out1
    assert out2  # didn't raise


def test_missing_body_tag_returns_unchanged():
    no_body = "<html><head></head>nope</html>"
    assert hook.apply(no_body, _ctx(_brief())) == no_body


def test_a_raising_hook_is_swallowed_by_the_seam():
    # The seam isolates a bad hook: even a brief that makes resolution explode
    # must never break the render — apply_render_hooks returns usable HTML.
    bad = SimpleNamespace(background_style="gradient_mesh")  # missing palette etc.
    out = apply_render_hooks(_HTML, _ctx(bad))
    assert isinstance(out, str) and "</body>" in out


# ===========================================================================
# Integration — real Playwright renders (skipped without Chromium)
# ===========================================================================

def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
        return True
    except Exception:
        return False


_PLAYWRIGHT = _have_playwright()
_render_skip = pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")


def _render_brand():
    from mediahub.brand.kit import BrandKit

    return BrandKit(
        profile_id="t", display_name="Test Swim Club",
        primary_colour="#0E5BFF", secondary_colour="#101820", short_name="TSC",
    )


def _render_eval():
    from mediahub.media_requirements.evaluator import EvaluationResult

    return EvaluationResult(
        content_item_id="ci-1", content_type="achievement_card_individual",
        status="ready", suggested_layout="big_number_dominant", matched={},
        missing_required=[], missing_optional=[], recommended_action="render",
        confidence_tier="high", confidence_label="NEW PB", explain="ok",
    )


def _render_brief(background_style: str = "water", layout: str = "big_number_dominant"):
    from mediahub.creative_brief.generator import generate as gen

    item = {
        "id": "ci-1", "post_angle": "individual_pb",
        "achievement": {"swimmer_name": "Eira Hughes", "event_name": "200m Freestyle",
                        "result_time": "2:08.41"},
    }
    b = gen(item, _render_eval(), _render_brand(), profile_id="t", meet_name="Manchester Open")
    b.layout_template = layout
    b.background_style = background_style
    return b


def _changed_fraction(a: Path, b: Path) -> float:
    from PIL import Image, ImageChops

    diff = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB"))
    nonzero = sum(1 for px in diff.getdata() if px != (0, 0, 0))
    w, h = Image.open(a).size
    return nonzero / float(w * h)


@_render_skip
def test_integration_mesh_paints_on_flat_ground(tmp_path: Path):
    from mediahub.graphic_renderer.render import render_brief

    off = render_brief(_render_brief("water"), output_dir=tmp_path / "off",
                       size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())
    on = render_brief(_render_brief("gradient_mesh:radial"), output_dir=tmp_path / "on",
                      size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())

    assert "mh:gradient-mesh" in on.html and "mh:gradient-mesh" not in off.html

    off_png = Path(off.visual.file_path)
    on_png = Path(on.visual.file_path)
    for p in (off_png, on_png):
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert p.stat().st_size > 20_000
    # The mesh visibly repaints the flat ground (a large fraction of the frame).
    assert _changed_fraction(off_png, on_png) > 0.5


@_render_skip
@pytest.mark.parametrize("mode", list(MESH_MODES))
def test_integration_each_mode_renders_and_differs(tmp_path: Path, mode: str):
    from mediahub.graphic_renderer.render import render_brief

    off = render_brief(_render_brief("water"), output_dir=tmp_path / "off",
                       size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())
    on = render_brief(_render_brief(f"gradient_mesh:{mode}"), output_dir=tmp_path / mode,
                      size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())
    assert Path(on.visual.file_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert _changed_fraction(Path(off.visual.file_path), Path(on.visual.file_path)) > 0.4


@_render_skip
def test_integration_render_is_deterministic(tmp_path: Path):
    # One brief rendered twice → byte-identical PNG (same card + seed → same PNG).
    from mediahub.graphic_renderer.render import render_brief

    brief = _render_brief("gradient_mesh:conic")
    a = render_brief(brief, output_dir=tmp_path / "a",
                     size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())
    b = render_brief(brief, output_dir=tmp_path / "b",
                     size=(1080, 1350), format_name="feed_portrait", brand_kit=_render_brand())
    assert Path(a.visual.file_path).read_bytes() == Path(b.visual.file_path).read_bytes()
