"""tests/test_bootstrap_extract.py — URL → draft DesignTokens onboarding.

`extract_brand_draft` pre-fills a brand-token draft from a club's
website for human confirmation. These tests mock the fetch (and, for the
semantic path, the LLM) and assert:

  - the draft is shaped like the DesignTokens contract (colour roles,
    palette candidates, logos by inferred form, font guesses);
  - EVERY field is "confirmed": false — nothing is auto-trusted;
  - deterministic extraction (hex scan, logo classification, font scan)
    works without an LLM, and the semantic colour/font roles stay null
    (never fabricated) when no provider is configured;
  - the LLM judgement step fills roles only from the extracted universe
    (hallucinated picks are dropped);
  - fetching reuses link_handlers' shared fetcher.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import bootstrap_extract  # noqa: E402


_CANNED_HTML = """
<!doctype html>
<html>
<head>
  <title>City Aquatics Swimming Club</title>
  <link rel="icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;700">
  <meta property="og:image" content="https://city.example/share.jpg">
  <style>
    body { background: #0b1f3a; color: #ffffff; font-family: "Inter", Arial, sans-serif; }
    h1 { font-family: 'Anton', sans-serif; }
    .brand { color: #a30d2d; }
    .accent { background: #ffd86e; }
    .x { font-family: Oswald; }
  </style>
</head>
<body>
  <img src="/img/logo-horizontal-white.svg" alt="City Aquatics logo" width="600" height="120">
  <img src="/img/badge.png" class="logo" width="200" height="200">
  <p>An inclusive community swimming club.</p>
</body>
</html>
"""

# Chromatic hexes the shared scanner keeps (pure white #ffffff is dropped).
_EXPECTED_CANDIDATES = {"#0b1f3a", "#a30d2d", "#ffd86e"}


def _fake_fetch_ok(_url):
    return _CANNED_HTML, 200


@pytest.fixture
def llm_off(monkeypatch):
    """Force the LLM 'unavailable' so tests don't depend on env keys."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    return _llm


# ---------------------------------------------------------------------------
# Recursive "confirmed: false" walker — the load-bearing honesty check.
# ---------------------------------------------------------------------------

def _collect_confirmed(obj) -> list:
    flags = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "confirmed":
                flags.append(v)
            flags.extend(_collect_confirmed(v))
    elif isinstance(obj, list):
        for item in obj:
            flags.extend(_collect_confirmed(item))
    return flags


def _assert_all_confirmed_false(draft) -> None:
    flags = _collect_confirmed(draft)
    assert flags, "draft carries no confirmed flags at all"
    assert all(f is False for f in flags), \
        f"found a confirmed flag that is not False: {flags}"


# ---------------------------------------------------------------------------
# 1. Shape + confirmed:false on the deterministic (no-LLM) path.
# ---------------------------------------------------------------------------

def test_draft_shape_without_llm(monkeypatch, llm_off):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    draft = bootstrap_extract.extract_brand_draft("city.example")

    # Top-level shape.
    assert draft["version"] == bootstrap_extract.DRAFT_VERSION
    assert draft["source_url"] == "https://city.example"
    assert draft["confirmed"] is False
    assert draft["reliability"] == "low"
    assert draft["fetch"] == {"status": "ok", "http_status": 200}
    assert "extracted_at" in draft and draft["extracted_at"]
    assert isinstance(draft["notes"], list) and draft["notes"]

    tokens = draft["tokens"]
    # Colour roles present with contract metadata; no hex without an LLM.
    for role in ("brand", "accent", "surface", "on_surface"):
        slot = tokens["colours"][role]
        assert set(slot) == {"hex", "brightness", "when_to_use",
                             "confidence", "confirmed"}
        assert slot["hex"] is None
        assert slot["confidence"] == "none"
        assert slot["when_to_use"]
        assert slot["confirmed"] is False

    # Palette candidates are deterministic facts — present even with no LLM.
    cand_hexes = {c["hex"] for c in tokens["palette_candidates"]}
    assert _EXPECTED_CANDIDATES <= cand_hexes
    assert "#ffffff" not in cand_hexes  # pure white dropped by the scanner
    for c in tokens["palette_candidates"]:
        assert 0.0 <= c["brightness"] <= 1.0
        assert c["confirmed"] is False

    # Fonts extracted; type roles null without an LLM.
    assert "Anton" in tokens["type"]["fonts_found"]
    assert "Inter" in tokens["type"]["fonts_found"]
    assert tokens["type"]["title"]["family"] is None
    assert tokens["type"]["body"]["family"] is None

    # Honest: interpretation unavailable, and a note says so.
    assert draft["interpretation"]["available"] is False
    assert any("not configured" in n for n in draft["notes"])

    _assert_all_confirmed_false(draft)


def test_no_field_ever_confirmed_true(monkeypatch, llm_off):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    draft = bootstrap_extract.extract_brand_draft("city.example")
    assert True not in _collect_confirmed(draft)


# ---------------------------------------------------------------------------
# 2. Logos grouped by inferred form / theme (deterministic).
# ---------------------------------------------------------------------------

def test_logo_form_and_theme_inference(monkeypatch, llm_off):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    logos = bootstrap_extract.extract_brand_draft("city.example")["tokens"]["logos"]
    by_url = {l["url"]: l for l in logos}

    fav = by_url["https://city.example/favicon.ico"]
    assert fav["form"] == "icon"
    assert fav["source"] == "link-icon"
    assert fav["confidence"] == "high"

    horiz = by_url["https://city.example/img/logo-horizontal-white.svg"]
    # canonical DesignTokens lockup vocabulary (brand/design_tokens.py)
    assert horiz["form"] == "full_horizontal"   # inferred from filename
    assert horiz["theme"] == "light"       # "white" → light-on-dark mark
    assert horiz["source"] == "img"

    badge = by_url["https://city.example/img/badge.png"]
    assert badge["form"] == "icon"         # "badge" keyword

    share = by_url["https://city.example/share.jpg"]
    assert share["form"] == "unknown"      # og:image may not be a logo
    assert share["confidence"] == "low"

    assert all(l["confirmed"] is False for l in logos)


# ---------------------------------------------------------------------------
# 3. Fonts: families extracted, generic fallbacks filtered out.
# ---------------------------------------------------------------------------

def test_fonts_extracted_and_generics_filtered(monkeypatch, llm_off):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    fonts = bootstrap_extract.extract_brand_draft("city.example")["tokens"]["type"]["fonts_found"]
    assert {"Anton", "Inter", "Oswald"} <= set(fonts)
    lowered = {f.lower() for f in fonts}
    assert "sans-serif" not in lowered
    assert "arial" not in lowered


# ---------------------------------------------------------------------------
# 4. Semantic roles via the LLM — filled only from the extracted universe.
# ---------------------------------------------------------------------------

def test_semantic_roles_filled_by_llm(monkeypatch):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    from mediahub.media_ai import llm as _llm

    def fake_generate_json(prompt, *, system, max_tokens, fallback):
        # on_surface picks pure white, which the scanner dropped → must be
        # rejected as a hallucination (not in the candidate universe).
        return {
            "brand": "#a30d2d",
            "accent": "#ffd86e",
            "surface": "#0b1f3a",
            "on_surface": "#ffffff",
            "title_font": "Anton",
            "body_font": "Inter",
            "reasoning": "Red is most prominent; navy is the dark ground.",
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_generate_json)

    draft = bootstrap_extract.extract_brand_draft("city.example")
    colours = draft["tokens"]["colours"]

    assert colours["brand"]["hex"] == "#a30d2d"
    assert colours["brand"]["confidence"] == "medium"   # never "high"
    assert colours["brand"]["brightness"] is not None
    assert colours["accent"]["hex"] == "#ffd86e"
    assert colours["surface"]["hex"] == "#0b1f3a"
    # Hallucinated colour dropped:
    assert colours["on_surface"]["hex"] is None
    assert colours["on_surface"]["confidence"] == "none"

    assert draft["tokens"]["type"]["title"]["family"] == "Anton"
    assert draft["tokens"]["type"]["body"]["family"] == "Inter"

    assert draft["interpretation"]["available"] is True
    assert draft["interpretation"]["reasoning"]

    # Even with roles filled, nothing is confirmed.
    _assert_all_confirmed_false(draft)


def test_llm_invented_font_is_dropped(monkeypatch):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", _fake_fetch_ok)
    from mediahub.media_ai import llm as _llm

    def fake_generate_json(prompt, *, system, max_tokens, fallback):
        return {"title_font": "Comic Sans MS", "body_font": "Inter"}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_generate_json)

    draft = bootstrap_extract.extract_brand_draft("city.example")
    # "Comic Sans MS" was never on the page → dropped; "Inter" was.
    assert draft["tokens"]["type"]["title"]["family"] is None
    assert draft["tokens"]["type"]["body"]["family"] == "Inter"


# ---------------------------------------------------------------------------
# 5. Honest failure when the page can't be read.
# ---------------------------------------------------------------------------

def test_unreachable_url_returns_honest_empty_draft(monkeypatch, llm_off):
    monkeypatch.setattr(bootstrap_extract, "_fetch_html", lambda _u: ("", 0))
    draft = bootstrap_extract.extract_brand_draft("nope.invalid")

    assert draft["fetch"]["status"] == "unreachable"
    assert draft["tokens"]["palette_candidates"] == []
    assert draft["tokens"]["logos"] == []
    assert draft["tokens"]["type"]["fonts_found"] == []
    for role in ("brand", "accent", "surface", "on_surface"):
        assert draft["tokens"]["colours"][role]["hex"] is None
    assert draft["interpretation"]["available"] is False
    assert any("could not be read" in n for n in draft["notes"])
    _assert_all_confirmed_false(draft)


def test_empty_url_does_not_crash(llm_off):
    draft = bootstrap_extract.extract_brand_draft("")
    assert draft["source_url"] == ""
    assert draft["fetch"]["status"] == "unreachable"
    _assert_all_confirmed_false(draft)


# ---------------------------------------------------------------------------
# 6. Fetching reuses the link_handlers fetcher (read-only).
# ---------------------------------------------------------------------------

def test_reuses_link_handlers_fetcher(monkeypatch, llm_off):
    """Patch the *underlying* link_handlers seam (not bootstrap's wrapper)
    to prove extraction flows through link_handlers' shared fetcher."""
    from mediahub.brand import link_handlers

    def fake_fetch_with_strategy(url, strat):
        return _CANNED_HTML, 200, {}

    monkeypatch.setattr(link_handlers, "_fetch_with_strategy",
                        fake_fetch_with_strategy)

    draft = bootstrap_extract.extract_brand_draft("city.example")
    assert draft["fetch"]["status"] == "ok"
    cand_hexes = {c["hex"] for c in draft["tokens"]["palette_candidates"]}
    assert _EXPECTED_CANDIDATES <= cand_hexes
    _assert_all_confirmed_false(draft)
