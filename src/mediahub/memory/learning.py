"""mediahub/memory/learning.py — cross-run "what worked" caption memory.

Capability 2b. Turns an APPROVED card's *(event context → accepted caption)*
into a stored memory, and recalls the captions that worked for the most similar
past moments so new caption generation can be conditioned on a club's own
proven voice. Cloud embeddings (Cap 2a `embedder`) + sqlite-vec store (Cap 2a
`store`).

Retrieval key = the **event context** (event, type, PB?, placing, meet), NOT the
caption text — we map "this kind of meet moment" to "the caption voice that
worked for it," per the council verdict (avoids circular caption→caption recall).

Off-by-default and honest: every entry point is a no-op / empty list when no
embedding backend is configured. There is NO keyword fallback — when embeddings
are unavailable, recall simply returns nothing rather than substituting a
keyword search. Best-effort throughout: these helpers never raise into the
caption path.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_MIN_CORPUS = 50
DEFAULT_TOPK = 3


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def min_corpus() -> int:
    """Tenant corpus size below which recall stays dormant (cold-start guard).

    The council warns that KNN over a handful of captions returns confident
    noise; below this floor the feature is silently off. Operator-tunable via
    ``MEDIAHUB_MEMORY_MIN_CORPUS``.
    """
    return _int_env("MEDIAHUB_MEMORY_MIN_CORPUS", DEFAULT_MIN_CORPUS)


def top_k() -> int:
    return max(1, _int_env("MEDIAHUB_MEMORY_TOPK", DEFAULT_TOPK))


def canonical_event_context(achievement: dict) -> str:
    """A stable natural-language key describing the *moment* (never the caption).

    Built from structured achievement fields so the same kind of swim maps to a
    consistent embedding regardless of caption wording.
    """
    a = achievement or {}

    def g(*keys: str) -> str:
        for k in keys:
            v = a.get(k)
            if v not in (None, "", []):
                return str(v).strip()
        return ""

    parts: list[str] = []
    ev = g("event")
    if ev:
        parts.append(ev)
    typ = g("type")
    if typ:
        parts.append(typ)
    if a.get("pb"):
        parts.append("personal best")
    place = g("place", "placing")
    if place:
        parts.append(f"place {place}")
    meet = g("meet", "meet_name")
    if meet:
        parts.append(f"at {meet}")
    age = g("age_group", "age")
    if age:
        parts.append(f"age {age}")
    if not parts:  # nothing structured — fall back to the headline
        hl = g("headline")
        if hl:
            parts.append(hl)
    return " | ".join(parts).strip()


def is_enabled() -> bool:
    """True when an embedding backend is configured (the feature's master switch)."""
    try:
        from mediahub.memory import embedder

        return embedder.is_configured()
    except Exception:
        return False


def capture(profile_id, achievement: dict, caption: str, *, card_id, run_id: str = "") -> bool:
    """Remember an accepted caption for this moment.

    Returns True when stored, False when skipped (unconfigured, empty inputs, or
    unchanged from what's already stored). Never raises.
    """
    if not is_enabled():
        return False
    caption = (caption or "").strip()
    context = canonical_event_context(achievement)
    if not caption or not context or not profile_id or not card_id:
        return False
    try:
        from mediahub.memory import embedder, store

        # Redundancy guard: if we already stored this exact caption for this
        # card, skip — avoids paying for a re-embed on every pack view.
        if store.get_caption(tenant_id=str(profile_id), entry_id=str(card_id)) == caption:
            return False
        res = embedder.embed_one(context)
        if not res.vectors:
            return False
        store.upsert(
            tenant_id=str(profile_id),
            vector=res.vectors[0],
            model_id=res.model_id,
            caption=caption,
            event_context=context,
            entry_id=str(card_id),
            card_id=str(card_id),
            run_id=str(run_id),
        )
        return True
    except Exception as e:
        log.debug("memory.capture skipped: %s", e)
        return False


def recall(
    profile_id,
    achievement: dict,
    *,
    k: Optional[int] = None,
    min_corpus_override: Optional[int] = None,
) -> list[str]:
    """Return captions that worked for the most similar past moments for this
    club, nearest first.

    Empty list unless an embedding backend is configured AND the club's corpus
    is at least :func:`min_corpus` (cold-start guard). Never raises.
    """
    if not is_enabled():
        return []
    context = canonical_event_context(achievement)
    if not context or not profile_id:
        return []
    try:
        from mediahub.memory import embedder, store

        floor = min_corpus() if min_corpus_override is None else max(0, int(min_corpus_override))
        # Cheap pre-check (no embed) — most clubs are below the floor early on.
        if store.count(tenant_id=str(profile_id)) < floor:
            return []
        res = embedder.embed_one(context)
        if not res.vectors:
            return []
        hits = store.query(
            tenant_id=str(profile_id),
            vector=res.vectors[0],
            model_id=res.model_id,
            k=(k or top_k()),
        )
        out: list[str] = []
        seen: set[str] = set()
        for h in hits:
            c = (h.caption or "").strip()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out
    except Exception as e:
        log.debug("memory.recall skipped: %s", e)
        return []


__all__ = ["canonical_event_context", "capture", "recall", "is_enabled", "min_corpus", "top_k"]
