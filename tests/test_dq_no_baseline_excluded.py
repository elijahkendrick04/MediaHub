"""
test_dq_no_baseline_excluded.py — QA-018 [P1 ACCURACY/TRUST].

This is the gap left by QA-013 (``test_dq_excluded_from_moments.py``). QA-013
made a DISQUALIFIED swim void its struck-out time so it bridges to
``dq=True`` / ``finals_time_cs=None`` and is dropped by the single central
recognition filter (``swim_content_v5.report``: ``if dq or finals_time_cs is
None: continue``) — verified for the PDF ``DQ`` rows (Kenneth Powell's DQ'd 200
Back no longer cards).

But QA-013 only ever fixed the *PDF* parser (``interpreter/rows.py``). The
Hy-Tek ``.hy3`` parser (``interpreter/hytek_parser.py``) — the live path for an
uploaded results file — never recognised Hy-Tek's ``Q`` disqualification code,
so a DQ'd swim kept its struck-out time and reached the recognition stage as a
*valid* result. With NO online prior-best baseline the engine then "celebrated"
it as **POSSIBLE PB — UNCONFIRMED**.

The headline live repro (Ken Deeley Open, City of Brighton & Hove): Binuthi
Siriwardane's ONLY 50m Breaststroke was the HY3 result record
``E2F  51.64SQ3Q`` — finals time ``51.64``, course ``S``, then ``Q3Q`` (the
disqualification code; a sibling ``H1`` record reads "Q7.6 Did not touch at the
turn or finish with both hands"). It was carded "Binuthi Siriwardane — 50m
Breaststroke — 51.64 — POSSIBLE PB — UNCONFIRMED". Her valid 50m Freestyle
(36.56) cards correctly.

Root cause + fix (deterministic — no AI): the Hy-Tek ``.hy3`` E2 record stamps
a DQ as a ``Q`` code right after the 8-char finals time and its 1-char course
flag (``E2P  151.39SQ1F`` → course ``S``, code ``Q1F``). The parser now voids
the printed time when that code is present, so the swim bridges to
``dq=True`` / ``finals_time_cs=None`` and feeds the SAME single exclusion a PDF
``DQ`` row feeds (QA-013). The SDIF ``.cl2`` ``DQ`` marker is handled the same
way. No moment type — confirmed PB, possible/unconfirmed PB, time-drop, medal,
barrier, biggest-drop, multi-PB — can resurface a disqualified swim.

These tests pin the contract end-to-end: a DQ'd swim by a swimmer with NO prior
baseline yields ZERO moments (including no "possible PB"), while an otherwise
identical VALID swim still surfaces — proving the DQ exclusion, not broken
plumbing, is what silences the disqualified swim.
"""

from __future__ import annotations

import pathlib
import sys
import types
import zipfile

import pytest

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import mediahub  # noqa: E402,F401  (registers legacy package aliases)

from mediahub.interpreter.hytek_parser import (  # noqa: E402
    _is_dq_e2,
    parse_hy3,
)
from mediahub.interpreter.sdif_parser import _parse_d0  # noqa: E402
from mediahub.pipeline.interpreter_bridge import (  # noqa: E402
    interpreted_to_canonical,
)
import swim_content_v5.report as report_mod  # noqa: E402
from swim_content_v5.achievements import get_all_detectors  # noqa: E402
from swim_content_v5.explainer import build_swim_trace  # noqa: E402
from swim_content_v5.history import SwimmerHistory  # noqa: E402
from swim_content_v5.report import (  # noqa: E402
    _run_detectors_for_swim,
    build_meet_context,
)


# ---------------------------------------------------------------------------
# Fixed-width Hy-Tek record builders (column-precise so the parser reads them
# exactly as it reads a real Meet Manager export)
# ---------------------------------------------------------------------------


def _rec(width: int, fields: list[tuple[int, str]]) -> str:
    """Place ``(col, text)`` fields into a space-padded buffer of ``width``."""
    buf = [" "] * width
    for col, text in fields:
        for i, ch in enumerate(text):
            buf[col + i] = ch
    return "".join(buf)


def _binuthi_hy3() -> bytes:
    """A minimal `.hy3` mirroring the live repro: one swimmer with NO online PB
    baseline, a DISQUALIFIED 50m Breaststroke (the ``Q3Q`` code) and a VALID
    50m Freestyle."""
    lines = [
        _rec(60, [(0, "A107SystemHeader"), (46, "Hy-Tek MM 8.0")]),
        _rec(110, [(0, "B1"), (2, "Ken Deeley Open 2025"),
                   (47, "Brighton Pool"), (92, "06212025"), (100, "06222025")]),
        _rec(60, [(0, "C1"), (2, "COBH"), (7, "City of Brighton & Hove")]),
        _rec(100, [(0, "D1"), (2, "F"), (3, "  042"), (8, "Siriwardane"),
                   (28, "Binuthi"), (68, "901234567"), (80, "01012009"),
                   (88, "16")]),
        # 50m Breaststroke (stroke C) — DISQUALIFIED: time 51.64, course S, Q3Q
        _rec(90, [(0, "E1"), (2, "F"), (3, "  042"), (8, "Siriw"),
                  (17, "  50"), (21, "C"), (33, "L"), (34, "0101")]),
        _rec(110, [(0, "E2"), (2, "F"), (3, "   51.64"), (11, "S"),
                   (12, "Q3Q"), (27, "  0"), (30, "  0")]),
        # 50m Freestyle (stroke A) — VALID 36.56, placed 1st
        _rec(90, [(0, "E1"), (2, "F"), (3, "  042"), (8, "Siriw"),
                  (17, "  50"), (21, "A"), (33, "L"), (34, "0102")]),
        _rec(110, [(0, "E2"), (2, "F"), (3, "   36.56"), (11, "S"),
                   (27, "  0"), (30, "  1")]),
    ]
    return ("\n".join(lines)).encode("latin-1")


def _canonical_binuthi():
    """Parse the synthetic `.hy3` → canonical Meet, returning (meet, dq, valid)."""
    meet = interpreted_to_canonical(
        parse_hy3(_binuthi_hy3()),
        source_filename="ken-deeley-2025-results.hy3",
        source_format="hy3",
    )
    dq = next(r for r in meet.results if r.stroke == "BR")
    valid = next(r for r in meet.results if r.stroke == "FR")
    return meet, dq, valid


def _empty_baseline(swimmer_key: str, name: str = "Binuthi Siriwardane") -> SwimmerHistory:
    """A history whose lookup SUCCEEDED but lists NO prior best for any event —
    exactly the no-online-baseline case that produces 'POSSIBLE PB —
    UNCONFIRMED' for a valid swim."""
    snap = types.SimpleNamespace(
        fetch_ok=True, source_domain="swimmingresults", pb_times={}
    )
    return SwimmerHistory(swimmer_key, name, snap)


# ---------------------------------------------------------------------------
# 1. Interpreter root cause — the Hy-Tek E2 'Q' code marks a disqualification
# ---------------------------------------------------------------------------


def test_is_dq_e2_detects_real_qcode_records():
    """Real corpus-shaped DQ E2 records (a ``Q`` after the time + course flag)
    are recognised; valid swims (course flag then ``S``/space/``R``) are not."""
    # Disqualified: course 'S' then 'Q<rule>'.
    assert _is_dq_e2("E2P  151.39SQ1F    0  3  9  0   0  0  151.38")
    assert _is_dq_e2("E2P   27.57SQ7B    0  6  2  0   0  0   2")
    assert _is_dq_e2("E2P    0.00SQ7C    0  4  9  0   0  0    ")
    # The exact code shape from the live repro (E2F  51.64SQ3Q).
    assert _is_dq_e2("E2F   51.64SQ3Q    0  3  9  0   0  0   51.64")
    # Valid finishes — the char after the course flag is 'S'/space/'R', not 'Q'.
    assert not _is_dq_e2("E2P   74.26SS      0  1  8  7  38  0   74.48")
    assert not _is_dq_e2("E2P  145.48S       0  2  6  4   8  0  145.48")
    assert not _is_dq_e2("E2F   30.00S       0  1  4  0   1  0   30.00")


# ---------------------------------------------------------------------------
# 2. Parser → canonical bridge — a DQ'd HY3 swim is voided, valid one intact
# ---------------------------------------------------------------------------


def test_hy3_dq_swim_voids_time_and_marks_dq():
    """The disqualified 50 Breast bridges to dq / no finals time; the valid 50
    Free keeps its real time. Before the fix the parser read the struck-out
    51.64 as a valid result (dq=False, finals_time_cs=5164), so this failed."""
    _meet, dq, valid = _canonical_binuthi()

    assert dq.dq is True
    assert dq.status == "dq"
    assert dq.finals_time_cs is None  # the void 51.64 must NOT surface

    assert valid.dq is False
    assert valid.status == "completed"
    assert valid.finals_time_cs == 36 * 100 + 56  # 3656 cs (36.56)
    assert valid.place == 1


def test_central_recognition_filter_drops_only_the_dq_swim():
    """The single central exclusion every moment type funnels through —
    ``report``: ``if dq or finals_time_cs is None: continue`` — drops the DQ
    swim while keeping the valid one."""
    meet, dq, valid = _canonical_binuthi()
    analysed = [
        r for r in meet.results
        if not (getattr(r, "dq", False) or r.finals_time_cs is None)
    ]
    assert dq not in analysed
    assert valid in analysed


# ---------------------------------------------------------------------------
# 3. End-to-end — a DQ swim with NO baseline produces NO card of any kind
# ---------------------------------------------------------------------------


def test_dq_swim_no_baseline_produces_no_card(monkeypatch):
    """The headline regression: build the full recognition report for the
    no-baseline swimmer. The disqualified 50 Breast produces NO trace, NO
    achievement and — critically — NO 'POSSIBLE PB — UNCONFIRMED'. Her valid 50
    Free still cards.

    Before the fix the parser surfaced the void 51.64 as a valid swim, so the
    report carried a Breaststroke trace categorised ``possible_pb_uncertain``
    — this assertion failed.
    """
    # Meet-identity discovery is purely additive and must never touch the
    # network in a unit test; force the (already try/except-guarded) path off.
    import context_engine.identity as ident

    def _no_net(**_kw):
        raise RuntimeError("network disabled in test")

    monkeypatch.setattr(ident, "discover_meet_identity", _no_net)

    meet, _dq, _valid = _canonical_binuthi()
    run = types.SimpleNamespace(
        canonical_meet=meet,
        run_id="qa018-test",
        profile_id="",
        _pb_snapshots={},                 # no PB baseline for anyone
        _our_results=list(meet.results),  # both swims are "ours"
        _our_swimmer_keys=None,
    )

    report = report_mod.build_recognition_report_for_run(run)

    # Both swims were analysed, but the DQ produced nothing.
    assert report.get("n_swims_analysed") == 2
    traces = report.get("swim_traces", [])

    # The DQ 50 Breast (the only Breaststroke) must not appear as ANY trace,
    # and its void time must never surface anywhere in the report.
    assert all("Breast" not in (t.get("event") or "") for t in traces)
    near_miss = {t.get("near_miss_category") for t in traces}
    assert "possible_pb_uncertain" not in near_miss

    import json

    blob = json.dumps(report)
    assert "51.64" not in blob          # the disqualified time never surfaces
    assert "possible_pb_uncertain" not in blob
    assert "Breaststroke" not in blob

    # The valid 50 Free is unaffected — it still cards.
    assert report.get("n_achievements", 0) >= 1
    assert any("Free" in (t.get("event") or "") for t in traces)


def test_valid_no_baseline_swim_still_surfaces_as_possible_pb():
    """Control: a VALID swim by a swimmer with no online baseline DOES surface
    as 'possible_pb_uncertain'. This proves the possible-PB wiring is live —
    so the DQ exclusion (not broken plumbing) is what silences the disqualified
    swim above."""
    meet, _dq, valid = _canonical_binuthi()
    # Drop the place so no medal/placing achievement pre-empts the near-miss.
    valid.place = None

    ctx = build_meet_context(meet, research_data=None)
    history = _empty_baseline(valid.swimmer_key)
    achs, traces = _run_detectors_for_swim(
        swim=valid,
        swimmer_name="Binuthi Siriwardane",
        ctx=ctx,
        history=history,
        all_results=meet.results,
        standards=[],
        club_code="",
        detectors=get_all_detectors(),
    )
    trace = build_swim_trace(valid, "Binuthi Siriwardane", traces, len(achs))
    assert achs == []
    assert trace.near_miss_category == "possible_pb_uncertain"


# ---------------------------------------------------------------------------
# 4. SDIF (.cl2) — the same single exclusion handles the 'DQ' result marker
# ---------------------------------------------------------------------------


def _sdif_d0(width: int, fields: list[tuple[int, str]]) -> str:
    return _rec(width, fields)


def test_sdif_dq_result_is_voided():
    """A disqualified SDIF D0 result (its time replaced by a ``DQ`` marker) is
    voided so it bridges to dq / no finals time — the same exclusion the HY3
    ``Q`` code feeds. A clean valid result keeps its time."""
    base = [
        (0, "D0"), (11, "Siriwardane, Binuthi"), (40, "901234567"), (52, "A"),
        (66, "F"), (67, "  50"), (71, "3"),  # 50m, stroke 3 = Breaststroke
        (79, "06212025"), (88, "   38.20"), (96, "S"),
        (115, "   51.64"), (123, "S"), (134, "     3"),
    ]
    valid = _sdif_d0(145, base)
    assert _parse_d0(valid)["finals_time"] == "51.64"  # control: parses cleanly

    # DQ: the finals field carries the 'DQ' marker rather than a time.
    dq_fields = [f for f in base if f[0] != 115] + [(115, "      DQ")]
    dq = _sdif_d0(145, dq_fields)
    assert _parse_d0(dq)["finals_time"] is None


def test_sdif_dq_marker_voids_time_even_under_column_drift():
    """Robustness: even when a Hy-Tek version shifts columns so the finals field
    accidentally captures a time-shaped value, a ``DQ`` marker anywhere in the
    result region still voids the swim — it must never surface a finishing time.
    Before the fix the stray time was read as a valid result."""
    drift = [
        (0, "D0"), (11, "Siriwardane, Binuthi"), (40, "901234567"), (52, "A"),
        (66, "F"), (67, "  50"), (71, "3"), (79, "06212025"), (88, "   38.20"),
        (96, "S"),
        (103, "DQ"),         # real disqualification marker (drifted position)
        (115, "   51.64"),   # stray time-shaped bytes in the finals column
        (123, "S"),
    ]
    rec = _sdif_d0(145, drift)
    assert _parse_d0(rec)["finals_time"] is None


# ---------------------------------------------------------------------------
# 5. Corpus regression — real Q-coded Hy-Tek swims are disqualified, not valid
# ---------------------------------------------------------------------------


CORPUS_ZIP = (
    PROJECT_ROOT / "samples" / "learning_corpus" / "level1"
    / "2025_11_nd_open_championships" / "results_hy3.zip"
)


def _corpus_hy3_bytes() -> bytes | None:
    if not CORPUS_ZIP.exists():
        return None
    with zipfile.ZipFile(CORPUS_ZIP) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".hy3"):
                return zf.read(name)
    return None


def test_corpus_hy3_qcode_swims_marked_dq():
    """Against the shipped North District Open corpus: every parsed swim whose
    source E2 record carries a Hy-Tek ``Q`` disqualification code has its
    printed time voided — so none of those struck-out times can reach the
    recognition stage as a valid result. Matching on the swim's own ``raw_row``
    (the E2 line) avoids any coincidence with another swimmer's legitimate
    time."""
    data = _corpus_hy3_bytes()
    if data is None:
        pytest.skip(f"corpus sample missing: {CORPUS_ZIP}")

    meet = parse_hy3(data)
    qcoded = 0
    for ev in meet.events:
        for s in ev.swims:
            if _is_dq_e2(s.raw_row or ""):
                qcoded += 1
                assert s.time is None, (
                    f"Q-coded (disqualified) swim was not voided: {s.raw_row!r}"
                )
    assert qcoded > 0, "corpus should contain Q-coded Hy-Tek DQ records"
