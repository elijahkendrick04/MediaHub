"""Stage J1 — the MEDIAHUB_ADAPTIVE_THEME feature-flag contract."""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    """Clean Flask app + isolated DATA_DIR + reloaded modules.

    Reload is critical because ``_default_theme_json_cached`` is
    module-level ``lru_cache``d — without a reload between tests
    the J2 cache would leak the previous test's DATA_DIR value.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR",
                        str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    from mediahub.theming.theme_store import _read_cached
    importlib.reload(cp)
    importlib.reload(wm)
    _read_cached.cache_clear()
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm


class TestFlagDefault:
    def test_unset_is_enabled(self, fresh_app, monkeypatch):
        _app, wm = fresh_app
        monkeypatch.delenv("MEDIAHUB_ADAPTIVE_THEME", raising=False)
        assert wm._adaptive_theme_enabled() is True

    def test_explicit_one_is_enabled(self, fresh_app, monkeypatch):
        _app, wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "1")
        assert wm._adaptive_theme_enabled() is True

    def test_arbitrary_truthy_value(self, fresh_app, monkeypatch):
        _app, wm = fresh_app
        # Anything not in the off-list is treated as enabled.
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "yes")
        assert wm._adaptive_theme_enabled() is True


class TestFlagDisabled:
    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "off", "OFF",
                                        "no", "NO"])
    def test_off_values(self, fresh_app, monkeypatch, value):
        _app, wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", value)
        assert wm._adaptive_theme_enabled() is False

    def test_whitespace_stripped(self, fresh_app, monkeypatch):
        _app, wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "  0  ")
        assert wm._adaptive_theme_enabled() is False


class TestSeedBlockRespectsFlag:
    """The seed block is the visible-cascade lever the flag controls."""

    def test_seed_block_present_when_enabled(self, fresh_app, monkeypatch):
        app, _wm = fresh_app
        monkeypatch.delenv("MEDIAHUB_ADAPTIVE_THEME", raising=False)
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert 'id="mh-theme-seed"' in body, (
            "seed override missing when flag enabled (default)"
        )

    def test_seed_block_absent_when_disabled(self, fresh_app, monkeypatch):
        app, _wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert 'id="mh-theme-seed"' not in body, (
            "seed override leaked when flag disabled (rollback broken)"
        )


class TestAuditPanelIndependentOfFlag:
    """Stage H audit panel + Stage G theme-store are independent
    of the visible-cascade flag — they always work."""

    def test_audit_panel_renders_when_flag_off(self, fresh_app, monkeypatch):
        app, _wm = fresh_app
        from mediahub.web.club_profile import ClubProfile, save_profile
        prof = ClubProfile(profile_id="flag-off-audit", display_name="X")
        prof.brand_primary = "#06D6A0"
        prof.brand_voice_summary = "Energetic"
        prof.brand_keywords = ["test"]
        prof.brand_palette_extracted = {"primary": "#06D6A0"}
        prof.brand_kit = {"profile_id": "flag-off-audit",
                          "display_name": "X", "primary_colour": "#06D6A0"}
        save_profile(prof)

        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "flag-off-audit"
            body = c.get("/organisation/setup").get_data(as_text=True)
        # Audit panel still renders even with flag off.
        assert "Why does my theme look like this?" in body
        # But the inline seed override is suppressed.
        assert 'id="mh-theme-seed"' not in body

    def test_theme_store_writes_when_flag_off(self, fresh_app, monkeypatch,
                                                tmp_path):
        """ensure_derived_palette() writes to disk regardless of the
        visible-cascade flag — the theme store is independent."""
        _app, _wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        from mediahub.brand.kit import BrandKit
        from mediahub.theming.theme_store import theme_path
        BrandKit(profile_id="flag-off-store", display_name="X",
                  primary_colour="#06D6A0").ensure_derived_palette()
        # Disk file exists even with flag off — Stage G is unaffected.
        assert theme_path("flag-off-store").is_file()
