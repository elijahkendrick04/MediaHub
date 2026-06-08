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


def test_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    assert archetypes.is_enabled() is False
    for val in ("1", "true", "on", "yes", "TRUE"):
        monkeypatch.setenv("MEDIAHUB_GEN_V2", val)
        assert archetypes.is_enabled() is True
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
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


# --------------------------------------------------------------------------- #
# Generator integration: flag flips the layout to a v2 archetype
# --------------------------------------------------------------------------- #


def test_generator_keeps_legacy_family_when_flag_off(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
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


def test_flag_off_renders_a_legacy_layout(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    brief = _brief()
    html = _render_html(monkeypatch, tmp_path, brief)
    # legacy engine: no v2 role-token block is injected
    assert "--mh-fit-surname-px:" not in html
    assert "{{" not in html


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
