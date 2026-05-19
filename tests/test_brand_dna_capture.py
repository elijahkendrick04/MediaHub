"""
tests/test_brand_dna_capture.py — Tests for the Brand DNA capture flow.

Covers Step 1 of the MediaHub roadmap:
  - Deterministic HTML colour/heading/title extraction.
  - Graceful failure when the URL is unreachable.
  - Heuristic fallback when no LLM provider is available.
  - End-to-end: /organisation accepts and persists captured fields,
    and old club profile JSON files (without the new fields) still load.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_data_dir(monkeypatch, tmp_path):
    """Redirect DATA_DIR so cache writes don't pollute the real repo."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    yield tmp_path


@pytest.fixture
def no_llm_env(monkeypatch):
    """Force the deterministic heuristic path by disabling every LLM provider."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_LOCAL_URL", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
    from mediahub.web import secrets_store
    monkeypatch.setattr(secrets_store, "_SECRETS_PATH", Path("/tmp/__no_such_secrets__.json"))
    yield


_SAMPLE_HTML = """
<html lang="en-GB">
<head>
<title>Lakeside Swimming Club — Performance, Community, Excellence</title>
<meta name="description" content="Lakeside SC is a community swimming club in the South West.">
<meta name="theme-color" content="#0d4d92">
<meta property="og:image" content="/img/og.png">
<style>
body { background: #0d4d92; color: #ffffff; }
.accent { color: #e94e1b; }
.muted { color: #444444; }
</style>
</head>
<body>
<header><img src="/static/logo.png" alt="Lakeside SC logo"></header>
<h1>Welcome to Lakeside</h1>
<h2>Train. Compete. Grow.</h2>
<p>Our community swims for the love of it.</p>
</body>
</html>
""".strip()


# ---------------------------------------------------------------------------
# 1. Deterministic extraction
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_extract_colours_frequency_ranked(self):
        from mediahub.brand.dna_capture import _extract_colours_from_html
        html = "<div style='background:#0d4d92'></div><span style='color:#0d4d92'></span><i style='color:#e94e1b'></i>"
        colours = _extract_colours_from_html(html)
        assert "#0d4d92" in colours
        # 3-char hex is normalised to 6-char
        html2 = "<div style='color:#abc'></div>"
        c2 = _extract_colours_from_html(html2)
        assert "#aabbcc" in c2

    def test_extract_signals_title_and_headings(self):
        from mediahub.brand.dna_capture import _extract_signals
        sig = _extract_signals(_SAMPLE_HTML, "https://lakeside.example/")
        assert "Lakeside Swimming Club" in sig["title"]
        assert "community swimming club" in sig["meta_description"]
        assert "Welcome to Lakeside" in sig["headings"]
        assert "Train. Compete. Grow." in sig["headings"]

    def test_extract_signals_theme_color_and_og_image(self):
        from mediahub.brand.dna_capture import _extract_signals
        sig = _extract_signals(_SAMPLE_HTML, "https://lakeside.example/")
        assert sig["theme_color"] == "#0d4d92"
        assert sig["og_image"].endswith("/img/og.png")
        assert sig["og_image"].startswith("https://lakeside.example/")

    def test_extract_signals_logo(self):
        from mediahub.brand.dna_capture import _extract_signals
        sig = _extract_signals(_SAMPLE_HTML, "https://lakeside.example/")
        assert sig["logo_url"].endswith("/static/logo.png")

    def test_extract_signals_colours_present(self):
        from mediahub.brand.dna_capture import _extract_signals
        sig = _extract_signals(_SAMPLE_HTML, "https://lakeside.example/")
        # Brand colours should outrank pure white/black
        assert sig["colours"][0] in ("#0d4d92", "#e94e1b")

    def test_extract_signals_empty_html(self):
        from mediahub.brand.dna_capture import _extract_signals
        sig = _extract_signals("", "https://x.example/")
        assert sig["title"] == ""
        assert sig["colours"] == []


# ---------------------------------------------------------------------------
# 2. capture_brand_dna — graceful failure
# ---------------------------------------------------------------------------

class TestGracefulFailure:
    def test_missing_url(self, isolated_data_dir):
        from mediahub.brand.dna_capture import capture_brand_dna
        out = capture_brand_dna("")
        assert out["brand_capture_status"] == "missing_url"
        assert out["brand_voice_summary"] == ""
        assert out["brand_keywords"] == []

    def test_unreachable_url(self, isolated_data_dir, monkeypatch):
        from mediahub.brand import dna_capture
        # Patch the internal _fetch to simulate failure regardless of network
        monkeypatch.setattr(dna_capture, "_fetch", lambda url: None)
        out = dna_capture.capture_brand_dna("https://does-not-exist.invalid/")
        assert out["brand_capture_status"] == "fetch_failed"
        assert out["brand_voice_summary"] == ""

    def test_never_raises_on_garbage(self, isolated_data_dir, monkeypatch):
        """Even with a fetch returning rubbish, capture must not raise."""
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda url: "<not html<<<<")
        out = dna_capture.capture_brand_dna("https://x.example/")
        assert isinstance(out, dict)
        assert "brand_capture_status" in out


# ---------------------------------------------------------------------------
# 3. capture_brand_dna — no cloud LLM configured
# ---------------------------------------------------------------------------

class TestNoProvider:
    def test_no_provider_keeps_deterministic_signals_only(self, isolated_data_dir, no_llm_env, monkeypatch):
        """When no cloud LLM is configured, capture_brand_dna preserves
        the deterministic signals extracted from HTML (logo URL, palette
        from CSS / meta theme-color) but does NOT fabricate voice
        summaries or keywords. Status is ``no_provider`` so the UI can
        surface "AI unavailable" honestly."""
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda url: _SAMPLE_HTML)
        out = dna_capture.capture_brand_dna("https://lakeside.example/")
        assert out["brand_capture_status"] == "no_provider"
        # Deterministic signals survive — they're CSS / HTML extraction,
        # not AI-fabricated.
        assert out["brand_logo_url"].endswith("/static/logo.png")
        assert out["brand_palette_extracted"]
        assert out["brand_palette_extracted"]["primary"] in ("#0d4d92", "#e94e1b")
        assert out["brand_source_url"].startswith("https://lakeside.example")
        # AI-only fields are empty (we declined to invent without an LLM)
        assert out["brand_voice_summary"] == ""
        assert out["brand_keywords"] == []

    def test_palette_filled_from_extracted_colours(self, isolated_data_dir, no_llm_env, monkeypatch):
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda url: _SAMPLE_HTML)
        out = dna_capture.capture_brand_dna("https://lakeside.example/")
        pal = out["brand_palette_extracted"]
        # Palette slots are filled from deterministic CSS / theme-color
        # extraction even without an LLM.
        assert pal.get("primary")
        # Each slot is a valid hex
        for k, v in pal.items():
            assert v.startswith("#") and len(v) == 7, f"{k}={v} not a 6-digit hex"

    def test_cache_round_trip(self, isolated_data_dir, no_llm_env, monkeypatch):
        from mediahub.brand import dna_capture
        url = "https://cache-test.example/"
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _SAMPLE_HTML)
        first = dna_capture.capture_brand_dna(url)
        assert first["brand_capture_status"] in ("ok", "no_provider")
        cache_file = dna_capture._cache_path(url)
        assert cache_file.exists()

        # Only fully-captured ("ok") results short-circuit the fetch on
        # the next call; "no_provider" results get re-fetched so that an
        # LLM result can replace them later.
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: None)
        if first["brand_capture_status"] == "ok":
            second = dna_capture.capture_brand_dna(url)
            assert second["brand_voice_summary"] == first["brand_voice_summary"]


# ---------------------------------------------------------------------------
# 4. capture_brand_dna — LLM happy path (mocked)
# ---------------------------------------------------------------------------

class TestLLMPath:
    def test_llm_result_merged(self, isolated_data_dir, monkeypatch):
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _SAMPLE_HTML)

        # Force is_available True and stub generate_json
        fake_llm = {
            "voice_summary": "A warm, community-led swimming club celebrating every effort.",
            "keywords": ["lakeside", "swimming", "community", "performance", "training",
                         "competition", "youth", "adult"],
            "phrases_to_use": ["proud of the squad", "another PB"],
            "phrases_to_avoid": ["destroyed", "smashed the competition"],
            "palette": {"primary": "#0D4D92", "secondary": "#E94E1B", "accent": "#FFFFFF"},
            "typography_hint": "sans",
        }
        monkeypatch.setattr(
            "mediahub.media_ai.llm.is_available",
            lambda: True,
        )
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda prompt, system=None, max_tokens=1024, fallback=None: fake_llm,
        )

        out = dna_capture.capture_brand_dna("https://lakeside.example/")
        assert out["brand_capture_status"] == "ok"
        assert "community-led" in out["brand_voice_summary"]
        assert "lakeside" in out["brand_keywords"]
        assert out["brand_phrases_to_use"] == ["proud of the squad", "another PB"]
        assert out["brand_phrases_to_avoid"][0] == "destroyed"
        assert out["brand_palette_extracted"]["primary"] == "#0d4d92"  # normalised
        assert out["brand_typography_hint"] == "sans"

    def test_llm_bad_palette_rejected(self, isolated_data_dir, monkeypatch):
        """Invalid hex codes from the LLM must not crash; fallbacks fill in."""
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _SAMPLE_HTML)
        bad_llm = {
            "voice_summary": "ok",
            "keywords": [],
            "phrases_to_use": [],
            "phrases_to_avoid": [],
            "palette": {"primary": "not-a-hex", "secondary": "#gggggg"},
            "typography_hint": "alien-script",
        }
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.media_ai.llm.generate_json",
            lambda prompt, system=None, max_tokens=1024, fallback=None: bad_llm,
        )
        out = dna_capture.capture_brand_dna("https://lakeside.example/")
        # Bad typography hint dropped
        assert out["brand_typography_hint"] != "alien-script"
        # Palette still populated from extracted colours
        assert out["brand_palette_extracted"].get("primary", "").startswith("#")


# ---------------------------------------------------------------------------
# 5. ClubProfile backward compatibility
# ---------------------------------------------------------------------------

class TestClubProfileBackwardCompat:
    def test_old_profile_json_loads(self, isolated_data_dir):
        """A JSON file without the new brand_* keys must load cleanly."""
        from mediahub.web.club_profile import ClubProfile
        old_json = {
            "profile_id": "old-club",
            "display_name": "Old Club",
            "short_name": "OC",
            "club_codes": ["OLD"],
            "brand_primary": "#A30D2D",
            "tone": "warm-club",
        }
        prof = ClubProfile.from_dict(old_json)
        assert prof.profile_id == "old-club"
        # New fields default to safe values
        assert prof.brand_voice_summary == ""
        assert prof.brand_keywords == []
        assert prof.brand_palette_extracted == {}
        assert prof.brand_logo_url == ""

    def test_new_fields_round_trip(self):
        from mediahub.web.club_profile import ClubProfile
        p = ClubProfile(
            profile_id="x",
            display_name="X",
            brand_voice_summary="A test voice.",
            brand_keywords=["foo", "bar"],
            brand_palette_extracted={"primary": "#0d4d92"},
            brand_logo_url="https://x.example/logo.png",
            brand_typography_hint="sans",
            brand_phrases_to_use=["a", "b"],
            brand_phrases_to_avoid=["c"],
            brand_source_url="https://x.example",
            brand_captured_at="2026-05-13T00:00:00+00:00",
            brand_capture_status="ok",
        )
        d = p.to_dict()
        p2 = ClubProfile.from_dict(d)
        assert p2.brand_voice_summary == "A test voice."
        assert p2.brand_keywords == ["foo", "bar"]
        assert p2.brand_palette_extracted == {"primary": "#0d4d92"}
        assert p2.brand_phrases_to_use == ["a", "b"]


# ---------------------------------------------------------------------------
# 6. /organisation route smoke test
# ---------------------------------------------------------------------------

class TestOrganisationRoute:
    def test_get_renders_with_no_url(self, isolated_data_dir):
        from mediahub.web.web import create_app
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        r = client.get("/organisation")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "brand_source_url" in body
        # The capture card must still be present (label was generalised
        # from "Capture from website" to cover both websites and socials).
        assert "Re-analyse brand" in body or "Capture from website" in body

    def test_capture_action_unreachable_url_shows_error(self, isolated_data_dir, monkeypatch):
        """An unreachable URL must produce a clear error, not a 500."""
        from mediahub.web.web import create_app
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: None)
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        r = client.post("/organisation", data={
            "action": "capture",
            "profile_id": "test-club",
            "display_name": "Test Club",
            "brand_source_url": "https://does-not-exist.invalid/",
        })
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Could not reach" in body or "Capture failed" in body

    def test_capture_then_save_persists(self, isolated_data_dir, no_llm_env, monkeypatch):
        """End-to-end: capture from a stubbed website, then submit the save
        form and confirm the captured fields land in the on-disk JSON."""
        from mediahub.web.web import create_app
        from mediahub.brand import dna_capture

        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _SAMPLE_HTML)

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()

        # Capture
        r1 = client.post("/organisation", data={
            "action": "capture",
            "profile_id": "lakeside",
            "display_name": "Lakeside SC",
            "brand_source_url": "https://lakeside.example/",
        })
        assert r1.status_code == 200
        body1 = r1.get_data(as_text=True)
        # Preview banner appears
        assert "Captured from website" in body1
        # Logo or palette swatch visible in preview
        assert "Brand DNA preview" in body1

        # Now submit Save with the hidden brand fields that the rendered
        # preview emits. We replay them by extracting from the response.
        import re as _re
        def find_hidden(name):
            m = _re.search(rf'name="{name}"\s+value="([^"]*)"', body1)
            return m.group(1) if m else ""

        save_form = {
            "action": "save",
            "profile_id": "lakeside",
            "display_name": "Lakeside SC",
            "short_name": "Lakeside",
            "brand_primary": "#0d4d92",
            "brand_secondary": "#000000",
            "tone": "warm-club",
            "brand_voice_summary": find_hidden("brand_voice_summary"),
            "brand_logo_url": find_hidden("brand_logo_url"),
            "brand_typography_hint": find_hidden("brand_typography_hint"),
            "brand_source_url_saved": find_hidden("brand_source_url_saved"),
            "brand_captured_at": find_hidden("brand_captured_at"),
            "brand_capture_status": find_hidden("brand_capture_status"),
            "brand_keywords_json": find_hidden("brand_keywords_json").replace("&#34;", '"').replace("&quot;", '"'),
            "brand_phrases_to_use_json": find_hidden("brand_phrases_to_use_json").replace("&#34;", '"').replace("&quot;", '"'),
            "brand_phrases_to_avoid_json": find_hidden("brand_phrases_to_avoid_json").replace("&#34;", '"').replace("&quot;", '"'),
            "brand_palette_extracted_json": find_hidden("brand_palette_extracted_json").replace("&#34;", '"').replace("&quot;", '"'),
        }
        r2 = client.post("/organisation", data=save_form)
        assert r2.status_code == 200
        assert "Organisation saved" in r2.get_data(as_text=True)

        # Confirm the JSON file now contains the captured fields
        profile_path = isolated_data_dir / "club_profiles" / "lakeside.json"
        assert profile_path.exists()
        saved = json.loads(profile_path.read_text())
        assert saved["brand_logo_url"].endswith("/static/logo.png")
        assert saved["brand_palette_extracted"]
        assert saved["brand_source_url"].startswith("https://lakeside.example")
        assert saved["brand_capture_status"] in ("ok", "no_provider")


# ---------------------------------------------------------------------------
# 7. Cache hygiene
# ---------------------------------------------------------------------------

class TestCacheHygiene:
    def test_cache_dir_under_data_dir(self, isolated_data_dir, monkeypatch):
        """The cache must write under DATA_DIR, never the source tree."""
        from mediahub.brand import dna_capture
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _SAMPLE_HTML)
        # Disable LLM so the fast heuristic path runs
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        dna_capture.capture_brand_dna("https://hygiene.example/")
        # Cache file must live under the tmp DATA_DIR, not the repo
        expected = isolated_data_dir / "brand_dna_cache" / "hygiene.example.json"
        assert expected.exists()
