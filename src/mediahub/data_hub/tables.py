"""data_hub.tables — read-only canonical views over the engine's stores (1.13).

The data hub shows the club its *real* data as browsable tables. These views are
**read-only mirrors** of what the deterministic engine already holds — they
never re-derive or guess anything:

* ``athletes``  — the athlete registry (``athletes/registry.py``)
* ``records``   — the club records store (``club_records/store.py``)
* ``meets``     — one row per processed meet/run (the run index)
* ``results``   — the individual swims in one run (canonical ``Meet.results``)
* ``swimmers``  — the swimmers seen in one run (canonical ``Meet.swimmers``)
* ``clubs``     — the clubs seen in one run (canonical ``Meet.clubs``)

Every cell is stamped with its provenance. A swim parsed from a results file is
``PARSED``; a record imported from a CSV is ``IMPORTED``; an athlete's manually
set birth year is ``HAND_ENTERED``. Anything the engine flagged as ambiguous
(a parse warning, a non-finished swim, a low-confidence identity) is surfaced as
a flagged cell — never hidden.

Editable org tables (rosters, sponsor facts, custom sheets) live in
``data_hub/store.py``; this module is only the read side of the engine's data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator, Optional

from mediahub.athletes import registry as _athletes
from mediahub.club_records import store as _records

from .models import DataCell, DataColumn, DataTable, DataWarning, Provenance

# How many recent runs the hub index lists result/swimmer/club tables for.
_RECENT_RUNS_CAP = 50

_STROKE_NAMES = {
    "FR": "Freestyle",
    "BK": "Backstroke",
    "BR": "Breaststroke",
    "FL": "Butterfly",
    "IM": "Individual Medley",
    "MEDLEY": "Medley",
}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))


def _runs_dir(runs_dir: Optional[Path] = None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir)
    env = os.environ.get("RUNS_DIR")
    if env:
        return Path(env)
    return _data_dir() / "runs_v4"


def _format_time_cs(cs: object) -> str:
    if cs is None:
        return ""
    try:
        return _records.format_time_cs(int(cs))
    except (TypeError, ValueError):
        return ""


def _event_label(distance: object, stroke: object, course: object) -> str:
    stroke_code = str(stroke or "").strip().upper()
    name = _STROKE_NAMES.get(stroke_code, stroke_code or "?")
    try:
        dist = int(distance)
    except (TypeError, ValueError):
        dist = 0
    crs = str(course or "").strip().upper()
    crs_part = f" ({crs})" if crs else ""
    return f"{dist}m {name}{crs_part}".strip()


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


def _load_run(run_id: str, runs_dir: Optional[Path] = None) -> Optional[dict]:
    path = _runs_dir(runs_dir) / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _iter_profile_runs(
    profile_id: str, *, runs_dir: Optional[Path] = None, cap: int = 0
) -> Iterator[tuple[str, dict]]:
    """Yield (run_id, run_data) for runs owned by ``profile_id``, newest first."""
    base = _runs_dir(runs_dir)
    if not base.exists():
        return
    files = [p for p in base.glob("*.json") if "__" not in p.name]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    seen = 0
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if profile_id and data.get("profile_id") not in (None, "", profile_id):
            continue
        yield p.stem, data
        seen += 1
        if cap and seen >= cap:
            return


def _warnings_by_record(meet: dict) -> dict[str, list[dict]]:
    """Index a meet's parse warnings by their ``record`` anchor."""
    out: dict[str, list[dict]] = {}
    for w in meet.get("warnings", []) or []:
        if isinstance(w, dict) and w.get("record"):
            out.setdefault(str(w["record"]), []).append(w)
    return out


# ---------------------------------------------------------------------------
# Athletes view
# ---------------------------------------------------------------------------


def athletes_table(profile_id: str, *, db_path: Optional[Path] = None) -> DataTable:
    columns = [
        DataColumn("name", "Athlete", "text", frozen=True),
        DataColumn("asa_id", "Member ID", "text"),
        DataColumn("birth_year", "Birth year", "int"),
        DataColumn("active", "Active", "bool"),
        DataColumn("race_count", "Swims logged", "int"),
        DataColumn("aliases", "Also known as", "text"),
    ]
    rows: list[dict] = []
    for rec in _athletes.list_athletes(profile_id, db_path=db_path):
        rows.append(
            {
                "name": DataCell(
                    rec.canonical_name,
                    rec.canonical_name,
                    provenance=Provenance.PARSED,
                    confidence="high",
                    source="athlete registry",
                ),
                "asa_id": DataCell(
                    rec.asa_id or "",
                    rec.asa_id or "",
                    provenance=Provenance.HAND_ENTERED if rec.asa_id else Provenance.REGISTRY,
                ),
                "birth_year": DataCell(
                    rec.birth_year,
                    str(rec.birth_year) if rec.birth_year else "",
                    provenance=Provenance.HAND_ENTERED if rec.birth_year else Provenance.REGISTRY,
                ),
                "active": DataCell(
                    bool(rec.active),
                    "Yes" if rec.active else "No",
                    provenance=Provenance.REGISTRY,
                ),
                "race_count": DataCell(
                    rec.race_count,
                    str(rec.race_count),
                    provenance=Provenance.PARSED,
                ),
                "aliases": DataCell(
                    ", ".join(rec.aliases),
                    ", ".join(rec.aliases),
                    provenance=Provenance.PARSED,
                ),
            }
        )
    return DataTable(
        table_id="athletes",
        title="Athletes",
        kind="athletes",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source="athlete registry",
        description="Every athlete MediaHub has identified across your meets.",
    )


# ---------------------------------------------------------------------------
# Records view
# ---------------------------------------------------------------------------


def _record_provenance(source: str) -> str:
    s = (source or "").strip().lower()
    if s.startswith("csv"):
        return Provenance.IMPORTED
    if s.startswith("approved:"):
        return Provenance.DERIVED
    if s == "manual":
        return Provenance.HAND_ENTERED
    return Provenance.REGISTRY


def records_table(profile_id: str, *, db_path: Optional[Path] = None) -> DataTable:
    columns = [
        DataColumn("event", "Event", "text", frozen=True),
        DataColumn("course", "Course", "text"),
        DataColumn("gender", "Gender", "text"),
        DataColumn("age_group", "Age group", "text"),
        DataColumn("time", "Record", "time"),
        DataColumn("holder", "Holder", "text"),
        DataColumn("set_date", "Set", "date"),
        DataColumn("source", "Where from", "text"),
    ]
    rows: list[dict] = []
    for rec in _records.list_records(profile_id, db_path=db_path):
        prov = _record_provenance(rec.source or "")
        rows.append(
            {
                "event": DataCell(
                    _event_label(rec.distance, rec.stroke, ""),
                    _event_label(rec.distance, rec.stroke, ""),
                    provenance=prov,
                ),
                "course": DataCell(rec.course, rec.course, provenance=prov),
                "gender": DataCell(rec.gender, rec.gender, provenance=prov),
                "age_group": DataCell(rec.age_group, rec.age_group, provenance=prov),
                "time": DataCell(rec.time_cs, rec.time_str, provenance=prov, confidence="high"),
                "holder": DataCell(rec.holder, rec.holder, provenance=prov),
                "set_date": DataCell(rec.set_date or "", rec.set_date or "", provenance=prov),
                "source": DataCell(rec.source or "", rec.source or "", provenance=prov),
            }
        )
    return DataTable(
        table_id="records",
        title="Club records",
        kind="records",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source="club records store",
        description="Your club's record holders, by event and age group.",
    )


# ---------------------------------------------------------------------------
# Meets / run index view
# ---------------------------------------------------------------------------


def meets_table(profile_id: str, *, runs_dir: Optional[Path] = None) -> DataTable:
    columns = [
        DataColumn("meet", "Meet", "text", frozen=True),
        DataColumn("date", "Date", "date"),
        DataColumn("venue", "Venue", "text"),
        DataColumn("course", "Course", "text"),
        DataColumn("our_swims", "Our swims", "int"),
        DataColumn("achievements", "Achievements", "int"),
        DataColumn("run_id", "Run", "text"),
    ]
    rows: list[dict] = []
    for run_id, data in _iter_profile_runs(profile_id, runs_dir=runs_dir):
        meet = data.get("meet") or {}
        rec = data.get("recognition_report") or {}
        rows.append(
            {
                "meet": DataCell(
                    meet.get("name") or data.get("file_name") or run_id,
                    meet.get("name") or data.get("file_name") or run_id,
                    provenance=Provenance.PARSED,
                ),
                "date": DataCell(
                    meet.get("start_date") or "",
                    meet.get("start_date") or "",
                    provenance=Provenance.PARSED,
                ),
                "venue": DataCell(
                    meet.get("venue") or "", meet.get("venue") or "", provenance=Provenance.PARSED
                ),
                "course": DataCell(
                    meet.get("course") or "", meet.get("course") or "", provenance=Provenance.PARSED
                ),
                "our_swims": DataCell(
                    int(data.get("our_swim_count") or 0),
                    str(data.get("our_swim_count") or 0),
                    provenance=Provenance.PARSED,
                ),
                "achievements": DataCell(
                    int(rec.get("n_achievements") or 0),
                    str(rec.get("n_achievements") or 0),
                    provenance=Provenance.DERIVED,
                ),
                "run_id": DataCell(run_id, run_id, provenance=Provenance.PARSED),
            }
        )
    return DataTable(
        table_id="meets",
        title="Meets",
        kind="meets",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source="run index",
        description="Every meet you've processed, newest first.",
    )


# ---------------------------------------------------------------------------
# Per-run views: results, swimmers, clubs
# ---------------------------------------------------------------------------


def results_table(
    profile_id: str, run_id: str, *, runs_dir: Optional[Path] = None
) -> Optional[DataTable]:
    data = _load_run(run_id, runs_dir)
    if not data:
        return None
    if profile_id and data.get("profile_id") not in (None, "", profile_id):
        return None
    meet = data.get("meet") or {}
    swimmers = meet.get("swimmers") or {}
    warn_index = _warnings_by_record(meet)

    columns = [
        DataColumn("swimmer", "Swimmer", "text", frozen=True),
        DataColumn("event", "Event", "text"),
        DataColumn("course", "Course", "text"),
        DataColumn("age_band", "Age", "text"),
        DataColumn("time", "Time", "time"),
        DataColumn("place", "Place", "int"),
        DataColumn("status", "Status", "text"),
        DataColumn("date", "Date", "date"),
    ]
    rows: list[dict] = []
    for r in meet.get("results", []) or []:
        if not isinstance(r, dict):
            continue
        key = r.get("swimmer_key") or ""
        sw = swimmers.get(key) or {}
        name = (f"{sw.get('first_name', '')} {sw.get('last_name', '')}").strip() or key
        status = str(r.get("status") or "completed")
        finished = status == "completed" and r.get("finals_time_cs") is not None
        time_display = _format_time_cs(r.get("finals_time_cs")) if finished else status.upper()

        # Surface any parse warning anchored to this swim or swimmer.
        anchor_notes: list[str] = []
        for anchor in (f"swimmer:{key}", key):
            for w in warn_index.get(anchor, []):
                anchor_notes.append(str(w.get("message", "")))

        rows.append(
            {
                "swimmer": DataCell(
                    name,
                    name,
                    provenance=Provenance.PARSED,
                    confidence=str(sw.get("identity_confidence") or ""),
                    flagged=str(sw.get("identity_confidence") or "high") == "low",
                    note="; ".join(anchor_notes),
                ),
                "event": DataCell(
                    _event_label(r.get("distance"), r.get("stroke"), r.get("course")),
                    _event_label(r.get("distance"), r.get("stroke"), r.get("course")),
                    provenance=Provenance.PARSED,
                ),
                "course": DataCell(
                    r.get("course") or "", r.get("course") or "", provenance=Provenance.PARSED
                ),
                "age_band": DataCell(
                    r.get("age_band") or "", r.get("age_band") or "", provenance=Provenance.PARSED
                ),
                "time": DataCell(
                    r.get("finals_time_cs"),
                    time_display,
                    provenance=Provenance.PARSED,
                    flagged=not finished,
                    note="" if finished else f"Not a finishing time ({status}).",
                ),
                "place": DataCell(
                    r.get("place"),
                    str(r.get("place")) if r.get("place") else "",
                    provenance=Provenance.PARSED,
                ),
                "status": DataCell(status, status, provenance=Provenance.PARSED),
                "date": DataCell(
                    r.get("swim_date") or "",
                    r.get("swim_date") or "",
                    provenance=Provenance.PARSED,
                ),
            }
        )
    title = f"Results — {meet.get('name') or run_id}"
    table = DataTable(
        table_id=f"results:{run_id}",
        title=title,
        kind="results",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source=f"run {run_id}",
        description="Every individual swim parsed from this meet.",
    )
    for w in meet.get("warnings", []) or []:
        if isinstance(w, dict):
            table.warnings.append(
                DataWarning(0, str(w.get("message", "")), severity=str(w.get("severity", "warn")))
            )
    return table


def swimmers_table(
    profile_id: str, run_id: str, *, runs_dir: Optional[Path] = None
) -> Optional[DataTable]:
    data = _load_run(run_id, runs_dir)
    if not data:
        return None
    if profile_id and data.get("profile_id") not in (None, "", profile_id):
        return None
    meet = data.get("meet") or {}
    columns = [
        DataColumn("name", "Swimmer", "text", frozen=True),
        DataColumn("gender", "Gender", "text"),
        DataColumn("age", "Age", "int"),
        DataColumn("club", "Club", "text"),
        DataColumn("asa_id", "Member ID", "text"),
        DataColumn("identity", "Identity match", "text"),
    ]
    rows: list[dict] = []
    for key, sw in (meet.get("swimmers") or {}).items():
        if not isinstance(sw, dict):
            continue
        name = (f"{sw.get('first_name', '')} {sw.get('last_name', '')}").strip() or key
        conf = str(sw.get("identity_confidence") or "")
        rows.append(
            {
                "name": DataCell(name, name, provenance=Provenance.PARSED),
                "gender": DataCell(
                    sw.get("gender") or "", sw.get("gender") or "", provenance=Provenance.PARSED
                ),
                "age": DataCell(
                    sw.get("age_at_meet"),
                    str(sw.get("age_at_meet")) if sw.get("age_at_meet") else "",
                    provenance=Provenance.PARSED,
                ),
                "club": DataCell(
                    sw.get("club_name") or sw.get("club_code") or "",
                    sw.get("club_name") or sw.get("club_code") or "",
                    provenance=Provenance.PARSED,
                ),
                "asa_id": DataCell(
                    sw.get("asa_id") or "", sw.get("asa_id") or "", provenance=Provenance.PARSED
                ),
                "identity": DataCell(
                    conf,
                    conf,
                    provenance=Provenance.PARSED,
                    confidence=conf,
                    flagged=conf == "low",
                    note="Identity matched on name only." if conf == "low" else "",
                ),
            }
        )
    return DataTable(
        table_id=f"swimmers:{run_id}",
        title=f"Swimmers — {meet.get('name') or run_id}",
        kind="swimmers",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source=f"run {run_id}",
        description="Everyone who swam at this meet, as MediaHub identified them.",
    )


def clubs_table(
    profile_id: str, run_id: str, *, runs_dir: Optional[Path] = None
) -> Optional[DataTable]:
    data = _load_run(run_id, runs_dir)
    if not data:
        return None
    if profile_id and data.get("profile_id") not in (None, "", profile_id):
        return None
    meet = data.get("meet") or {}
    columns = [
        DataColumn("name", "Club", "text", frozen=True),
        DataColumn("code", "Code", "text"),
        DataColumn("is_host", "Host", "bool"),
        DataColumn("aliases", "Also seen as", "text"),
    ]
    rows: list[dict] = []
    for code, club in (meet.get("clubs") or {}).items():
        if not isinstance(club, dict):
            continue
        aliases = ", ".join(club.get("aliases") or [])
        rows.append(
            {
                "name": DataCell(
                    club.get("name") or code, club.get("name") or code, provenance=Provenance.PARSED
                ),
                "code": DataCell(code, code, provenance=Provenance.PARSED),
                "is_host": DataCell(
                    bool(club.get("is_host")),
                    "Yes" if club.get("is_host") else "No",
                    provenance=Provenance.PARSED,
                ),
                "aliases": DataCell(aliases, aliases, provenance=Provenance.PARSED),
            }
        )
    return DataTable(
        table_id=f"clubs:{run_id}",
        title=f"Clubs — {meet.get('name') or run_id}",
        kind="clubs",
        profile_id=profile_id,
        columns=columns,
        rows=rows,
        editable=False,
        source=f"run {run_id}",
        description="The clubs that took part in this meet.",
    )


# ---------------------------------------------------------------------------
# Registry / dispatcher
# ---------------------------------------------------------------------------


def get_canonical_table(
    profile_id: str,
    table_id: str,
    *,
    db_path: Optional[Path] = None,
    runs_dir: Optional[Path] = None,
) -> Optional[DataTable]:
    """Resolve a canonical ``table_id`` to its read-only :class:`DataTable`.

    Returns ``None`` for an unknown id or an org table (handled by ``store.py``).
    """
    tid = (table_id or "").strip()
    if tid == "athletes":
        return athletes_table(profile_id, db_path=db_path)
    if tid == "records":
        return records_table(profile_id, db_path=db_path)
    if tid == "meets":
        return meets_table(profile_id, runs_dir=runs_dir)
    if ":" in tid:
        kind, _, run_id = tid.partition(":")
        if kind == "results":
            return results_table(profile_id, run_id, runs_dir=runs_dir)
        if kind == "swimmers":
            return swimmers_table(profile_id, run_id, runs_dir=runs_dir)
        if kind == "clubs":
            return clubs_table(profile_id, run_id, runs_dir=runs_dir)
    return None


def list_canonical_tables(
    profile_id: str,
    *,
    db_path: Optional[Path] = None,
    runs_dir: Optional[Path] = None,
) -> list[dict]:
    """Summaries of the canonical tables available to ``profile_id``.

    The three singletons (athletes, records, meets) always appear; per-run
    result tables appear for the most recent runs.
    """
    out: list[dict] = [
        athletes_table(profile_id, db_path=db_path).summary(),
        records_table(profile_id, db_path=db_path).summary(),
        meets_table(profile_id, runs_dir=runs_dir).summary(),
    ]
    for run_id, data in _iter_profile_runs(profile_id, runs_dir=runs_dir, cap=_RECENT_RUNS_CAP):
        meet = data.get("meet") or {}
        name = meet.get("name") or data.get("file_name") or run_id
        n_results = len(meet.get("results") or [])
        out.append(
            {
                "table_id": f"results:{run_id}",
                "title": f"Results — {name}",
                "kind": "results",
                "editable": False,
                "n_columns": 8,
                "n_rows": n_results,
                "n_flagged": 0,
                "n_warnings": len(meet.get("warnings") or []),
                "source": f"run {run_id}",
            }
        )
    return out


__all__ = [
    "athletes_table",
    "records_table",
    "meets_table",
    "results_table",
    "swimmers_table",
    "clubs_table",
    "get_canonical_table",
    "list_canonical_tables",
]
