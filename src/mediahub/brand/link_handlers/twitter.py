"""link_handlers/twitter.py — B4. Twitter / X handler.

Intent: bio, pinned tweet, recent tweet/reply tone (length, register,
emoji usage), and the account's voice — formal news-line vs casual
community vs hype-fan.
"""
from __future__ import annotations

from . import process_link

PLATFORM = "twitter"
INTENT = (
    "Twitter / X. Look for the account bio, pinned tweet, recent "
    "tweet content and replies, and the account's overall voice "
    "register (newsline, hype, fan-account, official, community). "
    "Tweets are short so cadence and word choice matter — note any "
    "characteristic openers, sign-offs, emoji habits, and hashtag "
    "patterns. Distinguish announcements from conversational replies."
)


def normalise(url: str) -> str:
    u = (url or "").strip().lstrip("@")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = u.strip("/")
        u = f"https://x.com/{u}"
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
