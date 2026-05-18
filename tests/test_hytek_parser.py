"""V8.1 tests: Hy-Tek `.hy3` and SDIF `.cl2` parsers.

These tests run against the V8.1 corpus samples and assert that the
parsers produce ≥10 events, ≥50 swims, confidence ≥0.7, with proper
swimmer names + clubs.
"""
from __future__ import annotations

import pathlib
import zipfile

import pytest

from mediahub.interpreter import interpret_document
from mediahub.interpreter.hytek_parser import detect_hy3, parse_hy3
from mediahub.interpreter.sdif_parser import detect_sdif, parse_sdif


# Corpus root for parser-against-real-data tests. We originally tried to
# parametrize over five level2 meet ZIPs (Westhill January, Elgin Spring,
# Garioch, Dyce Mini, Silver City Blues) but those samples never landed
# in the repo and the tests skipped every run. May 2026 cleanup: point at
# the level1 North District Open Championships sample, which IS shipped
# (samples/learning_corpus/level1/.../results_hy3.zip) so the parser is
# exercised against real Hy-Tek / SDIF data on every test run.
CORPUS_ZIP = (
    pathlib.Path(__file__).resolve().parents[1]
    / "samples" / "learning_corpus" / "level1"
    / "2025_11_nd_open_championships" / "results_hy3.zip"
)


def _read_member(zip_path: pathlib.Path, suffix: str) -> bytes | None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.lower().endswith(suffix.lower()):
                return zf.read(name)
    return None


def test_hy3_parser_against_corpus() -> None:
    """Parse the real .hy3 file from the shipped corpus.

    The thresholds (≥10 events, ≥50 swims, ≥0.7 confidence) match
    what we'd expect from any properly-formed competitive meet.
    """
    assert CORPUS_ZIP.exists(), f"corpus sample missing: {CORPUS_ZIP}"
    data = _read_member(CORPUS_ZIP, ".hy3")
    assert data is not None, f".hy3 not present in {CORPUS_ZIP.name}"

    assert detect_hy3(data), "detect_hy3 should be true for .hy3"
    meet = parse_hy3(data)

    assert meet.meet_name, "meet name missing"
    assert len(meet.events) >= 10, f"only {len(meet.events)} events"
    total_swims = sum(len(e.swims) for e in meet.events)
    assert total_swims >= 50, f"only {total_swims} swims"
    assert meet.overall_confidence >= 0.7, (
        f"overall confidence {meet.overall_confidence}"
    )

    # Spot-check that the first event has named swimmers + a club
    first = meet.events[0]
    assert first.distance_m, "first event distance missing"
    assert first.stroke, "first event stroke missing"
    sample_swim = first.swims[0]
    assert sample_swim.swimmer_name and sample_swim.swimmer_name != "Unknown"
    assert sample_swim.club, "club should be populated for the first swim"
    # The garbage "02Meet Results" placeholder we used to produce must not appear.
    for ev in meet.events:
        for s in ev.swims:
            assert "02Meet Results" not in (s.swimmer_name or "")


def test_sdif_parser_against_corpus() -> None:
    """Parse the real .cl2 file from the shipped corpus."""
    assert CORPUS_ZIP.exists(), f"corpus sample missing: {CORPUS_ZIP}"
    data = _read_member(CORPUS_ZIP, ".cl2")
    assert data is not None, f".cl2 not present in {CORPUS_ZIP.name}"

    assert detect_sdif(data), "detect_sdif should be true for .cl2"
    meet = parse_sdif(data)

    assert meet.meet_name, "meet name missing"
    assert len(meet.events) >= 10, f"only {len(meet.events)} events"
    total_swims = sum(len(e.swims) for e in meet.events)
    assert total_swims >= 50, f"only {total_swims} swims"
    assert meet.overall_confidence >= 0.7, (
        f"overall confidence {meet.overall_confidence}"
    )

    first = meet.events[0]
    assert first.distance_m, "first event distance missing"
    assert first.stroke, "first event stroke missing"
    sample_swim = first.swims[0]
    assert sample_swim.swimmer_name and sample_swim.swimmer_name != "Unknown"
    assert sample_swim.club


def test_zip_routes_through_native_parsers() -> None:
    """End-to-end: interpret_document on the ZIP should use the native path."""
    assert CORPUS_ZIP.exists(), f"corpus sample missing: {CORPUS_ZIP}"
    data = CORPUS_ZIP.read_bytes()
    meet = interpret_document(data, hint="zip")

    # Source list includes hy3 or sdif (proves the native fast path fired)
    assert any("hy3" in s for s in meet.sources_used) or any(
        "sdif" in s for s in meet.sources_used
    ), f"native parser was not invoked: sources={meet.sources_used}"

    assert len(meet.events) >= 10
    total_swims = sum(len(e.swims) for e in meet.events)
    assert total_swims >= 50
    assert meet.overall_confidence >= 0.7


def test_synthetic_hy3_round_trip() -> None:
    """Tiny synthetic .hy3 to verify parser handles minimal input."""
    body = "\n".join([
        "A107SystemHeader                              Hy-Tek MM 7.0",
        "B1Spring Meet                                 City Pool                                    050120250502202505022025",
        "C1NADX Test Swim Club                                                                                       0",
        "D1M  001Smith               John                                    USS123456789    000000000000000101201210     0",
        "E1M  001SmithMS    50A 10 11  0A  0.00101A   30.00S   30.00S    0.00    0.00   NN               N                               00",
        "E2F   30.00S       0  1  4  0   1  0   30.00    0.00    0.00        30.00     0.00     05012025                           0     00",
    ])
    meet = parse_hy3(body.encode("latin-1"))
    assert meet.events
    swim = meet.events[0].swims[0]
    assert swim.swimmer_name == "John Smith"
    assert swim.club == "Test Swim Club"
    assert meet.events[0].distance_m == 50
    assert meet.events[0].stroke == "Freestyle"
    assert swim.place == 1
