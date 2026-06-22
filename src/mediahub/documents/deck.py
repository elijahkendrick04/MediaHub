"""documents.deck — deck view-model + version stamp for the presenter surface.

Small helpers shared by the presenter console, the audience view and the phone
remote (the web routes live in build 5): a per-slide outline (title + speaker
notes) and a stable ``spec_version`` stamp so a live edit of the deck can tell the
audience view to reload.
"""

from __future__ import annotations

import hashlib
import json

from .models import DocumentSpec


def spec_version(spec: DocumentSpec) -> str:
    """A short, stable stamp of the deck's content (changes when the deck does)."""
    raw = json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False)
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def _slide_title(blocks) -> str:
    for b in blocks:
        if b.kind == "heading":
            return str(b.props.get("text", ""))
    return ""


def deck_view(spec: DocumentSpec) -> dict:
    """The outline the presenter console + remote render from."""
    slides = []
    for i, section in enumerate(spec.sections):
        slides.append(
            {
                "index": i,
                "title": _slide_title(section.blocks) or f"Slide {i + 1}",
                "layout": section.layout,
                "background": section.background,
                "notes": section.notes or "",
            }
        )
    return {
        "doc_id": spec.doc_id,
        "title": spec.title,
        "kind": spec.kind,
        "total": len(spec.sections),
        "version": spec_version(spec),
        "slides": slides,
    }


__all__ = ["spec_version", "deck_view"]
