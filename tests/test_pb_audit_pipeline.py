"""The discovery pipeline must persist a real per-swimmer PB audit.

Regression for the review-page warning "PB data was fetched but the full
per-swimmer audit wasn't saved": pipeline_v4 fetched PBs via discovery but
never assembled a RunPBAudit, so the V6 audit panel showed the legacy-mode
warning on every single run. _build_pb_audit closes that gap from real
data — discovery snapshots + detector decisions — with no invention.
"""

from types import SimpleNamespace as NS

from mediahub.pipeline.pipeline_v4 import _build_pb_audit


def _meet_two_swimmers():
    return NS(
        swimmers={
            "123456": NS(first_name="Eira", last_name="Hughes"),
            "654321": NS(first_name="Tom", last_name="Davies"),
        }
    )


def _snapshots():
    return {
        "123456": NS(
            pb_times={"100FRLC": [{"time_sec": 61.42}]},
            fetch_ok=True,
            error=None,
            source_url="https://example.org/eira",
            retrieved_at="2026-06-01T10:00:00Z",
        ),
        "654321": NS(
            pb_times={},
            fetch_ok=False,
            error="no PBs found",
            source_url=None,
            retrieved_at=None,
        ),
    }


def _claims():
    return [
        NS(
            kind="pb_confirmed",
            swimmer_tiref="123456",
            swimmer_name="Eira Hughes",
            event_label="100m Freestyle (LC)",
            distance=100,
            stroke="FR",
            course="LC",
            time_str="59.80",
            time_sec=59.8,
            extra={
                "delta_sec": -1.62,
                "prior_time_sec": 61.42,
                "prior_time_str": "1:01.42",
                "prior_date_iso": "2025-11-02",
                "source_url": "https://example.org/eira",
                "retrieved_at": "2026-06-01T10:00:00Z",
            },
        ),
        # Non-PB claims must be ignored by the audit builder.
        NS(
            kind="gold",
            swimmer_tiref="123456",
            swimmer_name="Eira Hughes",
            event_label="100m Freestyle (LC)",
            distance=100,
            stroke="FR",
            course="LC",
            time_str="59.80",
            time_sec=59.8,
            extra={},
        ),
        NS(
            kind="pb_likely",
            swimmer_tiref="654321",
            swimmer_name="Tom Davies",
            event_label="50m Backstroke (LC)",
            distance=50,
            stroke="BK",
            course="LC",
            time_str="31.00",
            time_sec=31.0,
            extra={"note": "no prior history found"},
        ),
    ]


def _build():
    return _build_pb_audit(
        run_id="test-run",
        meet=_meet_two_swimmers(),
        our_swimmer_keys={"123456", "654321"},
        pb_snapshots=_snapshots(),
        claims=_claims(),
        started_at="2026-06-01T09:59:00Z",
        fetch_start_wall=100.0,
        fetch_end_wall=130.5,
    )


class TestBuildPBAudit:
    def test_counts_reflect_detector_decisions(self):
        audit = _build()
        assert audit.swimmers_total == 2
        assert audit.pb_decisions_count == 2
        assert audit.pb_confirmed_count == 1  # CONFIRMED_PB_IMPROVEMENT counts
        assert audit.pb_likely_count == 1
        assert audit.swimmers_fetch_failed == 1
        assert audit.fetch_total_seconds == 30.5

    def test_per_swimmer_entries_carry_fetch_truth(self):
        audit = _build()
        per = {sa.asa_id: sa for sa in audit.per_swimmer}
        ok = per["123456"]
        assert ok.fetch_ok is True
        assert ok.events_fetched == ["100FRLC"]
        assert ok.source_urls == ["https://example.org/eira"]
        failed = per["654321"]
        assert failed.fetch_ok is False
        assert failed.fetch_error == "no PBs found"
        assert failed.source_urls == []

    def test_confirmed_decision_preserves_prior_pb_evidence(self):
        audit = _build()
        per = {sa.asa_id: sa for sa in audit.per_swimmer}
        dec = per["123456"].pb_decisions[0]
        assert dec.status == "CONFIRMED_PB_IMPROVEMENT"
        assert dec.previous_pb is not None
        assert dec.previous_pb.time_display == "1:01.42"
        assert dec.delta_seconds == -1.62
        assert dec.evidence == ["https://example.org/eira"]
        # Improvement percentage derived from delta vs prior, not invented.
        assert dec.improvement_percentage == round(100.0 * 1.62 / 61.42, 2)

    def test_serialises_for_run_persistence(self):
        """The exact path web.py uses to persist the run must round-trip."""
        from swim_content_pb.audit import run_audit_to_dict

        d = run_audit_to_dict(_build())
        assert d["swimmers_total"] == 2
        assert d["per_swimmer"][0]["hy3_name"]
        # identity is honestly absent (discovery does no SR identity match)
        assert all(sa["identity"] is None for sa in d["per_swimmer"])

    def test_no_snapshot_means_no_lookup_attempted(self):
        audit = _build_pb_audit(
            run_id="r2",
            meet=_meet_two_swimmers(),
            our_swimmer_keys={"123456", "999999"},
            pb_snapshots={},
            claims=[],
            started_at="",
            fetch_start_wall=0.0,
            fetch_end_wall=0.0,
        )
        assert audit.swimmers_total == 2
        assert all(not sa.fetch_ok for sa in audit.per_swimmer)
        assert all(sa.fetch_error == "no lookup attempted" for sa in audit.per_swimmer)


# ---------------------------------------------------------------------------
# V5 recognition achievements as a decision source.
#
# Interpreter-parsed runs have no ASA ids, so the V3 detector path produces
# zero claims and the audit used to show zero decisions on every run while
# the cards showed PBs. The audit must map the V5 achievements (keyed by the
# same canonical swimmer_key as the snapshots) into PBDecisions.
# ---------------------------------------------------------------------------


def _meet_interpreter_keys():
    return NS(
        swimmers={
            "anytown_sc:hughes,eira": NS(first_name="Eira", last_name="Hughes"),
            "anytown_sc:davies,tom": NS(first_name="Tom", last_name="Davies"),
        }
    )


def _interpreter_snapshots():
    return {
        "anytown_sc:hughes,eira": NS(
            pb_times={"100FRLC": [{"time_sec": 61.42}]},
            fetch_ok=True,
            error=None,
            no_history=False,
            from_cache=True,
            source_url="https://example.org/eira",
            retrieved_at="2026-06-01T10:00:00Z",
        ),
        "anytown_sc:davies,tom": NS(
            pb_times={},
            fetch_ok=True,
            error=None,
            no_history=True,
            from_cache=False,
            source_url=None,
            retrieved_at=None,
        ),
    }


def _ranked(achievements):
    return [{"rank": i + 1, "achievement": a} for i, a in enumerate(achievements)]


def _v5_pb_confirmed(key="anytown_sc:hughes,eira", name="Eira Hughes"):
    return {
        "type": "pb_confirmed",
        "swim_id": f"{key}:100FRLC:timed_final:pb",
        "swimmer_id": key,
        "swimmer_name": name,
        "event": "100m Freestyle (LC)",
        "headline": f"{name} sets new PB",
        "confidence_label": "high",
        "evidence": [
            {"source_type": "results_file", "source_name": "Meet results"},
            {
                "source_type": "pb_cache",
                "source_name": "example.org",
                "source_url": "https://example.org/eira",
            },
        ],
        "raw_facts": {
            "time_sec": 59.8,
            "time_str": "59.80",
            "prior_pb_sec": 61.42,
            "prior_pb_str": "1:01.42",
            "drop_seconds": 1.62,
            "drop_pct": 2.64,
        },
        "uncertainty_notes": [],
    }


def _build_v5(achievements, *, claims=None, snapshots=None, budget_exceeded=False):
    return _build_pb_audit(
        run_id="test-run-v5",
        meet=_meet_interpreter_keys(),
        our_swimmer_keys=set(_meet_interpreter_keys().swimmers.keys()),
        pb_snapshots=snapshots if snapshots is not None else _interpreter_snapshots(),
        claims=claims or [],
        ranked_achievements=_ranked(achievements),
        started_at="2026-06-01T09:59:00Z",
        fetch_start_wall=100.0,
        fetch_end_wall=130.5,
        budget_exceeded=budget_exceeded,
    )


class TestBuildPBAuditFromV5Recognition:
    def test_v5_pb_confirmed_becomes_audit_decision(self):
        audit = _build_v5([_v5_pb_confirmed()])
        assert audit.pb_decisions_count == 1
        assert audit.pb_confirmed_count == 1
        per = {sa.asa_id: sa for sa in audit.per_swimmer}
        dec = per["anytown_sc:hughes,eira"].pb_decisions[0]
        assert dec.status == "CONFIRMED_PB_IMPROVEMENT"
        assert dec.course == "LC"
        assert dec.current_time_display == "59.80"
        assert dec.previous_pb is not None
        assert dec.previous_pb.time_seconds == 61.42
        assert dec.previous_pb.time_display == "1:01.42"
        assert dec.delta_seconds == -1.62
        assert dec.improvement_percentage == 2.64
        assert dec.evidence == ["https://example.org/eira"]
        assert dec.safe_to_post is True

    def test_official_pb_maps_to_official_status(self):
        ach = {
            "type": "official_pb_confirmed",
            "swim_id": "anytown_sc:hughes,eira:100FRLC:timed_final:official_pb",
            "swimmer_id": "anytown_sc:hughes,eira",
            "swimmer_name": "Eira Hughes",
            "event": "100m Freestyle (LC)",
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "live_research",
                    "source_name": "example.org",
                    "source_url": "https://example.org/eira",
                }
            ],
            "raw_facts": {
                "time_str": "59.80",
                "time_cs": 5980,
                "pb_decision_status": "CONFIRMED_OFFICIAL_PB",
                "reason": "Time and date match the swimmer's listed all-time PB.",
            },
        }
        audit = _build_v5([ach])
        assert audit.pb_confirmed_official_count == 1
        assert audit.pb_confirmed_count == 1
        dec = {sa.asa_id: sa for sa in audit.per_swimmer}["anytown_sc:hughes,eira"].pb_decisions[0]
        assert dec.status == "CONFIRMED_OFFICIAL_PB"
        assert dec.current_time_seconds == 59.8
        assert dec.safe_to_post is True

    def test_pb_likely_maps_with_uncertainty(self):
        ach = {
            "type": "pb_likely",
            "swim_id": "anytown_sc:davies,tom:50BKLC:timed_final:pb_likely",
            "swimmer_id": "anytown_sc:davies,tom",
            "swimmer_name": "Tom Davies",
            "event": "50m Backstroke (LC)",
            "confidence_label": "medium",
            "evidence": [],
            "raw_facts": {"time_sec": 31.0, "time_str": "31.00"},
            "uncertainty_notes": ["no prior PB data available"],
        }
        audit = _build_v5([ach])
        assert audit.pb_likely_count == 1
        dec = {sa.asa_id: sa for sa in audit.per_swimmer}["anytown_sc:davies,tom"].pb_decisions[0]
        assert dec.status == "LIKELY_PB"
        assert dec.safe_to_post is False
        assert dec.uncertainty_notes == ["no prior PB data available"]

    def test_derivative_achievement_types_are_not_double_counted(self):
        magnitude = dict(_v5_pb_confirmed())
        magnitude["type"] = "pb_magnitude_big"
        audit = _build_v5([_v5_pb_confirmed(), magnitude])
        assert audit.pb_decisions_count == 1

    def test_v3_claim_for_same_event_is_deduped(self):
        claim = NS(
            kind="pb_confirmed",
            swimmer_tiref="anytown_sc:hughes,eira",
            swimmer_name="Eira Hughes",
            event_label="100m Freestyle (LC)",
            distance=100,
            stroke="FR",
            course="LC",
            time_str="59.80",
            time_sec=59.8,
            extra={"prior_time_sec": 61.42, "delta_sec": -1.62},
        )
        audit = _build_v5([_v5_pb_confirmed()], claims=[claim])
        assert audit.pb_decisions_count == 1

    def test_budget_flag_flows_to_run_audit(self):
        audit = _build_v5([], budget_exceeded=True)
        assert audit.fetch_budget_exceeded is True

    def test_cache_hits_counted_from_snapshots(self):
        audit = _build_v5([])
        assert audit.cache_hits == 1
        assert audit.cache_misses == 1

    def test_no_history_counted_separately_from_failures(self):
        audit = _build_v5([])
        assert audit.swimmers_no_history == 1
        assert audit.swimmers_fetch_failed == 0
        per = {sa.asa_id: sa for sa in audit.per_swimmer}
        assert per["anytown_sc:davies,tom"].no_history is True
        assert per["anytown_sc:davies,tom"].fetch_error is None
