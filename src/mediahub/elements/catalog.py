"""elements.catalog — load and query the element library (roadmap 1.10).

Two sources, later wins on id collision (mirrors the audio library precedent):

  1. **Bundled pack** — ``catalog.json`` + ``assets/svg/*.svg`` shipped in the
     wheel. MediaHub's own first-party, CC0 sport-editorial elements.
  2. **Org-custom packs** — ``<DATA_DIR>/element_packs/<profile_id>/catalog.json``
     + sibling ``svg/``. Lets a club add its own crest/mascot stickers (build 4)
     without a code change.

Everything here is deterministic and offline: pure file reads + ordering. The
*choice* of which element fits a moment is AI territory (build 2's search); the
catalogue itself is plain data.
"""

from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .models import Element

_PACK_ROOT = Path(__file__).resolve().parent
_BUNDLED_CATALOG = _PACK_ROOT / "catalog.json"
_BUNDLED_SVG_DIR = _PACK_ROOT / "assets" / "svg"

_lock = threading.Lock()


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(_PACK_ROOT.parents[1])))


def _org_pack_dir(profile_id: str) -> Path:
    return _data_dir() / "element_packs" / str(profile_id)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def _load_manifest(path: Path, *, source: str) -> list[Element]:
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("elements") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    pack_id = ""
    if isinstance(raw, dict):
        pack_id = str(raw.get("pack", "")).strip()
    out: list[Element] = []
    for entry in entries:
        el = Element.from_dict(entry, source=source, pack=pack_id or "sport-editorial")
        if el is not None:
            out.append(el)
    return out


@lru_cache(maxsize=1)
def _bundled() -> tuple[Element, ...]:
    return tuple(_load_manifest(_BUNDLED_CATALOG, source="bundled"))


def load_catalog(profile_id: Optional[str] = None) -> list[Element]:
    """All elements visible to ``profile_id`` (bundled + that org's custom pack).

    Org-custom entries override bundled ones on matching id (a club can replace
    a default element with its own). Order is stable: bundled first (in manifest
    order), then any org-only additions.
    """
    by_id: dict[str, Element] = {el.id: el for el in _bundled()}
    order: list[str] = [el.id for el in _bundled()]
    if profile_id:
        custom = _load_manifest(_org_pack_dir(profile_id) / "catalog.json", source="org_custom")
        for el in custom:
            if el.id not in by_id:
                order.append(el.id)
            by_id[el.id] = el
    return [by_id[i] for i in order]


def get_element(element_id: str, profile_id: Optional[str] = None) -> Optional[Element]:
    for el in load_catalog(profile_id):
        if el.id == element_id:
            return el
    return None


def load_svg(element: Element, profile_id: Optional[str] = None) -> Optional[str]:
    """Read an element's raw SVG text (before recolour). ``None`` if missing."""
    candidates: list[Path] = []
    if element.source == "org_custom" and profile_id:
        candidates.append(_org_pack_dir(profile_id) / "svg" / element.svg_file)
    candidates.append(_BUNDLED_SVG_DIR / element.svg_file)
    for p in candidates:
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                continue
    return None


# --------------------------------------------------------------------------- #
# deterministic filters / facets
# --------------------------------------------------------------------------- #
def filter_elements(
    *,
    profile_id: Optional[str] = None,
    kind: Optional[str] = None,
    sport: Optional[str] = None,
    tags: Optional[list[str]] = None,
    mood: Optional[str] = None,
    query: str = "",
) -> list[Element]:
    """Tag/keyword filter (the deterministic fallback for build-2 search).

    ``query`` is a simple case-insensitive substring over each element's
    search text — no embedding provider needed, so browse always works even
    when no AI key is configured.
    """
    items = load_catalog(profile_id)
    q = (query or "").strip().lower()
    want_tags = {t.strip().lower() for t in (tags or []) if t.strip()}
    out: list[Element] = []
    for el in items:
        if kind and el.kind != kind:
            continue
        if sport and el.sport not in (sport, "general"):
            continue
        if mood and mood.strip().lower() not in {m.lower() for m in el.mood}:
            continue
        if want_tags and not (want_tags & {t.lower() for t in el.tags}):
            continue
        if q and q not in el.search_text().lower():
            continue
        out.append(el)
    return out


def list_kinds(profile_id: Optional[str] = None) -> list[str]:
    seen: list[str] = []
    for el in load_catalog(profile_id):
        if el.kind not in seen:
            seen.append(el.kind)
    return seen


def list_tags(profile_id: Optional[str] = None) -> list[str]:
    seen: set[str] = set()
    for el in load_catalog(profile_id):
        seen.update(el.tags)
    return sorted(seen)


def summary(profile_id: Optional[str] = None) -> dict:
    items = load_catalog(profile_id)
    by_kind: dict[str, int] = {}
    for el in items:
        by_kind[el.kind] = by_kind.get(el.kind, 0) + 1
    return {
        "count": len(items),
        "by_kind": by_kind,
        "kinds": list_kinds(profile_id),
        "tags": list_tags(profile_id),
    }


def reload_bundled_cache() -> None:
    """Drop the bundled-catalog cache (tests / hot-reload)."""
    with _lock:
        _bundled.cache_clear()


__all__ = [
    "load_catalog",
    "get_element",
    "load_svg",
    "filter_elements",
    "list_kinds",
    "list_tags",
    "summary",
    "reload_bundled_cache",
]
