"""Club records store — deterministic, org-scoped, approval-gated (W.3).

Records are keyed (distance, stroke, course, gender, age_group). The
table changes in exactly two ways:

* CSV import of the club's records sheet (onboarding), and
* ``apply_approved_card`` — called when a NEW CLUB RECORD card is
  *approved* in review. Detection alone never mutates the table.

Stroke codes follow the canonical engine (FR/BK/BR/FL/IM); courses are
LC/SC/Y; ``age_group`` is ``open`` or a band like ``11-12``.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

STROKES = ("FR", "BK", "BR", "FL", "IM")

_STROKE_ALIASES = {
    "fr": "FR",
    "free": "FR",
    "freestyle": "FR",
    "bk": "BK",
    "back": "BK",
    "backstroke": "BK",
    "br": "BR",
    "breast": "BR",
    "breaststroke": "BR",
    "fl": "FL",
    "fly": "FL",
    "butterfly": "FL",
    "im": "IM",
    "medley": "IM",
    "individual medley": "IM",
}

_COURSE_ALIASES = {"lc": "LC", "lcm": "LC", "sc": "SC", "scm": "SC", "y": "Y", "scy": "Y"}


def _db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    data_dir = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return data_dir / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = _db_path(db_path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS club_records (
    profile_id TEXT NOT NULL,
    distance   INTEGER NOT NULL,
    stroke     TEXT NOT NULL,
    course     TEXT NOT NULL,
    gender     TEXT NOT NULL,
    age_group  TEXT NOT NULL DEFAULT 'open',
    time_cs    INTEGER NOT NULL,
    holder     TEXT NOT NULL,
    set_date   TEXT,
    source     TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, distance, stroke, course, gender, age_group)
);
"""


def ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Time parsing — same conventions as the rest of the deterministic engine
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2})[.,](\d{1,2})$")


def parse_time_cs(text: str) -> Optional[int]:
    """ "1:05.32" / "31.24" → centiseconds. None when unparseable."""
    s = (text or "").strip()
    m = _TIME_RE.match(s)
    if not m:
        return None
    mins = int(m.group(1) or 0)
    secs = int(m.group(2))
    frac = m.group(3)
    cs = int(frac) * (10 if len(frac) == 1 else 1)
    if secs >= 60 and mins:
        return None
    return mins * 6000 + secs * 100 + cs


def format_time_cs(cs: int) -> str:
    mins = cs // 6000
    rem = cs - mins * 6000
    secs, frac = rem // 100, rem % 100
    return f"{mins}:{secs:02d}.{frac:02d}" if mins else f"{secs}.{frac:02d}"


def _norm_stroke(text: str) -> Optional[str]:
    return _STROKE_ALIASES.get((text or "").strip().lower())


def _norm_course(text: str) -> Optional[str]:
    return _COURSE_ALIASES.get((text or "").strip().lower())


def _norm_gender(text: str) -> Optional[str]:
    g = (text or "").strip().upper()[:1]
    return g if g in ("M", "F", "X") else None


def _norm_age_group(text: str) -> str:
    s = (text or "").strip().lower()
    return s if s else "open"


@dataclass
class RecordRow:
    profile_id: str
    distance: int
    stroke: str
    course: str
    gender: str
    age_group: str
    time_cs: int
    holder: str
    set_date: Optional[str]
    source: Optional[str]
    updated_at: str

    @property
    def time_str(self) -> str:
        return format_time_cs(self.time_cs)

    def to_dict(self) -> dict:
        return {
            "distance": self.distance,
            "stroke": self.stroke,
            "course": self.course,
            "gender": self.gender,
            "age_group": self.age_group,
            "time_cs": self.time_cs,
            "time": self.time_str,
            "holder": self.holder,
            "set_date": self.set_date or "",
            "source": self.source or "",
            "updated_at": self.updated_at,
        }


def upsert_record(
    profile_id: str,
    *,
    distance: int,
    stroke: str,
    course: str,
    gender: str,
    age_group: str = "open",
    time_cs: int,
    holder: str,
    set_date: str = "",
    source: str = "manual",
    db_path: Optional[Path] = None,
) -> None:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO club_records (profile_id, distance, stroke, course, gender,"
            " age_group, time_cs, holder, set_date, source, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(profile_id, distance, stroke, course, gender, age_group)"
            " DO UPDATE SET time_cs = excluded.time_cs, holder = excluded.holder,"
            " set_date = excluded.set_date, source = excluded.source,"
            " updated_at = excluded.updated_at",
            (
                profile_id,
                int(distance),
                stroke,
                course,
                gender,
                _norm_age_group(age_group),
                int(time_cs),
                holder.strip(),
                set_date or None,
                source or None,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_record(
    profile_id: str,
    *,
    distance: int,
    stroke: str,
    course: str,
    gender: str,
    age_group: str = "open",
    db_path: Optional[Path] = None,
) -> bool:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM club_records WHERE profile_id = ? AND distance = ? AND"
            " stroke = ? AND course = ? AND gender = ? AND age_group = ?",
            (profile_id, int(distance), stroke, course, gender, _norm_age_group(age_group)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_records(profile_id: str, db_path: Optional[Path] = None) -> list[RecordRow]:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM club_records WHERE profile_id = ?"
            " ORDER BY course, stroke, distance, gender, age_group",
            (profile_id,),
        ).fetchall()
        return [
            RecordRow(
                profile_id=r["profile_id"],
                distance=r["distance"],
                stroke=r["stroke"],
                course=r["course"],
                gender=r["gender"],
                age_group=r["age_group"],
                time_cs=r["time_cs"],
                holder=r["holder"],
                set_date=r["set_date"],
                source=r["source"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def records_map(profile_id: str, db_path: Optional[Path] = None) -> dict:
    """Detector-shaped lookup:
    ``{(distance, stroke, course, gender, age_group): {"time_cs", "holder", "set_date"}}``.
    Empty dict when the workspace has no records — the detector stays silent.
    """
    out: dict = {}
    for r in list_records(profile_id, db_path):
        out[(r.distance, r.stroke, r.course, r.gender, r.age_group)] = {
            "time_cs": r.time_cs,
            "holder": r.holder,
            "set_date": r.set_date or "",
        }
    return out


# ---------------------------------------------------------------------------
# CSV import — the onboarding hook
# ---------------------------------------------------------------------------


def import_csv(
    profile_id: str,
    text: str,
    *,
    source: str = "csv-import",
    db_path: Optional[Path] = None,
) -> dict:
    """Import ``event,course,gender,age_group,time,holder[,date]`` rows.

    ``event`` is "<distance> <stroke>" in any common spelling ("100 FR",
    "100 Freestyle"). Unparseable rows are reported back, never guessed.
    """
    ok, skipped = 0, []
    reader = csv.reader(io.StringIO(text or ""))
    for i, row in enumerate(reader, start=1):
        if not row or not (row[0] or "").strip():
            continue
        first = row[0].strip().lower()
        if i == 1 and first in ("event", "race"):
            continue  # header row
        if len(row) < 6:
            skipped.append(
                {"row": i, "reason": "expected event,course,gender,age_group,time,holder"}
            )
            continue
        m = re.match(r"^(\d{2,4})\s*[mx]?\s+(.+)$", row[0].strip(), flags=re.IGNORECASE)
        stroke = _norm_stroke(m.group(2)) if m else None
        course = _norm_course(row[1])
        gender = _norm_gender(row[2])
        time_cs = parse_time_cs(row[4])
        holder = (row[5] or "").strip()
        if (
            not m
            or stroke is None
            or course is None
            or gender is None
            or time_cs is None
            or not holder
        ):
            skipped.append({"row": i, "reason": "unparseable event/course/gender/time/holder"})
            continue
        upsert_record(
            profile_id,
            distance=int(m.group(1)),
            stroke=stroke,
            course=course,
            gender=gender,
            age_group=row[3],
            time_cs=time_cs,
            holder=holder,
            set_date=row[6].strip() if len(row) > 6 else "",
            source=source,
            db_path=db_path,
        )
        ok += 1
    return {"imported": ok, "skipped": skipped}


# ---------------------------------------------------------------------------
# Approval hook — the ONLY in-product mutation path (update-on-approval)
# ---------------------------------------------------------------------------


def apply_approved_card(profile_id: str, card: dict, db_path: Optional[Path] = None) -> bool:
    """Apply an approved NEW CLUB RECORD card to the table.

    ``card`` is the enriched pack/run card dict whose
    ``achievement.type == "club_record"``. Idempotent and monotonic: the
    stored mark only ever improves, so re-approval or out-of-order
    approvals can never regress the table.
    """
    ach = (card or {}).get("achievement") or card or {}
    if ach.get("type") != "club_record":
        return False
    facts = ach.get("raw_facts") or {}
    required = ("distance", "stroke", "course", "gender", "new_time_cs")
    if any(facts.get(k) in (None, "") for k in required):
        log.warning("club_record approval missing facts: %s", facts)
        return False
    distance = int(facts["distance"])
    stroke = str(facts["stroke"])
    course = str(facts["course"])
    gender = str(facts["gender"])
    age_group = _norm_age_group(str(facts.get("age_group") or "open"))
    new_cs = int(facts["new_time_cs"])
    current = records_map(profile_id, db_path).get((distance, stroke, course, gender, age_group))
    if current is not None and current["time_cs"] <= new_cs:
        return False  # table already carries an equal-or-better mark
    upsert_record(
        profile_id,
        distance=distance,
        stroke=stroke,
        course=course,
        gender=gender,
        age_group=age_group,
        time_cs=new_cs,
        holder=str(ach.get("swimmer_name") or facts.get("swimmer_name") or "").strip() or "Unknown",
        set_date=str(facts.get("swim_date") or ""),
        source=f"approved:{card.get('run_id', '') or ach.get('swim_id', '')}",
        db_path=db_path,
    )
    return True
