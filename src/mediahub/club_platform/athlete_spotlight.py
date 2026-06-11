"""
AthleteSpotlightContentType — filter + re-rank pass over existing V5
recognition data for a single swimmer.

This is NOT a new pipeline. It takes a run's recognition_report (already
computed), filters to the named swimmer, re-ranks within that scope, and
returns a "spotlight pack" — the same data shape as the meet recap but
scoped to one athlete.

Entry points:
  build_spotlight_pack(run_data, swimmer_key) -> dict | None
"""

from __future__ import annotations

from typing import Optional

from .content_types import ContentType, ContentTypeMeta, REGISTRY


class AthleteSpotlightContentType:
    meta: ContentTypeMeta = REGISTRY[ContentType.ATHLETE_SPOTLIGHT]
    type: ContentType = ContentType.ATHLETE_SPOTLIGHT

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return cls.meta

    @classmethod
    def is_ready(cls) -> bool:
        return cls.meta.is_implemented

    def __repr__(self) -> str:
        return f"<AthleteSpotlightContentType ready={self.is_ready()}>"


def build_spotlight_pack(
    run_data: dict,
    swimmer_key: str,
) -> Optional[dict]:
    """
    Filter the run's recognition_report to one swimmer and re-rank.

    Parameters
    ----------
    run_data : dict
        The full persisted run dict loaded from runs_v4/<run_id>.json.
    swimmer_key : str
        The swimmer_key (asa_id or canonical key) to spotlight.

    Returns
    -------
    dict or None
        A spotlight pack dict with the following keys:
          - swimmer_key  : str
          - swimmer_name : str
          - run_id       : str
          - meet_name    : str
          - ranked_achievements : list[dict]  (re-ranked 1…N)
          - n_achievements : int
          - n_elite, n_strong, n_story : int
          - meet_context : dict
        Returns None if run_data is missing or no achievements found for
        the swimmer.
    """
    if not run_data:
        return None

    rr = run_data.get("recognition_report") or {}
    if not rr:
        return None

    run_id = run_data.get("run_id", "")
    meet = run_data.get("meet") or {}
    meet_name = rr.get("meet_name") or meet.get("name", "(unknown)")
    meet_context = rr.get("meet_context") or {}

    ranked_achs = rr.get("ranked_achievements") or []

    # Filter to the target swimmer
    swimmer_achs = [
        ra
        for ra in ranked_achs
        if ra.get("achievement", {}).get("swimmer_id", "") == swimmer_key
        or ra.get("achievement", {}).get("swimmer_name", "") == swimmer_key
    ]

    # If no match by id, try partial name match (for URL-safe keys)
    if not swimmer_achs:
        swimmer_achs = [
            ra
            for ra in ranked_achs
            if _normalise_key(ra.get("achievement", {}).get("swimmer_id", ""))
            == _normalise_key(swimmer_key)
            or _normalise_key(ra.get("achievement", {}).get("swimmer_name", ""))
            == _normalise_key(swimmer_key)
        ]

    if not swimmer_achs:
        return None

    # Re-rank within the spotlight scope (just re-number; priority already set)
    swimmer_achs_sorted = sorted(
        swimmer_achs,
        key=lambda ra: -ra.get("priority", 0.0),
    )
    for i, ra in enumerate(swimmer_achs_sorted):
        ra = dict(ra)  # shallow copy so we don't mutate the original
        ra["rank"] = i + 1
        swimmer_achs_sorted[i] = ra

    # Resolve swimmer display name from first achievement
    swimmer_name = ""
    if swimmer_achs_sorted:
        swimmer_name = (
            swimmer_achs_sorted[0].get("achievement", {}).get("swimmer_name", swimmer_key)
        )

    # Band counts
    from swim_content_v5.schema import QualityBand

    band_labels = {
        QualityBand.ELITE.value: "elite",
        QualityBand.STRONG.value: "strong",
        QualityBand.STORY.value: "story",
    }
    n_elite = sum(1 for ra in swimmer_achs_sorted if ra.get("quality_band") == "elite")
    n_strong = sum(1 for ra in swimmer_achs_sorted if ra.get("quality_band") == "strong")
    n_story = sum(1 for ra in swimmer_achs_sorted if ra.get("quality_band") == "story")

    return {
        "swimmer_key": swimmer_key,
        "swimmer_name": swimmer_name,
        "run_id": run_id,
        "meet_name": meet_name,
        "ranked_achievements": swimmer_achs_sorted,
        "n_achievements": len(swimmer_achs_sorted),
        "n_elite": n_elite,
        "n_strong": n_strong,
        "n_story": n_story,
        "meet_context": meet_context,
    }


def _normalise_key(s: str) -> str:
    """Lowercase, strip, replace spaces with underscores for fuzzy matching."""
    return s.strip().lower().replace(" ", "_")


def list_swimmers_in_run(run_data: dict) -> list[dict]:
    """
    Return list of dicts: [{swimmer_key, swimmer_name, n_achievements}]
    for every swimmer that appears in the recognition_report of run_data.
    Sorted by n_achievements descending.
    """
    if not run_data:
        return []
    rr = run_data.get("recognition_report") or {}
    ranked_achs = rr.get("ranked_achievements") or []

    by_swimmer: dict[str, dict] = {}
    for ra in ranked_achs:
        a = ra.get("achievement") or {}
        sk = a.get("swimmer_id", "") or a.get("swimmer_name", "")
        sn = a.get("swimmer_name", sk)
        if not sk:
            continue
        if sk not in by_swimmer:
            by_swimmer[sk] = {"swimmer_key": sk, "swimmer_name": sn, "n_achievements": 0}
        by_swimmer[sk]["n_achievements"] += 1

    return sorted(by_swimmer.values(), key=lambda x: -x["n_achievements"])
