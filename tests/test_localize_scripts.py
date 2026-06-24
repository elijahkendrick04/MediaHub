"""localize.scripts — writing-system / direction / font metadata.

These pin the renderer-facing facts (script, RTL, font family) and the
drift guard that keeps the table in lock-step with the caption-language
registry in web/languages.py.
"""

from __future__ import annotations

from mediahub.localize import scripts as S


class TestBaseCode:
    def test_strips_region_and_lowercases(self):
        assert S.base_code("en-GB") == "en"
        assert S.base_code("en_US") == "en"
        assert S.base_code(" CY ") == "cy"
        assert S.base_code("zh-Hans") == "zh"

    def test_empty_and_none(self):
        assert S.base_code("") == ""
        assert S.base_code(None) == ""


class TestScriptLookup:
    def test_known_scripts(self):
        assert S.script_name("en") == "latin"
        assert S.script_name("cy") == "latin"
        assert S.script_name("ru") == "cyrillic"
        assert S.script_name("zh") == "han"
        assert S.script_name("hi") == "devanagari"
        assert S.script_name("bn") == "bengali"
        assert S.script_name("ar") == "arabic"
        assert S.script_name("ur") == "arabic"

    def test_region_subtag_ignored(self):
        assert S.script_name("ar-EG") == "arabic"
        assert S.script_name("en-US") == "latin"

    def test_unknown_is_none(self):
        assert S.script_for("klingon") is None
        assert S.script_name("klingon") == ""
        assert S.font_family_for("klingon") == ""

    def test_rtl_flags(self):
        assert S.is_rtl("ar") and S.is_rtl("ur")
        assert S.is_rtl("ar-EG")
        for c in ("en", "cy", "ga", "zh", "hi", "es", "fr", "bn", "pt", "ru"):
            assert not S.is_rtl(c)

    def test_font_families(self):
        # Latin scripts reuse the layout's own (brand) stack — blank family.
        assert S.font_family_for("en") == ""
        assert S.font_family_for("cy") == ""
        # Non-Latin scripts name a self-hosted Noto family.
        assert S.font_family_for("zh") == "Noto Sans SC"
        assert S.font_family_for("ar") == "Noto Sans Arabic"
        assert S.font_family_for("hi") == "Noto Sans Devanagari"
        assert S.font_family_for("bn") == "Noto Sans Bengali"
        assert S.font_family_for("ru") == "Noto Sans"

    def test_is_non_latin(self):
        assert not S.is_non_latin("en")
        assert not S.is_non_latin("cy")
        assert S.is_non_latin("zh")
        assert S.is_non_latin("ar")
        assert S.is_non_latin("ru")

    def test_non_latin_scripts_set(self):
        assert "arabic" in S.NON_LATIN_SCRIPTS
        assert "han" in S.NON_LATIN_SCRIPTS
        assert "cyrillic" in S.NON_LATIN_SCRIPTS
        assert "latin" not in S.NON_LATIN_SCRIPTS


class TestRegistryDriftGuard:
    """Every caption language must have a script entry, and RTL must agree."""

    def test_every_caption_language_has_a_script(self):
        from mediahub.web.languages import SUPPORTED_LANGUAGES

        for lang in SUPPORTED_LANGUAGES:
            info = S.script_for(lang.code)
            assert info is not None, f"no script metadata for caption language {lang.code!r}"

    def test_rtl_flags_agree_with_caption_registry(self):
        from mediahub.web.languages import SUPPORTED_LANGUAGES

        for lang in SUPPORTED_LANGUAGES:
            assert S.is_rtl(lang.code) == lang.rtl, (
                f"RTL mismatch for {lang.code}: scripts={S.is_rtl(lang.code)} "
                f"languages={lang.rtl}"
            )

    def test_no_orphan_script_entries(self):
        # Conversely, every script entry should correspond to a caption language
        # (no stale rows).
        from mediahub.web.languages import LANGUAGES_BY_CODE

        for info in S.all_scripts():
            assert info.code in LANGUAGES_BY_CODE, f"orphan script entry {info.code!r}"
