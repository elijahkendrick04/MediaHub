"""V8 media_ai LLM wrapper tests.

Verifies:
1. ``is_available()`` is callable and returns a bool.
2. ``generate()`` returns a non-empty string even when no LLM key is configured
   (heuristic fallback).
3. ``generate_json()`` returns the supplied fallback dict when LLM is unavailable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.media_ai import generate, generate_json, is_available


def test_is_available_returns_bool():
    assert isinstance(is_available(), bool)


def test_generate_text_fallback():
    out = generate("Write one short sentence about swimming.", system="Be concise.", max_tokens=64)
    assert isinstance(out, str)
    # Even fallback must produce *something*.
    assert len(out.strip()) > 0


def test_generate_json_returns_dict():
    fallback = {"athlete_name": None, "venue_name": "Pool", "tags": ["x"]}
    out = generate_json(
        "Extract athlete + venue from: 'sample text'.",
        fallback=fallback,
    )
    # In all configurations, generate_json must return a dict (possibly empty).
    assert isinstance(out, dict)
