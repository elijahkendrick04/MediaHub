"""documents.cache — content-addressed output cache for rendered documents.

Same idea as ``charts.export`` / ``graphic_renderer.render_cache``: a render is
keyed by its full HTML (which already folds in the spec + brand role vars +
geometry) plus the output kind/size, so an identical document re-renders as a
cache hit and the bytes are stable for a given Chromium. Files land under
``DATA_DIR/document_cache`` so storage follows the ``DATA_DIR`` rule.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def cache_dir() -> Path:
    data_dir = Path(os.environ.get("DATA_DIR", ".")).resolve()
    d = data_dir / "document_cache"
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


def cached_path(suffix: str, *key_parts: object) -> Path:
    """Resolve the cache path for an output of ``suffix`` keyed by ``key_parts``."""
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return cache_dir() / f"{content_key(*key_parts)}{suffix}"


__all__ = ["cache_dir", "content_key", "cached_path"]
