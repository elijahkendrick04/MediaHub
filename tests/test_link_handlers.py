"""tests/test_link_handlers.py — B1-B6 orchestration + drift detection.

The handler tests use heavy monkeypatching to stub HTTP + LLM so each
test runs in milliseconds. The seams we test through:

  - link_handlers._fetch_with_strategy(url, strategy)   — HTTP fetch
  - link_learners.content_extractor.extract_brand_dna   — DNA extraction
  - link_learners.block_detector.classify               — block decision
  - link_learners.strategy.propose_strategy             — new strategies
  - link_learners.endpoint_discoverer.propose_alternatives — alt URLs

Per-platform handlers (B1-B6) all delegate to the same orchestrator, so
once orchestration is verified we only need a smoke test per platform
to confirm intent + URL normalisation are wired correctly.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import link_handlers, playbooks  # noqa: E402
from mediahub.brand.link_handlers import (  # noqa: E402
    facebook, instagram, linkedin, tiktok, twitter, website,
)


@pytest.fixture
def iso_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def stubbed_pipeline(monkeypatch, iso_root):
    """Stub HTTP + the three LLM-driven learners so handler orchestration
    can be tested deterministically.

    Returns a dict whose values tests can mutate to change the next
    fetch / classify outcome.
    """
    state = {
        "fetch_responses": [],   # popped left-to-right
        "classify_label": "real_content",
        "dna": {
            "voice_summary": "An inclusive community swimming club.",
            "keywords": ["inclusive", "community"],
            "phrases_to_use": ["shout-out"],
            "phrases_to_avoid": [],
            "palette_mentions": ["#0066cc"],
            "typography_hint": "sans",
            "sponsor_mentions": [],
            "hashtag_patterns": ["#ClubLife"],
        },
        "strategy": {
            "url_template": "{handle}",  # marker the orchestrator expands
            "headers": {"User-Agent": "Test"},
            "parser": "html",
            "selectors_or_jsonpath": [],
            "alt_endpoints": [],
            "notes": "stub",
        },
        "alt_endpoints": [],
    }

    def fake_fetch(url, strat):
        if state["fetch_responses"]:
            body, code, hdrs = state["fetch_responses"].pop(0)
        else:
            body, code, hdrs = "<html><body>real org content</body></html>", 200, {}
        return body, code, hdrs

    def fake_classify(url, *, status_code=0, headers=None, body="", use_llm=True):
        return {
            "label": state["classify_label"],
            "reason": "stub",
            "source": "stub",
        }

    def fake_dna(text, *, url="", platform_intent=""):
        return dict(state["dna"])

    def fake_strategy(url, *, platform_intent="", sample=None):
        s = dict(state["strategy"])
        # Replace the marker so the orchestrator hits something concrete.
        if s["url_template"] == "{handle}":
            s["url_template"] = url
        return s

    def fake_alt(url, *, platform_intent="", last_status="", last_strategy=None):
        return list(state["alt_endpoints"])

    monkeypatch.setattr(link_handlers, "_fetch_with_strategy", fake_fetch)
    from mediahub.brand.link_learners import (
        block_detector, content_extractor, endpoint_discoverer,
        strategy as strategy_mod,
    )
    monkeypatch.setattr(block_detector, "classify", fake_classify)
    monkeypatch.setattr(content_extractor, "extract_brand_dna", fake_dna)
    monkeypatch.setattr(strategy_mod, "propose_strategy", fake_strategy)
    monkeypatch.setattr(endpoint_discoverer, "propose_alternatives", fake_alt)

    yield state


# ---------------------------------------------------------------------------
# 1. Per-platform smoke tests — INTENT + URL normalisation
# ---------------------------------------------------------------------------

def test_website_normalises_bare_host(stubbed_pipeline):
    out = website.process("city.example")
    assert out["platform"] == "website"
    assert out["url"] == "https://city.example"
    assert out["status"] == "real_content"


def test_instagram_normalises_bare_handle(stubbed_pipeline):
    out = instagram.process("city.aquatics")
    assert out["platform"] == "instagram"
    assert out["url"] == "https://www.instagram.com/city.aquatics/"


def test_instagram_normalises_at_handle(stubbed_pipeline):
    out = instagram.process("@city.aquatics")
    assert out["url"] == "https://www.instagram.com/city.aquatics/"


def test_facebook_normalises_bare_handle(stubbed_pipeline):
    out = facebook.process("CityAquatics")
    assert out["url"] == "https://www.facebook.com/CityAquatics"


def test_twitter_normalises_bare_handle(stubbed_pipeline):
    out = twitter.process("CityAquatics")
    assert out["url"] == "https://x.com/CityAquatics"


def test_tiktok_normalises_bare_handle(stubbed_pipeline):
    out = tiktok.process("CityAquatics")
    assert out["url"] == "https://www.tiktok.com/@CityAquatics"


def test_linkedin_normalises_bare_slug(stubbed_pipeline):
    out = linkedin.process("city-aquatics")
    assert out["url"] == "https://www.linkedin.com/company/city-aquatics"


# ---------------------------------------------------------------------------
# 2. Orchestration — playbook regenerated when stale
# ---------------------------------------------------------------------------

def test_first_run_regenerates_strategy(stubbed_pipeline, iso_root):
    out = instagram.process("city.aquatics")
    assert out["regenerated"] is True
    # Playbook persisted under instagram.com
    pb = playbooks.load("instagram.com")
    assert pb is not None
    assert pb["strategy"]["url_template"]
    # audit log records the regeneration
    log = playbooks.audit_tail()
    assert any(e.get("action") == "regenerate" for e in log)


def test_subsequent_fresh_call_replays_playbook(stubbed_pipeline, iso_root):
    instagram.process("city.aquatics")  # seed
    audit_before = len(playbooks.audit_tail(100))
    out = instagram.process("city.aquatics")
    assert out["regenerated"] is False
    audit_after = playbooks.audit_tail(100)
    assert audit_after[-1].get("action") == "replay"


def test_stale_playbook_regenerates(stubbed_pipeline, iso_root):
    # Seed a playbook with an old timestamp
    pb = playbooks.empty_playbook("instagram.com")
    pb["strategy"] = {"url_template": "https://www.instagram.com/{handle}/",
                       "headers": {"User-Agent": "Test"},
                       "parser": "html", "alt_endpoints": []}
    pb["last_validated_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    playbooks.save(pb)

    out = instagram.process("city.aquatics")
    assert out["regenerated"] is True


def test_streak_of_blocks_triggers_regeneration(stubbed_pipeline, iso_root):
    # Seed a fresh-but-broken playbook (recent timestamp, 3 failures)
    pb = playbooks.empty_playbook("instagram.com")
    pb["strategy"] = {"url_template": "https://www.instagram.com/{handle}/",
                       "headers": {"User-Agent": "Test"},
                       "parser": "html", "alt_endpoints": []}
    pb["last_validated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pb["history"] = [
        {"ts": "x", "status": "hard_blocked", "notes": ""},
        {"ts": "x", "status": "auth_walled", "notes": ""},
        {"ts": "x", "status": "hard_blocked", "notes": ""},
    ]
    playbooks.save(pb)

    out = instagram.process("city.aquatics")
    assert out["regenerated"] is True


# ---------------------------------------------------------------------------
# 3. Alternative-endpoint flow when primary is blocked
# ---------------------------------------------------------------------------

def test_blocked_primary_tries_alternative(stubbed_pipeline, iso_root):
    # First fetch: blocked. Second fetch: real_content.
    stubbed_pipeline["fetch_responses"] = [
        ("", 200, {}),  # soft-blocked
        ("<html><body>real content</body></html>", 200, {}),
    ]
    # Force classify to differentiate primary vs alt
    calls = {"n": 0}
    labels = ["soft_blocked_spa", "real_content"]

    from mediahub.brand.link_learners import block_detector

    def alternating_classify(url, *, status_code=0, headers=None, body="", use_llm=True):
        i = min(calls["n"], len(labels) - 1)
        calls["n"] += 1
        return {"label": labels[i], "reason": "stub", "source": "stub"}

    import mediahub.brand.link_learners.block_detector as bd
    bd.classify = alternating_classify  # monkeypatch directly
    stubbed_pipeline["alt_endpoints"] = ["https://r.jina.ai/https://www.instagram.com/city.aquatics/"]

    try:
        out = instagram.process("city.aquatics")
        assert out["status"] == "real_content"
    finally:
        # restore
        from mediahub.brand.link_learners.block_detector import classify as _orig
        # the stubbed_pipeline fixture sets the original stub back via monkeypatch teardown


# ---------------------------------------------------------------------------
# 4. process_links aggregator
# ---------------------------------------------------------------------------

def test_process_links_aggregates_per_link_state(stubbed_pipeline, iso_root):
    out = link_handlers.process_links(
        website_url="https://city.example",
        social_links={"instagram": "city.aquatics"},
    )
    assert out["any_real"] is True
    assert "website" in out["state"]
    assert "instagram" in out["state"]
    assert out["state"]["website"]["status"] == "real_content"
    # merged_dna picks the richest source
    assert out["merged_dna"]["voice_summary"]


def test_process_links_ignores_unknown_platforms(stubbed_pipeline, iso_root):
    out = link_handlers.process_links(
        social_links={"myspace": "https://myspace.com/x"},
    )
    # No known handler, no work done — but no crash.
    assert out["any_real"] is False
    assert "myspace" not in out["state"]


def test_process_links_empty_input(iso_root):
    out = link_handlers.process_links()
    assert out["any_real"] is False
    assert out["state"] == {}
    assert out["merged_dna"] == {}
