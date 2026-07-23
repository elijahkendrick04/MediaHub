"""motion-supersample — optional supersampled motion render.

Motion renders at 1x by default; MEDIAHUB_MOTION_SUPERSAMPLE renders at scale×
and Lanczos-downscales back to the target for crisper text/vector/gradient
edges. Off by default and folded into the cache key only when active, so the
default render stays byte-identical.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mediahub.visual import motion
from mediahub.visual import reel_ffmpeg


def test_motion_supersample_env_clamps(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MOTION_SUPERSAMPLE", raising=False)
    assert motion._motion_supersample() == 1.0  # unset → 1x
    for raw, expected in [("", 1.0), ("0", 1.0), ("x", 1.0), ("1.5", 1.5), ("9", 2.0), ("2", 2.0)]:
        monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", raw)
        assert motion._motion_supersample() == expected, raw


def test_supersample_folds_into_cache_key_only_when_active():
    base = {"card": {"a": 1}, "size": [1080, 1920]}
    ss = {**base, "supersample": 2.0}
    h_plain = motion._content_hash(base, kind="story")
    h_ss = motion._content_hash(ss, kind="story")
    assert h_plain == motion._content_hash(base, kind="story")
    assert h_plain != h_ss


def test_run_remotion_passes_scale_and_downscales(tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "node_available", lambda: True)

    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run_capture(cmd, *, cwd=None, timeout=None):
        captured["cmd"] = list(cmd)
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"x" * 4096)  # the n× render
        return _Proc()

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)
    monkeypatch.setattr("mediahub.visual.reel_ffmpeg.ffmpeg_exe", lambda: "/usr/bin/ffmpeg")

    ff: dict = {}

    def fake_sub_run(args, **kw):
        ff["args"] = list(args)
        Path(args[-1]).write_bytes(b"y" * 4096)  # the downscaled output

        class _R:
            returncode = 0
            stderr = ""

        return _R()

    monkeypatch.setattr(subprocess, "run", fake_sub_run)

    # ss > 1: --scale is passed and a Lanczos downscale to the exact target runs.
    out = tmp_path / "card.mp4"
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=out,
        duration_sec=6.0,
        size=(1080, 1920),
        supersample=2.0,
    )
    assert "--scale" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--scale") + 1] == "2"
    assert "scale=1080:1920:flags=lanczos" in " ".join(ff["args"])
    assert out.exists()

    # ss == 1 (default): no --scale, no extra ffmpeg downscale pass.
    captured.clear()
    ff.clear()
    out2 = tmp_path / "card2.mp4"
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=out2,
        duration_sec=6.0,
        size=(1080, 1920),
        supersample=1.0,
    )
    assert "--scale" not in captured["cmd"]
    assert not ff, "no downscale ffmpeg pass on the default 1x path"


def test_ffmpeg_engine_reports_supersample_unsupported(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MOTION_SUPERSAMPLE", raising=False)
    assert reel_ffmpeg._supersample_requested() is False
    monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", "2")
    assert reel_ffmpeg._supersample_requested() is True
    monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", "1")  # not > 1
    assert reel_ffmpeg._supersample_requested() is False
