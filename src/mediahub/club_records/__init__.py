"""club_records — per-workspace club records engine (Phase W.3).

A deterministic records store (event × course × age-group × gender)
seeded by CSV import of the club's records sheet and updated from
ingested meets **on approval only**. The `ClubRecordDetector`
(`recognition_swim/achievements/club_record.py`) reads this store and
emits "NEW CLUB RECORD" achievements ranked above PBs.
"""

from .store import (
    RecordRow,
    apply_approved_card,
    delete_record,
    ensure_schema,
    import_csv,
    list_records,
    records_map,
    upsert_record,
)

__all__ = [
    "RecordRow",
    "apply_approved_card",
    "delete_record",
    "ensure_schema",
    "import_csv",
    "list_records",
    "records_map",
    "upsert_record",
]
