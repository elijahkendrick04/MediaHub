"""tests/test_review_body_content.py — /review/<run_id> body-content regression.

Regression guard for the LLM Council finding: a route can return HTTP 200 with
an empty or skeleton body, making a status-only check meaningless.  These tests
prove that /review/<run_id> actually renders the achievement card data (swimmer
names, events, headlines) in its body, not just a 200 shell.
"""
from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _seed_run(tmp_path, wm, profile_id, run_payload):
    """Write run JSON to disk and insert a matching DB row."""
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, run_payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


@pytest.fixture
def review_env(tmp_path, monkeypatch):
    """Fresh DATA_DIR with one club profile and a test client."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="org-test",
        display_name="Test Club",
        brand_voice_summary="Clear and energetic.",
    ))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as client:
        # Pin the session to org-test
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_payload(profile_id, achievements):
    """Build a minimal but realistic run payload with the given achievements."""
    run_id = "run-body-test-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "BODY CONTENT TEST INVITATIONAL"},
        "cards": [
            {
                "card_id": f"card-{a['swim_id']}",
                "swim_id": a["swim_id"],
                "swimmer_name": a["swimmer_name"],
                "event": a["event"],
                "headline": a["headline"],
                "id": f"card-{a['swim_id']}",
            }
            for a in achievements
        ],
        "trust": {"score": 0.85},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": a["swim_id"],
                        "swimmer_name": a["swimmer_name"],
                        "event": a["event"],
                        "headline": a["headline"],
                        "type": a.get("type", "pb"),
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, a in enumerate(achievements)
            ],
            "n_elite": len(achievements),
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": len(achievements),
            "n_swims_analysed": len(achievements),
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


# ---------------------------------------------------------------------------
# Tests: body actually contains card data
# ---------------------------------------------------------------------------

class TestReviewBodyContainsCardData:
    """A 200 from /review/<run_id> must render the achievement content, not a skeleton."""

    def test_body_is_non_empty(self, review_env):
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s1", "swimmer_name": "Jane Smith", "event": "200m Butterfly", "headline": "PB set"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert len(body) > 500, "Response body is suspiciously short — expected rendered HTML"

    def test_swimmer_name_present_in_body(self, review_env):
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s2", "swimmer_name": "Jane Smith", "event": "200m Butterfly", "headline": "PB set"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Jane Smith" in body, (
            "/review body must contain the swimmer name from ranked_achievements; "
            "a 200 with no card content is indistinguishable from a skeleton response"
        )

    def test_event_name_present_in_body(self, review_env):
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s3", "swimmer_name": "Tom Jones", "event": "100m Backstroke", "headline": "Club record"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "100m Backstroke" in body, (
            "/review body must contain the event name from ranked_achievements"
        )

    def test_headline_present_in_body(self, review_env):
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s4", "swimmer_name": "Sam Lee", "event": "50m Freestyle", "headline": "UNIQUE_HEADLINE_XYZ"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "UNIQUE_HEADLINE_XYZ" in body, (
            "/review body must contain the achievement headline from ranked_achievements"
        )

    def test_ach_row_element_present(self, review_env):
        """The .ach-row DOM element is the card container — its presence confirms cards rendered."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s5", "swimmer_name": "Alex Brown", "event": "400m IM", "headline": "Season best"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'class="ach-row"' in body, (
            "/review body must contain .ach-row elements confirming achievement cards rendered"
        )

    def test_data_swimmer_attribute_matches_payload(self, review_env):
        """data-swimmer on .ach-row must match the swimmer name from the run payload."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s6", "swimmer_name": "Riley Park", "event": "200m Breaststroke", "headline": "New PB"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'data-swimmer="Riley Park"' in body, (
            "data-swimmer attribute on .ach-row must match the swimmer name from the run"
        )

    def test_multiple_achievements_all_rendered(self, review_env):
        """Every achievement in ranked_achievements must appear in the body."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        achievements = [
            {"swim_id": "s7a", "swimmer_name": "Swimmer Alpha", "event": "100m Free", "headline": "PB Alpha"},
            {"swim_id": "s7b", "swimmer_name": "Swimmer Beta", "event": "200m Back", "headline": "PB Beta"},
            {"swim_id": "s7c", "swimmer_name": "Swimmer Gamma", "event": "50m Fly", "headline": "PB Gamma"},
        ]
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        for ach in achievements:
            assert ach["swimmer_name"] in body, (
                f"Swimmer '{ach['swimmer_name']}' from ranked_achievements missing from /review body"
            )
            assert ach["headline"] in body, (
                f"Headline '{ach['headline']}' from ranked_achievements missing from /review body"
            )

    def test_meet_name_present_in_body(self, review_env):
        """Meet name must appear in the page — basic sanity before card assertions."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [
            {"swim_id": "s8", "swimmer_name": "Any Swimmer", "event": "100m Free", "headline": "PB"},
        ])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "BODY CONTENT TEST INVITATIONAL" in body, (
            "/review body must contain the meet name"
        )

    def test_run_with_no_achievements_shows_empty_state_not_crash(self, review_env):
        """A run with an empty ranked_achievements list must render an empty-state page, not crash."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = _make_run_payload("org-test", [])
        run_id = _seed_run(tmp_path, wm, "org-test", payload)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        # No swimmer data from the empty list
        assert 'class="ach-row"' not in body
        # Empty state should be shown
        assert len(body) > 200, "Response body must not be blank even for a zero-achievement run"

    def test_unknown_run_returns_recovery_page_not_500(self, review_env):
        """A non-existent run_id must show a recovery page, not a 500 or blank body."""
        client = review_env["client"]

        r = client.get("/review/run-does-not-exist-xyz")
        # Either a redirect to home or a rendered recovery page is acceptable;
        # a 500 or empty 200 body is not.
        assert r.status_code in (200, 302, 404)
        if r.status_code == 200:
            body = r.get_data(as_text=True)
            assert len(body) > 100, "Recovery page body must not be blank"
            # Must not contain a Python traceback
            assert "Traceback" not in body
            assert "Internal Server Error" not in body


class TestReviewProgressUsesRankedTotal:
    """Regression guard for the "REVIEWED 3/3 = 100%" false-completion bug.

    The progress strip denominator must be the pipeline's ranked-achievement
    count, not the workflow-store total. With 4 ranked achievements and only 1
    approved, the store total is 1 (only the touched card has a saved state) —
    the buggy code did ``wf_total or n_ranked`` = 1 and rendered "1/1 = 100%
    reviewed" while 3 cards were still queued.

    Unlike the unit test that mirrors the formula in a local helper (it passes on
    the buggy source — "hollow"), this drives the REAL /review route end-to-end.
    """

    def test_progress_denominator_is_ranked_total_not_store_total(self, review_env):
        wm = review_env["wm"]
        client = review_env["client"]
        achievements = [
            {"swim_id": f"swim-{i}", "swimmer_name": f"Swimmer {i}",
             "event": "100m Freestyle", "headline": f"PB for Swimmer {i}"}
            for i in range(4)
        ]
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(review_env["tmp_path"], wm, "org-test", payload)

        # Approve exactly ONE card via the same store the route reads.
        from mediahub.workflow.status import CardStatus
        ws = wm._get_wf_store()
        ws.set_status(run_id, "card-swim-0", CardStatus.APPROVED)
        # The store only knows the 1 card we touched ...
        assert ws.summary(run_id)["total"] == 1
        # ... but the run has 4 ranked achievements.
        assert len(payload["recognition_report"]["ranked_achievements"]) == 4

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        # FIXED: 1 decided / 4 ranked = 25%.
        assert '1<span class="total">/ 4</span>' in body, "denominator must be the ranked total (4)"
        assert 'mh-progress-strip-label">25%<' in body, "1 of 4 reviewed must read 25%"
        # BUG SIGNATURE must be ABSENT: store-total denominator (1) -> 100%.
        assert '1<span class="total">/ 1</span>' not in body
        assert 'mh-progress-strip-label">100%<' not in body


class TestReviewLegacyPbAuditHasRerunButton:
    """Regression guard: legacy-mode PB warning must include an actionable Re-run button.

    Bug: when pb_fetch_ok > 0 but no pb_audit is present, the /review page
    showed "PB fetching used legacy mode. Re-run to see the full audit." with no
    button, leaving the volunteer with degraded data and no path to fix it.
    """

    def _make_legacy_pb_payload(self, profile_id):
        run_id = "run-legacy-pb-" + uuid.uuid4().hex[:8]
        return {
            "run_id": run_id,
            "profile_id": profile_id,
            "profile_display": "Test Club",
            "meet": {"name": "LEGACY PB TEST MEET"},
            "cards": [],
            "pb_fetch_ok": 3,
            "pb_audit": None,
            "trust": {},
            "recognition_report": {
                "ranked_achievements": [],
                "n_elite": 0,
                "n_strong": 0,
                "n_story": 0,
            },
            "parse_warnings": [],
            "self_check": {},
            "detector_summary": {},
            "dispatch_log": {},
        }

    def test_warning_includes_rerun_button_when_input_on_disk(self, review_env):
        """When input.bin exists, the warning card links to the configure re-run page."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = self._make_legacy_pb_payload("org-test")
        run_id = _seed_run(tmp_path, wm, "org-test", payload)
        run_dir = tmp_path / "runs_v4" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "input.bin").write_bytes(b"dummy")

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        assert "per-swimmer audit" in body, (
            "Legacy PB warning text must be present in the review page"
        )
        assert "upload/configure" in body, (
            "Legacy PB warning must include a link to upload/configure for re-run"
        )
        assert run_id in body, (
            "The configure link must embed the run_id so the user is taken to the right run"
        )

    def test_warning_falls_back_to_upload_when_input_missing(self, review_env):
        """When input.bin is gone, the warning card falls back to the upload page."""
        wm = review_env["wm"]
        tmp_path = review_env["tmp_path"]
        client = review_env["client"]

        payload = self._make_legacy_pb_payload("org-test")
        run_id = _seed_run(tmp_path, wm, "org-test", payload)
        # Do NOT create input.bin — simulate an expired upload session.

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        assert "per-swimmer audit" in body, (
            "Legacy PB warning text must be present even without input.bin"
        )
        assert "/upload" in body, (
            "Fallback must link to the upload page when input.bin is not on disk"
        )


class TestBulkApproveButtonVisibility:
    """Regression guard: 'Approve all in queue' must not appear at 100% reviewed.

    Before the fix the button was rendered unconditionally, producing the
    contradictory UI described in the bug report: 'REVIEWED 3/3 = 100%'
    immediately above 'Approve all in queue'.
    """

    def test_bulk_approve_hidden_when_all_reviewed(self, review_env):
        wm = review_env["wm"]
        client = review_env["client"]
        achievements = [
            {"swim_id": f"swim-{i}", "swimmer_name": f"Swimmer {i}",
             "event": "100m Freestyle", "headline": f"PB #{i}"}
            for i in range(3)
        ]
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(review_env["tmp_path"], wm, "org-test", payload)

        from mediahub.workflow.status import CardStatus
        ws = wm._get_wf_store()
        ws.set_status(run_id, "swim-0", CardStatus.APPROVED)
        ws.set_status(run_id, "swim-1", CardStatus.APPROVED)
        ws.set_status(run_id, "swim-2", CardStatus.REJECTED)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        # Progress strip must show 100%.
        assert 'mh-progress-strip-label">100%<' in body, "3/3 reviewed must read 100%"
        # BUG SIGNATURE must be ABSENT: button element must be hidden at 100%.
        # Note: the JS always references getElementById('mh-bulk-approve'), so we
        # check for the HTML attribute id="mh-bulk-approve" (double-quote form),
        # which only appears when the button element is actually rendered.
        assert 'id="mh-bulk-approve"' not in body, "Approve all button must be hidden when fully reviewed"
        assert 'Approve all in queue' not in body

    def test_bulk_approve_visible_when_cards_remain(self, review_env):
        wm = review_env["wm"]
        client = review_env["client"]
        achievements = [
            {"swim_id": f"swim-{i}", "swimmer_name": f"Swimmer {i}",
             "event": "100m Freestyle", "headline": f"PB #{i}"}
            for i in range(3)
        ]
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(review_env["tmp_path"], wm, "org-test", payload)

        from mediahub.workflow.status import CardStatus
        ws = wm._get_wf_store()
        # Approve only 1 of 3 — two still in queue.
        ws.set_status(run_id, "swim-0", CardStatus.APPROVED)

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        # Button element must be present while unreviewed cards remain.
        assert 'id="mh-bulk-approve"' in body, "Approve all button must appear when cards are pending"
        assert 'Approve all in queue' in body

    def test_bulk_approve_visible_with_no_workflow_state(self, review_env):
        wm = review_env["wm"]
        client = review_env["client"]
        achievements = [
            {"swim_id": f"swim-{i}", "swimmer_name": f"Swimmer {i}",
             "event": "100m Freestyle", "headline": f"PB #{i}"}
            for i in range(3)
        ]
        payload = _make_run_payload("org-test", achievements)
        run_id = _seed_run(review_env["tmp_path"], wm, "org-test", payload)
        # No workflow state at all — all cards are implicitly in queue (0% reviewed).

        r = client.get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)

        # Button element must be present when nothing has been reviewed yet.
        assert 'id="mh-bulk-approve"' in body, "Approve all button must appear at 0% reviewed"
        assert 'Approve all in queue' in body
