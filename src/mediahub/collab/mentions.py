"""collab/mentions.py — parse @mentions in a comment and resolve them (1.18).

Pure text → people resolution, no I/O. A reviewer types ``@coach`` or
``@coach@club.org`` (or the person's name) in a comment; this finds those tokens
and matches them against the workspace's members, returning the emails to notify.
The web layer owns the side effects (writing the notification, sending the
email) — this module only decides *who was meant*.

Matching is deliberately forgiving for committee use: a token matches a member
by full email, by the email's local-part, or by a slug of their display name
(so ``@JaneDoe`` finds "Jane Doe"). The reserved ``@assistant`` handle is
recognised separately so the P6.2 assistant can be tagged into a thread (1.18 /
Build 5) without ever resolving to a human.
"""

from __future__ import annotations

import re
from typing import Iterable

# @token where token is an email-ish local part, optionally a full address.
_MENTION_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9._%+\-]+(?:@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})?)")

# Reserved handles that mean "the assistant", never a human member.
ASSISTANT_HANDLES = frozenset({"assistant", "ai", "mediahub", "copilot"})


def _slug(name: str) -> str:
    """Lowercase, alphanumerics only — so '@JaneDoe' can match 'Jane Doe'."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def extract_tokens(text: str) -> list[str]:
    """The distinct ``@token`` strings in ``text`` (without the leading @),
    lowercased, order-preserving."""
    if not text:
        return []
    out: list[str] = []
    for m in _MENTION_RE.finditer(text):
        tok = m.group(1).strip().lower()
        if tok and tok not in out:
            out.append(tok)
    return out


def mentions_assistant(text: str) -> bool:
    """True when the text tags the assistant (``@assistant`` / ``@ai`` / …)."""
    return any(tok in ASSISTANT_HANDLES for tok in extract_tokens(text))


def resolve_mentions(text: str, members: Iterable) -> list[str]:
    """Resolve @mentions in ``text`` to member emails.

    ``members`` is an iterable of ``(email, name)`` pairs (a bare email string is
    also accepted). A token matches by full email, by email local-part, or by a
    name slug. Returns distinct, lowercased emails in first-seen order. Reserved
    assistant handles never match a human and are skipped here.
    """
    tokens = [t for t in extract_tokens(text) if t not in ASSISTANT_HANDLES]
    if not tokens:
        return []

    # Build lookup tables once.
    by_email: dict[str, str] = {}
    by_local: dict[str, str] = {}
    by_slug: dict[str, str] = {}
    for entry in members:
        if isinstance(entry, str):
            email, name = entry, ""
        else:
            email = (entry[0] if len(entry) > 0 else "") or ""
            name = (entry[1] if len(entry) > 1 else "") or ""
        email = email.strip().lower()
        if not email:
            continue
        by_email.setdefault(email, email)
        local = email.split("@", 1)[0]
        if local:
            by_local.setdefault(local, email)
        slug = _slug(name)
        if slug:
            by_slug.setdefault(slug, email)

    out: list[str] = []
    for tok in tokens:
        email = by_email.get(tok) or by_local.get(tok) or by_slug.get(_slug(tok))
        if email and email not in out:
            out.append(email)
    return out


__all__ = [
    "ASSISTANT_HANDLES",
    "extract_tokens",
    "mentions_assistant",
    "resolve_mentions",
]
