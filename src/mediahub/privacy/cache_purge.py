"""Site-wide cache purge — permanently delete every re-derivable cache.

This is the deployment-level "clear the cache for the entire site, for all
runs" operation. It wipes every *performance* cache MediaHub writes under
``DATA_DIR``, for the whole deployment and across every organisation and run,
**and** drops the matching in-process caches so the worker handling the purge
stops serving them from memory — a disk-only purge would leave the cache
effectively intact in RAM.

Honest limit: the in-process drop reaches only the worker that runs the purge.
Under a multi-worker server (gunicorn ``--workers 2`` in the reference deploy)
sibling workers keep their in-memory entries until they next miss or restart;
the on-disk roots, shared by all workers, are gone immediately.

Nothing here is a source of truth: each directory is a cache the engine
rebuilds on demand — re-fetched PB-lookup pages, re-rendered motion, re-shot
graphic-card PNGs, re-captured brand DNA, re-synthesised narration, re-run web
research. Source data is deliberately **untouched**: runs (``runs_v4``),
uploads (``uploads_v4``), the SQLite databases (``data.db``, ``memory.db``),
the media library originals, and the JSONL ledgers all survive a purge. The
only cost of clearing is that the next request re-derives what it needs.

Each cache root is resolved through the owning module's own resolver where one
exists, so this follows path changes rather than duplicating them. All
resolution happens at call time from ``DATA_DIR`` (never frozen at import),
matching the rest of the codebase.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Tuple

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    """The writable data root — ``DATA_DIR`` when set, else ``src/mediahub``
    (the same dev default ``web.py`` and the cache modules use)."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def cache_roots() -> List[Tuple[str, Path]]:
    """Every re-derivable on-disk cache root, as ``(label, path)`` pairs.

    Resolved via each module's own resolver where one exists so a path change
    in (say) the motion cache or the PB-discovery tree is picked up here for
    free rather than silently diverging.
    """
    data = _data_dir()
    roots: List[Tuple[str, Path]] = [
        # PB-lookup HTML, the legacy swimmingresults mirror, and the web-research
        # cache all live under the shared ``.cache`` tree.
        ("pb_lookup_cache", data / ".cache"),
        ("motion_cache", data / "motion_cache"),
        ("ai_background_cache", data / "ai_bg_cache"),
        ("voice_cache", data / "voice_cache"),
        ("social_dna_cache", data / "social_dna_cache"),
        ("brand_dna_cache", data / "brand_dna_cache"),
        # Still-graphic renderer's HTML→PNG screenshot cache (G1.24). A pure
        # function of its inputs and disposable at any time, so it belongs in
        # the site-wide purge — without it "clear all caches" left every
        # rendered card PNG on disk despite the UI promising graphic renders.
        ("graphic_render_cache", data / "render_cache"),
    ]

    # PB-discovery tree (pbs / swimmers / search_cache / meets). The resolver
    # also migrates the legacy doubled-``data`` path, so use it.
    try:
        from mediahub.context_engine.cache import _discovered_root

        roots.append(("pb_discovery_cache", _discovered_root()))
    except Exception:  # best-effort: fall back to the conventional location
        roots.append(("pb_discovery_cache", data / "discovered"))

    # Creative-brief vision cache keeps its own module-level constant.
    try:
        from mediahub.creative_brief.generator import _VISION_CACHE_DIR

        roots.append(("vision_brief_cache", Path(_VISION_CACHE_DIR)))
    except Exception:
        pass

    # Rendered-document, microsite-asset, ASR-transcript and stock-thumbnail
    # caches each keep their own resolver (which mkdirs — harmless here, the
    # purge removes the tree anyway). Resolve through them so a path change is
    # picked up for free; fall back to the conventional DATA_DIR locations.
    try:
        from mediahub.documents.cache import cache_dir as _doc_cache_dir

        roots.append(("document_cache", _doc_cache_dir()))
    except Exception:
        roots.append(("document_cache", data / "document_cache"))
    try:
        from mediahub.sites.cache import cache_dir as _site_cache_dir

        roots.append(("site_cache", _site_cache_dir()))
    except Exception:
        roots.append(("site_cache", data / "site_cache"))
    try:
        from mediahub.visual.transcribe import cache_dir as _asr_cache_dir

        roots.append(("asr_cache", _asr_cache_dir()))
    except Exception:
        roots.append(("asr_cache", data / "asr_cache"))
    try:
        from mediahub.elements.stock import _thumb_cache_dir

        roots.append(("stock_thumb_cache", _thumb_cache_dir()))
    except Exception:
        roots.append(("stock_thumb_cache", data / "stock_thumb_cache"))

    return roots


def _purge_dir(path: Path) -> Tuple[int, int]:
    """Delete every file under ``path`` then remove the emptied tree.

    Returns ``(files_deleted, bytes_reclaimed)``. Tolerates a missing
    directory and individual unreadable/locked files (best-effort).
    """
    if not path.exists():
        return (0, 0)
    files = 0
    size = 0
    for f in path.rglob("*"):
        if not f.is_file():
            continue
        try:
            size += f.stat().st_size
        except OSError:
            pass
        try:
            f.unlink()
            files += 1
        except OSError:
            log.debug("cache purge: could not unlink %s", f)
    # Drop the now-empty directory tree itself; it is recreated lazily on the
    # next cache write by the owning module's mkdir.
    shutil.rmtree(path, ignore_errors=True)
    return (files, size)


def purge_all_caches() -> dict:
    """Permanently delete every re-derivable cache, site-wide.

    Clears both the on-disk cache roots and the matching in-process module
    caches in *this* worker (sibling workers drop theirs on their next miss
    or restart — see the module docstring).

    Returns a report::

        {
          "files_deleted": <int>,
          "bytes_reclaimed": <int>,
          "sections": {<label>: {"path", "files_deleted", "bytes_reclaimed"}},
          "inprocess_cleared": [<label>, ...],  # in-memory caches dropped
        }
    """
    sections: dict = {}
    total_files = 0
    total_bytes = 0
    seen: set = set()
    for label, path in cache_roots():
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            continue  # de-dupe overlapping roots (e.g. resolver aliasing)
        seen.add(resolved)
        files, size = _purge_dir(path)
        sections[label] = {
            "path": str(path),
            "files_deleted": files,
            "bytes_reclaimed": size,
        }
        total_files += files
        total_bytes += size

    # In-process caches that mirror the on-disk caches just purged. A disk-only
    # purge leaves the running worker serving these from memory and its RSS
    # unchanged, so "clear all caches" must drop them too — otherwise the cache
    # is not, in fact, cleared. Best-effort: a missing or broken module never
    # fails the purge. (web.py's own BoundedCaches live in the request process
    # and are cleared by the operator route — importing them here would cycle.)
    inprocess_cleared: List[str] = []
    try:
        from mediahub.graphic_renderer import render_cache as _render_cache

        # Drops the in-memory base64 asset-URI cache + hit/miss stats. The PNG
        # dir was already removed above, so clear()'s disk pass is a no-op.
        _render_cache.clear()
        inprocess_cleared.append("graphic_render_asset_cache")
    except Exception:
        log.debug("cache purge: could not clear render_cache in-memory cache", exc_info=True)
    try:
        from mediahub.graphic_renderer.render import clear_logo_prep_cache

        clear_logo_prep_cache()
        inprocess_cleared.append("logo_prep_cache")
    except Exception:
        log.debug("cache purge: could not clear logo-prep cache", exc_info=True)

    log.info(
        "site-wide cache purge: removed %d files, reclaimed %d bytes across %d roots; "
        "dropped in-process caches: %s",
        total_files,
        total_bytes,
        len(sections),
        ", ".join(inprocess_cleared) or "none",
    )
    return {
        "files_deleted": total_files,
        "bytes_reclaimed": total_bytes,
        "sections": sections,
        "inprocess_cleared": inprocess_cleared,
    }
