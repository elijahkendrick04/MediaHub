"""Generation Engine v2 — Tier A (archetype library + deterministic picker).

Covers the SEQ-1 wiring: the ``layouts/v2`` archetype registry, the seeded
picker, the ``MEDIAHUB_GEN_V2`` gate, the brand-role / autofit / saliency CSS
injection, and the flag-off-is-unchanged invariant. The heavy Playwright render
is exercised once and skipped when Chromium is unavailable; everything else runs
without a browser by stubbing the single ``render_html_to_png`` call.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult

# The PAR-7 placeholder allow-list every v2 archetype must stay within.
_ALLOWED_PLACEHOLDERS = {
    "ATHLETE_FULL_NAME",
    "ATHLETE_FIRST_NAME",
    "ATHLETE_SURNAME_DISPLAY",
    "EVENT_NAME",
    "RESULT_VALUE",
    "ACHIEVEMENT_LABEL",
    "MEET_NAME",
    "CLUB_FULL",
    "HERO_STAT",
    "LOGO_BLOCK",
    "ATHLETE_IMG_BLOCK",
    "ACCENT_DECORATION",
    "SPONSOR_BLOCK",
    "WIDTH",
    "HEIGHT",
    "BASE_CSS",
}


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval(layout="individual_hero"):
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(*, seed=0, swimmer="Eira Hughes", result="2:08.41"):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": result,
        },
    }
    return gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="test",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=seed,
    )


# --------------------------------------------------------------------------- #
# Registry + picker (no rendering)
# --------------------------------------------------------------------------- #


def test_registry_lists_six_distinct_archetypes():
    names = archetypes.list_archetypes()
    assert len(names) >= 6, names
    assert names == sorted(names)  # stable order for a deterministic picker
    assert len(set(names)) == len(names)


def test_v2_is_default_on_with_killswitch(monkeypatch):
    # v2 is the production default: unset (or anything but a kill value) is ON.
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    assert archetypes.is_enabled() is True
    for val in ("1", "true", "on", "yes", "TRUE", "anything"):
        monkeypatch.setenv("MEDIAHUB_GEN_V2", val)
        assert archetypes.is_enabled() is True
    # the kill-switch values fall back to the legacy engine
    for val in ("0", "false", "off", "no", "OFF"):
        monkeypatch.setenv("MEDIAHUB_GEN_V2", val)
        assert archetypes.is_enabled() is False


def test_picker_is_deterministic_and_spreads():
    names = archetypes.list_archetypes()
    # stable per seed
    assert archetypes.pick_archetype(3) == archetypes.pick_archetype(3)
    # spreads across the whole library over distinct seeds
    picks = {archetypes.pick_archetype(s) for s in range(len(names) * 2)}
    assert picks == set(names)


# --------------------------------------------------------------------------- #
# Archetype authoring convention (PAR-7 hygiene)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", archetypes.list_archetypes())
def test_archetype_follows_convention(name):
    raw = (archetypes.V2_DIR / f"{name}.html").read_text(encoding="utf-8")
    # {{BASE_CSS}} present
    assert "{{BASE_CSS}}" in raw
    # brand colour only via --mh-* roles: no hex colour literal anywhere
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None, f"{name} has a hex literal"
    assert "var(--mh-" in raw
    # every placeholder is on the allow-list
    for ph in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", raw)):
        assert ph in _ALLOWED_PLACEHOLDERS, f"{name} uses unknown placeholder {ph}"


@pytest.mark.parametrize("name", archetypes.list_archetypes())
def test_archetype_has_authoring_notes(name):
    # GENERATION.md §7: every archetype ships a one-paragraph <name>.notes.md
    # describing the composition and when the director should pick it — the
    # notes feed the SEQ-2 design-spec director's archetype catalog.
    notes = archetypes.V2_DIR / f"{name}.notes.md"
    assert notes.exists(), f"{name} is missing its .notes.md (director catalog entry)"
    text = notes.read_text(encoding="utf-8").strip()
    assert len(text) > 200, f"{name}.notes.md is too thin to brief the director"


# --------------------------------------------------------------------------- #
# Generator integration: flag flips the layout to a v2 archetype
# --------------------------------------------------------------------------- #


def test_generator_uses_legacy_family_with_killswitch(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")  # kill-switch → legacy engine
    brief = _brief()
    assert brief.layout_template not in archetypes.list_archetypes()


def test_generator_swaps_to_v2_when_flag_on(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    chosen = {_brief(seed=s).layout_template for s in range(12)}
    # every chosen layout is a real v2 archetype, and a pack spans them all
    assert chosen <= set(archetypes.list_archetypes())
    assert len(chosen) >= 6


# --------------------------------------------------------------------------- #
# Full HTML assembly without a browser (stub the Playwright call)
# --------------------------------------------------------------------------- #


def _render_html(monkeypatch, tmp_path, brief):
    """Run render_brief but capture the assembled HTML instead of rasterising."""
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350))
    return captured["html"]


@pytest.mark.parametrize("seed", range(6))
def test_v2_assembly_is_clean_for_every_archetype(monkeypatch, tmp_path, seed):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    brief = _brief(seed=seed)
    html = _render_html(monkeypatch, tmp_path, brief)
    # no raw placeholders survive
    assert "{{" not in html and "}}" not in html
    # the brand role tokens + autofit vars were injected
    assert ":root{" in html
    for token in (
        "--mh-primary:",
        "--mh-accent:",
        "--mh-on-primary:",
        "--mh-fit-surname-px:",
        "--mh-fit-result-px:",
        "--mh-photo-pos:",
    ):
        assert token in html, f"{brief.layout_template} missing {token}"
    # real content made it in
    assert "Manchester Open" in html


def test_autofit_shrinks_a_long_surname(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")

    def _surname_px(html):
        m = re.search(r"--mh-fit-surname-px:(\d+)px", html)
        assert m, "surname autofit var not found"
        return int(m.group(1))

    short = _render_html(monkeypatch, tmp_path, _brief(seed=0, swimmer="Mo Li"))
    # a genuinely long, wide surname can't fit at the 132px default in the box,
    # so autofit must shrink it rather than let it overflow
    long = _render_html(
        monkeypatch,
        tmp_path,
        _brief(seed=0, swimmer="Aleksandra Vandersloot-Chamberlain"),
    )
    short_px, long_px = _surname_px(short), _surname_px(long)
    assert short_px == 132  # short name keeps the layout's full default
    assert long_px < short_px  # long name autofits down — no overflow


def test_killswitch_renders_a_legacy_layout(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")  # kill-switch → legacy engine
    brief = _brief()
    html = _render_html(monkeypatch, tmp_path, brief)
    # legacy engine: no v2 role-token block is injected
    assert "--mh-fit-surname-px:" not in html
    assert "{{" not in html


# --------------------------------------------------------------------------- #
# Regression guards (from code review)
# --------------------------------------------------------------------------- #


def test_darken_fallback_is_byte_identical_flag_off():
    """The v2 helpers must not shadow the module-level `_hex_to_rgb` and change
    `darken`/`lighten`'s malformed-input fallback — that would alter the legacy
    (flag-OFF) render path. Pre-PR `darken("")` is "#000000"."""
    from mediahub.graphic_renderer.render import darken, lighten

    assert darken("") == "#000000"
    assert lighten("") != "#0A2540"  # not the navy the duplicate helper returned


def test_single_colour_kit_accent_stays_legible():
    """A kit with only a primary (accent=None, secondary=#000000 by BrandKit
    default) must NOT collapse --mh-accent to black against a dark ground."""
    from mediahub.graphic_renderer.render import _mh_role_vars, _contrast_ratio

    kit = BrandKit(
        profile_id="x",
        display_name="X",
        primary_colour="#A30D2D",
        secondary_colour="#000000",
        short_name="X",
    )  # accent_colour defaults to None
    roles = _mh_role_vars({}, kit)
    assert _contrast_ratio(roles["--mh-accent"], roles["--mh-primary"]) >= 3.0


def test_contrasting_secondary_is_used_as_accent():
    """A navy+gold kit (no explicit accent) should still get the gold secondary
    as its accent — the legibility guard must not discard a good contrast."""
    from mediahub.graphic_renderer.render import _mh_role_vars

    kit = BrandKit(
        profile_id="x",
        display_name="X",
        primary_colour="#0A2540",
        secondary_colour="#F2C14E",
        short_name="X",
    )
    assert _mh_role_vars({}, kit)["--mh-accent"].upper() == "#F2C14E"


def test_fit_one_line_keeps_multiword_surname_on_one_line():
    """`white-space: nowrap` slots must be sized single-line: a multi-word
    surname has to FIT on one line at the returned px (no overflow/clip)."""
    from mediahub.graphic_renderer.render import _fit_one_line_px
    from mediahub.graphic_renderer.autofit import em_width

    box_w = 1080 * 0.86
    surname = "VAN DER BERG"
    px = _fit_one_line_px(
        surname, box_w, 1350 * 0.18, font_family="Anton", weight=400, min_px=44, max_px=132
    )
    assert em_width(surname, font_family="Anton", weight=400) * px <= box_w + 1


# --------------------------------------------------------------------------- #
# One real Playwright render (skipped without Chromium)
# --------------------------------------------------------------------------- #


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                b = p.chromium.launch()
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_real_render_produces_pngs_for_all_archetypes(monkeypatch, tmp_path):
    from mediahub.graphic_renderer.render import render_brief

    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    seen = set()
    for seed in range(6):
        brief = _brief(seed=seed)
        seen.add(brief.layout_template)
        res = render_brief(brief, output_dir=tmp_path / str(seed), size=(1080, 1350))
        assert res.png_bytes > 2000  # a real, non-empty card
        assert "{{" not in res.html
    assert len(seen) >= 6  # the pack really spanned the library
