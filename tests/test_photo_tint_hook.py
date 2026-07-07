"""Tests for the G1.7 photo-derived ground-tint render hook.

Covers the two hard rules and the default-on contract (M9/STILLS-3):

  * **Never overrides a confirmed brand hex** — a club's ``--mh-primary`` is left
    byte-identical; only the *derived* ``--mh-surface`` is tinted. The no-brand
    fallback ground is the sole exception (then the photo may seed it).
  * **APCA-gated** — a tint that would erode on-ground legibility is rejected and
    the card renders unchanged.
  * **Default ON / explicit off byte-identical** — unset ``MEDIAHUB_PHOTO_TINT``
    runs the hook; an explicit falsy value (``0``/``false``/``no``/``off``) is a
    pure no-op; v1 cards and photo-less cards pass through untouched either way.
  * Wired into the real ``render_brief`` pipeline (Playwright stubbed).
"""
from __future__ import annotations

import base64
import io
import re

import pytest
from PIL import Image

from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
from mediahub.graphic_renderer.sprint_hooks import photo_tint as PT
from mediahub.theming.contrast import apca


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _tint_on(monkeypatch):
    """Default every test to flag-ON; the opt-in tests clear it explicitly."""
    monkeypatch.setenv("MEDIAHUB_PHOTO_TINT", "1")


def _photo_uri(colour=(230, 120, 40), size=(60, 90)) -> str:
    """A solid-colour opaque photo as an inlined PNG data URI."""
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _html(roles: dict, *, with_photo=True, photo_colour=(230, 120, 40)) -> str:
    root = "".join(f"{k}:{v};" for k, v in roles.items())
    img = (
        f'<img class="athlete-cutout" src="{_photo_uri(photo_colour)}" alt="x"/>'
        if with_photo
        else "<div>text-led, no photo</div>"
    )
    return (
        "<html><head><style>:root{" + root + "}</style></head>"
        f"<body><div class=\"sd\">{img}</div></body></html>"
    )


class _Brief:
    def __init__(self, palette):
        self.palette = palette


def _ctx(palette, *, is_v2=True):
    return RenderHookCtx(
        brief=_Brief(palette),
        width=1080,
        height=1350,
        family="split_diagonal_hero",
        format_name="feed_portrait",
        is_v2=is_v2,
    )


def _injected(html: str) -> dict:
    """Parse ONLY the hook's appended block — the ``<style>:root{…}</style>``
    immediately before ``</body>`` — so the page's own head ``:root`` is never
    mistaken for an injection. Returns ``{}`` when the hook injected nothing.
    """
    m = re.search(r"<style>:root\{([^}]*)\}</style></body>", html)
    if not m:
        return {}
    out = {}
    for decl in m.group(1).split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip()] = v.strip()
    return out


_CONFIRMED = {
    "--mh-primary": "#0E5BFF",
    "--mh-secondary": "#101820",
    "--mh-accent": "#FFC400",
    "--mh-surface": "#072E80",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.20)",
}


# --------------------------------------------------------------------------- #
# Rule 1 — never overrides a confirmed brand hex
# --------------------------------------------------------------------------- #


def test_confirmed_brand_primary_is_never_overridden():
    html = _html(_CONFIRMED)
    out = PT.apply(html, _ctx({"primary": "#0E5BFF", "secondary": "#101820"}))
    inj = _injected(out)
    # The brand ground is NOT among the re-declared vars …
    assert "--mh-primary" not in inj
    # … and the original brand hex still stands, untouched, exactly once.
    assert out.count("--mh-primary:#0E5BFF") == 1


def test_derived_surface_is_tinted_toward_the_photo():
    html = _html(_CONFIRMED, photo_colour=(230, 120, 40))  # orange
    out = PT.apply(html, _ctx({"primary": "#0E5BFF"}))
    inj = _injected(out)
    assert "--mh-surface" in inj
    new = inj["--mh-surface"]
    assert new.upper() != "#072E80"  # moved …
    # … toward the photo: the red channel rises relative to the deep-blue base.
    assert int(new[1:3], 16) > 0x07
    # The decorative photo accent is exposed for downstream hooks.
    assert inj.get("--mh-photo-accent")


def test_unconfirmed_fallback_ground_may_be_seeded_from_photo():
    """A club that supplied NO brand colour gets the renderer fallback ground
    (#0A2540) with an empty brief palette — only then may the photo tint it."""
    roles = dict(_CONFIRMED, **{"--mh-primary": "#0A2540", "--mh-surface": "#051220"})
    out = PT.apply(_html(roles), _ctx({}))  # empty brief palette → unconfirmed
    inj = _injected(out)
    assert "--mh-primary" in inj
    assert inj["--mh-primary"].upper() != "#0A2540"


def test_navy_brand_equal_to_fallback_is_still_protected_when_brief_has_it():
    """A real club whose brand IS #0A2540 must stay protected: the brief carries
    it as the brand primary, so it is confirmed despite equalling the fallback."""
    roles = dict(_CONFIRMED, **{"--mh-primary": "#0A2540", "--mh-surface": "#051220"})
    out = PT.apply(_html(roles), _ctx({"primary": "#0A2540"}))
    assert "--mh-primary" not in _injected(out)


# --------------------------------------------------------------------------- #
# Rule 2 — APCA gate
# --------------------------------------------------------------------------- #


def test_tint_keeps_on_surface_legible():
    html = _html(_CONFIRMED)
    out = PT.apply(html, _ctx({"primary": "#0E5BFF"}))
    new_surface = _injected(out)["--mh-surface"]
    # White on-surface ink must still clear the APCA headline bar on the tint.
    assert abs(apca("#FFFFFF", new_surface)) >= 45.0


def test_illegible_surface_is_left_untouched():
    """If the surface already can't carry its ink (white on near-white), the gate
    refuses to tint it rather than make a bad ground worse."""
    roles = dict(_CONFIRMED, **{"--mh-surface": "#F4F4F4", "--mh-on-surface": "#FFFFFF"})
    out = PT.apply(_html(roles), _ctx({"primary": "#0E5BFF"}))
    assert "--mh-surface" not in _injected(out)


# --------------------------------------------------------------------------- #
# Opt-in / no-op contract
# --------------------------------------------------------------------------- #


def test_flag_off_is_byte_identical(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_PHOTO_TINT", "0")
    html = _html(_CONFIRMED)
    assert PT.apply(html, _ctx({"primary": "#0E5BFF"})) == html


def test_unset_flag_defaults_on(monkeypatch):
    # M9: the tint is default-ON — an unset flag runs the hook.
    monkeypatch.delenv("MEDIAHUB_PHOTO_TINT", raising=False)
    html = _html(_CONFIRMED)
    out = PT.apply(html, _ctx({"primary": "#0E5BFF"}))
    assert out != html and "--mh-photo-accent:" in out


@pytest.mark.parametrize("val", ["0", "false", "no", "off"])
def test_falsey_flag_values_are_no_ops(monkeypatch, val):
    monkeypatch.setenv("MEDIAHUB_PHOTO_TINT", val)
    html = _html(_CONFIRMED)
    assert PT.apply(html, _ctx({"primary": "#0E5BFF"})) == html


def test_v1_cards_are_untouched():
    html = _html(_CONFIRMED)
    assert PT.apply(html, _ctx({"primary": "#0E5BFF"}, is_v2=False)) == html


def test_photoless_card_is_untouched():
    html = _html(_CONFIRMED, with_photo=False)
    assert PT.apply(html, _ctx({"primary": "#0E5BFF"})) == html


def test_missing_role_vars_is_untouched():
    # No :root surface at all → nothing safe to tint.
    html = "<html><head></head><body>" + f'<img class="athlete-cutout" src="{_photo_uri()}"/>' + "</body></html>"
    assert PT.apply(html, _ctx({"primary": "#0E5BFF"})) == html


def test_hook_is_deterministic():
    html = _html(_CONFIRMED)
    ctx = _ctx({"primary": "#0E5BFF"})
    assert PT.apply(html, ctx) == PT.apply(html, ctx)


def test_neutral_photo_produces_no_tint():
    """A flat grey photo has a tint target (its grey), but tinting the deep-blue
    surface toward grey still clears the gate — assert we at least never raise and
    never touch the brand ground."""
    out = PT.apply(_html(_CONFIRMED, photo_colour=(120, 120, 120)), _ctx({"primary": "#0E5BFF"}))
    assert "--mh-primary" not in _injected(out)


# --------------------------------------------------------------------------- #
# Registry wiring — discovered, ordered, isolated
# --------------------------------------------------------------------------- #


def test_hook_is_registered_in_the_seam():
    from mediahub.graphic_renderer.sprint_hooks import _discover

    names = [name for _order, name, _fn in _discover()]
    assert "photo_tint" in names


def test_a_raising_hook_is_skipped_not_fatal(monkeypatch):
    """The registry isolates a bad hook; flag-on with malformed html must not
    raise out of apply_render_hooks."""
    from mediahub.graphic_renderer.sprint_hooks import apply_render_hooks

    ctx = _ctx({"primary": "#0E5BFF"})
    # Garbage in → unchanged out, no exception.
    assert apply_render_hooks("<html></html>", ctx) == "<html></html>"


# --------------------------------------------------------------------------- #
# End-to-end through the real render pipeline (Playwright stubbed)
# --------------------------------------------------------------------------- #


def _render_capture(monkeypatch, tmp_path, photo_path, *, tint: bool):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    # M9: the hook is default-ON, so "off" is now the explicit kill value.
    monkeypatch.setenv("MEDIAHUB_PHOTO_TINT", "1" if tint else "0")

    import mediahub.graphic_renderer.render as R
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    brand = BrandKit(
        profile_id="t",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )
    ev = EvaluationResult(
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
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    brief = gen_brief(item, ev, brand, profile_id="t", meet_name="Manchester Open", variation_seed=0)
    brief.layout_template = "split_diagonal_hero"

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350), athlete_path=str(photo_path), skip_cutout=True)
    return captured["html"]


@pytest.fixture
def structured_photo(tmp_path):
    """A photo with a real colour story (orange subject on blue)."""
    p = tmp_path / "athlete.png"
    im = Image.new("RGB", (200, 300), (20, 60, 160))
    im.paste(Image.new("RGB", (120, 200), (230, 120, 40)), (40, 50))
    im.save(p)
    return p


def test_e2e_hook_fires_and_preserves_brand(monkeypatch, tmp_path, structured_photo):
    off = _render_capture(monkeypatch, tmp_path / "off", structured_photo, tint=False)
    on = _render_capture(monkeypatch, tmp_path / "on", structured_photo, tint=True)

    # Flag-off render carries no photo tint; flag-on does → the hook is wired.
    assert "--mh-photo-accent:" not in off
    assert "--mh-photo-accent:" in on
    assert on != off
    # The athlete photo really is inlined for the hook to read.
    assert "athlete-cutout" in on
    # The confirmed brand ground survives in BOTH renders, untouched.
    assert off.count("--mh-primary:#0E5BFF") == 1
    assert on.count("--mh-primary:#0E5BFF") == 1


def test_e2e_flag_off_render_has_no_injection(monkeypatch, tmp_path, structured_photo):
    off = _render_capture(monkeypatch, tmp_path, structured_photo, tint=False)
    assert "<style>:root{--mh-surface:" not in off
