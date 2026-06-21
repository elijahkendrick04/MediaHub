"""Sponsor A/B ad-variant sets (roadmap 1.14).

Take the copy angles a sponsor-activation draft already holds — each card the
content engine generated is one angle — and lay them out as an **A/B creative
set** for a paid campaign: every angle becomes a labelled variant (A, B, C…),
tagged with the sponsor, mapped to an ad platform's required sizes
(``ad_export.specs``), and bundled into an export manifest a club hands to
whoever runs the ads.

MediaHub **prepares, never spends** (standing rule): the output is creative +
a manifest for *manual* upload — no ad-account API, no spend, no auto-publish.
Pure and deterministic: same cards + sponsor + platform → same set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mediahub.ad_export.specs import AdPlatform, ad_platform

# A, B, C … labels for the variants (A/B testing convention).
_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MAX_VARIANTS = 12


@dataclass
class AdVariant:
    """One labelled creative angle in the A/B set."""

    label: str  # "A", "B", …
    caption: str
    hashtags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"label": self.label, "caption": self.caption, "hashtags": list(self.hashtags)}


@dataclass
class AdVariantSet:
    """An A/B creative set for one sponsor on one ad platform."""

    sponsor: str
    platform: AdPlatform
    variants: list[AdVariant] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "sponsor": self.sponsor,
            "platform": self.platform.to_dict(),
            "variants": [v.to_dict() for v in self.variants],
            "generated_at": self.generated_at,
        }


def build_variant_set(
    cards: list[dict],
    sponsor: str,
    platform_slug: str,
) -> Optional[AdVariantSet]:
    """Build the A/B set from a draft's cards. None when the platform is unknown.

    Each card with non-empty caption becomes one labelled variant (capped at
    ``MAX_VARIANTS``); the platform supplies the sizes. ``sponsor`` is whatever
    the draft/profile names — it is only a tag, never fabricated.
    """
    platform = ad_platform(platform_slug)
    if platform is None:
        return None
    variants: list[AdVariant] = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        caption = str(card.get("caption") or "").strip()
        if not caption:
            continue
        tags = [str(h).lstrip("#") for h in (card.get("hashtags") or []) if str(h).strip()]
        variants.append(AdVariant(label=_LABELS[len(variants)], caption=caption, hashtags=tags))
        if len(variants) >= MAX_VARIANTS:
            break
    return AdVariantSet(
        sponsor=(sponsor or "").strip(),
        platform=platform,
        variants=variants,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def manifest_text(variant_set: AdVariantSet) -> str:
    """A plain-text export manifest for manual upload to the ad platform."""
    s = variant_set
    sponsor = s.sponsor or "(sponsor not set)"
    lines: list[str] = []
    lines.append(f"Ad creative set — {sponsor} — {s.platform.name}")
    lines.append("=" * 64)
    lines.append(f"Generated: {s.generated_at}")
    lines.append(f"Variants: {len(s.variants)} (A/B test set)")
    lines.append("")
    lines.append("Prepare each variant's artwork at these sizes:")
    for sz in s.platform.sizes:
        lines.append(f"  - {sz.name}: {sz.width}x{sz.height} ({sz.aspect_label()})")
    lines.append("")
    for v in s.variants:
        lines.append(f"--- Variant {v.label} · sponsor: {sponsor} ---")
        lines.append(v.caption)
        if v.hashtags:
            lines.append("")
            lines.append(" ".join(f"#{h}" for h in v.hashtags))
        lines.append("")
    lines.append("-" * 64)
    lines.append(
        "MediaHub prepares this creative; it does NOT buy or place ads. Upload these "
        "variants and sizes manually in the ad platform's own manager, where a human "
        "controls targeting and spend."
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "AdVariant",
    "AdVariantSet",
    "MAX_VARIANTS",
    "build_variant_set",
    "manifest_text",
]
