"""P6.1 — the smart format catalogue (club_platform/format_catalog.py).

Pins the catalogue's invariants: canonical slugs, sane sizes, aspect parity
with the renderer, per-sport availability sourced from the sport profile, and
the custom-size escape hatch's unit maths + bounds.
"""

from __future__ import annotations

import pytest

from mediahub.club_platform import format_catalog as fc
from mediahub.club_platform.post_types import canonical_slug
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer.render import _format_aspect
from mediahub.sport_profiles.schema import SportProfile


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_catalog_is_non_empty_and_covers_social_and_offfeed():
    cats = {f.category for f in fc.all_formats()}
    assert "social_size" in cats
    # at least one genuinely off-feed club format ships
    assert cats & {"poster", "certificate", "card", "document", "calendar", "wallpaper"}


def test_every_slug_is_unique_and_canonical():
    seen = set()
    for f in fc.all_formats():
        assert f.slug == canonical_slug(f.slug), f.slug
        assert f.slug not in seen, f"duplicate slug {f.slug}"
        seen.add(f.slug)


def test_every_format_has_sane_fields():
    for f in fc.all_formats():
        assert f.width > 0 and f.height > 0, f.slug
        assert f.category in fc.CATEGORIES, (f.slug, f.category)
        assert f.render_name, f.slug
        assert f.aspect in fc.ASPECT_CLASSES, (f.slug, f.aspect)
        assert f.orientation in ("portrait", "square", "landscape")
        d = f.to_dict()
        assert d["slug"] == f.slug and d["width"] == f.width and d["aspect"] == f.aspect
        assert set(d["safe"]) == {"top", "bottom", "left", "right"}


def test_safe_zones_exposed_for_declaring_formats():
    # The story format declares vertical safe margins (UI chrome zones); they
    # ride the API contract so a client can draw safe-zone guides.
    story = fc.format_for("ig_story")
    assert story.to_dict()["safe"]["top"] > 0 and story.to_dict()["safe"]["bottom"] > 0
    # YouTube banner declares all four (its central safe area).
    yt = fc.format_for("youtube_banner")
    safe = yt.to_dict()["safe"]
    assert all(safe[k] > 0 for k in ("top", "bottom", "left", "right"))


def test_format_for_and_is_known_round_trip():
    for f in fc.all_formats():
        assert fc.format_for(f.slug) is f
        assert fc.is_known(f.slug)
    # canonicalisation is applied on lookup
    assert fc.format_for(" IG-Story ") is fc.format_for("ig_story")
    assert fc.format_for("does_not_exist") is None
    assert not fc.is_known("does_not_exist")


def test_categories_only_lists_present_ones_in_order():
    cats = fc.categories()
    present = {f.category for f in fc.all_formats()}
    assert set(cats) == present
    # order follows the canonical CATEGORIES order
    assert list(cats) == [c for c in fc.CATEGORIES if c in present]


def test_formats_in_category_partitions_the_catalog():
    total = sum(len(fc.formats_in_category(c)) for c in fc.categories())
    assert total == len(fc.all_formats())


# ---------------------------------------------------------------------------
# Aspect parity with the renderer — must never drift
# ---------------------------------------------------------------------------


def test_aspect_class_matches_renderer_for_every_format():
    for f in fc.all_formats():
        assert fc.aspect_class(f.width, f.height) == _format_aspect(f.width, f.height), f.slug


@pytest.mark.parametrize(
    "w,h",
    [(1080, 1080), (1080, 1350), (1080, 1920), (1920, 1080), (1620, 1080), (1440, 1080),
     (1500, 500), (1280, 720), (1000, 1500), (1640, 624)],
)
def test_aspect_class_matches_renderer_for_synthetic_sizes(w, h):
    assert fc.aspect_class(w, h) == _format_aspect(w, h)


def test_aspect_rejects_non_positive():
    with pytest.raises(ValueError):
        fc.aspect_class(0, 100)


# ---------------------------------------------------------------------------
# Archetypes — every preferred archetype must exist in the live library
# ---------------------------------------------------------------------------


def test_preferred_archetypes_all_exist_in_live_library():
    live = set(A.list_archetypes())
    for f in fc.all_formats():
        for a in fc.preferred_archetypes(f):
            assert a in live, (f.slug, a)


def test_bucket_default_archetypes_all_exist():
    live = set(A.list_archetypes())
    for bucket, arts in fc.ARCHETYPES_BY_BUCKET.items():
        for a in arts:
            assert a in live, (bucket, a)


def test_every_format_has_a_live_preferred_archetype():
    live = list(A.list_archetypes())
    for f in fc.all_formats():
        assert fc.preferred_archetypes(f, available=live), f.slug


# ---------------------------------------------------------------------------
# Per-channel social presets — sizes a club would expect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,w,h",
    [
        ("ig_post", 1080, 1350),
        ("ig_square", 1080, 1080),
        ("ig_story", 1080, 1920),
        ("x_header", 1500, 500),
        ("youtube_thumbnail", 1280, 720),
        ("pinterest_pin", 1000, 1500),
        ("linkedin_banner", 1584, 396),
    ],
)
def test_social_presets_have_expected_dimensions(slug, w, h):
    spec = fc.format_for(slug)
    assert spec is not None and spec.size == (w, h)


def test_social_formats_carry_a_caption_style():
    for f in fc.formats_in_category("social_size"):
        assert f.caption_style, f.slug


# ---------------------------------------------------------------------------
# Per-sport availability — sourced from the sport profile
# ---------------------------------------------------------------------------


def _profile(post_types: dict) -> SportProfile:
    return SportProfile.from_dict(
        {"sport": "demo", "display_name": "Demo", "post_types": post_types}
    )


def test_universal_formats_available_to_every_sport_and_to_none():
    universal = {f.slug for f in fc.all_formats() if not f.requires_post_types and not f.sports}
    none_slugs = {f.slug for f in fc.formats_for_sport(None)}
    assert universal and universal <= none_slugs


def test_data_gated_formats_excluded_without_the_post_type():
    # A profile that only does free_text gets no certificate / one-pager / calendar.
    prof = _profile({"free_text": {"enabled": True}})
    slugs = {f.slug for f in fc.formats_for_sport(prof)}
    assert "certificate" not in slugs
    assert "athlete_one_pager" not in slugs
    assert "season_calendar" not in slugs
    # but it still gets the universal social sizes
    assert "ig_story" in slugs


def test_achievement_formats_appear_with_an_achievement_post_type():
    prof = _profile({"pb_spotlight": {"enabled": True}})
    slugs = {f.slug for f in fc.formats_for_sport(prof)}
    assert "certificate" in slugs
    assert "athlete_one_pager" in slugs


def test_calendar_needs_fixtures():
    no_fix = _profile({"pb_spotlight": {"enabled": True}})
    with_fix = _profile({"fixture_announcement": {"enabled": True}})
    assert "season_calendar" not in {f.slug for f in fc.formats_for_sport(no_fix)}
    assert "season_calendar" in {f.slug for f in fc.formats_for_sport(with_fix)}


def test_disabled_post_type_does_not_count():
    prof = _profile({"pb_spotlight": {"enabled": False}})
    assert "certificate" not in {f.slug for f in fc.formats_for_sport(prof)}


def test_shipped_sports_get_the_data_gated_formats():
    # swimming + football both enable achievement + fixture post types.
    for sport in ("swimming", "football"):
        slugs = {f.slug for f in fc.formats_for_sport(sport)}
        assert {"certificate", "athlete_one_pager", "season_calendar"} <= slugs


# ---------------------------------------------------------------------------
# Custom-size escape hatch
# ---------------------------------------------------------------------------


def test_custom_format_px_is_verbatim():
    spec = fc.custom_format(1234, 567, slug="my_size", title="Mine")
    assert spec.size == (1234, 567)
    assert spec.custom is True
    assert spec.slug == "my_size"
    assert spec.dpi == 0  # px carries no print intent


@pytest.mark.parametrize(
    "w,h,unit,dpi,expect",
    [
        (5, 7, "in", 300, (1500, 2100)),
        (210, 297, "mm", 150, (1240, 1754)),  # A4 @150dpi
        (21.0, 29.7, "cm", 100, (827, 1169)),
    ],
)
def test_custom_format_unit_conversion(w, h, unit, dpi, expect):
    spec = fc.custom_format(w, h, unit=unit, dpi=dpi)
    assert spec.size == expect
    assert spec.dpi == dpi
    assert spec.is_print is True


def test_custom_format_rejects_out_of_range():
    with pytest.raises(ValueError):
        fc.custom_format(50, 50)  # below min
    with pytest.raises(ValueError):
        fc.custom_format(50000, 50000)  # above max


def test_custom_format_rejects_bad_unit_and_non_positive():
    with pytest.raises(ValueError):
        fc.custom_format(100, 100, unit="furlong")
    with pytest.raises(ValueError):
        fc.custom_format(-5, 100)


def test_custom_format_canonicalises_slug():
    spec = fc.custom_format(1080, 1080, slug="My Custom")
    assert spec.slug == "my_custom"


# ---------------------------------------------------------------------------
# orientation helper
# ---------------------------------------------------------------------------


def test_orientation_of():
    assert fc.orientation_of(1080, 1080) == "square"
    assert fc.orientation_of(1080, 1920) == "portrait"
    assert fc.orientation_of(1920, 1080) == "landscape"
