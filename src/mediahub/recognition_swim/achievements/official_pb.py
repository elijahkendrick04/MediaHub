"""
recognition_swim/achievements/official_pb.py

OfficialPBDetector: fires when PBDecision status == CONFIRMED_OFFICIAL_PB.

This detector checks for the CONFIRMED_OFFICIAL_PB status produced by the
PB-audit pipeline (sourced from whichever provider pb_discovery selected at
runtime) and creates a high-confidence achievement.
"""

from __future__ import annotations

import re
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


# Ranking sites publish PB dates in whatever locale format the source page uses,
# and the interpreter extraction path carries no date at all. A strict ISO gate
# (``date.fromisoformat``) therefore rejects the dates real snapshots actually
# hold, which is what made ``official_pb_confirmed`` effectively unfireable in
# production (F18). ``_parse_pb_date`` normalises the common forms so a genuinely
# confirmed official PB can fire; it stays deterministic and LLM-free.
_YEAR_FIRST_RE = re.compile(r"^\s*(\d{4})[./](\d{1,2})[./](\d{1,2})")
_DAY_FIRST_RE = re.compile(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)")


def _parse_pb_date(value) -> date | None:
    """Parse a listed-PB entry date, tolerating the formats real sources emit.

    Accepts ISO ``YYYY-MM-DD`` (also the leading date of an ISO datetime), the
    year-first slash/dot forms ``YYYY/MM/DD`` / ``YYYY.MM.DD``, and the day-first
    forms ``DD/MM/YYYY`` / ``DD.MM.YYYY`` / ``DD-MM-YYYY`` — including the
    two-digit-year variants (``DD/MM/YY``) the discovery scraper emits
    (``pb_discovery/parse_pbs.py`` captures ``\\d{2,4}`` years) — used by the
    European / continental swimming-results sites in scope. A two-digit year is
    pivoted on 70 (PB dates are recent; never before 1970). Genuinely ambiguous
    ``xx/xx/yyyy`` values are read day-first — the convention on those sources —
    a deterministic, documented choice. Returns ``None`` for empty / ``None`` /
    unrecognised input.

    Crucially, the caller distinguishes a *genuinely absent* date (empty field →
    may still confirm on the fastest-time match) from a *present but unparseable*
    one (a date WAS recorded but cannot be verified in-window → never a
    confirmation), so a ``None`` returned here is never read as "confirmed
    in-window".
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    iso = _parse_iso_date(s)
    if iso is not None:
        return iso
    m = _YEAR_FIRST_RE.match(s)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _DAY_FIRST_RE.match(s)
        if not m:
            return None
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            # Two-digit year → pivot on 70. Swim PB dates are recent, so a value
            # under 70 is this century (24 → 2024), 70–99 the previous (98 → 1998).
            year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day)
    except ValueError:
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

        This swim IS the swimmer's official PB when it equals their *fastest*
        listed time for the event (within 0.005s) — i.e. the source the PB
        lookup chose records this time as their all-time best. When the source
        also dates that best time inside the meet window (±1 day) the source has
        already recorded THIS swim; that is the strongest confirmation. When the
        source records NO date at all — the interpreter extraction path carries
        none (F18) — the exact match to the *fastest* listed time still confirms
        "this is their listed all-time PB", so we fire with an honest reason. A
        listed best whose date is *present* but either outside the meet window or
        unparseable is a different / unverifiable swim that merely equals this
        time, so it is never a confirmation (a recorded-but-unreadable date must
        never be mistaken for "no date").

        Deterministic; returns None unless the swim equals the listed best. The
        plain PBConfirmedDetector cannot fire in this scenario (the swim equals,
        not beats, the listed best), so without this rule a genuine PB produces
        no achievement at all.
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

        # The listed all-time PB is the *fastest* recorded time for the event.
        # This swim only *is* that PB if it matches the fastest listed time; a
        # slower progression entry that happens to equal this swim must never be
        # announced as the all-time PB.
        timed = [e for e in (entries or []) if e.get("time_sec") is not None]
        if not timed:
            return None
        best_sec = min(float(e["time_sec"]) for e in timed)
        if abs(best_sec - current_sec) > 0.005:
            return None

        window_start = meet_start - timedelta(days=1)
        window_end = meet_end + timedelta(days=1)

        # Among the fastest-tier entries (those equal to the listed best), prefer
        # a date-confirmed match; otherwise fall back to a date-less match. An
        # entry whose date is known but outside the meet window is excluded.
        date_confirmed = None
        dateless = None
        for entry in timed:
            if abs(float(entry["time_sec"]) - best_sec) > 0.005:
                continue
            raw = entry.get("date_iso") or entry.get("date")
            raw_str = str(raw).strip() if raw is not None else ""
            if raw_str:
                # A date WAS recorded. Only an in-window date confirms this swim;
                # a known out-of-window date is an older swim that merely equals
                # this time, and a date we cannot parse is unverifiable — neither
                # may fire, and neither is ever treated as "dateless".
                entry_date = _parse_pb_date(raw_str)
                if entry_date is not None and window_start <= entry_date <= window_end:
                    date_confirmed = entry
                    break
                continue
            # Genuinely no date recorded (the interpreter path carries none). The
            # exact match to the fastest listed time still confirms the official PB.
            if dateless is None:
                dateless = entry

        chosen = date_confirmed or dateless
        if chosen is None:
            return None

        source_url = chosen.get("source_url") or ""
        source_name = ""
        try:
            source_name = history.source_name() or ""
        except Exception:
            pass
        if date_confirmed is not None:
            reason = (
                "Time and date match the swimmer's listed all-time PB — "
                "this swim is their official PB."
            )
        else:
            reason = (
                "Time matches the swimmer's listed all-time PB for the event — "
                "this swim is their official PB (the source published no "
                "cross-checkable date)."
            )
        return {
            "status": "CONFIRMED_OFFICIAL_PB",
            "reason": reason,
            "evidence": [{"source_url": source_url, "source_name": source_name}],
        }

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
