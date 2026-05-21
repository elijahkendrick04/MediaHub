"""quality — deterministic distinctiveness metrics for generated content.

Offline, LLM-free measures that score generation *outputs* against the §8C
success metrics of the generative-AI thesis (structural distinctiveness,
perceptual spread, caption non-repetition).

Exposes:
  archetype_diversity   (variant_metrics)
  perceptual_spread     (variant_metrics)
  caption_repetition    (variant_metrics)
"""
from .variant_metrics import (
    archetype_diversity,
    caption_repetition,
    perceptual_spread,
)

__all__ = [
    "archetype_diversity",
    "caption_repetition",
    "perceptual_spread",
]
