"""Tests for the motion-graphic / short-form video output pipeline.

The Remotion pipeline depends on Node 18+ and a local ``npm install`` inside
``src/mediahub/remotion``. Tests that exercise real renders are gated on
``MEDIAHUB_RUN_MOTION_TESTS=1`` so CI doesn't have to ship Node binaries by
default; the pure-Python shaping helpers are still tested unconditionally
because they don't touch Node.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion


# ---------------------------------------------------------------------------
# Pure Python helpers — always exercised so the shaping logic is covered even
# when Node isn't installed.
# ---------------------------------------------------------------------------

def test_brand_to_dict_from_dataclass():
    bk = BrandKit(profile_id="club", display_name="Test SC",
                  primary_colour="#112233", secondary_colour="#445566",
                  accent_colour="#778899", short_name="TSC")
    out = motion._brand_to_dict(bk)
    assert out["primary"] == "#112233"
    assert out["secondary"] == "#445566"
    assert out["accent"] == "#778899"
    assert out["displayName"] == "Test SC"
    assert out["shortName"] == "TSC"


def test_brand_to_dict_from_plain_dict():
    out = motion._brand_to_dict({
        "primary_colour": "#aabbcc",
        "secondary_colour": "#001122",
        "display_name": "Direct Club",
    })
    assert out["primary"] == "#aabbcc"
    assert out["secondary"] == "#001122"
    assert out["displayName"] == "Direct Club"
    # No accent provided → falls back to white.
    assert out["accent"] == "#FFFFFF"


def test_brand_to_dict_handles_none():
    out = motion._brand_to_dict(None)
    assert set(out.keys()) >= {
        "primary", "secondary", "accent", "displayName", "shortName", "logoDataUri",
    }
    assert out["logoDataUri"] == ""


def test_logo_to_data_uri_encodes_inline_svg():
    svg = "<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"
    uri = motion._logo_to_data_uri(svg)
    assert uri.startswith("data:image/svg+xml;base64,")
    # Round-trip base64 to confirm the SVG payload survives intact.
    import base64
    payload = base64.b64decode(uri.split(",", 1)[1]).decode("utf-8")
    assert payload == svg


def test_logo_to_data_uri_rejects_non_svg():
    assert motion._logo_to_data_uri(None) == ""
    assert motion._logo_to_data_uri("") == ""
    assert motion._logo_to_data_uri("not svg markup") == ""
    # Tolerate leading whitespace.
    assert motion._logo_to_data_uri("\n  <svg/>").startswith("data:image/svg+xml;base64,")


def test_brand_to_dict_threads_logo_through():
    from mediahub.brand.kit import BrandKit
    svg = "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='40'/></svg>"
    bk = BrandKit(profile_id="x", display_name="With Logo", logo_svg=svg)
    out = motion._brand_to_dict(bk)
    assert out["logoDataUri"].startswith("data:image/svg+xml;base64,")
    # Plain-dict input with the same field name works too.
    out2 = motion._brand_to_dict({"logo_svg": svg, "display_name": "Dict"})
    assert out2["logoDataUri"] == out["logoDataUri"]


def test_card_to_props_pulls_from_achievement():
    card = {
        "id": "swim_1",
        "achievement": {
            "swimmer_name": "Alice Example",
            "event_name": "200m IM LC",
            "result_time": "02:14.55",
            "place": "1",
            "type": "NEW PB",
        },
    }
    props = motion._card_to_props(card, variation_seed=42)
    assert props["athleteFullName"] == "Alice Example"
    assert props["athleteFirstName"] == "Alice"
    assert props["athleteSurname"] == "Example"
    assert props["eventName"] == "200m IM LC"
    assert props["resultValue"] == "02:14.55"
    assert props["place"] == "1"
    assert props["achievementLabel"] == "NEW PB"
    assert props["variationSeed"] == 42


def test_card_to_props_prefers_text_layers_when_present():
    card = {
        "text_layers": {
            "athlete_full_name": "Override Name",
            "athlete_first_name": "Override",
            "athlete_surname": "Name",
            "event_name": "50m Free SC",
            "result_value": "00:23.10",
            "achievement_label": "Likely PB",
            "meet_name": "Override Meet",
        },
        "achievement": {"swimmer_name": "Ignored", "event_name": "Ignored"},
    }
    props = motion._card_to_props(card)
    assert props["athleteFullName"] == "Override Name"
    assert props["eventName"] == "50m Free SC"
    assert props["meetName"] == "Override Meet"
    assert props["achievementLabel"] == "LIKELY PB"


def test_card_to_props_forwards_brief_variation_axes():
    """When a CreativeBrief dict is passed, the AI-directed variation
    axes (background_style, typography_pair, composition, accent_style,
    mood, photo_treatment) must flow through to the Remotion props so
    the TSX composition can vary fonts, layout, animation spring, and
    background pattern per card."""
    card = {"achievement": {"swimmer_name": "Sample Person", "event_name": "200m IM"}}
    brief = {
        "background_style": "dots",
        "typography_pair": "anton-inter",
        "composition": "right",
        "accent_style": "brackets",
        "mood": "electric, precise",
        "photo_treatment": "cutout",
    }
    props = motion._card_to_props(card, variation_seed=2, brief=brief)
    assert props["backgroundStyle"] == "dots"
    assert props["typographyPair"] == "anton-inter"
    assert props["composition"] == "right"
    assert props["accentStyle"] == "brackets"
    assert props["mood"] == "electric, precise"
    assert props["photoTreatment"] == "cutout"
    assert props["variationSeed"] == 2


def test_card_to_props_without_brief_keeps_axes_empty():
    """Legacy callers that don't supply a brief get empty axis strings
    so the TSX composition falls back to its variationSeed-only path."""
    card = {"achievement": {"swimmer_name": "Sample Person"}}
    props = motion._card_to_props(card, variation_seed=1)
    for k in ("backgroundStyle", "typographyPair", "composition",
              "accentStyle", "mood", "photoTreatment"):
        assert props[k] == ""


def test_content_hash_is_stable_and_kind_sensitive():
    payload = {"a": 1, "b": [1, 2, 3], "c": {"x": "y"}}
    h1 = motion._content_hash(payload, kind="story")
    h2 = motion._content_hash(payload, kind="story")
    h3 = motion._content_hash(payload, kind="reel")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 24


def test_remotion_dir_layout_present():
    """Sanity-check the Remotion project files exist on disk."""
    assert (motion.REMOTION_DIR / "package.json").exists()
    assert (motion.REMOTION_DIR / "render.js").exists()
    assert (motion.REMOTION_DIR / "src" / "Root.tsx").exists()
    assert (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").exists()
    assert (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").exists()


def test_render_story_card_returns_cached_file_when_present(tmp_path, monkeypatch):
    """If the cache already holds an MP4, render should reuse it without
    invoking Node — useful sanity check for the cache-hit path."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cache_dir = tmp_path / "motion_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    fake_mp4_bytes = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096

    # Pre-seed the cache with a hash that matches what render_story_card will
    # compute for this input.
    card = {"id": "c1", "achievement": {"swimmer_name": "Cache Hit",
                                          "event_name": "100m Free LC",
                                          "result_time": "00:50.00"}}
    brand = BrandKit(profile_id="x", display_name="Cache Club")
    brand_dict = motion._brand_to_dict(brand)
    card_dict = motion._card_to_props(card, variation_seed=7)
    cache_key = motion._content_hash(
        {"card": card_dict, "brand": brand_dict, "duration": 6.0,
         "size": [1080, 1920], "rev": motion.STORY_COMPOSITION_REVISION},
        kind="story",
    )
    (cache_dir / f"{cache_key}.mp4").write_bytes(fake_mp4_bytes)

    out = tmp_path / "out.mp4"
    result = motion.render_story_card(card, brand, out, variation_seed=7)
    assert Path(result).exists()
    assert Path(result).stat().st_size == len(fake_mp4_bytes)


# ---------------------------------------------------------------------------
# Integration: actually shell out to Node + Remotion. Skipped unless Node is
# present AND ``MEDIAHUB_RUN_MOTION_TESTS=1``. Even with Node available we
# don't want to add 60s to the suite by default.
# ---------------------------------------------------------------------------

def _node_present() -> bool:
    return shutil.which("node") is not None


def _remotion_installed() -> bool:
    return (motion.REMOTION_DIR / "node_modules" / "remotion").exists()


# Integration test runs by default now (Phase 1.5 no-skips directive).
# Override with MEDIAHUB_SKIP_MOTION_TESTS=1 if you need to run the suite
# in a Node-less environment temporarily. The Dockerfile always installs
# Remotion's node_modules so the production image satisfies this.
_SKIP_INTEGRATION = (
    os.environ.get("MEDIAHUB_SKIP_MOTION_TESTS", "").lower() in ("1", "true", "yes")
)


@pytest.mark.skipif(_SKIP_INTEGRATION, reason="MEDIAHUB_SKIP_MOTION_TESTS set")
@pytest.mark.skipif(not _node_present(), reason="node not installed")
@pytest.mark.skipif(
    not _remotion_installed(),
    reason="Remotion deps not installed (run `npm install` in src/mediahub/remotion)",
)
def test_render_story_card_produces_valid_mp4(tmp_path, monkeypatch):
    """End-to-end: 1-second render should produce a real, non-empty MP4."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    card = {
        "id": "smoke",
        "achievement": {
            "swimmer_name": "Test Swimmer",
            "event_name": "100m Free LC",
            "result_time": "00:54.32",
            "type": "NEW PB",
        },
    }
    brand = BrandKit(profile_id="t", display_name="Smoke Club",
                     primary_colour="#0A2540", secondary_colour="#000000",
                     accent_colour="#FFFFFF", short_name="SC")
    out = tmp_path / "story.mp4"
    result = motion.render_story_card(card, brand, out, duration_sec=1.0,
                                       variation_seed=1)
    assert Path(result).exists()
    size = Path(result).stat().st_size
    assert size > 4096, f"MP4 unexpectedly small: {size} bytes"
    # Smoke check on container: MP4 files start with an ``ftyp`` box.
    head = Path(result).read_bytes()[:12]
    assert b"ftyp" in head, "Output does not look like an MP4"


# ---------------------------------------------------------------------------
# Render-diff regression — guards against silent flattening of the variation
# vocabulary. If a future TSX refactor stops consuming an axis (e.g. someone
# removes the typographyPair branch in fontStackFor), the static graphic
# would still vary but motion would silently revert to "everything looks
# the same again". These tests catch that by:
#
#   1. _BRIEF_VARIANTS gives N briefs that differ on every axis the
#      composition consumes (background_style, typography_pair, composition,
#      accent_style, mood, photo_treatment).
#   2. The fast layer asserts that each variant produces a unique cache key
#      — proves Python props differ. Runs in CI without Node.
#   3. The slow layer renders one MP4 per variant and asserts every output
#      file is byte-distinct from the others — proves the TSX composition
#      actually consumes the axes. Opt-in via MEDIAHUB_RUN_DIFF_REGRESSION=1
#      since it adds ~30-60s per variant on first run.
# ---------------------------------------------------------------------------

_BRIEF_VARIANTS: list[dict] = [
    {
        "background_style": "dots",
        "typography_pair": "anton-inter",
        "composition": "left",
        "accent_style": "brackets",
        "mood": "electric, precise",
        "photo_treatment": "cutout",
    },
    {
        "background_style": "diagonal",
        "typography_pair": "bowlby-inter",
        "composition": "right",
        "accent_style": "stripe",
        "mood": "calm, weighty",
        "photo_treatment": "duotone",
    },
    {
        "background_style": "halftone",
        "typography_pair": "archivo-inter",
        "composition": "center",
        "accent_style": "ribbon",
        "mood": "celebratory, bold",
        "photo_treatment": "frame",
    },
    {
        "background_style": "geometric",
        "typography_pair": "bebas-grotesk",
        "composition": "off-center",
        "accent_style": "badge",
        "mood": "kinetic",
        "photo_treatment": "vignette",
    },
    {
        "background_style": "stripes",
        "typography_pair": "druk-inter",
        "composition": "left",
        "accent_style": "underline",
        "mood": "composed",
        "photo_treatment": "no-photo",
    },
]


def _shared_test_card() -> dict:
    """Same achievement across variants — only the brief axes change so
    the only legitimate cause of cache-key divergence is the axis
    plumbing actually working."""
    return {
        "id": "diff_regression",
        "achievement": {
            "swimmer_name": "Diff Regression",
            "event_name": "100m Freestyle LC",
            "result_time": "00:54.32",
            "type": "NEW PB",
        },
    }


def _shared_brand() -> BrandKit:
    return BrandKit(
        profile_id="diff-club", display_name="Diff Test Club",
        primary_colour="#0A2540", secondary_colour="#FF6F61",
        accent_colour="#FFFFFF", short_name="DTC",
    )


def test_render_diff_brief_variants_produce_unique_cache_keys():
    """Fast layer of the render-diff regression.

    Each brief variant must produce a distinct content hash so the cache
    layer renders (and stores) a separate MP4 per variant. If two
    variants collide here, the props shaping is dropping an axis on the
    floor — TSX never even gets to consume it.
    """
    card = _shared_test_card()
    brand_dict = motion._brand_to_dict(_shared_brand())
    keys: list[str] = []
    for brief in _BRIEF_VARIANTS:
        card_dict = motion._card_to_props(
            card, variation_seed=2, brief=brief,
        )
        key = motion._content_hash(
            {"card": card_dict, "brand": brand_dict, "duration": 1.0},
            kind="story",
        )
        keys.append(key)
    assert len(set(keys)) == len(keys), (
        f"Cache keys collided across variants — at least one variation "
        f"axis is not flowing into the Remotion props. keys={keys}"
    )


_SKIP_DIFF_REGRESSION = (
    os.environ.get("MEDIAHUB_RUN_DIFF_REGRESSION", "").lower()
    not in ("1", "true", "yes")
)


@pytest.mark.skipif(
    _SKIP_DIFF_REGRESSION,
    reason="set MEDIAHUB_RUN_DIFF_REGRESSION=1 to run the slow render-diff",
)
@pytest.mark.skipif(not _node_present(), reason="node not installed")
@pytest.mark.skipif(
    not _remotion_installed(),
    reason="Remotion deps not installed (run `npm install` in src/mediahub/remotion)",
)
def test_render_diff_brief_variants_produce_distinct_mp4s(tmp_path, monkeypatch):
    """Slow layer of the render-diff regression.

    Renders one MP4 per brief variant and asserts every pair is
    byte-distinct. Identical bytes would mean the TSX composition isn't
    actually consuming the axis (e.g. backgroundStyle accepted by the
    schema but never read). Each render is held to 1.0s of video so the
    full sweep takes ~30-60s on a Standard Render box.
    """
    import hashlib
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    card = _shared_test_card()
    brand = _shared_brand()
    digests: list[tuple[int, str]] = []
    for idx, brief in enumerate(_BRIEF_VARIANTS):
        out = tmp_path / f"variant_{idx}.mp4"
        result = motion.render_story_card(
            card, brand, out,
            variation_seed=2,
            duration_sec=1.0,
            brief=brief,
        )
        data = Path(result).read_bytes()
        assert b"ftyp" in data[:32], f"variant {idx} not a valid MP4"
        digests.append((idx, hashlib.sha256(data).hexdigest()))
    seen: dict[str, int] = {}
    for idx, digest in digests:
        if digest in seen:
            prior = seen[digest]
            raise AssertionError(
                f"variant {idx} produced the same bytes as variant "
                f"{prior} — the TSX composition is ignoring at least "
                f"one of: {sorted(set(_BRIEF_VARIANTS[idx]) - set())}. "
                f"Check StoryCard.tsx helpers (bgPatternFor / "
                f"fontStackFor / springConfigFor / "
                f"compositionLayoutFor / accentDecoration)."
            )
        seen[digest] = idx
