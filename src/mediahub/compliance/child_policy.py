"""Per-tenant child-protection content controls (ICO Children's Code / DUAA Art 25(1)).

In plain words: clubs can dial down how identifiable their under-18
athletes are in generated content —

- ``child_surname_initial``  — "Eira Hughes" appears as "Eira H."
- ``child_suppress_age``     — no age / age-group on the content
- ``child_exclude_photos``   — no photos of the athlete on under-18 posts

The transformation runs at the *pipeline* boundary (achievements are
transformed before cards are persisted, so stills/captions/reels all
inherit it) and again at the LLM caption boundary as a backstop for
legacy runs. The full name is kept in ``raw_facts.full_name`` — internal
only — so consent matching and erasure still find the athlete.

Applies to athletes with a known age under 18. An unknown age is NOT
transformed here (most UK meet results carry age-at-day); the consent
gate's opt-in mode is where unknown-age-as-minor conservatism lives.
Design rationale against the Code's 15 standards:
docs/compliance/CHILDRENS_CODE.md.
"""

from __future__ import annotations

import re
from typing import Optional


def _profile_flags(profile) -> tuple[bool, bool, bool]:
    if profile is None:
        return False, False, False
    if isinstance(profile, dict):
        return (
            bool(profile.get("child_surname_initial", False)),
            bool(profile.get("child_suppress_age", False)),
            bool(profile.get("child_exclude_photos", False)),
        )
    return (
        bool(getattr(profile, "child_surname_initial", False)),
        bool(getattr(profile, "child_suppress_age", False)),
        bool(getattr(profile, "child_exclude_photos", False)),
    )


def initialise_name(name: str) -> str:
    """'Eira Mair Hughes' → 'Eira H.' (first name + last-surname initial)."""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if len(parts) < 2:
        return (name or "").strip()
    return f"{parts[0]} {parts[-1][0].upper()}."


def _age_of(ach: dict) -> Optional[int]:
    for source in (ach, ach.get("raw_facts") or {}):
        if not isinstance(source, dict):
            continue
        raw = source.get("age")
        try:
            age = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if 0 < age < 130:
            return age
    return None


_AGE_DISPLAY_KEYS = ("age", "age_group", "aad", "age_at_day")


def apply_to_achievement(profile, ach: dict) -> dict:
    """Apply the tenant's child policy to one achievement dict, in place.

    Only touches under-18 athletes. Keeps the full name in
    ``raw_facts.full_name`` and the age in ``raw_facts.age`` so internal
    machinery (consent gate, safeguarding gate, erasure) keeps working.
    """
    if not isinstance(ach, dict):
        return ach
    surname_initial, suppress_age, _ = _profile_flags(profile)
    if not (surname_initial or suppress_age):
        return ach
    age = _age_of(ach)
    if age is None or age >= 18:
        return ach

    raw_facts = ach.get("raw_facts")
    if not isinstance(raw_facts, dict):
        raw_facts = {}
        ach["raw_facts"] = raw_facts
    if age is not None and "age" not in raw_facts:
        raw_facts["age"] = age

    if surname_initial:
        for key in ("swimmer_name", "name", "athlete_name"):
            full = ach.get(key)
            if isinstance(full, str) and full.strip() and " " in full.strip():
                raw_facts.setdefault("full_name", full.strip())
                short = initialise_name(full)
                ach[key] = short
                # free-text fields that embed the name (headlines)
                for text_key in ("headline", "subline", "caption"):
                    v = ach.get(text_key)
                    if isinstance(v, str) and full.strip() in v:
                        ach[text_key] = v.replace(full.strip(), short)

    if suppress_age:
        for key in _AGE_DISPLAY_KEYS:
            if key in ach:
                ach.pop(key, None)
        # age stays in raw_facts (internal) for the safeguarding/consent gates
    return ach


def apply_to_ranked(profile, ranked: list) -> list:
    """Apply the policy across a recognition report's ranked achievements."""
    surname_initial, suppress_age, _ = _profile_flags(profile)
    if not (surname_initial or suppress_age):
        return ranked
    for ra in ranked or []:
        if isinstance(ra, dict):
            ach = ra.get("achievement")
            if isinstance(ach, dict):
                apply_to_achievement(profile, ach)
            elif isinstance(ra, dict) and ("swimmer_name" in ra or "name" in ra):
                apply_to_achievement(profile, ra)
    return ranked


def exclude_athlete_photos_for_item(profile, item: dict) -> bool:
    """True when the tenant excludes photos on under-18 content and this
    item's athlete is (or may be) a minor."""
    _, _, exclude_photos = _profile_flags(profile)
    if not exclude_photos:
        return False
    ach = item.get("achievement") if isinstance(item.get("achievement"), dict) else item
    age = _age_of(ach if isinstance(ach, dict) else {})
    # For the PHOTO control, unknown age is treated as a minor — a photo of
    # an unidentified child is the highest-harm surface, so fail safe.
    return age is None or age < 18
