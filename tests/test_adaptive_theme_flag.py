"""Stage J1 — the MEDIAHUB_ADAPTIVE_THEME feature-flag contract."""

from __future__ import annotations

import pytest


@pytest.fixture
def fresh_app(web_module):
    """Clean Flask app + isolated DATA_DIR via the canonical fixtures.

    ``web_module`` (through conftest's ``_isolate_data_dir``) repoints the
    shared ``web.py`` at this test's DATA_DIR and clears its per-run caches —
    including the module-level ``lru_cache``d default-theme lookup that a
    reload used to reset, so the J2 cache no longer leaks a prior test's
    DATA_DIR. ``theme_store._read_cached`` is keyed on ``(path, mtime_ns)``
    and self-clears on every write/delete, so it needs no explicit clear here.

    The ``MEDIAHUB_ADAPTIVE_THEME`` flag is read live inside
    ``_adaptive_theme_enabled()`` (never at import time), so each test flips
    it in its own body via ``monkeypatch.setenv`` before the request/call
    that reads it — monkeypatch auto-undoes it, keeping the on/off cases
    isolated without a reload.
    """
    app = web_module.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret-key"
    return app, web_module


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
    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "off", "OFF", "no", "NO"])
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
        assert 'id="mh-theme-seed"' in body, "seed override missing when flag enabled (default)"

    def test_seed_block_absent_when_disabled(self, fresh_app, monkeypatch):
        app, _wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert (
            'id="mh-theme-seed"' not in body
        ), "seed override leaked when flag disabled (rollback broken)"


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
        prof.brand_kit = {
            "profile_id": "flag-off-audit",
            "display_name": "X",
            "primary_colour": "#06D6A0",
        }
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

    def test_theme_store_writes_when_flag_off(self, fresh_app, monkeypatch, tmp_path):
        """ensure_derived_palette() writes to disk regardless of the
        visible-cascade flag — the theme store is independent."""
        _app, _wm = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        from mediahub.brand.kit import BrandKit
        from mediahub.theming.theme_store import theme_path

        BrandKit(
            profile_id="flag-off-store", display_name="X", primary_colour="#06D6A0"
        ).ensure_derived_palette()
        # Disk file exists even with flag off — Stage G is unaffected.
        assert theme_path("flag-off-store").is_file()
