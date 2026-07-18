"""
Output pack assembler.

Given the approved/edited cards, produce:
  - a JSON export (machine-readable)
  - a text export (copy-ready captions split by category)
  - a zip bundle of both
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone

from .cards import (
    ContentCard,
    TYPE_STANDOUT, TYPE_SPOTLIGHT, TYPE_PB_ROUNDUP, TYPE_PODIUM_ROUNDUP,
    TYPE_QUAL_ALERT, TYPE_WEEKEND_NUMBERS,
)


def assemble_pack(
    cards: list[ContentCard],
    *,
    meet_name: str,
    club_name: str,
) -> dict:
    """Return a dict with keys: ready_to_post, recap, archive, summary."""
    by_bucket: dict[str, list[ContentCard]] = {
        "ready_to_post": [],
        "recap": [],
        "archive": [],
    }
    for c in cards:
        # Approved cards always go to ready_to_post (overrides bucket)
        if c.approved is True:
            by_bucket["ready_to_post"].append(c)
            continue
        if c.approved is False:
            by_bucket["archive"].append(c)
            continue
        # Default to bucket
        b = c.bucket
        if b == "queue":
            by_bucket["ready_to_post"].append(c)
        elif b in by_bucket:
            by_bucket[b].append(c)
        else:
            by_bucket["archive"].append(c)

    summary = {
        "meet_name": meet_name,
        "club_name": club_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {k: len(v) for k, v in by_bucket.items()},
    }
    return {
        "ready_to_post": by_bucket["ready_to_post"],
        "recap": by_bucket["recap"],
        "archive": by_bucket["archive"],
        "summary": summary,
    }


def render_text_pack(pack: dict) -> str:
    """Plain-text human-readable export."""
    lines: list[str] = []
    s = pack["summary"]
    lines.append(f"# Content Pack — {s['club_name']} · {s['meet_name']}")
    lines.append(f"Generated {s['generated_at']}")
    lines.append("")
    for label, key in [("Ready to post", "ready_to_post"),
                        ("Recap mentions", "recap")]:
        cards: list[ContentCard] = pack[key]
        if not cards:
            continue
        lines.append(f"## {label} ({len(cards)})")
        lines.append("")
        for c in cards:
            lines.append(f"### {c.headline}")
            if c.subhead:
                lines.append(c.subhead)
            lines.append("")
            chosen = c.user_caption or c.captions.team or c.captions.clean
            lines.append(chosen)
            lines.append("")
            if not c.user_caption:
                lines.append("Other voices:")
                if c.captions.clean:
                    lines.append(f"  • Clean: {c.captions.clean}")
                if c.captions.hype:
                    lines.append(f"  • Hype:  {c.captions.hype}")
                lines.append("")
            if c.evidence:
                lines.append("Evidence:")
                for e in c.evidence:
                    src = e.source
                    if e.source_url:
                        src = f"{src} ({e.source_url})"
                    lines.append(f"  • {e.claim} — {src}")
                lines.append("")
            lines.append(f"Why selected: {' · '.join(c.score_reasons[:5])}")
            lines.append(f"Score: {c.score} · Format: {c.suggested_format} · Confidence: {c.confidence}")
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines)


def render_json_pack(pack: dict) -> str:
    """Machine-readable JSON export."""
    serial = {
        "summary": pack["summary"],
        "ready_to_post": [c.to_dict() for c in pack["ready_to_post"]],
        "recap": [c.to_dict() for c in pack["recap"]],
    }
    return json.dumps(serial, indent=2, default=str)


def render_zip_bytes(pack: dict) -> bytes:
    """Bundle JSON + text + per-card text files into a zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("content_pack.json", render_json_pack(pack))
        z.writestr("content_pack.txt", render_text_pack(pack))
        # Per-card files for easy paste-and-go
        for label, key in [("ready_to_post", "ready_to_post"),
                            ("recap", "recap")]:
            for i, c in enumerate(pack[key], start=1):
                fname = f"{label}/{i:02d}_{_safe(c.headline)}.txt"
                body = (c.user_caption or c.captions.team or c.captions.clean) + "\n"
                z.writestr(fname, body)
    return buf.getvalue()


def _safe(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in s).strip().replace(" ", "_")[:60]
