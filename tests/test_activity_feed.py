"""tests/test_activity_feed.py — Dashboard activity feed (UI 1.16).

Two layers:

  * **Unit** — the pure builder in ``mediahub.web.activity_feed``: timestamp
    parsing, relative-time + bucketing, per-card workflow aggregation, the
    per-source event builders, and the merge/sort/limit/filter of
    ``build_activity_feed``. No Flask, DB, or filesystem.

  * **Integration** — the ``/activity/feed`` route end-to-end on the Flask test
    client, mirroring ``tests/test_activity_scoping.py``: rendering, the three
    lanes (runs / approvals / exports), the empty state, multi-tenant
    isolation, the ?kind= filter, expandable detail, and HTML-escaping.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mediahub.web import activity_feed as af  # noqa: E402

NOW = datetime(2026, 6, 14, 13, 0, 0, tzinfo=timezone.utc)


def _ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


# ===========================================================================
# Unit — timestamp parsing
# ===========================================================================


class TestParseTs:
    def test_iso_with_offset(self):
        dt = af.parse_ts("2026-06-14T13:00:00+00:00")
        assert dt == NOW

    def test_z_suffix(self):
        assert af.parse_ts("2026-06-14T13:00:00Z") == NOW

    def test_space_separator(self):
        assert af.parse_ts("2026-06-14 13:00:00") == NOW

    def test_naive_assumed_utc(self):
        dt = af.parse_ts("2026-06-14T13:00:00")
        assert dt.tzinfo is not None and dt == NOW

    def test_datetime_passthrough_made_aware(self):
        naive = datetime(2026, 6, 14, 13, 0, 0)
        assert af.parse_ts(naive) == NOW

    def test_subsecond_and_trailing_junk_falls_back_to_prefix(self):
        # A noisy value still yields the leading second-precision slice.
        assert af.parse_ts("2026-06-14T13:00:00.123456 something") == NOW

    @pytest.mark.parametrize("bad", [None, "", "   ", "not-a-date", "garbage"])
    def test_unparseable_is_none(self, bad):
        assert af.parse_ts(bad) is None


# ===========================================================================
# Unit — relative time + buckets
# ===========================================================================


class TestHumanizeAge:
    @pytest.mark.parametrize(
        "secs,expected",
        [
            (5, "just now"),
            (60, "1 min ago"),
            (300, "5 min ago"),
            (3600, "1 hr ago"),
            (7200, "2 hr ago"),
        ],
    )
    def test_recent(self, secs, expected):
        assert af.humanize_age(_ago(seconds=secs), now=NOW) == expected

    def test_yesterday_then_days(self):
        assert af.humanize_age(_ago(days=1), now=NOW) == "yesterday"
        assert af.humanize_age(_ago(days=3), now=NOW) == "3 days ago"

    def test_months_and_years(self):
        assert af.humanize_age(_ago(days=60), now=NOW) == "2 months ago"
        assert af.humanize_age(_ago(days=800), now=NOW) == "2 years ago"

    def test_future_clamps_to_just_now(self):
        assert af.humanize_age((NOW + timedelta(hours=1)).isoformat(), now=NOW) == "just now"

    def test_unparseable_is_empty(self):
        assert af.humanize_age("nonsense", now=NOW) == ""


class TestBucketFor:
    @pytest.mark.parametrize(
        "delta,expected",
        [
            (timedelta(minutes=5), "today"),
            (timedelta(days=1), "yesterday"),
            (timedelta(days=3), "this_week"),
            (timedelta(days=15), "this_month"),
            (timedelta(days=90), "earlier"),
        ],
    )
    def test_buckets(self, delta, expected):
        assert af.bucket_for((NOW - delta).isoformat(), now=NOW) == expected

    def test_future_is_today(self):
        assert af.bucket_for((NOW + timedelta(hours=2)).isoformat(), now=NOW) == "today"

    def test_unparseable_is_earlier(self):
        assert af.bucket_for("nonsense", now=NOW) == "earlier"

    def test_labels_cover_every_bucket(self):
        assert set(af.BUCKET_ORDER) == set(af.BUCKET_LABELS)


# ===========================================================================
# Unit — workflow aggregation
# ===========================================================================


def _state(card_id, status, *, changed="", posted=""):
    """A duck-typed workflow state (dict form) for the builder."""
    return {"card_id": card_id, "status": status, "last_changed_at": changed, "posted_at": posted}


class TestSummariseWorkflow:
    def test_counts_and_latest_review(self):
        states = {
            "c1": _state("c1", "approved", changed=_ago(minutes=30)),
            "c2": _state("c2", "approved", changed=_ago(minutes=10)),
            "c3": _state("c3", "rejected", changed=_ago(minutes=50)),
            "c4": _state("c4", "edited", changed=_ago(minutes=70)),
            "c5": _state("c5", "queue", changed=_ago(minutes=5)),
        }
        summ = af.summarise_workflow(states)
        assert summ["counts"] == {
            "queue": 1, "approved": 2, "rejected": 1, "posted": 0, "edited": 1, "total": 5,
        }
        # Newest review change is the second approval (10 min ago).
        assert summ["review_latest"] == _ago(minutes=10)

    def test_posted_latest_prefers_posted_at(self):
        states = {
            "c1": _state("c1", "posted", changed=_ago(minutes=90), posted=_ago(minutes=20)),
        }
        summ = af.summarise_workflow(states)
        assert summ["counts"]["posted"] == 1
        assert summ["posted_latest"] == _ago(minutes=20)

    def test_posted_falls_back_to_last_changed(self):
        states = {"c1": _state("c1", "posted", changed=_ago(minutes=40))}
        assert af.summarise_workflow(states)["posted_latest"] == _ago(minutes=40)

    def test_empty(self):
        summ = af.summarise_workflow({})
        assert summ["counts"]["total"] == 0
        assert summ["review_latest"] == "" and summ["posted_latest"] == ""

    def test_accepts_real_cardworkflowstate(self):
        from mediahub.workflow.status import CardStatus, CardWorkflowState

        states = {
            "c1": CardWorkflowState(card_id="c1", status=CardStatus.APPROVED, last_changed_at=_ago(minutes=12)),
            "c2": CardWorkflowState(card_id="c2", status=CardStatus.POSTED, posted_at=_ago(minutes=4)),
        }
        summ = af.summarise_workflow(states)
        assert summ["counts"]["approved"] == 1
        assert summ["counts"]["posted"] == 1
        assert summ["posted_latest"] == _ago(minutes=4)


# ===========================================================================
# Unit — per-source event builders
# ===========================================================================


class TestRunEvent:
    def _run(self, **over):
        base = {
            "id": "r1", "created_at": _ago(hours=2), "finished_at": _ago(hours=2, minutes=-1),
            "status": "done", "meet_name": "County Champs", "file_name": "county.pdf",
            "our_swims": 12, "n_achievements": 5, "n_queue": 3, "error": None,
        }
        base.update(over)
        return af._run_event(base)

    def test_done(self):
        e = self._run()
        assert e.kind == af.KIND_RUN and e.subkind == "run_done"
        assert e.status_tone == af.TONE_GOOD and e.status_label == "completed"
        assert "12 swims matched" in e.summary and "5 moments detected" in e.summary
        assert e.run_id == "r1"

    def test_error_is_bad_with_excerpt(self):
        e = self._run(status="error", error="parse failed: bad header")
        assert e.subkind == "run_error" and e.status_tone == af.TONE_BAD
        assert e.summary == "parse failed: bad header"
        assert ("Error", "parse failed: bad header") in e.detail

    def test_running_is_info(self):
        e = self._run(status="running", finished_at=None)
        assert e.subkind == "run_running" and e.status_tone == af.TONE_INFO

    def test_terminal_run_anchored_on_finish(self):
        e = self._run(status="done", created_at=_ago(hours=3), finished_at=_ago(hours=1))
        assert e.ts == _ago(hours=1)

    def test_running_anchored_on_created(self):
        e = self._run(status="running", created_at=_ago(minutes=5), finished_at=None)
        assert e.ts == _ago(minutes=5)

    def test_title_fallback_chain(self):
        assert af._run_event({"id": "r9", "status": "done"}).title == "r9"
        assert af._run_event({"id": "r9", "file_name": "f.pdf", "status": "done"}).title == "f.pdf"


class TestApprovalEvent:
    def test_emitted_with_label_precedence(self):
        summ = {"counts": {"approved": 2, "rejected": 1, "edited": 0, "posted": 0, "queue": 0, "total": 3},
                "review_latest": _ago(minutes=10), "posted_latest": ""}
        e = af._approval_event("r1", {"meet_name": "County"}, summ)
        assert e.kind == af.KIND_APPROVAL and e.status_label == "approved"
        assert e.status_tone == af.TONE_GOOD
        assert "2 approved" in e.summary and "1 rejected" in e.summary
        assert e.ts == _ago(minutes=10) and e.title == "County"

    def test_rejected_only_is_warn(self):
        summ = {"counts": {"approved": 0, "rejected": 3, "edited": 0, "posted": 0, "queue": 0, "total": 3},
                "review_latest": _ago(minutes=5), "posted_latest": ""}
        e = af._approval_event("r1", {}, summ)
        assert e.status_label == "rejected" and e.status_tone == af.TONE_WARN

    def test_edited_only_is_info(self):
        summ = {"counts": {"approved": 0, "rejected": 0, "edited": 2, "posted": 0, "queue": 0, "total": 2},
                "review_latest": _ago(minutes=5), "posted_latest": ""}
        e = af._approval_event("r1", {}, summ)
        assert e.status_label == "edited" and e.status_tone == af.TONE_INFO

    def test_no_event_without_review_activity(self):
        summ = {"counts": {"approved": 0, "rejected": 0, "edited": 0, "posted": 4, "queue": 1, "total": 5},
                "review_latest": "", "posted_latest": _ago(minutes=1)}
        assert af._approval_event("r1", {}, summ) is None


class TestExportEvents:
    def test_posted_export(self):
        summ = {"counts": {"approved": 0, "rejected": 0, "edited": 0, "posted": 3, "queue": 0, "total": 3},
                "review_latest": "", "posted_latest": _ago(minutes=2)}
        e = af._posted_export_event("r1", {"meet_name": "County"}, summ)
        assert e.kind == af.KIND_EXPORT and e.subkind == "posted"
        assert e.status_tone == af.TONE_GOOD and "3 cards marked posted" in e.summary
        assert e.ts == _ago(minutes=2)

    def test_no_posted_export_when_zero(self):
        summ = {"counts": {"approved": 1, "rejected": 0, "edited": 0, "posted": 0, "queue": 0, "total": 1},
                "review_latest": _ago(minutes=2), "posted_latest": ""}
        assert af._posted_export_event("r1", {}, summ) is None


# ===========================================================================
# Unit — the merged builder
# ===========================================================================


class TestBuildFeed:
    def _data(self):
        runs = [
            {"id": "r1", "created_at": _ago(hours=2), "finished_at": _ago(hours=2),
             "status": "done", "meet_name": "County Champs", "our_swims": 12, "n_achievements": 5},
            {"id": "r2", "created_at": _ago(hours=1), "finished_at": _ago(hours=1),
             "status": "error", "meet_name": "Regional", "error": "boom"},
        ]
        wf = {"r1": {
            "c1": _state("c1", "approved", changed=_ago(minutes=40)),
            "c2": _state("c2", "posted", posted=_ago(minutes=20)),
        }}
        return runs, wf

    def test_merge_sort_newest_first(self):
        runs, wf = self._data()
        events = af.build_activity_feed(runs=runs, workflow_by_run=wf)
        # 2 runs + 1 approval + 1 posted-export = 4
        assert len(events) == 4
        times = [af.parse_ts(e.ts) for e in events]
        assert times == sorted(times, reverse=True)
        # Newest is the 20-min-ago posted-card export.
        assert events[0].kind == af.KIND_EXPORT and events[0].subkind == "posted"

    def test_counts(self):
        runs, wf = self._data()
        events = af.build_activity_feed(runs=runs, workflow_by_run=wf)
        assert af.feed_counts(events) == {"all": 4, "run": 2, "approval": 1, "export": 1}

    def test_kind_filter(self):
        runs, wf = self._data()
        for kind in (af.KIND_RUN, af.KIND_APPROVAL, af.KIND_EXPORT):
            events = af.build_activity_feed(runs=runs, workflow_by_run=wf, kind=kind)
            assert events and all(e.kind == kind for e in events)

    def test_invalid_kind_returns_all(self):
        runs, wf = self._data()
        events = af.build_activity_feed(runs=runs, workflow_by_run=wf, kind="bogus")
        assert len(events) == 4

    def test_limit(self):
        runs, wf = self._data()
        assert len(af.build_activity_feed(runs=runs, workflow_by_run=wf, limit=2)) == 2

    def test_run_meta_titles_approval_from_runs(self):
        # The approval event borrows the run's meet name even though only the
        # runs list carries it.
        runs, wf = self._data()
        events = af.build_activity_feed(runs=runs, workflow_by_run=wf)
        approval = next(e for e in events if e.kind == af.KIND_APPROVAL)
        assert approval.title == "County Champs"

    def test_unparseable_timestamps_sort_last_not_crash(self):
        runs = [{"id": "r1", "status": "done", "created_at": "garbage", "finished_at": "garbage"}]
        events = af.build_activity_feed(runs=runs)
        assert len(events) == 1  # did not raise

    def test_empty_inputs(self):
        assert af.build_activity_feed() == []


# ===========================================================================
# Integration — the /activity/feed route
# ===========================================================================


@pytest.fixture
def feed_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR + org gate, mirroring tests/test_activity_scoping.py."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(profile_id="club-a", display_name="Club A",
                             brand_voice_summary="Friendly."))
    save_profile(ClubProfile(profile_id="club-b", display_name="Club B",
                             brand_voice_summary="Serious."))

    with app.test_client() as c:
        yield c, wm


def _seed_run(wm, run_id, profile_id, meet, *, status="done", error=None):
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?, 6, 0, 2, 4, ?)",
        (run_id, status, profile_id, meet, f"{meet}.pdf", error),
    )
    conn.commit()
    conn.close()


def _pin(client, profile_id):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_data(as_text=True)


class TestFeedRoute:
    def test_renders_runs_approvals_exports(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "County Champs")
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore
        ws = WorkflowStore(wm.RUNS_DIR)
        ws.set_status("r1", "c1", CardStatus.APPROVED)
        ws.set_status("r1", "c2", CardStatus.POSTED)

        _pin(c, "club-a")
        body = c.get("/activity/feed").get_data(as_text=True)
        assert "Activity feed" in body
        assert "County Champs" in body              # run + approval titles
        assert 'data-kind="run"' in body
        assert 'data-kind="approval"' in body
        assert 'data-kind="export"' in body         # the card marked posted
        assert '<article class="mh-feed-item' in body
        assert "<details" in body                   # expandable detail
        assert 'class="tag good"' in body
        assert 'class="mh-rel' in body              # relative timestamps

    def test_empty_state_for_new_org(self, feed_client):
        c, wm = feed_client
        _pin(c, "club-a")
        body = c.get("/activity/feed").get_data(as_text=True)
        assert "Nothing here yet" in body
        assert '<article class="mh-feed-item' not in body

    def test_multi_tenant_isolation(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "ra", "club-a", "Club A meet")
        _seed_run(wm, "rb", "club-b", "Club B meet")
        # Club B approvals + exports that must never appear in Club A's feed.
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore
        ws = WorkflowStore(wm.RUNS_DIR)
        ws.set_status("rb", "c1", CardStatus.APPROVED)

        _pin(c, "club-a")
        body = c.get("/activity/feed").get_data(as_text=True)
        assert "Club A meet" in body
        assert "Club B meet" not in body

    def test_kind_filter_server_side(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "County Champs")
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore
        ws = WorkflowStore(wm.RUNS_DIR)
        ws.set_status("r1", "c1", CardStatus.APPROVED)
        _pin(c, "club-a")

        runs_only = c.get("/activity/feed?kind=run").get_data(as_text=True)
        assert 'data-kind="run"' in runs_only
        assert 'data-kind="approval"' not in runs_only

        appr_only = c.get("/activity/feed?kind=approval").get_data(as_text=True)
        assert 'data-kind="approval"' in appr_only
        assert 'data-kind="run"' not in appr_only

    def test_kind_filter_with_no_matches_shows_notice(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "County Champs")  # a run, but no exports
        _pin(c, "club-a")
        body = c.get("/activity/feed?kind=export").get_data(as_text=True)
        assert "No export activity yet" in body
        assert '<article class="mh-feed-item' not in body

    def test_invalid_kind_shows_all(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "County Champs")
        _pin(c, "club-a")
        body = c.get("/activity/feed?kind=evil';DROP").get_data(as_text=True)
        assert "County Champs" in body
        assert 'data-kind="run"' in body

    def test_view_toggle_present_on_both_views(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "County Champs")
        _pin(c, "club-a")
        feed_body = c.get("/activity/feed").get_data(as_text=True)
        table_body = c.get("/activity").get_data(as_text=True)
        assert ">Runs table<" in feed_body and ">Feed<" in feed_body
        assert ">Runs table<" in table_body and ">Feed<" in table_body
        assert "/activity/feed" in table_body  # discoverable from the table view

    def test_failed_run_renders_bad_badge(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "Broken meet", status="error", error="parse failed")
        _pin(c, "club-a")
        body = c.get("/activity/feed").get_data(as_text=True)
        assert 'class="tag bad"' in body
        assert "Broken meet" in body

    def test_redirects_without_profile(self, feed_client):
        c, wm = feed_client
        resp = c.get("/activity/feed")  # nothing pinned
        assert resp.status_code in (301, 302)

    def test_meet_name_is_html_escaped(self, feed_client):
        c, wm = feed_client
        _seed_run(wm, "r1", "club-a", "<script>alert(1)</script>")
        _pin(c, "club-a")
        body = c.get("/activity/feed").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body
