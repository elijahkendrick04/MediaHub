"""
SwimmerHistory — wrapper around a per-swimmer PB snapshot.

Provides a clean interface for achievement detectors to query prior times
without knowing the internal structure of the snapshot or which provider
the data came from. The underlying source is learned at runtime by
``pb_discovery`` and surfaced via ``source_name()`` / ``source_url()``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional


def _cs_to_sec(cs: int) -> float:
    return cs / 100.0


def _sec_to_str(sec: float) -> str:
    """Format seconds as mm:ss.cc or ss.cc."""
    cs = round(sec * 100)
    mins = cs // 6000
    rem = cs - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _event_key(distance: int, stroke: str, course: str) -> str:
    """Normalised event key e.g. ``"100FRLC"`` (distance + stroke code + course)."""
    return f"{distance}{stroke}{course}"


class SwimmerHistory:
    """
    Wraps a per-swimmer PB snapshot (or None) and provides a clean query API.

    The underlying pb_snapshot is built by ``swim_content_v4.pb_bridge`` from a
    ``pb_discovery.PBDiscovery`` result. It exposes the following attributes:
        .pb_times: dict[str, list[dict]]  keyed by "<dist><stroke><course>" e.g. "100FRLC"
            Each entry: {"time_sec": float, "date_iso": str, "source_url": str, "retrieved_at": str}
        .fetch_ok: bool
        .error: str | None
        .tiref: str  (ASA id)
    """

    def __init__(self, swimmer_key: str, swimmer_name: str, pb_snapshot=None):
        self.swimmer_key = swimmer_key
        self.swimmer_name = swimmer_name
        self._snap = pb_snapshot  # SwimmerPBSnapshot | None

    @property
    def has_data(self) -> bool:
        if self._snap is None:
            return False
        return bool(getattr(self._snap, "fetch_ok", False))

    def _pb_times_for(self, distance: int, stroke: str, course: str) -> list[dict]:
        """Return list of time dicts for an event, sorted fastest first."""
        if not self.has_data:
            return []
        key = _event_key(distance, stroke, course)
        pb_times = getattr(self._snap, "pb_times", {}) or {}
        entries = pb_times.get(key, [])
        if not entries:
            # Also try the swimmingresults format which may differ
            # Try all keys that look like this event
            for k, v in pb_times.items():
                if k.upper() == key.upper():
                    entries = v
                    break
        return sorted(entries, key=lambda x: x.get("time_sec", 9999))

    def source_name(self) -> Optional[str]:
        """Return the source name/domain learned by pb_discovery, if any.

        Falls back to ``"PB lookup"`` so detectors always have a label without
        ever hardcoding a provider domain.
        """
        if self._snap is None:
            return None
        domain = getattr(self._snap, "source_domain", None)
        if domain:
            return str(domain)
        # Try to derive from URL if no explicit domain was set
        url = self.source_url()
        if url:
            try:
                from urllib.parse import urlparse
                host = (urlparse(url).hostname or "").lower()
                if host.startswith("www."):
                    host = host[4:]
                if host:
                    return host
            except Exception:
                pass
        return "PB lookup"

    def best_time_in_event(self, distance: int, stroke: str, course: str) -> Optional[float]:
        """Return best time in seconds, or None if no data."""
        entries = self._pb_times_for(distance, stroke, course)
        if not entries:
            return None
        return entries[0].get("time_sec")

    def best_time_str(self, distance: int, stroke: str, course: str) -> Optional[str]:
        t = self.best_time_in_event(distance, stroke, course)
        return _sec_to_str(t) if t is not None else None

    def times_in_event(self, distance: int, stroke: str, course: str) -> list[tuple[str, float]]:
        """Return list of (date_iso, time_sec) tuples, chronological order."""
        entries = self._pb_times_for(distance, stroke, course)
        result = []
        for e in entries:
            d = e.get("date_iso") or e.get("date") or ""
            t = e.get("time_sec")
            if t is not None:
                result.append((d, t))
        return result

    def last_swam_event(self, distance: int, stroke: str, course: str) -> Optional[str]:
        """Return ISO date string of the most recent swim, or None."""
        entries = self._pb_times_for(distance, stroke, course)
        if not entries:
            return None
        # Sort by date descending
        dated = [e for e in entries if e.get("date_iso") or e.get("date")]
        if not dated:
            return None
        dated.sort(key=lambda x: x.get("date_iso") or x.get("date") or "", reverse=True)
        return dated[0].get("date_iso") or dated[0].get("date")

    def all_pbs(self) -> dict[str, float]:
        """Return {event_key: best_time_sec} for all events in snapshot."""
        if not self.has_data:
            return {}
        pb_times = getattr(self._snap, "pb_times", {}) or {}
        result = {}
        for key, entries in pb_times.items():
            if entries:
                best = sorted(entries, key=lambda x: x.get("time_sec", 9999))[0]
                t = best.get("time_sec")
                if t is not None:
                    result[key] = t
        return result

    def source_url(self) -> Optional[str]:
        if self._snap is None:
            return None
        # Get URL from any entry
        pb_times = getattr(self._snap, "pb_times", {}) or {}
        for entries in pb_times.values():
            for e in entries:
                url = e.get("source_url")
                if url:
                    return url
        return None

    def retrieved_at(self) -> Optional[str]:
        if self._snap is None:
            return None
        pb_times = getattr(self._snap, "pb_times", {}) or {}
        for entries in pb_times.values():
            for e in entries:
                ra = e.get("retrieved_at")
                if ra:
                    return ra
        return None


def build_history_map(
    our_swims: list,
    pb_snapshots: dict,
    swimmers_by_key: dict,
) -> dict[str, SwimmerHistory]:
    """
    Build a dict[swimmer_key -> SwimmerHistory] from the pipeline's pb_snapshots.

    our_swims: list of V3 ParsedSwim objects (have .asa_id, .swimmer_key etc.)
    pb_snapshots: dict[asa_id -> SwimmerPBSnapshot]
    swimmers_by_key: dict[asa_id -> ParsedSwimmer] (V3 shim swimmers)
    """
    history_map: dict[str, SwimmerHistory] = {}
    seen_keys = set()

    for sw in our_swims:
        asa_id = getattr(sw, "asa_id", None) or ""
        # Use asa_id as the key since pb_snapshots is keyed by asa_id
        if asa_id in seen_keys:
            continue
        seen_keys.add(asa_id)

        swimmer = swimmers_by_key.get(asa_id)
        name = ""
        if swimmer:
            name = f"{getattr(swimmer, 'first_name', '')} {getattr(swimmer, 'last_name', '')}".strip()

        snap = pb_snapshots.get(asa_id)
        history_map[asa_id] = SwimmerHistory(
            swimmer_key=asa_id,
            swimmer_name=name,
            pb_snapshot=snap,
        )

    return history_map
