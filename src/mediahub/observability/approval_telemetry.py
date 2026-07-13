"""Approval telemetry — W.14 phase 1 (no external APIs).

Records every approve / reject / edit decision made at the workflow seam,
per workspace, with the card's achievement type, post angle and tone.
``preference_summary`` turns that history into deterministic, explainable
"this club prefers…" signals for the planner and pack UI. The LLM never
ranks anything here.

Same SQLite conventions as the other Phase W stores (db_path injectable
for tests; org-scoped by profile_id).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
CREATE TABLE IF NOT EXISTS approval_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT NOT NULL,
    profile_id       TEXT NOT NULL,
    run_id           TEXT NOT NULL,
    card_id          TEXT NOT NULL,
    action           TEXT NOT NULL,
    achievement_type TEXT,
    post_angle       TEXT,
    tone             TEXT,
    quality_band     TEXT,
    via              TEXT,
    actor            TEXT
);
CREATE INDEX IF NOT EXISTS idx_approval_events_profile
    ON approval_events(profile_id, ts DESC);
"""

_ACTIONS = ("approved", "rejected", "edited", "requeued")


def ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        # Finding #116: the `actor` column was added after first ship; back-fill
        # it on pre-existing tables (CREATE TABLE IF NOT EXISTS won't add it).
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(approval_events)")}
        if "actor" not in cols:
            conn.execute("ALTER TABLE approval_events ADD COLUMN actor TEXT")
        conn.commit()
    finally:
        conn.close()


def record_event(
    profile_id: str,
    run_id: str,
    card_id: str,
    action: str,
    *,
    achievement_type: str = "",
    post_angle: str = "",
    tone: str = "",
    quality_band: str = "",
    via: str = "web",
    actor: str = "",
    db_path: Optional[Path] = None,
) -> bool:
    """Best-effort insert — telemetry must never block an approval.

    ``actor`` (finding #116) is the machine-distinguishable audit label of who
    made the change — a member's email, or ``api-token:<id>`` for a public-API /
    MCP action — so agent and human approvals can be told apart in the history.
    """
    if action not in _ACTIONS or not profile_id:
        return False
    try:
        ensure_schema(db_path)
        conn = _connect(db_path)
        try:
            conn.execute(
                "INSERT INTO approval_events (ts, profile_id, run_id, card_id, action,"
                " achievement_type, post_angle, tone, quality_band, via, actor)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    profile_id,
                    run_id,
                    card_id,
                    action,
                    achievement_type or None,
                    post_angle or None,
                    tone or None,
                    quality_band or None,
                    via or None,
                    actor or None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        log.warning("approval telemetry insert failed", exc_info=True)
        return False


def preference_summary(
    profile_id: str, *, min_events: int = 3, db_path: Optional[Path] = None
) -> dict:
    """Deterministic per-club preference profile from approval history.

    ``{"total_events", "angles": [...], "tones": [...], "reasons": [...]}``
    where each angle/tone row carries approved/rejected/edited counts and an
    approval rate over (approved+rejected). ``reasons`` are ready-made,
    explainable planner strings; only signals with ≥ ``min_events`` decided
    events are voiced.
    """
    ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT post_angle, achievement_type, tone, action, COUNT(*) AS n"
            " FROM approval_events WHERE profile_id = ?"
            " GROUP BY post_angle, achievement_type, tone, action",
            (profile_id,),
        ).fetchall()
    finally:
        conn.close()

    total = 0
    by_angle: dict[str, dict] = {}
    by_tone: dict[str, dict] = {}
    for r in rows:
        n = int(r["n"])
        total += n
        angle = r["post_angle"] or r["achievement_type"] or "unknown"
        a = by_angle.setdefault(angle, {"approved": 0, "rejected": 0, "edited": 0, "requeued": 0})
        a[r["action"]] = a.get(r["action"], 0) + n
        if r["tone"]:
            t = by_tone.setdefault(
                r["tone"], {"approved": 0, "rejected": 0, "edited": 0, "requeued": 0}
            )
            t[r["action"]] = t.get(r["action"], 0) + n

    def _rate(c: dict) -> Optional[float]:
        decided = c["approved"] + c["rejected"]
        return (c["approved"] / decided) if decided else None

    angles = [
        {"post_angle": k, **v, "approval_rate": _rate(v)} for k, v in sorted(by_angle.items())
    ]
    tones = [{"tone": k, **v, "approval_rate": _rate(v)} for k, v in sorted(by_tone.items())]

    reasons: list[str] = []
    for row in sorted(
        (a for a in angles if (a["approved"] + a["rejected"]) >= min_events),
        key=lambda a: (-(a["approval_rate"] or 0), a["post_angle"]),
    ):
        rate = row["approval_rate"]
        if rate is None:
            continue
        decided = row["approved"] + row["rejected"]
        label = row["post_angle"].replace("_", " ")
        if rate >= 0.75:
            reasons.append(
                f"This club approves {label} cards {rate:.0%} of the time "
                f"({row['approved']}/{decided})."
            )
        elif rate <= 0.25:
            reasons.append(
                f"This club usually rejects {label} cards ({row['rejected']}/{decided} rejected)."
            )
    for row in (t for t in tones if (t["approved"] + t["rejected"]) >= min_events):
        rate = row["approval_rate"]
        if rate is not None and rate >= 0.75:
            reasons.append(
                f"The {row['tone']} tone lands well here "
                f"({row['approved']}/{row['approved'] + row['rejected']} approved)."
            )

    return {"total_events": total, "angles": angles, "tones": tones, "reasons": reasons}
