"""
pb_bridge.py — adapt `pb_discovery.PBDiscovery` results to the existing
`pb_snapshots` shape consumed by `swim_content_v5/history.py`.

`SwimmerHistory` expects a snapshot object with:

  * ``pb_times: dict[str, list[dict]]`` keyed by ``"<dist><stroke><course>"``
    (e.g. ``"100FRLC"``). Each entry is a dict with keys
    ``time_sec``, ``date_iso``, ``source_url``, ``retrieved_at``.
  * ``fetch_ok: bool``
  * ``error: Optional[str]``
  * ``tiref: str`` (legacy ASA id; we set the swimmer key here).

This module produces such a shape from a `PBDiscovery` so all downstream
consumers (history, detectors, recognition report) keep working without
caring where the data came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Iterable

from mediahub.pb_discovery import PBDiscovery, PBRow


_STROKE_TO_CODE: dict[str, str] = {
    "freestyle": "FR",
    "free": "FR",
    "backstroke": "BK",
    "back": "BK",
    "breaststroke": "BR",
    "breast": "BR",
    "butterfly": "FL",
    "fly": "FL",
    "individual medley": "IM",
    "medley": "IM",
    "im": "IM",
}

_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2})[.:](\d{1,2})\s*$")


def _stroke_to_code(stroke: str) -> str:
    s = (stroke or "").strip().lower()
    if s in _STROKE_TO_CODE:
        return _STROKE_TO_CODE[s]
    for key, code in _STROKE_TO_CODE.items():
        if key in s:
            return code
    return ""


def _time_to_seconds(time_str: str) -> Optional[float]:
    if not time_str:
        return None
    m = _TIME_RE.match(str(time_str).strip())
    if not m:
        return None
    mins = int(m.group(1)) if m.group(1) else 0
    secs = int(m.group(2))
    frac = m.group(3)
    if len(frac) == 1:
        frac_val = int(frac) / 10.0
    else:
        frac_val = int(frac[:2]) / 100.0
    return mins * 60 + secs + frac_val


def _event_key(distance: int, stroke_code: str, course: str) -> str:
    return f"{distance}{stroke_code}{course}"


def _split_event(event: str) -> tuple[Optional[int], str]:
    """
    Parse "100m Freestyle" → (100, "Freestyle"); "200 IM" → (200, "IM").
    Returns (None, "") if it can't.
    """
    if not event:
        return (None, "")
    m = re.match(r"\s*(\d{2,4})\s*m?\s+(.+)\s*$", event, re.IGNORECASE)
    if not m:
        return (None, "")
    return (int(m.group(1)), m.group(2).strip())


@dataclass
class BridgedSnapshot:
    """
    Shape consumed by `swim_content_v5/history.SwimmerHistory`.

    Fields mirror `swim_content.enrichment_swimmingresults.SwimmerPBSnapshot`
    closely enough that the history wrapper sees no difference.
    """
    tiref: str
    pb_times: dict[str, list[dict]] = field(default_factory=dict)
    fetch_ok: bool = True
    error: Optional[str] = None
    source_url: Optional[str] = None
    retrieved_at: Optional[str] = None
    source_domain: Optional[str] = None  # learned at runtime by pb_discovery


def discovery_to_snapshot(
    discovery: PBDiscovery,
    swimmer_key: str,
) -> BridgedSnapshot:
    """
    Convert a single PBDiscovery → BridgedSnapshot.

    Source URLs and fetched timestamps come from the chosen source —
    we do NOT hardcode any provider; if pb_discovery picked a different
    site this still works.
    """
    source_url = None
    retrieved_at = None
    source_domain = None
    if discovery.chosen_source is not None:
        source_url = discovery.chosen_source.url or None
        retrieved_at = discovery.chosen_source.fetched_at or None
        source_domain = (
            getattr(discovery.chosen_source, "domain", None)
            or getattr(discovery.chosen_source, "name", None)
            or None
        )

    snap = BridgedSnapshot(
        tiref=swimmer_key,
        fetch_ok=discovery.confidence > 0 and bool(discovery.pbs),
        error=None if discovery.pbs else "no PBs found",
        source_url=source_url,
        retrieved_at=retrieved_at,
        source_domain=source_domain,
    )

    for pb in discovery.pbs or []:
        distance, stroke_label = _split_event(pb.event)
        if distance is None:
            continue
        stroke_code = _stroke_to_code(stroke_label)
        if not stroke_code:
            continue
        course = (pb.course or "LC").upper()
        if course not in ("LC", "SC", "Y"):
            course = "LC"

        seconds = _time_to_seconds(pb.time_canonical)
        if seconds is None:
            continue

        key = _event_key(distance, stroke_code, course)
        snap.pb_times.setdefault(key, []).append({
            "time_sec": seconds,
            "date_iso": pb.date or "",
            "source_url": source_url or "",
            "retrieved_at": retrieved_at or "",
            "meet": pb.meet or "",
            "rank": pb.rank,
        })

    return snap


def build_pb_snapshots(
    discoveries: Iterable[tuple[str, PBDiscovery]],
) -> dict[str, BridgedSnapshot]:
    """
    Build the dict consumed by `pipeline_v4` / `swim_content_v5/report`.

    Each (swimmer_key, discovery) pair becomes one snapshot entry.
    """
    return {key: discovery_to_snapshot(disc, key) for key, disc in discoveries}
