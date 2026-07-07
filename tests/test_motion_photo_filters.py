"""R1.10 — Motion photo filter stack (sprint/layers/photo_filters.tsx).

The reel-side photo grade: a deterministic, frame-pure brightness / contrast /
saturation / blur treatment applied to the card's photo, driven by brief fields
(``photo_treatment`` + a small ``mood`` nuance), in parity with the still
renderer's ``_photo_treatment_css``.

No Node needed: the live render is exercised by hand / the integration gates;
everything here is the same source-contract + prop-flow shaping the rest of the
motion suite uses (see ``test_motion_v2_parity.py``), plus a genuine numeric
parity cross-check against the still renderer so the two surfaces can't drift.
"""
from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer.render import _photo_treatment_css
from mediahub.visual import motion


LAYER = (
    motion.REMOTION_DIR
    / "src"
    / "compositions"
    / "sprint"
    / "layers"
    / "photo_filters.tsx"
)

# The canonical photo-treatment vocabulary (creative_brief/generator.py +
# graphic_renderer/render.py). Only these three grade the photo on the still;
# the motion layer must grade exactly the same set and leave the rest clean.
GRADED = ("duotone", "halftone", "vignette")
CLEAN = ("cutout", "frame", "no-photo", "")

BRAND = BrandKit(
    profile_id="pf-parity",
    display_name="Filter SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="FSC",
)


def _src() -> str:
    return LAYER.read_text()


# ---------------------------------------------------------------------------
# The file exists and honours the sprint layer drop-in contract
# ---------------------------------------------------------------------------


def test_layer_file_exists():
    assert LAYER.is_file(), f"R1.10 layer missing at {LAYER}"


def test_layer_honours_the_registry_contract():
    """A layer module DEFAULT-exports ``{ Layer, order? }`` (registry.ts)."""
    src = _src()
    assert re.search(r"const\s+Layer\s*:\s*SceneComponent", src), (
        "Layer must be typed as the registry's SceneComponent"
    )
    assert re.search(r"export\s+default\s*\{\s*Layer\s*,\s*order\s*:", src), (
        "must default-export { Layer, order } so require.context can discover it"
    )
    # Imports types from the one place every sprint module does (../registry).
    assert 'from "../registry"' in src


def test_layer_lives_under_the_auto_discovered_layers_dir():
    """The sprint registry's require.context enumerates sprint/layers/*.tsx, and
    the motion-parity scanner walks sprint/**/*.tsx — both discover any file
    placed here with no StoryCard.tsx edit. Confirm the file sits in that folder
    and its grade source is visible to a sprint-wide scan."""
    comp = motion.REMOTION_DIR / "src" / "compositions"
    assert LAYER.parent == comp / "sprint" / "layers"
    corpus = "\n".join(
        p.read_text()
        for p in sorted((comp / "sprint").rglob("*"))
        if p.suffix in {".ts", ".tsx"}
    )
    assert "brightness(" in corpus, (
        "the photo-filter layer source must be part of the scanned motion corpus"
    )


# ---------------------------------------------------------------------------
# All four roadmap levers, deterministic + frame-pure
# ---------------------------------------------------------------------------


def test_declares_all_four_roadmap_levers():
    """R1.10 names brightness / contrast / saturation / blur explicitly."""
    src = _src()
    for lever in ("brightness(", "contrast(", "saturate(", "blur("):
        assert lever in src, f"missing filter lever {lever!r}"


def test_is_frame_pure_and_deterministic():
    src = _src()
    # Time-varying values ride the frame via interpolate(frame, ...).
    assert "interpolate(frame" in src
    assert "Easing" in src
    # Determinism: never a wall-clock or RNG source in a render (the call
    # forms — the file's own comment mentions the names in prose).
    assert "Math.random(" not in src
    assert "Date.now(" not in src and "new Date(" not in src


def test_focus_in_blur_resolves_to_zero():
    """The blur is a frame-pure focus-in that settles to 0 so the held frame
    (and any text caught in the photo zone) is never permanently softened."""
    src = _src()
    # interpolate(frame, [0, fps * FOCUS_IN_SEC], [FOCUS_IN_BLUR_PX, 0], ...)
    assert re.search(r"\[\s*FOCUS_IN_BLUR_PX\s*,\s*0\s*\]", src), (
        "the focus-in blur must interpolate down to 0"
    )


# ---------------------------------------------------------------------------
# Gating: no-op for photo-less and clean/structural cards (byte-identical)
# ---------------------------------------------------------------------------


def test_no_op_without_a_photo():
    src = _src()
    assert re.search(r"if\s*\(!card\.photoSrc\)\s*\{?\s*return null", src), (
        "must return null when there is no photo (photo-less cards unchanged)"
    )


def test_only_the_graded_treatments_produce_a_stack():
    """baseStackFor returns a stack for duotone/halftone/vignette and null for
    everything else — so cutout / frame / no-photo / unknown stay clean."""
    src = _src()
    block = src.split("function baseStackFor", 1)[1].split("\n}", 1)[0]
    for t in GRADED:
        assert f'case "{t}"' in block, f"graded treatment {t!r} not handled"
    for t in ("cutout", "frame", "no-photo"):
        assert f'case "{t}"' not in block, (
            f"clean/structural treatment {t!r} must fall through to null, not grade"
        )
    assert "return null" in block, "the default branch must be a no-grade null"


def test_mood_only_shifts_an_already_active_grade():
    """A mood nuance must never turn a clean photo graded — it only adjusts a
    stack baseStackFor already returned."""
    src = _src()
    # applyMoodNuance takes an existing FilterStack and returns a shifted one.
    assert re.search(r"function applyMoodNuance\(s:\s*FilterStack", src)


# ---------------------------------------------------------------------------
# Parity: the held grade matches the still renderer numerically
# ---------------------------------------------------------------------------


def _parse_css_filter(css: str) -> dict[str, float]:
    """Pull ``func(value)`` numbers out of a CSS ``filter:`` declaration."""
    return {
        name: float(val)
        for name, val in re.findall(r"(\w+)\(([\d.]+)\)", css)
    }


def _parse_tsx_stack(treatment: str) -> dict[str, float]:
    """Pull the numeric FilterStack the TSX returns for one treatment."""
    src = _src()
    block = src.split("function baseStackFor", 1)[1].split("\n}", 1)[0]
    case = block.split(f'case "{treatment}"', 1)[1].split("return {", 1)[1]
    case = case.split("};", 1)[0]
    return {k: float(v) for k, v in re.findall(r"(\w+):\s*([\d.]+)", case)}


@pytest.mark.parametrize("treatment", ["duotone", "halftone"])
def test_held_grade_matches_the_still_renderer(treatment):
    """duotone / halftone carry the same brightness / contrast / grayscale /
    sepia the still graphic paints, so a card's video reads like its still."""
    still = _parse_css_filter(_photo_treatment_css(treatment, {"accent": "#FFF"}))
    tsx = _parse_tsx_stack(treatment)
    for func in ("brightness", "contrast", "grayscale", "sepia"):
        if func in still:
            assert tsx.get(func) == pytest.approx(still[func]), (
                f"{treatment}.{func}: motion {tsx.get(func)} != still {still[func]}"
            )


# ---------------------------------------------------------------------------
# Prop flow: every treatment token reaches the composition as photoTreatment
# ---------------------------------------------------------------------------


def _card(i: int = 1) -> dict:
    return {
        "id": f"pf-{i}",
        "achievement": {
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": "58.12",
        },
        "meet_name": "Filter Open",
    }


@pytest.mark.parametrize("treatment", [*GRADED, "cutout", "no-photo"])
def test_photo_treatment_flows_into_card_props(treatment):
    brief = generate(
        {
            "id": "pf-1",
            "post_angle": "confirmed_official_pb",
            "achievement": _card(1)["achievement"],
        },
        None,
        BRAND,
        profile_id="pf-parity",
    ).to_dict()
    brief["photo_treatment"] = treatment
    props = motion._card_to_props(_card(1), variation_seed=1, brief=brief)
    assert props["photoTreatment"] == treatment


# ---------------------------------------------------------------------------
# Photo-element-only scope: the grade rides the photo <img>, never scene text
# ---------------------------------------------------------------------------


def test_grade_is_exported_as_a_photo_element_filter_helper():
    """The grade is applied per photo element via photoGradeFilterFor — the
    exact scope of the still's _photo_treatment_css — not a scene-wide wash."""
    src = _src()
    assert "export function photoGradeFilterFor" in src
    # The gates return "" so ungraded cards stay byte-identical.
    assert re.search(r"if\s*\(!card\.photoSrc\)\s*\{?\s*return \"\"", src)


def test_banded_backdrop_filter_is_retired():
    """The old fixed-band backdrop-filter washed any copy inside 17–48% of the
    frame — it must stay gone; only the vignette radial overlay may remain."""
    src = _src()
    assert "backdropFilter" not in src and "WebkitBackdropFilter" not in src
    assert "PHOTO_ZONE_MASK" not in src
    # The Layer half only paints the vignette's radial edge-darkening.
    layer_block = src.split("const Layer: SceneComponent", 1)[1]
    assert '!== "vignette"' in layer_block and "radial-gradient" in layer_block
    assert "cssFilter(" not in layer_block, "the Layer must not apply the photo grade itself"


@pytest.mark.parametrize(
    "path,component",
    [
        ("StoryCard.tsx", "const PhotoLayer"),
        ("sprint/sceneKit.tsx", "export const PhotoFill"),
    ],
)
def test_photo_paint_sites_apply_the_grade_on_their_img(path, component):
    """Both shared photo paint sites thread photoGradeFilterFor into their own
    <img> style.filter (and only when a grade is active, so clean cards keep a
    byte-identical style object)."""
    src = (motion.REMOTION_DIR / "src" / "compositions" / path).read_text()
    assert "photoGradeFilterFor" in src, f"{path} must import the grade helper"
    block = src.split(component, 1)[1]
    img = block.split("<img", 1)[1].split("/>", 1)[0]
    assert "grade ? { filter: grade }" in img, (
        f"{component} must apply the grade on its own <img> element"
    )
