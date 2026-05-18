"""link_handlers/website.py — B1. Website handler.

Intent passed to the AI: the organisation's self-description, founding
story, sponsor relationships, and key messages. The website is
typically the richest single source so the orchestrator's strategy
proposer is told to look for About / Mission / Press / Brand pages.
"""
from __future__ import annotations

from . import process_link

PLATFORM = "website"
INTENT = (
    "Website. Look for the organisation's self-description, mission, "
    "history, sponsor relationships, key messages, and any brand-voice "
    "indicators (tone of headlines, recurring themes, what they "
    "emphasise about themselves). Pages worth checking: /about, "
    "/mission, /press, /brand, /partners. Extract voice and "
    "vocabulary; ignore navigation, footer boilerplate, cookie banners."
)


def normalise(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
