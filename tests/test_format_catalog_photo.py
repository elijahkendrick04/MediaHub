"""The 1.3 photo-editor formats registered in the catalogue (collages + avatars)."""
from __future__ import annotations

from mediahub.club_platform import format_catalog as fc


def test_collage_formats_present():
    slugs = {f.slug for f in fc.formats_in_category("collage")}
    assert {"collage_square", "collage_portrait", "collage_story"} <= slugs
    sq = fc.format_for("collage_square")
    assert sq.size == (1080, 1080) and sq.aspect == "square"
    assert fc.format_for("collage_portrait").size == (1080, 1350)
    assert fc.format_for("collage_story").size == (1080, 1920)


def test_profile_format_present():
    av = fc.format_for("profile_avatar")
    assert av is not None
    assert av.category == "profile"
    assert av.size == (512, 512)
    assert av.orientation == "square"


def test_new_categories_surface_in_catalogue():
    cats = fc.categories()
    assert "collage" in cats and "profile" in cats
