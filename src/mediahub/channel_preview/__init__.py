"""channel_preview — per-platform preview rules for the Plan surface (1.14).

Before a club posts a card by hand, MediaHub shows it the way each platform
will: the right crop/aspect, the platform **safe zones** (where the app chrome
covers the image), where the **caption truncates**, whether the hashtags fit the
cap, and whether an @-mention is valid for that platform. Plus an Instagram-style
**grid preview** of the planned feed.

All of it is plain data + pure functions (``specs.py`` / ``preview.py``):
deterministic, offline, no AI — mechanical platform geometry and text rules, a
review aid for *manual* posting (MediaHub never posts).
"""

from .preview import (
    hashtag_status,
    instagram_grid,
    preview_card,
    truncate_caption,
    validate_handle,
)
from .specs import PLATFORMS, PlatformFormat, PlatformSpec, SafeZone, all_platforms, platform

__all__ = [
    "PLATFORMS",
    "PlatformFormat",
    "PlatformSpec",
    "SafeZone",
    "all_platforms",
    "hashtag_status",
    "instagram_grid",
    "platform",
    "preview_card",
    "truncate_caption",
    "validate_handle",
]
