"""link_handlers/tiktok.py — B5. TikTok handler.

Intent: bio, recent video captions, trending hashtags the account
participates in, and any audio / music affinity worth knowing about for
motion compositions.
"""

from __future__ import annotations

from . import process_link

PLATFORM = "tiktok"
INTENT = (
    "TikTok. Look for the account bio, recent video captions (text "
    "overlaid on TikTok videos AND the caption beneath), hashtags "
    "they participate in, and any recurring music / audio choices "
    "the captions reference. Note caption length and emoji habits — "
    "TikTok captions are typically punchier than Instagram's. "
    "Identify the audience the account is performing to."
)


def normalise(url: str) -> str:
    u = (url or "").strip().lstrip("@")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = u.strip("/")
        # TikTok handles are typically @username
        if not u.startswith("@"):
            u = "@" + u
        u = f"https://www.tiktok.com/{u}"
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
