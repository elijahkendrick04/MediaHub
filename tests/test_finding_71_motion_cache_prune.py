"""Finding #71 — the motion cache is bounded (LRU prune), not unbounded.

Before the fix, ``DATA_DIR/motion_cache`` had no eviction (unlike the still-PNG
cache, capped at 512). On a bounded Render disk it trended to exhaustion, after
which every render write failed. ``_prune_motion_cache`` now bounds the number
of cached MP4s, evicting the oldest by mtime and sweeping each evicted key's
sidecars; cache hits touch the MP4 mtime so hot entries survive.
"""

from __future__ import annotations

import os

from mediahub.visual import motion


def _seed(cache_dir, stem, *, mtime):
    """Write a fake <stem>.mp4 plus its sidecars, all stamped to ``mtime``."""
    mp4 = cache_dir / f"{stem}.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
    manifest = cache_dir / f"{stem}.json"
    manifest.write_text("{}")
    poster = cache_dir / f"{stem}.poster.png"
    poster.write_bytes(b"\x89PNG")
    audio = cache_dir / f"{stem}.audio.json"
    audio.write_text("{}")
    for p in (mp4, manifest, poster, audio):
        os.utime(p, (mtime, mtime))
    return mp4


def test_default_cap_is_positive_and_env_overridable(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MOTION_CACHE_MAX", raising=False)
    assert motion._motion_cache_max() == motion._DEFAULT_MOTION_CACHE_MAX
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "3")
    assert motion._motion_cache_max() == 3
    # Garbage / non-positive values fall back to a safe bound.
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "not-a-number")
    assert motion._motion_cache_max() == motion._DEFAULT_MOTION_CACHE_MAX
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "0")
    assert motion._motion_cache_max() == 1


def test_prune_evicts_oldest_and_sweeps_sidecars(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "2")
    d = motion._cache_dir()
    # Three entries, oldest -> newest.
    _seed(d, "aaa", mtime=1000)
    _seed(d, "bbb", mtime=2000)
    _seed(d, "ccc", mtime=3000)

    motion._prune_motion_cache()

    remaining = {p.stem for p in d.glob("*.mp4")}
    assert remaining == {"bbb", "ccc"}, "oldest MP4 should be evicted down to the cap"
    # The evicted key took ALL its sidecars with it.
    assert not (d / "aaa.json").exists()
    assert not (d / "aaa.poster.png").exists()
    assert not (d / "aaa.audio.json").exists()
    # Survivors keep their sidecars.
    assert (d / "bbb.poster.png").exists()
    assert (d / "ccc.audio.json").exists()


def test_prune_is_noop_under_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "5")
    d = motion._cache_dir()
    _seed(d, "aaa", mtime=1000)
    _seed(d, "bbb", mtime=2000)
    motion._prune_motion_cache()
    assert {p.stem for p in d.glob("*.mp4")} == {"aaa", "bbb"}


def test_touch_hit_saves_hot_entry_from_eviction(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "2")
    d = motion._cache_dir()
    old_hot = _seed(d, "hot", mtime=1000)  # oldest by mtime...
    _seed(d, "mid", mtime=2000)
    _seed(d, "new", mtime=3000)

    # A cache hit on the oldest entry refreshes its recency to newest.
    motion._touch_cache_hit(old_hot)
    motion._prune_motion_cache()

    remaining = {p.stem for p in d.glob("*.mp4")}
    # "hot" survives (just touched); "mid" is now the oldest and is evicted.
    assert "hot" in remaining
    assert "mid" not in remaining
    assert "new" in remaining


def test_prune_leaves_props_subdir_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "1")
    d = motion._cache_dir()
    props = d / "props"
    props.mkdir(parents=True, exist_ok=True)
    (props / "some-output.json").write_text("{}")
    _seed(d, "aaa", mtime=1000)
    _seed(d, "bbb", mtime=2000)

    motion._prune_motion_cache()

    assert (props / "some-output.json").exists(), "props/ is output-keyed, not swept"
    assert {p.stem for p in d.glob("*.mp4")} == {"bbb"}
