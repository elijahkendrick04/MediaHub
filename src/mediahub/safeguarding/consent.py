"""Consent registry + deterministic enforcement policy (W.2).

Levels (single axis, most→least permissive):

    full           photo OK, full name OK
    no_photo       full name OK, never use a photo
    initials_only  initials only, never use a photo
    do_not_feature never feature this athlete in content

An athlete with no record is "unknown". While a workspace has no consent
regime (zero records, enforcement off) unknown athletes behave as
``full`` — the legacy behaviour, so day-zero clubs aren't blanked. The
moment a regime exists, unknown collapses to most-restrictive
(``do_not_feature``) with the reason "no consent on file".
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mediahub.athletes.registry import (
    get_or_create,
    initials_of,
    list_athletes,
    resolve,
)

log = logging.getLogger(__name__)

LEVELS = ("full", "no_photo", "initials_only", "do_not_feature")

LEVEL_LABELS = {
    "full": "Photo + name OK",
    "no_photo": "Name OK, no photos",
    "initials_only": "Initials only, no photos",
    "do_not_feature": "Do not feature",
    "unknown": "No consent on file",
}


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
CREATE TABLE IF NOT EXISTS athlete_consent (
    profile_id TEXT NOT NULL,
    athlete_id TEXT NOT NULL,
    level      TEXT NOT NULL,
    note       TEXT,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (profile_id, athlete_id)
);
CREATE TABLE IF NOT EXISTS consent_settings (
    profile_id TEXT PRIMARY KEY,
    enforce    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
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


def _audit(profile_id: str, kind: str, args: dict, result: str) -> None:
    try:
        from mediahub.workflow.autonomy import AuditLog

        AuditLog().record(
            profile_id,
            f"consent:{args.get('athlete_id', '-')}",
            kind,
            tool="safeguarding.consent",
            args=args,
            result=result,
        )
    except Exception:  # audit is best-effort, never blocks the change
        log.warning("consent audit failed", exc_info=True)


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------


def set_consent(
    profile_id: str,
    athlete_id: str,
    level: str,
    *,
    actor: str = "",
    note: str = "",
    db_path: Optional[Path] = None,
) -> bool:
    if level not in LEVELS:
        raise ValueError(f"unknown consent level: {level!r}")
    if not profile_id or not athlete_id:
        return False
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO athlete_consent (profile_id, athlete_id, level, note,"
            " updated_at, updated_by) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(profile_id, athlete_id) DO UPDATE SET"
            " level = excluded.level, note = excluded.note,"
            " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
            (profile_id, athlete_id, level, note or None, _now(), actor or None),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(
        profile_id,
        "consent_change",
        {"athlete_id": athlete_id, "level": level, "actor": actor},
        f"set {level}",
    )
    return True


def set_consent_many(
    profile_id: str,
    athlete_ids: list[str],
    level: str,
    *,
    actor: str = "",
    note: str = "",
    db_path: Optional[Path] = None,
) -> int:
    """All-or-nothing bulk upsert (CON2-4): ONE connection, ONE transaction.

    A per-id ``set_consent`` loop commits each row separately, so a failure
    mid-way leaves the roster half-updated while the UI reports a clean
    failure. Here the whole batch commits together — on any failure the
    transaction rolls back, nothing is written, and the error re-raises.
    Returns the number of rows upserted.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown consent level: {level!r}")
    ids = [str(a).strip() for a in athlete_ids if str(a).strip()]
    if not profile_id or not ids:
        return 0
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN")
        for athlete_id in ids:
            conn.execute(
                "INSERT INTO athlete_consent (profile_id, athlete_id, level, note,"
                " updated_at, updated_by) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(profile_id, athlete_id) DO UPDATE SET"
                " level = excluded.level, note = excluded.note,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (profile_id, athlete_id, level, note or None, _now(), actor or None),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for athlete_id in ids:
        _audit(
            profile_id,
            "consent_change",
            {"athlete_id": athlete_id, "level": level, "actor": actor},
            f"set {level}",
        )
    return len(ids)


def get_consent(profile_id: str, athlete_id: str, db_path: Optional[Path] = None) -> Optional[str]:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT level FROM athlete_consent WHERE profile_id = ? AND athlete_id = ?",
            (profile_id, athlete_id),
        ).fetchone()
        return row["level"] if row else None
    finally:
        conn.close()


def list_consent(profile_id: str, db_path: Optional[Path] = None) -> dict[str, dict]:
    """``{athlete_id: {"level", "note", "updated_at", "updated_by"}}``."""
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        return {
            r["athlete_id"]: {
                "level": r["level"],
                "note": r["note"] or "",
                "updated_at": r["updated_at"],
                "updated_by": r["updated_by"] or "",
            }
            for r in conn.execute(
                "SELECT * FROM athlete_consent WHERE profile_id = ?", (profile_id,)
            ).fetchall()
        }
    finally:
        conn.close()


def set_enforce(
    profile_id: str, enforce: bool, *, actor: str = "", db_path: Optional[Path] = None
) -> None:
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO consent_settings (profile_id, enforce, updated_at)"
            " VALUES (?,?,?) ON CONFLICT(profile_id) DO UPDATE SET"
            " enforce = excluded.enforce, updated_at = excluded.updated_at",
            (profile_id, 1 if enforce else 0, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    _audit(
        profile_id,
        "consent_enforce",
        {"athlete_id": "-", "enforce": enforce, "actor": actor},
        f"enforcement {'on' if enforce else 'off'}",
    )


def regime_active(profile_id: str, db_path: Optional[Path] = None) -> bool:
    """True when the workspace runs a consent regime: enforcement switched
    on, or at least one consent record on file."""
    if not profile_id:
        return False
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT enforce FROM consent_settings WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        if row and row["enforce"]:
            return True
        any_row = conn.execute(
            "SELECT 1 FROM athlete_consent WHERE profile_id = ? LIMIT 1", (profile_id,)
        ).fetchone()
        return any_row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The enforcement policy — deterministic, consumed by pack builder + gate
# ---------------------------------------------------------------------------


@dataclass
class ConsentPolicy:
    level: str  # one of LEVELS or "unknown"
    display_name: str  # what content may call the athlete
    name_ok: bool
    photo_ok: bool
    blocked: bool  # True → the athlete must not be featured at all
    reason: str
    athlete_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "display_name": self.display_name,
            "name_ok": self.name_ok,
            "photo_ok": self.photo_ok,
            "blocked": self.blocked,
            "reason": self.reason,
            "athlete_id": self.athlete_id,
        }


def effective_policy(
    profile_id: str, swimmer_name: str, db_path: Optional[Path] = None
) -> ConsentPolicy:
    """Resolve the enforceable policy for a swimmer name.

    No regime → permissive legacy behaviour. Regime active → the athlete's
    recorded level, or most-restrictive when unknown ("no consent on file").
    """
    name = (swimmer_name or "").strip()
    if not profile_id or not name:
        return ConsentPolicy("full", name, True, True, False, "")
    try:
        active = regime_active(profile_id, db_path)
    except sqlite3.Error:
        # Fail CLOSED: the normal no-regime path returns False (ensure_schema
        # runs first), so an error here is a genuine operational fault, not an
        # unconfigured workspace. A transient SQLITE_BUSY must never let a
        # do-not-feature / no-consent-on-file child be featured.
        log.error("consent lookup failed; blocking the athlete to stay safe", exc_info=True)
        return ConsentPolicy("unknown", "", False, False, True, "blocked: consent lookup failed")
    if not active:
        return ConsentPolicy("full", name, True, True, False, "")

    rec = resolve(profile_id, name, db_path)
    level = get_consent(profile_id, rec.athlete_id, db_path) if rec else None
    athlete_id = rec.athlete_id if rec else None

    if level == "full":
        return ConsentPolicy("full", name, True, True, False, "", athlete_id)
    if level == "no_photo":
        return ConsentPolicy(
            "no_photo", name, True, False, False, "photo consent not given", athlete_id
        )
    if level == "initials_only":
        return ConsentPolicy(
            "initials_only",
            initials_of(name) or name[:1].upper() + ".",
            True,
            False,
            False,
            "initials-only consent",
            athlete_id,
        )
    if level == "do_not_feature":
        return ConsentPolicy(
            "do_not_feature",
            "",
            False,
            False,
            True,
            "blocked: athlete is marked do-not-feature",
            athlete_id,
        )
    # Unknown under an active regime → most restrictive.
    return ConsentPolicy(
        "unknown",
        "",
        False,
        False,
        True,
        "blocked: no consent on file",
        athlete_id,
    )


# ---------------------------------------------------------------------------
# CSV import / welfare-officer export
# ---------------------------------------------------------------------------

_CSV_LEVEL_ALIASES = {
    "full": "full",
    "photo": "full",
    "photo ok": "full",
    "yes": "full",
    "no photo": "no_photo",
    "no_photo": "no_photo",
    "name only": "no_photo",
    "initials": "initials_only",
    "initials only": "initials_only",
    "initials_only": "initials_only",
    "do not feature": "do_not_feature",
    "do_not_feature": "do_not_feature",
    "none": "do_not_feature",
    "no": "do_not_feature",
}


def import_csv(
    profile_id: str,
    text: str,
    *,
    actor: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Import ``name,level[,note]`` rows from the club's own records.

    Unknown names create registry athletes (source ``manual``); rows with
    unrecognised levels are reported, never guessed.
    """
    ok, skipped = 0, []
    reader = csv.reader(io.StringIO(text or ""))
    for i, row in enumerate(reader, start=1):
        if not row or not (row[0] or "").strip():
            continue
        name = row[0].strip()
        if i == 1 and name.lower() in ("name", "athlete", "swimmer"):
            continue  # header row
        raw_level = row[1].strip().lower() if len(row) > 1 else ""
        level = _CSV_LEVEL_ALIASES.get(raw_level)
        if level is None:
            skipped.append({"row": i, "name": name, "reason": f"unrecognised level {raw_level!r}"})
            continue
        note = row[2].strip() if len(row) > 2 else ""
        rec = get_or_create(profile_id, name, source="manual", db_path=db_path)
        if rec is None:
            skipped.append({"row": i, "name": name, "reason": "unusable name"})
            continue
        set_consent(
            profile_id,
            rec.athlete_id,
            level,
            actor=actor or "csv-import",
            note=note,
            db_path=db_path,
        )
        ok += 1
    return {"imported": ok, "skipped": skipped}


def _csv_safe(value) -> str:
    """Neutralise CSV formula injection at export time: a cell beginning with
    ``=``, ``+``, ``-``, ``@`` or a leading tab/CR is executed as a formula when
    the sheet is opened in Excel/Sheets. Prefix a single quote so an athlete
    name or free-text note can't run as a formula. Export-only — stored values
    are untouched."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(profile_id: str, db_path: Optional[Path] = None) -> str:
    """Welfare-officer export: every active athlete with consent state,
    including athletes with no record (state ``unknown``)."""
    consent = list_consent(profile_id, db_path)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "consent_level", "note", "updated_at", "updated_by"])
    for rec in list_athletes(profile_id, db_path):
        row = consent.get(rec.athlete_id)
        if row:
            w.writerow(
                _csv_safe(c)
                for c in (
                    rec.canonical_name,
                    row["level"],
                    row["note"],
                    row["updated_at"],
                    row["updated_by"],
                )
            )
        else:
            w.writerow([_csv_safe(rec.canonical_name), "unknown", "", "", ""])
    return buf.getvalue()
