"""
recognition_swim/achievements/official_pb.py

OfficialPBDetector: fires when PBDecision status == CONFIRMED_OFFICIAL_PB.

This detector checks for the CONFIRMED_OFFICIAL_PB status produced by the
PB-audit pipeline (sourced from whichever provider pb_discovery selected at
runtime) and creates a high-confidence achievement.
"""

from __future__ import annotations

from datetime import date, timedelta

from swim_content_v5.achievements.base import AchievementDetector
from swim_content_v5.schema import Achievement, AchievementEvidence


def _parse_iso_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _cs_to_str(cs) -> str:
    if cs is None:
        return "—"
    cs_int = round(cs)
    mins = cs_int // 6000
    rem = cs_int - mins * 6000
    secs = rem // 100
    frac = rem % 100
    if mins:
        return f"{mins}:{secs:02d}.{frac:02d}"
    return f"{secs}.{frac:02d}"


def _swim_id(swim, suffix: str = "") -> str:
    key = getattr(swim, "swimmer_key", "") or ""
    dist = getattr(swim, "distance", 0)
    stroke = getattr(swim, "stroke", "")
    course = getattr(swim, "course", "")
    rnd = getattr(swim, "round", "")
    return f"{key}:{dist}{stroke}{course}:{rnd}{suffix}"


def _event_label(swim) -> str:
    from swim_content_v5.report import _event_label as _el

    return _el(swim)


class OfficialPBDetector(AchievementDetector):
    """
    Fires when the PB audit decides CONFIRMED_OFFICIAL_PB.

    This is the strongest PB confirmation: the swimmer's listed PB from
    the source chosen by ``pb_discovery`` matches this swim by time
    (within 0.005s) and date (exact match or within 1 day). The source
    domain is read from the PB-decision evidence at runtime; no provider
    is hardcoded here.
    """

    name = "official_pb_confirmed"

    def detect(self, swim, ctx, history, all_results=None, extra=None) -> list[Achievement]:
        if getattr(swim, "dq", False) or getattr(swim, "finals_time_cs", None) is None:
            return []

        # Look for CONFIRMED_OFFICIAL_PB in the PB audit
        pb_decision = self._get_pb_decision(swim, history, ctx=ctx)
        if not pb_decision:
            return []

        if pb_decision.get("status") != "CONFIRMED_OFFICIAL_PB":
            return []

        time_str = _cs_to_str(swim.finals_time_cs)
        evt = _event_label(swim)
        swimmer_name = (extra or {}).get("swimmer_name", history.swimmer_name)

        reason = pb_decision.get("reason", "Time and date match the listed official PB.")
        source_url = ""
        source_label = ""
        for ev in pb_decision.get("evidence", []):
            if isinstance(ev, dict):
                if not source_url:
                    source_url = ev.get("url", "") or ev.get("source_url", "")
                if not source_label:
                    source_label = ev.get("source_name", "") or ev.get("name", "")
                if source_url and source_label:
                    break
        if not source_label:
            # Fall back to deriving from URL host, then to a neutral label
            if source_url:
                try:
                    from urllib.parse import urlparse

                    host = (urlparse(source_url).hostname or "").lower()
                    if host.startswith("www."):
                        host = host[4:]
                    source_label = host or "PB lookup"
                except Exception:
                    source_label = "PB lookup"
            else:
                source_label = "PB lookup"

        evidence = [
            AchievementEvidence(
                source_type="results_file",
                source_name="Meet results",
                statement=f"Swam {time_str} in {evt}",
                confidence="high",
            ),
        ]
        if source_url:
            evidence.append(
                AchievementEvidence(
                    source_type="live_research",
                    source_name=source_label,
                    statement=reason,
                    source_url=source_url,
                    confidence="high",
                )
            )

        return [
            Achievement(
                type="official_pb_confirmed",
                swim_id=_swim_id(swim, ":official_pb"),
                swimmer_id=swim.swimmer_key,
                swimmer_name=swimmer_name,
                event=evt,
                headline=f"{swimmer_name} — official PB confirmed: {time_str} in {evt}",
                angle_hint=f"Official PB confirmed by {source_label}: {time_str} is their listed all-time PB for {evt}.",
                confidence=0.98,
                confidence_label="high",
                evidence=evidence,
                raw_facts={
                    "time_str": time_str,
                    "time_cs": swim.finals_time_cs,
                    "pb_decision_status": "CONFIRMED_OFFICIAL_PB",
                    "reason": reason,
                },
                uncertainty_notes=[],
                detector_name=self.name,
            )
        ]

    def _get_pb_decision(self, swim, history, ctx=None) -> dict | None:
        """Extract the PBDecision dict from the history object."""
        # history may have a pb_decision attribute set by the pipeline
        pb_decision = getattr(history, "pb_decision", None)
        if pb_decision is None:
            # Production path: derive the decision from the swimmer's PB
            # snapshot (pb_discovery via pb_bridge) — V7.3 Rule 0.
            return self._derive_decision(swim, history, ctx)
        if hasattr(pb_decision, "status"):
            # It's a PBDecision dataclass — convert to dict-like access
            return {
                "status": pb_decision.status,
                "reason": getattr(pb_decision, "reason", ""),
                "evidence": getattr(pb_decision, "evidence", []),
            }
        if isinstance(pb_decision, dict):
            return pb_decision
        return None

    def _derive_decision(self, swim, history, ctx) -> dict | None:
        """V7.3 Rule 0 over the discovery-bridged snapshot.

        The swimmer's listed all-time PB matches this swim by time (within
        0.005s) and date (within the meet window ±1 day) — i.e. the source
        the PB lookup chose already records THIS swim as the official PB.
        Deterministic; returns None unless every condition holds. The plain
        PBConfirmedDetector cannot fire in this scenario (the swim equals,
        not beats, the listed best), so without this rule a genuine PB
        produces no achievement at all.
        """
        if not getattr(history, "has_data", False):
            return None
        meet_start = _parse_iso_date(getattr(ctx, "start_date", None))
        meet_end = _parse_iso_date(getattr(ctx, "end_date", None)) or meet_start
        if meet_start is None:
            return None
        try:
            entries = history._pb_times_for(swim.distance, swim.stroke, swim.course)
        except Exception:
            return None
        current_sec = swim.finals_time_cs / 100.0
        for entry in entries or []:
            time_sec = entry.get("time_sec")
            if time_sec is None or abs(float(time_sec) - current_sec) > 0.005:
                continue
            entry_date = _parse_iso_date(entry.get("date_iso") or entry.get("date"))
            if entry_date is None:
                continue
            window_start = meet_start - timedelta(days=1)
            window_end = meet_end + timedelta(days=1)
            if not (window_start <= entry_date <= window_end):
                continue
            source_url = entry.get("source_url") or ""
            source_name = ""
            try:
                source_name = history.source_name() or ""
            except Exception:
                pass
            return {
                "status": "CONFIRMED_OFFICIAL_PB",
                "reason": (
                    "Time and date match the swimmer's listed all-time PB — "
                    "this swim is their official PB."
                ),
                "evidence": [{"source_url": source_url, "source_name": source_name}],
            }
        return None

    def _no_fire_reason(self, swim, ctx, history, all_results=None, extra=None) -> str:
        pb_decision = self._get_pb_decision(swim, history, ctx=ctx)
        if pb_decision is None:
            return "no PB decision data on history object"
        status = (
            pb_decision.get("status", "")
            if isinstance(pb_decision, dict)
            else getattr(pb_decision, "status", "")
        )
        if status != "CONFIRMED_OFFICIAL_PB":
            return f"PB decision is {status}, not CONFIRMED_OFFICIAL_PB"
        return "did not fire"
