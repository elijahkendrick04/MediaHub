"""Incremental render-stage cache for the still-graphic renderer (roadmap G1.24).

The graphic renderer assembles a result card from several *deterministic* stages
and then screenshots it with headless Chromium. Two of those stages are pure
functions of their inputs and expensive enough to be worth memoising, so a
re-render of an unchanged card skips the work it already did:

* **asset-URI stage** — turning an on-disk image (athlete cutout, venue photo,
  background photo, club / sponsor logo) into a base64 ``data:`` URI. Keyed on
  the file's resolved path + mtime + size, so an unchanged file is read and
  encoded once per process. Held in memory (the encoded blobs are large and
  process-local; nothing is duplicated to disk).

* **HTML→PNG stage** — the headless-Chromium screenshot, by far the most
  expensive step (a fresh browser launch, layout, font settle and screenshot
  each call). Keyed on a SHA-256 of the fully-assembled HTML + canvas size +
  device-scale factor, so an identical card never re-launches Chromium. Stored
  on disk under ``DATA_DIR/render_cache`` so the win survives across requests
  and worker processes.

Why this is safe (and not an engine change)
------------------------------------------
Both stages are *pure*: identical inputs always produced an identical output, so
handing back a previously-computed artifact is byte-for-byte what a fresh render
would have made. The cache never changes a render's *content* — it only elides
repeat *work*. The card maths (autofit, colour roles, layout) is untouched; this
sits beside the deterministic engine, not inside it.

Operational notes
-----------------
* Disable entirely with ``MEDIAHUB_RENDER_CACHE=0`` (also accepts ``false`` /
  ``off`` / ``no``) — e.g. to benchmark a cold render or rule the cache out
  while debugging.
* The on-disk PNG cache is bounded to ``MEDIAHUB_RENDER_CACHE_MAX`` entries
  (default 512); the oldest are pruned on write. The whole ``render_cache``
  directory is disposable and safe to delete at any time.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_MAX_ENTRIES = 512
# In-memory asset-URI entries. Each base64 blob can be multiple MB, so this is
# deliberately small — a content pack only juggles a handful of distinct assets
# (athlete, logo, venue, sponsor, background) at once.
_ASSET_MEM_MAX = 64

_FALSEY = {"0", "false", "off", "no"}


def cache_enabled() -> bool:
    """True unless explicitly disabled via ``MEDIAHUB_RENDER_CACHE``."""
    return os.environ.get("MEDIAHUB_RENDER_CACHE", "1").strip().lower() not in _FALSEY


def _data_dir() -> Path:
    """Resolve ``DATA_DIR`` at call time so tests can monkeypatch it."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    # …/src/mediahub/graphic_renderer/render_cache.py → …/src/mediahub
    return Path(__file__).resolve().parents[1]


def png_cache_dir() -> Path:
    """The on-disk PNG cache directory (created on demand)."""
    d = _data_dir() / "render_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _max_entries() -> int:
    try:
        n = int(os.environ.get("MEDIAHUB_RENDER_CACHE_MAX", str(_DEFAULT_MAX_ENTRIES)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ENTRIES
    return max(1, n)


# ---------------------------------------------------------------------------
# Observability — small hit/miss counters so callers and tests can see the
# cache working without reaching into the filesystem.
# ---------------------------------------------------------------------------


class _Stats:
    __slots__ = ("asset_hits", "asset_misses", "png_hits", "png_misses")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.asset_hits = 0
        self.asset_misses = 0
        self.png_hits = 0
        self.png_misses = 0

    def as_dict(self) -> dict:
        return {
            "asset_hits": self.asset_hits,
            "asset_misses": self.asset_misses,
            "png_hits": self.png_hits,
            "png_misses": self.png_misses,
        }


_stats = _Stats()
_stats_lock = threading.Lock()


def stats() -> dict:
    """Snapshot of cache hit/miss counters for this process."""
    with _stats_lock:
        return _stats.as_dict()


def reset_stats() -> None:
    """Zero the hit/miss counters (test/ops convenience)."""
    with _stats_lock:
        _stats.reset()


# ---------------------------------------------------------------------------
# Asset-URI stage — in-memory memoisation of base64 data: URIs.
# ---------------------------------------------------------------------------

_asset_lock = threading.Lock()
_asset_cache: "OrderedDict[tuple, str]" = OrderedDict()


def _asset_key(path: Path) -> Optional[tuple]:
    """Identity key for an on-disk asset: (resolved path, mtime_ns, size)."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def asset_data_uri(path: str | Path, loader: Callable[[Path], str]) -> str:
    """Return ``loader(path)`` for an on-disk asset, memoised on path+mtime+size.

    ``loader`` does the actual read + base64 encode; the cache only elides repeat
    work for an unchanged file and returns byte-identical text. Falls straight
    through to ``loader`` when the cache is disabled or the file can't be
    ``stat``-ed — so any genuine read error still surfaces exactly as it would
    have without the cache.
    """
    p = Path(path)
    if not cache_enabled():
        return loader(p)
    key = _asset_key(p)
    if key is None:
        # Unstattable: let the loader run so its real error (if any) propagates.
        return loader(p)

    with _asset_lock:
        hit = _asset_cache.get(key)
        if hit is not None:
            _asset_cache.move_to_end(key)
            with _stats_lock:
                _stats.asset_hits += 1
            return hit

    # Encode outside the lock (it can be slow for large photos). Under
    # contention two threads may encode the same file once each; both produce
    # identical text, so the duplicate is harmless.
    value = loader(p)
    with _asset_lock:
        _asset_cache[key] = value
        _asset_cache.move_to_end(key)
        while len(_asset_cache) > _ASSET_MEM_MAX:
            _asset_cache.popitem(last=False)
    with _stats_lock:
        _stats.asset_misses += 1
    return value


# ---------------------------------------------------------------------------
# HTML→PNG stage — on-disk, content-addressed PNG cache.
# ---------------------------------------------------------------------------


def png_cache_key(html: str, width: int, height: int, dpr: int) -> str:
    """Stable SHA-256 hex key for a finished card render.

    The screenshot is a pure function of (final HTML, canvas size, device-scale
    factor) — the card HTML is fully self-contained (data: URIs + file:// fonts,
    no network at screenshot time) — so these three fully determine the output
    bytes.
    """
    h = hashlib.sha256()
    h.update(html.encode("utf-8"))
    # Domain-separate the dimensions so they can't collide with HTML bytes.
    h.update(f"|{int(width)}x{int(height)}@{int(dpr)}".encode("ascii"))
    return h.hexdigest()


def _png_path(key: str) -> Path:
    return png_cache_dir() / f"{key}.png"


def get_cached_png(key: str) -> Optional[bytes]:
    """Return cached PNG bytes for ``key``, or ``None`` on a miss / disabled cache."""
    if not cache_enabled():
        return None
    p = _png_path(key)
    try:
        data = p.read_bytes()
    except OSError:
        with _stats_lock:
            _stats.png_misses += 1
        return None
    # Touch for LRU recency so the prune keeps hot entries.
    try:
        os.utime(p, None)
    except OSError:
        pass
    with _stats_lock:
        _stats.png_hits += 1
    return data


def store_png(key: str, png_bytes: bytes) -> None:
    """Persist ``png_bytes`` under ``key`` (atomic write), then prune to bound."""
    if not cache_enabled():
        return
    d = png_cache_dir()
    final = d / f"{key}.png"
    tmp = d / f".{key}.{os.getpid()}.tmp"
    try:
        tmp.write_bytes(png_bytes)
        os.replace(tmp, final)  # atomic — readers never see a torn file
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return
    _prune(d)


def _prune(d: Path) -> None:
    """Bound the on-disk cache to ``_max_entries()``, dropping the oldest first."""
    cap = _max_entries()
    try:
        entries = list(d.glob("*.png"))
    except OSError:
        return
    if len(entries) <= cap:
        return
    try:
        entries.sort(key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for p in entries[: len(entries) - cap]:
        try:
            p.unlink()
        except OSError:
            pass


def clear() -> None:
    """Drop every in-memory and on-disk cache entry (test / ops convenience)."""
    with _asset_lock:
        _asset_cache.clear()
    d = _data_dir() / "render_cache"
    if d.exists():
        for p in d.glob("*.png"):
            try:
                p.unlink()
            except OSError:
                pass
    reset_stats()


__all__ = [
    "cache_enabled",
    "png_cache_dir",
    "asset_data_uri",
    "png_cache_key",
    "get_cached_png",
    "store_png",
    "stats",
    "reset_stats",
    "clear",
]
