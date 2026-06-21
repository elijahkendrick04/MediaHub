"""Ad-platform creative specs — the sizes an ad-variant set targets (1.14).

The organic channel specs (``channel_preview``) describe how a post *looks* in a
feed; this is the paid-distribution counterpart: the exact creative **sizes** each
ad platform asks for, as plain data. A sponsor A/B set (``ad_export.variants``)
is laid out against these so a club can hand finished creative to whoever runs
the paid campaign.

MediaHub **prepares, never spends**: there is no ad-account API and no spend
automation here (standing rule) — only the spec data + an export manifest for
manual upload. Deterministic, offline, no AI (mechanical geometry).

Honesty note: ad sizes shift as platforms revise their managers; these are
sourced, common-denominator sizes for preparation, each platform carrying a
``source`` so the list can be checked and refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AdSize:
    """One named creative size an ad platform accepts."""

    name: str
    width: int
    height: int

    def aspect_label(self) -> str:
        from math import gcd

        g = gcd(self.width, self.height) or 1
        return f"{self.width // g}:{self.height // g}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "aspect": self.aspect_label(),
        }


@dataclass(frozen=True)
class AdPlatform:
    """An ad platform and the creative sizes a club should prepare for it."""

    slug: str
    name: str
    sizes: tuple[AdSize, ...]
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "sizes": [s.to_dict() for s in self.sizes],
            "source": self.source,
        }


# The registry. Sizes are sourced, common-denominator creatives (see module note).
AD_PLATFORMS: tuple[AdPlatform, ...] = (
    AdPlatform(
        slug="meta",
        name="Meta Ads (Facebook / Instagram)",
        sizes=(
            AdSize("Square", 1080, 1080),
            AdSize("Portrait (feed)", 1080, 1350),
            AdSize("Story / Reel", 1080, 1920),
        ),
        source="Meta Ads Manager: 1:1 and 4:5 feed, 9:16 stories/reels (1080px wide).",
    ),
    AdPlatform(
        slug="google_display",
        name="Google Display",
        sizes=(
            AdSize("Medium rectangle", 300, 250),
            AdSize("Large rectangle", 336, 280),
            AdSize("Leaderboard", 728, 90),
            AdSize("Half-page", 300, 600),
            AdSize("Large mobile banner", 320, 100),
            AdSize("Wide skyscraper", 160, 600),
        ),
        source="Google Display Network top-performing fixed sizes (support.google.com).",
    ),
    AdPlatform(
        slug="linkedin",
        name="LinkedIn Ads",
        sizes=(
            AdSize("Single image (landscape)", 1200, 627),
            AdSize("Square", 1080, 1080),
        ),
        source="LinkedIn single-image ad: 1.91:1 (1200×627) and 1:1.",
    ),
    AdPlatform(
        slug="tiktok",
        name="TikTok Ads",
        sizes=(AdSize("In-feed (9:16)", 1080, 1920),),
        source="TikTok in-feed ad: full-screen 9:16, 1080×1920.",
    ),
)

_BY_SLUG = {p.slug: p for p in AD_PLATFORMS}
_ALIASES = {
    "facebook": "meta",
    "instagram": "meta",
    "google": "google_display",
    "display": "google_display",
}


def ad_platform(slug: str) -> Optional[AdPlatform]:
    """The ad platform for ``slug`` (alias-tolerant, case-insensitive), or None."""
    s = (slug or "").strip().lower()
    s = _ALIASES.get(s, s)
    return _BY_SLUG.get(s)


def all_ad_platforms() -> tuple[AdPlatform, ...]:
    return AD_PLATFORMS


__all__ = [
    "AdSize",
    "AdPlatform",
    "AD_PLATFORMS",
    "ad_platform",
    "all_ad_platforms",
]
