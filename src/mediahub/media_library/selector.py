"""Score+pick the best media asset for a content item.

Scoring axes (all 0..1):
  - athlete_match: exact id match > name fuzzy match
  - type_fit: asset_type matches the requested role
  - permission: user_owned/approved > unknown > needs_approval
  - approval: approved > draft > rejected
  - orientation_fit: matches requested orientation
  - freshness: more recent uploads slightly preferred
  - quality: sharpness-dominant when ingest metrics exist (resolution stays the
    ceiling, clipping penalised); resolution-only for legacy assets
  - safety: respects safe_for_minors / do_not_use

Identity guard: when a subject athlete is given, an asset linked to a
DIFFERENT athlete is hard-demoted (×0.15) — a wrong face beside the subject's
name is a trust bug, not a partial fit — and unlinked assets always rank below
any subject-matched asset.

Returns assets sorted high → low with .score attached on a copy of the dict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .models import MediaAsset
from .tagger import dhash_hamming


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

# Roles whose subject is a person — the only roles where has_face is a signal.
_FACE_ROLES = ("headshot", "hero_athlete", "any_athlete")

# Hard demotion multiplier when the asset is linked to a different athlete
# than the card's subject (STILLS-9). Keeps the asset available as a last
# resort but below any honest candidate.
WRONG_ATHLETE_MULTIPLIER = 0.15

# dHash Hamming distance at or below which two frames count as the same
# burst family (near-duplicates from poolside burst shooting).
BURST_HAMMING_MAX = 6


def _identity_basis(
    asset: MediaAsset,
    athlete_name: Optional[str],
    athlete_id: Optional[str],
) -> Optional[str]:
    """How this asset relates to the requested subject athlete.

    Returns None when no subject was requested; otherwise one of
    "subject" (evidence the subject is in the photo), "other_athlete"
    (linked to someone else, subject absent) or "unlinked" (no athlete
    links at all — identity unverified).
    """
    if not (athlete_id or athlete_name):
        return None
    ids = asset.linked_athlete_ids or []
    names = asset.linked_athlete_names or []
    if athlete_id and athlete_id in ids:
        return "subject"
    if athlete_name:
        needle = athlete_name.lower()
        lnames = [n.lower() for n in names]
        if needle in lnames or any(needle in n or n in needle for n in lnames):
            return "subject"
        if needle in (asset.description_raw or "").lower():
            return "subject"
    return "other_athlete" if (ids or names) else "unlinked"


def _quality_meta(asset: MediaAsset) -> Optional[dict]:
    """The ingest-time quality dict, or None for legacy/unmeasured assets."""
    meta = asset.media_meta if isinstance(asset.media_meta, dict) else {}
    q = meta.get("quality")
    if isinstance(q, dict) and isinstance(q.get("sharpness"), (int, float)):
        return q
    return None


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

    # 6) Quality — resolution tier is the baseline (and the ceiling: a tiny
    # image can never top the axis); when ingest metrics exist, sharpness
    # dominates within that ceiling and clipping is penalised. Assets without
    # metrics keep the resolution-only score exactly (legacy behaviour).
    if asset.width >= 1500 or asset.height >= 1500:
        res_score = 1.0
    elif asset.width >= 800 or asset.height >= 800:
        res_score = 0.85
    elif asset.width >= 400 or asset.height >= 400:
        res_score = 0.6
    else:
        res_score = 0.3
    qmeta = _quality_meta(asset)
    if qmeta is None:
        quality = res_score
    else:
        sharp_norm = min(1.0, float(qmeta["sharpness"]) / 250.0)
        clip = float(qmeta.get("clip_highlights") or 0.0) + float(
            qmeta.get("clip_shadows") or 0.0
        )
        # Up to 10% combined clipped pixels is normal (specular water, dark
        # lanes); beyond that each extra point of clipping costs 1.5×.
        clip_penalty = min(0.3, max(0.0, clip - 0.10) * 1.5)
        quality = min(res_score, 0.25 * res_score + 0.75 * sharp_norm)
        quality = max(0.0, quality - clip_penalty)

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

    # 9) Face signal — only when a REAL signal was recorded (has_face True).
    # None (no signal yet) and False leave the blend untouched.
    if asset.has_face is True and role in _FACE_ROLES:
        score += 0.05 if role == "headshot" else 0.03

    # 10) Wrong-athlete guard (STILLS-9): linked to someone else entirely →
    # hard demotion. Unlinked assets keep their score (ranking handles them).
    if _identity_basis(asset, athlete_name, athlete_id) == "other_athlete":
        score *= WRONG_ATHLETE_MULTIPLIER

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
    exclude_families: Optional[Iterable[str]] = None,
) -> list[dict]:
    """Return up to k scored asset dicts sorted high → low.

    Each item is a dict: {asset_id, score, reason_summary, asset (dict)}.

    Burst dedupe: candidates whose ingest dHashes sit within
    ``BURST_HAMMING_MAX`` Hamming bits of each other are one burst family;
    only the sharpest member is returned. ``exclude_families`` takes dHash
    hex strings of recently-used photos (e.g. earlier cards in the same
    content pack) and drops any near-frame of them, so one pack never
    features two near-identical shots. Assets without a dHash (legacy,
    unmeasured) are untouched by both mechanisms.

    Ranking: when a subject athlete is requested, subject-matched assets
    always rank above unlinked ones, which rank above wrong-athlete ones —
    score orders within each band.
    """
    excluded = [h for h in (exclude_families or []) if h]
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
        qmeta = _quality_meta(a)
        dh = str((qmeta or {}).get("dhash") or "")
        if dh and any(dhash_hamming(dh, x) <= BURST_HAMMING_MAX for x in excluded):
            continue
        scored.append(
            {
                "asset_id": a.id,
                "score": round(s, 3),
                "reason_summary": _reason(a, role, athlete_name, athlete_id),
                "asset": a.to_dict(),
                "_dhash": dh,
                "_sharpness": float((qmeta or {}).get("sharpness") or 0.0),
                "_identity": _identity_basis(a, athlete_name, athlete_id),
            }
        )

    scored = _dedupe_burst_families(scored)

    _identity_rank = {"subject": 0, None: 1, "unlinked": 1, "other_athlete": 2}
    if athlete_id or athlete_name:
        scored.sort(key=lambda x: (_identity_rank.get(x["_identity"], 1), -x["score"]))
    else:
        scored.sort(key=lambda x: -x["score"])
    for entry in scored:
        entry.pop("_dhash", None)
        entry.pop("_sharpness", None)
        entry.pop("_identity", None)
    return scored[:k]


def _dedupe_burst_families(scored: list[dict]) -> list[dict]:
    """Keep only the sharpest member of each dHash burst family.

    Greedy pass in (sharpness, score, id) order: the best frame of a family
    is seen first and becomes its representative; every later frame within
    ``BURST_HAMMING_MAX`` bits of a representative is dropped. Entries with
    no dHash can't join a family and always survive. Output preserves the
    input (scoring) order of the survivors.
    """
    with_hash = [e for e in scored if e["_dhash"]]
    if len(with_hash) < 2:
        return scored
    reps: list[str] = []
    dropped: set[str] = set()
    for entry in sorted(
        with_hash, key=lambda e: (-e["_sharpness"], -e["score"], e["asset_id"])
    ):
        if any(dhash_hamming(entry["_dhash"], r) <= BURST_HAMMING_MAX for r in reps):
            dropped.add(entry["asset_id"])
        else:
            reps.append(entry["_dhash"])
    return [e for e in scored if e["asset_id"] not in dropped]


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
    basis = _identity_basis(asset, athlete_name, athlete_id)
    if basis == "other_athlete":
        parts.append("linked to a different athlete (demoted)")
    elif basis == "unlinked":
        parts.append("identity unverified (no athlete linked)")
    if asset.type in ROLE_TYPE_MAP.get(role, []):
        parts.append(f"type fits role ({asset.type})")
    if asset.permission_status in ("user_owned", "approved_by_club", "approved_public"):
        parts.append(f"permission {asset.permission_status}")
    if asset.approval_status == "approved":
        parts.append("approved")
    if not parts:
        parts.append("partial fit")
    return " · ".join(parts)


__all__ = [
    "score_asset",
    "select_assets",
    "ROLE_TYPE_MAP",
    "WRONG_ATHLETE_MULTIPLIER",
    "BURST_HAMMING_MAX",
]
