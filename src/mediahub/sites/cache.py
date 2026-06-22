"""sites.cache — content-addressed output cache for rendered microsite assets.

Same idea as :mod:`documents.cache`: an output (a QR PNG/PDF, a page-snapshot PNG)
is keyed by its full inputs, so an identical asset re-renders as a cache hit with
stable bytes. Files land under ``DATA_DIR/site_cache`` so storage follows the
``DATA_DIR`` rule.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def cache_dir() -> Path:
    d = Path(os.environ.get("DATA_DIR", ".")).resolve() / "site_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def content_key(*parts: object) -> str:
    """A stable blake2b hex key over the given parts."""
    h = hashlib.blake2b(digest_size=16)
    for p in parts:
        h.update(b"\x1f")
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
    return h.hexdigest()


def cached_path(suffix: str, *key_parts: object) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return cache_dir() / f"{content_key(*key_parts)}{suffix}"


__all__ = ["cache_dir", "content_key", "cached_path"]
