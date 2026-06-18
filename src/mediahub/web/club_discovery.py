"""
club_discovery.py — persist every club name observed during interpretation
to ``data/discovered/clubs/<slug>.json``.

This file feeds the universal club-picker dropdown so users can filter
recognition to ANY club ever seen by the engine, regardless of whether
that club has a saved profile.

Schema (per JSON file):

    {
        "name": "City of Manchester Aquatics",
        "slug": "city_of_manchester_aquatics",
        "slugs_seen": ["co_manch_aq", "city_of_manchester_aquatics"],
        "meets_seen_in": ["run_id_1", "run_id_2"],
        "first_seen": "2024-...",
        "last_seen": "2024-..."
    }
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)


def _clubs_root() -> Path:
    """Writable clubs store, under the shared ``DATA_DIR/discovered`` tree (the
    same resolver pb_discovery and the context engine use) — never the
    read-only package source. On the hosted deployment DATA_DIR is the mounted
    disk, so this resolves to a writable path instead of
    ``/app/src/mediahub/data`` (read-only → Permission denied)."""
    from mediahub.context_engine.cache import _data_root

    return _data_root() / "discovered" / "clubs"


def _slugify(value: str) -> str:
    if not value:
        return ""
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_")
    return cleaned.lower()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def record_clubs(
    club_names: Iterable[str],
    *,
    run_id: str,
    root: Optional[Path] = None,
) -> list[Path]:
    """
    Append-record each unique club name. Returns the list of file paths
    written. Idempotent: re-recording an existing club just appends the
    run_id (deduplicated) and updates ``last_seen``.

    Best-effort: club discovery feeds the universal picker but is never a parse
    dependency, so a read-only / unavailable store is logged and skipped — it
    must never abort the meet recap that triggered it.
    """
    try:
        base = Path(root) if root else _clubs_root()
        _ensure_dir(base)
    except OSError as exc:
        log.warning("Club discovery store unavailable, skipping: %s", exc)
        return []

    now_iso = datetime.now(timezone.utc).isoformat()
    written: list[Path] = []

    for raw in club_names:
        name = (raw or "").strip()
        if not name:
            continue
        slug = _slugify(name)
        if not slug:
            continue
        path = base / f"{slug}.json"

        try:
            if path.exists():
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    doc = {}
            else:
                doc = {}

            doc.setdefault("name", name)
            doc.setdefault("slug", slug)
            slugs_seen = set(doc.get("slugs_seen", []))
            slugs_seen.add(slug)
            doc["slugs_seen"] = sorted(slugs_seen)

            meets = list(doc.get("meets_seen_in", []))
            if run_id and run_id not in meets:
                meets.append(run_id)
            doc["meets_seen_in"] = meets

            doc.setdefault("first_seen", now_iso)
            doc["last_seen"] = now_iso

            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            written.append(path)
        except OSError as exc:
            log.warning("Could not record discovered club %r: %s", name, exc)
            continue

    return written


def list_discovered_clubs(root: Optional[Path] = None) -> list[dict]:
    """
    Return every recorded club document, sorted by name. Used by the
    universal club picker.
    """
    try:
        base = Path(root) if root else _clubs_root()
    except OSError:
        return []
    if not base.exists():
        return []
    docs: list[dict] = []
    for f in sorted(base.glob("*.json")):
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    docs.sort(key=lambda d: (d.get("name") or "").lower())
    return docs


def list_discovered_club_names(root: Optional[Path] = None) -> list[str]:
    return [d.get("name", "") for d in list_discovered_clubs(root) if d.get("name")]
