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


LAYER = motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "layers" / "photo_filters.tsx"

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
    assert re.search(
        r"const\s+Layer\s*:\s*SceneComponent", src
    ), "Layer must be typed as the registry's SceneComponent"
    assert re.search(
        r"export\s+default\s*\{\s*Layer\s*,\s*order\s*:", src
    ), "must default-export { Layer, order } so require.context can discover it"
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
        p.read_text() for p in sorted((comp / "sprint").rglob("*")) if p.suffix in {".ts", ".tsx"}
    )
    assert (
        "brightness(" in corpus
    ), "the photo-filter layer source must be part of the scanned motion corpus"


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
    assert re.search(
        r"\[\s*FOCUS_IN_BLUR_PX\s*,\s*0\s*\]", src
    ), "the focus-in blur must interpolate down to 0"


# ---------------------------------------------------------------------------
# Gating: no-op for photo-less and clean/structural cards (byte-identical)
# ---------------------------------------------------------------------------


def test_no_op_without_a_photo():
    src = _src()
    assert re.search(
        r"if\s*\(!card\.photoSrc\)\s*\{?\s*return null", src
    ), "must return null when there is no photo (photo-less cards unchanged)"


def test_only_the_graded_treatments_produce_a_stack():
    """baseStackFor returns a stack for duotone/halftone/vignette and null for
    everything else — so cutout / frame / no-photo / unknown stay clean."""
    src = _src()
    block = src.split("function baseStackFor", 1)[1].split("\n}", 1)[0]
    for t in GRADED:
        assert f'case "{t}"' in block, f"graded treatment {t!r} not handled"
    for t in ("cutout", "frame", "no-photo"):
        assert (
            f'case "{t}"' not in block
        ), f"clean/structural treatment {t!r} must fall through to null, not grade"
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
    return {name: float(val) for name, val in re.findall(r"(\w+)\(([\d.]+)\)", css)}


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
            assert tsx.get(func) == pytest.approx(
                still[func]
            ), f"{treatment}.{func}: motion {tsx.get(func)} != still {still[func]}"


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
    assert (
        "grade ? { filter: grade }" in img
    ), f"{component} must apply the grade on its own <img> element"


# ---------------------------------------------------------------------------
# blur-family — the develop-in focus blur enriched from the single isotropic
# gaussian into a deterministic {directional, radial, lens} family. motion.py
# picks the family (pure fn of seed + mood); photo_filters.tsx re-emits the
# animated SVG <filter> each frame and resolves it to a no-op on the held frame.
# ---------------------------------------------------------------------------

FOCUS_STYLES = ("directional", "radial", "lens")


def _brief(treatment="vignette", *, mood="", layout_template="", decoration_strength=0.5):
    b = generate(
        {
            "id": "pf-1",
            "post_angle": "confirmed_official_pb",
            "achievement": _card(1)["achievement"],
        },
        None,
        BRAND,
        profile_id="pf-parity",
    ).to_dict()
    b["photo_treatment"] = treatment
    b["mood"] = mood
    b["decoration_strength"] = decoration_strength
    if layout_template:
        b["layout_template"] = layout_template
    return b


@pytest.fixture
def _photo(monkeypatch):
    """Resolve any brief to a photo card without touching the media library."""
    monkeypatch.setattr(
        motion, "_photo_data_uri_for_brief", lambda b: "data:image/jpeg;base64,AA=="
    )
    monkeypatch.setattr(motion, "_cutout_for_brief", lambda b: ("", None))


# ---- Python: motion.py gating (fold-only-when-present) --------------------


def test_focus_blur_style_attached_for_graded_photo_card(_photo):
    """A legacy-animated graded photo card (vignette here — never an exact
    mirror) gets a non-gaussian family picked from seed + mood."""
    props = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("vignette"), brand_kit=BRAND
    )
    assert props["photoSrc"]
    assert props["focusBlurStyle"] in FOCUS_STYLES


def test_focus_blur_style_absent_without_a_photo():
    """Photo-less cards never carry the prop — byte-identical prop dict."""
    props = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("vignette"), brand_kit=BRAND
    )
    assert not props.get("photoSrc")
    assert "focusBlurStyle" not in props


@pytest.mark.parametrize("treatment", ["cutout", "frame", "no-photo", ""])
def test_focus_blur_style_absent_for_clean_treatments(_photo, treatment):
    """A clean / structural treatment has no develop-in grade to enrich."""
    props = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief(treatment), brand_kit=BRAND
    )
    assert "focusBlurStyle" not in props


def test_focus_blur_style_not_stacked_on_exact_mirror(_photo):
    """A v2 exact-mirror card (halftone here → halftoneTile) keeps its held SVG
    grade; the focus-blur family must NOT stack on top of it."""
    props = motion._card_to_props(
        _card(1),
        variation_seed=1,
        brief=_brief(
            "halftone", layout_template="full_bleed_photo_lower_third", decoration_strength=0.8
        ),
        brand_kit=BRAND,
    )
    assert props.get("halftoneTile"), "expected the exact-mirror halftone tile"
    assert "focusBlurStyle" not in props


def test_focus_blur_style_is_a_pure_fn_of_seed_and_mood():
    """Same (seed, mood) → same pick; mood buckets are authoritative; the
    neutral bucket varies by seed. Never returns the absence default."""
    assert motion._focus_blur_style(7, "calm") == motion._focus_blur_style(7, "calm")
    assert motion._focus_blur_style(0, "electric triumph") == "directional"
    assert motion._focus_blur_style(999, "composed weighty") == "lens"
    # Neutral mood: the seed alone picks, so a pack of neutral cards varies.
    picks = {motion._focus_blur_style(s, "") for s in range(40)}
    assert len(picks) >= 2
    assert picks <= set(FOCUS_STYLES)
    assert "gaussian" not in picks


def test_focus_blur_folds_only_when_present(_photo):
    """The active card's cache payload changes (real pixel change); a card that
    never gains the prop hashes identically to one without the feature."""
    active = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("vignette"), brand_kit=BRAND
    )
    clean = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("cutout"), brand_kit=BRAND
    )
    assert motion._content_hash({"card": active}, kind="story") != motion._content_hash(
        {"card": clean}, kind="story"
    )
    # Removing the fold-only prop reproduces the byte-identical payload.
    stripped = {k: v for k, v in active.items() if k != "focusBlurStyle"}
    assert motion._content_hash({"card": stripped}, kind="story") == motion._content_hash(
        {"card": dict(stripped)}, kind="story"
    )


def test_manifest_axis_reports_focus_blur_style(_photo):
    active = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("vignette"), brand_kit=BRAND
    )
    assert motion._card_manifest_axes(active)["focus_blur_style"] in FOCUS_STYLES
    plain = motion._card_to_props(
        _card(1), variation_seed=1, brief=_brief("cutout"), brand_kit=BRAND
    )
    assert motion._card_manifest_axes(plain)["focus_blur_style"] == "gaussian"


# ---- TSX source-contract: the animated SVG family + wiring ----------------


def test_default_grade_tail_is_byte_identical():
    """When no family is active, photoGradeFilterFor still composes today's
    exact `... blur(px)` string (cssFilter), so ungraded cards are unchanged."""
    src = _src()
    grade_fn = src.split("export function photoGradeFilterFor", 1)[1].split("\n}", 1)[0]
    # The default path returns cssFilter(developed, blurPx); the family path is
    # the ONLY branch that swaps the blur() tail for the url() filter.
    assert "return cssFilter(developed, blurPx)" in grade_fn
    assert "url(#${focusBlurFilterId(card)})" in grade_fn
    # cssFilter still ends in the literal blur(px) lever (regression guard).
    css_fn = src.split("function cssFilter(", 1)[1].split("\n}", 1)[0]
    assert "blur(${blurPx.toFixed(2)}px)" in css_fn


def test_focus_blur_filter_id_is_per_style_and_seed():
    """The filter id folds BOTH the style and the seed, so two overlapping reel
    beats can never share one animated blur filter (bleed guard)."""
    src = _src()
    fn = src.split("export function focusBlurFilterId", 1)[1].split("\n}", 1)[0]
    assert "focusBlurStyle" in fn and "variationSeed" in fn
    assert "mh-focus-${style}-${seed}" in fn


def test_photo_filter_defs_emits_the_animated_family():
    """PhotoFilterDefs takes frame/fps and re-emits a frame-driven feGaussianBlur
    (directional/radial single-axis) plus a bounded feComponentTransfer highlight
    lift (lens). stdDeviation is markup, re-rendered per frame (not a CSS var)."""
    src = _src()
    assert re.search(r"PhotoFilterDefs:\s*React\.FC<\{\s*card:\s*TreatmentCard;\s*frame\?", src)
    defs = src.split("export const PhotoFilterDefs", 1)[1].split("\n};", 1)[0]
    assert "focusBlurActive(card)" in defs
    assert "focusBlurMag(frame, fps)" in defs
    assert "focusBlurPrimitives(card, mag)" in defs
    prims = src.split("function focusBlurPrimitives", 1)[1].split("\n}", 1)[0]
    # Directional / radial ride a single-axis feGaussianBlur (the reel whip idiom).
    assert prims.count("feGaussianBlur") >= 2
    assert 'edgeMode="duplicate"' in prims
    # Lens lifts highlights with a BOUNDED, frame-decaying transfer.
    assert "feComponentTransfer" in prims and "feFuncR" in prims
    assert "FOCUS_LENS_MAX_LIFT" in prims


def test_focus_blur_magnitude_resolves_to_zero_on_the_held_frame():
    """The family shares the legacy focus-in curve (FOCUS_IN_BLUR_PX → 0), so the
    held frame is a filter no-op and still<->motion parity is preserved."""
    src = _src()
    mag = src.split("function focusBlurMag", 1)[1].split("\n}", 1)[0]
    assert re.search(r"\[\s*FOCUS_IN_BLUR_PX\s*,\s*0\s*\]", mag)


def test_focus_blur_is_frame_pure():
    """No randomness/wall-clock in the family — the style rides a prop, the axis
    an integer seed hash, the magnitude interpolate(frame)."""
    src = _src()
    fam = src.split("const FOCUS_BLUR_STYLES", 1)[1].split("export const PhotoFilterDefs", 1)[0]
    assert "Math.random(" not in fam
    assert "Date.now(" not in fam and "new Date(" not in fam
    assert "focusSeedFrac" in fam


@pytest.mark.parametrize(
    "path",
    [
        "StoryCard.tsx",
        "sprint/sceneKit.tsx",
        "sprint/layers/cutout.tsx",
        "sprint/scenes/poster_name_behind.tsx",
    ],
)
def test_all_paint_sites_thread_frame_into_photo_filter_defs(path):
    """All four PhotoFilterDefs mount sites pass frame/fps so the animated blur
    filter can re-render each frame (the feasibility fix)."""
    src = (motion.REMOTION_DIR / "src" / "compositions" / path).read_text()
    assert "<PhotoFilterDefs card={card} frame={frame} fps={fps} />" in src
