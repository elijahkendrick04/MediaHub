"""Athlete registry — SQLite-backed identity across runs (W.1).

Tables (in ``DATA_DIR/data.db``, the shared store):

    athletes         one row per athlete per workspace (org-scoped)
    athlete_aliases  normalised name variants → athlete id
    athlete_swims    one row per completed swim per run (the milestone log)

Every public function is org-scoped by ``profile_id`` (the workspace id
used across the app — ADR-0003/ADR-0014). All take an optional
``db_path`` so tests run against a throwaway database.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)


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
CREATE TABLE IF NOT EXISTS athletes (
    id             TEXT PRIMARY KEY,
    profile_id     TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    asa_id         TEXT,
    birth_year     INTEGER,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_athletes_profile
    ON athletes(profile_id, active);

CREATE TABLE IF NOT EXISTS athlete_aliases (
    profile_id TEXT NOT NULL,
    alias      TEXT NOT NULL,
    athlete_id TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'run',
    created_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_athlete_aliases_athlete
    ON athlete_aliases(athlete_id);

CREATE TABLE IF NOT EXISTS athlete_swims (
    profile_id TEXT NOT NULL,
    athlete_id TEXT NOT NULL,
    run_id     TEXT NOT NULL,
    event      TEXT NOT NULL,
    swim_date  TEXT,
    time_cs    INTEGER NOT NULL,
    PRIMARY KEY (profile_id, athlete_id, run_id, event, time_cs)
);
CREATE INDEX IF NOT EXISTS idx_athlete_swims_athlete
    ON athlete_swims(profile_id, athlete_id);
CREATE INDEX IF NOT EXISTS idx_athlete_swims_run
    ON athlete_swims(profile_id, run_id);
"""


def ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Name normalisation — the alias key. Deterministic by design.
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s\-']", flags=re.UNICODE)


def normalise_name(name: str) -> str:
    """Casefolded, punctuation-stripped, whitespace-collapsed name key.

    Handles the "Last, First" convention some result files use.
    """
    s = (name or "").strip()
    if "," in s:
        last, _, first = s.partition(",")
        s = f"{first.strip()} {last.strip()}"
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip().casefold()
    return s


def initials_of(name: str) -> str:
    """ "Maya Patel" → "M.P." — used by the consent initials-only rendering."""
    parts = [p for p in normalise_name(name).split(" ") if p]
    if not parts:
        return ""
    return ".".join(p[0].upper() for p in parts) + "."


@dataclass
class AthleteRecord:
    athlete_id: str
    profile_id: str
    canonical_name: str
    asa_id: Optional[str] = None
    birth_year: Optional[int] = None
    active: bool = True
    aliases: list[str] = field(default_factory=list)
    race_count: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row: sqlite3.Row) -> AthleteRecord:
    return AthleteRecord(
        athlete_id=row["id"],
        profile_id=row["profile_id"],
        canonical_name=row["canonical_name"],
        asa_id=row["asa_id"],
        birth_year=row["birth_year"],
        active=bool(row["active"]),
    )


# ---------------------------------------------------------------------------
# Resolution / creation
# ---------------------------------------------------------------------------


def resolve(profile_id: str, name: str, db_path: Optional[Path] = None) -> Optional[AthleteRecord]:
    """Look an athlete up by any known alias. None when unknown."""
    if not profile_id or not name:
        return None
    ensure_schema(db_path)
    key = normalise_name(name)
    if not key:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT a.* FROM athletes a
            JOIN athlete_aliases al ON al.athlete_id = a.id
            WHERE al.profile_id = ? AND al.alias = ?
            """,
            (profile_id, key),
        ).fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def get_or_create(
    profile_id: str,
    name: str,
    *,
    birth_year: Optional[int] = None,
    source: str = "run",
    db_path: Optional[Path] = None,
) -> Optional[AthleteRecord]:
    """Resolve by alias, creating the athlete + alias when unknown."""
    if not profile_id or not normalise_name(name):
        return None
    existing = resolve(profile_id, name, db_path)
    if existing is not None:
        if birth_year and not existing.birth_year:
            set_details(profile_id, existing.athlete_id, birth_year=birth_year, db_path=db_path)
            existing.birth_year = birth_year
        return existing
    conn = _connect(db_path)
    try:
        aid = uuid.uuid4().hex[:12]
        now = _now()
        display = _WS_RE.sub(" ", (name or "").strip())
        if "," in display:
            last, _, first = display.partition(",")
            display = f"{first.strip()} {last.strip()}"
        conn.execute(
            "INSERT INTO athletes (id, profile_id, canonical_name, birth_year,"
            " active, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
            (aid, profile_id, display, birth_year, now, now),
        )
        conn.execute(
            "INSERT OR IGNORE INTO athlete_aliases"
            " (profile_id, alias, athlete_id, source, created_at) VALUES (?,?,?,?,?)",
            (profile_id, normalise_name(name), aid, source, now),
        )
        conn.commit()
        return AthleteRecord(
            athlete_id=aid,
            profile_id=profile_id,
            canonical_name=display,
            birth_year=birth_year,
        )
    finally:
        conn.close()


def set_details(
    profile_id: str,
    athlete_id: str,
    *,
    asa_id: Optional[str] = None,
    birth_year: Optional[int] = None,
    active: Optional[bool] = None,
    canonical_name: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> bool:
    ensure_schema(db_path)
    sets, args = [], []
    if asa_id is not None:
        sets.append("asa_id = ?")
        args.append(asa_id.strip() or None)
    if birth_year is not None:
        sets.append("birth_year = ?")
        args.append(int(birth_year))
    if active is not None:
        sets.append("active = ?")
        args.append(1 if active else 0)
    if canonical_name is not None and canonical_name.strip():
        sets.append("canonical_name = ?")
        args.append(canonical_name.strip())
    if not sets:
        return False
    sets.append("updated_at = ?")
    args.extend([_now(), athlete_id, profile_id])
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"UPDATE athletes SET {', '.join(sets)} WHERE id = ? AND profile_id = ?",
            args,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Swim log — the milestone substrate
# ---------------------------------------------------------------------------


def record_run_swims(
    profile_id: str,
    run_id: str,
    swims: Iterable[dict],
    db_path: Optional[Path] = None,
) -> dict:
    """Idempotently log completed swims for a run.

    Each swim dict: ``{"name", "event", "time_cs", "swim_date"?, "birth_year"?}``.
    Swims without a name, event or time are skipped (DQ/NS rows carry no
    milestone weight). Returns ``{"athletes": n, "swims": n}``.
    """
    ensure_schema(db_path)
    n_athletes, n_swims = 0, 0
    seen_ids: set[str] = set()
    for swim in swims:
        name = (swim.get("name") or "").strip()
        event = (swim.get("event") or "").strip()
        time_cs = swim.get("time_cs")
        if not name or not event or time_cs is None:
            continue
        rec = get_or_create(
            profile_id,
            name,
            birth_year=swim.get("birth_year"),
            source="run",
            db_path=db_path,
        )
        if rec is None:
            continue
        if rec.athlete_id not in seen_ids:
            seen_ids.add(rec.athlete_id)
            n_athletes += 1
        conn = _connect(db_path)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO athlete_swims"
                " (profile_id, athlete_id, run_id, event, swim_date, time_cs)"
                " VALUES (?,?,?,?,?,?)",
                (
                    profile_id,
                    rec.athlete_id,
                    run_id,
                    event,
                    swim.get("swim_date"),
                    int(time_cs),
                ),
            )
            conn.commit()
            n_swims += cur.rowcount
        finally:
            conn.close()
    return {"athletes": n_athletes, "swims": n_swims}


def _swims_from_run_payload(
    payload: dict, is_ours: Optional[Callable[[Optional[str]], bool]] = None
) -> list[dict]:
    """Extract loggable swims from a runs_v4 snapshot dict."""
    meet = payload.get("meet") or {}
    swimmers = meet.get("swimmers") or {}
    out: list[dict] = []
    for res in meet.get("results") or []:
        if res.get("dq") or res.get("finals_time_cs") is None:
            continue
        sk = res.get("swimmer_key") or ""
        sw = swimmers.get(sk) or {}
        club = res.get("club_code") or sw.get("club_code")
        if is_ours is not None and not is_ours(club):
            continue
        name = f"{sw.get('first_name', '')} {sw.get('last_name', '')}".strip() or sk
        dist = res.get("distance")
        stroke = res.get("stroke")
        course = res.get("course")
        if not dist or not stroke:
            continue
        yob = None
        dob = sw.get("dob") or ""
        if isinstance(dob, str) and len(dob) >= 4 and dob[:4].isdigit():
            yob = int(dob[:4])
        out.append(
            {
                "name": name,
                "event": f"{dist}{stroke}{course or ''}",
                "time_cs": res.get("finals_time_cs"),
                "swim_date": res.get("swim_date") or meet.get("start_date"),
                "birth_year": yob,
            }
        )
    return out


def sync_run_payload(
    profile_id: str,
    payload: dict,
    *,
    is_ours: Optional[Callable[[Optional[str]], bool]] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Log one finished run's swims into the registry (idempotent)."""
    run_id = payload.get("run_id") or ""
    if not profile_id or not run_id:
        return {"athletes": 0, "swims": 0}
    swims = _swims_from_run_payload(payload, is_ours)
    return record_run_swims(profile_id, run_id, swims, db_path=db_path)


def backfill_from_runs(
    profile_id: str,
    runs_dir: Path,
    *,
    is_ours: Optional[Callable[[Optional[str]], bool]] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Backfill the registry from every persisted run owned by the org."""
    import json

    totals = {"runs": 0, "athletes": 0, "swims": 0}
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return totals
    for p in sorted(runs_dir.glob("*.json")):
        if p.name.endswith("__workflow.json"):
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (payload.get("profile_id") or "") != profile_id:
            continue
        stats = sync_run_payload(profile_id, payload, is_ours=is_ours, db_path=db_path)
        totals["runs"] += 1
        totals["athletes"] += stats["athletes"]
        totals["swims"] += stats["swims"]
    return totals


# ---------------------------------------------------------------------------
# Roster / merge
# ---------------------------------------------------------------------------


def list_athletes(profile_id: str, db_path: Optional[Path] = None) -> list[AthleteRecord]:
    """Active roster with alias lists and race counts, ordered by name."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM athletes WHERE profile_id = ? AND active = 1"
            " ORDER BY canonical_name COLLATE NOCASE",
            (profile_id,),
        ).fetchall()
        records = [_row_to_record(r) for r in rows]
        for rec in records:
            rec.aliases = [
                r["alias"]
                for r in conn.execute(
                    "SELECT alias FROM athlete_aliases WHERE athlete_id = ? ORDER BY alias",
                    (rec.athlete_id,),
                ).fetchall()
            ]
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM athlete_swims WHERE profile_id = ? AND athlete_id = ?",
                (profile_id, rec.athlete_id),
            ).fetchone()
            rec.race_count = int(cnt["c"]) if cnt else 0
        return records
    finally:
        conn.close()


def athlete_swims(
    profile_id: str,
    athlete_id: str,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """All logged swims for one athlete, newest first.

    Each row: ``{"event", "swim_date", "time_cs", "run_id"}``. Empty list
    when the athlete has no logged swims (or isn't this org's).
    """
    if not profile_id or not athlete_id:
        return []
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT event, swim_date, time_cs, run_id FROM athlete_swims"
            " WHERE profile_id = ? AND athlete_id = ?"
            " ORDER BY swim_date DESC, event",
            (profile_id, athlete_id),
        ).fetchall()
        return [
            {
                "event": r["event"],
                "swim_date": r["swim_date"],
                "time_cs": r["time_cs"],
                "run_id": r["run_id"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def merge_athletes(
    profile_id: str,
    keep_id: str,
    merge_id: str,
    *,
    actor: str = "",
    db_path: Optional[Path] = None,
) -> bool:
    """Fold ``merge_id`` into ``keep_id``: aliases and swims move across,
    the merged row is deactivated, and the decision is audited. This is
    the persistence surface for the review-time "same swimmer?" call.
    """
    if keep_id == merge_id:
        return False
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        keep = conn.execute(
            "SELECT * FROM athletes WHERE id = ? AND profile_id = ?", (keep_id, profile_id)
        ).fetchone()
        merged = conn.execute(
            "SELECT * FROM athletes WHERE id = ? AND profile_id = ?", (merge_id, profile_id)
        ).fetchone()
        if keep is None or merged is None:
            return False
        now = _now()
        conn.execute(
            "UPDATE athlete_aliases SET athlete_id = ?, source = 'merge'"
            " WHERE athlete_id = ? AND profile_id = ?",
            (keep_id, merge_id, profile_id),
        )
        # Move the swim log across, tolerating rows that already exist on
        # the kept athlete (same run/event/time logged under both names).
        conn.execute(
            "INSERT OR IGNORE INTO athlete_swims"
            " (profile_id, athlete_id, run_id, event, swim_date, time_cs)"
            " SELECT profile_id, ?, run_id, event, swim_date, time_cs"
            " FROM athlete_swims WHERE profile_id = ? AND athlete_id = ?",
            (keep_id, profile_id, merge_id),
        )
        conn.execute(
            "DELETE FROM athlete_swims WHERE profile_id = ? AND athlete_id = ?",
            (profile_id, merge_id),
        )
        conn.execute(
            "UPDATE athletes SET active = 0, updated_at = ? WHERE id = ? AND profile_id = ?",
            (now, merge_id, profile_id),
        )
        if not keep["birth_year"] and merged["birth_year"]:
            conn.execute(
                "UPDATE athletes SET birth_year = ?, updated_at = ? WHERE id = ?",
                (merged["birth_year"], now, keep_id),
            )
        conn.commit()
    finally:
        conn.close()
    try:
        from mediahub.workflow.autonomy import AuditLog

        AuditLog().record(
            profile_id,
            f"athletes:{keep_id}",
            "athlete_merge",
            tool="merge_athletes",
            args={"keep": keep_id, "merged": merge_id, "actor": actor},
            result="merged",
        )
    except Exception:  # audit is best-effort, never blocks the merge
        log.warning("athlete merge audit failed", exc_info=True)
    return True


# ---------------------------------------------------------------------------
# Milestone context — consumed by the deterministic MilestoneDetector
# ---------------------------------------------------------------------------


def milestone_context(
    profile_id: str,
    *,
    exclude_run_id: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Per-athlete prior history keyed by normalised alias.

    ``{alias: {"athlete_id", "prior_races", "prior_events": [event,...]}}``
    counting only swims from runs other than ``exclude_run_id`` (so the
    run being analysed never counts toward its own milestones). Empty
    dict when the registry has nothing — detectors stay silent then.
    """
    if not profile_id:
        return {}
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT al.alias, al.athlete_id,
                   COUNT(s.run_id) AS prior_races
            FROM athlete_aliases al
            LEFT JOIN athlete_swims s
                   ON s.athlete_id = al.athlete_id
                  AND s.profile_id = al.profile_id
                  AND s.run_id != ?
            WHERE al.profile_id = ?
            GROUP BY al.alias, al.athlete_id
            """,
            (exclude_run_id, profile_id),
        ).fetchall()
        out: dict = {}
        events_by_athlete: dict[str, list[str]] = {}
        for r in rows:
            aid = r["athlete_id"]
            if aid not in events_by_athlete:
                events_by_athlete[aid] = [
                    e["event"]
                    for e in conn.execute(
                        "SELECT DISTINCT event FROM athlete_swims"
                        " WHERE profile_id = ? AND athlete_id = ? AND run_id != ?",
                        (profile_id, aid, exclude_run_id),
                    ).fetchall()
                ]
            out[r["alias"]] = {
                "athlete_id": aid,
                "prior_races": int(r["prior_races"]),
                "prior_events": events_by_athlete[aid],
            }
        return out
    finally:
        conn.close()
