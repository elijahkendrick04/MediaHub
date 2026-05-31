"""Score+pick the best media asset for a content item.

Scoring axes (all 0..1):
  - athlete_match: exact id match > name fuzzy match
  - type_fit: asset_type matches the requested role
  - permission: user_owned/approved > unknown > needs_approval
  - approval: approved > draft > rejected
  - orientation_fit: matches requested orientation
  - freshness: more recent uploads slightly preferred
  - quality: resolution above 800px wide bonus
  - safety: respects safe_for_minors / do_not_use

Returns assets sorted high → low with .score attached on a copy of the dict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import MediaAsset


# Map content-item asset role → which MediaAsset.type values fit
ROLE_TYPE_MAP = {
    "hero_athlete": ["athlete_action", "athlete_headshot", "team_photo"],
    "headshot": ["athlete_headshot", "athlete_action"],
    "team": ["team_photo", "athlete_action"],
    "venue": ["venue_photo"],
    "logo": ["logo"],
    "sponsor": ["sponsor_logo"],
    "brand_pattern": ["brand_pattern"],
    "exemplar": ["exemplar_post"],
    "any_athlete": ["athlete_action", "athlete_headshot", "team_photo"],
}


def score_asset(
    asset: MediaAsset,
    *,
    role: str = "hero_athlete",
    athlete_name: Optional[str] = None,
    athlete_id: Optional[str] = None,
    preferred_orientation: Optional[str] = None,
) -> float:
    """Compute a 0..1 fitness score for using `asset` in the given role."""
    if not asset.is_usable_for_post():
        return 0.0

    # 1) Type fit
    fit_types = ROLE_TYPE_MAP.get(role, [])
    if asset.type in fit_types:
        type_fit = 1.0 if asset.type == fit_types[0] else 0.7
    else:
        type_fit = 0.1
    # team_photo is acceptable for athlete role only as a fallback
    if role == "headshot" and asset.type == "team_photo":
        type_fit = 0.4

    # 2) Athlete match
    am = 0.0
    if athlete_id and athlete_id in (asset.linked_athlete_ids or []):
        am = 1.0
    elif athlete_name:
        names = [n.lower() for n in (asset.linked_athlete_names or [])]
        needle = athlete_name.lower()
        if needle in names:
            am = 0.9
        elif any(needle in n or n in needle for n in names):
            am = 0.6
        elif needle in (asset.description_raw or "").lower():
            am = 0.5
    elif role in ("venue", "logo", "sponsor", "brand_pattern", "exemplar"):
        am = 0.7  # athlete identity not relevant
    elif role == "team":
        am = 0.6

    # 3) Permission status
    perm_score = {
        "user_owned": 1.0,
        "approved_by_club": 1.0,
        "approved_by_photographer": 1.0,
        "approved_public": 0.85,
        "internal_only": 0.5,
        "needs_approval": 0.4,
        "needs_parental_consent": 0.0,
        "do_not_use": 0.0,
        "unknown": 0.5,
    }.get(asset.permission_status, 0.4)

    # 4) Approval status
    appr_score = {
        "approved": 1.0,
        "draft": 0.6,
        "pending": 0.55,
        "rejected": 0.0,
    }.get(asset.approval_status, 0.5)

    # 5) Orientation fit
    if preferred_orientation and asset.orientation != "unknown":
        o_fit = 1.0 if asset.orientation == preferred_orientation else 0.55
    else:
        o_fit = 0.8

    # 6) Quality (resolution)
    if asset.width >= 1500 or asset.height >= 1500:
        quality = 1.0
    elif asset.width >= 800 or asset.height >= 800:
        quality = 0.85
    elif asset.width >= 400 or asset.height >= 400:
        quality = 0.6
    else:
        quality = 0.3

    # 7) Freshness (linear decay over 365 days)
    fresh = _freshness(asset.uploaded_at)

    # 8) Reuse penalty (used a lot recently → slight downweight to encourage variety)
    reuse_penalty = max(0.0, 1.0 - 0.04 * len(asset.used_in or []))

    # Weighted blend
    score = (
        0.30 * am
        + 0.18 * type_fit
        + 0.14 * perm_score
        + 0.10 * appr_score
        + 0.10 * quality
        + 0.08 * o_fit
        + 0.05 * fresh
        + 0.05 * reuse_penalty
    )
    return max(0.0, min(1.0, score))


def select_assets(
    assets: Iterable[MediaAsset],
    *,
    role: str = "hero_athlete",
    athlete_name: Optional[str] = None,
    athlete_id: Optional[str] = None,
    preferred_orientation: Optional[str] = None,
    min_score: float = 0.35,
    k: int = 5,
) -> list[dict]:
    """Return up to k scored asset dicts sorted high → low.

    Each item is a dict: {asset_id, score, reason_summary, asset (dict)}.
    """
    scored: list[dict] = []
    for a in assets:
        s = score_asset(
            a,
            role=role,
            athlete_name=athlete_name,
            athlete_id=athlete_id,
            preferred_orientation=preferred_orientation,
        )
        if s < min_score:
            continue
        scored.append(
            {
                "asset_id": a.id,
                "score": round(s, 3),
                "reason_summary": _reason(a, role, athlete_name, athlete_id),
                "asset": a.to_dict(),
            }
        )
    scored.sort(key=lambda x: -x["score"])
    return scored[:k]


def _freshness(uploaded_at: str) -> float:
    if not uploaded_at:
        return 0.5
    try:
        dt = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - dt).days)
        return max(0.0, 1.0 - (days / 365.0))
    except Exception:
        return 0.5


def _reason(
    asset: MediaAsset, role: str, athlete_name: Optional[str], athlete_id: Optional[str]
) -> str:
    parts: list[str] = []
    if athlete_id and athlete_id in (asset.linked_athlete_ids or []):
        parts.append("athlete-ID match")
    elif athlete_name and any(
        athlete_name.lower() in n.lower() for n in (asset.linked_athlete_names or [])
    ):
        parts.append(f"named match ({athlete_name})")
    if asset.type in ROLE_TYPE_MAP.get(role, []):
        parts.append(f"type fits role ({asset.type})")
    if asset.permission_status in ("user_owned", "approved_by_club", "approved_public"):
        parts.append(f"permission {asset.permission_status}")
    if asset.approval_status == "approved":
        parts.append("approved")
    if not parts:
        parts.append("partial fit")
    return " · ".join(parts)


__all__ = ["score_asset", "select_assets", "ROLE_TYPE_MAP"]
