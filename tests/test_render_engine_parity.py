"""Render-engine parity — the production default (Gen Engine v2) gets covered.

Deep-review finding #132: the suite-wide autouse pin in ``conftest.py`` runs
every render test on the *legacy* v1 engine, even though Gen Engine v2 is the
production default (``archetypes.is_enabled()`` is True unless
``MEDIAHUB_GEN_V2=0``). So the bulk of render coverage validated a path a real
customer's card never takes.

This module is the first slice of the parity layer. Every test here requests the
``render_engine`` fixture (``conftest.py``), so its body runs **twice** — once on
legacy v1, once under the real production default — driving the true
``render_brief`` path (Playwright stubbed) for a generator-picked family on each
engine. Under v1 the generator picks a *legacy* family; under the default it
swaps to a *v2 archetype*, so the two runs exercise genuinely different render
code, and the shared assertions pin the contract that must hold on both: a clean,
branded, placeholder-free card carrying the real, verified facts.

No browser needed — the single ``render_html_to_png`` call is stubbed, exactly as
``tests/test_gen_v2_tier_a.py`` does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult

# The v2-only CSS custom properties ``render.py`` injects when the resolved brand
# roles + autofit boxes ride into a v2 archetype (Tier A/B). The legacy engine
# never emits these — they are the fingerprint of the production render path.
_V2_ROLE_TOKENS = (
    ":root{",
    "--mh-primary:",
    "--mh-accent:",
    "--mh-on-primary:",
    "--mh-fit-surname-px:",
    "--mh-fit-result-px:",
    "--mh-photo-pos:",
)


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval() -> EvaluationResult:
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


def _brief(*, seed: int = 0, swimmer: str = "Eira Hughes", result: str = "2:08.41"):
    """Build a real ``CreativeBrief`` through the production generator.

    The generator reads ``archetypes.is_enabled()`` at build time, so the family
    it picks depends on the engine the ``render_engine`` fixture selected: a legacy
    family under v1, a ``layouts/v2`` archetype under the default.
    """
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


def _render_capture(monkeypatch, tmp_path, brief, **kwargs):
    """Run the real ``render_brief`` but capture the assembled HTML instead of
    rasterising — the one Playwright seam (``render_html_to_png``) is stubbed, so
    this runs everywhere with no Chromium."""
    import mediahub.graphic_renderer.render as R

    captured: dict[str, str] = {}

    def _fake_png(html, output_path, size, **_kw):
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    res = R.render_brief(brief, output_dir=tmp_path, brand_kit=_brand(), **kwargs)
    return res, captured["html"]


# --------------------------------------------------------------------------- #
# The parity layer is wired correctly
# --------------------------------------------------------------------------- #


def test_flag_matches_selected_engine(render_engine):
    """The ``render_engine`` fixture + the autouse back-off actually flip the
    production gate — v2 leaves ``is_enabled()`` True, v1 forces it False. Without
    the back-off the suite-wide pin would clobber the v2 leg and this would fail."""
    assert archetypes.is_enabled() is (render_engine == "v2")


# --------------------------------------------------------------------------- #
# The crux of #132: the production default renders the v2 archetype path
# --------------------------------------------------------------------------- #


def test_engine_takes_expected_family_path(render_engine, monkeypatch, tmp_path):
    """v2 must route through a real ``layouts/v2`` archetype; v1 through a legacy
    family. This is the heart of the finding — proof that the production default
    exercises the archetype engine, not the legacy one the suite used to pin."""
    brief = _brief(seed=0)
    is_archetype = brief.layout_template in archetypes.list_archetypes()
    if render_engine == "v2":
        assert is_archetype, (
            "production default should render a v2 archetype, "
            f"got legacy family {brief.layout_template!r}"
        )
    else:
        assert not is_archetype, (
            f"legacy engine should render a v1 family, got archetype {brief.layout_template!r}"
        )
    # …and it assembles cleanly whichever path it took.
    _res, html = _render_capture(monkeypatch, tmp_path, brief, size=(1080, 1350))
    assert "{{" not in html and "}}" not in html


def test_brand_role_injection_is_v2_only(render_engine, monkeypatch, tmp_path):
    """The resolved ``--mh-*`` brand-role tokens + autofit vars are a v2 render
    feature (APCA-gated role resolution → archetype slots). Under the production
    default they must be injected into the assembled HTML; the legacy engine paints
    brand colour a different way and must not emit the v2 role scaffold. Pinning
    both directions stops the v2 injection from silently regressing to the
    previously-untested path."""
    brief = _brief(seed=0)
    _res, html = _render_capture(monkeypatch, tmp_path, brief, size=(1080, 1350))
    if render_engine == "v2":
        for token in _V2_ROLE_TOKENS:
            assert token in html, f"v2 render of {brief.layout_template!r} is missing {token!r}"
    else:
        assert "--mh-fit-surname-px:" not in html
        assert "--mh-photo-pos:" not in html


# --------------------------------------------------------------------------- #
# The shared contract every engine must honour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("seed", range(10))
def test_render_assembles_clean_card(render_engine, monkeypatch, tmp_path, seed):
    """The core contract that must hold on BOTH engines: the generator-picked
    family assembles through ``render_brief`` into a clean, branded card with a
    real PNG written and full provenance — no unfilled template placeholders,
    whichever engine ran. Ten seeds spread the generator's picker across ten
    distinct families per engine, so this is not a single-layout smoke test."""
    brief = _brief(seed=seed)
    res, html = _render_capture(monkeypatch, tmp_path, brief, size=(1080, 1350))

    # No unfilled template placeholders survived assembly.
    assert "{{" not in html and "}}" not in html
    assert len(html) > 5000, "assembled HTML is an empty shell, not a real card"

    # The RenderResult / GeneratedVisual provenance is populated identically.
    assert res.png_bytes > 0
    assert res.visual.layout_template == brief.layout_template
    assert (res.visual.width, res.visual.height) == (1080, 1350)
    out = Path(res.visual.file_path)
    assert out.exists() and out.name == "feed_portrait.png"

    # The club identity always reaches the card, on either engine.
    assert "Test Swim Club" in html or "TSC" in html


@pytest.mark.parametrize("seed", (0, 2, 6))
def test_content_fidelity_is_engine_independent(render_engine, monkeypatch, tmp_path, seed):
    """The verified facts survive assembly on either engine — the athlete's real
    result and club identity are never dropped or garbled by the layout swap. Seeds
    0/2/6 pick an individual-result family on both engines; if a future archetype
    addition shifts the picker so one lands on a recap/preview family (which
    legitimately omits a single result), re-curate the seeds here."""
    brief = _brief(seed=seed, swimmer="Eira Hughes", result="2:08.41")
    _res, html = _render_capture(monkeypatch, tmp_path, brief, size=(1080, 1350))
    assert "2:08.41" in html, f"result value dropped by {brief.layout_template!r}"
    assert "Test Swim Club" in html or "TSC" in html
