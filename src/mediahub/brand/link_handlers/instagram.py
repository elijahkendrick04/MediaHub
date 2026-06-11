"""link_handlers/instagram.py — B2. Instagram handler.

Intent: bio, recent caption tone, hashtag rhythm, post cadence pattern.
No hardcoded Instagram-specific extraction lives here — the orchestrator
delegates that to the strategy proposer + content extractor.
"""

from __future__ import annotations

from . import process_link

PLATFORM = "instagram"
INTENT = (
    "Instagram. Look for the organisation's bio, recent post caption "
    "tone (formal vs casual, emoji usage, sentence length), hashtag "
    "rhythm (how many per post, which ones recur), and what kinds of "
    "moments they post (results, training, social, sponsor mentions). "
    "Pay attention to how they refer to athletes/members and any "
    "characteristic openers or sign-offs."
)


def normalise(url: str) -> str:
    """Accept full URLs, bare handles, or @handle. Returns a canonical
    HTTPS URL on instagram.com.
    """
    u = (url or "").strip().lstrip("@")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        # bare handle case
        u = u.strip("/")
        u = f"https://www.instagram.com/{u}/"
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
