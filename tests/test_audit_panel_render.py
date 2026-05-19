"""Stage H — the "Why does my theme look like this?" audit panel.

Tests both the standalone helper _theme_audit_panel_html() and the
integration via /organisation/setup.
"""
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


def _seed_profile(cp, *, profile_id="h-test", primary="#06D6A0"):
    from mediahub.web.club_profile import ClubProfile
    prof = ClubProfile(profile_id=profile_id, display_name="H Audit Test")
    prof.brand_primary = primary
    prof.brand_voice_summary = "Energetic"
    prof.brand_keywords = ["club", "test"]
    prof.brand_palette_extracted = {"primary": primary}
    prof.brand_kit = {
        "profile_id": profile_id, "display_name": "H Audit Test",
        "primary_colour": primary,
    }
    cp.save_profile(prof)
    return prof


class TestPanelHelperStandalone:
    def test_none_input_returns_empty(self, app_client):
        client, wm, _ = app_client
        with wm.create_app().test_request_context():
            assert wm._theme_audit_panel_html(None) == ""

    def test_invalid_input_returns_empty(self, app_client):
        client, wm, _ = app_client
        with wm.create_app().test_request_context():
            assert wm._theme_audit_panel_html("not a dict") == ""
            assert wm._theme_audit_panel_html(42) == ""

    def test_minimal_theme_renders_details_block(self, app_client):
        client, wm, _ = app_client
        with wm.create_app().test_request_context():
            html = wm._theme_audit_panel_html({
                "seed_hex": "#0E2A47",
                "seed_source": "hex",
                "seed_hct": [256.0, 27.0, 17.0],
                "palettes": {"primary": {"hue": 256, "chroma": 27,
                                          "tones": {"400": "#406088"}}},
                "quality_detail": {"contrast": [], "adjacency": [],
                                    "status_distance": [], "cvd": [],
                                    "warnings": [], "errors": []},
                "harmonic_fit": {"template": "I", "rotation": 0.0,
                                  "energy": 0.0, "hue_count": 1,
                                  "template_bands": []},
                "decision_trace": ["seed: #0E2A47 accepted"],
                "was_repaired": False,
            })
            assert "<details" in html
            assert "Why does my theme look like this?" in html
            assert "#0E2A47" in html


class TestPanelInPage:
    def test_panel_renders_on_setup(self, app_client):
        client, wm, cp = app_client
        prof = _seed_profile(cp, profile_id="h-panel", primary="#06D6A0")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-panel"
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Why does my theme look like this?" in body
        assert "mh-theme-audit" in body
        assert "Captured seed" in body
        assert "Contrast checks" in body

    def test_panel_uses_collapsible_details(self, app_client):
        client, _, cp = app_client
        _seed_profile(cp, profile_id="h-coll", primary="#06D6A0")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-coll"
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Native <details> element — works without JS
        assert '<details class="mh-theme-audit"' in body

    def test_panel_carries_seed_hex(self, app_client):
        client, _, cp = app_client
        _seed_profile(cp, profile_id="h-seed", primary="#A30D2D")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-seed"
        body = client.get("/organisation/setup").get_data(as_text=True)
        # The seed hex should appear inside the captured-seed section.
        assert "#A30D2D" in body

    def test_panel_carries_decision_trace(self, app_client):
        client, _, cp = app_client
        _seed_profile(cp, profile_id="h-trace", primary="#06D6A0")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-trace"
        body = client.get("/organisation/setup").get_data(as_text=True)
        # The trace section's <pre> block should exist.
        assert "Decision trace" in body
        # And it should mention "seed" (Stage B's trace lines all do).
        assert "seed:" in body.lower() or "direct-hex" in body.lower()

    def test_panel_mentions_cohen_or(self, app_client):
        client, _, cp = app_client
        _seed_profile(cp, profile_id="h-coh", primary="#06D6A0")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-coh"
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Cohen-Or 2006" in body

    def test_panel_includes_cvd_table(self, app_client):
        client, _, cp = app_client
        _seed_profile(cp, profile_id="h-cvd", primary="#06D6A0")
        with client.session_transaction() as s:
            s["active_profile_id"] = "h-cvd"
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Colour-vision-deficiency simulation" in body
        assert "Machado 2009" in body


class TestPanelEscapesUserInput:
    def test_xss_in_trace_text_escaped(self, app_client):
        """The decision trace gets HTML-escaped by _h() — a crafted
        trace line cannot inject script tags."""
        client, wm, _ = app_client
        with wm.create_app().test_request_context():
            html = wm._theme_audit_panel_html({
                "seed_hex": "#000000",
                "seed_source": "hex",
                "seed_hct": [0.0, 0.0, 0.0],
                "palettes": {},
                "quality_detail": {"contrast": [], "adjacency": [],
                                    "status_distance": [], "cvd": [],
                                    "warnings": [], "errors": []},
                "harmonic_fit": None,
                "decision_trace": ["<script>alert(1)</script>"],
                "was_repaired": False,
            })
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
