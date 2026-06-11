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
