"""elements — MediaHub's curated, brand-token-recolourable element library (roadmap 1.10).

A small, sport-editorial library of composable assets — sport pictograms, stat
and time chips, ribbons and badges, dividers, lines, frames and texture panels —
each a token-slotted SVG that :mod:`elements.recolour` paints in the card's own
brand colours, so every element is automatically on-brand and APCA-legible. Plus
brand-palette gradient presets.

In MediaHub a tightly-curated pack beats a million generic clip-art elements:
the defensible layer is *which element fits this moment* (the director + build-2
embedding search), not raw count. Stock photo/video pools and the draw/annotate
telestration layer build on this foundation (builds 3 and 4).

Public surface:
  - ``models``      — Element / ElementPlacement data model
  - ``catalog``     — load + query bundled and org-custom packs (deterministic)
  - ``recolour``    — brand-token → role-colour substitution (APCA-gated)
  - ``render``      — Element → recoloured inline SVG (cards + thumbnails)
  - ``gradients``   — brand-palette gradient presets
"""

from .models import Element, ElementPlacement, KINDS, SLOTS

__all__ = ["Element", "ElementPlacement", "KINDS", "SLOTS"]
