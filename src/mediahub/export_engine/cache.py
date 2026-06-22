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
from pathlib import Path


def cache_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", ".")).resolve()
    d = data_dir / "export_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


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


__all__ = ["cache_dir", "content_key", "file_fingerprint", "cached_path"]
