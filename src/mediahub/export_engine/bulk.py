"""export_engine/bulk.py — bulk export jobs (roadmap 1.19).

"Export everything at once": take a set of rendered items (the cards in a pack,
a date range of content, a media-library selection) and a set of target formats,
convert each item to each format, and bundle the lot into one ZIP with a
machine-readable manifest. This is the engine half — a deterministic, Flask-free
function with a progress callback — so it can be driven equally by the on-demand
background-job route and by a recurring ``scheduler/`` task.

Honesty is built in: if one item can't be produced in one format (say a still
can't become an MP4), that single cell is recorded as an error in the manifest
and the job keeps going — you still get every file that *could* be made, and the
manifest tells you exactly what was skipped and why. Never a half-written ZIP, a
silent drop, or a fabricated file.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from . import cache as _cache
from .engine import ExportError, convert_file
from .formats import get_format, normalise_key
from .options import ExportOptions

# progress(done_items, total_items, current_label)
ProgressFn = Callable[[int, int, str], None]


def _slug(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (text or "").strip()).strip("-").lower()
    return s[:60] or fallback


@dataclass(frozen=True)
class BulkItem:
    """One thing to export: a name (its folder in the ZIP) and a source file."""

    name: str
    source: Path
    caption: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BulkExportSpec:
    """A bulk export request: items × formats, with shared options."""

    items: Sequence[BulkItem]
    formats: Sequence[str]
    options: ExportOptions = field(default_factory=ExportOptions)
    label: str = "mediahub-export"

    def normalised_formats(self) -> list[str]:
        seen: list[str] = []
        for f in self.formats:
            key = normalise_key(f)
            if key and key not in seen:
                seen.append(key)
        return seen

    def cache_token(self) -> str:
        parts = [self.label, ",".join(self.normalised_formats()), self.options.cache_token()]
        for it in self.items:
            parts.append(f"{it.name}:{_cache.file_fingerprint(it.source)}")
        return _cache.content_key(*parts)


@dataclass(frozen=True)
class BulkExportResult:
    """The outcome: the ZIP on disk plus the truth about what's in it."""

    zip_path: Path
    manifest: dict
    item_count: int
    file_count: int
    error_count: int
    from_cache: bool = False


def _readme(label: str, manifest: dict) -> str:
    s = manifest["summary"]
    lines = [
        f"{label} — MediaHub bulk export",
        "",
        f"Generated: {manifest['generated_at']}",
        f"Formats:   {', '.join(manifest['formats'])}",
        f"Items:     {s['items']}",
        f"Files:     {s['files']}",
    ]
    if s["errors"]:
        lines += [
            f"Skipped:   {s['errors']} (see manifest.json — each says why)",
        ]
    lines += [
        "",
        "Every file in here was made by MediaHub on our own server (Pillow/FFmpeg).",
        "Approve before posting — MediaHub never publishes for you.",
    ]
    return "\n".join(lines) + "\n"


def run_bulk_export(
    spec: BulkExportSpec,
    *,
    out: Optional[Path] = None,
    progress: Optional[ProgressFn] = None,
    use_cache: bool = True,
) -> BulkExportResult:
    """Execute a :class:`BulkExportSpec` → a ZIP on disk, reporting progress.

    With ``out`` omitted the ZIP lands in the content-addressed export cache, so
    an identical request is a free cache hit.
    """
    formats = spec.normalised_formats()
    if not formats:
        raise ExportError("bulk export needs at least one target format")
    items = list(spec.items)
    label = _slug(spec.label, "mediahub-export")
    opts = spec.options.clamped()

    # Resolve destination / cache slot.
    if out is not None:
        zip_path = Path(out)
        cache_hit = False
    else:
        zip_path = _cache.cached_path(".zip", "bulk", spec.cache_token())
        cache_hit = use_cache and zip_path.is_file() and zip_path.stat().st_size > 0

    if cache_hit:
        manifest = _read_manifest_from_zip(zip_path)
        s = manifest.get("summary", {})
        return BulkExportResult(
            zip_path=zip_path,
            manifest=manifest,
            item_count=int(s.get("items", 0)),
            file_count=int(s.get("files", 0)),
            error_count=int(s.get("errors", 0)),
            from_cache=True,
        )

    _cache.maybe_gc()  # bound old bulk ZIPs / export-cache growth (best-effort)

    # Stream the archive to a temp sibling and os.replace into place: peak RAM
    # is one member (not the whole archive twice), and a crash mid-build can
    # never leave a truncated ZIP at the path the share route existence-checks.
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = zip_path.with_name(zip_path.name + ".tmp")
    try:
        manifest, file_count, error_count = _write_zip(
            tmp_path, items, formats, label, opts, progress
        )
        os.replace(tmp_path, zip_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return BulkExportResult(
        zip_path=zip_path,
        manifest=manifest,
        item_count=len(items),
        file_count=file_count,
        error_count=error_count,
        from_cache=False,
    )


def _write_zip(
    tmp_path: Path,
    items: Sequence[BulkItem],
    formats: Sequence[str],
    label: str,
    opts: ExportOptions,
    progress: Optional[ProgressFn],
) -> tuple[dict, int, int]:
    """Build the archive at ``tmp_path``; returns (manifest, files, errors)."""
    total = len(items)
    manifest_items: list[dict] = []
    file_count = 0
    error_count = 0
    total_bytes = 0

    with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for idx, item in enumerate(items):
            name = _slug(item.name, f"item-{idx + 1:02d}")
            # De-duplicate folder names so two same-named items don't collide.
            base = name
            n = 2
            while name in used_names:
                name = f"{base}-{n}"
                n += 1
            used_names.add(name)

            files: list[dict] = []
            errors: list[dict] = []
            for fmt in formats:
                ext = get_format(fmt).suffix
                arc = (
                    f"{label}/{name}/{name}{ext}"
                    if len(formats) == 1
                    else f"{label}/{name}/{fmt}{ext}"
                )
                try:
                    res = convert_file(item.source, fmt, options=opts)
                    data = res.path.read_bytes()
                    zf.writestr(arc, data)
                    files.append({"format": fmt, "path": arc[len(label) + 1 :], "bytes": len(data)})
                    file_count += 1
                    total_bytes += len(data)
                except Exception as exc:  # noqa: BLE001 - record and continue
                    errors.append({"format": fmt, "error": str(exc)})
                    error_count += 1

            if item.caption:
                cap_arc = f"{label}/{name}/caption.txt"
                zf.writestr(cap_arc, item.caption)
            entry = {"name": name, "source": Path(item.source).name, "files": files}
            if errors:
                entry["errors"] = errors
            if item.meta:
                entry["meta"] = item.meta
            manifest_items.append(entry)

            if progress is not None:
                try:
                    progress(idx + 1, total, name)
                except Exception:
                    pass

        manifest = {
            "kind": "mediahub-bulk-export",
            "manifest_version": 1,
            "label": label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "formats": formats,
            "options": opts.to_dict(),
            "summary": {
                "items": total,
                "files": file_count,
                "errors": error_count,
                "bytes": total_bytes,
            },
            "items": manifest_items,
        }
        zf.writestr(f"{label}/manifest.json", json.dumps(manifest, indent=2))
        zf.writestr(f"{label}/README.txt", _readme(label, manifest))

    return manifest, file_count, error_count


def _read_manifest_from_zip(zip_path: Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for n in zf.namelist():
                if n.endswith("/manifest.json") or n == "manifest.json":
                    return json.loads(zf.read(n))
    except Exception:  # noqa: BLE001
        pass
    return {"summary": {}}


__all__ = [
    "BulkItem",
    "BulkExportSpec",
    "BulkExportResult",
    "run_bulk_export",
    "ProgressFn",
]
