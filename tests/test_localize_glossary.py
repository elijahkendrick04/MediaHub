"""localize.glossary — per-sport protected vocabulary + the deterministic
post-check that the AI respected it.
"""

from __future__ import annotations

from mediahub.localize import glossary as G


class TestSwimmingGlossary:
    def test_registered_under_swimming(self):
        assert G.glossary_for("swimming") is G.SWIMMING_GLOSSARY
        assert G.glossary_for("SWIMMING") is G.SWIMMING_GLOSSARY  # case-insensitive
        assert G.glossary_for("curling") == ()
        assert G.glossary_for(None) == ()

    def test_codes_are_keep_verbatim(self):
        keep = {t.canonical for t in G.SWIMMING_GLOSSARY if t.keep_verbatim}
        for code in ("PB", "DQ", "IM", "SB", "WR", "CR", "NR", "LC", "SC", "DNF", "DNS", "NT"):
            assert code in keep, f"{code} should be keep-verbatim"

    def test_verified_welsh_terms(self):
        by_canon = {t.canonical: t for t in G.SWIMMING_GLOSSARY}
        assert by_canon["freestyle"].translations["cy"] == "dull rhydd"
        assert by_canon["backstroke"].translations["cy"] == "dull cefn"
        assert by_canon["breaststroke"].translations["cy"] == "dull broga"
        assert by_canon["butterfly"].translations["cy"] == "dull pili-pala"
        assert by_canon["personal best"].translations["cy"] == "record personol"

    def test_no_unverified_translations_baked(self):
        # We only ever bake VERIFIED translations. Today that's Welsh only; this
        # guard makes an accidental unverified term (e.g. a guessed French one)
        # an explicit decision rather than a silent slip.
        for t in G.SWIMMING_GLOSSARY:
            assert set(t.translations).issubset({"cy"}), (
                f"{t.canonical} has translations for unverified languages: "
                f"{set(t.translations) - {'cy'}}"
            )


class TestProtectedTerms:
    def test_includes_codes(self):
        terms = G.protected_terms("swimming")
        assert "PB" in terms and "DQ" in terms and "IM" in terms

    def test_longest_first(self):
        terms = G.protected_terms("swimming")
        lengths = [len(t) for t in terms]
        assert lengths == sorted(lengths, reverse=True)

    def test_unknown_sport_empty(self):
        assert G.protected_terms("curling") == []


class TestGlossaryPrompt:
    def test_welsh_prompt_names_verified_terms_and_codes(self):
        p = G.glossary_prompt("swimming", "cy")
        assert p  # non-empty
        assert "record personol" in p
        assert "dull rhydd" in p
        assert "PB" in p and "DQ" in p

    def test_french_prompt_has_codes_but_no_welsh(self):
        p = G.glossary_prompt("swimming", "fr")
        assert "PB" in p
        # No baked French terms, so the Welsh forms must not leak in.
        assert "dull rhydd" not in p
        assert "record personol" not in p

    def test_region_subtag_tolerated(self):
        assert "record personol" in G.glossary_prompt("swimming", "cy-GB")

    def test_unknown_sport_is_empty(self):
        assert G.glossary_prompt("curling", "cy") == ""


class TestCheckProtected:
    def test_flags_dropped_code(self):
        warns = G.check_protected("swimming", "New PB for Hannah!", "Camp newydd i Hannah!")
        assert len(warns) == 1
        assert "PB" in warns[0]

    def test_passes_when_code_survives(self):
        warns = G.check_protected("swimming", "New PB!", "PB newydd!")
        assert warns == []

    def test_case_insensitive_presence(self):
        # Source has DQ; translation keeps it (any case) → no warning.
        assert G.check_protected("swimming", "Sadly a DQ", "Yn anffodus, dq") == []

    def test_whole_token_only(self):
        # "PB" inside another word doesn't count as the protected code present.
        warns = G.check_protected("swimming", "A new PB today", "Diwrnod gwych, PBwobr")
        assert len(warns) == 1  # "PBwobr" is not the token "PB"

    def test_no_warning_when_term_absent_from_source(self):
        assert G.check_protected("swimming", "Great swim today", "Nofio gwych heddiw") == []

    def test_unknown_sport_no_warnings(self):
        assert G.check_protected("curling", "New PB!", "anything") == []
