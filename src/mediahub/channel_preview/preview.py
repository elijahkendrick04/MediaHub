"""Channel-preview computation — caption truncation, safe zones, mentions, grid.

Pure functions over :mod:`channel_preview.specs`: given a card and a platform,
work out exactly what a club will see when it posts by hand — where the caption
folds, whether the hashtags are within the cap, whether an @-mention is valid for
that platform, and the safe-zone overlay for a story/reel crop. The web layer
turns these dicts into the preview frames.

Deterministic + offline; no AI (mechanical platform rules). MediaHub never
posts — this is a review aid for manual posting.
"""

from __future__ import annotations

import re
from typing import Optional

from mediahub.channel_preview.specs import PlatformSpec, PlatformFormat, platform


def truncate_caption(text: str, spec: PlatformSpec) -> dict:
    """Split ``text`` into the part shown before the platform's "… more" fold and
    the hidden remainder. Returns ``{shown, hidden, truncated, length, over_limit}``.

    The fold is a display heuristic (see specs); ``over_limit`` flags a caption
    that exceeds the platform's hard maximum and would be rejected outright.
    """
    text = text or ""
    length = len(text)
    over_limit = length > spec.caption_limit
    cut = spec.caption_truncate
    if length <= cut:
        return {
            "shown": text,
            "hidden": "",
            "truncated": False,
            "length": length,
            "over_limit": over_limit,
        }
    # Prefer to fold on a word boundary at/just before the cut for a natural look.
    head = text[:cut]
    sp = head.rfind(" ")
    if sp >= cut - 18 and sp > 0:  # only honour a nearby space, else hard cut
        head = head[:sp]
    return {
        "shown": head.rstrip(),
        "hidden": text[len(head) :].lstrip(),
        "truncated": True,
        "length": length,
        "over_limit": over_limit,
    }


def hashtag_status(hashtags, spec: PlatformSpec) -> dict:
    """Whether the hashtag count is within the platform cap.
    ``{count, limit, within}`` — ``limit`` None means uncapped."""
    count = len([h for h in (hashtags or []) if str(h).strip()])
    limit = spec.hashtag_limit
    within = True if limit is None else count <= limit
    return {"count": count, "limit": limit, "within": within}


def validate_handle(handle: str, spec: PlatformSpec) -> dict:
    """Validate an @-mention for one platform. ``{handle, valid, reason}``.

    Per-platform character set + max length (specs). A leading ``@`` is optional
    on input and normalised away. Empty input is invalid (nothing to tag).
    """
    raw = (handle or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if not raw:
        return {"handle": "", "valid": False, "reason": "empty"}
    if len(raw) > spec.handle_max:
        return {
            "handle": raw,
            "valid": False,
            "reason": f"too long for {spec.name} (max {spec.handle_max})",
        }
    if not re.fullmatch(f"[{spec.handle_chars}]+", raw):
        return {
            "handle": raw,
            "valid": False,
            "reason": f"invalid characters for {spec.name}",
        }
    return {"handle": raw, "valid": True, "reason": ""}


def preview_card(
    card: dict,
    platform_slug: str,
    *,
    format_name: Optional[str] = None,
) -> Optional[dict]:
    """Everything a preview frame needs for one card on one platform, or None
    when the platform slug is unknown.

    ``card`` is a stub-pack card dict (``{caption, hashtags, platform?, ...}``).
    """
    spec = platform(platform_slug)
    if spec is None:
        return None
    fmt: PlatformFormat = spec.format(format_name)
    caption = str(card.get("caption") or "")
    trunc = truncate_caption(caption, spec)
    tags = hashtag_status(card.get("hashtags"), spec)
    return {
        "platform": spec.slug,
        "platform_name": spec.name,
        "format": fmt.to_dict(),
        "caption": trunc,
        "hashtags": tags,
        "caption_limit": spec.caption_limit,
        "caption_truncate": spec.caption_truncate,
        "source": spec.source,
    }


def instagram_grid(cells: list[dict], *, columns: int = 3) -> list[list[dict]]:
    """Arrange feed cells into the Instagram-style grid (newest first, left→right,
    top→bottom), padded so the final row is full. Each cell passes through as-is;
    callers supply ``{title, thumb?, status?, ...}``. Deterministic."""
    cols = max(1, int(columns))
    rows: list[list[dict]] = []
    row: list[dict] = []
    for c in cells:
        row.append(c)
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        while len(row) < cols:
            row.append({"placeholder": True})
        rows.append(row)
    return rows


__all__ = [
    "truncate_caption",
    "hashtag_status",
    "validate_handle",
    "preview_card",
    "instagram_grid",
]
