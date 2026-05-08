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


CORPUS = pathlib.Path(__file__).resolve().parents[1] / "samples" / "learning_corpus" / "level2"

SAMPLES = [
    "2025_01_westhill_january/results.zip",
    "2025_02_elgin_spring_meet/results.zip",
    "2025_03_garioch_pre_snags/results.zip",
    "2025_03_dyce_mini_meet/results.zip",
    "2025_02_silver_city_blues_masters/results.zip",
]


def _read_member(zip_path: pathlib.Path, suffix: str) -> bytes | None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.lower().endswith(suffix.lower()):
                return zf.read(name)
    return None


@pytest.mark.parametrize("rel_path", SAMPLES)
def test_hy3_parser_against_corpus(rel_path: str) -> None:
    zip_path = CORPUS / rel_path
    if not zip_path.exists():
        pytest.skip(f"corpus sample missing: {zip_path}")
    data = _read_member(zip_path, ".hy3")
    if data is None:
        pytest.skip(f".hy3 not present in {rel_path}")

    assert detect_hy3(data), "detect_hy3 should be true for .hy3"
    meet = parse_hy3(data)

    assert meet.meet_name, f"{rel_path}: meet name missing"
    assert len(meet.events) >= 10, f"{rel_path}: only {len(meet.events)} events"
    total_swims = sum(len(e.swims) for e in meet.events)
    assert total_swims >= 50, f"{rel_path}: only {total_swims} swims"
    assert meet.overall_confidence >= 0.7, (
        f"{rel_path}: overall confidence {meet.overall_confidence}"
    )

    # Spot-check that the first event has named swimmers + a club
    first = meet.events[0]
    assert first.distance_m, f"{rel_path}: first event distance missing"
    assert first.stroke, f"{rel_path}: first event stroke missing"
    sample_swim = first.swims[0]
    assert sample_swim.swimmer_name and sample_swim.swimmer_name != "Unknown"
    assert sample_swim.club, "club should be populated for the first swim"
    # The garbage "02Meet Results" placeholder we used to produce must not appear.
    for ev in meet.events:
        for s in ev.swims:
            assert "02Meet Results" not in (s.swimmer_name or "")


@pytest.mark.parametrize("rel_path", SAMPLES)
def test_sdif_parser_against_corpus(rel_path: str) -> None:
    zip_path = CORPUS / rel_path
    if not zip_path.exists():
        pytest.skip(f"corpus sample missing: {zip_path}")
    data = _read_member(zip_path, ".cl2")
    if data is None:
        pytest.skip(f".cl2 not present in {rel_path}")

    assert detect_sdif(data), "detect_sdif should be true for .cl2"
    meet = parse_sdif(data)

    assert meet.meet_name, f"{rel_path}: meet name missing"
    assert len(meet.events) >= 10, f"{rel_path}: only {len(meet.events)} events"
    total_swims = sum(len(e.swims) for e in meet.events)
    assert total_swims >= 50, f"{rel_path}: only {total_swims} swims"
    assert meet.overall_confidence >= 0.7, (
        f"{rel_path}: overall confidence {meet.overall_confidence}"
    )

    first = meet.events[0]
    assert first.distance_m, f"{rel_path}: first event distance missing"
    assert first.stroke, f"{rel_path}: first event stroke missing"
    sample_swim = first.swims[0]
    assert sample_swim.swimmer_name and sample_swim.swimmer_name != "Unknown"
    assert sample_swim.club


@pytest.mark.parametrize("rel_path", SAMPLES)
def test_zip_routes_through_native_parsers(rel_path: str) -> None:
    """End-to-end: interpret_document on the ZIP should use the native path."""
    zip_path = CORPUS / rel_path
    if not zip_path.exists():
        pytest.skip(f"corpus sample missing: {zip_path}")
    data = zip_path.read_bytes()
    meet = interpret_document(data, hint="zip")

    # Source list includes hy3 or sdif (proves the native fast path fired)
    assert any("hy3" in s for s in meet.sources_used) or any(
        "sdif" in s for s in meet.sources_used
    ), f"native parser was not invoked for {rel_path}: sources={meet.sources_used}"

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
