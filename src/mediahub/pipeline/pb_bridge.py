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

from mediahub.pb_discovery import PBDiscovery


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

# A canonical swim time is colon-separated clock fields (``[HH:]MM:SS``) with an
# optional ``.`` decimal fraction on the final (seconds) field only. ``:`` is a
# field separator, never a decimal point. Validating one field each means a
# dotted date (``12.03.2024``) or a stray integer (``99``) can never masquerade
# as a time.
_CLOCK_FIELD_RE = re.compile(r"^\d+$")             # hours / minutes — whole numbers
_SECONDS_FIELD_RE = re.compile(r"^\d+(?:\.\d+)?$")  # seconds, optional decimal fraction


def _stroke_to_code(stroke: str) -> str:
    s = (stroke or "").strip().lower()
    if s in _STROKE_TO_CODE:
        return _STROKE_TO_CODE[s]
    for key, code in _STROKE_TO_CODE.items():
        if key in s:
            return code
    return ""


def _time_to_seconds(time_str: str) -> Optional[float]:
    """Convert a canonical swim-time string to a float number of seconds.

    Accepts every shape ``parse_pbs`` can emit as ``time_canonical`` — the
    heuristic ``_TIME_RE`` explicitly produces ``HH:MM:SS.ss`` (per its own
    comment) and the interpreter / cache paths can carry a 3-digit fraction:

      * ``SS.ss`` / ``SSS.ss``           → ``"59.87"`` → 59.87, ``"159.87"`` → 159.87
      * ``SS.sss``                       → ``"58.345"`` → 58.345
      * ``M:SS.ss`` / ``MM:SS.ss``       → ``"1:02.34"`` → 62.34, ``"15:25.10"`` → 925.10
      * ``H:MM:SS.ss`` / ``HH:MM:SS.ss`` → ``"2:01:02.34"`` → 7262.34

    ``:`` separates hours / minutes / seconds and is **never** a decimal point,
    so ``"1:02:34"`` is 1h 02m 34s = 3754.0s (not 62.34s). The fraction is
    introduced only by ``.``. Returns ``None`` for non-times (``""``, ``None``,
    ``"DNF"``, bare integers like ``"99"``, dotted dates like ``"12.03.2024"``)
    so an unparseable row is dropped rather than poisoning a baseline.
    """
    if not time_str:
        return None
    s = str(time_str).strip()
    if not s:
        return None

    parts = s.split(":")
    if len(parts) > 3:  # more fields than H:MM:SS — not a clock time
        return None

    seconds_field = parts[-1]
    clock_fields = parts[:-1]  # hours and/or minutes, most-significant first

    # A bare number (no ``:``) must carry a decimal fraction, so a stray integer
    # (rank, bib, place) never becomes a spurious 0-fraction baseline.
    if not clock_fields and "." not in seconds_field:
        return None
    if not _SECONDS_FIELD_RE.match(seconds_field):
        return None
    if any(not _CLOCK_FIELD_RE.match(f) for f in clock_fields):
        return None

    total = float(seconds_field)
    for position, field_value in enumerate(reversed(clock_fields), start=1):
        total += int(field_value) * (60 ** position)
    return total


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

    ``fetch_ok`` means the lookup *completed* — we reached the web and either
    found a baseline or established there was nothing verifiable to find.
    ``no_history`` separates "completed, nothing found" from a transport
    failure so the audit never reports a swimmer without an online profile
    as a failed fetch. ``from_cache`` carries pb_discovery's cache_hit flag
    through to the run audit's cache-hit/miss counters.
    """

    tiref: str
    pb_times: dict[str, list[dict]] = field(default_factory=dict)
    fetch_ok: bool = True
    error: Optional[str] = None
    no_history: bool = False
    from_cache: bool = False
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

    # Classify the lookup outcome honestly. "Found nothing" is only a
    # *failure* when we never actually saw the web (no search candidates,
    # or every candidate page failed to fetch); a swimmer with no online
    # history is a completed lookup, not a failed one.
    sources = discovery.sources_tried or []
    fetched_any = any(getattr(s, "fetch_success", True) for s in sources)
    if discovery.pbs:
        fetch_ok, error, no_history = True, None, False
    elif not sources:
        fetch_ok, error, no_history = False, "web search returned no candidate pages", False
    elif not fetched_any:
        fetch_ok, error, no_history = False, "could not fetch any candidate page", False
    else:
        fetch_ok, error, no_history = True, None, True

    snap = BridgedSnapshot(
        tiref=swimmer_key,
        fetch_ok=fetch_ok,
        error=error,
        no_history=no_history,
        from_cache=bool(getattr(discovery, "cache_hit", False)),
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
        snap.pb_times.setdefault(key, []).append(
            {
                "time_sec": seconds,
                "date_iso": pb.date or "",
                "source_url": source_url or "",
                "retrieved_at": retrieved_at or "",
                "meet": pb.meet or "",
                "rank": pb.rank,
            }
        )

    return snap


def build_pb_snapshots(
    discoveries: Iterable[tuple[str, PBDiscovery]],
) -> dict[str, BridgedSnapshot]:
    """
    Build the dict consumed by `pipeline_v4` / `swim_content_v5/report`.

    Each (swimmer_key, discovery) pair becomes one snapshot entry.
    """
    return {key: discovery_to_snapshot(disc, key) for key, disc in discoveries}
