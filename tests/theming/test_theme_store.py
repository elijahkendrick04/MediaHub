"""Stage G — on-disk theme store contract tests.

Pins the contract of ``mediahub.theming.theme_store``:
  - profile-id validation rejects path traversal
  - writes are atomic (no half-written files)
  - reads return None for missing/malformed files
  - role-mapping helpers produce documented shapes
  - delete is idempotent
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediahub.theming.theme_store import (
    themes_dir,
    theme_path,
    write_theme,
    read_theme,
    delete_theme,
    palette_for_motion,
    palette_for_email,
    palette_for_static,
    ProfileIdError,
)


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Bust the lru_cache so reads see the fresh DATA_DIR.
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    return tmp_path


_SAMPLE = {
    "schema_version": "1",
    "seed_hex": "#A30D2D",
    "roles": {
        "dark":  {"primary": "#FFB3B4", "secondary_container": "#5C1F1F", "tertiary": "#FFB68F"},
        "light": {"primary": "#8B4C4F", "secondary_container": "#FFDAD6", "tertiary": "#7B5731"},
    },
}


class TestProfileIdValidation:
    def test_themes_dir_created(self, isolated_data_dir):
        d = themes_dir()
        assert d.is_dir()
        assert d == isolated_data_dir / "themes"

    def test_dev_fallback_matches_web_src_root(self, monkeypatch):
        """With DATA_DIR unset, the fallback is src/mediahub/ — the same
        dev default web.py uses (_SRC_ROOT) — not src/."""
        monkeypatch.delenv("DATA_DIR", raising=False)
        from mediahub.theming import theme_store
        fallback = theme_store._data_dir()
        pkg_root = Path(theme_store.__file__).resolve().parents[1]
        assert fallback == pkg_root
        assert fallback.name == "mediahub"

    @pytest.mark.parametrize("bad", [
        "../etc/passwd",
        "a/b",
        "name with spaces",
        "",
        "x" * 81,           # too long
        "UPPERCASE",
        "name.with.dots",
        "name;rm",
    ])
    def test_bad_profile_id_rejected(self, bad):
        with pytest.raises(ProfileIdError):
            theme_path(bad)

    @pytest.mark.parametrize("good", [
        "swim-club", "swim_club", "abc", "club-2026", "test-12345",
        "a", "x" * 80,
    ])
    def test_good_profile_id_accepted(self, isolated_data_dir, good):
        path = theme_path(good)
        assert path.parent == themes_dir()
        assert path.name == f"{good}.json"


class TestRoundTrip:
    def test_write_then_read(self, isolated_data_dir):
        write_theme("test-club", _SAMPLE)
        result = read_theme("test-club")
        assert result == _SAMPLE

    def test_read_missing_returns_none(self, isolated_data_dir):
        assert read_theme("nonexistent") is None

    def test_read_malformed_returns_none(self, isolated_data_dir):
        path = theme_path("malformed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {", encoding="utf-8")
        from mediahub.theming.theme_store import _read_cached
        _read_cached.cache_clear()
        assert read_theme("malformed") is None

    def test_read_non_dict_returns_none(self, isolated_data_dir):
        path = theme_path("not-a-dict")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('["array", "not", "dict"]', encoding="utf-8")
        from mediahub.theming.theme_store import _read_cached
        _read_cached.cache_clear()
        assert read_theme("not-a-dict") is None

    def test_read_with_bad_pid_returns_none(self, isolated_data_dir):
        # read_theme must NOT raise on bad profile_ids — it returns
        # None so consumers fall through cleanly.
        assert read_theme("../etc/passwd") is None
        assert read_theme("") is None


class TestAtomicity:
    def test_write_is_atomic(self, isolated_data_dir):
        # Two writes in succession — neither leaves a tmp file behind.
        write_theme("atomic", _SAMPLE)
        write_theme("atomic", {**_SAMPLE, "seed_hex": "#000000"})
        # Only the final file exists; no .tmp orphans.
        leftovers = list(themes_dir().glob(".*tmp*"))
        assert leftovers == [], f"tmp files leaked: {leftovers}"
        result = read_theme("atomic")
        assert result["seed_hex"] == "#000000"

    def test_write_rejects_non_dict(self, isolated_data_dir):
        with pytest.raises(TypeError):
            write_theme("xyz", "not a dict")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            write_theme("xyz", ["array"])  # type: ignore[arg-type]


class TestCacheInvalidation:
    def test_cache_picks_up_fresh_writes(self, isolated_data_dir):
        write_theme("cache-test", _SAMPLE)
        a = read_theme("cache-test")
        assert a == _SAMPLE
        # Overwrite
        new = {**_SAMPLE, "seed_hex": "#FFFFFF"}
        write_theme("cache-test", new)
        b = read_theme("cache-test")
        assert b == new
        assert a != b


class TestDelete:
    def test_delete_existing_returns_true(self, isolated_data_dir):
        write_theme("delete-me", _SAMPLE)
        assert delete_theme("delete-me") is True

    def test_delete_missing_returns_false(self, isolated_data_dir):
        assert delete_theme("never-existed") is False

    def test_delete_idempotent(self, isolated_data_dir):
        write_theme("delete-me", _SAMPLE)
        assert delete_theme("delete-me") is True
        assert delete_theme("delete-me") is False
        assert read_theme("delete-me") is None

    def test_delete_bad_pid_returns_false(self, isolated_data_dir):
        # delete must NOT raise on bad profile_ids.
        assert delete_theme("../etc/passwd") is False


class TestRoleMappingMotion:
    def test_motion_uses_dark_scheme(self):
        p = palette_for_motion(_SAMPLE)
        assert p["scheme"] == "dark"
        assert p["primary"] == "#FFB3B4"   # dark.primary

    def test_motion_shape(self):
        p = palette_for_motion(_SAMPLE)
        for key in ("primary", "secondary", "accent", "scheme", "source"):
            assert key in p

    def test_motion_with_empty_theme_uses_fallbacks(self):
        p = palette_for_motion({})
        assert p["primary"] == "#0A2540"
        assert p["secondary"] == "#000000"
        assert p["accent"] == "#FFFFFF"


class TestRoleMappingEmail:
    def test_email_uses_light_scheme(self):
        p = palette_for_email(_SAMPLE)
        assert p["scheme"] == "light"
        assert p["primary"] == "#8B4C4F"   # light.primary

    def test_email_shape(self):
        p = palette_for_email(_SAMPLE)
        for key in ("primary", "secondary", "accent", "scheme", "source"):
            assert key in p


class TestRoleMappingStatic:
    def test_static_uses_light_scheme(self):
        p = palette_for_static(_SAMPLE)
        assert p["scheme"] == "light"
        assert p["primary"] == "#8B4C4F"

    def test_static_matches_email_primary(self):
        """Both static graphics and email use the light primary;
        documented zero-drift between these two surfaces."""
        a = palette_for_email(_SAMPLE)
        b = palette_for_static(_SAMPLE)
        assert a["primary"] == b["primary"]


class TestRoleMappingFallbacks:
    """When a theme JSON is missing role data, the helpers must
    fall back to the documented defaults rather than crashing."""

    def test_missing_roles_key(self):
        p = palette_for_motion({"schema_version": "1"})  # no roles
        assert p["primary"] == "#0A2540"

    def test_missing_scheme(self):
        # Has roles dict but no dark/light keys
        p = palette_for_motion({"roles": {}})
        assert p["primary"] == "#0A2540"

    def test_non_hex_role_value(self):
        # Role exists but isn't a hex string
        bad = {"roles": {"dark": {"primary": "not a hex"}}}
        p = palette_for_motion(bad)
        assert p["primary"] == "#0A2540"
