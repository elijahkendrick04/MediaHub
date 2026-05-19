"""Tests for the V4 canonical schema in `mediahub.web.canonical`.

The canonical Meet schema is the contract every input adapter must
produce — downstream PB enrichment, ranker, captioning, and rendering
all depend on these dataclasses. These tests pin the public API
(`to_dict`, helper methods, constants) so adapters keep producing
schema-compliant output.
"""
from __future__ import annotations

import pytest

from mediahub.web.canonical import (
    COURSE_CODES,
    ROUND_CODES,
    STROKE_CODES,
    Club,
    Meet,
    MeetAdapter,
    ParseWarning,
    RaceResult,
    RelayLeg,
    RelayResult,
    SourceEvidence,
    Split,
    Swimmer,
)


# ---------------------------------------------------------------------------
# Constants — the universe of valid codes adapters must emit
# ---------------------------------------------------------------------------


class TestSchemaConstants:
    def test_stroke_codes_include_swim_strokes(self) -> None:
        # Four standard strokes + IM + relay medley.
        assert {"FR", "BK", "BR", "FL", "IM"}.issubset(STROKE_CODES)
        assert "MEDLEY" in STROKE_CODES

    def test_course_codes_are_LC_SC_Y(self) -> None:
        assert COURSE_CODES == {"LC", "SC", "Y"}

    def test_round_codes_cover_meet_phases(self) -> None:
        assert {"final", "timed_final", "heat", "semi"}.issubset(ROUND_CODES)


# ---------------------------------------------------------------------------
# Swimmer / Club dataclasses
# ---------------------------------------------------------------------------


class TestSwimmer:
    def test_full_name_concatenates(self) -> None:
        s = Swimmer(
            swimmer_key="swim:1",
            first_name="Jane",
            last_name="Smith",
            gender="F",
        )
        assert s.full_name == "Jane Smith"

    def test_full_name_handles_blanks(self) -> None:
        s = Swimmer(swimmer_key="", first_name="", last_name="Smith", gender="")
        assert s.full_name == "Smith"
        s = Swimmer(swimmer_key="", first_name="Jane", last_name="", gender="")
        assert s.full_name == "Jane"
        s = Swimmer(swimmer_key="", first_name="", last_name="", gender="")
        assert s.full_name == ""

    def test_default_identity_confidence(self) -> None:
        s = Swimmer(swimmer_key="x", first_name="A", last_name="B", gender="F")
        assert s.identity_confidence == "high"

    def test_aliases_independent_per_instance(self) -> None:
        # Dataclass default_factory must NOT share lists across instances.
        a = Swimmer(swimmer_key="a", first_name="A", last_name="A", gender="M")
        b = Swimmer(swimmer_key="b", first_name="B", last_name="B", gender="M")
        a.aliases.append("Foo")
        assert b.aliases == []


class TestClub:
    def test_defaults(self) -> None:
        c = Club(code="ABC", name="Aquatic B Club")
        assert c.short_name == ""
        assert c.aliases == []
        assert c.is_host is False
        assert c.extra == {}


# ---------------------------------------------------------------------------
# RaceResult / RelayResult
# ---------------------------------------------------------------------------


class TestRaceResult:
    def test_defaults_for_required_fields(self) -> None:
        r = RaceResult(
            swimmer_key="x",
            club_code="ABC",
            distance=100,
            stroke="FR",
            course="LC",
            gender="F",
        )
        assert r.round == "timed_final"
        assert r.status == "completed"
        assert r.dq is False
        assert r.splits == []

    def test_splits_can_attach(self) -> None:
        r = RaceResult(
            swimmer_key="x",
            club_code="ABC",
            distance=200,
            stroke="FR",
            course="LC",
            gender="F",
            splits=[Split(50, 3010), Split(100, 6080, differential_cs=3070)],
        )
        assert len(r.splits) == 2
        assert r.splits[1].differential_cs == 3070


class TestRelayResult:
    def test_legs_attach(self) -> None:
        relay = RelayResult(
            club_code="ABC",
            distance=200,
            stroke="MEDLEY",
            course="SC",
            gender="M",
            legs=[
                RelayLeg(leg_index=0, leg_stroke="BK", leg_time_cs=2900),
                RelayLeg(leg_index=1, leg_stroke="BR", leg_time_cs=3200),
            ],
        )
        assert len(relay.legs) == 2
        assert relay.legs[0].leg_stroke == "BK"


# ---------------------------------------------------------------------------
# SourceEvidence / ParseWarning
# ---------------------------------------------------------------------------


class TestSourceEvidence:
    def test_to_dict_round_trip(self) -> None:
        ev = SourceEvidence(
            source="Meet results file",
            source_url="https://example.org/meet.pdf",
            retrieved_at="2024-05-01T10:00:00Z",
            confidence="high",
            note="parsed via pdfminer",
        )
        d = ev.to_dict()
        assert d["source"] == "Meet results file"
        assert d["confidence"] == "high"
        assert d["note"] == "parsed via pdfminer"
        assert set(d.keys()) == {
            "source",
            "source_url",
            "retrieved_at",
            "confidence",
            "note",
        }


class TestParseWarning:
    def test_default_severity_info(self) -> None:
        w = ParseWarning(code="missing_dob", message="No DOB found")
        assert w.severity == "info"
        assert w.field is None
        assert w.record is None

    def test_to_dict_keys(self) -> None:
        w = ParseWarning(
            code="ambiguous_course",
            message="Course not in B1 record",
            severity="warn",
            field="course",
            record="swim:50FR_F:Smith,J",
        )
        d = w.to_dict()
        assert d["code"] == "ambiguous_course"
        assert d["severity"] == "warn"
        assert d["field"] == "course"
        assert d["record"] == "swim:50FR_F:Smith,J"


# ---------------------------------------------------------------------------
# Meet — the top-level entity adapters return
# ---------------------------------------------------------------------------


class TestMeet:
    def test_defaults(self) -> None:
        m = Meet()
        assert m.name == "(unknown)"
        assert m.course == "LC"
        assert m.clubs == {}
        assert m.swimmers == {}
        assert m.results == []
        assert m.relays == []
        assert m.warnings == []
        assert m.has_blocking_errors() is False

    def test_add_warning_appends(self) -> None:
        m = Meet()
        m.add_warning("missing_dob", "DOB absent")
        assert len(m.warnings) == 1
        w = m.warnings[0]
        assert w.code == "missing_dob"
        # Default severity in add_warning is "warn", not "info".
        assert w.severity == "warn"

    def test_add_warning_with_field_and_record(self) -> None:
        m = Meet()
        m.add_warning(
            "ambiguous_course",
            "could be SC or LC",
            severity="error",
            field_name="course",
            record="swim:50FR_F:1",
        )
        w = m.warnings[0]
        assert w.severity == "error"
        assert w.field == "course"
        assert w.record == "swim:50FR_F:1"

    def test_has_blocking_errors_detects_error_severity(self) -> None:
        m = Meet()
        m.add_warning("warn_code", "warn", severity="warn")
        assert m.has_blocking_errors() is False
        m.add_warning("err_code", "err", severity="error")
        assert m.has_blocking_errors() is True

    def test_to_dict_has_top_level_keys(self) -> None:
        m = Meet(name="Test Champs", venue="Test Pool", source_format="hy3")
        d = m.to_dict()
        expected = {
            "name",
            "venue",
            "course",
            "start_date",
            "end_date",
            "host_club_code",
            "country",
            "governing_body",
            "clubs",
            "swimmers",
            "results",
            "relays",
            "source_format",
            "source_filename",
            "source_evidence",
            "warnings",
            "inferred_fields",
        }
        assert set(d.keys()) == expected
        assert d["name"] == "Test Champs"
        assert d["source_format"] == "hy3"

    def test_to_dict_serialises_nested_clubs_and_swimmers(self) -> None:
        m = Meet()
        m.clubs["AB-XYZ"] = Club(code="AB-XYZ", name="Aquatic Sharks SC")
        m.swimmers["sw:1"] = Swimmer(
            swimmer_key="sw:1",
            first_name="Jane",
            last_name="Smith",
            gender="F",
        )
        d = m.to_dict()
        assert d["clubs"]["AB-XYZ"]["name"] == "Aquatic Sharks SC"
        assert d["swimmers"]["sw:1"]["first_name"] == "Jane"

    def test_to_dict_serialises_warnings_via_to_dict(self) -> None:
        m = Meet()
        m.add_warning("x", "y", severity="info")
        d = m.to_dict()
        assert d["warnings"][0]["code"] == "x"
        assert d["warnings"][0]["severity"] == "info"

    def test_to_dict_serialises_source_evidence_via_to_dict(self) -> None:
        m = Meet()
        m.source_evidence.append(
            SourceEvidence(source="Meet file", confidence="high")
        )
        d = m.to_dict()
        assert d["source_evidence"][0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# MeetAdapter base class
# ---------------------------------------------------------------------------


class TestMeetAdapter:
    def test_can_parse_defaults_to_zero(self) -> None:
        adapter = MeetAdapter()
        assert adapter.can_parse(b"any bytes", "any.txt") == 0.0

    def test_parse_raises_notimplemented(self) -> None:
        adapter = MeetAdapter()
        with pytest.raises(NotImplementedError):
            adapter.parse(b"x", "y.txt")

    def test_format_id_default(self) -> None:
        assert MeetAdapter.format_id == "abstract"
