"""Timestamp-anchored reel review comments (UI 1.8 — Frame.io-style).

A reviewer scrubbing a generated reel (or a single story card) in the
content-builder review surface can pin a feedback marker to a specific
moment in the video. Each marker carries the playhead time, the note body,
and who left it; markers are stored per run/target in the shared SQLite
database and replayed as overlays on the video scrubber.

This is review *metadata*, not engine state — deterministic CRUD, no AI and
no heuristics. It lives in the ``workflow`` package beside the other
review/approval stores and shares the same ``data.db`` the scheduler uses.

Conventions mirror ``workflow/schedule.py``: a short-lived connection per
call with the same ``busy_timeout`` web.py uses, an idempotent
``init_schema``, parameterised queries throughout, and a ``db_path``
override on every function so tests run against a temp database.
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Bounds — keep a single marker sane and stop a runaway/abusive client from
# unbounding the row or the table. These are deliberately generous: a note,
# not an essay; a club's reviewers, not a public comment wall.
MAX_BODY_LEN = 2000
MAX_AUTHOR_LEN = 120
MAX_TARGET_LEN = 200
# 6 hours — far beyond any reel (the longest cut is ~23s) but a hard ceiling
# so a bogus timestamp can't be stored as a 9e18 integer.
MAX_TIME_MS = 6 * 60 * 60 * 1000
MAX_COMMENTS_PER_TARGET = 500

DEFAULT_AUTHOR = "Reviewer"
# The canonical target for the meet reel. Single story cards use
# ``card:<card_id>`` so one run's markers stay separated per video.
REEL_TARGET = "reel"


class ReelCommentError(ValueError):
    """Invalid comment input (empty body, bad timestamp, over a limit)."""


@dataclass
class ReelComment:
    """One timestamp-anchored review marker on a generated video."""

    id: str
    run_id: str
    target: str
    t_ms: int
    body: str
    author: str
    resolved: bool
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["t_ms"] = int(self.t_ms)
        d["resolved"] = bool(self.resolved)
        return d

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "ReelComment":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            target=row["target"],
            t_ms=int(row["t_ms"]),
            body=row["body"],
            author=row["author"],
            resolved=bool(row["resolved"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    """The shared ``data.db`` under the live ``DATA_DIR``.

    Resolved at call time (not frozen at import) so a late ``DATA_DIR`` or a
    test monkeypatch is honoured — matching the privacy/erasure and autonomy
    ledgers rather than the import-time freeze the scheduler uses.
    """
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a short-lived connection with the same busy_timeout web.py uses,
    so two workers racing a write wait briefly rather than erroring."""
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create the comments table + lookup index (idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reel_review_comments (
            id          TEXT PRIMARY KEY,
            run_id      TEXT NOT NULL,
            target      TEXT NOT NULL DEFAULT 'reel',
            t_ms        INTEGER NOT NULL DEFAULT 0,
            body        TEXT NOT NULL,
            author      TEXT NOT NULL DEFAULT 'Reviewer',
            resolved    INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reel_comments_run_target
            ON reel_review_comments(run_id, target, t_ms);
        """
    )
    conn.commit()


def _ensure_schema(db_path: Optional[Path] = None) -> None:
    conn = _connect(db_path)
    try:
        init_schema(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _clean_target(target: Optional[str]) -> str:
    if target is None:
        return REEL_TARGET
    if not isinstance(target, str):
        raise ReelCommentError("target must be text")
    t = target.strip() or REEL_TARGET
    if len(t) > MAX_TARGET_LEN:
        raise ReelCommentError("target is too long")
    return t


def _clean_body(body: Optional[str]) -> str:
    if not isinstance(body, str):
        raise ReelCommentError("comment body must be text")
    b = body.strip()
    if not b:
        raise ReelCommentError("comment body is empty")
    if len(b) > MAX_BODY_LEN:
        raise ReelCommentError(f"comment body exceeds {MAX_BODY_LEN} characters")
    return b


def _clean_author(author: Optional[str]) -> str:
    if not isinstance(author, str):
        return DEFAULT_AUTHOR
    return (author.strip() or DEFAULT_AUTHOR)[:MAX_AUTHOR_LEN]


def _clean_time_ms(t_ms) -> int:
    # bool is an int subclass — reject it so a stray ``true`` isn't read as 1ms.
    if isinstance(t_ms, bool):
        raise ReelCommentError("t_ms must be a number")
    try:
        f = float(t_ms)
    except (TypeError, ValueError):
        raise ReelCommentError("t_ms must be a number") from None
    # inf/nan (e.g. JSON ``1e400`` parses to inf) would blow up int(round(...)).
    if not math.isfinite(f):
        raise ReelCommentError("t_ms must be a finite number")
    v = int(round(f))
    if v < 0:
        raise ReelCommentError("t_ms must be >= 0")
    if v > MAX_TIME_MS:
        raise ReelCommentError("t_ms is out of range")
    return v


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def add_comment(
    run_id: str,
    target: Optional[str],
    t_ms,
    body: Optional[str],
    author: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> ReelComment:
    """Pin a new review marker. Raises ``ReelCommentError`` on bad input."""
    if not (run_id or "").strip():
        raise ReelCommentError("run_id is required")
    tgt = _clean_target(target)
    ts = _clean_time_ms(t_ms)
    bd = _clean_body(body)
    au = _clean_author(author)
    now = time.time()
    cid = uuid.uuid4().hex

    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM reel_review_comments WHERE run_id=? AND target=?",
            (run_id, tgt),
        ).fetchone()
        if int(row["c"]) >= MAX_COMMENTS_PER_TARGET:
            raise ReelCommentError("too many comments on this reel")
        conn.execute(
            "INSERT INTO reel_review_comments"
            "(id,run_id,target,t_ms,body,author,resolved,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (cid, run_id, tgt, ts, bd, au, 0, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return ReelComment(cid, run_id, tgt, ts, bd, au, False, now, now)


def list_comments(
    run_id: str,
    target: Optional[str] = None,
    *,
    include_resolved: bool = True,
    db_path: Optional[Path] = None,
) -> list[ReelComment]:
    """All markers for a run, optionally narrowed to one ``target``.

    Ordered by timestamp so the scrubber overlay and the list read the same
    way the video plays.
    """
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT * FROM reel_review_comments WHERE run_id=?"
        params: list = [run_id]
        if target is not None:
            q += " AND target=?"
            params.append(_clean_target(target))
        if not include_resolved:
            q += " AND resolved=0"
        q += " ORDER BY t_ms ASC, created_at ASC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    return [ReelComment._from_row(r) for r in rows]


def get_comment(comment_id: str, *, db_path: Optional[Path] = None) -> Optional[ReelComment]:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM reel_review_comments WHERE id=?", (comment_id,)
        ).fetchone()
    finally:
        conn.close()
    return ReelComment._from_row(row) if row else None


def update_comment(
    comment_id: str,
    *,
    body: Optional[str] = None,
    resolved: Optional[bool] = None,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[ReelComment]:
    """Edit the body and/or flip the resolved flag.

    ``run_id``, when given, scopes the update so a comment id can only be
    mutated under the run it belongs to. Returns the updated row, or ``None``
    when nothing matched.
    """
    sets: list[str] = []
    params: list = []
    if body is not None:
        sets.append("body=?")
        params.append(_clean_body(body))
    if resolved is not None:
        sets.append("resolved=?")
        params.append(1 if resolved else 0)
    if not sets:
        return get_comment(comment_id, db_path=db_path)
    sets.append("updated_at=?")
    params.append(time.time())

    where = "id=?"
    params.append(comment_id)
    if run_id is not None:
        where += " AND run_id=?"
        params.append(run_id)

    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            f"UPDATE reel_review_comments SET {', '.join(sets)} WHERE {where}", params
        )
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()
    if not changed:
        return None
    return get_comment(comment_id, db_path=db_path)


def delete_comment(
    comment_id: str, *, run_id: Optional[str] = None, db_path: Optional[Path] = None
) -> bool:
    """Remove one marker. ``run_id`` scopes the delete the same way
    ``update_comment`` does. Returns whether a row was removed."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        if run_id is not None:
            cur = conn.execute(
                "DELETE FROM reel_review_comments WHERE id=? AND run_id=?",
                (comment_id, run_id),
            )
        else:
            cur = conn.execute("DELETE FROM reel_review_comments WHERE id=?", (comment_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_comments(
    run_id: str,
    target: Optional[str] = None,
    *,
    include_resolved: bool = True,
    db_path: Optional[Path] = None,
) -> int:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT COUNT(*) AS c FROM reel_review_comments WHERE run_id=?"
        params: list = [run_id]
        if target is not None:
            q += " AND target=?"
            params.append(_clean_target(target))
        if not include_resolved:
            q += " AND resolved=0"
        row = conn.execute(q, params).fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


def delete_comments_for_run(run_id: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every marker for a run — the erasure cascade calls this so the
    review ledger never outlives the run it annotates. Returns rows removed."""
    if not (run_id or "").strip():
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM reel_review_comments WHERE run_id=?", (run_id,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
