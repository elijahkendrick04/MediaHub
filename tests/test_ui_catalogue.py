"""localize.ui_catalogue — the curated UI string catalogue + t() lookup (1.24)."""

from __future__ import annotations

from mediahub.localize import ui_catalogue as UI


class TestLookup:
    def test_english_base(self):
        assert UI.t("nav.home", "en") == "Home"
        assert UI.t("action.approve", "en") == "Approve"

    def test_welsh_flagship(self):
        assert UI.t("nav.home", "cy") == "Hafan"
        # A-5: the org "sign out" is now "Leave organisation" (Gadael sefydliad),
        # kept distinct from the account log-out (Allgofnodi).
        assert UI.t("nav.sign_out", "cy") == "Gadael sefydliad"
        assert UI.t("action.approve", "cy") == "Cymeradwyo"

    def test_unknown_locale_falls_back_to_english(self):
        assert UI.t("nav.home", "fr") == "Home"
        assert UI.t("action.save", "zz") == "Save"

    def test_none_locale_is_english(self):
        assert UI.t("nav.home", None) == "Home"

    def test_region_subtag_ignored(self):
        assert UI.t("nav.home", "cy-GB") == "Hafan"

    def test_unknown_key_returns_the_key(self):
        # Visible in dev rather than crashing.
        assert UI.t("totally.missing", "cy") == "totally.missing"


class TestCatalogueIntegrity:
    def test_locales(self):
        assert UI.available_ui_locales() == ("en", "cy")
        assert UI.has_ui_locale("cy") and UI.has_ui_locale("en")
        assert not UI.has_ui_locale("fr")
        assert not UI.has_ui_locale("")

    def test_no_orphan_welsh_keys(self):
        # Every Welsh key must have an English source (English is the base).
        en_keys = set(UI.UI_STRINGS["en"])
        for key in UI.UI_STRINGS["cy"]:
            assert key in en_keys, f"cy key {key!r} has no English source"

    def test_welsh_values_are_non_empty_and_differ_from_english(self):
        for key, cy_val in UI.UI_STRINGS["cy"].items():
            assert cy_val.strip(), f"empty Welsh for {key}"
            # A real translation, not a copy of the English (sanity, not strict).
            assert cy_val != UI.UI_STRINGS["en"][key], f"{key} Welsh == English"
