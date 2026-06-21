"""Per-platform channel specs — the data behind the 1.14 channel previews.

Before a club posts a card by hand, the Plan surface shows it the way each
platform will: the right crop/aspect, the platform's **safe zones** (where the
app's own chrome — profile, caption, buttons — covers the image), and the point
the **caption truncates** behind a "… more". This module is the single source of
those rules, expressed as plain data so they are reviewable and testable.

Deterministic + offline: this is mechanical platform geometry and text rules, not
a judgement call — so it stays out of the AI path entirely (CLAUDE.md: AI only
for judgement surfaces). MediaHub never posts; these previews are a review aid
for manual posting.

Honesty note: caption-truncation thresholds and reel safe-zone insets are
**display heuristics** — platforms tweak them and they vary by device. The
values here are sourced, conservative approximations for preview only, never a
guarantee of exact pixel parity with the live app. Each spec carries its
``source`` so a value can be checked and refreshed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SafeZone:
    """Fractional insets (0..1 of width/height) the platform chrome can cover.

    Used to draw a "keep clear" overlay on a preview — mainly for full-screen
    story/reel formats where the profile row, caption and action rail sit on top
    of the media. ``0`` everywhere means the whole frame is usable (feed posts).
    """

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0

    def to_dict(self) -> dict:
        return {"top": self.top, "right": self.right, "bottom": self.bottom, "left": self.left}


@dataclass(frozen=True)
class PlatformFormat:
    """One named crop a platform accepts (e.g. Instagram ``feed`` 1080×1350)."""

    name: str
    width: int
    height: int
    safe_zone: SafeZone = field(default_factory=SafeZone)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    def aspect_label(self) -> str:
        # Reduce to a small integer ratio for display (e.g. "4:5", "9:16").
        from math import gcd

        g = gcd(self.width, self.height) or 1
        return f"{self.width // g}:{self.height // g}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "aspect": self.aspect_label(),
            "safe_zone": self.safe_zone.to_dict(),
        }


@dataclass(frozen=True)
class PlatformSpec:
    """Everything a preview needs to render a card the way one platform shows it."""

    slug: str
    name: str
    formats: tuple[PlatformFormat, ...]
    default_format: str
    caption_limit: int  # hard maximum characters the platform accepts
    caption_truncate: int  # chars shown before a "… more" fold (display heuristic)
    hashtag_limit: Optional[int]  # max hashtags, or None when uncapped/counted in caption
    handle_max: int  # max @-handle length (mention validation)
    handle_chars: str  # regex char-class (without the @) a handle may use
    source: str = ""  # provenance for the numbers above

    def format(self, name: Optional[str] = None) -> PlatformFormat:
        want = name or self.default_format
        for f in self.formats:
            if f.name == want:
                return f
        return self.formats[0]

    def format_names(self) -> list[str]:
        return [f.name for f in self.formats]

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "formats": [f.to_dict() for f in self.formats],
            "default_format": self.default_format,
            "caption_limit": self.caption_limit,
            "caption_truncate": self.caption_truncate,
            "hashtag_limit": self.hashtag_limit,
            "handle_max": self.handle_max,
            "source": self.source,
        }


# Common story/reel safe zone — central column kept clear of the top profile row
# and the bottom caption + right-hand action rail. Conservative, for preview only.
_REEL_SAFE = SafeZone(top=0.12, right=0.06, bottom=0.20, left=0.06)
_TIKTOK_SAFE = SafeZone(top=0.10, right=0.13, bottom=0.18, left=0.04)


# The registry. Values are sourced approximations for PREVIEW (see module note).
PLATFORMS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        slug="instagram",
        name="Instagram",
        formats=(
            PlatformFormat("feed", 1080, 1350),
            PlatformFormat("square", 1080, 1080),
            PlatformFormat("story", 1080, 1920, _REEL_SAFE),
        ),
        default_format="feed",
        caption_limit=2200,
        caption_truncate=125,
        hashtag_limit=30,
        handle_max=30,
        handle_chars=r"A-Za-z0-9_.",
        source="Instagram Help: caption ≤2,200 chars, ≤30 hashtags; feed 4:5; "
        "stories/reels 9:16. Truncation ~125 chars is a display heuristic.",
    ),
    PlatformSpec(
        slug="tiktok",
        name="TikTok",
        formats=(PlatformFormat("video", 1080, 1920, _TIKTOK_SAFE),),
        default_format="video",
        caption_limit=2200,
        caption_truncate=100,
        hashtag_limit=None,
        handle_max=24,
        handle_chars=r"A-Za-z0-9_.",
        source="TikTok: 9:16 full-screen; caption up to ~2,200 chars (hashtags "
        "count toward it). Action rail + caption overlay on the lower-right.",
    ),
    PlatformSpec(
        slug="x",
        name="X (Twitter)",
        formats=(
            PlatformFormat("landscape", 1600, 900),
            PlatformFormat("square", 1080, 1080),
        ),
        default_format="landscape",
        caption_limit=280,
        caption_truncate=280,
        hashtag_limit=None,
        handle_max=15,
        handle_chars=r"A-Za-z0-9_",
        source="X: 280-char posts (base tier); 16:9 single-image preview; handles "
        "≤15 chars [A-Za-z0-9_].",
    ),
    PlatformSpec(
        slug="facebook",
        name="Facebook",
        formats=(
            PlatformFormat("portrait", 1080, 1350),
            PlatformFormat("landscape", 1200, 630),
        ),
        default_format="portrait",
        caption_limit=63206,
        caption_truncate=480,
        hashtag_limit=None,
        handle_max=50,
        handle_chars=r"A-Za-z0-9.",
        source="Facebook: long captions fold behind 'See more' (~480 chars is a "
        "display heuristic); link card 1.91:1, portrait 4:5.",
    ),
    PlatformSpec(
        slug="linkedin",
        name="LinkedIn",
        formats=(
            PlatformFormat("portrait", 1080, 1350),
            PlatformFormat("landscape", 1200, 627),
        ),
        default_format="portrait",
        caption_limit=3000,
        caption_truncate=210,
        hashtag_limit=None,
        handle_max=100,
        handle_chars=r"A-Za-z0-9-",
        source="LinkedIn: ~3,000-char posts folding behind 'see more' (~210 chars "
        "is a display heuristic); 1.91:1 or 4:5 imagery.",
    ),
)

_BY_SLUG = {p.slug: p for p in PLATFORMS}

# Accept a few friendly aliases so callers/UX can pass natural names.
_ALIASES = {
    "ig": "instagram",
    "insta": "instagram",
    "twitter": "x",
    "tweet": "x",
    "fb": "facebook",
    "meta": "facebook",
    "li": "linkedin",
}


def platform(slug: str) -> Optional[PlatformSpec]:
    """The spec for ``slug`` (alias-tolerant, case-insensitive), or None."""
    s = (slug or "").strip().lower()
    s = _ALIASES.get(s, s)
    return _BY_SLUG.get(s)


def all_platforms() -> tuple[PlatformSpec, ...]:
    return PLATFORMS


__all__ = [
    "SafeZone",
    "PlatformFormat",
    "PlatformSpec",
    "PLATFORMS",
    "platform",
    "all_platforms",
]
