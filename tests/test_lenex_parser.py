"""Tests for `mediahub.interpreter.lenex_parser` (roadmap W.5).

LENEX 3.0 is the openly licensed XML interchange format for swim
results/entries (.lef = XML, .lxf = zipped .lef). The parser is
deterministic — stdlib ElementTree + ontology lookups, no LLM — and its
output has parity with the HY3/SDIF path (canonical stroke names,
"LC"/"SC" courses, "m:ss.cc"/"ss.cc" time strings).

Fixtures are hand-crafted per the Lenex 3.0 public spec structure under
tests/fixtures/lenex/ so every expected value is exact and assertable.
"""

from __future__ import annotations

import dataclasses
import io
import pathlib
import zipfile

import pytest

from mediahub.interpreter import interpret_document
from mediahub.interpreter._zip_safety import UnsafeZipError
from mediahub.interpreter.ingest import _sniff_format
from mediahub.interpreter.lenex_parser import (
    _parse_swimtime,
    detect_lenex,
    parse_lenex,
    parse_lenex_entries,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "lenex"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# detect_lenex — file-type sniff
# ---------------------------------------------------------------------------


class TestDetectLenex:
    def test_results_lef_detected(self) -> None:
        assert detect_lenex(_fixture("mini_results.lef")) is True

    def test_entries_lef_detected(self) -> None:
        assert detect_lenex(_fixture("mini_entries.lef")) is True

    def test_malformed_lef_still_detected(self) -> None:
        # Detection is a sniff, not a validation — the honest-error path
        # in parse_lenex handles the malformed payload.
        assert detect_lenex(_fixture("malformed.lef")) is True

    def test_no_xml_declaration_still_detected(self) -> None:
        assert detect_lenex(b'<LENEX version="3.0"><MEETS/></LENEX>') is True

    def test_utf8_bom_tolerated(self) -> None:
        assert detect_lenex(b'\xef\xbb\xbf<?xml version="1.0"?><LENEX version="3.0"/>') is True

    def test_hy3_bytes_not_lenex(self) -> None:
        assert detect_lenex(b"A107SystemHeader        Hy-Tek MM 7.0\nB1Spring Meet") is False

    def test_pdf_bytes_not_lenex(self) -> None:
        assert detect_lenex(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj") is False

    def test_random_xml_not_lenex(self) -> None:
        data = b'<?xml version="1.0"?><results><row place="1"/></results>'
        assert detect_lenex(data) is False

    def test_lenex_prefixed_other_tag_not_lenex(self) -> None:
        assert detect_lenex(b'<?xml version="1.0"?><LENEXTRAS></LENEXTRAS>') is False

    def test_lxf_zip_bytes_not_lenex(self) -> None:
        # .lxf is routed via the filename hint / ZIP recursion, both of
        # which call parse_lenex (which unwraps the ZIP itself).
        assert detect_lenex(_fixture("mini_results.lxf")) is False

    def test_empty_buffer_not_lenex(self) -> None:
        assert detect_lenex(b"") is False


# ---------------------------------------------------------------------------
# _parse_swimtime — LENEX HH:MM:SS.hh → canonical m:ss.cc / ss.cc
# ---------------------------------------------------------------------------


class TestParseSwimtime:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("00:00:55.43", "55.43"),
            ("00:01:05.32", "1:05.32"),
            ("00:01:02.18", "1:02.18"),
            ("00:17:25.10", "17:25.10"),
            ("01:02:03.45", "62:03.45"),  # hour-plus open-water style swims
            ("00:00:05.43", "5.43"),
        ],
    )
    def test_valid_times_canonicalised(self, raw: str, expected: str) -> None:
        assert _parse_swimtime(raw) == expected

    @pytest.mark.parametrize("raw", ["NT", "nt", "", "   ", "00:00:00.00", None])
    def test_no_time_returns_none(self, raw) -> None:
        assert _parse_swimtime(raw) is None

    def test_tolerated_short_forms(self) -> None:
        # Non-spec shapes some exporters emit are tolerated, matching the
        # forgiving stance of the HY3/SDIF parsers.
        assert _parse_swimtime("1:02.18") == "1:02.18"
        assert _parse_swimtime("55.43") == "55.43"

    @pytest.mark.parametrize("raw", ["DSQ", "abc", "1:2:3", "00:00:55"])
    def test_malformed_returns_none(self, raw: str) -> None:
        assert _parse_swimtime(raw) is None


# ---------------------------------------------------------------------------
# parse_lenex — results (.lef)
# ---------------------------------------------------------------------------


class TestParseLenexResults:
    @pytest.fixture()
    def meet(self):
        return parse_lenex(_fixture("mini_results.lef"))

    def test_meet_metadata(self, meet) -> None:
        assert meet.meet_name == "Summer Sprint Gala 2026"
        assert meet.venue == "Aberdeen"
        assert meet.dates == ("2026-05-16", "2026-05-16")
        assert meet.course_default == "LC"
        assert meet.sources_used == ["format:lenex"]

    def test_event_count_and_shape(self, meet) -> None:
        assert len(meet.events) == 2
        men_100_free, women_50_breast = meet.events
        assert men_100_free.gender == "M"
        assert men_100_free.distance_m == 100
        assert men_100_free.stroke == "Freestyle"  # parity with HY3 canon
        assert men_100_free.course == "LC"
        assert women_50_breast.gender == "F"
        assert women_50_breast.distance_m == 50
        assert women_50_breast.stroke == "Breaststroke"
        assert women_50_breast.course == "LC"

    def test_swim_count_excludes_dsq(self, meet) -> None:
        # 4 RESULT elements in the fixture, one DSQ → 3 countable swims.
        assert sum(len(e.swims) for e in meet.events) == 3

    def test_specific_swimmer_time_place_and_reaction(self, meet) -> None:
        first = meet.events[0].swims[0]
        assert first.swimmer_name == "Calum Reid"
        assert first.time == "55.43"  # 00:00:55.43 canonicalised
        assert first.place == 1  # via RANKINGS resultid mapping
        assert first.reaction == "0.68"  # "+0.68" normalised
        assert first.yob == 2008
        assert first.club == "Aberdeen Dolphins"

    def test_minute_plus_time_canonicalised(self, meet) -> None:
        second = meet.events[0].swims[1]
        assert second.swimmer_name == "Euan Park"
        assert second.time == "1:02.18"
        assert second.place == 2

    def test_second_club_swim(self, meet) -> None:
        swim = meet.events[1].swims[0]
        assert swim.swimmer_name == "Mhairi Watt"
        assert swim.club == "Granite City SC"
        assert swim.time == "41.07"
        assert swim.place == 1

    def test_dsq_flagged_in_needs_review(self, meet) -> None:
        flags = [n for n in meet.needs_review if n["reason"] == "lenex-result-status-excluded"]
        assert len(flags) == 1
        assert flags[0]["status"] == "DSQ"
        assert flags[0]["swimmer"] == "Skye Munro"
        # DSQ swimmer must not appear as a countable swim anywhere.
        names = [s.swimmer_name for e in meet.events for s in e.swims]
        assert "Skye Munro" not in names

    def test_confidence_high_for_structured_format(self, meet) -> None:
        assert meet.overall_confidence >= 0.9
        for ev in meet.events:
            for s in ev.swims:
                assert s.confidence >= 0.9
                assert s.field_confidence["time"] == 0.95


# ---------------------------------------------------------------------------
# .lxf (zipped .lef) path
# ---------------------------------------------------------------------------


class TestLxfPath:
    def test_lxf_output_equals_lef_output(self) -> None:
        from_lef = parse_lenex(_fixture("mini_results.lef"))
        from_lxf = parse_lenex(_fixture("mini_results.lxf"))
        assert dataclasses.asdict(from_lxf) == dataclasses.asdict(from_lef)

    def test_in_memory_lxf_round_trip(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meet.lef", _fixture("mini_results.lef"))
        meet = parse_lenex(buf.getvalue())
        assert meet.meet_name == "Summer Sprint Gala 2026"
        assert sum(len(e.swims) for e in meet.events) == 3

    def test_zip_with_too_many_members_raises_unsafe(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for i in range(65):  # MAX_ZIP_MEMBERS is 64
                zf.writestr(f"part{i}.lef", b"<LENEX/>")
        with pytest.raises(UnsafeZipError):
            parse_lenex(buf.getvalue())

    def test_compression_bomb_member_raises_unsafe(self) -> None:
        # A .lef member whose declared uncompressed size blows the
        # per-member cap is filtered by _zip_safety; with every .lef
        # member rejected the parser raises honestly instead of guessing.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.lef", b"\x00" * (70 * 1024 * 1024))
        with pytest.raises(UnsafeZipError):
            parse_lenex(buf.getvalue())

    def test_zip_without_lenex_member_is_honest(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", b"nothing to see here")
        meet = parse_lenex(buf.getvalue())
        assert meet.events == []
        assert meet.overall_confidence == 0.0
        assert meet.needs_review[0]["reason"] == "lenex-lxf-no-member"


# ---------------------------------------------------------------------------
# parse_lenex_entries — W.6 feed
# ---------------------------------------------------------------------------


class TestParseLenexEntries:
    def test_entry_rows_exact(self) -> None:
        rows = parse_lenex_entries(_fixture("mini_entries.lef"))
        assert rows == [
            {
                "swimmer_name": "Calum Reid",
                "yob": 2008,
                "gender": "M",
                "club": "Aberdeen Dolphins",
                "distance_m": 100,
                "stroke": "Freestyle",
                "course": "LC",
                "entry_time": "58.20",
                "event_id": "1",
                "session_date": "2026-05-16",
            },
            {
                "swimmer_name": "Euan Park",
                "yob": 2009,
                "gender": "M",
                "club": "Aberdeen Dolphins",
                "distance_m": 100,
                "stroke": "Freestyle",
                "course": "LC",
                "entry_time": None,  # "NT" → no time, never guessed
                "event_id": "1",
                "session_date": "2026-05-16",
            },
            {
                "swimmer_name": "Mhairi Watt",
                "yob": 2010,
                "gender": "F",
                "club": "Granite City SC",
                "distance_m": 50,
                "stroke": "Breaststroke",
                "course": "LC",
                "entry_time": "43.50",
                "event_id": "2",
                "session_date": "2026-05-16",
            },
        ]

    def test_results_file_has_no_entry_rows(self) -> None:
        assert parse_lenex_entries(_fixture("mini_results.lef")) == []

    def test_malformed_xml_yields_empty_list(self) -> None:
        assert parse_lenex_entries(_fixture("malformed.lef")) == []

    def test_entries_only_file_flagged_by_results_parse(self) -> None:
        meet = parse_lenex(_fixture("mini_entries.lef"))
        assert meet.events == []
        reasons = [n["reason"] for n in meet.needs_review]
        assert "lenex-entries-only" in reasons


# ---------------------------------------------------------------------------
# Honest-error path — malformed XML never crashes
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_malformed_xml_returns_needs_review_not_exception(self) -> None:
        meet = parse_lenex(_fixture("malformed.lef"))
        assert meet.events == []
        assert meet.overall_confidence == 0.0
        assert meet.needs_review[0]["reason"] == "lenex-xml-malformed"
        assert meet.sources_used == ["format:lenex"]

    def test_lenex_root_without_meet_flagged(self) -> None:
        meet = parse_lenex(b'<?xml version="1.0"?><LENEX version="3.0"></LENEX>')
        assert meet.events == []
        assert meet.needs_review[0]["reason"] == "lenex-no-meet"


# ---------------------------------------------------------------------------
# Registration — interpret_document + ingest._sniff_format routing
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_interpret_document_with_lef_hint(self) -> None:
        meet = interpret_document(_fixture("mini_results.lef"), hint="results.lef")
        assert meet.sources_used == ["format:lenex"]  # native fast path fired
        assert meet.meet_name == "Summer Sprint Gala 2026"
        assert sum(len(e.swims) for e in meet.events) == 3
        assert meet.overall_confidence >= 0.9

    def test_interpret_document_without_hint_detects_lenex(self) -> None:
        meet = interpret_document(_fixture("mini_results.lef"))
        assert meet.sources_used == ["format:lenex"]
        assert meet.meet_name == "Summer Sprint Gala 2026"

    def test_interpret_document_with_lxf_hint(self) -> None:
        meet = interpret_document(_fixture("mini_results.lxf"), hint="results.lxf")
        assert "format:lenex" in meet.sources_used
        assert meet.meet_name == "Summer Sprint Gala 2026"
        assert sum(len(e.swims) for e in meet.events) == 3

    def test_interpret_document_lxf_without_hint_via_zip_recursion(self) -> None:
        meet = interpret_document(_fixture("mini_results.lxf"))
        assert "format:lenex" in meet.sources_used
        assert meet.meet_name == "Summer Sprint Gala 2026"

    def test_sniff_format_routes_lenex_hints(self) -> None:
        assert _sniff_format(b"", "results.lef") == "lenex"
        assert _sniff_format(b"", "meet.lxf") == "lenex"
        assert _sniff_format(b"", "lenex") == "lenex"

    def test_sniff_format_content_sniffs_lef_bytes(self) -> None:
        assert _sniff_format(_fixture("mini_results.lef")) == "lenex"

    def test_sniff_format_random_xml_is_not_lenex(self) -> None:
        data = b'<?xml version="1.0"?><results><row place="1"/></results>'
        assert _sniff_format(data) != "lenex"


# ---------------------------------------------------------------------------
# XML entity-expansion guard — DOCTYPE-bearing payloads are rejected unparsed
# ---------------------------------------------------------------------------


class TestDoctypeGuard:
    _BOMB = (
        b'<?xml version="1.0"?>\n'
        b"<!DOCTYPE lolz [\n"
        b'  <!ENTITY a "aaaaaaaaaa">\n'
        b'  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        b'  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n'
        b"]>\n"
        b'<LENEX version="3.0"><MEETS><MEET name="&c;"/></MEETS></LENEX>'
    )

    def test_doctype_payload_is_rejected_not_parsed(self) -> None:
        # A billion-laughs-class payload must yield an honest lenex-xml-unsafe
        # flag, never an expanded parse (LENEX never carries a DTD).
        meet = parse_lenex(self._BOMB)
        assert meet.events == []
        assert meet.overall_confidence == 0.0
        reasons = [f["reason"] for f in meet.needs_review]
        assert reasons == ["lenex-xml-unsafe"]

    def test_lowercase_doctype_also_rejected(self) -> None:
        payload = self._BOMB.replace(b"<!DOCTYPE", b"<!doctype")
        meet = parse_lenex(payload)
        assert [f["reason"] for f in meet.needs_review] == ["lenex-xml-unsafe"]

    def test_utf16_doctype_also_rejected(self) -> None:
        # Re-encoding the payload must not dodge the guard.
        payload = self._BOMB.decode("utf-8").encode("utf-16-le")
        meet = parse_lenex(payload)
        assert [f["reason"] for f in meet.needs_review] == ["lenex-xml-unsafe"]

    def test_clean_lenex_still_parses(self) -> None:
        meet = parse_lenex(_fixture("mini_results.lef"))
        assert meet.events, "a legitimate DOCTYPE-free LENEX file must still parse"
        assert not any(f["reason"] == "lenex-xml-unsafe" for f in meet.needs_review)
