"""Stage H3 — the non-blocking warning callout."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, wm, cp


def _seed_profile(cp, *, profile_id, primary):
    from mediahub.web.club_profile import ClubProfile
    prof = ClubProfile(profile_id=profile_id, display_name=f"Test {profile_id}")
    prof.brand_primary = primary
    prof.brand_voice_summary = "Energetic"
    prof.brand_keywords = ["club"]
    prof.brand_palette_extracted = {"primary": primary}
    prof.brand_kit = {
        "profile_id": profile_id, "display_name": f"Test {profile_id}",
        "primary_colour": primary,
    }
    cp.save_profile(prof)
    return prof


class TestRepairTextHelper:
    def test_none_when_not_repaired(self, app_client):
        _, wm, _ = app_client
        assert wm._repair_summary_text(None) is None
        assert wm._repair_summary_text({"was_repaired": False}) is None
        assert wm._repair_summary_text({}) is None

    def test_returns_string_when_repaired(self, app_client):
        _, wm, _ = app_client
        text = wm._repair_summary_text({
            "was_repaired": True,
            "palettes": {
                "error": {"hue": 25.0},      # canonical
                "success": {"hue": 160.0},    # shifted from 142 → +18°
                "warning": {"hue": 80.0},     # canonical
                "info": {"hue": 240.0},       # canonical
            },
        })
        assert text is not None
        assert "success" in text  # the moved anchor
        assert "+18°" in text or "+ 18" in text  # the magnitude


class TestCalloutInPage:
    def test_callout_renders_for_repaired_profile(self, app_client):
        client, _, cp = app_client
        # Brand red triggers Stage B's repair loop deterministically.
        _seed_profile(cp, profile_id="h3-repaired", primary="#A30D2D")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h3-repaired"
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Theme adjusted for accessibility" in body
        assert "mh-theme-warning" in body

    def test_no_callout_when_not_repaired(self, app_client):
        client, _, cp = app_client
        # Lane yellow → Stage B passes all gates without repair.
        _seed_profile(cp, profile_id="h3-clean", primary="#D4FF3A")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h3-clean"
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Theme adjusted for accessibility" not in body


class TestCalloutShape:
    def test_callout_html_renders_non_empty_for_repaired(self, app_client):
        _, wm, _ = app_client
        html = wm._theme_repair_callout_html({
            "was_repaired": True,
            "palettes": {"success": {"hue": 175.0}},
        })
        assert "mh-theme-warning" in html
        assert "Theme adjusted for accessibility" in html

    def test_callout_html_empty_when_not_repaired(self, app_client):
        _, wm, _ = app_client
        assert wm._theme_repair_callout_html(None) == ""
        assert wm._theme_repair_callout_html({"was_repaired": False}) == ""

    def test_callout_uses_warning_role(self, app_client):
        _, wm, _ = app_client
        html = wm._theme_repair_callout_html({
            "was_repaired": True,
            "palettes": {"success": {"hue": 175.0}},
        })
        # role="status" is a non-blocking announcement (vs role="alert")
        assert 'role="status"' in html
