"""tests/test_link_learners.py — B7-B10. The five LLM-driven capabilities.

These tests exercise the deterministic fallback paths (no LLM
configured) and a handful of LLM-pretend paths via monkeypatch on
``mediahub.media_ai.llm.generate_json`` and ``is_available``. Together
they confirm:

  - Each learner returns a valid output shape even when no LLM is
    reachable (so MediaHub keeps working on offline / quota-failed
    deployments).
  - When an LLM response is well-formed it overrides the heuristic.
  - When an LLM response is malformed the learner falls back rather
    than crashing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand.link_learners import (  # noqa: E402
    block_detector, content_extractor, endpoint_discoverer, strategy,
)


@pytest.fixture
def no_llm(monkeypatch):
    """Force every learner down its heuristic fallback path."""
    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: False, raising=False)
    yield


@pytest.fixture
def fake_llm(monkeypatch):
    """Programmable LLM stub. Yields a dict that tests can mutate to
    set the response for the next generate_json call."""
    box = {"response": {}}

    def fake_is_available():
        return True

    def fake_generate_json(prompt, system="", max_tokens=0, fallback=None, **kw):
        return box["response"]

    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", fake_is_available, raising=False)
    monkeypatch.setattr(_llm, "generate_json", fake_generate_json, raising=False)
    yield box


# ---------------------------------------------------------------------------
# B7 — strategy proposer
# ---------------------------------------------------------------------------

class TestStrategyProposer:

    def test_no_llm_returns_default_strategy(self, no_llm):
        out = strategy.propose_strategy("https://www.example.com/foo")
        assert out["url_template"] == "https://www.example.com/foo"
        assert out["parser"] == "html"
        assert out["notes"]

    def test_llm_response_drives_strategy(self, fake_llm):
        fake_llm["response"] = {
            "url_template": "https://www.example.com/{handle}/embed/",
            "headers": {"User-Agent": "Custom UA"},
            "parser": "oembed",
            "selectors_or_jsonpath": ["$.html"],
            "alt_endpoints": ["https://r.jina.ai/https://www.example.com/{handle}/"],
            "notes": "oEmbed returns clean HTML.",
        }
        out = strategy.propose_strategy("https://www.example.com/foo",
                                          platform_intent="Instagram bio")
        assert out["url_template"] == "https://www.example.com/{handle}/embed/"
        assert out["parser"] == "oembed"
        # Default headers must remain present even if LLM omitted them
        assert "User-Agent" in out["headers"]
        # Custom header overrides the default
        assert out["headers"]["User-Agent"] == "Custom UA"
        assert out["alt_endpoints"] == ["https://r.jina.ai/https://www.example.com/{handle}/"]

    def test_llm_bad_shape_falls_back_to_url(self, fake_llm):
        fake_llm["response"] = "not a dict"  # garbage
        out = strategy.propose_strategy("https://www.example.com/foo")
        assert out["url_template"] == "https://www.example.com/foo"
        assert out["parser"] == "html"

    def test_invalid_parser_drops_to_html(self, fake_llm):
        fake_llm["response"] = {"parser": "magic-parser"}
        out = strategy.propose_strategy("https://x.com/foo")
        assert out["parser"] == "html"


# ---------------------------------------------------------------------------
# B8 — block detector
# ---------------------------------------------------------------------------

class TestBlockDetector:

    def test_404_is_not_found(self):
        out = block_detector.classify("https://x", status_code=404, body="")
        assert out["label"] == "not_found"

    def test_429_is_rate_limited(self):
        out = block_detector.classify("https://x", status_code=429, body="")
        assert out["label"] == "rate_limited"

    def test_403_is_auth_walled(self):
        out = block_detector.classify("https://x", status_code=403, body="")
        assert out["label"] == "auth_walled"

    def test_real_content_for_long_body(self):
        body = "<html><body>" + "<p>This is a real club with about us text. </p>" * 20 + "</body></html>"
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "real_content"

    def test_empty_body_is_soft_blocked(self):
        out = block_detector.classify("https://x", status_code=200, body="")
        assert out["label"] == "soft_blocked_spa"

    def test_captcha_text_is_hard_blocked(self):
        body = "<html><body><h1>Please complete this captcha to continue.</h1></body></html>"
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "hard_blocked"

    def test_sign_in_with_short_body_is_auth_walled(self):
        body = "<html><body>Sign in to continue</body></html>"
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "auth_walled"

    # --- False-positive guards. A misclassification here discards ALL
    # captured brand voice from the link (real_content-only extraction),
    # so these club-site shapes must NOT be walled / 404'd / SPA'd. ---

    def test_club_homepage_with_signin_link_is_real_content(self):
        # A real club page that merely links to a members' "Sign in"
        # area must keep its content, not get auth-walled.
        body = (
            "<html><body><h1>City of Glasgow Swim Team</h1>"
            "<p>We are a friendly competitive swimming club based in the "
            "west end. Our squads train six days a week across three pools. "
            "New members always welcome — come along to a taster session "
            "and meet our coaches. We compete across Scotland and pride "
            "ourselves on community spirit.</p>"
            "<nav><a href='/members'>Sign in</a></nav></body></html>"
        )
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "real_content"

    def test_prose_could_not_be_resolved_is_not_dns_error(self):
        # "could not be resolved" in ordinary prose is not a DNS failure.
        body = ("<html><body><h1>Our Club</h1>"
                + "<p>A long and storied history of success here. " * 30
                + "<p>After the 2019 dispute could not be resolved, the "
                "committee was reformed.</p></body></html>")
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "real_content"

    def test_create_account_cta_is_not_auth_walled(self):
        body = ("<html><body><h1>Annual Gala 2026</h1>"
                + "<p>Join us for our biggest meet of the year. " * 25
                + "<p>Create account to register for the gala.</p></body></html>")
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "real_content"

    def test_tiny_real_club_paragraph_is_real_content(self):
        body = ("<html><body><p>Paisley Otters is a masters swimming club "
                "training Tuesday and Thursday evenings at the Lagoon.</p>"
                "</body></html>")
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "real_content"

    def test_real_dns_error_json_is_not_found(self):
        body = ('{"name":"ParamValidationError","message":'
                '"Domain example.org could not be resolved"}')
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "not_found"

    def test_react_spa_shell_is_soft_blocked(self):
        body = ("<html><body><div id=root>You need to enable JavaScript "
                "to run this app.</div></body></html>")
        out = block_detector.classify("https://x", status_code=200, body=body)
        assert out["label"] == "soft_blocked_spa"


# ---------------------------------------------------------------------------
# B9 — endpoint discoverer
# ---------------------------------------------------------------------------

class TestEndpointDiscoverer:

    def test_no_llm_produces_fallback_candidates(self, no_llm):
        cands = endpoint_discoverer.propose_alternatives(
            "https://www.example.com/page",
        )
        assert cands
        # Should include the readability gateway transform
        assert any("r.jina.ai" in c for c in cands)

    def test_llm_response_used_when_valid(self, fake_llm):
        fake_llm["response"] = {
            "candidates": [
                "https://www.example.com/page/about",
                "https://m.example.com/page",
                "https://web.archive.org/web/2024/https://www.example.com/page",
            ]
        }
        cands = endpoint_discoverer.propose_alternatives(
            "https://www.example.com/page",
        )
        assert "https://www.example.com/page/about" in cands
        assert len(cands) <= 4

    def test_llm_garbage_falls_back_to_transforms(self, fake_llm):
        fake_llm["response"] = "garbage"
        cands = endpoint_discoverer.propose_alternatives(
            "https://www.example.com/page",
        )
        assert cands
        assert any("r.jina.ai" in c for c in cands)

    def test_filters_tokens_and_secrets(self, fake_llm):
        fake_llm["response"] = {
            "candidates": [
                "https://api.example.com/private?access_token=abc",
                "https://www.example.com/page/about",
            ]
        }
        cands = endpoint_discoverer.propose_alternatives(
            "https://www.example.com/page",
        )
        assert all("access_token" not in c for c in cands)


# ---------------------------------------------------------------------------
# B10 — content extractor
# ---------------------------------------------------------------------------

class TestContentExtractor:

    def test_no_llm_returns_heuristic_summary(self, no_llm):
        text = ("City Aquatics is an inclusive community swimming club. "
                "#ClubLife #PBseason")
        out = content_extractor.extract_brand_dna(
            text, url="https://x", platform_intent="Instagram bio",
        )
        assert out["voice_summary"]   # heuristic prefix of text
        assert "#ClubLife" in out["hashtag_patterns"]
        assert "#PBseason" in out["hashtag_patterns"]

    def test_empty_input(self):
        out = content_extractor.extract_brand_dna("")
        assert out["voice_summary"] == ""
        assert out["keywords"] == []

    def test_llm_response_drives_dna(self, fake_llm):
        fake_llm["response"] = {
            "voice_summary": "An inclusive grassroots club, warm and direct.",
            "keywords": ["inclusive", "grassroots", "community"],
            "phrases_to_use": ["shout-out to the squad", "celebrate every effort"],
            "phrases_to_avoid": ["elite only"],
            "palette_mentions": ["#0066cc"],
            "typography_hint": "sans",
            "sponsor_mentions": [],
            "hashtag_patterns": ["#ClubLife"],
        }
        out = content_extractor.extract_brand_dna(
            "<html><body>City Aquatics</body></html>",
            url="https://x", platform_intent="website",
        )
        assert out["voice_summary"].startswith("An inclusive grassroots")
        assert "inclusive" in out["keywords"]
        assert out["typography_hint"] == "sans"
        assert "#0066cc" in out["palette_mentions"]

    def test_llm_empty_falls_back_to_heuristic(self, fake_llm):
        fake_llm["response"] = {"voice_summary": "", "keywords": []}
        out = content_extractor.extract_brand_dna(
            "City Aquatics #ClubLife", url="https://x", platform_intent="",
        )
        # heuristic picked up the hashtag
        assert "#ClubLife" in out["hashtag_patterns"]

    def test_palette_normalisation(self, fake_llm):
        fake_llm["response"] = {
            "voice_summary": "x",
            "keywords": ["a"],
            "palette_mentions": ["#06C", "0066cc", "#GGGGGG"],
        }
        out = content_extractor.extract_brand_dna("x")
        # 3-digit expanded, missing # prepended, invalid hex dropped
        assert "#0066cc" in out["palette_mentions"]
        assert len([c for c in out["palette_mentions"] if c.startswith("#")]) == len(out["palette_mentions"])

    def test_full_body_hex_merged_with_llm_palette(self, fake_llm):
        # The LLM only sees the first ~6KB of body. The real brand
        # colour (#f4b214 gold) lives further down in a <style> block.
        # The LLM returns only the visible-header white; the regex scan
        # of the FULL body must merge the gold in so the resolver has a
        # real candidate. (Regression for the cocsc.co.uk all-white bug.)
        fake_llm["response"] = {
            "voice_summary": "Competitive club.",
            "keywords": ["swimming"],
            "palette_mentions": ["#ffffff"],
        }
        body = (
            "<html><head><style>body{color:#ffffff}</style></head><body>"
            + "padding text. " * 600
            + "<style>.brand{background:#f4b214}</style></body></html>"
        )
        out = content_extractor.extract_brand_dna(
            body, url="https://x", platform_intent="website",
        )
        assert "#f4b214" in out["palette_mentions"], out["palette_mentions"]

    def test_full_body_scan_skips_pure_white_and_grey(self, fake_llm):
        # The merged scan must not flood the candidates with #ffffff /
        # near-grey UI tokens — only chromatic colours are added.
        fake_llm["response"] = {"voice_summary": "x", "keywords": ["a"],
                                "palette_mentions": []}
        body = ("<html><body>" + "x " * 400
                + "<div style='color:#ffffff;background:#eeeeee;border:#333333'>"
                "<span style='color:#c0392b'>brand</span></div></body></html>")
        out = content_extractor.extract_brand_dna(
            body, url="https://x", platform_intent="website",
        )
        assert "#c0392b" in out["palette_mentions"]
        assert "#ffffff" not in out["palette_mentions"]
        assert "#eeeeee" not in out["palette_mentions"]
