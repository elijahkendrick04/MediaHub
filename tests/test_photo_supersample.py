"""transform-sampling — opt-in per-photo resample-quality hint.

The Remotion engine's transform-scaled athlete photos get an honest, framing-
neutral resample hint (``imageRendering:'auto'``) when the operator opts in via
``MEDIAHUB_PHOTO_SUPERSAMPLE``. It is folded into the card props ONLY when active,
so every default render stays byte-identical. It is deliberately NOT a geometry
prescale: under renderMedia's default ``scale:1`` a "render at 100·ss %% then
scale(1/ss)" trick does not create a real supersampled backing store (Chromium
rasters the shrunk layer at display resolution) and would mis-frame the photo, so
the guaranteed dense-buffer path stays the whole-composition motion supersample.
The manifest records the hint honestly; the free FFmpeg engine reports its native
2x Lanczos prescale as satisfying it.
"""

from __future__ import annotations

import re
from pathlib import Path

from mediahub.visual import motion, reel_ffmpeg

_REPO = Path(__file__).resolve().parents[1]
_STORYCARD = _REPO / "src/mediahub/remotion/src/compositions/StoryCard.tsx"
_ROOT = _REPO / "src/mediahub/remotion/src/Root.tsx"


def test_photo_supersample_env_clamps(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_PHOTO_SUPERSAMPLE", raising=False)
    assert motion._photo_supersample() == 0  # unset → off
    for raw, expected in [
        ("", 0),
        ("0", 0),
        ("1", 0),  # 1x is not a supersample → off
        ("x", 0),  # malformed → off
        ("2", 2),
        ("2.0", 2),
        ("3", 2),  # capped at 2 for cross-engine (FFmpeg fixed 2x) parity
        ("9", 2),
    ]:
        monkeypatch.setenv("MEDIAHUB_PHOTO_SUPERSAMPLE", raw)
        assert motion._photo_supersample() == expected, raw


def test_folds_into_cache_key_only_when_active():
    base_card = {"result": "1:02.34", "athleteFullName": "A. B."}
    payload_off = {"card": base_card, "size": [1080, 1920]}
    card_on = {**base_card, "photoSupersample": 2}
    payload_on = {"card": card_on, "size": [1080, 1920]}

    h_off = motion._content_hash(payload_off, kind="story")
    h_on = motion._content_hash(payload_on, kind="story")

    # Off path is stable and byte-identical to itself; the opted-in fold keys
    # independently so only the opted-in videos re-render.
    assert h_off == motion._content_hash(payload_off, kind="story")
    assert h_off != h_on
    # The fold never mutates the caller's card dict in place.
    assert "photoSupersample" not in base_card


def test_ffmpeg_engine_reports_photo_supersample_native(monkeypatch):
    # The free engine already resamples from a genuine 2x Lanczos prescale, so it
    # reports the knob as natively satisfied rather than faking a caller factor.
    monkeypatch.delenv("MEDIAHUB_PHOTO_SUPERSAMPLE", raising=False)
    assert reel_ffmpeg._photo_supersample_requested() is False
    monkeypatch.setenv("MEDIAHUB_PHOTO_SUPERSAMPLE", "2")
    assert reel_ffmpeg._photo_supersample_requested() is True
    monkeypatch.setenv("MEDIAHUB_PHOTO_SUPERSAMPLE", "1")  # 1x is off
    assert reel_ffmpeg._photo_supersample_requested() is False
    monkeypatch.setenv("MEDIAHUB_PHOTO_SUPERSAMPLE", "x")  # malformed
    assert reel_ffmpeg._photo_supersample_requested() is False


def test_storycard_schema_field_and_root_default():
    src = _STORYCARD.read_text()
    assert "photoSupersample: z.number().default(0)" in src
    # Preview default matches the byte-identical (ss=0) render.
    assert "photoSupersample: 0" in _ROOT.read_text()


def test_supersampled_helper_returns_base_unchanged_when_off():
    """The byte-identical-default guarantee lives entirely in the helper: at
    ss<=0 it returns the SAME style object it was handed (reference-identical, so
    React serialises it string-for-string as today). Guard the source shape since
    the repo has no JS test runner."""
    src = _STORYCARD.read_text()
    assert "export function supersampledImgStyle(" in src
    m = re.search(
        r"export function supersampledImgStyle\([^)]*\):[^{]*\{(.*?)\n\}",
        src,
        re.S,
    )
    assert m, "supersampledImgStyle body not found"
    body = m.group(1)
    # Off branch returns the base object verbatim — no reordered / added keys.
    assert "if (!ss || ss <= 0) {" in body
    assert "return base;" in body
    # On branch is a framing-neutral hint only (no geometry rewrite).
    assert 'imageRendering: "auto"' in body
    assert "%" not in body, "helper must not rewrite geometry (no 100·ss %% trick)"


def test_helper_applied_at_scaled_photo_sites():
    src = _STORYCARD.read_text()
    # Helper definition + the three transform-scaled athlete-photo <img> sites,
    # each threaded from the card prop.
    assert src.count("supersampledImgStyle(") >= 4
    assert src.count("card.photoSupersample,") >= 3
