"""
Online cross-reference layer.

Goal: enrich the canonical store using public sources so the detector has a
trustworthy PB baseline before it judges new meets. The intelligence layer
should NEVER rely on the meet file alone for PB truth.

Implemented sources (v1, designed for extension):
  * swimmingresults.org — Swim England individual best times lookup
    (cached aggressively; retried gracefully)

The functions below return parsed Python dicts. They never raise on network
failure — they return empty lists / None and log a warning so the pipeline
degrades gracefully if the user is offline.
"""

from __future__ import annotations
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .events import canonical_event, parse_time_to_cs

LOG = logging.getLogger("swim_content.crossref")
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
HEADERS = {
    "User-Agent": (
        "SwimContentBot/0.1 (+contact: elijahkendrick04@gmail.com) "
        "respectful-cache; identifies-itself"
    )
}
SWIM_ENGLAND_BASE = "https://www.swimmingresults.org"


def _cached_get(url: str, ttl_seconds: int = 60 * 60 * 24 * 7) -> Optional[str]:
    """Cache-aware GET. Returns body text or None."""
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", url)[:200]
    fp = CACHE_DIR / f"{safe}.html"
    if fp.exists() and (time.time() - fp.stat().st_mtime) < ttl_seconds:
        return fp.read_text(encoding="utf-8", errors="ignore")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            fp.write_text(r.text, encoding="utf-8")
            return r.text
        LOG.warning("cross-ref %s -> %s", url, r.status_code)
        return None
    except Exception as e:
        LOG.warning("cross-ref network error: %s", e)
        return None


# ------------------------------------------------------------------
# Swim England — Individual Best Times
# ------------------------------------------------------------------
# Public URL pattern (observed): /individualbest/personal_best.php?mode=A&tiref=<ID>
# The site requires a registration ID; for unknown swimmers we have to search
# first via /biogs/ search results. This is best-effort.

def fetch_swim_england_pbs(swim_england_id: str) -> list[dict]:
    """Return list of {event_code, course, time_cs, best_date} for a given ID."""
    if not swim_england_id:
        return []
    url = f"{SWIM_ENGLAND_BASE}/individualbest/personal_best.php?mode=A&tiref={swim_england_id}"
    html = _cached_get(url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for table in soup.find_all("table"):
        # Heuristic: tables with header rows that include 'Event' and 'Time'
        head = " ".join(th.get_text(" ", strip=True).lower() for th in table.find_all("th"))
        if "event" not in head or "time" not in head:
            continue
        course = "LC" if "long course" in head or "lc" in head else (
                  "SC" if "short course" in head or "sc" in head else "LC")
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 2:
                continue
            event_raw = cells[0]
            ev = canonical_event(event_raw, course_hint=course)
            if not ev:
                continue
            # Time is usually the 2nd or 3rd column
            time_cs = None
            best_date = None
            for c in cells[1:]:
                if time_cs is None:
                    time_cs = parse_time_to_cs(c.split()[0]) if c else None
                if re.match(r"\d{2}/\d{2}/\d{2,4}", c):
                    best_date = c
            if time_cs is None:
                continue
            out.append({
                "event_code": ev, "course": course,
                "time_cs": time_cs, "best_date": best_date,
            })
    return out


def import_swim_england_into_store(conn, swimmer_id: int, swim_england_id: str) -> int:
    """Pull PBs from swimmingresults.org and merge into personal_best.
    Returns number of rows imported. swim_england data takes precedence over 'meet'.
    """
    pbs = fetch_swim_england_pbs(swim_england_id)
    n = 0
    for pb in pbs:
        existing = conn.execute(
            "SELECT best_time_cs, source FROM personal_best "
            "WHERE swimmer_id=? AND event_code=? AND course=?",
            (swimmer_id, pb["event_code"], pb["course"]),
        ).fetchone()
        if existing and existing[1] == "swim_england" and existing[0] <= pb["time_cs"]:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO personal_best "
            "(swimmer_id, event_code, course, best_time_cs, best_date, source, confidence) "
            "VALUES (?,?,?,?,?,?,?)",
            (swimmer_id, pb["event_code"], pb["course"], pb["time_cs"],
             pb["best_date"], "swim_england", 0.97),
        )
        n += 1
    if swim_england_id:
        conn.execute("UPDATE swimmer SET swim_england_id=? WHERE id=? AND (swim_england_id IS NULL OR swim_england_id='')",
                     (swim_england_id, swimmer_id))
    conn.commit()
    return n


# ------------------------------------------------------------------
# Manual import helpers (CSV) — used when the user has a historical PB sheet
# ------------------------------------------------------------------

def import_pbs_csv(conn, csv_text: str, default_gender: str | None = None) -> int:
    """CSV columns: swimmer_name, event, course, time, date(optional), gender(optional).

    Resolves swimmers by display_name; creates if needed. CRITICALLY: writes
    event codes with the canonical gender prefix so detector queries match
    meet-derived event codes. Gender is taken from (in order): row['gender'],
    swimmer record, default_gender. If gender cannot be resolved the row is
    written under both M and F so it still matches — but a warning is logged.
    """
    import csv
    import io
    from .identity import resolve_or_create
    reader = csv.DictReader(io.StringIO(csv_text))
    n = 0
    for row in reader:
        name = (row.get("swimmer_name") or row.get("name") or "").strip()
        if not name:
            continue
        # Resolve gender BEFORE building the canonical event code.
        gender = (row.get("gender") or "").strip().upper()[:1] or None
        sid = resolve_or_create(conn, name, gender=gender, club_id=None)
        if not gender:
            existing = conn.execute("SELECT gender FROM swimmer WHERE id=?", (sid,)).fetchone()
            if existing and existing[0]:
                gender = existing[0]
        if not gender:
            gender = default_gender

        ev = canonical_event(row.get("event", ""), gender_hint=gender,
                             course_hint=row.get("course"))
        course = (row.get("course") or "LC").upper()
        if course not in ("LC", "SC"):
            course = "LC"
        if not ev:
            continue
        t = parse_time_to_cs(row.get("time"))
        if t is None:
            continue
        if ev.startswith("X_"):
            # Gender unknown — write a record under each likely gender so the
            # detector still finds a baseline; mark lower confidence.
            for g in ("M", "F"):
                gen_ev = "_".join([g] + ev.split("_")[1:])
                conn.execute(
                    "INSERT OR REPLACE INTO personal_best "
                    "(swimmer_id, event_code, course, best_time_cs, best_date, source, confidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (sid, gen_ev, course, t, row.get("date"), "imported", 0.7),
                )
            LOG.warning("PB import: gender unknown for %s; wrote both genders", name)
        else:
            conn.execute(
                "INSERT OR REPLACE INTO personal_best "
                "(swimmer_id, event_code, course, best_time_cs, best_date, source, confidence) "
                "VALUES (?,?,?,?,?,?,?)",
                (sid, ev, course, t, row.get("date"), "imported", 0.95),
            )
        n += 1
    conn.commit()
    return n
