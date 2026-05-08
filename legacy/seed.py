"""
Seed the database with historical PBs, club records, and qualifying times.
Run this once before uploading meets so the detector has comparison baselines.

    python seed.py
"""
from __future__ import annotations
import csv
import sqlite3
from pathlib import Path

from swim_content.app import init_db, get_db
from swim_content.events import canonical_event, parse_time_to_cs
from swim_content.identity import resolve_or_create
from swim_content.crossref import import_pbs_csv

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "sample_data"


def seed_pbs(conn):
    text = (SAMPLE / "swansea_historical_pbs.csv").read_text()
    n = import_pbs_csv(conn, text)
    print(f"  PBs imported: {n}")


def seed_records(conn):
    club_id = conn.execute("SELECT id FROM club WHERE short_name='SUS'").fetchone()[0]
    with (SAMPLE / "sample_club_records.csv").open() as f:
        reader = csv.DictReader(f)
        n = 0
        for row in reader:
            ev = canonical_event(row["event"], course_hint=row["course"])
            if not ev:
                continue
            t = parse_time_to_cs(row["time"])
            if t is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO club_record "
                "(club_id, event_code, course, age_band, time_cs, holder, date_set) "
                "VALUES (?,?,?,?,?,?,?)",
                (club_id, ev, row["course"].upper(), row["age_band"],
                 t, row["holder"], row["date_set"]),
            )
            n += 1
        conn.commit()
    print(f"  club records imported: {n}")


def seed_qts(conn):
    with (SAMPLE / "sample_qualifying_times.csv").open() as f:
        reader = csv.DictReader(f)
        n = 0
        for row in reader:
            # canonical_event needs gender for the prefix; QTs are gender-specific anyway
            ev = canonical_event(row["event"], gender_hint=row["gender"],
                                 course_hint=row["course"])
            if not ev:
                continue
            t = parse_time_to_cs(row["time"])
            if t is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO qualifying_time "
                "(standard, event_code, course, gender, age_band, time_cs) "
                "VALUES (?,?,?,?,?,?)",
                (row["standard"], ev, row["course"].upper(),
                 row["gender"].upper(), "OPEN", t),
            )
            n += 1
        conn.commit()
    print(f"  qualifying times imported: {n}")


def main():
    init_db()
    conn = get_db()
    print("Seeding database...")
    seed_pbs(conn)
    seed_records(conn)
    seed_qts(conn)
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
