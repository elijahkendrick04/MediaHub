"""tests/test_social_dna.py — first-run AI brand DNA capture from social links.

Covers the three concerns the user cares about:
  1. The interpretation layer is LLM-driven — when an LLM is mocked, its
     output is what shapes the returned brand profile (not regex
     heuristics on the URL).
  2. Graceful degradation — auth-walled / blocked / 4xx / network-failed
     links are recorded in social_links_status but never blow up the
     pipeline. When at least one source returns something readable, the
     analyser still produces a profile.
  3. The fetched payload (titles, descriptions, candidate captions,
     hashtags) is what gets passed to the LLM — i.e. the AI engine
     actually sees the content from the user's links, not just the URL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import social_dna  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Redirect the social_dna cache dir under tmp_path so tests can't
    pick up stale cache hits from another test run."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


def _stub_fetch(responses: dict[str, tuple[str | None, int]]):
    """Return a fake ``_fetch`` that serves canned HTML per-URL."""
    def fake_fetch(url: str):
        return responses.get(url, (None, 0))
    return fake_fetch


# ---------------------------------------------------------------------------
# 1. LLM-driven interpretation
# ---------------------------------------------------------------------------

class TestLlmDrivenInterpretation:
    """Whatever the LLM returns shapes the brand profile — there is no
    fallback URL-pattern matching for voice."""

    def test_llm_output_populates_voice_fields(self, isolated_cache, monkeypatch):
        responses = {
            "https://city-aquatics.example": (
                "<html><head><title>City Aquatics</title>"
                "<meta name='description' content='Inclusive community swimming for all ages'/>"
                "<meta name='theme-color' content='#0066CC'/>"
                "<style>.brand{color:#0066CC} .accent{background:#F2A900}</style>"
                "</head><body><h1>City Aquatics</h1>"
                "<p>Big PB for the squad this weekend. #ClubLife</p>"
                "<p>What a meet — five PBs and a county standard. #Swimming</p>"
                "</body></html>",
                200,
            ),
            "https://instagram.com/city-aquatics": (
                "<html><head><title>City Aquatics (@city.aquatics) · Instagram</title>"
                "<meta property='og:description' content='Inclusive club. We celebrate every effort. #ClubLife'/>"
                "</head><body><p>Massive shout out to the junior squad #PBseason</p></body></html>",
                200,
            ),
        }
        monkeypatch.setattr(social_dna, "_fetch", _stub_fetch(responses))

        mock_llm_output = {
            "voice_summary": "An inclusive community swimming club that celebrates every effort, with a warm and encouraging tone.",
            "keywords": ["inclusive", "community", "swimming", "PBs", "junior squad"],
            "phrases_to_use": ["Big PB for the squad", "What a meet"],
            "phrases_to_avoid": ["elite athletes only", "champions only"],
            "palette": {"primary": "#0066cc", "secondary": "#f2a900"},
            "typography_hint": "sans",
            "voice_profile": {
                "sentence_length_avg": 9,
                "sentence_length_p90": 14,
                "emoji_rate_per_caption": 0.0,
                "hashtag_count_avg": 1.5,
                "characteristic_openers": ["Big PB", "What a meet", "Massive shout out"],
                "characteristic_closers": ["#ClubLife", "#PBseason"],
                "preferred_swimmer_address": "first_name",
                "common_hashtags": ["#ClubLife", "#PBseason", "#Swimming"],
                "capitalisation_style": "sentence",
            },
        }
        monkeypatch.setattr(social_dna, "_call_llm", lambda prompt: mock_llm_output)

        result = social_dna.capture_from_socials(
            social_links={"instagram": "https://instagram.com/city-aquatics"},
            website_url="https://city-aquatics.example",
        )

        assert result["brand_capture_status"] == "ok"
        assert "inclusive community swimming" in result["brand_voice_summary"].lower()
        assert "inclusive" in result["brand_keywords"]
        assert "Big PB for the squad" in result["brand_phrases_to_use"]
        assert "elite athletes only" in result["brand_phrases_to_avoid"]
        # Voice profile flows through to the saved structure
        vp = result["voice_profile"]
        assert vp["preferred_swimmer_address"] == "first_name"
        assert "Big PB" in vp["characteristic_openers"]
        assert vp["capitalisation_style"] == "sentence"

    def test_llm_sees_actual_caption_text(self, isolated_cache, monkeypatch):
        """The LLM prompt must include candidate captions extracted from
        the fetched page — proving the AI is reading the user's links."""
        responses = {
            "https://example.example": (
                "<html><head><title>Example Club</title></head><body>"
                "<p>This is a very specific caption that should make it into the prompt.</p>"
                "<p>Another caption here for good measure. #Hashtag</p>"
                "</body></html>",
                200,
            ),
        }
        monkeypatch.setattr(social_dna, "_fetch", _stub_fetch(responses))

        captured_prompt: dict = {"text": ""}

        def fake_llm(prompt: str):
            captured_prompt["text"] = prompt
            return {"voice_summary": "x", "keywords": []}

        monkeypatch.setattr(social_dna, "_call_llm", fake_llm)

        social_dna.capture_from_socials(
            social_links={}, website_url="https://example.example"
        )

        assert "specific caption that should make it" in captured_prompt["text"]
        assert "#Hashtag" in captured_prompt["text"]

    def test_no_llm_falls_back_gracefully(self, isolated_cache, monkeypatch):
        """When no LLM is available the analyser still returns ok_heuristic
        and a usable voice_summary built from fetched meta — never raises."""
        responses = {
            "https://example.example": (
                "<html><head><title>Example Club</title>"
                "<meta name='description' content='A friendly local club'/>"
                "</head></html>",
                200,
            ),
        }
        monkeypatch.setattr(social_dna, "_fetch", _stub_fetch(responses))
        monkeypatch.setattr(social_dna, "_call_llm", lambda prompt: None)

        result = social_dna.capture_from_socials(
            social_links={}, website_url="https://example.example"
        )
        assert result["brand_capture_status"] == "ok_heuristic"
        assert "friendly local club" in result["brand_voice_summary"].lower()


# ---------------------------------------------------------------------------
# 2. Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_no_sources_returns_clean_error(self, isolated_cache):
        result = social_dna.capture_from_socials(social_links={}, website_url="")
        assert result["brand_capture_status"] == "no_sources"
        # Never raises
        assert result["brand_voice_summary"] == ""

    def test_auth_walled_link_recorded_but_does_not_fail(self, isolated_cache, monkeypatch):
        """A 403 on Instagram should not poison the whole capture if at
        least one other link is readable."""
        responses = {
            "https://instagram.com/blocked": (None, 403),
            "https://city.example": (
                "<html><head><title>City</title>"
                "<meta name='description' content='A club'/></head></html>",
                200,
            ),
        }
        monkeypatch.setattr(social_dna, "_fetch", _stub_fetch(responses))
        monkeypatch.setattr(social_dna, "_call_llm", lambda prompt: {"voice_summary": "A club"})

        result = social_dna.capture_from_socials(
            social_links={"instagram": "https://instagram.com/blocked"},
            website_url="https://city.example",
        )
        assert result["brand_capture_status"] == "ok"
        assert result["social_links_status"]["instagram"] == "auth_walled"
        assert result["social_links_status"]["website"] == "ok"

    def test_all_links_fail_returns_status(self, isolated_cache, monkeypatch):
        responses = {
            "https://instagram.com/x": (None, 0),
            "https://facebook.com/x": (None, 500),
        }
        monkeypatch.setattr(social_dna, "_fetch", _stub_fetch(responses))

        result = social_dna.capture_from_socials(
            social_links={
                "instagram": "https://instagram.com/x",
                "facebook": "https://facebook.com/x",
            },
            website_url="",
        )
        assert result["brand_capture_status"] == "fetch_failed_all"
        assert result["social_links_status"]["instagram"] == "fetch_failed"
        # 500 is not in the special-cased buckets so it lands in http_500
        assert result["social_links_status"]["facebook"] == "http_500"

    def test_garbage_url_no_crash(self, isolated_cache, monkeypatch):
        monkeypatch.setattr(social_dna, "_fetch", lambda u: (None, 0))
        result = social_dna.capture_from_socials(
            social_links={"instagram": "not-a-url"}, website_url="also-broken",
        )
        # Must not raise; status is fetch_failed_all
        assert result["brand_capture_status"] == "fetch_failed_all"


# ---------------------------------------------------------------------------
# 3. Caching + URL normalisation
# ---------------------------------------------------------------------------

class TestCaching:
    def test_cache_hit_skips_fetch(self, isolated_cache, monkeypatch):
        responses = {
            "https://city.example": (
                "<html><head><title>City</title></head></html>",
                200,
            ),
        }
        fetch_calls: list[str] = []

        def counting_fetch(url):
            fetch_calls.append(url)
            return responses.get(url, (None, 0))

        monkeypatch.setattr(social_dna, "_fetch", counting_fetch)
        monkeypatch.setattr(social_dna, "_call_llm", lambda p: {"voice_summary": "x"})

        # First call populates cache
        social_dna.capture_from_socials(social_links={}, website_url="https://city.example")
        first_count = len(fetch_calls)
        # Second call must serve from cache
        social_dna.capture_from_socials(social_links={}, website_url="https://city.example")
        assert len(fetch_calls) == first_count, "cache was not consulted"

    def test_force_bypasses_cache(self, isolated_cache, monkeypatch):
        responses = {
            "https://city.example": (
                "<html><head><title>City</title></head></html>",
                200,
            ),
        }
        fetch_calls: list[str] = []

        def counting_fetch(url):
            fetch_calls.append(url)
            return responses.get(url, (None, 0))

        monkeypatch.setattr(social_dna, "_fetch", counting_fetch)
        monkeypatch.setattr(social_dna, "_call_llm", lambda p: {"voice_summary": "x"})

        social_dna.capture_from_socials(social_links={}, website_url="https://city.example")
        social_dna.capture_from_socials(
            social_links={}, website_url="https://city.example", force=True,
        )
        # force=True re-fetches
        assert len(fetch_calls) >= 2

    def test_missing_scheme_is_normalised(self, isolated_cache, monkeypatch):
        seen: list[str] = []

        def fetch(url):
            seen.append(url)
            return ("<html><title>X</title></html>", 200)

        monkeypatch.setattr(social_dna, "_fetch", fetch)
        monkeypatch.setattr(social_dna, "_call_llm", lambda p: {"voice_summary": "x"})

        social_dna.capture_from_socials(
            social_links={"instagram": "instagram.com/x"},
            website_url="city.example",
        )
        # Both URLs must have been upgraded to https://
        assert any(u.startswith("https://") for u in seen)
        assert not any(u.startswith("http://") and not u.startswith("https://") for u in seen)
