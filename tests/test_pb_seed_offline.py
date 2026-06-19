"""Offline, file-only PB detection from entry/seed times.

Before this path existed the PB finder could only confirm a PB by looking the
swimmer up on the web — so a throttled or unconfigured deployment produced
**zero PBs** for a meet with hundreds of them. The fix threads the swimmer's
entry/seed time (which most result files already carry: HY-TEK E1, SDIF seed
column, printed "Seed Time" / "Finals Time" columns) end-to-end so the engine
can confirm a PB straight from the file — deterministically, instantly, and
with no network at all.

These tests pin that whole chain:

  parse (seed captured) → bridge (seed_time_cs set) → detector (pb_likely fires)
  → counter (the "weekend at a glance" PB tally is no longer 0).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "legacy") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "legacy"))


# --------------------------------------------------------------------------- #
# 1. Schema carries a seed field
# --------------------------------------------------------------------------- #


def test_interpreted_swim_has_seed_field():
    from mediahub.interpreter.schema_dataclasses import InterpretedSwim

    s = InterpretedSwim(
        swimmer_name="A B", yob=None, club=None, place=1,
        time="58.21", reaction=None, confidence=0.9, raw_row="",
    )
    assert s.seed_time is None  # default, no false seed
    s2 = InterpretedSwim(
        swimmer_name="A B", yob=None, club=None, place=1,
        time="58.21", reaction=None, confidence=0.9, raw_row="", seed_time="59.10",
    )
    assert s2.seed_time == "59.10"


# --------------------------------------------------------------------------- #
# 2. Printed "Seed Time  Finals Time" rows — the result is the finals (last),
#    the seed is the entry (first). This is the layout HY-TEK county PDFs print.
# --------------------------------------------------------------------------- #

_PRINTED = """Sussex County ASA LC Champ
Event 101  Girls 200 LC Meter Freestyle
Name                  AaD Club            Seed Time  Finals Time
1 Effy Johnson         15 Brighton Dolph  2:51.20    2:49.40
2 Mia Carter           14 Brighton Dolph  2:55.00    2:53.10
3 Sara Lowe            16 Brighton Dolph  2:48.00    2:50.90
Event 102  Boys 100 LC Meter Freestyle
Name                  AaD Club            Seed Time  Finals Time
1 Oscar Earthrowl      15 Brighton Dolph  55.20      54.10
""".encode("utf-8")


def _swims_from(text: bytes):
    from mediahub.interpreter import interpret_document

    im = interpret_document(text, hint=None)
    return {s.swimmer_name: s for ev in im.events for s in ev.swims}, im


def test_printed_seed_and_finals_split_correctly():
    swims, _ = _swims_from(_PRINTED)
    assert "Effy Johnson" in swims
    effy = swims["Effy Johnson"]
    # The achieved/result time is the LAST column; the seed is the entry column.
    assert effy.time == "2:49.40"
    assert effy.seed_time == "2:51.20"
    oscar = swims["Oscar Earthrowl"]
    assert oscar.time == "54.10" and oscar.seed_time == "55.20"


def test_finals_only_row_has_no_false_seed():
    """A row with a single time (no seed column) must not invent a seed."""
    text = (
        "Event 1 Girls 50 LC Meter Freestyle\n"
        "1 Jane Doe 12 Brighton Dolph 30.10\n"
        "2 Amy Roe 13 Brighton Dolph 31.40\n"
    ).encode("utf-8")
    swims, _ = _swims_from(text)
    assert swims["Jane Doe"].time == "30.10"
    assert swims["Jane Doe"].seed_time is None


def test_trailing_points_column_not_mistaken_for_seed():
    """A decimal-shaped trailing column (e.g. points) after the time must not be
    read as a seed (the ratio gate rejects it) AND the real swim time must stay
    the result — the long-standing first-time behaviour when the pair is not a
    genuine seed/finals pair."""
    text = (
        "Event 1 Girls 50 LC Meter Freestyle\n"
        "1 Jane Doe 12 Brighton Dolph 24.50 9.00\n"  # 9.00 ~ points, ratio 0.37
    ).encode("utf-8")
    swims, _ = _swims_from(text)
    jane = swims["Jane Doe"]
    assert jane.time == "24.50", "the real swim time stays the result"
    assert jane.seed_time is None, "ratio 0.37 is outside the seed window → no seed"


# --------------------------------------------------------------------------- #
# 3. Bridge: seed → canonical seed_time_cs
# --------------------------------------------------------------------------- #


def test_bridge_sets_seed_time_cs():
    from mediahub.pipeline.interpreter_bridge import interpreted_to_canonical

    _, im = _swims_from(_PRINTED)
    meet = interpreted_to_canonical(im, source_filename="sussex.txt")
    seeded = [r for r in meet.results if r.seed_time_cs]
    assert len(seeded) == len(meet.results) > 0, "every parsed seed reaches canonical"
    # Effy: 2:51.20 → 17120 cs ; finals 2:49.40 → 16940 cs
    effy = next(r for r in meet.results if r.swimmer_key.endswith("Johnson,Effy"))
    assert effy.finals_time_cs == 16940
    assert effy.seed_time_cs == 17120


# --------------------------------------------------------------------------- #
# 4. Detector: a swim that beats its seed fires pb_likely (no web data)
# --------------------------------------------------------------------------- #


def test_pb_likely_fires_from_seed_without_web():
    from swim_content_v5.achievements.pb import PBLikelyDetector
    from swim_content_v5.history import SwimmerHistory

    swim = NS(dq=False, finals_time_cs=16940, seed_time_cs=17120,
              distance=200, stroke="FR", course="LC", swimmer_key="k1", round="F")
    hist = SwimmerHistory("k1", "Effy Johnson", pb_snapshot=None)  # no web baseline
    ctx = NS(start_date="2026-02-15", end_date="2026-02-15")
    out = PBLikelyDetector().detect(swim, ctx, hist, extra={"swimmer_name": "Effy Johnson"})
    assert out and out[0].type == "pb_likely"
    assert "2:49.40" in out[0].headline

    # A swim slower than its seed is not a PB.
    slow = NS(dq=False, finals_time_cs=17500, seed_time_cs=17120,
              distance=200, stroke="FR", course="LC", swimmer_key="k1", round="F")
    assert PBLikelyDetector().detect(slow, ctx, hist) == []


# --------------------------------------------------------------------------- #
# 5. End-to-end through the real pipeline — offline (fetch_pbs=False)
# --------------------------------------------------------------------------- #


def test_pipeline_reports_pbs_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_PB_DISCOVERY_PARALLEL", "0")
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    run = run_pipeline_v4(
        file_bytes=_PRINTED, filename="sussex.txt", profile_id=None,
        club_filter="Brighton Dolph", use_pb_cache=True,
        fetch_pbs=False,  # NO network — PBs must come from the file's seed times
        run_id="seed-offline-e2e",
    )
    assert run.error is None
    rr = run.recognition_report or {}
    pb_headlines = [
        (ra.get("achievement", {}) or {}).get("headline", "")
        for ra in rr.get("ranked_achievements", [])
        if "pb" in (ra.get("achievement", {}) or {}).get("type", "")
    ]
    # Effy, Mia, Oscar beat their seeds; Sara did not.
    assert len(pb_headlines) == 3, f"expected 3 offline PBs, got {pb_headlines}"

    from mediahub.web.weekend_glance import build_weekend_glance

    glance = build_weekend_glance(
        {"recognition_report": rr, "meet": {"name": "Sussex"},
         "our_swim_count": run.our_swim_count}
    )
    assert glance is not None and glance.n_pbs == 3, "the glance PB tally is no longer 0"


# --------------------------------------------------------------------------- #
# 6. HY-TEK .hy3 E1 seed extraction (real corpus) — was 0 before the fix
# --------------------------------------------------------------------------- #

_CORPUS_ZIP = (
    _REPO_ROOT / "samples" / "learning_corpus" / "level1"
    / "2025_11_nd_open_championships" / "results_hy3.zip"
)


@pytest.mark.skipif(not _CORPUS_ZIP.exists(), reason="corpus .hy3 sample not shipped")
def test_hy3_seed_times_extracted_from_corpus():
    import zipfile

    from mediahub.interpreter.hytek_parser import parse_hy3

    with zipfile.ZipFile(_CORPUS_ZIP) as z:
        data = next(z.read(n) for n in z.namelist() if n.lower().endswith(".hy3"))
    meet = parse_hy3(data)
    swims = [s for ev in meet.events for s in ev.swims]
    seeded = [s for s in swims if s.seed_time]
    # The E1 records carry seed times for the vast majority of swims; the old
    # fixed-offset read captured none.
    assert len(seeded) > 0.5 * len(swims), (
        f"expected seed times on most swims, got {len(seeded)}/{len(swims)}"
    )


# --------------------------------------------------------------------------- #
# 7. Counter consistency: the by-the-numbers card counts pb_likely too
# --------------------------------------------------------------------------- #


def test_weekend_in_numbers_counts_pb_likely():
    from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers

    report = {
        "meet_name": "Test",
        "n_swims_analysed": 4,
        "ranked_achievements": [
            {"achievement": {"type": "pb_likely", "swimmer_name": "A",
                             "raw_facts": {}}},
            {"achievement": {"type": "pb_confirmed", "swimmer_name": "B",
                             "raw_facts": {}}},
            {"achievement": {"type": "medal_gold", "swimmer_name": "C",
                             "raw_facts": {"place": 1}}},
        ],
    }
    card = build_weekend_in_numbers(report)
    pbs = next(s["value"] for s in card["stats"] if s["label"] == "PBs")
    assert pbs == "2", "pb_likely + pb_confirmed both count toward PBs"
