"""governance/provenance.py — honest provenance manifests for AI output (1.23).

"Stamp every output, regardless of backend." Each thing MediaHub produces can
carry a small JSON manifest that answers *what made this, from what, and when* —
and, crucially, *what was AI and what was deterministic*. That honesty cuts both
ways: a generated image is marked as AI-generated media; a rendered result card
is marked as a **deterministic composite of real photography** (the pixels are
not AI — only the caption and creative direction may be), so the card is never
misrepresented as a synthetic image.

This module is the single schema + I/O. It is pure stdlib (no Flask, no sibling
governance imports) so it stays cheap to import from the rendering/integration
layers without dragging the web stack in.

Three builders, one shape:

  * :func:`build_card_manifest`           — a deterministically-rendered card
  * :func:`build_generated_image_manifest`— an AI-generated/edited image
  * :func:`build_caption_manifest`        — an AI-written caption (text)

and sidecar I/O (:func:`write_sidecar`, :func:`read_sidecar`,
:func:`sidecar_path`) plus a one-line :func:`summarise` for the UI.

Generative imagery and motion already write their own manifests
(``*.imagine.json`` / ``<hash>.json``); :func:`normalise` accepts any of them so
the governance dashboard can read a single, consistent shape.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Optional

from .._atomic_io import atomic_write_text

log = logging.getLogger(__name__)

PRODUCER = "MediaHub"
PROVENANCE_VERSION = 1

# kinds
KIND_CARD = "still_card"
KIND_GENERATED_IMAGE = "generated_image"
KIND_CAPTION = "caption"
KIND_STORY = "story"
KIND_REEL = "reel"

# how the pixels/text were produced
RENDER_DETERMINISTIC = "deterministic"
RENDER_AI_GENERATED = "ai_generated"
RENDER_AI_COMPOSITE = "ai_composite"


def _ai_component(component: str, *, provider: str = "", model: str = "", note: str = "") -> dict:
    """One AI-touched part of an output (caption, design direction, image, …)."""
    out = {"component": str(component)}
    if provider:
        out["provider"] = str(provider)
    if model:
        out["model"] = str(model)
    if note:
        out["note"] = str(note)
    return out


def _base(kind: str, *, produced_at: Optional[str]) -> dict:
    return {
        "produced_by": PRODUCER,
        "kind": kind,
        # produced_at is supplied by the caller (deterministic-friendly: no
        # hidden clock read here). Empty string when the caller has no stamp.
        "produced_at": str(produced_at or ""),
        "version": PROVENANCE_VERSION,
        "ai_components": [],
        "deterministic_components": [],
        "sources": {},
    }


def build_card_manifest(
    visual,
    *,
    brief=None,
    produced_at: Optional[str] = None,
    ai_components: Optional[Iterable[dict]] = None,
) -> dict:
    """Provenance for a deterministically-rendered result card.

    ``visual`` is a ``GeneratedVisual`` (or any object/dict exposing the same
    fields). The manifest states plainly that the pixels are a deterministic
    composite and the source photography is real — only listed ``ai_components``
    (e.g. an AI caption or AI creative direction) were AI-assisted.
    """
    g = _as_attr(visual)
    stamp = produced_at or g("rendered_at") or ""
    m = _base(KIND_CARD, produced_at=stamp)
    m["render"] = {
        "method": RENDER_DETERMINISTIC,
        "engine": "html_to_png",
        "layout": g("layout_template") or "",
        "format": g("format_name") or "",
        "width": g("width") or 0,
        "height": g("height") or 0,
    }
    m["deterministic_components"] = ["layout", "colour_science", "render"]
    photos = list(g("sourced_asset_ids") or [])
    m["sources"] = {
        "photos": photos,
        "photography": "real" if photos else "none",
    }
    m["palette"] = dict(g("palette") or {})
    m["text_layers"] = sorted((g("text_layers") or {}).keys())
    if g("why_this_design"):
        m["design_rationale"] = g("why_this_design")
    if g("safety_notes"):
        m["safety_notes"] = list(g("safety_notes") or [])
    components = list(ai_components or [])
    # The creative direction behind the card is AI-assisted in the v2 path; the
    # rationale string is the honest record of it.
    has_direction = any(c.get("component") == "design_direction" for c in components)
    if g("why_this_design") and not has_direction:
        components.append(_ai_component("design_direction", note="AI-assisted creative brief"))
    m["ai_components"] = components
    m["summary"] = (
        "Deterministically rendered by MediaHub; source photography is real "
        "(not AI-generated). Caption and creative direction may be AI-assisted."
    )
    if brief is not None:
        bid = getattr(brief, "id", None)
        if bid:
            m["brief_id"] = str(bid)
    return m


def build_generated_image_manifest(
    *,
    operation: str,
    provider: str = "",
    model: str = "",
    prompt: str = "",
    source_asset_id: str = "",
    produced_at: Optional[str] = None,
    content_sha256: str = "",
) -> dict:
    """Provenance for an AI-generated or AI-edited image.

    Wholesale generation (``generate`` / ``similar``) is ``ai_generated``; an
    edit of an existing photo (``edit`` / ``expand`` / ``remove`` / ``upscale`` /
    ``style_match``) is ``ai_composite``. Mirrors the IPTC DigitalSourceType
    distinction the imagine pipeline already embeds.
    """
    op = str(operation or "").strip().lower()
    composite = op in {"edit", "expand", "remove", "upscale", "style_match"}
    m = _base(KIND_GENERATED_IMAGE, produced_at=produced_at)
    m["render"] = {
        "method": RENDER_AI_COMPOSITE if composite else RENDER_AI_GENERATED,
        "operation": op,
    }
    m["ai_components"] = [
        _ai_component("image", provider=provider, model=model, note=op or "generate")
    ]
    if prompt:
        m["prompt"] = str(prompt)[:500]
    if source_asset_id:
        m["sources"] = {"source_asset_id": str(source_asset_id)}
    if content_sha256:
        m["content_sha256"] = str(content_sha256)
    m["summary"] = f"AI-{'edited' if composite else 'generated'} image" + (
        f" ({provider})" if provider else ""
    )
    return m


def build_caption_manifest(
    *,
    provider: str = "",
    model: str = "",
    tone: str = "",
    produced_at: Optional[str] = None,
) -> dict:
    """Provenance for an AI-written caption (text, not a file)."""
    m = _base(KIND_CAPTION, produced_at=produced_at)
    m["ai_components"] = [_ai_component("caption", provider=provider, model=model, note=tone)]
    m["summary"] = "AI-written caption" + (f" ({provider})" if provider else "")
    return m


# ---------------------------------------------------------------------------
# Sidecar I/O
# ---------------------------------------------------------------------------


def sidecar_path(image_path) -> Path:
    """The provenance sidecar path for an output file (``<file>.provenance.json``)."""
    return Path(str(image_path) + ".provenance.json")


def write_sidecar(image_path, manifest: dict) -> Optional[Path]:
    """Write ``manifest`` beside ``image_path``. Best-effort: returns the path or
    None on any failure (a provenance write must never sink a render)."""
    try:
        p = sidecar_path(image_path)
        atomic_write_text(p, json.dumps(manifest, indent=2, sort_keys=True, default=str))
        return p
    except OSError as exc:
        log.warning("provenance: sidecar write failed: %s", exc)
        return None


def read_sidecar(image_path) -> Optional[dict]:
    """Read the provenance sidecar for an output file, or None."""
    try:
        p = sidecar_path(image_path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("provenance: sidecar read failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Normalisation + summary (for the dashboard / audit reader)
# ---------------------------------------------------------------------------


def normalise(manifest: Optional[dict]) -> dict:
    """Coerce any manifest (ours, ``*.imagine.json``, motion ``<hash>.json``) to a
    consistent shape: ``{produced_by, kind, produced_at, ai, summary, raw}``.

    ``ai`` is True when the output had any AI component / AI render method.
    """
    m = dict(manifest or {})
    kind = m.get("kind") or _infer_kind(m)
    produced_at = m.get("produced_at") or m.get("created_at") or ""
    render = m.get("render") or {}
    method = render.get("method") if isinstance(render, dict) else ""
    digital = m.get("digital_source_type") or ""
    ai = bool(
        m.get("ai_components")
        or method in (RENDER_AI_GENERATED, RENDER_AI_COMPOSITE)
        or "algorithmic" in str(digital).lower()
        or str(m.get("generated_by") or "").startswith("media_ai.imagine")
    )
    return {
        "produced_by": m.get("produced_by") or m.get("software") or PRODUCER,
        "kind": kind,
        "produced_at": produced_at,
        "ai": ai,
        "summary": m.get("summary") or summarise(m),
        "raw": m,
    }


def _infer_kind(m: dict) -> str:
    if m.get("operation") or m.get("digital_source_type"):
        return KIND_GENERATED_IMAGE
    if m.get("cards") or m.get("rhythm"):
        return KIND_REEL
    return m.get("kind") or "unknown"


def summarise(manifest: Optional[dict]) -> str:
    """A one-line human description for the UI (best-effort, never raises)."""
    m = dict(manifest or {})
    if m.get("summary"):
        return str(m["summary"])
    kind = m.get("kind") or _infer_kind(m)
    if kind == KIND_GENERATED_IMAGE:
        prov = m.get("provider") or ""
        return "AI-generated image" + (f" ({prov})" if prov else "")
    if kind in (KIND_REEL, KIND_STORY):
        return f"MediaHub {kind} (deterministic render)"
    if kind == KIND_CARD:
        return "MediaHub result card (deterministic render)"
    if kind == KIND_CAPTION:
        return "AI-written caption"
    return "MediaHub output"


def _as_attr(obj):
    """Return a getter that reads ``obj.attr`` or ``obj['attr']`` uniformly."""
    if isinstance(obj, dict):
        return lambda k: obj.get(k)
    return lambda k: getattr(obj, k, None)


__all__ = [
    "PRODUCER",
    "PROVENANCE_VERSION",
    "KIND_CARD",
    "KIND_GENERATED_IMAGE",
    "KIND_CAPTION",
    "KIND_STORY",
    "KIND_REEL",
    "build_card_manifest",
    "build_generated_image_manifest",
    "build_caption_manifest",
    "sidecar_path",
    "write_sidecar",
    "read_sidecar",
    "normalise",
    "summarise",
]
