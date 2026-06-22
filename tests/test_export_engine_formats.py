"""Tests for export_engine.formats — the format catalogue (roadmap 1.19)."""

from __future__ import annotations

import pytest

from mediahub.export_engine import formats
from mediahub.export_engine.formats import (
    CATEGORIES,
    OPTION_KEYS,
    UnknownFormatError,
    all_formats,
    formats_for_category,
    get_format,
    has_format,
    mime_for,
    normalise_key,
    suffix_for,
)


class TestLookup:
    def test_known_format(self):
        f = get_format("png")
        assert f.key == "png"
        assert f.category == "image"
        assert f.suffix == ".png"
        assert f.mime == "image/png"

    @pytest.mark.parametrize(
        "spelling,expected",
        [
            ("PNG", "png"),
            (".png", "png"),
            ("jpeg", "jpg"),
            ("JPE", "jpg"),
            ("  WebP ", "webp"),
            ("m4v", "mp4"),
            ("print", "print_pdf"),
        ],
    )
    def test_alias_and_normalisation(self, spelling, expected):
        assert normalise_key(spelling) == expected
        assert get_format(spelling).key == expected

    def test_unknown_format_raises(self):
        with pytest.raises(UnknownFormatError):
            get_format("ico")
        assert not has_format("ico")

    def test_has_format(self):
        assert has_format("gif")
        assert has_format("JPEG")
        assert not has_format("")

    def test_suffix_and_mime_helpers(self):
        assert suffix_for("docx") == ".docx"
        assert mime_for("zip") == "application/zip"


class TestCatalogue:
    def test_every_category_has_members(self):
        for cat in CATEGORIES:
            assert formats_for_category(cat), f"no formats in {cat}"

    def test_all_formats_categories_are_valid(self):
        for f in all_formats():
            assert f.category in CATEGORIES, f"{f.key} has bad category {f.category}"

    def test_accepts_only_known_option_keys(self):
        for f in all_formats():
            assert f.accepts <= set(OPTION_KEYS), f"{f.key} accepts unknown option"

    def test_suffix_starts_with_dot_and_mime_present(self):
        for f in all_formats():
            assert f.suffix.startswith("."), f"{f.key} suffix not dotted"
            assert "/" in f.mime, f"{f.key} mime malformed"

    def test_lossless_formats_do_not_take_quality(self):
        # PNG/SVG/WAV/FLAC are lossless — a quality slider would be a lie.
        for key in ("png", "svg", "wav", "flac"):
            assert "quality" not in get_format(key).accepts

    def test_lossy_formats_take_quality(self):
        for key in ("jpg", "webp", "mp3", "webm"):
            assert "quality" in get_format(key).accepts

    def test_only_transparency_capable_formats_accept_transparent(self):
        for f in all_formats():
            if "transparent" in f.accepts:
                assert f.supports_transparency, f"{f.key} accepts transparent but can't"

    def test_jpeg_cannot_be_transparent(self):
        assert not get_format("jpg").supports_transparency

    def test_expected_core_formats_present(self):
        # The headline 1.19 additions all live in the catalogue.
        for key in ("svg", "gif", "webm", "pptx", "docx", "wav", "print_pdf"):
            assert has_format(key)
