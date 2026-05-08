"""
Achievement Detection Engine — the defensible IP layer.

Inputs:  the new meet's RaceResult rows + canonical PB store + records + QTs
Outputs: a list of Achievement objects, each with:
            - type, evidence, explanation, confidence, content_worthiness

Key principles (from BLUEPRINT.md §5):
  * never compare across courses (LC vs SC are separate worlds)
  * confirmed_pb only when the PB came from a TRUSTED source
  * everything is explainable; no opaque scoring
  * meet-wide ranking signals (biggest improvement) need the full meet in scope
"""

from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any
from .events import cs_to_str, event_human


# Round → can-be-medal? Only finals award medals.
MEDAL_ROUNDS = {"final"}

# Common psychological barriers per (distance, stroke). Hitting these for the
# first time is a content-worthy moment.
BARRIERS_CS = {
    # 50m
    ("50", "FR"): [3000, 2800, 2700, 2600, 2500, 2400, 2300, 2200],   # 30, 28, 27, ... 22
    ("50", "BK"): [3500, 3300, 3100, 2900, 2700, 2600, 2500],
    ("50", "BR"): [4000, 3800, 3600, 3400, 3200, 3000, 2900],
    ("50", "FL"): [3200, 3000, 2800, 2700, 2600, 2500, 2400],
    # 100m
    ("100", "FR"): [7000, 6500, 6000, 5800, 5600, 5400, 5200, 5000],  # 1:10, 1:05, 1:00, 58, ...
    ("100", "BK"): [7500, 7000, 6500, 6200, 6000, 5800],
    ("100", "BR"): [8500, 8000, 7500, 7200, 7000, 6800],
    ("100", "FL"): [7500, 7000, 6500, 6200, 6000, 5800],
    ("100", "IM"): [8000, 7500, 7000, 6500, 6200, 6000],
    # 200m
    ("200", "FR"): [15000, 14000, 13000, 12500, 12000, 11800, 11500],
    ("200", "BK"): [16000, 15000, 14000, 13500, 13000, 12500],
    ("200", "BR"): [18000, 17000, 16000, 15000, 14500, 14000],
    ("200", "FL"): [16000, 15000, 14000, 13500, 13000, 12500],
    ("200", "IM"): [16500, 15500, 14500, 14000, 13500, 13000],
    # 400m
    ("400", "FR"): [32000, 30000, 28000, 27000, 26000, 25000, 24500],
    ("400", "IM"): [35000, 32500, 30000, 29000, 28000, 27000],
    # 800m
    ("800", "FR"): [70000, 65000, 60000, 57000, 55000, 53000],
    # 1500m
    ("1500", "FR"): [130000, 120000, 110000, 105000, 100000, 95000],
}


@dataclass
class Achievement:
    type: str
    swimmer_id: int | None
    swimmer_name: str
    race_id: int | None
    event_code: str
    explanation: str
    confidence: float
    content_worthiness: int
    suggested_formats: list[str]
    evidence: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_pb(conn, swimmer_id, event_code, course):
    row = conn.execute(
        "SELECT best_time_cs, best_date, source, confidence FROM personal_best "
        "WHERE swimmer_id=? AND event_code=? AND course=?",
        (swimmer_id, event_code, course),
    ).fetchone()
    return row  # tuple or None


def _set_pb(conn, swimmer_id, event_code, course, time_cs, date, source, confidence):
    conn.execute(
        "INSERT OR REPLACE INTO personal_best "
        "(swimmer_id, event_code, course, best_time_cs, best_date, source, confidence) "
        "VALUES (?,?,?,?,?,?,?)",
        (swimmer_id, event_code, course, time_cs, date, source, confidence),
    )


def _suggest_formats(score: int) -> list[str]:
    if score >= 85:
        return ["feed", "story", "reel_script"]
    if score >= 70:
        return ["feed", "story"]
    if score >= 55:
        return ["story"]
    if score >= 40:
        return ["recap_only"]
    return []


def _decompose_event(event_code: str):
    g, d, s, c = event_code.split("_")
    return g, d, s, c


# ------------------------------------------------------------------
# Detection passes
# ------------------------------------------------------------------

def detect_achievements(conn: sqlite3.Connection, meet_id: int,
                        meet_date: str | None) -> list[Achievement]:
    """Run all detection passes for a single meet. Returns a sorted list."""
    rows = conn.execute(
        "SELECT r.id, r.swimmer_id, s.display_name, r.event_code, r.round, "
        "r.place, r.time_cs, r.entry_time_cs, r.dq, m.course, s.club_id "
        "FROM race_result r JOIN swimmer s ON s.id=r.swimmer_id "
        "JOIN meet m ON m.id=r.meet_id "
        "WHERE r.meet_id=? AND r.dq=0",
        (meet_id,),
    ).fetchall()

    achievements: list[Achievement] = []
    improvement_pool: list[tuple[float, dict]] = []  # (improvement_seconds, data)

    for (race_id, swimmer_id, name, event_code, rnd, place,
         time_cs, entry_cs, _dq, course, club_id) in rows:

        g, d, stroke, course_from_event = _decompose_event(event_code)
        # PB analysis
        pb = _get_pb(conn, swimmer_id, event_code, course)
        prev_best_cs = pb[0] if pb else None
        prev_source = pb[2] if pb else None
        margin_cs = (prev_best_cs - time_cs) if prev_best_cs else None

        is_pb = prev_best_cs is not None and time_cs < prev_best_cs
        pb_type = None
        confidence = 0.0
        if is_pb:
            if prev_source in ("swim_england", "imported", "meet"):
                pb_type = "CONFIRMED_PB"
                confidence = 0.95
            else:
                pb_type = "LIKELY_PB"
                confidence = 0.7
        elif prev_best_cs is None and entry_cs and time_cs < entry_cs:
            # No history at all but beat entry time → cautious likely-PB
            pb_type = "LIKELY_PB"
            margin_cs = entry_cs - time_cs
            confidence = 0.55

        if pb_type:
            margin_str = cs_to_str(abs(margin_cs)) if margin_cs is not None else "?"
            base_score = 50
            if margin_cs:
                base_score += min(25, int(margin_cs / 100 * 5))  # +5 per second up to +25
            if pb_type == "CONFIRMED_PB":
                base_score += 5
            achievements.append(Achievement(
                type=pb_type,
                swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                event_code=event_code,
                explanation=(
                    f"{'PB' if pb_type=='CONFIRMED_PB' else 'Likely PB'} "
                    f"by {margin_str} in the {event_human(event_code)} "
                    f"({cs_to_str(time_cs)}, previous best {cs_to_str(prev_best_cs) if prev_best_cs else cs_to_str(entry_cs)+' (entry)'})."
                ),
                confidence=confidence,
                content_worthiness=base_score,
                suggested_formats=_suggest_formats(base_score),
                evidence={
                    "time_cs": time_cs, "previous_best_cs": prev_best_cs,
                    "entry_time_cs": entry_cs, "margin_cs": margin_cs,
                    "previous_source": prev_source,
                },
            ))
            # Only confirmed PBs (real history) feed the improvement pool.
            # Otherwise we'd over-celebrate first-meet swimmers whose 'baseline' is just an entry guess.
            if margin_cs and margin_cs > 0 and pb_type == "CONFIRMED_PB":
                improvement_pool.append((margin_cs, {
                    "name": name, "swimmer_id": swimmer_id, "race_id": race_id,
                    "event_code": event_code, "time_cs": time_cs,
                    "previous_best_cs": prev_best_cs or entry_cs,
                }))

        # Update canonical PB store IF this is a real improvement.
        # We trust the meet itself; flag confidence accordingly.
        if is_pb or prev_best_cs is None:
            new_conf = 0.95 if pb and prev_source == "swim_england" else 0.85
            _set_pb(conn, swimmer_id, event_code, course, time_cs,
                    meet_date, "meet", new_conf)

        # Medal
        if rnd in MEDAL_ROUNDS and place in (1, 2, 3):
            medal_name = {1: "Gold", 2: "Silver", 3: "Bronze"}[place]
            score = {1: 70, 2: 55, 3: 50}[place]
            achievements.append(Achievement(
                type=f"MEDAL_{medal_name.upper()}",
                swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                event_code=event_code,
                explanation=f"{medal_name} medal in {event_human(event_code)} "
                            f"({cs_to_str(time_cs)}).",
                confidence=1.0,
                content_worthiness=score,
                suggested_formats=_suggest_formats(score),
                evidence={"place": place, "round": rnd, "time_cs": time_cs},
            ))

        # Final qualification
        if rnd in {"final", "semi"}:
            achievements.append(Achievement(
                type="FINAL_QUALIFICATION",
                swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                event_code=event_code,
                explanation=f"Made the {rnd} of the {event_human(event_code)}.",
                confidence=1.0,
                content_worthiness=42,
                suggested_formats=_suggest_formats(42),
                evidence={"round": rnd},
            ))

        # Barrier break
        barriers = BARRIERS_CS.get((d, stroke), [])
        if prev_best_cs:
            for b in barriers:
                if prev_best_cs >= b > time_cs:
                    achievements.append(Achievement(
                        type="BARRIER_BREAK",
                        swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                        event_code=event_code,
                        explanation=f"First time under {cs_to_str(b)} in {event_human(event_code)} "
                                    f"({cs_to_str(time_cs)}).",
                        confidence=0.95,
                        content_worthiness=80,
                        suggested_formats=_suggest_formats(80),
                        evidence={"barrier_cs": b, "time_cs": time_cs,
                                  "previous_best_cs": prev_best_cs},
                    ))

        # Club record
        if club_id:
            rec = conn.execute(
                "SELECT time_cs, holder, age_band FROM club_record "
                "WHERE club_id=? AND event_code=? AND course=? "
                "ORDER BY time_cs ASC LIMIT 1",
                (club_id, event_code, course),
            ).fetchone()
            if rec and time_cs < rec[0]:
                achievements.append(Achievement(
                    type="RECORD_BROKEN",
                    swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                    event_code=event_code,
                    explanation=(
                        f"CLUB RECORD: {cs_to_str(time_cs)} in {event_human(event_code)}. "
                        f"Previous record {cs_to_str(rec[0])} held by {rec[1] or 'unknown'}."
                    ),
                    confidence=0.99,
                    content_worthiness=95,
                    suggested_formats=_suggest_formats(95),
                    evidence={"old_record_cs": rec[0], "holder": rec[1], "new_time_cs": time_cs},
                ))

        # Qualifying time hit
        gender_for_qt = g if g in ("M", "F") else None
        if gender_for_qt:
            qts = conn.execute(
                "SELECT standard, time_cs FROM qualifying_time "
                "WHERE event_code=? AND course=? AND gender=? AND time_cs >= ?",
                (event_code, course, gender_for_qt, time_cs),
            ).fetchall()
            for qt_standard, qt_cs in qts:
                achievements.append(Achievement(
                    type="QT_HIT",
                    swimmer_id=swimmer_id, swimmer_name=name, race_id=race_id,
                    event_code=event_code,
                    explanation=(
                        f"Hit the {qt_standard} qualifying time in "
                        f"{event_human(event_code)} ({cs_to_str(time_cs)}, "
                        f"standard {cs_to_str(qt_cs)})."
                    ),
                    confidence=0.95,
                    content_worthiness=85,
                    suggested_formats=_suggest_formats(85),
                    evidence={"standard": qt_standard, "qt_cs": qt_cs, "time_cs": time_cs},
                ))

    # Meet-wide: biggest improvement (top 3)
    improvement_pool.sort(key=lambda x: x[0], reverse=True)
    for i, (margin, info) in enumerate(improvement_pool[:3]):
        score = 80 - i * 8  # 80, 72, 64
        achievements.append(Achievement(
            type="BIGGEST_IMPROVEMENT",
            swimmer_id=info["swimmer_id"], swimmer_name=info["name"],
            race_id=info["race_id"], event_code=info["event_code"],
            explanation=(
                f"#{i+1} biggest improvement of the meet: "
                f"{cs_to_str(margin)} faster in {event_human(info['event_code'])}."
            ),
            confidence=0.9,
            content_worthiness=score,
            suggested_formats=_suggest_formats(score),
            evidence={"rank": i+1, "margin_cs": margin, "time_cs": info["time_cs"]},
        ))

    # Team-wide stat: count of PBs
    pb_count = sum(1 for a in achievements if a.type in ("CONFIRMED_PB", "LIKELY_PB"))
    if pb_count >= 3:
        achievements.append(Achievement(
            type="TEAM_STAT",
            swimmer_id=None, swimmer_name="(Team)",
            race_id=None, event_code="-",
            explanation=f"{pb_count} personal bests across the meet.",
            confidence=0.9,
            content_worthiness=60,
            suggested_formats=_suggest_formats(60),
            evidence={"pb_count": pb_count},
        ))

    conn.commit()
    achievements.sort(key=lambda a: a.content_worthiness, reverse=True)
    return achievements


def persist_achievements(conn: sqlite3.Connection, meet_id: int,
                         items: list[Achievement]) -> list[int]:
    cur = conn.cursor()
    ids = []
    for a in items:
        cur.execute(
            "INSERT INTO achievement (meet_id, swimmer_id, race_id, type, "
            "evidence_json, explanation, confidence, content_worthiness, suggested_formats) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (meet_id, a.swimmer_id, a.race_id, a.type,
             json.dumps(a.evidence), a.explanation, a.confidence,
             a.content_worthiness, json.dumps(a.suggested_formats)),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids
