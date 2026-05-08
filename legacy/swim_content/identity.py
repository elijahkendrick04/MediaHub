"""
Swimmer identity resolution.

Goal: take a parsed (name, gender, club) tuple from a meet file and resolve
it to a stable internal swimmer_id. Never create duplicates from name typos.
"""

from __future__ import annotations
import json
import sqlite3
from rapidfuzz import fuzz, process


def _normalise(name: str) -> str:
    return " ".join(name.replace(",", " ").split()).strip().lower()


def resolve_or_create(conn: sqlite3.Connection, name: str, gender: str | None,
                      club_id: int | None, threshold: int = 88) -> int:
    """Return swimmer.id, creating a row if no good match exists."""
    norm = _normalise(name)
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, display_name, aka_json, gender, club_id FROM swimmer"
    ).fetchall()

    candidates = []
    for r in rows:
        if club_id and r[4] and r[4] != club_id:
            continue
        if gender and r[3] and r[3] != gender:
            continue
        names = [r[1]] + json.loads(r[2] or "[]")
        for n in names:
            score = fuzz.token_sort_ratio(norm, _normalise(n))
            candidates.append((score, r[0], n))
    candidates.sort(reverse=True)

    if candidates and candidates[0][0] >= threshold:
        sid = candidates[0][1]
        # remember alias if it's a new spelling
        existing_names = cur.execute(
            "SELECT display_name, aka_json FROM swimmer WHERE id=?", (sid,)
        ).fetchone()
        all_names = {existing_names[0]} | set(json.loads(existing_names[1] or "[]"))
        if name not in all_names:
            all_names.add(name)
            new_aka = json.dumps(sorted(all_names - {existing_names[0]}))
            cur.execute("UPDATE swimmer SET aka_json=? WHERE id=?", (new_aka, sid))
            conn.commit()
        return sid

    cur.execute(
        "INSERT INTO swimmer (display_name, gender, club_id, aka_json) VALUES (?,?,?,?)",
        (name, gender, club_id, "[]"),
    )
    conn.commit()
    return cur.lastrowid
