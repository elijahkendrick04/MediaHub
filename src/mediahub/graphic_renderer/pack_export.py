"""Batch pack export — every rendered format of a content pack, plus a manifest (roadmap G1.15).

What this is
------------
A club approves a handful of cards, MediaHub renders each one at several format
sizes (the spec trio ``feed_square`` / ``feed_portrait`` / ``story`` by default,
sometimes more), and a social-media volunteer then wants *all of it* in one
download — every size of every card, organised so they can grab the right
crop for each channel, with a machine-readable record of what's inside.

This module builds exactly that: it walks a run's on-disk visuals, groups every
rendered PNG by card and by format, and bundles them into one ZIP alongside a
``metadata.json`` manifest. It is the engine behind the new
``/pack/<run_id>/export.zip`` download route.

Why packaging, not rendering
----------------------------
Rendering is the generation pipeline's job (``content_pack_visual.integration``
→ ``graphic_renderer.variants.render_all_formats``), which already produces the
format trio for every card and needs headless Chromium, the brand kit and the
media library. This module is deliberately a **pure, deterministic, dependency-
light packager**: it reads what was rendered, never shells out to a browser, so
the download route stays fast (no minute-long re-render inside a request) and
the whole thing is unit-testable without a browser. It is honest about coverage
— the manifest records, per card, which standard formats are present and which
are missing — rather than silently re-rendering or pretending.

Disk layout it reads (written by ``content_pack_visual.integration``)::

    <runs_dir>/<run_id>/visuals/<brief_id>/
        visual.json          # GeneratedVisual sidecar (+ optional embedded brief)
        feed_square.png      # one PNG per rendered format; stem == format name
        feed_portrait.png
        story.png

ZIP layout it writes::

    content-pack-<run_id>/
        metadata.json        # the manifest (the headline deliverable)
        README.txt           # plain-English guide to the folder
        cards/
            01-<slug>/
                feed_square.png
                feed_portrait.png
                story.png
                caption.txt   # only when a caption is known

Public API
----------
- ``collect_pack_cards(visuals_dir)`` → ordered list of ``PackCard`` records.
- ``build_manifest(run_id, cards, ...)`` → the ``metadata.json`` dict.
- ``build_pack_export(run_id, *, visuals_dir, ...)`` → ``PackExportResult``
  (zip bytes + manifest + counts) — the one call the route makes.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MANIFEST_VERSION = 1
MANIFEST_KIND = "mediahub.content_pack_export"
GENERATOR = "MediaHub graphic_renderer.pack_export"

# The formats every card is rendered at by default (variants.render_all_formats).
# Coverage in the manifest is reported against this set so the export is honest
# about which standard sizes a card is missing.
STANDARD_FORMATS: tuple[str, ...] = ("feed_square", "feed_portrait", "story")

# Human labels for the README + manifest (extra formats fall back to their id).
FORMAT_LABELS: dict[str, str] = {
    "feed_square": "Square (1:1 feed)",
    "feed_portrait": "Portrait (4:5 feed)",
    "story": "Story / Reel (9:16)",
    "reel_cover": "Reel cover (9:16)",
    "carousel_slide": "Carousel slide (1:1)",
}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class PackFormat:
    """One rendered format of one card."""

    format_name: str
    path: Path
    width: int
    height: int
    bytes: int
    sha256: str
    # Optional vector sidecar (<format>.svg written by the opt-in
    # MEDIAHUB_SVG_SIDECAR export) — bundled beside the PNG when present.
    svg_path: Optional[Path] = None


@dataclass
class PackCard:
    """One card in the pack — its sidecar metadata + every rendered format."""

    brief_id: str
    visual_id: str
    content_item_id: str
    layout_template: str
    confidence_label: str
    why_this_design: str
    palette: dict
    text_layers: dict
    source_asset_ids: list
    safety_notes: list
    formats: list[PackFormat] = field(default_factory=list)

    @property
    def formats_present(self) -> list[str]:
        return [f.format_name for f in self.formats]

    @property
    def formats_missing(self) -> list[str]:
        present = set(self.formats_present)
        return [f for f in STANDARD_FORMATS if f not in present]


@dataclass
class PackExportResult:
    """Output of :func:`build_pack_export`."""

    zip_bytes: bytes
    manifest: dict
    card_count: int
    image_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug(*parts: str, fallback: str = "card") -> str:
    """A filesystem-safe, lowercase slug from one or more text parts.

    Used for the per-card folder names; never trusts caller text into a path —
    everything outside ``[a-z0-9-]`` collapses to a single hyphen.
    """
    text = " ".join(p for p in parts if p)
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s[:60] or fallback


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Read (width, height) from a PNG's IHDR header. (0, 0) if not a PNG.

    Self-contained so the manifest carries the *actual* pixel size of each file
    without importing Pillow or trusting the format→size table.
    """
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    # IHDR is the first chunk: width is bytes 16-20, height 20-24 (big-endian).
    try:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return (width, height)
    except Exception:
        return (0, 0)


def _format_sort_key(name: str) -> tuple[int, str]:
    """Order formats: the standard trio first (in spec order), then the rest A-Z."""
    if name in STANDARD_FORMATS:
        return (STANDARD_FORMATS.index(name), name)
    return (len(STANDARD_FORMATS), name)


def _read_sidecar(brief_dir: Path) -> Optional[dict]:
    sidecar = brief_dir / "visual.json"
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_pack_cards(visuals_dir: str | Path) -> list[PackCard]:
    """Walk ``<run>/visuals``; return one :class:`PackCard` per brief dir.

    Each brief directory holds a ``visual.json`` sidecar and one PNG per
    rendered format (the PNG stem *is* the format name — see
    ``graphic_renderer.render.render_brief``). A directory with a sidecar but
    no PNGs is skipped (nothing to export); a malformed sidecar is skipped
    rather than fatal. Order is by brief-dir name so the result is stable.
    """
    visuals_dir = Path(visuals_dir)
    cards: list[PackCard] = []
    if not visuals_dir.is_dir():
        return cards

    for brief_dir in sorted(visuals_dir.iterdir()):
        if not brief_dir.is_dir():
            continue
        sidecar = _read_sidecar(brief_dir)
        if sidecar is None:
            continue

        formats: list[PackFormat] = []
        for png in brief_dir.glob("*.png"):
            try:
                data = png.read_bytes()
            except OSError:
                continue
            if not data:
                continue
            w, h = _png_dimensions(data)
            svg = png.with_suffix(".svg")
            formats.append(
                PackFormat(
                    format_name=png.stem,
                    path=png,
                    width=w,
                    height=h,
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    svg_path=svg if svg.is_file() else None,
                )
            )
        if not formats:
            continue
        formats.sort(key=lambda f: _format_sort_key(f.format_name))

        cards.append(
            PackCard(
                brief_id=brief_dir.name,
                visual_id=str(sidecar.get("id") or brief_dir.name),
                content_item_id=str(sidecar.get("content_item_id") or ""),
                layout_template=str(sidecar.get("layout_template") or ""),
                confidence_label=str(sidecar.get("confidence_label") or ""),
                why_this_design=str(sidecar.get("why_this_design") or ""),
                palette=dict(sidecar.get("palette") or {}),
                text_layers=dict(sidecar.get("text_layers") or {}),
                source_asset_ids=list(sidecar.get("sourced_asset_ids") or []),
                safety_notes=list(sidecar.get("safety_notes") or []),
                formats=formats,
            )
        )
    return cards


def _order_cards(cards: list[PackCard], order: Optional[list[str]]) -> list[PackCard]:
    """Reorder ``cards`` to follow ``order`` (a list of content_item_ids).

    Cards named in ``order`` come first, in that order (this is the approved-
    pack ranking when the route supplies it); anything not named keeps its
    stable by-dir position at the end. A no-op when ``order`` is falsy.
    """
    if not order:
        return cards
    rank = {cid: i for i, cid in enumerate(order)}
    ordered = sorted(
        enumerate(cards),
        key=lambda t: (rank.get(t[1].content_item_id, len(rank)), t[0]),
    )
    return [c for _, c in ordered]


def _card_title(card: PackCard) -> str:
    """A human card title from the text layers (swimmer + event), best-effort."""
    tl = card.text_layers or {}
    name = str(tl.get("swimmer_name") or tl.get("name") or tl.get("headline") or "").strip()
    event = str(tl.get("event") or tl.get("event_name") or "").strip()
    title = " — ".join(p for p in (name, event) if p)
    return title


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest(
    run_id: str,
    cards: list[PackCard],
    *,
    run_meta: Optional[dict] = None,
    club: Optional[dict] = None,
    captions: Optional[dict] = None,
    alt_texts: Optional[dict] = None,
    statuses: Optional[dict] = None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build the ``metadata.json`` manifest dict for an ordered list of cards.

    Lookups (``captions`` / ``alt_texts`` / ``statuses``) are keyed by
    ``content_item_id``. Everything is JSON-serialisable; the caller writes it
    into the ZIP. The per-card ``dir`` matches the folders :func:`build_pack_export`
    creates so the manifest is a faithful index of the archive.
    """
    captions = captions or {}
    alt_texts = alt_texts or {}
    statuses = statuses or {}
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()

    card_entries: list[dict] = []
    image_count = 0
    total_bytes = 0
    present_union: set[str] = set()

    for idx, card in enumerate(cards, start=1):
        cid = card.content_item_id
        folder = f"cards/{idx:02d}-{_slug(_card_title(card), card.visual_id)}"
        fmt_entries = []
        for f in card.formats:
            image_count += 1
            total_bytes += f.bytes
            present_union.add(f.format_name)
            entry = {
                "format": f.format_name,
                "label": FORMAT_LABELS.get(f.format_name, f.format_name),
                "file": f"{folder}/{f.format_name}.png",
                "width": f.width,
                "height": f.height,
                "bytes": f.bytes,
                "sha256": f.sha256,
            }
            if f.svg_path is not None:
                entry["svg_file"] = f"{folder}/{f.format_name}.svg"
            fmt_entries.append(entry)
        card_entries.append(
            {
                "index": idx,
                "dir": folder,
                "title": _card_title(card),
                "visual_id": card.visual_id,
                "content_item_id": cid,
                "brief_id": card.brief_id,
                "layout_template": card.layout_template,
                "confidence_label": card.confidence_label,
                "why_this_design": card.why_this_design,
                "text": card.text_layers,
                "status": str(statuses.get(cid, "") or ""),
                "caption": str(captions.get(cid, "") or ""),
                "alt_text": str(alt_texts.get(cid, "") or ""),
                "palette": card.palette,
                "source_asset_ids": card.source_asset_ids,
                "safety_notes": card.safety_notes,
                "formats": fmt_entries,
                "formats_present": card.formats_present,
                "formats_missing": card.formats_missing,
            }
        )

    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": MANIFEST_KIND,
        "generator": GENERATOR,
        "run_id": run_id,
        "generated_at": generated_at,
        "meet": dict(run_meta or {}),
        "club": dict(club or {}),
        "standard_formats": list(STANDARD_FORMATS),
        "summary": {
            "card_count": len(card_entries),
            "image_count": image_count,
            "total_image_bytes": total_bytes,
            "formats_present": sorted(present_union, key=_format_sort_key),
        },
        "cards": card_entries,
    }


def _readme_text(manifest: dict) -> str:
    """A plain-English guide to the archive, generated from the manifest."""
    summary = manifest.get("summary") or {}
    fmts = summary.get("formats_present") or []
    fmt_lines = (
        "\n".join(f"  - {FORMAT_LABELS.get(f, f)}  ({f}.png)" for f in fmts) or "  - (no images)"
    )
    meet = (manifest.get("meet") or {}).get("name") or manifest.get("run_id")
    return (
        "MediaHub content pack export\n"
        "============================\n\n"
        f"Meet: {meet}\n"
        f"Cards: {summary.get('card_count', 0)}   "
        f"Images: {summary.get('image_count', 0)}\n\n"
        "What's inside\n"
        "-------------\n"
        "Every approved and pending card (rejected cards are excluded),\n"
        "rendered at every available size, in its own folder under cards/.\n"
        "Each card's approval status is in metadata.json. Grab the size that\n"
        "fits the channel you're posting to:\n\n"
        f"{fmt_lines}\n\n"
        "Where a card has a caption.txt, that's the ready-to-post caption.\n\n"
        "metadata.json\n"
        "-------------\n"
        "A machine-readable manifest of everything here: each card's layout,\n"
        "colour palette, confidence label, the design reasoning, and which\n"
        "formats are present (and which standard sizes, if any, are missing).\n\n"
        "Post the visual + caption to your chosen platform manually — no\n"
        "third-party scheduler required.\n"
    )


# ---------------------------------------------------------------------------
# The export
# ---------------------------------------------------------------------------


def build_pack_export(
    run_id: str,
    *,
    visuals_dir: str | Path,
    run_meta: Optional[dict] = None,
    club: Optional[dict] = None,
    captions: Optional[dict] = None,
    alt_texts: Optional[dict] = None,
    statuses: Optional[dict] = None,
    order: Optional[list[str]] = None,
    generated_at: Optional[str] = None,
) -> PackExportResult:
    """Bundle every rendered format of every card in the pack into one ZIP.

    Parameters
    ----------
    run_id:
        The run whose visuals are being exported (folder/label only).
    visuals_dir:
        ``<runs_dir>/<run_id>/visuals`` — the directory of brief sub-dirs.
    run_meta / club:
        Optional dicts copied into the manifest's ``meet`` / ``club`` blocks
        (e.g. ``{"name": ..., "venue": ..., "date": ...}``).
    captions / alt_texts / statuses:
        Optional ``content_item_id`` → value maps. Captions are written as a
        ``caption.txt`` beside each card's images and recorded in the manifest.
    order:
        Optional list of ``content_item_id``s giving the pack ranking; cards in
        it are emitted first, in that order.
    generated_at:
        Optional ISO timestamp override (tests pin it for byte-stability).

    Returns
    -------
    PackExportResult
        ``zip_bytes`` (ready to stream as ``application/zip``), the ``manifest``
        dict, and ``card_count`` / ``image_count``.
    """
    cards = _order_cards(collect_pack_cards(visuals_dir), order)
    # A human rejected these cards — they must not ship in the download.
    # Approved and pending cards stay in, with their status in metadata.json.
    if statuses:
        cards = [
            c
            for c in cards
            if str(statuses.get(c.content_item_id, "") or "").strip().lower() != "rejected"
        ]
    manifest = build_manifest(
        run_id,
        cards,
        run_meta=run_meta,
        club=club,
        captions=captions,
        alt_texts=alt_texts,
        statuses=statuses,
        generated_at=generated_at,
    )

    root = f"content-pack-{_slug(run_id, fallback='run')}"
    captions = captions or {}

    buf = io.BytesIO()
    image_count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{root}/metadata.json", json.dumps(manifest, indent=2, default=str))
        z.writestr(f"{root}/README.txt", _readme_text(manifest))
        for entry, card in zip(manifest["cards"], cards):
            folder = f"{root}/{entry['dir']}"
            for f in card.formats:
                try:
                    z.writestr(f"{folder}/{f.format_name}.png", f.path.read_bytes())
                    image_count += 1
                except OSError:
                    continue
                if f.svg_path is not None:
                    try:
                        z.writestr(f"{folder}/{f.format_name}.svg", f.svg_path.read_bytes())
                    except OSError:
                        pass
            cap = str(captions.get(card.content_item_id, "") or "").strip()
            alt = str((alt_texts or {}).get(card.content_item_id, "") or "").strip()
            if cap or alt:
                body = ""
                if cap:
                    body += f"CAPTION:\n{cap}\n"
                if alt:
                    body += f"\nALT TEXT:\n{alt}\n"
                z.writestr(f"{folder}/caption.txt", body)

    buf.seek(0)
    return PackExportResult(
        zip_bytes=buf.getvalue(),
        manifest=manifest,
        card_count=len(cards),
        image_count=image_count,
    )


__all__ = [
    "MANIFEST_VERSION",
    "MANIFEST_KIND",
    "STANDARD_FORMATS",
    "FORMAT_LABELS",
    "PackFormat",
    "PackCard",
    "PackExportResult",
    "collect_pack_cards",
    "build_manifest",
    "build_pack_export",
]
