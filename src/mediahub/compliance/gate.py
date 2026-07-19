"""The consent gate — the one answer to "may this athlete appear?".

Every surface that can make a card public asks this module first:

- card approval (``POST /api/workflow/<run>/<card>`` in web.py),
- pack building (``api_turn_into`` filters blocked cards out).

Keeping the decision in one function means the answer cannot drift between
surfaces. The rule set is documented in ``compliance.consent``; the
"no-consent athlete can never be approved, packed, or published" guarantee
holds whenever the tenant runs in ``opt_in`` mode, and explicit
refusals/revocations/restrictions are honoured in every mode.
"""

from __future__ import annotations

from typing import Optional

from .consent import ConsentRegistry


def _profile_consent_settings(profile_id: str) -> tuple[str, bool]:
    """(consent_mode, require_parental_for_minors) for a tenant.

    Unset mode behaves as ``opt_out`` so legacy tenants keep working while
    explicit refusals still bite (see compliance.consent docstring).
    """
    mode, parental = "", True
    try:
        from mediahub.web.club_profile import load_profile

        profile = load_profile(profile_id) if profile_id else None
        if profile is not None:
            mode = (getattr(profile, "consent_mode", "") or "").strip()
            parental = bool(getattr(profile, "consent_require_parental_for_minors", True))
    except Exception:
        pass
    return (mode or "opt_out"), parental


def consent_block_reason(
    profile_id: str,
    athlete_name: str,
    *,
    age: Optional[int] = None,
) -> Optional[str]:
    """Why this athlete must NOT appear in public content — or None if OK.

    Consults BOTH consent systems: the W.2 safeguarding registry
    (per-athlete levels) and this compliance ledger (opt-outs, Art 18
    restriction, opt-in/parental mode, erasure suppression). Blocked if
    either blocks — one effective policy at every enforcement point.
    """
    name = (athlete_name or "").strip()
    if not name:
        return None  # cards without an athlete (e.g. club summary) pass

    # W.2 safeguarding levels (do_not_feature blocks; the photo/initials
    # levels are enforced at media selection / rendering, not here).
    try:
        from mediahub.safeguarding import effective_policy  # noqa: PLC0415

        if profile_id:
            # effective_policy is permissive when no regime is configured and
            # fails closed on a lookup error, so consult it directly rather than
            # gating on a separate regime_active() that could raise and skip the
            # whole W.2 check.
            policy = effective_policy(profile_id, name)
            if policy.blocked:
                return policy.reason or f"{name}'s consent level does not allow featuring"
    except Exception:
        # A failure reaching the safeguarding check must not silently open the
        # W.2 gate — block pending review (the ledger checks below add to this).
        return f"{name}: safeguarding consent check failed — blocked pending review"

    registry = ConsentRegistry(profile_id)
    rec = registry.get(name)

    if rec is not None and rec.restricted:
        return f"processing for {rec.athlete_name} is restricted (Art 18) — release the restriction first"
    if rec is not None and rec.status in ("refused", "revoked"):
        return f"{rec.athlete_name} has opted out of publication (consent {rec.status})"

    mode, require_parental = _profile_consent_settings(profile_id)
    if mode != "opt_in":
        return None

    if rec is None or rec.status != "granted":
        return (
            f"no recorded consent for {name} — this club requires opt-in consent before publication"
        )

    # Under-18 (or unknown age — treated as under-18, the conservative read)
    minor = (age is not None and age < 18) or (age is None and rec.under_18 is not False)
    if minor and require_parental and not rec.parental:
        return (
            f"consent for {rec.athlete_name} is recorded but not marked parental — "
            "under-18 athletes need a parent/guardian consent"
        )
    return None


def card_athlete(card: Optional[dict]) -> tuple[str, Optional[int]]:
    """(athlete name, age) from a card/achievement dict, tolerant of shapes.

    Cards appear as ``{"achievement": {...}}`` wrappers (ranked list), as
    flat achievement dicts, or as card dicts with ``raw_facts``.
    """
    if not isinstance(card, dict):
        return "", None
    ach = card.get("achievement") if isinstance(card.get("achievement"), dict) else card
    # Prefer the internal full name: child-policy display transforms keep it
    # in raw_facts so consent decisions match the registry record exactly.
    raw_facts = ach.get("raw_facts") if isinstance(ach.get("raw_facts"), dict) else {}
    name = str(
        raw_facts.get("full_name") or ach.get("swimmer_name") or ach.get("name") or ""
    ).strip()
    age: Optional[int] = None
    for source in (ach, ach.get("raw_facts") or {}):
        if not isinstance(source, dict):
            continue
        raw = source.get("age")
        try:
            if raw is not None and str(raw).strip():
                age = int(str(raw).strip())
                break
        except (TypeError, ValueError):
            continue
    return name, age


def consent_block_reason_for_card(profile_id: str, card: Optional[dict]) -> Optional[str]:
    name, age = card_athlete(card)
    return consent_block_reason(profile_id, name, age=age)


def find_card_in_run(run_data: Optional[dict], card_id: str) -> Optional[dict]:
    """Locate a card by id in a persisted run dict (same lookup web.py uses)."""
    if not isinstance(run_data, dict):
        return None
    rr = run_data.get("recognition_report") or {}
    for ra in rr.get("ranked_achievements") or []:
        ach = (ra or {}).get("achievement") or {}
        if ach.get("swim_id") == card_id or ra.get("id") == card_id:
            return ra
    for c in run_data.get("cards") or []:
        if isinstance(c, dict) and (c.get("swim_id") == card_id or c.get("id") == card_id):
            return c
    return None


def filter_consent_blocked(profile_id: str, run_data: dict) -> tuple[dict, list[str]]:
    """A copy of run_data with consent-blocked athletes' cards removed.

    Used before pack building so a blocked athlete cannot be rendered into
    a pack. Returns (filtered_run, sorted list of excluded athlete names).
    """
    excluded: set[str] = set()
    filtered = dict(run_data)

    rr = run_data.get("recognition_report")
    if isinstance(rr, dict):
        kept = []
        for ra in rr.get("ranked_achievements") or []:
            reason = consent_block_reason_for_card(profile_id, ra)
            if reason:
                name, _ = card_athlete(ra)
                excluded.add(name or "?")
            else:
                kept.append(ra)
        new_rr = dict(rr)
        new_rr["ranked_achievements"] = kept
        filtered["recognition_report"] = new_rr

    cards = run_data.get("cards")
    if isinstance(cards, list):
        kept_cards = []
        for c in cards:
            reason = consent_block_reason_for_card(profile_id, c)
            if reason:
                name, _ = card_athlete(c)
                excluded.add(name or "?")
            else:
                kept_cards.append(c)
        filtered["cards"] = kept_cards

    return filtered, sorted(excluded)
