"""quality — deterministic, LLM-free checks on generated content.

Offline measures that score generation *outputs*: distinctiveness against the
§8C success metrics of the generative-AI thesis (structural distinctiveness,
perceptual spread, caption non-repetition), and colour accessibility of the
exact roles a card paints (per-card APCA/WCAG report + colourblind simulation).

Exposes:
  archetype_diversity   (variant_metrics)
  perceptual_spread     (variant_metrics)
  caption_repetition    (variant_metrics)
  audit_roles           (colour_audit) — per-card colour-accessibility audit
  audit_brief           (colour_audit) — audit the colours a brief would paint
  simulate_roles        (colour_audit) — the colourblind "preview" palette
  swatches_svg          (colour_audit) — a deterministic preview swatch strip
"""

from .colour_audit import (
    ColourAudit,
    audit_brief,
    audit_roles,
    simulate_roles,
    swatches_svg,
)
from .variant_metrics import (
    archetype_diversity,
    caption_repetition,
    perceptual_spread,
)

__all__ = [
    "archetype_diversity",
    "caption_repetition",
    "perceptual_spread",
    "ColourAudit",
    "audit_roles",
    "audit_brief",
    "simulate_roles",
    "swatches_svg",
]
