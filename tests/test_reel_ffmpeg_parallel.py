"""Tests for the FFmpeg-engine concurrent beat renderer
(``mediahub.visual.reel_ffmpeg_parallel``).

Two layers, neither needing Chromium or an FFmpeg binary:

  - the helper itself (``Beat`` / ``render_beats``): output order follows beat
    order regardless of completion order, concurrency is bounded by the worker
    cap, the calling thread is used when a pool would not help, and the first
    beat error propagates unchanged;
  - the wiring: ``render_meet_reel_from_props`` always hands FFmpeg the stills
    in beat order (cover, card0, card1, …) whether beats render concurrently or
    serially — the still renderer, the FFmpeg arg builder and the runner are
    all stubbed so this proves the wiring everywhere the suite runs.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import reel_ffmpeg, reel_ffmpeg_parallel
from mediahub.visual.reel_ffmpeg_parallel import Beat, render_beats


def _beat(name: str, fn) -> Beat:
    return Beat(name, fn)


# ---------------------------------------------------------------------------
# Env-driven configuration
# ---------------------------------------------------------------------------


def test_parallel_enabled_defaults_on_and_only_zero_disables(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_PARALLEL", raising=False)
    assert reel_ffmpeg_parallel.parallel_enabled() is True
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "0")
    assert reel_ffmpeg_parallel.parallel_enabled() is False
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    assert reel_ffmpeg_parallel.parallel_enabled() is True
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "yes")
    assert reel_ffmpeg_parallel.parallel_enabled() is True  # any non-"0" enables


def test_max_workers_prefers_reel_specific_override(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_WORKERS", "2")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "5")
    assert reel_ffmpeg_parallel.max_workers() == 5


def test_max_workers_falls_back_to_shared_then_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_RENDER_WORKERS", raising=False)
    monkeypatch.setenv("MEDIAHUB_RENDER_WORKERS", "7")
    assert reel_ffmpeg_parallel.max_workers() == 7
    monkeypatch.delenv("MEDIAHUB_RENDER_WORKERS", raising=False)
    assert reel_ffmpeg_parallel.max_workers() == reel_ffmpeg_parallel.DEFAULT_MAX_WORKERS


def test_max_workers_rejects_bad_values(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_RENDER_WORKERS", raising=False)
    for bad in ("0", "-3", "abc", "  "):
        monkeypatch.setenv("MEDIAHUB_RENDER_WORKERS", bad)
        assert reel_ffmpeg_parallel.max_workers() == reel_ffmpeg_parallel.DEFAULT_MAX_WORKERS


# ---------------------------------------------------------------------------
# Output ordering
# ---------------------------------------------------------------------------


def test_empty_beats_returns_empty_list():
    assert render_beats([]) == []


def test_order_preserved_when_later_beats_finish_first(monkeypatch):
    """beat0 sleeps longest and beat3 returns first, yet the result list is in
    beat order — completion order must never leak into the output."""
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "4")

    def make(i: int, delay: float) -> Beat:
        return _beat(f"b{i}", lambda d=delay, n=i: (time.sleep(d), Path(f"/tmp/beat{n}.png"))[1])

    beats = [make(0, 0.15), make(1, 0.10), make(2, 0.05), make(3, 0.0)]
    out = render_beats(beats)
    assert [p.name for p in out] == ["beat0.png", "beat1.png", "beat2.png", "beat3.png"]


# ---------------------------------------------------------------------------
# Concurrency is real, and bounded by the worker cap
# ---------------------------------------------------------------------------


def test_runs_up_to_the_worker_cap_concurrently(monkeypatch):
    """With a cap of 3 and 6 beats, a barrier lets us prove exactly three beats
    run at once (concurrency happened) and never more (the cap held)."""
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "3")

    barrier = threading.Barrier(3, timeout=10)
    lock = threading.Lock()
    live = {"now": 0, "peak": 0}

    def make(i: int) -> Beat:
        def _render(n=i):
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            try:
                barrier.wait()
            except threading.BrokenBarrierError:  # pragma: no cover - cap regressed
                pass
            with lock:
                live["now"] -= 1
            return Path(f"/tmp/beat{n}.png")

        return _beat(f"b{i}", _render)

    out = render_beats([make(i) for i in range(6)])
    assert [p.name for p in out] == [f"beat{i}.png" for i in range(6)]
    assert live["peak"] == 3  # exactly the cap — concurrent, and bounded


def test_worker_cap_never_exceeds_beat_count(monkeypatch):
    """Two beats with a generous cap still only ever run two at once (the pool
    is sized to min(cap, n))."""
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "8")

    barrier = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    live = {"now": 0, "peak": 0}

    def make(i: int) -> Beat:
        def _render(n=i):
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            try:
                barrier.wait()
            except threading.BrokenBarrierError:  # pragma: no cover
                pass
            with lock:
                live["now"] -= 1
            return Path(f"/tmp/beat{n}.png")

        return _beat(f"b{i}", _render)

    out = render_beats([make(0), make(1)])
    assert [p.name for p in out] == ["beat0.png", "beat1.png"]
    assert live["peak"] == 2


# ---------------------------------------------------------------------------
# Inline (no-pool) paths are byte-identical to the old sequential loop
# ---------------------------------------------------------------------------


def test_disabled_runs_on_the_calling_thread(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "0")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "4")
    main = threading.current_thread()
    seen: list[threading.Thread] = []

    def make(i: int) -> Beat:
        def _render(n=i):
            seen.append(threading.current_thread())
            return Path(f"/tmp/b{n}.png")

        return _beat(f"b{i}", _render)

    out = render_beats([make(i) for i in range(4)])
    assert [p.name for p in out] == [f"b{i}.png" for i in range(4)]
    assert all(t is main for t in seen)  # never left the calling thread


def test_single_beat_runs_inline_without_a_pool(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "4")
    main = threading.current_thread()
    seen: list[threading.Thread] = []

    def _render():
        seen.append(threading.current_thread())
        return Path("/tmp/only.png")

    out = render_beats([_beat("only", _render)])
    assert [p.name for p in out] == ["only.png"]
    assert seen == [main]


def test_worker_cap_of_one_runs_inline(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "1")
    main = threading.current_thread()
    seen: list[threading.Thread] = []

    def make(i: int) -> Beat:
        def _render(n=i):
            seen.append(threading.current_thread())
            return Path(f"/tmp/b{n}.png")

        return _beat(f"b{i}", _render)

    out = render_beats([make(i) for i in range(3)])
    assert [p.name for p in out] == ["b0.png", "b1.png", "b2.png"]
    assert all(t is main for t in seen)


# ---------------------------------------------------------------------------
# Honest errors — never a partial reel / placeholder frame
# ---------------------------------------------------------------------------


class _BeatBoom(RuntimeError):
    pass


def test_first_beat_error_propagates_unchanged(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "1")
    monkeypatch.setenv("MEDIAHUB_REEL_RENDER_WORKERS", "4")

    def boom():
        raise _BeatBoom("still render failed")

    beats = [
        _beat("b0", lambda: Path("/tmp/b0.png")),
        _beat("bad", boom),
        _beat("b2", lambda: Path("/tmp/b2.png")),
    ]
    with pytest.raises(_BeatBoom, match="still render failed"):
        render_beats(beats)


def test_error_propagates_in_the_sequential_path_too(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", "0")

    def boom():
        raise _BeatBoom("nope")

    with pytest.raises(_BeatBoom, match="nope"):
        render_beats([_beat("b0", lambda: Path("/tmp/b0.png")), _beat("bad", boom)])


# ---------------------------------------------------------------------------
# Wiring — render_meet_reel_from_props composites beats in order (no FFmpeg
# binary, no Chromium: still render + arg builder + runner are all stubbed)
# ---------------------------------------------------------------------------


def _props(name="Ada Lovelace", event="100m Freestyle LC", result="00:58.31") -> dict:
    first, surname = name.split()[0], name.split()[-1]
    return {
        "athleteFullName": name,
        "athleteFirstName": first,
        "athleteSurname": surname,
        "eventName": event,
        "resultValue": result,
        "achievementLabel": "NEW PB",
        "meetName": "Welsh Winter Nationals 2026",
        "place": "1",
        "variationSeed": 3,
    }


def _brand_dict() -> dict:
    return {
        "primary": "#0A2540",
        "secondary": "#101418",
        "accent": "#D4FF3A",
        "displayName": "City of Swansea Aquatics",
        "shortName": "COSA",
        "logoDataUri": "",
        "themeSource": "brand-kit",
    }


def _brand_kit() -> BrandKit:
    return BrandKit(
        profile_id="ffmpeg-parallel-test",
        display_name="City of Swansea Aquatics",
        short_name="COSA",
        primary_colour="#0A2540",
        secondary_colour="#101418",
        accent_colour="#D4FF3A",
    )


@pytest.mark.parametrize("parallel", ["1", "0"])
def test_reel_beats_composite_in_order(tmp_path, monkeypatch, parallel):
    """The stills handed to FFmpeg are always cover, card0, card1, … in beat
    order — whether beats render concurrently (default) or serially
    (MEDIAHUB_RENDER_PARALLEL=0). render_beats preserves order regardless of
    which beat finishes first, so the transition chain is never reordered."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_RENDER_PARALLEL", parallel)

    def _fake_still(brief, brand_kit, out_dir, *, name, **kw):
        frame_dir = out_dir / name
        frame_dir.mkdir(parents=True, exist_ok=True)
        png = frame_dir / "story.png"
        png.write_bytes(b"\x89PNG\r\n")
        return png

    captured: dict = {}

    def _fake_args(stills, out_path, segment_durations, **kw):
        # The beat each still belongs to is its parent directory's name.
        captured["beats"] = [Path(s).parent.name for s in stills]
        return [str(out_path)]

    def _fake_run(args, **kw):
        Path(args[-1]).write_bytes(b"\x00" * 4096)

    monkeypatch.setattr(reel_ffmpeg, "_render_still", _fake_still)
    monkeypatch.setattr(reel_ffmpeg, "reel_ffmpeg_args", _fake_args)
    monkeypatch.setattr(reel_ffmpeg, "_run_ffmpeg", _fake_run)
    monkeypatch.setattr(reel_ffmpeg, "ffmpeg_exe", lambda: "/bin/true")

    cards = [
        _props(name="Ada Lovelace"),
        _props(name="Grace Hopper", event="200m Butterfly LC"),
        _props(name="Katherine Johnson", event="400m IM LC"),
    ]
    out = tmp_path / "reel.mp4"
    result = reel_ffmpeg.render_meet_reel_from_props(
        cards, _brand_dict(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert Path(result).exists()
    assert captured["beats"] == ["cover", "card0", "card1", "card2"]
