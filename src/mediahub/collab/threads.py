"""collab/threads.py — anchored review comments, tasks & reactions (roadmap 1.18).

The review layer's conversation store: threaded comments anchored to a run, a
card, or a named element on a card ("the sponsor strip"); @mentions; emoji
reactions; and **tasks** — a comment flavour with an assignee that blocks the
card's approval until it's resolved ("check lane-4 name before this goes out").

This is review *metadata*, not engine state — deterministic CRUD, no AI and no
heuristics. It lives beside :mod:`mediahub.workflow.review_comments` (the
Frame.io-style time-anchored reel markers) and shares the same ``data.db``,
following its conventions exactly: a short-lived connection per call with the
web layer's ``busy_timeout``, an idempotent ``init_schema``, parameterised
queries throughout, a ``db_path`` override on every function for tests, and a
``delete_for_run`` the erasure cascade calls so the thread never outlives the
run it annotates.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# Bounds — a note, not an essay; a club's reviewers, not a public wall.
MAX_BODY_LEN = 4000
MAX_NAME_LEN = 120
MAX_ANCHOR_LEN = 200
MAX_EMAIL_LEN = 254
MAX_MENTIONS = 50
MAX_COMMENTS_PER_CARD = 1000
MAX_EMOJI_LEN = 16

KIND_COMMENT = "comment"
KIND_TASK = "task"
_KINDS = {KIND_COMMENT, KIND_TASK}


class ThreadError(ValueError):
    """Invalid comment/task input (empty body, over a limit, bad parent)."""


@dataclass
class CollabComment:
    """One comment or task in a review thread."""

    id: str
    run_id: str
    card_id: str
    anchor: str
    thread_id: str
    parent_id: str
    kind: str
    body: str
    author_email: str
    author_name: str
    assignee_email: str
    mentions: list[str]
    resolved: bool
    created_at: float
    updated_at: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resolved"] = bool(self.resolved)
        d["mentions"] = list(self.mentions or [])
        return d

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "CollabComment":
        try:
            mentions = json.loads(row["mentions"] or "[]")
            if not isinstance(mentions, list):
                mentions = []
        except (json.JSONDecodeError, TypeError):
            mentions = []
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            card_id=row["card_id"] or "",
            anchor=row["anchor"] or "",
            thread_id=row["thread_id"],
            parent_id=row["parent_id"] or "",
            kind=row["kind"] or KIND_COMMENT,
            body=row["body"],
            author_email=row["author_email"] or "",
            author_name=row["author_name"] or "",
            assignee_email=row["assignee_email"] or "",
            mentions=[str(m) for m in mentions],
            resolved=bool(row["resolved"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def _default_db_path() -> Path:
    base = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))
    return base / "data.db"


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
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
    """Create the comments + reactions tables and lookup indexes (idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collab_comments (
            id              TEXT PRIMARY KEY,
            run_id          TEXT NOT NULL,
            card_id         TEXT NOT NULL DEFAULT '',
            anchor          TEXT NOT NULL DEFAULT '',
            thread_id       TEXT NOT NULL,
            parent_id       TEXT NOT NULL DEFAULT '',
            kind            TEXT NOT NULL DEFAULT 'comment',
            body            TEXT NOT NULL,
            author_email    TEXT NOT NULL DEFAULT '',
            author_name     TEXT NOT NULL DEFAULT '',
            assignee_email  TEXT NOT NULL DEFAULT '',
            mentions        TEXT NOT NULL DEFAULT '[]',
            resolved        INTEGER NOT NULL DEFAULT 0,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_collab_comments_run_card
            ON collab_comments(run_id, card_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_collab_comments_thread
            ON collab_comments(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_collab_comments_open_tasks
            ON collab_comments(run_id, kind, resolved);

        CREATE TABLE IF NOT EXISTS collab_reactions (
            comment_id      TEXT NOT NULL,
            emoji           TEXT NOT NULL,
            author_email    TEXT NOT NULL,
            created_at      REAL NOT NULL,
            PRIMARY KEY (comment_id, emoji, author_email)
        );
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


def _clean_body(body: Optional[str]) -> str:
    if not isinstance(body, str):
        raise ThreadError("comment body must be text")
    b = body.strip()
    if not b:
        raise ThreadError("comment body is empty")
    if len(b) > MAX_BODY_LEN:
        raise ThreadError(f"comment body exceeds {MAX_BODY_LEN} characters")
    return b


def _clean_email(email: Optional[str]) -> str:
    e = (email or "").strip().lower()
    return e[:MAX_EMAIL_LEN]


def _clean_mentions(mentions) -> list[str]:
    if not mentions:
        return []
    out: list[str] = []
    for m in mentions:
        e = _clean_email(str(m))
        if e and e not in out:
            out.append(e)
        if len(out) >= MAX_MENTIONS:
            break
    return out


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def add_comment(
    run_id: str,
    card_id: Optional[str],
    body: Optional[str],
    *,
    author_email: Optional[str] = None,
    author_name: Optional[str] = None,
    anchor: Optional[str] = None,
    parent_id: Optional[str] = None,
    kind: str = KIND_COMMENT,
    assignee_email: Optional[str] = None,
    mentions=None,
    db_path: Optional[Path] = None,
) -> CollabComment:
    """Add a comment, reply, or task. Raises ``ThreadError`` on bad input.

    A reply (``parent_id`` set) inherits its root's ``thread_id`` and must live
    under the same run. A task (``kind='task'``) starts unresolved and blocks
    the card's approval until resolved.
    """
    if not (run_id or "").strip():
        raise ThreadError("run_id is required")
    body = _clean_body(body)
    kind = (kind or KIND_COMMENT).strip().lower()
    if kind not in _KINDS:
        kind = KIND_COMMENT
    card_id = (card_id or "").strip()
    anchor = (anchor or "").strip()[:MAX_ANCHOR_LEN]
    author_email = _clean_email(author_email)
    author_name = (author_name or "").strip()[:MAX_NAME_LEN]
    assignee_email = _clean_email(assignee_email)
    mention_list = _clean_mentions(mentions)
    now = time.time()
    cid = uuid.uuid4().hex

    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        thread_id = cid
        parent = (parent_id or "").strip()
        if parent:
            prow = conn.execute(
                "SELECT run_id, thread_id FROM collab_comments WHERE id=?", (parent,)
            ).fetchone()
            if prow is None or prow["run_id"] != run_id:
                raise ThreadError("parent comment not found in this run")
            thread_id = prow["thread_id"]
            # A reply takes its root's card so the whole thread stays on one card.
            crow = conn.execute(
                "SELECT card_id, anchor FROM collab_comments WHERE id=?", (thread_id,)
            ).fetchone()
            if crow is not None:
                card_id = crow["card_id"] or card_id
                anchor = anchor or (crow["anchor"] or "")
        else:
            parent = ""

        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM collab_comments WHERE run_id=? AND card_id=?",
            (run_id, card_id),
        ).fetchone()
        if int(cnt["c"]) >= MAX_COMMENTS_PER_CARD:
            raise ThreadError("too many comments on this card")

        conn.execute(
            "INSERT INTO collab_comments"
            "(id,run_id,card_id,anchor,thread_id,parent_id,kind,body,author_email,"
            "author_name,assignee_email,mentions,resolved,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (
                cid,
                run_id,
                card_id,
                anchor,
                thread_id,
                parent,
                kind,
                body,
                author_email,
                author_name,
                assignee_email,
                json.dumps(mention_list),
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return CollabComment(
        cid,
        run_id,
        card_id,
        anchor,
        thread_id,
        parent,
        kind,
        body,
        author_email,
        author_name,
        assignee_email,
        mention_list,
        False,
        now,
        now,
    )


def set_resolved(
    comment_id: str,
    resolved: bool,
    *,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[CollabComment]:
    """Resolve / reopen a thread, or mark a task done / not-done."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        where = "id=?"
        params: list = [1 if resolved else 0, time.time(), comment_id]
        if run_id is not None:
            where += " AND run_id=?"
            params.append(run_id)
        cur = conn.execute(
            f"UPDATE collab_comments SET resolved=?, updated_at=? WHERE {where}", params
        )
        conn.commit()
        if not cur.rowcount:
            return None
    finally:
        conn.close()
    return get_comment(comment_id, db_path=db_path)


def edit_body(
    comment_id: str,
    body: Optional[str],
    *,
    run_id: Optional[str] = None,
    author_email: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Optional[CollabComment]:
    """Edit a comment's body. ``author_email``, when given, scopes the edit to
    the comment's author (so one member can't rewrite another's words)."""
    body = _clean_body(body)
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        where = "id=?"
        params: list = [body, time.time(), comment_id]
        if run_id is not None:
            where += " AND run_id=?"
            params.append(run_id)
        if author_email is not None:
            where += " AND author_email=?"
            params.append(_clean_email(author_email))
        cur = conn.execute(f"UPDATE collab_comments SET body=?, updated_at=? WHERE {where}", params)
        conn.commit()
        if not cur.rowcount:
            return None
    finally:
        conn.close()
    return get_comment(comment_id, db_path=db_path)


def delete_comment(
    comment_id: str,
    *,
    run_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Delete a comment. Deleting a thread root removes its whole thread (and the
    reactions on every comment removed). Returns the number of comments removed."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, thread_id, parent_id FROM collab_comments WHERE id=?", (comment_id,)
        ).fetchone()
        if row is None:
            return 0
        if run_id is not None:
            owns = conn.execute(
                "SELECT 1 FROM collab_comments WHERE id=? AND run_id=?", (comment_id, run_id)
            ).fetchone()
            if owns is None:
                return 0
        # A root (parent_id == '') takes the whole thread with it.
        if not (row["parent_id"] or ""):
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM collab_comments WHERE thread_id=?", (row["thread_id"],)
                ).fetchall()
            ]
        else:
            ids = [comment_id]
        qmarks = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM collab_reactions WHERE comment_id IN ({qmarks})", ids)
        cur = conn.execute(f"DELETE FROM collab_comments WHERE id IN ({qmarks})", ids)
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_comment(comment_id: str, *, db_path: Optional[Path] = None) -> Optional[CollabComment]:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM collab_comments WHERE id=?", (comment_id,)).fetchone()
    finally:
        conn.close()
    return CollabComment._from_row(row) if row else None


def list_for_card(
    run_id: str,
    card_id: Optional[str] = None,
    *,
    include_resolved: bool = True,
    db_path: Optional[Path] = None,
) -> list[CollabComment]:
    """All comments for a card (or the whole run when ``card_id`` is None),
    oldest-first so a thread reads top-to-bottom."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT * FROM collab_comments WHERE run_id=?"
        params: list = [run_id]
        if card_id is not None:
            q += " AND card_id=?"
            params.append((card_id or "").strip())
        if not include_resolved:
            q += " AND resolved=0"
        q += " ORDER BY created_at ASC, rowid ASC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    return [CollabComment._from_row(r) for r in rows]


def open_task_count(
    run_id: str,
    card_id: Optional[str] = None,
    *,
    db_path: Optional[Path] = None,
) -> int:
    """Unresolved tasks for a card (or the whole run). The approval gate calls
    this — an open task holds the card in QUEUE until it's ticked off."""
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT COUNT(*) AS c FROM collab_comments WHERE run_id=? AND kind=? AND resolved=0"
        params: list = [run_id, KIND_TASK]
        if card_id is not None:
            q += " AND card_id=?"
            params.append((card_id or "").strip())
        row = conn.execute(q, params).fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


def count_for_card(
    run_id: str,
    card_id: Optional[str] = None,
    *,
    include_resolved: bool = True,
    db_path: Optional[Path] = None,
) -> int:
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        q = "SELECT COUNT(*) AS c FROM collab_comments WHERE run_id=?"
        params: list = [run_id]
        if card_id is not None:
            q += " AND card_id=?"
            params.append((card_id or "").strip())
        if not include_resolved:
            q += " AND resolved=0"
        row = conn.execute(q, params).fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


def delete_for_run(run_id: str, *, db_path: Optional[Path] = None) -> int:
    """Drop every comment, task and reaction for a run — the erasure cascade
    calls this so review threads never outlive the run. Returns comments removed."""
    if not (run_id or "").strip():
        return 0
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM collab_comments WHERE run_id=?", (run_id,)
            ).fetchall()
        ]
        if ids:
            qmarks = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM collab_reactions WHERE comment_id IN ({qmarks})", ids)
        cur = conn.execute("DELETE FROM collab_comments WHERE run_id=?", (run_id,))
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


def toggle_reaction(
    comment_id: str,
    emoji: Optional[str],
    author_email: Optional[str],
    *,
    db_path: Optional[Path] = None,
) -> bool:
    """Add or remove one reaction. Returns True when it's now ON, False when
    removed (or the comment doesn't exist). Distinct per (comment, emoji, user)."""
    emoji = (emoji or "").strip()[:MAX_EMOJI_LEN]
    author = _clean_email(author_email)
    if not emoji or not author:
        raise ThreadError("emoji and author are required")
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        exists = conn.execute("SELECT 1 FROM collab_comments WHERE id=?", (comment_id,)).fetchone()
        if exists is None:
            return False
        already = conn.execute(
            "SELECT 1 FROM collab_reactions WHERE comment_id=? AND emoji=? AND author_email=?",
            (comment_id, emoji, author),
        ).fetchone()
        if already:
            conn.execute(
                "DELETE FROM collab_reactions WHERE comment_id=? AND emoji=? AND author_email=?",
                (comment_id, emoji, author),
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO collab_reactions(comment_id,emoji,author_email,created_at) "
            "VALUES(?,?,?,?)",
            (comment_id, emoji, author, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reactions_for(
    comment_ids, *, db_path: Optional[Path] = None
) -> dict[str, dict[str, list[str]]]:
    """Batch-load reactions for several comments → ``{comment_id: {emoji: [emails]}}``."""
    ids = [c for c in (comment_ids or []) if c]
    if not ids:
        return {}
    _ensure_schema(db_path)
    conn = _connect(db_path)
    try:
        qmarks = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT comment_id, emoji, author_email FROM collab_reactions "
            f"WHERE comment_id IN ({qmarks}) ORDER BY created_at ASC",
            ids,
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        out.setdefault(r["comment_id"], {}).setdefault(r["emoji"], []).append(r["author_email"])
    return out


__all__ = [
    "CollabComment",
    "ThreadError",
    "KIND_COMMENT",
    "KIND_TASK",
    "init_schema",
    "add_comment",
    "set_resolved",
    "edit_body",
    "delete_comment",
    "get_comment",
    "list_for_card",
    "open_task_count",
    "count_for_card",
    "delete_for_run",
    "toggle_reaction",
    "reactions_for",
]
