"""R1.29 — progressive in-render poster capture (Remotion ``renderStill``)
replaces the post-hoc ffmpeg/ffprobe frame grab on the happy path.

Contract under test:

* ``remotion/render.js`` captures the poster *in-render* (a ``renderStill`` that
  honours the fonts ``delayRender`` hook) and writes the ``<hash>.poster.png``
  sidecar next to the MP4;
* ``visual/motion._finish_cached_video`` (via ``_ensure_poster_sidecar``) trusts
  that sidecar when it is present and non-empty and **skips the ffmpeg
  extraction** (the "skipping ffprobe extraction" win), reporting ``"in-render"``;
* it falls back to the ffmpeg frame grab only when the in-render poster is
  absent or empty — the free ffmpeg engine, a capture failure, or a video
  cached before R1.29 — reporting ``"ffmpeg"`` (or ``""`` if even that fails);
* ``render.js``'s ``posterTimeFor`` / ``posterPathFor`` stay in byte-parity with
  Python's ``audio_mux.poster_time_for`` / ``poster_path_for`` so there is a
  single poster-frame policy across both languages.

The unit + static layers are Node-free. The parity layer needs only ``node``;
the real-render layer needs Node **and** the Remotion install — gated exactly
like ``tests/test_motion.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import audio_mux, motion

_REMOTION_DIR = motion.REMOTION_DIR
_RENDER_JS = _REMOTION_DIR / "render.js"


# ---------------------------------------------------------------------------
# Unit: _ensure_poster_sidecar / _finish_cached_video poster policy (no Node)
# ---------------------------------------------------------------------------


def _seed_cached_mp4(cache_dir: Path, name: str = "deadbeefcafe.mp4") -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / name
    cached.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
    return cached


def test_in_render_poster_returns_in_render_and_skips_ffmpeg(tmp_path, monkeypatch):
    """When render.js already wrote a non-empty poster, _ensure_poster_sidecar
    keeps it, reports 'in-render', and never calls the ffmpeg write_poster —
    that skip is the whole point of R1.29."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cached = _seed_cached_mp4(tmp_path / "motion_cache")
    # Simulate render.js's in-render renderStill capture.
    audio_mux.poster_path_for(cached).write_bytes(b"\x89PNG\r\n\x1a\n in-render frame")

    calls: list = []
    monkeypatch.setattr(
        audio_mux, "write_poster", lambda *a, **k: calls.append((a, k)) or True
    )

    source = motion._ensure_poster_sidecar(cached, kind="story", duration_sec=6.0)

    assert source == "in-render"
    assert calls == [], "ffmpeg extraction must be skipped when the in-render poster exists"


def test_missing_in_render_poster_falls_back_to_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cached = _seed_cached_mp4(tmp_path / "motion_cache")

    at_secs: list = []

    def _spy(video, poster, *, at_sec):
        at_secs.append(at_sec)
        Path(poster).write_bytes(b"\x89PNG\r\n\x1a\n ffmpeg frame")
        return True

    monkeypatch.setattr(audio_mux, "write_poster", _spy)

    source = motion._ensure_poster_sidecar(cached, kind="reel", duration_sec=15.0)

    assert source == "ffmpeg"
    assert at_secs == [audio_mux.poster_time_for("reel", 15.0)], (
        "the fallback must extract at the deterministic poster timestamp"
    )
    assert audio_mux.poster_path_for(cached).exists()


def test_empty_in_render_poster_is_not_trusted(tmp_path, monkeypatch):
    """A 0-byte sidecar (a broken/partial in-render capture) must not be
    trusted — the finishing pass repairs it with the ffmpeg grab."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cached = _seed_cached_mp4(tmp_path / "motion_cache")
    audio_mux.poster_path_for(cached).write_bytes(b"")  # empty — a failed capture

    def _repair(video, poster, *, at_sec):
        Path(poster).write_bytes(b"\x89PNG\r\n\x1a\n repaired")
        return True

    monkeypatch.setattr(audio_mux, "write_poster", _repair)

    source = motion._ensure_poster_sidecar(cached, kind="story", duration_sec=6.0)

    assert source == "ffmpeg"
    assert audio_mux.poster_path_for(cached).stat().st_size > 0


def test_ffmpeg_fallback_failure_reports_no_poster(tmp_path, monkeypatch):
    """Honest reporting: when neither the in-render poster nor the ffmpeg grab
    produced a file, the provenance is the empty string (no poster)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cached = _seed_cached_mp4(tmp_path / "motion_cache")
    monkeypatch.setattr(audio_mux, "write_poster", lambda *a, **k: False)

    source = motion._ensure_poster_sidecar(cached, kind="story", duration_sec=6.0)

    assert source == ""
    assert not audio_mux.poster_path_for(cached).exists()


def test_finish_cached_video_skips_ffmpeg_when_in_render_poster_present(tmp_path, monkeypatch):
    """End-to-end through _finish_cached_video: an in-render poster means the
    ffmpeg write_poster is never called, and the audio record is unchanged."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cached = _seed_cached_mp4(tmp_path / "motion_cache")
    audio_mux.poster_path_for(cached).write_bytes(b"\x89PNG\r\n\x1a\n in-render frame")

    calls: list = []
    monkeypatch.setattr(audio_mux, "write_poster", lambda *a, **k: calls.append(1) or True)

    audio_rec = motion._finish_cached_video(
        cached, kind="story", plan=None, duration_sec=6.0
    )

    assert calls == [], "the in-render poster must skip the ffmpeg extraction"
    assert audio_rec == {"status": "off"}


def test_cold_render_skips_ffmpeg_when_render_js_wrote_poster(tmp_path, monkeypatch):
    """A cold render whose render.js wrote the in-render poster never touches
    ffmpeg, and the poster ships beside the published MP4."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)

    def _fake_run_with_in_render_poster(
        *, composition_id, props, out_path, duration_sec=None, size=None, timeout=600
    ):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        # render.js's renderStill writes the poster sidecar as a side effect.
        audio_mux.poster_path_for(out).write_bytes(b"\x89PNG\r\n\x1a\n in-render")
        return out

    ffmpeg_calls: list = []
    monkeypatch.setattr(
        audio_mux, "write_poster", lambda *a, **k: ffmpeg_calls.append(1) or True
    )

    brand = BrandKit(profile_id="x", display_name="Poster Club")
    card = {
        "id": "p1",
        "achievement": {
            "swimmer_name": "Post Er",
            "event_name": "50m Free",
            "result_time": "00:24.00",
        },
    }
    out = tmp_path / "out" / "s.mp4"
    with mock.patch.object(
        motion, "_run_remotion", side_effect=_fake_run_with_in_render_poster
    ):
        motion.render_story_card(card, brand, out)

    assert ffmpeg_calls == [], "the in-render poster must skip the ffmpeg extraction"
    assert audio_mux.poster_path_for(out).exists(), "the poster must ship beside the MP4"


def test_cold_render_without_in_render_poster_uses_ffmpeg(tmp_path, monkeypatch):
    """If render.js produced no poster (e.g. capture failed), the finishing
    pass falls back to the ffmpeg frame grab."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)

    def _fake_run_no_poster(
        *, composition_id, props, out_path, duration_sec=None, size=None, timeout=600
    ):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out  # no poster sidecar

    ffmpeg_calls: list = []

    def _ffmpeg_poster(video, poster, *, at_sec):
        ffmpeg_calls.append(at_sec)
        Path(poster).write_bytes(b"\x89PNG\r\n\x1a\n ffmpeg")
        return True

    monkeypatch.setattr(audio_mux, "write_poster", _ffmpeg_poster)

    brand = BrandKit(profile_id="x", display_name="Poster Club")
    card = {"id": "p2", "achievement": {"swimmer_name": "No Poster", "event_name": "50m"}}
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run_no_poster):
        motion.render_story_card(card, brand, tmp_path / "out" / "s.mp4")

    assert ffmpeg_calls, "without an in-render poster the ffmpeg fallback must run"


# ---------------------------------------------------------------------------
# Static: render.js wires the in-render capture and exports the helpers
# ---------------------------------------------------------------------------


def test_render_js_wires_in_render_poster_capture():
    src = _RENDER_JS.read_text(encoding="utf-8")
    assert "renderStill" in src, (
        "render.js must call renderStill for the in-render poster capture"
    )
    assert "delayRender" in src, (
        "render.js must document that the capture honours the fonts delayRender hook"
    )
    assert "posterTimeFor" in src and "posterPathFor" in src, (
        "render.js must own the poster-frame policy helpers"
    )
    assert "module.exports" in src, "the poster helpers must be exported for parity tests"
    assert "require.main === module" in src, (
        "main() must be guarded so require() can import the helpers without rendering"
    )


# ---------------------------------------------------------------------------
# Parity: render.js's helpers agree with Python (node only — no Remotion)
# ---------------------------------------------------------------------------


def _node() -> str | None:
    return shutil.which("node")


_SKIP_NODE = os.environ.get("MEDIAHUB_SKIP_MOTION_TESTS", "").lower() in ("1", "true", "yes")


@pytest.mark.skipif(_SKIP_NODE, reason="MEDIAHUB_SKIP_MOTION_TESTS set")
@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_poster_helpers_parity_with_python():
    """render.js's posterTimeFor / posterPathFor must match Python's
    audio_mux.poster_time_for / poster_path_for — one poster-frame policy."""
    render_js = json.dumps(str(_RENDER_JS))
    script = (
        "const m=require(" + render_js + ");"
        "const t=[['story',6.0],['story',1.0],['reel',15.0],['reel',1.0],"
        "['story',0.3],['reel',23.0]];"
        "const out={times:t.map(([k,d])=>m.posterTimeFor(k,d)),"
        "path:m.posterPathFor('/x/y/abc123.mp4')};"
        "console.log(JSON.stringify(out));"
    )
    res = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, f"node failed: {res.stderr}"
    got = json.loads(res.stdout.strip())

    expected_times = [
        audio_mux.poster_time_for("story", 6.0),
        audio_mux.poster_time_for("story", 1.0),
        audio_mux.poster_time_for("reel", 15.0),
        audio_mux.poster_time_for("reel", 1.0),
        audio_mux.poster_time_for("story", 0.3),
        audio_mux.poster_time_for("reel", 23.0),
    ]
    for js_val, py_val in zip(got["times"], expected_times):
        assert abs(js_val - py_val) < 1e-9, f"poster-time drift: js={js_val} py={py_val}"
    assert got["path"] == str(audio_mux.poster_path_for(Path("/x/y/abc123.mp4")))


# ---------------------------------------------------------------------------
# Integration: a real render emits a valid in-render PNG poster sidecar.
# Gated exactly like test_motion.py's render smoke test.
# ---------------------------------------------------------------------------


def _remotion_installed() -> bool:
    return (_REMOTION_DIR / "node_modules" / "remotion").exists()


@pytest.mark.skipif(_SKIP_NODE, reason="MEDIAHUB_SKIP_MOTION_TESTS set")
@pytest.mark.skipif(_node() is None, reason="node not installed")
@pytest.mark.skipif(not _remotion_installed(), reason="Remotion deps not installed")
def test_real_render_emits_in_render_poster(tmp_path, monkeypatch):
    """End-to-end: a real 1s render writes a valid PNG poster sidecar through the
    in-render renderStill path, and the finishing pass keeps it (no ffmpeg)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    card = {
        "id": "poster-smoke",
        "achievement": {
            "swimmer_name": "Poster Smoke",
            "event_name": "100m Free LC",
            "result_time": "00:54.32",
            "type": "NEW PB",
        },
    }
    brand = BrandKit(
        profile_id="t",
        display_name="Smoke Club",
        primary_colour="#0A2540",
        secondary_colour="#000000",
        accent_colour="#FFFFFF",
        short_name="SC",
    )
    out = tmp_path / "story.mp4"
    result = motion.render_story_card(card, brand, out, duration_sec=1.0, variation_seed=1)

    cached_poster = audio_mux.poster_path_for(Path(result))
    assert cached_poster.exists() and cached_poster.stat().st_size > 0, (
        "the in-render poster sidecar must exist next to the cached MP4"
    )
    assert cached_poster.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "poster must be a real PNG"
    # The poster also ships next to the published out-path MP4.
    assert audio_mux.poster_path_for(out).exists()
