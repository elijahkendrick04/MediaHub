"""P1.5 — local brand-DNA-from-URL with no paid API.

Pins the three legs of the flow:
  * **local scrape, SSRF-safe** — the page/CSS/image fetches refuse private,
    loopback and link-local hosts, re-validated on every redirect hop;
  * **local colour science** — `materialyoucolor` quantize+score turns the
    club's real logo pixels into deterministic, provenance-carrying palette
    evidence, and the deterministic no-provider path grounds its palette in
    that evidence (a real deterministic path, never an invented palette);
  * **local model slot** — the one judgement step rides ``media_ai.llm``,
    which serves a keyless OpenAI-compatible endpoint (Ollama via
    ``MEDIAHUB_LLM_ENDPOINTS``); LLM palette picks are validated against the
    evidence universe (anti-hallucination).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from mediahub.brand import dna_capture
from mediahub.brand.palette_evidence import gather_image_evidence, image_colour_candidates

MAROON = "#7f1d2b"
GOLD = "#f5c542"


@pytest.fixture
def isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def no_llm_env(monkeypatch):
    for var in (
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MEDIAHUB_LLM_ENDPOINTS",
        "MEDIAHUB_LLM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
    from mediahub.web import secrets_store

    monkeypatch.setattr(secrets_store, "_SECRETS_PATH", Path("/tmp/__no_such_secrets__.json"))
    yield


def _two_colour_png() -> bytes:
    """A 64×64 PNG: maroon left half, gold right half."""
    from PIL import Image

    img = Image.new("RGB", (64, 64))
    maroon = tuple(int(MAROON[i : i + 2], 16) for i in (1, 3, 5))
    gold = tuple(int(GOLD[i : i + 2], 16) for i in (1, 3, 5))
    for x in range(64):
        for y in range(64):
            img.putpixel((x, y), maroon if x < 32 else gold)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_HTML = f"""
<html><head>
<title>Lakeside Swimming Club</title>
<meta property="og:image" content="/img/og.png">
<style>.a {{ color: {MAROON}; }} .b {{ color: {MAROON}; }} .c {{ color: #2266aa; }}</style>
</head>
<body><header><img src="/static/logo.png" alt="Lakeside SC logo"></header>
<h1>Welcome</h1></body></html>
""".strip()


# ---------------------------------------------------------------------------
# SSRF safety — local scrape refuses non-public hosts
# ---------------------------------------------------------------------------


class TestSSRF:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost/internal",
            "ftp://example.com/x",
        ],
    )
    def test_unsafe_urls_never_fetch(self, url, isolated_data_dir, no_llm_env):
        out = dna_capture.capture_brand_dna(url, force=True)
        assert out["brand_capture_status"] == "fetch_failed"

    def test_redirect_to_private_host_is_blocked(self, monkeypatch):
        class _Resp:
            status_code = 302
            headers = {"Location": "http://127.0.0.1/internal"}
            text = ""

        calls: list[str] = []

        def fake_get(url, **kw):
            calls.append(url)
            assert kw.get("allow_redirects") is False
            return _Resp()

        import requests

        monkeypatch.setattr(requests, "get", fake_get)
        monkeypatch.setattr(dna_capture, "_url_is_safe", lambda u: "127.0.0.1" not in u)
        assert dna_capture._fetch("https://club.example/") is None
        # The private hop was validated and refused before any request.
        assert all("127.0.0.1" not in u for u in calls)

    def test_css_fetcher_blocks_unsafe_hosts(self, monkeypatch):
        import requests

        def explode(*a, **k):  # the gate must trip before any HTTP happens
            raise AssertionError("HTTP request should not have been attempted")

        monkeypatch.setattr(requests, "get", explode)
        assert dna_capture._default_css_fetcher("http://127.0.0.1/site.css") is None

    def test_image_fetch_blocks_unsafe_hosts(self):
        from mediahub.brand.palette_evidence import fetch_image_bytes

        assert fetch_image_bytes("http://127.0.0.1/logo.png") is None
        assert fetch_image_bytes("http://169.254.169.254/x.png") is None


# ---------------------------------------------------------------------------
# Local colour science — pixels → deterministic, provenance-carrying evidence
# ---------------------------------------------------------------------------


class TestImageEvidence:
    def test_quantize_finds_the_real_brand_colours(self):
        cands = image_colour_candidates(_two_colour_png())
        hexes = {c["hex"] for c in cands}
        assert MAROON in hexes and GOLD in hexes
        assert all(c["rank"] >= 1 and 0 <= c["population_share"] <= 1 for c in cands)

    def test_quantize_is_deterministic(self):
        png = _two_colour_png()
        assert image_colour_candidates(png) == image_colour_candidates(png)

    def test_undecodable_image_yields_no_candidates(self):
        assert image_colour_candidates(b"not an image") == []
        assert image_colour_candidates(b"") == []

    def test_gather_image_evidence_uses_injected_fetcher(self):
        png = _two_colour_png()
        seen: list[str] = []

        def fake_fetch(url: str):
            seen.append(url)
            return png if "logo" in url else None

        ev = gather_image_evidence(
            logo_url="https://club.example/static/logo.png",
            og_image_url="https://club.example/img/og.png",
            image_fetcher=fake_fetch,
        )
        assert {c["hex"] for c in ev["logo"]} >= {MAROON, GOLD}
        assert ev["og_image"] == []
        assert len(seen) == 2

    def test_evidence_orders_logo_pixels_first_with_provenance(self):
        signals = dna_capture._extract_signals(_HTML, "https://club.example/")
        ev = dna_capture.gather_palette_evidence(
            _HTML,
            "https://club.example/",
            signals,
            css_fetcher=lambda u: None,
            image_fetcher=lambda u: _two_colour_png() if "logo" in u else None,
        )
        assert ev["ordered"], "expected colour evidence"
        top_src = ev["sources"][ev["ordered"][0]]
        assert "logo pixels" in top_src
        # CSS-usage colours are present further down with usage provenance.
        assert any("used" in s and "CSS" in s for s in ev["sources"].values())


# ---------------------------------------------------------------------------
# No provider — honest gap, evidence-grounded deterministic palette
# ---------------------------------------------------------------------------


class TestNoProvider:
    def test_palette_grounded_in_logo_pixels_voice_left_empty(
        self, isolated_data_dir, no_llm_env, monkeypatch
    ):
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _HTML)
        out = dna_capture.capture_brand_dna(
            "https://club.example/",
            force=True,
            css_fetcher=lambda u: None,
            image_fetcher=lambda u: _two_colour_png() if "logo" in u else None,
        )
        assert out["brand_capture_status"] == "no_provider"
        # The palette is real evidence (the club's own pixels), not a guess…
        assert out["brand_palette_extracted"].get("primary") in {MAROON, GOLD}
        assert any("logo pixels" in s for s in out["brand_palette_sources"].values())
        assert "evidence-strength" in out["brand_palette_reasoning"]
        # …and the judgement fields stay honestly empty.
        assert out["brand_voice_summary"] == ""
        assert out["brand_keywords"] == []


# ---------------------------------------------------------------------------
# LLM merge — anti-hallucination against the evidence universe
# ---------------------------------------------------------------------------


class TestAntiHallucination:
    def test_invented_hex_is_dropped_and_backfilled(self, isolated_data_dir, monkeypatch):
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _HTML)
        monkeypatch.setattr(
            dna_capture,
            "_call_llm",
            lambda signals, url, evidence=None: {
                "voice_summary": "A proud community swimming club with a competitive edge.",
                "keywords": ["swimming", "community"],
                "phrases_to_use": ["see you poolside"],
                "phrases_to_avoid": ["synergy"],
                # primary is a colour the site never exhibited → must be dropped
                "palette": {"primary": "#123456", "secondary": MAROON, "accent": GOLD},
                "typography_hint": "sans",
            },
        )
        out = dna_capture.capture_brand_dna(
            "https://club.example/",
            force=True,
            css_fetcher=lambda u: None,
            image_fetcher=lambda u: _two_colour_png() if "logo" in u else None,
        )
        assert out["brand_capture_status"] == "ok"
        pal = out["brand_palette_extracted"]
        assert "#123456" not in pal.values()
        assert pal["secondary"] == MAROON and pal["accent"] == GOLD
        # The dropped slot is backfilled from real evidence, provenance kept.
        assert pal["primary"] in dict(
            [(h, 1) for h in (MAROON, GOLD, "#2266aa")]
        ) or pal["primary"].startswith("#")
        assert out["brand_palette_sources"]["secondary"].startswith("ai pick")
        assert out["brand_palette_sources"]["primary"].startswith("evidence")
        assert "Dropped invented colour" in out["brand_palette_reasoning"]


# ---------------------------------------------------------------------------
# Local model slot — the judgement step with zero paid APIs
# ---------------------------------------------------------------------------


class TestLocalModelSlot:
    def test_keyless_local_endpoint_drives_the_capture(
        self, isolated_data_dir, no_llm_env, monkeypatch
    ):
        # Configure ONLY a local OpenAI-compatible endpoint — no cloud keys.
        monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "http://127.0.0.1:11434/v1")
        monkeypatch.setenv("MEDIAHUB_LLM_PROVIDER", "openai")

        from mediahub.media_ai import llm as media_llm

        assert media_llm.is_available(), "local endpoint alone must enable the AI surface"
        assert media_llm.active_provider() == "openai-api"

        # Mock the HTTP boundary (the local model's reply), not the flow.
        def fake_call_openai(messages, system, max_tokens, **kw):
            return json.dumps(
                {
                    "voice_summary": "Friendly, competitive, community-first swimming club.",
                    "keywords": ["swimming", "club", "community"],
                    "phrases_to_use": ["poolside pride"],
                    "phrases_to_avoid": ["synergy"],
                    "palette": {"primary": MAROON, "secondary": GOLD, "accent": "#2266aa"},
                    "typography_hint": "sans",
                }
            )

        from mediahub.media_ai import llm_providers

        monkeypatch.setattr(llm_providers, "call_openai", fake_call_openai)
        monkeypatch.setattr(dna_capture, "_fetch", lambda u: _HTML)

        out = dna_capture.capture_brand_dna(
            "https://club.example/",
            force=True,
            css_fetcher=lambda u: None,
            image_fetcher=lambda u: _two_colour_png() if "logo" in u else None,
        )
        assert out["brand_capture_status"] == "ok"
        assert out["brand_voice_summary"].startswith("Friendly")
        assert out["brand_palette_extracted"]["primary"] == MAROON
        assert out["brand_palette_sources"]["primary"].startswith("ai pick")
