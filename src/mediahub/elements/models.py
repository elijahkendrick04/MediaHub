"""elements.models — the data model for the curated element library (roadmap 1.10).

An :class:`Element` is one composable, **brand-token-recolourable** SVG asset:
a sport pictogram, a stat/time chip, a ribbon/badge, a divider/line, a frame,
or a texture panel. The geometry lives in an SVG file under ``assets/svg/`` that
carries ``__SLOT__`` token placeholders (the same convention the icon-overlay
badges use — see ``graphic_renderer/icons/``); the metadata lives in
``catalog.json``. At paint time :mod:`elements.recolour` substitutes each slot
with the card's resolved brand role colour, so every element is automatically
on-brand and APCA-legible — never an off-palette sticker.

The model is deliberately small and curated: in MediaHub a tightly-edited,
sport-editorial pack beats a million generic clip-art elements (the defensible
layer is *choice* — which element fits this moment — not raw count).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The element kinds the library ships. Kept as a tuple (not an enum) so the
# catalog JSON stays plain-text and new kinds are additive.
KINDS: tuple[str, ...] = (
    "pictogram",  # sport iconography (strokes, dive, podium, trophy …)
    "chip",  # stat / time / rank chip (carries a value)
    "badge",  # placement / PB rosette
    "ribbon",  # award ribbon
    "divider",  # horizontal divider motif
    "line",  # rule / arrow accent line
    "frame",  # corner ticks / double-rule border
    "texture",  # repeating background panel (waves / chevron)
    "sticker",  # club mascot / emoji sticker (org-custom; build 4)
)

# Token slots an element SVG may reference. These map 1:1 onto the renderer's
# resolved ``--mh-*`` role vars in :mod:`elements.recolour`, so an element only
# ever paints in the brand's own colours.
SLOTS: tuple[str, ...] = (
    "GROUND",  # --mh-primary    (brand ground)
    "SECONDARY",  # --mh-secondary  (supporting colour)
    "SURFACE",  # --mh-surface    (deep tinted panel)
    "ACCENT",  # --mh-accent     (kicker / chip / medal tint — APCA-gated)
    "ON_GROUND",  # --mh-on-primary (text/ink on ground)
    "ON_SURFACE",  # --mh-on-surface (text/ink on surface)
    "OUTLINE",  # --mh-outline    (hairline rgba)
)


@dataclass(frozen=True)
class Element:
    """One library element. ``svg_file`` is resolved relative to the pack root."""

    id: str  # stable id, e.g. "pictogram.freestyle"
    name: str  # human label, e.g. "Freestyle stroke"
    kind: str  # one of KINDS
    sport: str  # "swimming" | "general"
    svg_file: str  # filename within the pack's svg/ dir
    tags: tuple[str, ...] = ()  # discrete filter tags, e.g. ("relay","speed")
    keywords: str = ""  # free-text description for embedding search
    mood: tuple[str, ...] = ()  # mood words, e.g. ("celebratory","bold")
    slots: tuple[str, ...] = ()  # which SLOTS the SVG uses (for validation/docs)
    aspect: float = 1.0  # nominal width/height (layout hint)
    carries_text: bool = False  # element paints text → APCA-gate at recolour
    licence: str = "first-party-CC0"  # bundled packs are MediaHub's own, CC0
    source: str = "bundled"  # "bundled" | "org_custom"
    pack: str = "sport-editorial"  # pack id this element belongs to

    # ------------------------------------------------------------------ #
    def search_text(self) -> str:
        """The text an embedding/keyword index is built over."""
        bits = [self.name, self.kind, self.sport, self.keywords]
        bits.extend(self.tags)
        bits.extend(self.mood)
        return " ".join(b for b in bits if b).strip()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "sport": self.sport,
            "svg_file": self.svg_file,
            "tags": list(self.tags),
            "keywords": self.keywords,
            "mood": list(self.mood),
            "slots": list(self.slots),
            "aspect": self.aspect,
            "carries_text": self.carries_text,
            "licence": self.licence,
            "source": self.source,
            "pack": self.pack,
        }

    @classmethod
    def from_dict(
        cls, data: dict, *, source: str = "bundled", pack: str = "sport-editorial"
    ) -> Optional["Element"]:
        """Build an Element from a catalog entry. Returns ``None`` if invalid.

        Unknown keys are dropped and missing optionals default, so older/newer
        catalog shapes load cleanly (mirrors ``CreativeBrief.from_dict``).
        """
        if not isinstance(data, dict):
            return None
        try:
            eid = str(data["id"]).strip()
            name = str(data["name"]).strip()
            kind = str(data["kind"]).strip()
            svg_file = str(data["svg_file"]).strip()
        except (KeyError, TypeError, ValueError):
            return None
        if not (eid and name and kind and svg_file):
            return None
        if kind not in KINDS:
            return None
        return cls(
            id=eid,
            name=name,
            kind=kind,
            sport=str(data.get("sport", "general")).strip() or "general",
            svg_file=svg_file,
            tags=tuple(str(t).strip() for t in data.get("tags", []) if str(t).strip()),
            keywords=str(data.get("keywords", "")).strip(),
            mood=tuple(str(m).strip() for m in data.get("mood", []) if str(m).strip()),
            slots=tuple(
                s for s in (str(x).strip().upper() for x in data.get("slots", [])) if s in SLOTS
            ),
            aspect=_safe_float(data.get("aspect", 1.0), 1.0),
            carries_text=bool(data.get("carries_text", False)),
            licence=str(data.get("licence", "first-party-CC0")).strip() or "first-party-CC0",
            source=source,
            pack=str(data.get("pack", pack)).strip() or pack,
        )


@dataclass(frozen=True)
class ElementPlacement:
    """A brief's request to paint one element on a card.

    Coordinates are fractions of the card's short edge / box (0..1) so the same
    placement renders consistently across formats. Additive + default-safe: a
    brief with no placements renders byte-identically (the sprint-hook contract).
    """

    element_id: str
    x: float = 0.5  # centre x, fraction of width (0..1)
    y: float = 0.5  # centre y, fraction of height (0..1)
    scale: float = 0.18  # size as a fraction of the card's short edge
    rotation: float = 0.0  # degrees
    opacity: float = 1.0  # 0..1

    def to_dict(self) -> dict:
        return {
            "element_id": self.element_id,
            "x": self.x,
            "y": self.y,
            "scale": self.scale,
            "rotation": self.rotation,
            "opacity": self.opacity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["ElementPlacement"]:
        if not isinstance(data, dict):
            return None
        eid = str(data.get("element_id", "") or data.get("id", "")).strip()
        if not eid:
            return None
        return cls(
            element_id=eid,
            x=_clamp01(_safe_float(data.get("x", 0.5), 0.5)),
            y=_clamp01(_safe_float(data.get("y", 0.5), 0.5)),
            scale=_clamp(_safe_float(data.get("scale", 0.18), 0.18), 0.02, 1.5),
            rotation=_safe_float(data.get("rotation", 0.0), 0.0),
            opacity=_clamp01(_safe_float(data.get("opacity", 1.0), 1.0)),
        )


# --------------------------------------------------------------------------- #
# small numeric helpers (deterministic, no deps)
# --------------------------------------------------------------------------- #
def _safe_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _clamp01(v: float) -> float:
    return _clamp(v, 0.0, 1.0)


__all__ = ["Element", "ElementPlacement", "KINDS", "SLOTS"]
