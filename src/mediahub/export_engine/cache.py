"""export_engine/cache.py — content-addressed output cache for exports (1.19).

Same idea as ``documents.cache`` / ``charts.export``: an export is keyed by
everything that determines its bytes (source fingerprint + target format +
clamped options), so an identical request is a cache hit and re-running the
engine never re-encodes the same file twice. Files land under
``DATA_DIR/export_cache`` so storage follows the ``DATA_DIR`` rule.

Source files are folded in by a cheap fingerprint (size + mtime + name) rather
than a full content hash — the same convention the video render cache uses —
so keying a 200 MB clip costs a ``stat`` call, not a re-read.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


def cache_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", ".")).resolve()
    d = data_dir / "export_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- garbage collection -----------------------------------------------------
# Export artifacts otherwise grow without bound on the hosted disk: every bulk
# POST writes RUNS_DIR/<run>/exports/bulk_<uuid>.zip and every quick action
# writes export_cache/quick/<...>-<uuid8>.<ext>. ``maybe_gc`` is a throttled,
# best-effort sweep any export call site can invoke cheaply (one stat when
# throttled). Thresholds sit far above the 15-minute variant-job TTL and any
# plausible download window, so nothing mid-serve is ever unlinked.

_GC_THROTTLE_S = 15 * 60.0  # at most one sweep per interval per process pool
_CACHE_MAX_AGE_S = 7 * 24 * 3600.0  # export_cache entries (incl. quick/)
_CACHE_MAX_BYTES = 2 * 1024**3  # total export_cache size cap
_BULK_ZIP_MAX_AGE_S = 24 * 3600.0  # runs/*/exports/bulk_*.zip


def _runs_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", ".")).resolve()
    return Path(os.environ.get("RUNS_DIR", str(data_dir / "runs_v4")))


def maybe_gc(*, force: bool = False) -> None:
    """Throttled, best-effort sweep of stale export artifacts.

    Removes export_cache entries (including ``quick/``) past the age cap,
    evicts oldest-first when the cache exceeds the total-size cap, and unlinks
    ``runs/*/exports/bulk_*.zip`` past the bulk TTL. Never raises.
    """
    try:
        d = cache_dir()
        stamp = d / ".gc_stamp"
        now = time.time()
        if not force:
            try:
                if now - stamp.stat().st_mtime < _GC_THROTTLE_S:
                    return
            except OSError:
                pass
        stamp.touch()

        # 1) Age sweep + size-cap eviction for export_cache (incl. quick/).
        entries: list[tuple[float, int, Path]] = []
        for f in d.rglob("*"):
            if not f.is_file() or f.name == ".gc_stamp":
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if now - st.st_mtime > _CACHE_MAX_AGE_S:
                _unlink_quiet(f)
            else:
                entries.append((st.st_mtime, st.st_size, f))
        total = sum(size for _, size, _ in entries)
        if total > _CACHE_MAX_BYTES:
            for _, size, f in sorted(entries):  # oldest mtime first
                _unlink_quiet(f)
                total -= size
                if total <= _CACHE_MAX_BYTES:
                    break

        # 2) Stale per-job bulk ZIPs under the runs tree.
        runs = _runs_dir()
        if runs.is_dir():
            for z in runs.glob("*/exports/bulk_*.zip"):
                try:
                    if now - z.stat().st_mtime > _BULK_ZIP_MAX_AGE_S:
                        _unlink_quiet(z)
                except OSError:
                    continue
    except Exception:
        pass  # GC is best-effort; an export must never fail because of it


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def content_key(*parts: object) -> str:
    """A stable blake2b hex key over the given parts."""
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(b"\x1f")
        if isinstance(p, bytes):
            h.update(p)
        else:
            h.update(str(p).encode("utf-8"))
    return h.hexdigest()


def file_fingerprint(path: str | Path) -> str:
    """A cheap fingerprint for a source file: ``name:size:mtime_ns``.

    Returns ``"missing:<name>"`` when the file is absent so a key still forms
    (the engine will then honest-error at encode time rather than here).
    """
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return f"missing:{p.name}"
    return f"{p.name}:{st.st_size}:{st.st_mtime_ns}"


def cached_path(suffix: str, *key_parts: object) -> Path:
    """Resolve the cache path for an output of ``suffix`` keyed by ``key_parts``."""
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return cache_dir() / f"{content_key(*key_parts)}{suffix}"


__all__ = ["cache_dir", "content_key", "file_fingerprint", "cached_path", "maybe_gc"]
