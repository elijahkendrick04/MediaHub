"""V8.1 Issue 7 §5 — vision-based creative direction tests.

Verifies:
- Returns ``None`` when no Anthropic key is configured (no-API-key path).
- Returns ``None`` when the photo file is missing.
- Calls ``media_ai.llm.generate_vision`` with the photo path and a sane prompt.
- Caches the result to disk for 24h: a second call hits the cache and does
  not re-invoke the LLM.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.creative_brief import generator as gen_mod
from mediahub.creative_brief.generator import vision_creative_direction


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point the vision cache at a tmp dir so tests don't pollute the repo."""
    cache_dir = tmp_path / "vision_cache"
    monkeypatch.setattr(gen_mod, "_VISION_CACHE_DIR", cache_dir)
    return cache_dir


@pytest.fixture
def fake_photo(tmp_path):
    p = tmp_path / "photo.jpg"
    # Just needs to exist + have some bytes for the cache fingerprint.
    p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return p


# ---------------------------------------------------------------------------
# No-API-key path: must skip without raising
# ---------------------------------------------------------------------------

def test_returns_none_when_llm_unavailable(isolated_cache, fake_photo):
    with mock.patch.object(gen_mod, "_llm_available", return_value=False):
        out = vision_creative_direction(
            str(fake_photo), asset_id="a1", brand_id="b1", achievement_summary="200m PB",
        )
    assert out is None


def test_returns_none_when_photo_missing(isolated_cache, tmp_path):
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        out = vision_creative_direction(
            str(tmp_path / "does-not-exist.jpg"),
            asset_id="a1", brand_id="b1",
        )
    assert out is None


def test_returns_none_when_llm_call_raises(isolated_cache, fake_photo):
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.llm.generate_vision",
            side_effect=RuntimeError("boom"),
        ):
            out = vision_creative_direction(
                str(fake_photo), asset_id="a", brand_id="b",
            )
    assert out is None


# ---------------------------------------------------------------------------
# Happy path + cache
# ---------------------------------------------------------------------------

_DIRECTION = (
    "Position the swimmer slightly off-centre with a tight crop on the gaze. "
    "Lean into a cool, focused mood with deep navy and a single accent of brand blue."
)


def test_happy_path_calls_generate_vision_with_photo(isolated_cache, fake_photo):
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.llm.generate_vision", return_value=_DIRECTION,
        ) as gv:
            out = vision_creative_direction(
                str(fake_photo),
                asset_id="asset-1",
                brand_id="brand-1",
                achievement_summary="Eira Hughes — 200m Freestyle PB 2:08.41",
            )

    assert out == _DIRECTION
    assert gv.call_count == 1
    args, kwargs = gv.call_args
    image_paths = args[0]
    prompt = args[1]
    assert image_paths == [str(fake_photo)]
    assert isinstance(prompt, str) and len(prompt) > 20
    assert "Eira Hughes" in prompt or "200m" in prompt
    # System prompt is passed by keyword
    assert "system" in kwargs and isinstance(kwargs["system"], str)


def test_cache_hit_skips_second_llm_call(isolated_cache, fake_photo):
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.llm.generate_vision", return_value=_DIRECTION,
        ) as gv:
            out1 = vision_creative_direction(
                str(fake_photo), asset_id="a1", brand_id="b1",
            )
            out2 = vision_creative_direction(
                str(fake_photo), asset_id="a1", brand_id="b1",
            )

    assert out1 == _DIRECTION
    assert out2 == _DIRECTION
    # Critical: the second call MUST hit cache, not the LLM.
    assert gv.call_count == 1


def test_cache_busted_when_ttl_expires(isolated_cache, fake_photo, monkeypatch):
    """Spec: 24h TTL. Force the cache to look stale and confirm a re-call."""
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.llm.generate_vision", return_value=_DIRECTION,
        ) as gv:
            vision_creative_direction(
                str(fake_photo), asset_id="a1", brand_id="b1",
            )
            assert gv.call_count == 1

            # Move "now" forward by 25h so the cached entry is past TTL.
            real_time = time.time
            monkeypatch.setattr(
                gen_mod.time, "time",
                lambda: real_time() + (25 * 60 * 60),
            )
            vision_creative_direction(
                str(fake_photo), asset_id="a1", brand_id="b1",
            )
            assert gv.call_count == 2


def test_different_assets_get_different_cache_keys(isolated_cache, fake_photo):
    k1 = gen_mod._vision_cache_key("asset-A", "brand-1", str(fake_photo))
    k2 = gen_mod._vision_cache_key("asset-B", "brand-1", str(fake_photo))
    k3 = gen_mod._vision_cache_key("asset-A", "brand-2", str(fake_photo))
    assert k1 != k2
    assert k1 != k3


def test_returns_none_for_too_short_response(isolated_cache, fake_photo):
    """If the model returns a stub or empty string, we treat that as a skip."""
    with mock.patch.object(gen_mod, "_llm_available", return_value=True):
        with mock.patch(
            "mediahub.media_ai.llm.generate_vision", return_value="ok.",
        ):
            out = vision_creative_direction(
                str(fake_photo), asset_id="a", brand_id="b",
            )
    assert out is None
