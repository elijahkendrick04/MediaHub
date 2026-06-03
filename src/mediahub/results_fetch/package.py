"""mediahub/results_fetch/package.py — mirror → ZIP for the existing pipeline.

This is the join: it turns a crawl's in-memory mirror (kept files, captured JSON,
AI-extracted CSVs, screenshots, provenance) into a single ZIP that the existing
upload flow ingests *unchanged* — the same ``interpret_document(zip_bytes)`` path
a Hytek ``.zip`` takes. Nothing downstream knows the data came from a URL.

Two real constraints shape it:

  * **``_zip_safety`` budgets** — the interpreter refuses a ZIP with more than
    ``MAX_ZIP_MEMBERS`` (64) members or over the total-size cap. A championship
    frameset can have hundreds of event pages, so when the kept HTML would blow
    the member budget we **consolidate** HTML snapshots into a few combined
    documents (the interpreter already aggregates sibling event pages this way),
    keeping every table while staying within budget. Non-HTML data files
    (PDF/CSV/XLSX/JSON) and AI CSVs stay separate.
  * **Trust/explainability** — a ``_provenance.json`` records, per kept file, its
    source URL, the tier that read it, and the escalation trigger; AI-extracted
    tables carry an ``.ai.json`` sidecar marking ``extraction:"ai"`` + confidence.
    Screenshots ride along under ``_screenshots/`` (bounded).

Inert: importing this adds no route and changes no behaviour.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from dataclasses import dataclass
from typing import Optional

from mediahub.interpreter._zip_safety import (
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_ZIP_MEMBERS,
)

from .ai_read import AiExtraction
from .crawl import CrawlResult

log = logging.getLogger(__name__)

__all__ = ["package_mirror", "PackageStats"]

_SCREENSHOT_CAP = 8
_HTML_TYPES = ("text/html", "application/xhtml+xml")
# Leave headroom under the hard member cap for safety / future metadata.
_MEMBER_BUDGET = MAX_ZIP_MEMBERS - 2


@dataclass
class PackageStats:
    """Honest accounting of what made it into the mirror ZIP."""

    members: int = 0
    total_uncompressed: int = 0
    html_files: int = 0
    data_files: int = 0
    ai_tables: int = 0
    screenshots: int = 0
    dropped_for_budget: int = 0


def _is_html(content_type: str) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() in _HTML_TYPES


def _chunk(seq: list, n_chunks: int) -> list[list]:
    """Split ``seq`` into at most ``n_chunks`` roughly equal contiguous groups."""
    n_chunks = max(1, n_chunks)
    size = (len(seq) + n_chunks - 1) // n_chunks
    return [seq[i : i + size] for i in range(0, len(seq), size)] or [[]]


def package_mirror(
    crawl: CrawlResult,
    ai_extractions: Optional[list[AiExtraction]] = None,
) -> bytes:
    """Build the mirror ZIP from a crawl + its AI extractions.

    Returns the ZIP bytes ready for ``interpret_document``. Always within
    ``_zip_safety`` budgets: HTML is consolidated when the member count would
    otherwise exceed the cap, total uncompressed size is bounded, and the
    per-member size cap is honoured.
    """
    ai_extractions = ai_extractions or []
    stats = PackageStats()

    # Partition kept files into HTML (consolidatable) and other data (kept as-is).
    html_items: list[tuple[str, bytes, str]] = []  # (path, bytes, source_url)
    data_items: list[tuple[str, bytes]] = []
    for path, blob in crawl.files.items():
        prov = crawl.provenance.get(path)
        ctype = prov.content_type if prov else ""
        if _is_html(ctype):
            html_items.append((path, blob, prov.source_url if prov else path))
        else:
            data_items.append((path, blob))

    ai_members = sum(len(e.tables) for e in ai_extractions) * 2  # csv + sidecar each
    screenshots = list(crawl.screenshots.items())[:_SCREENSHOT_CAP]
    reserved = 1 + ai_members + len(screenshots) + len(data_items)  # 1 = _provenance.json
    html_slots = max(1, _MEMBER_BUDGET - reserved)

    members: dict[str, bytes] = {}
    file_provenance: dict[str, dict] = {}

    # --- HTML: separate when it fits, consolidated when it doesn't ----------
    if len(html_items) <= html_slots:
        for path, blob, _src in html_items:
            members[path] = blob
            prov = crawl.provenance.get(path)
            if prov:
                file_provenance[path] = _prov_dict(prov)
        stats.html_files = len(html_items)
    else:
        groups = _chunk(html_items, html_slots)
        for i, group in enumerate(groups):
            name = f"pages_{i + 1:03d}.html"
            joined = b"\n<!-- mediahub mirror page break -->\n".join(b for _p, b, _s in group)
            members[name] = joined
            file_provenance[name] = {
                "consolidated": True,
                "tier": "mixed",
                "sources": [s for _p, _b, s in group],
                "page_count": len(group),
            }
        stats.html_files = len(html_items)
        log.info("consolidated %d HTML pages into %d files", len(html_items), len(groups))

    # --- Non-HTML data files (PDF/CSV/XLSX/JSON, incl. captured APIs) --------
    for path, blob in data_items:
        members[path] = blob
        prov = crawl.provenance.get(path)
        if prov:
            file_provenance[path] = _prov_dict(prov)
    stats.data_files = len(data_items)

    # --- AI-extracted CSV tables + their trust sidecars ---------------------
    for ei, extraction in enumerate(ai_extractions):
        for ti, table in enumerate(extraction.tables):
            base = f"_ai/extract_{ei + 1:02d}_{ti + 1:02d}"
            members[f"{base}.csv"] = table.csv_bytes
            members[f"{base}.ai.json"] = json.dumps(table.sidecar, indent=2).encode("utf-8")
            file_provenance[f"{base}.csv"] = {
                "tier": "ai",
                "extraction": "ai",
                "source_url": table.sidecar.get("source_url", extraction.source_url),
                "confidence": table.sidecar.get("confidence", 0.0),
            }
            stats.ai_tables += 1

    # --- Screenshots (bounded; trust-only, harmless to ingestion) -----------
    for path, blob in screenshots:
        members[f"_screenshots/{os.path.basename(path)}"] = blob
        stats.screenshots += 1

    # --- Provenance manifest ------------------------------------------------
    provenance = {
        "entry_url": crawl.entry_url,
        "generated_at": time.time(),
        "counters": {
            "pages_visited": crawl.pages_visited,
            "kept": crawl.kept,
            "skipped": crawl.skipped,
            "blocked": crawl.blocked,
            "render_budget_hit": crawl.render_budget_hit,
        },
        "files": file_provenance,
        "ai_extractions": [
            {
                "source_url": e.source_url,
                "model": e.model,
                "tables": len(e.tables),
                "confidence": round(e.confidence, 3),
            }
            for e in ai_extractions
        ],
    }

    # --- Write the ZIP, bounding total uncompressed + per-member size -------
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # provenance first so it's always present even if we hit the size cap
        prov_bytes = json.dumps(provenance, indent=2, default=str).encode("utf-8")
        zf.writestr("_provenance.json", prov_bytes)
        total += len(prov_bytes)
        stats.members += 1
        for name, blob in members.items():
            if stats.members >= MAX_ZIP_MEMBERS:
                stats.dropped_for_budget += 1
                continue
            if len(blob) > MAX_MEMBER_UNCOMPRESSED_BYTES:
                stats.dropped_for_budget += 1
                continue
            if total + len(blob) > MAX_TOTAL_UNCOMPRESSED_BYTES:
                stats.dropped_for_budget += 1
                continue
            zf.writestr(name, blob)
            total += len(blob)
            stats.members += 1
    stats.total_uncompressed = total
    log.info("packaged mirror: %s", stats)
    return buf.getvalue()


def _prov_dict(prov) -> dict:
    return {
        "source_url": prov.source_url,
        "tier": prov.tier,
        "trigger": prov.trigger,
        "content_type": prov.content_type,
        "fetched_at": prov.fetched_at,
    }
