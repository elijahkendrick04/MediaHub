"""link_handlers/linkedin.py — B6. LinkedIn handler.

Intent: Company About text, recent post voice (more formal than the
other socials), professional positioning, sponsor / partner ecosystem,
and any awards or accreditations the organisation references.
"""

from __future__ import annotations

from . import process_link

PLATFORM = "linkedin"
INTENT = (
    "LinkedIn. Look for the Company / Page About text, recent post "
    "voice (more formal and professional than other socials), "
    "industry positioning, sponsor and partner ecosystem, accolades "
    "or accreditations mentioned, and the audience the page is "
    "writing for (members, recruiters, sponsors, peer organisations). "
    "Note any official phrasing the org uses about itself — those "
    "often double as press-release language."
)


def normalise(url: str) -> str:
    u = (url or "").strip().lstrip("@")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = u.strip("/")
        # Default to the company URL form; user can override with a full URL.
        if "/" not in u:
            u = f"https://www.linkedin.com/company/{u}"
        else:
            u = "https://www.linkedin.com/" + u
    return u


def process(url: str) -> dict:
    return process_link(PLATFORM, url, intent=INTENT, normalise_url=normalise)


__all__ = ["process", "PLATFORM", "INTENT"]
