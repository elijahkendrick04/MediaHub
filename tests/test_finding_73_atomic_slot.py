"""Finding #73 — concurrent same-key MP4 renders must not race on the cache slot.

``_run_remotion`` pointed render.js's ``--output`` straight at the shared cache
slot. render.js writes its MP4 incrementally, so two concurrent same-key renders
— or a reader on the cache-hit path (``cached.exists() and size > 1024``) — could
observe a torn, half-written file. The fix renders into a unique per-process/
thread temp file and atomically ``os.replace``-es it into the slot, so the slot
only ever flips from absent to a complete MP4. It also teaches the #71 LRU prune
to skip those in-flight ``.tmp.mp4`` dotfiles.
"""

from __future__ import annotations

import os
import types

import pytest

from mediahub.visual import motion


class _FakeProc:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def _output_arg(cmd):
    return cmd[cmd.index("--output") + 1]


@pytest.fixture
def _remotion_stubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "node_available", lambda: True)
    # RENDER_SCRIPT just needs to exist.
    script = tmp_path / "render.js"
    script.write_text("// stub")
    monkeypatch.setattr(motion, "RENDER_SCRIPT", script)
    return tmp_path


def test_run_remotion_publishes_atomically(_remotion_stubbed, monkeypatch):
    out = _remotion_stubbed / "cache" / "abc123.mp4"

    captured = {}

    def fake_run_capture(cmd, cwd=None, timeout=None):
        target = _output_arg(cmd)
        captured["target"] = target
        # A real render writes the MP4 to --output; it must be the TEMP file,
        # never the final slot directly.
        assert os.path.basename(target).startswith(".") and target.endswith(".tmp.mp4")
        assert target != str(out)
        with open(target, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
        return _FakeProc(returncode=0)

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)

    result = motion._run_remotion(composition_id="Story", props={"a": 1}, out_path=out)

    assert result == out
    assert out.exists() and out.stat().st_size > 1024
    # The temp file was renamed away — no stray .tmp.mp4 remains.
    assert not list(out.parent.glob("*.tmp.mp4"))
    assert captured["target"] != str(out)


def test_failed_render_leaves_no_partial_slot(_remotion_stubbed, monkeypatch):
    out = _remotion_stubbed / "cache" / "def456.mp4"

    def fake_run_capture(cmd, cwd=None, timeout=None):
        # Render "starts" (writes a partial temp) then fails.
        with open(_output_arg(cmd), "wb") as fh:
            fh.write(b"partial")
        return _FakeProc(returncode=1, stderr="boom")

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)

    with pytest.raises(RuntimeError):
        motion._run_remotion(composition_id="Story", props={}, out_path=out)

    # The slot never received a torn file, and the temp was cleaned up.
    assert not out.exists()
    assert not list(out.parent.glob("*.tmp.mp4"))


def test_prune_skips_in_flight_temp_files(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "2")
    d = motion._cache_dir()
    # Two real entries (under the cap) + two in-flight temp dotfiles.
    for stem, mtime in (("aaa", 1000), ("bbb", 2000)):
        p = d / f"{stem}.mp4"
        p.write_bytes(b"\x00" * 2048)
        os.utime(p, (mtime, mtime))
    (d / ".aaa.111.222.tmp.mp4").write_bytes(b"\x00" * 2048)
    (d / ".ccc.333.444.tmp.mp4").write_bytes(b"\x00" * 2048)

    motion._prune_motion_cache()

    # Both real entries survive (temps were not counted toward the cap of 2)...
    assert {p.stem for p in d.glob("*.mp4") if not p.name.startswith(".")} == {"aaa", "bbb"}
    # ...and the temp files were never touched by the prune.
    assert (d / ".aaa.111.222.tmp.mp4").exists()
    assert (d / ".ccc.333.444.tmp.mp4").exists()
