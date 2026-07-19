"""Stage J2 — the generic-default theme pre-derivation.

When no club has finalised a brand kit, the unconfigured pages
should still run the full pipeline. The
``_default_theme_json()`` helper derives a theme from
``BrandKit.generic_default()``'s seeds (#0E2A47 + #C9A227) on
first call and caches the result. Subsequent calls are free.

The side-effect (Stage G's hook) is that
``DATA_DIR/themes/default.json`` exists after the first call,
making the default theme available to the motion / email /
static-graphic renderers exactly the same way real profile
themes are.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def fresh_app(app, web_module, tmp_path):
    """Clean app + web module + isolated DATA_DIR, built on the canonical
    conftest fixtures (deep-review finding #130).

    ``_isolate_data_dir`` — pulled in via ``app`` / ``web_module`` — repoints
    ``DATA_DIR`` (and the derived storage dirs) at this test's ``tmp_path`` and
    clears the module's ``_default_theme_json_cached`` lru_cache, so the reload
    the old fixture used purely to reset that cache is no longer needed. The
    theme_store read cache is keyed by the DATA_DIR-derived path (and mtime),
    but is cleared here too so a prior test's ``default`` theme can never
    satisfy a read."""
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    return app, web_module, tmp_path


class TestDefaultThemeHelper:
    def test_returns_dict(self, fresh_app):
        _app, wm, _ = fresh_app
        theme = wm._default_theme_json()
        assert isinstance(theme, dict)

    def test_seed_hex_is_generic_default(self, fresh_app):
        _app, wm, _ = fresh_app
        theme = wm._default_theme_json()
        # BrandKit.generic_default() ships primary_colour="#0E2A47"
        assert theme["seed_hex"] == "#0E2A47"

    def test_has_full_dtcg_shape(self, fresh_app):
        """The default theme is a full derived palette — every key
        a real profile's theme has."""
        _app, wm, _ = fresh_app
        theme = wm._default_theme_json()
        for key in ("schema_version", "seed_hex", "palettes", "roles",
                    "quality", "quality_detail", "harmonic_fit"):
            assert key in theme, f"default theme missing {key!r}"

    def test_cached_across_calls(self, fresh_app):
        """Repeat calls return the same dict object (lru_cache)."""
        _app, wm, _ = fresh_app
        a = wm._default_theme_json()
        b = wm._default_theme_json()
        assert a is b, "default theme not cached"


class TestDiskSideEffect:
    def test_default_json_persisted(self, fresh_app):
        _app, wm, tmp_path = fresh_app
        wm._default_theme_json()
        path = tmp_path / "themes" / "default.json"
        assert path.is_file(), (
            f"default.json not written to {path} — Stage G hook regressed"
        )

    def test_disk_content_matches_in_memory(self, fresh_app):
        _app, wm, tmp_path = fresh_app
        in_mem = wm._default_theme_json()
        path = tmp_path / "themes" / "default.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        # The seed at minimum should agree.
        assert on_disk["seed_hex"] == in_mem["seed_hex"]

    def test_consumers_can_read_default(self, fresh_app):
        """Motion / email / static helpers can pluck the default
        theme by profile_id 'default'."""
        _app, wm, _ = fresh_app
        wm._default_theme_json()   # populate disk
        from mediahub.theming.theme_store import (
            read_theme, palette_for_motion,
        )
        theme = read_theme("default")
        assert theme is not None
        # The role-mapping helper resolves cleanly.
        motion = palette_for_motion(theme)
        assert motion["scheme"] == "dark"
        assert motion["primary"].startswith("#")


class TestUnconfiguredCascade:
    """The headline J2 outcome: unconfigured /status renders with
    the generic-default override."""

    def test_override_present_on_unconfigured_status(self, fresh_app):
        app, _wm, _ = fresh_app
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        # The inline override block is present.
        assert 'id="mh-theme-seed"' in body, (
            "default-theme override missing on unconfigured /status"
        )
        # The seed is the generic-default navy.
        assert "#0E2A47" in body, (
            "expected the generic-default seed (#0E2A47) in the override"
        )

    def test_override_uses_default_when_no_profile(self, fresh_app):
        """Even without an active profile, the override block
        renders — that's the Stage J2 contract."""
        app, _wm, _ = fresh_app
        with app.test_client() as c:
            # No active *profile* — but the usage dashboard is operator-only.
            with c.session_transaction() as s:
                s["dev_operator"] = True
            body = c.get("/healthz/usage").get_data(as_text=True)
        assert 'id="mh-theme-seed"' in body

    def test_active_profile_overrides_default(self, fresh_app):
        """Stage E precedence: an active profile's seed wins over
        the J2 default."""
        app, _wm, _ = fresh_app
        from mediahub.web.club_profile import ClubProfile, save_profile
        prof = ClubProfile(profile_id="j2-active", display_name="X")
        prof.brand_primary = "#A30D2D"
        prof.brand_kit = {"profile_id": "j2-active", "display_name": "X",
                          "primary_colour": "#A30D2D"}
        save_profile(prof)
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "j2-active"
            body = c.get("/status").get_data(as_text=True)
        # The active profile's seed wins.
        assert "#A30D2D" in body
        # Generic-default does NOT appear in the override section
        # (it may appear elsewhere in palettes if cached).
        import re
        override_block = re.search(
            r'<style id="mh-theme-seed">[^<]*</style>', body,
        )
        assert override_block is not None
        assert "#0E2A47" not in override_block.group(0)
        assert "#A30D2D" in override_block.group(0)


class TestFlagOffSuppresses:
    """When the J1 flag is disabled, even the J2 default override
    is suppressed — the rollback is complete."""

    def test_flag_off_no_default_override(self, fresh_app, monkeypatch):
        app, _wm, _ = fresh_app
        monkeypatch.setenv("MEDIAHUB_ADAPTIVE_THEME", "0")
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        assert 'id="mh-theme-seed"' not in body
