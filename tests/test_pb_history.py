"""Tests for the accumulating per-club PB-history baseline.

Covers the store semantics that make it correct and scalable: fastest-within-a-
meet, same-meet exclusion (a swim is never its own baseline), re-run idempotency,
multi-tenant isolation, conservative cross-upload identity, and the glue that
turns prior results into the snapshot shape the PB detectors already consume.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

_ROOT = Path(__file__).resolve().parents[1]
for p in (_ROOT / "src", _ROOT / "legacy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mediahub.pb_history.identity import (  # noqa: E402
    canon_meet_key,
    event_key,
    swimmer_identity,
)
from mediahub.pb_history.store import PBHistoryStore  # noqa: E402
from mediahub.pb_history import service  # noqa: E402


# --------------------------------------------------------------------------- #
# identity / keys
# --------------------------------------------------------------------------- #


def test_identity_is_stable_and_club_variations_fold():
    a = swimmer_identity("Effy", "Johnson", "Brighton Dolphins SC", 2010)
    b = swimmer_identity("effy", "johnson", "Brighton Dolphins Swimming Club", 2010)
    assert a == b, "club generic-word and case variations must fold to one identity"
    assert swimmer_identity("", "", "Club", 2010) == "", "no name → no identity"
    # Different YoB → different person (same-name disambiguation).
    assert swimmer_identity("Tom", "Davies", "X", 2008) != swimmer_identity(
        "Tom", "Davies", "X", 2009
    )


def test_event_and_meet_keys():
    assert event_key(100, "fr", "lc") == "100FRLC"
    k1 = canon_meet_key("Sussex County ASA - LC Champ!", "2026-02-15", "K2 Crawley")
    k2 = canon_meet_key("SUSSEX COUNTY ASA  LC CHAMP", "2026-02-15", "k2 crawley")
    assert k1 == k2, "meet key canonicalises name/venue so a re-upload matches"


# --------------------------------------------------------------------------- #
# store semantics
# --------------------------------------------------------------------------- #


def _store(tmp_path):
    return PBHistoryStore(db_path=tmp_path / "pb_history.db")


def test_record_and_prior_best(tmp_path):
    s = _store(tmp_path)
    s.record_meet("clubA", "meet1", [("ident1", "nk", "100FRLC", 6100, "2026-01-10", "Meet 1")])
    bests = s.prior_bests("clubA", ["ident1"], exclude_meet_key="meet2")
    assert bests["ident1"]["100FRLC"]["time_cs"] == 6100
    assert bests["ident1"]["100FRLC"]["date_iso"] == "2026-01-10"


def test_same_meet_is_excluded(tmp_path):
    s = _store(tmp_path)
    s.record_meet("clubA", "meet1", [("ident1", "nk", "100FRLC", 6100, "2026-01-10", "M1")])
    # Excluding the only meet that holds the time → no prior baseline.
    assert s.prior_bests("clubA", ["ident1"], exclude_meet_key="meet1") == {}


def test_fastest_across_meets_and_within_meet(tmp_path):
    s = _store(tmp_path)
    # Two heats of the same event in one meet → keep the fastest.
    s.record_meet("clubA", "meet1", [("i", "nk", "100FRLC", 6200, "2026-01-10", "M1")])
    s.record_meet("clubA", "meet1", [("i", "nk", "100FRLC", 6050, "2026-01-10", "M1")])
    # A later, slower meet must not raise the baseline.
    s.record_meet("clubA", "meet2", [("i", "nk", "100FRLC", 6300, "2026-03-10", "M2")])
    bests = s.prior_bests("clubA", ["i"], exclude_meet_key="meet9")
    assert bests["i"]["100FRLC"]["time_cs"] == 6050


def test_rerun_is_idempotent(tmp_path):
    s = _store(tmp_path)
    row = [("i", "nk", "100FRLC", 6100, "2026-01-10", "M1")]
    s.record_meet("clubA", "meet1", row)
    s.record_meet("clubA", "meet1", row)  # re-upload same meet
    bests = s.prior_bests("clubA", ["i"], exclude_meet_key="meetX")
    assert bests["i"]["100FRLC"]["time_cs"] == 6100  # not duplicated/corrupted


def test_multi_tenant_isolation(tmp_path):
    s = _store(tmp_path)
    s.record_meet("clubA", "m1", [("i", "nk", "100FRLC", 6100, "2026-01-10", "M1")])
    s.record_meet("clubB", "m1", [("i", "nk", "100FRLC", 5900, "2026-01-10", "M1")])
    a = s.prior_bests("clubA", ["i"], exclude_meet_key="z")
    b = s.prior_bests("clubB", ["i"], exclude_meet_key="z")
    assert a["i"]["100FRLC"]["time_cs"] == 6100
    assert b["i"]["100FRLC"]["time_cs"] == 5900, "one club's history must not leak to another"


# --------------------------------------------------------------------------- #
# service glue: record a meet, then load it as a baseline for the next
# --------------------------------------------------------------------------- #


def _meet(name, date, results):
    swimmers = {
        "clubx:johnson,effy": NS(
            first_name="Effy", last_name="Johnson", club_name="Brighton Dolphins",
            club_code="clubx", dob="2010-05-01", age_at_meet=None,
        )
    }
    return NS(name=name, start_date=date, end_date=date, venue="Pool", swimmers=swimmers, results=results)


def _result(cs, dq=False):
    return NS(
        swimmer_key="clubx:johnson,effy", distance=200, stroke="FR", course="LC",
        finals_time_cs=cs, dq=dq, swim_date=None,
    )


def test_record_then_baseline_round_trip(tmp_path):
    store = _store(tmp_path)
    keys = {"clubx:johnson,effy"}

    meet1 = _meet("Winter Open", "2026-01-10", [_result(17120)])  # 2:51.20
    n = service.record_meet_results(meet1, keys, tenant_id="clubx", store=store)
    assert n == 1

    # A later meet: she swims 2:49.40 — faster than her stored 2:51.20.
    meet2 = _meet("County Champs", "2026-02-15", [_result(16940)])
    snaps = service.load_history_snapshots(meet2, keys, tenant_id="clubx", store=store)
    snap = snaps["clubx:johnson,effy"]
    assert snap.pb_times["200FRLC"][0]["time_sec"] == 171.20  # prior best surfaced
    assert snap.source_domain  # carries an honest source label

    # The current meet must be excluded from its own baseline.
    snaps_same = service.load_history_snapshots(meet1, keys, tenant_id="clubx", store=store)
    assert snaps_same == {}


def test_dq_and_no_time_swims_are_not_stored(tmp_path):
    store = _store(tmp_path)
    keys = {"clubx:johnson,effy"}
    meet = _meet("Open", "2026-01-10", [_result(None), _result(0), _result(17000, dq=True)])
    assert service.record_meet_results(meet, keys, tenant_id="clubx", store=store) == 0


def test_no_tenant_is_a_safe_noop(tmp_path):
    store = _store(tmp_path)
    keys = {"clubx:johnson,effy"}
    meet = _meet("Open", "2026-01-10", [_result(17000)])
    assert service.record_meet_results(meet, keys, tenant_id="", store=store) == 0
    assert service.load_history_snapshots(meet, keys, tenant_id="", store=store) == {}


# --------------------------------------------------------------------------- #
# erasure (GDPR "forget me") — order-independent name match, tenant-scoped
# --------------------------------------------------------------------------- #


def test_erase_subject_removes_only_that_swimmer(tmp_path):
    store = _store(tmp_path)
    store.record_meet("clubx", "m1", [
        ("johnson|effy|brighton dolphins|", "effy johnson", "100FRLC", 6100, "d", "M1"),
        ("carter|mia|brighton dolphins|", "carter mia", "100FRLC", 6200, "d", "M1"),
    ])
    # Erase by full name, written in the other order — must still match.
    removed = service.erase_subject("clubx", "Johnson, Effy", store=store)
    assert removed == 1
    left = store.prior_bests("clubx", ["johnson|effy|brighton dolphins|",
                                       "carter|mia|brighton dolphins|"], exclude_meet_key="z")
    assert "johnson|effy|brighton dolphins|" not in left  # erased
    assert "carter|mia|brighton dolphins|" in left        # untouched

    # Wrong tenant erases nothing.
    assert service.erase_subject("other", "Mia Carter", store=store) == 0


def test_purge_tenant_clears_one_club_only(tmp_path):
    store = _store(tmp_path)
    store.record_meet("clubx", "m1", [("i", "ix", "100FRLC", 6100, "d", "M1")])
    store.record_meet("cluby", "m1", [("i", "ix", "100FRLC", 6100, "d", "M1")])
    assert store.purge_tenant("clubx") == 1
    assert store.prior_bests("clubx", ["i"], exclude_meet_key="z") == {}
    assert store.prior_bests("cluby", ["i"], exclude_meet_key="z")  # other club intact
