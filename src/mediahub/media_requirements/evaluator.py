"""Evaluate readiness of a content item against its media requirements.

Inputs:
  - content_item: dict with at least {post_angle, achievement{swimmer_name, ...}}
  - library_assets: iterable[MediaAsset]  (filtered by profile_id by caller)
  - profile / brand info (for logo presence)

Output: EvaluationResult with status, matched_assets per role, missing roles,
and a recommended_action string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from mediahub.media_library import MediaAsset, select_assets

from .rules import requirements_for


READY = "ready"
NEEDS_MEDIA = "needs_media"
SKIP_LOW_CONFIDENCE = "skip_low_confidence"
TEXT_LED_OK = "text_led_ok"


@dataclass
class EvaluationResult:
    content_item_id: str
    content_type: str
    status: str  # READY | NEEDS_MEDIA | SKIP_LOW_CONFIDENCE | TEXT_LED_OK
    suggested_layout: str
    matched: dict[str, list[dict]]  # role -> scored asset dicts (best first)
    missing_required: list[str]
    missing_optional: list[str]
    recommended_action: str
    confidence_tier: str = "high"  # high | medium | low
    confidence_label: str = "NEW PB"  # readable label for graphic ("NEW PB" / "LIKELY PB" / ...)
    explain: str = ""
    # PHOTOS-6: when hero matching fails but this meet's uploads exist,
    # the top-k of those photos — surfaced for a HUMAN to pick from, never
    # auto-placed on a named card (they carry no verified athlete link).
    candidates: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content_item_id": self.content_item_id,
            "content_type": self.content_type,
            "status": self.status,
            "suggested_layout": self.suggested_layout,
            "matched": self.matched,
            "missing_required": self.missing_required,
            "missing_optional": self.missing_optional,
            "recommended_action": self.recommended_action,
            "confidence_tier": self.confidence_tier,
            "confidence_label": self.confidence_label,
            "explain": self.explain,
            "candidates": self.candidates,
        }


# ---------------------------------------------------------------------------
# Confidence handling — engine-level, not sport-specific
# ---------------------------------------------------------------------------


def _confidence_tier_and_label(content_item: dict) -> tuple[str, str]:
    """Map the raw confidence + post_angle to a tier and graphic label."""
    angle = (
        content_item.get("post_angle")
        or content_item.get("achievement", {}).get("post_angle")
        or ""
    )
    s2p = content_item.get("safe_to_post") or {}
    s2p_level = s2p.get("level") if isinstance(s2p, dict) else "needs_review"
    conf = (
        content_item.get("confidence")
        or content_item.get("achievement", {}).get("confidence")
        or 0.5
    )
    try:
        conf = float(conf)
    except Exception:
        conf = 0.5

    # Low confidence / do_not_post → skip
    if s2p_level == "do_not_post" or conf < 0.4:
        return ("low", "VERIFY")
    # Likely-PB explicit angle → medium even if confidence higher
    if angle == "likely_pb":
        return ("medium", "LIKELY PB")
    if s2p_level == "needs_review" or conf < 0.7:
        # Map angle to a hedged label
        hedged = {
            "confirmed_official_pb": "LIKELY PB",
            "pb_improvement": "LIKELY PB",
            "first_sub_barrier": "LIKELY MILESTONE",
            "medal_gold": "GOLD",
            "medal_silver": "SILVER",
            "medal_bronze": "BRONZE",
            "qualifying_time": "POTENTIAL QUALIFIER",
            "biggest_drop": "BIG DROP",
        }
        return ("medium", hedged.get(angle, "STRONG SWIM"))
    # High confidence
    label_map = {
        "confirmed_official_pb": "NEW PB",
        "pb_improvement": "NEW PB",
        "likely_pb": "LIKELY PB",
        "first_sub_barrier": "FIRST UNDER",
        "medal_gold": "GOLD",
        "medal_silver": "SILVER",
        "medal_bronze": "BRONZE",
        "medal_and_pb_combo": "MEDAL + PB",
        "finalist": "FINALIST",
        "top_of_field": "TOP FIELD",
        "qualifying_time": "QUALIFIED",
        "heat_to_final_drop": "DROPPED INTO FINAL",
        "biggest_drop": "BIGGEST DROP",
        "fastest_since": "FASTEST SINCE",
        "multi_pb_weekend": "MULTI-PB WEEKEND",
        "return_to_form": "BACK TO FORM",
        "team_depth": "TEAM DEPTH",
        "relay_highlight": "RELAY",
        "weekend_in_numbers": "WEEKEND IN NUMBERS",
        "athlete_spotlight": "SPOTLIGHT",
        "recap_mention": "RECAP",
    }
    return ("high", label_map.get(angle, "STRONG SWIM"))


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------


def evaluate(
    content_item: dict,
    library_assets: Iterable[MediaAsset],
    *,
    profile_logo_present: bool = False,
    content_type_override: Optional[str] = None,
    exclude_athlete_photos: bool = False,
    run_id: Optional[str] = None,
    meet_window: Optional[tuple[str, str]] = None,
    exclude_asset_families: Optional[list[str]] = None,
) -> EvaluationResult:
    """Compute readiness + best-fit assets per role.

    ``run_id`` / ``meet_window`` scope the PHOTOS-6 candidate surface: when
    hero matching fails, photos stamped with this run's id (or uploaded inside
    the meet's ISO-timestamp window) are ranked and surfaced as ``candidates``
    for a human to pick from. ``exclude_asset_families`` threads recently-used
    dHashes through to the selector so one pack never repeats a near-frame.
    """
    item_id = (
        content_item.get("id")
        or content_item.get("content_item_id")
        or content_item.get("achievement", {}).get("swim_id")
        or content_item.get("swim_id")
        or ""
    )
    angle = (
        content_type_override
        or content_item.get("post_angle")
        or content_item.get("achievement", {}).get("post_angle")
        or content_item.get("card_type")
        or "recap_mention"
    )
    req_set = requirements_for(angle)

    # Confidence
    tier, label = _confidence_tier_and_label(content_item)

    # Pull athlete name from the item
    ach = content_item.get("achievement") or {}
    athlete_name = (
        content_item.get("swimmer_name")
        or ach.get("swimmer_name")
        or content_item.get("athlete_name")
        or ach.get("athlete_name")
    )
    athlete_id = (
        content_item.get("swimmer_id") or ach.get("swimmer_id") or content_item.get("athlete_id")
    )

    # Cache for asset list (used multiple times)
    library_list = list(library_assets)

    # W.2: the consent policy resolved onto the card by the pack builder.
    # When photo consent is withheld, athlete-linked photo roles must never
    # match an asset — the photo simply doesn't exist for this card.
    _consent = content_item.get("consent") or ach.get("consent") or {}
    _photo_ok = True
    if isinstance(_consent, dict) and _consent.get("level"):
        _photo_ok = bool(_consent.get("photo_ok", True))

    matched: dict[str, list[dict]] = {}
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for req in req_set.items:
        # Logo handled separately via brand profile
        if req.role == "logo":
            if profile_logo_present:
                matched["logo"] = [
                    {
                        "asset_id": "_brand_logo_",
                        "score": 1.0,
                        "reason_summary": "from brand profile",
                    }
                ]
            else:
                if req.required:
                    missing_required.append("logo")
                else:
                    missing_optional.append("logo")
            continue

        _athlete_role = req.role.startswith("hero") or req.role == "headshot"
        if _athlete_role and (not _photo_ok or exclude_athlete_photos):
            # Photo blocked by EITHER control: the W.2 per-athlete consent
            # level (photo consent withheld/unknown under an active regime)
            # or the tenant's Children's Code policy (no photos on under-18
            # content). The artefact renders text-led instead.
            if req.required:
                missing_required.append(req.role)
            else:
                missing_optional.append(req.role)
            continue

        scored = select_assets(
            library_list,
            role=req.role,
            athlete_name=athlete_name
            if req.role.startswith("hero") or req.role == "headshot"
            else None,
            athlete_id=athlete_id
            if req.role.startswith("hero") or req.role == "headshot"
            else None,
            preferred_orientation="portrait" if req.role.startswith("hero") else None,
            min_score=0.35,
            k=5,
            exclude_families=exclude_asset_families,
        )
        if scored:
            matched[req.role] = scored
        else:
            # Try fallback role if specified
            if req.fallback_role:
                fb = select_assets(
                    library_list,
                    role=req.fallback_role,
                    min_score=0.35,
                    k=3,
                    exclude_families=exclude_asset_families,
                )
                if fb:
                    matched[req.role] = fb
                    continue
            if req.required:
                missing_required.append(req.role)
            else:
                missing_optional.append(req.role)

    # Status decision
    candidates: list[dict] = []
    if tier == "low":
        status = SKIP_LOW_CONFIDENCE
        action = "Verify the underlying result before generating a graphic."
    elif missing_required:
        # Recap-style or weekend_in_numbers can be text-led
        if req_set.suggested_layout in ("weekend_numbers", "text_led_recap"):
            status = TEXT_LED_OK
            action = "Render as text-led graphic (no athlete photo required)."
        else:
            status = NEEDS_MEDIA
            roles_text = ", ".join(missing_required)
            _hero_missing = any(r.startswith("hero") for r in missing_required)
            _meet_total = 0
            if _hero_missing and _photo_ok and not exclude_athlete_photos:
                # PHOTOS-6: the volunteer may have already uploaded this
                # meet's photos — surface them to pick from instead of the
                # upload nag. Never auto-matched: an unconfirmed face on a
                # named card needs a human click.
                candidates, _meet_total = _meet_scoped_candidates(
                    library_list,
                    run_id=run_id,
                    meet_window=meet_window,
                    athlete_name=athlete_name,
                    athlete_id=athlete_id,
                    exclude_asset_families=exclude_asset_families,
                )
            if candidates:
                _n = _meet_total or len(candidates)
                action = (
                    f"Pick from {_n} photo{'s' if _n != 1 else ''} "
                    "uploaded for this meet."
                )
            elif "hero_athlete" in missing_required and athlete_name:
                action = f"Upload a real photo of {athlete_name} to render this post."
            elif "venue" in missing_required:
                action = "Search for a venue image, or upload one."
            else:
                action = f"Provide: {roles_text}."
    else:
        status = READY
        action = "Ready to render."

    explain = _build_explanation(angle, matched, missing_required, missing_optional, tier)

    return EvaluationResult(
        content_item_id=item_id,
        content_type=angle,
        status=status,
        suggested_layout=req_set.suggested_layout,
        matched=matched,
        missing_required=missing_required,
        missing_optional=missing_optional,
        recommended_action=action,
        confidence_tier=tier,
        confidence_label=label,
        explain=explain,
        candidates=candidates,
    )


# Person-photo types eligible for the meet-scoped candidate surface (quick
# uploads land as "other", so it stays in the pickable set).
_CANDIDATE_TYPES = ("athlete_action", "athlete_headshot", "team_photo", "other")


def _meet_scoped_candidates(
    library_list: list[MediaAsset],
    *,
    run_id: Optional[str],
    meet_window: Optional[tuple[str, str]],
    athlete_name: Optional[str],
    athlete_id: Optional[str],
    exclude_asset_families: Optional[list[str]],
    k: int = 5,
) -> tuple[list[dict], int]:
    """Rank this meet's uploaded photos as pick-from candidates.

    A photo belongs to the meet when its ``linked_meet_ids`` carries the run
    id (stamped at upload time — recorded, never guessed) or, when a
    ``meet_window`` of ISO timestamps is given, when it was uploaded inside
    that window. Returns ``(top_k_scored, total_in_scope)``; deterministic —
    same library in, same ranking out.
    """
    if not run_id and not meet_window:
        return [], 0
    scoped: list[MediaAsset] = []
    for a in library_list:
        if a.type not in _CANDIDATE_TYPES or not a.is_usable_for_post():
            continue
        in_scope = bool(run_id and run_id in (a.linked_meet_ids or []))
        if not in_scope and meet_window:
            in_scope = _uploaded_within(a.uploaded_at, meet_window)
        if in_scope:
            scoped.append(a)
    if not scoped:
        return [], 0
    ranked = select_assets(
        scoped,
        role="hero_athlete",
        athlete_name=athlete_name,
        athlete_id=athlete_id,
        preferred_orientation="portrait",
        min_score=0.0,
        k=k,
        exclude_families=exclude_asset_families,
    )
    # min_score=0.0 admits hard-zero (unusable) scores; scoped is already
    # usable-only, but keep the guard explicit for safety.
    ranked = [r for r in ranked if r["score"] > 0.0]
    return ranked, len(scoped)


def _uploaded_within(uploaded_at: str, window: tuple[str, str]) -> bool:
    """True iff ``uploaded_at`` parses and falls inside the ISO window."""
    try:
        from datetime import datetime, timezone

        def _parse(s: str) -> datetime:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        return _parse(window[0]) <= _parse(uploaded_at) <= _parse(window[1])
    except Exception:
        return False


def _build_explanation(
    angle: str, matched: dict, missing_req: list, missing_opt: list, tier: str
) -> str:
    parts = []
    if matched.get("hero_athlete"):
        a = matched["hero_athlete"][0]
        parts.append(f"Athlete photo found ({a.get('reason_summary', '')}).")
    if matched.get("venue"):
        parts.append("Venue image available.")
    if missing_req:
        parts.append(f"Missing required: {', '.join(missing_req)}.")
    if missing_opt:
        parts.append(f"Optional missing: {', '.join(missing_opt)}.")
    parts.append(f"Confidence tier: {tier}.")
    return " ".join(parts)


__all__ = [
    "evaluate",
    "EvaluationResult",
    "READY",
    "NEEDS_MEDIA",
    "SKIP_LOW_CONFIDENCE",
    "TEXT_LED_OK",
]
