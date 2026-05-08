"""
Qualification standards registry.

Loads `data/quals.json` and provides lookups + comparisons for meet swims.

Concepts:
  - A *standard* is a row of (event, gender, course, qualifying or consideration time, window).
  - A *qual hit* is a meet swim that meets or beats a standard inside its window.
  - Each standard has an importance_score driving how heavily a hit weighs in ranking.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .enrichment_swimmingresults import parse_swim_time


DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "quals.json"
FRESHNESS_DAYS = 60  # standards retrieved more than this many days ago are "stale"


@dataclass
class Standard:
    standard_id: str
    competition: str
    body: str
    level: str          # international | national | university | regional | county | open
    course: str         # LC | SC
    season: str
    window_start: Optional[date]
    window_end: Optional[date]
    venue: str
    event_dates: str
    source_url: str
    retrieved_at: str
    confidence: str
    importance_score: int
    relevance_clubs: list[str]  # club codes; "*" means relevant to everyone
    notes: str
    times: list[dict]   # {event, gender, ct, qt_only?}

    def is_relevant_to(self, club_code: str) -> bool:
        if "*" in self.relevance_clubs:
            return True
        return club_code in self.relevance_clubs

    def is_fresh(self, today: Optional[date] = None) -> bool:
        try:
            ts = datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
        except Exception:
            return False
        today = today or datetime.now(timezone.utc).date()
        age = (today - ts.date()).days
        return age <= FRESHNESS_DAYS

    def in_window(self, swim_date: date) -> bool:
        if self.window_start and swim_date < self.window_start:
            return False
        if self.window_end and swim_date > self.window_end:
            return False
        return True

    def lookup(self, distance: int, stroke: str, gender: str) -> Optional[dict]:
        key = f"{distance}_{stroke}"
        for t in self.times:
            if t["event"] == key and t["gender"] == gender:
                return t
        return None


@dataclass
class QualHit:
    standard_id: str
    competition: str
    body: str
    level: str
    course: str
    importance_score: int
    threshold_str: str
    threshold_sec: float
    swim_time_sec: float
    margin_sec: float        # negative means under the standard (i.e. achieved)
    in_window: bool
    source_url: str
    retrieved_at: str
    note: str = ""


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[Standard]:
    data = json.loads(Path(path).read_text())
    out: list[Standard] = []
    for s in data.get("standards", []):
        out.append(Standard(
            standard_id=s["id"],
            competition=s["competition"],
            body=s["body"],
            level=s["level"],
            course=s["course"],
            season=s["season"],
            window_start=_parse_iso_date(s.get("window_start")),
            window_end=_parse_iso_date(s.get("window_end")),
            venue=s.get("venue", ""),
            event_dates=s.get("event_dates", ""),
            source_url=s["source_url"],
            retrieved_at=s["retrieved_at"],
            confidence=s.get("confidence", "medium"),
            importance_score=int(s.get("importance_score", 50)),
            relevance_clubs=s.get("relevance_clubs", ["*"]),
            notes=s.get("notes", ""),
            times=s.get("times", []),
        ))
    return out


def stale_standards(standards: list[Standard]) -> list[Standard]:
    return [s for s in standards if not s.is_fresh()]


def relevant_standards(standards: list[Standard], club_code: str, course: str) -> list[Standard]:
    return [s for s in standards if s.is_relevant_to(club_code) and s.course == course]


def check_swim_against_standards(
    *,
    standards: list[Standard],
    distance: int,
    stroke: str,
    gender: str,
    course: str,
    swim_time_sec: float,
    swim_date: date,
    club_code: str,
) -> list[QualHit]:
    """
    Return all qualification hits for a swim, sorted by importance descending.

    A 'hit' is recorded when:
      - the standard is relevant to the swimmer's club
      - the standard's course matches the swim's course (LC vs LC, SC vs SC)
      - the swim is at or under the threshold time
    Window is reported but does NOT prevent recording the hit; the caller decides
    how strictly to treat out-of-window hits (we mark them but do not hide them).
    """
    hits: list[QualHit] = []
    for s in standards:
        if not s.is_relevant_to(club_code):
            continue
        if s.course != course:
            continue
        row = s.lookup(distance, stroke, gender)
        if row is None:
            continue
        threshold_sec = parse_swim_time(row["ct"])
        if threshold_sec is None:
            continue
        margin = swim_time_sec - threshold_sec
        if margin > 0.005:
            continue  # not achieved
        hits.append(QualHit(
            standard_id=s.standard_id,
            competition=s.competition,
            body=s.body,
            level=s.level,
            course=s.course,
            importance_score=s.importance_score,
            threshold_str=row["ct"],
            threshold_sec=threshold_sec,
            swim_time_sec=swim_time_sec,
            margin_sec=margin,
            in_window=s.in_window(swim_date),
            source_url=s.source_url,
            retrieved_at=s.retrieved_at,
            note=("Inside qualification window." if s.in_window(swim_date)
                  else "Achieved time but OUTSIDE the qualification window."),
        ))
    hits.sort(key=lambda h: (-h.importance_score, h.margin_sec))
    return hits
