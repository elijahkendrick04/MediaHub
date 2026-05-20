"""tests/test_brand_palette.py — unified palette resolver.

The brand.palette module unifies colour signals from every source the
org supplied (website + social links + brand-guidelines document +
uploaded logos) and asks the cloud LLM (Gemini / Anthropic) to pick
the actual brand palette. There is no heuristic fallback — when no
provider is configured the resolver raises ClaudeUnavailableError
and the caller leaves the existing palette untouched.

Covered:
  1. gather_colour_sources merges every source, labelled, cleaned
  2. _normalise / sanitise_manual_palette guard against bad hex
  3. resolve_palette uses the LLM when available
  4. resolve_palette raises ClaudeUnavailableError when LLM is off
  5. LLM hallucinations (hex codes not in the supplied sources) are dropped
  6. effective_palette merges manual override on top of AI pick
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import palette  # noqa: E402


# ---------------------------------------------------------------------------
# 1. gather_colour_sources
# ---------------------------------------------------------------------------

def test_gather_merges_links_guidelines_and_logos():
    sources = palette.gather_colour_sources(
        link_palette_signals={
            "website": ["#0066cc", "#ff0000"],
            "instagram": ["#0066cc"],
        },
        brand_guidelines={"palette_mentions": ["#0066cc", "#f2a900"]},
        brand_logos=[
            {"label": "Navy on white", "ai_dominant_colours": ["#0066cc", "#ffffff"]},
            {"original_filename": "knockout.png", "ai_dominant_colours": ["#ffffff"]},
        ],
    )
    # One key per source, labelled
    assert "website (palette_mentions)" in sources
    assert "instagram (palette_mentions)" in sources
    assert "brand_guidelines (palette_mentions)" in sources
    assert any(k.startswith("logo: Navy on white") for k in sources)
    assert any(k.startswith("logo: knockout.png") for k in sources)


def test_gather_drops_invalid_hex_and_dedupes():
    sources = palette.gather_colour_sources(
        link_palette_signals={
            "website": ["#0066cc", "not-a-colour", "0066cc", "#fff", "#0066cc"],
        },
        brand_guidelines=None,
        brand_logos=None,
    )
    cleaned = sources["website (palette_mentions)"]
    assert "#0066cc" in cleaned
    assert "#ffffff" in cleaned  # #fff was normalised
    assert "not-a-colour" not in cleaned
    # Dedup: #0066cc only appears once
    assert cleaned.count("#0066cc") == 1


def test_gather_empty_inputs_return_empty_dict():
    assert palette.gather_colour_sources() == {}
    assert palette.gather_colour_sources(
        link_palette_signals={},
        brand_guidelines={"palette_mentions": []},
        brand_logos=[],
    ) == {}


# ---------------------------------------------------------------------------
# 2. sanitise_manual_palette
# ---------------------------------------------------------------------------

def test_sanitise_keeps_valid_hex_drops_garbage():
    out = palette.sanitise_manual_palette(
        primary="#A30D2D",
        secondary="not a colour",
        accent="#fff",
        fourth="#deadbeef",  # 8-char invalid for #rrggbb
        include_fourth=True,
    )
    assert out["primary"] == "#a30d2d"  # lowered
    assert "secondary" not in out
    assert out["accent"] == "#ffffff"   # expanded
    assert "fourth" not in out  # too long


def test_sanitise_ignores_fourth_when_checkbox_off():
    out = palette.sanitise_manual_palette(
        primary="#000000", secondary="#ffffff", accent="#ff0000",
        fourth="#00ff00", include_fourth=False,
    )
    assert "fourth" not in out


# ---------------------------------------------------------------------------
# 3 + 4. resolve_palette — LLM happy path + fallback
# ---------------------------------------------------------------------------

def test_resolve_uses_llm_when_available(monkeypatch):
    from mediahub.media_ai import llm as _llm

    def fake_generate_json(prompt, *, system, max_tokens, fallback):
        # Sanity: prompt mentions both label types
        assert "brand_guidelines" in prompt
        assert "logo:" in prompt
        return {
            "primary": "#0066CC",  # capitalised — should be normalised
            "secondary": "#f2a900",
            "accent": "#ffffff",
            "reasoning": "Primary in guidelines + logo; accent only on site.",
        }

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", fake_generate_json)

    sources = palette.gather_colour_sources(
        link_palette_signals={"website": ["#0066cc", "#ffffff"]},
        brand_guidelines={"palette_mentions": ["#0066cc", "#f2a900"]},
        brand_logos=[{"label": "primary", "ai_dominant_colours": ["#0066cc"]}],
    )
    out = palette.resolve_palette(
        org_name="City Aquatics", voice_summary="Inclusive community swimming.",
        sources=sources, allow_fourth=False,
    )
    assert out["primary"] == "#0066cc"
    assert out["secondary"] == "#f2a900"
    assert out["accent"] == "#ffffff"
    assert out["reasoning"].startswith("Primary")


def test_resolve_raises_when_llm_unavailable(monkeypatch):
    """When no cloud LLM provider is configured, resolve_palette raises
    ClaudeUnavailableError. Callers (web.py) wrap the call in
    try/except and leave the existing palette untouched."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: False)

    sources = palette.gather_colour_sources(
        link_palette_signals={"website": ["#000000", "#ff0000", "#ff0000"]},
        brand_guidelines={"palette_mentions": ["#ff0000", "#00aaff"]},
        brand_logos=None,
    )
    with pytest.raises(_llm.ClaudeUnavailableError):
        palette.resolve_palette(
            org_name="Demo", voice_summary="", sources=sources, allow_fourth=False,
        )


def test_resolve_drops_hallucinated_hex(monkeypatch):
    """The LLM is instructed to only pick from the supplied colours; if
    it picks a colour we didn't show it, we drop the slot."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm, "generate_json",
        lambda *a, **kw: {
            "primary": "#0066cc",      # legit (in sources)
            "secondary": "#abcdef",    # hallucinated
            "accent": "#ff0000",       # legit
        },
    )

    sources = palette.gather_colour_sources(
        link_palette_signals={"website": ["#0066cc", "#ff0000"]},
    )
    out = palette.resolve_palette(
        org_name="Demo", voice_summary="", sources=sources, allow_fourth=False,
    )
    assert out["primary"] == "#0066cc"
    assert out["accent"] == "#ff0000"
    # The hallucinated #abcdef is dropped — the slot is simply absent
    # from the result since there's no longer a heuristic backfill.
    assert out.get("secondary") != "#abcdef"


def test_resolve_returns_empty_when_no_sources(monkeypatch):
    """No colour signals at all → empty dict, no LLM call needed."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: False)
    assert palette.resolve_palette(
        org_name="x", voice_summary="", sources={}, allow_fourth=False,
    ) == {}


def test_is_chromatic_rejects_white_black_grey():
    # Achromatic — must be rejected.
    for h in ("#ffffff", "#000000", "#eeeeee", "#808080", "#1a1a1a", "#f5f5f5"):
        assert palette._is_chromatic(h) is False, h
    # Real brand colours — must pass.
    for h in ("#f4b214", "#003c71", "#a30d2d", "#0066cc", "#fdb913"):
        assert palette._is_chromatic(h) is True, h


def test_resolve_returns_empty_when_only_achromatic(monkeypatch):
    """A site whose only colour signal is white/grey has no real brand
    identity. The resolver must return {} rather than painting the whole
    palette white (the real-world cocsc.co.uk failure: all-white)."""
    from mediahub.media_ai import llm as _llm
    called = {"n": 0}

    def _should_not_run(*a, **kw):
        called["n"] += 1
        return {}

    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(_llm, "generate_json", _should_not_run)

    sources = palette.gather_colour_sources(
        link_palette_signals={"website": ["#ffffff", "#eeeeee", "#000000"]},
    )
    out = palette.resolve_palette(
        org_name="Demo", voice_summary="", sources=sources, allow_fourth=False,
    )
    assert out == {}
    # Bailed before spending an LLM call.
    assert called["n"] == 0


def test_resolve_keeps_white_as_accent_when_chromatic_present(monkeypatch):
    """White is still a valid accent as long as a chromatic colour
    anchors the palette (the cocsc.co.uk fix: gold primary + white)."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    monkeypatch.setattr(
        _llm, "generate_json",
        lambda *a, **kw: {"primary": "#f4b214", "secondary": "#ffffff",
                          "reasoning": "Gold primary, white for contrast."},
    )
    sources = palette.gather_colour_sources(
        link_palette_signals={"website": ["#ffffff", "#f4b214"]},
    )
    out = palette.resolve_palette(
        org_name="City of Chester SC", voice_summary="Competitive club.",
        sources=sources, allow_fourth=False,
    )
    assert out["primary"] == "#f4b214"
    assert out["secondary"] == "#ffffff"


# ---------------------------------------------------------------------------
# 5. effective_palette
# ---------------------------------------------------------------------------

def test_effective_palette_manual_overrides_extracted():
    out = palette.effective_palette(
        manual={"primary": "#aaaaaa"},
        extracted={"primary": "#000000", "secondary": "#ffffff",
                   "accent": "#ff0000"},
    )
    assert out["primary"] == "#aaaaaa"        # manual wins
    assert out["secondary"] == "#ffffff"      # extracted fallback
    assert out["accent"] == "#ff0000"


def test_effective_palette_drops_invalid_manual_slot():
    out = palette.effective_palette(
        manual={"primary": "garbage", "accent": "#abc"},
        extracted={"primary": "#0066cc", "accent": "#000000"},
    )
    assert out["primary"] == "#0066cc"  # garbage dropped, extracted used
    assert out["accent"] == "#aabbcc"   # short-form manual expanded


def test_effective_palette_fourth_only_present_when_set():
    out = palette.effective_palette(
        manual={"primary": "#000000"},
        extracted={"primary": "#ffffff", "secondary": "#ff0000"},
    )
    assert "fourth" not in out

    out = palette.effective_palette(
        manual={"fourth": "#00ff00"},
        extracted={"primary": "#000000"},
    )
    assert out["fourth"] == "#00ff00"
