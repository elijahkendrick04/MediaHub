"""Regression — logo file names must never reach caption prompts.

Live bug (2026-06-04): a generated 'Precise' caption ended with the literal
file name "stockport_logo_crest.png". The logo inventory that
``brand_context_for_llm`` builds for asset-picking generators was included
in EVERY prompt — captions too — and the LLM echoed the raw file name into
published copy.

Pinned here:
  1. the inventory is excluded by default (text generators);
  2. asset-pickers can still opt in with ``include_logos=True``;
  3. even when included, a filename-derived label is humanised (no
     extension/underscores) and the prompt forbids echoing names.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand.context import brand_context_for_llm  # noqa: E402
from mediahub.web.club_profile import ClubProfile  # noqa: E402


def _prof():
    return ClubProfile(
        profile_id="metro",
        display_name="Stockport Metro Swimming Club",
        brand_voice_summary="Proud Wolfpack voice.",
        brand_logos=[
            {
                "logo_id": "x1",
                "original_filename": "stockport_logo_crest.png",
                "label": "",
                "mime": "image/png",
                "ai_description": "Howling wolf crest on royal blue.",
                "ai_dominant_colours": ["#3060d8"],
            }
        ],
    )


def test_default_context_has_no_logo_inventory():
    ctx = brand_context_for_llm(_prof())
    assert "logo variant" not in ctx
    assert (
        "stockport_logo_crest" not in ctx
    ), "raw logo identifiers leaked into the default (caption) prompt"


def test_opt_in_includes_inventory_without_raw_filename():
    ctx = brand_context_for_llm(_prof(), include_logos=True)
    assert "logo variant" in ctx
    assert (
        "stockport_logo_crest.png" not in ctx
    ), "filename fallback must be humanised, not the raw file name"
    assert "NEVER mention logo names" in ctx


def test_opt_in_keeps_explicit_labels():
    p = _prof()
    p.brand_logos[0]["label"] = "Royal blue crest"
    ctx = brand_context_for_llm(p, include_logos=True)
    assert "Royal blue crest" in ctx
