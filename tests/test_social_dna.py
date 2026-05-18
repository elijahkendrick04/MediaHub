"""tests/test_social_dna.py — capture_from_socials() public API.

The internals of capture_from_socials() were rewritten to delegate to
the AI-driven link_handlers / link_learners pipeline. This file now
covers the mapping concern only:

  - the returned dict has the legacy ClubProfile-friendly shape
  - link_capture_state is surfaced for the next-page audits
  - graceful no_sources / fetch_failed_all handling
  - cache round-trip

End-to-end orchestration (drift detection, learner dispatch, etc.) is
covered in tests/test_link_handlers.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import social_dna, link_handlers  # noqa: E402


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# 1. No-sources case
# ---------------------------------------------------------------------------

def test_no_sources_returns_no_sources_status(isolated_cache):
    out = social_dna.capture_from_socials(social_links={}, website_url="")
    assert out["brand_capture_status"] == "no_sources"
    assert out["brand_voice_summary"] == ""
    assert out["brand_keywords"] == []


# ---------------------------------------------------------------------------
# 2. Successful capture maps merged_dna into ClubProfile fields
# ---------------------------------------------------------------------------

def test_capture_maps_handler_output_into_legacy_shape(isolated_cache, monkeypatch):
    fake_handler_out = {
        "any_real": True,
        "state": {
            "website": {
                "url": "https://city-aquatics.example",
                "status": "real_content",
                "playbook_age": 0,
                "regenerated": True,
                "voice_digest": "Inclusive community swimming.",
            },
            "instagram": {
                "url": "https://www.instagram.com/city.aquatics/",
                "status": "real_content",
                "playbook_age": 0,
                "regenerated": True,
                "voice_digest": "Celebrates every effort.",
            },
        },
        "merged_dna": {
            "voice_summary": "Inclusive community swimming club, warm and encouraging.",
            "keywords": ["inclusive", "community", "swimming", "pb"],
            "phrases_to_use": ["celebrate every effort", "shout out to the squad"],
            "phrases_to_avoid": ["elite only"],
            "palette_mentions": ["#0066cc", "#f2a900"],
            "typography_hint": "sans",
            "sponsor_mentions": [],
            "hashtag_patterns": ["#ClubLife", "#PBseason"],
        },
    }
    monkeypatch.setattr(link_handlers, "process_links",
                         lambda **kw: fake_handler_out)

    out = social_dna.capture_from_socials(
        social_links={"instagram": "https://instagram.com/city.aquatics"},
        website_url="https://city-aquatics.example",
    )

    assert out["brand_capture_status"] == "ok"
    assert out["brand_voice_summary"].startswith("Inclusive community swimming")
    assert "inclusive" in out["brand_keywords"]
    assert "celebrate every effort" in out["brand_phrases_to_use"]
    assert out["brand_typography_hint"] == "sans"
    palette = out["brand_palette_extracted"]
    assert palette.get("primary") == "#0066cc"
    assert palette.get("secondary") == "#f2a900"
    # social_links_status is populated for the next-page audit
    assert out["social_links_status"]["website"] == "real_content"
    assert out["social_links_status"]["instagram"] == "real_content"
    # link_capture_state carries the full per-link record
    state = out["link_capture_state"]
    assert state["instagram"]["voice_digest"] == "Celebrates every effort."
    assert state["website"]["regenerated"] is True


# ---------------------------------------------------------------------------
# 3. Fetch failures bubble up as a status, not an exception
# ---------------------------------------------------------------------------

def test_all_links_blocked_returns_fetch_failed_all(isolated_cache, monkeypatch):
    monkeypatch.setattr(link_handlers, "process_links", lambda **kw: {
        "any_real": False,
        "state": {
            "instagram": {"url": "x", "status": "hard_blocked",
                          "playbook_age": -1, "regenerated": True,
                          "voice_digest": ""},
        },
        "merged_dna": {},
    })
    out = social_dna.capture_from_socials(
        social_links={"instagram": "https://instagram.com/x"},
        website_url="",
    )
    assert out["brand_capture_status"] == "fetch_failed_all"
    assert out["social_links_status"]["instagram"] == "hard_blocked"


def test_handler_exception_returns_error_status(isolated_cache, monkeypatch):
    def boom(**kw):
        raise RuntimeError("internal blow-up")
    monkeypatch.setattr(link_handlers, "process_links", boom)
    out = social_dna.capture_from_socials(
        social_links={"instagram": "https://instagram.com/x"},
        website_url="",
    )
    assert out["brand_capture_status"].startswith("error: ")


# ---------------------------------------------------------------------------
# 4. Cache round-trip
# ---------------------------------------------------------------------------

def test_cache_hit_skips_pipeline(isolated_cache, monkeypatch):
    call_count = {"n": 0}

    def counting_handler(**kw):
        call_count["n"] += 1
        return {
            "any_real": True,
            "state": {"website": {"url": "https://x.example",
                                    "status": "real_content",
                                    "playbook_age": 0,
                                    "regenerated": True,
                                    "voice_digest": "Demo."}},
            "merged_dna": {"voice_summary": "Demo voice.", "keywords": ["a"]},
        }
    monkeypatch.setattr(link_handlers, "process_links", counting_handler)

    social_dna.capture_from_socials(website_url="https://x.example")
    social_dna.capture_from_socials(website_url="https://x.example")
    # second call hits cache, not the handler
    assert call_count["n"] == 1


def test_force_bypasses_cache(isolated_cache, monkeypatch):
    call_count = {"n": 0}

    def counting_handler(**kw):
        call_count["n"] += 1
        return {
            "any_real": True,
            "state": {"website": {"url": "https://x.example",
                                    "status": "real_content",
                                    "playbook_age": 0,
                                    "regenerated": True,
                                    "voice_digest": "Demo."}},
            "merged_dna": {"voice_summary": "Demo voice.", "keywords": ["a"]},
        }
    monkeypatch.setattr(link_handlers, "process_links", counting_handler)

    social_dna.capture_from_socials(website_url="https://x.example")
    social_dna.capture_from_socials(website_url="https://x.example", force=True)
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 5. The legacy contract: output keys downstream code depends on
# ---------------------------------------------------------------------------

REQUIRED_KEYS = (
    "brand_voice_summary",
    "brand_keywords",
    "brand_palette_extracted",
    "brand_logo_url",
    "brand_typography_hint",
    "brand_phrases_to_avoid",
    "brand_phrases_to_use",
    "brand_source_url",
    "brand_captured_at",
    "brand_capture_status",
    "voice_profile",
    "social_links_status",
    "captions_captured",
    "link_capture_state",
)


def test_output_always_contains_all_required_keys(isolated_cache):
    out = social_dna.capture_from_socials(social_links={}, website_url="")
    for k in REQUIRED_KEYS:
        assert k in out, f"missing key {k!r} in capture output"


# ---------------------------------------------------------------------------
# 6. URL normalisation
# ---------------------------------------------------------------------------

def test_bare_host_gets_https_prefix(isolated_cache, monkeypatch):
    seen = {}

    def capture(**kw):
        seen.update(kw)
        return {"any_real": False, "state": {}, "merged_dna": {}}
    monkeypatch.setattr(link_handlers, "process_links", capture)

    social_dna.capture_from_socials(website_url="club.example")
    assert seen["website_url"] == "https://club.example"


def test_bare_handle_get_normalised_to_full_url(isolated_cache, monkeypatch):
    seen = {}

    def capture(**kw):
        seen.update(kw)
        return {"any_real": False, "state": {}, "merged_dna": {}}
    monkeypatch.setattr(link_handlers, "process_links", capture)

    social_dna.capture_from_socials(
        social_links={"instagram": "city.aquatics"},
    )
    # social_dna prepends https:// — the handler then runs its own
    # platform normalisation on top.
    assert seen["social_links"]["instagram"] == "https://city.aquatics"
