"""link_handlers/facebook.py — B3. Facebook handler.

Intent: Page About text, recent post voice, sponsor / partner mentions,
and the overall positioning the page projects.
"""
from __future__ import annotations

from . import process_link

PLATFORM = "facebook"
INTENT = (
    "Facebook Page. Look for the Page's About / Description text, "
    "recent post voice (longer-form than Instagram typically), "
    "sponsor or partner mentions, contact / venue information, and "
    "the audience the Page is clearly speaking to (members, parents, "
    "alumni, local community). Avoid generic Facebook UI strings; "
    "focus on what the organisation has actually written about itself."
)


def normalise(url: str) -> str:
    u = (url or "").strip().lstrip("@")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = u.strip("/")
        u = f"https://www.facebook.com/{u}"
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
