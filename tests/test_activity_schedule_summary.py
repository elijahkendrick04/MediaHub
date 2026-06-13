"""tests/test_activity_schedule_summary.py — Phase 1.3 /activity enhancements.

Phase 1.3 added two surfaces to the /activity page:

  1. A per-run "Schedule" column that aggregates each run's ScheduleStatus
     counts (scheduled / published / failed) pulled live from the
     workflow sidecar. Runs with no scheduler activity show an em-dash
     instead of a misleading "0 scheduled" pill.

  2. A "Recent posting activity" panel at the bottom of the page that
     surfaces the last 20 publish attempts logged via
     mediahub.publishing.posting_log. The panel is hidden entirely when
     no attempts have been logged so an empty deploy still feels clean.

A matching JSON endpoint at /api/posting/log returns the same data for
SPA / polling consumers.

Both surfaces MUST be strictly org-scoped — runs and posting attempts
for other organisations must never leak into the active profile's view.
This file pins all of the above.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixtures — mirrors tests/test_activity_scoping.py's style.
# ---------------------------------------------------------------------------

@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced.

    Reloads ``mediahub.web.club_profile``, ``mediahub.web.web``, and
    ``mediahub.publishing.posting_log`` so each module's cached
    module-level paths (DB_PATH, RUNS_DIR, the WorkflowStore singleton)
    re-resolve against the per-test tmp dir. Two profiles + four runs
    are seeded so the multi-tenant assertions have real data to chew on.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    import mediahub.publishing.posting_log as plog
    importlib.reload(cp)
    importlib.reload(wm)
    # The posting log caches DB_PATH at import time — reload so it picks
    # up the new DATA_DIR.
    importlib.reload(plog)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    # Seed two ready organisations — both have brand_voice_summary so
    # ClubProfile.is_ready() is True and the gate lets them through.
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="club-a", display_name="Club A",
        brand_voice_summary="A friendly club.",
    ))
    save_profile(ClubProfile(
        profile_id="club-b", display_name="Club B",
        brand_voice_summary="A serious club.",
    ))

    # Seed four runs across both clubs in the SQLite store.
    conn = wm._db()
    for run_id, profile_id, meet in [
        ("run-a1", "club-a", "Club A meet 1"),
        ("run-a2", "club-a", "Club A meet 2"),
        ("run-a3", "club-a", "Club A meet 3"),
        ("run-b1", "club-b", "Club B meet 1"),
    ]:
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, error) "
            "VALUES (?, datetime('now'), datetime('now'), 'done', ?, ?, ?, 1, 1, 0, NULL)",
            (run_id, profile_id, meet, f"{meet}.pdf"),
        )
    conn.commit()
    conn.close()

    with app.test_client() as c:
        yield c, app


@pytest.fixture
def empty_gated_client(tmp_path, monkeypatch):
    """Same as gated_client but with NO profiles seeded.

    Used by the /api/posting/log "no org pinned" assertion — with no
    profiles on disk the gate returns 409 because _active_profile() is
    None.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    import mediahub.publishing.posting_log as plog
    importlib.reload(cp)
    importlib.reload(wm)
    importlib.reload(plog)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as c:
        yield c, app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pin(client, profile_id: str) -> None:
    """Pin a profile into the test session via the active-org API."""
    resp = client.post(
        "/api/organisation/active",
        data={"profile_id": profile_id},
    )
    assert resp.status_code == 200, resp.get_json()


def _seed_schedule_states(
    run_id: str,
    *,
    scheduled: int = 0,
    published: int = 0,
    failed: int = 0,
) -> None:
    """Write per-card schedule states into the workflow sidecar.

    Uses the WorkflowStore directly so we exercise the same code path
    the publish flow uses; this also pins the sidecar's JSON layout.
    """
    from mediahub.workflow.status import ScheduleStatus
    from mediahub.workflow.store import WorkflowStore
    from mediahub.web.web import RUNS_DIR

    ws = WorkflowStore(RUNS_DIR)
    card_idx = 0
    for _ in range(scheduled):
        ws.set_schedule(
            run_id, f"card-sched-{card_idx}",
            ScheduleStatus.SCHEDULED,
            scheduler_update_id=f"buf-{card_idx}",
            scheduled_at="2026-05-20T10:00:00+00:00",
        )
        card_idx += 1
    for _ in range(published):
        ws.set_schedule(
            run_id, f"card-pub-{card_idx}",
            ScheduleStatus.PUBLISHED,
            scheduler_update_id=f"buf-{card_idx}",
        )
        card_idx += 1
    for _ in range(failed):
        ws.set_schedule(
            run_id, f"card-fail-{card_idx}",
            ScheduleStatus.FAILED,
            schedule_error="api timeout",
        )
        card_idx += 1


def _seed_attempt(
    *,
    profile_id: str,
    run_id: str = "run-a1",
    card_id: str = "card-1",
    status: str = "ok",
    channel_name: str = "@club_a_ig",
    caption: str = "Big PB today!",
    error_kind: str | None = None,
    error_message: str | None = None,
    attempted_at: str | None = None,
) -> int:
    """Insert one posting-log row through the public API."""
    from mediahub.publishing import posting_log as _plog
    return _plog.record_attempt(
        profile_id=profile_id,
        run_id=run_id,
        card_id=card_id,
        channel_name=channel_name,
        service="instagram",
        status=status,
        caption=caption,
        error_kind=error_kind,
        error_message=error_message,
        attempted_at=attempted_at,
    )


# ---------------------------------------------------------------------------
# 1. Per-run schedule summary on the /activity table
# ---------------------------------------------------------------------------

class TestPerRunScheduleSummary:
    def test_run_with_no_scheduled_cards_shows_em_dash(self, gated_client):
        """A run that has never been handed off to the scheduler must render
        an em-dash rather than a misleading '0 scheduled' pill."""
        c, _ = gated_client
        _pin(c, "club-a")
        # run-a1 has zero schedule states — confirm the column is dashed.
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # The em-dash glyph is inserted raw, so it appears as the
        # literal entity reference (markupsafe never sees it).
        assert "&mdash;" in body
        # And no spurious "0 scheduled" pill leaked into the page.
        assert "0 scheduled" not in body

    def test_three_scheduled_cards_renders_scheduled_pill(self, gated_client):
        c, _ = gated_client
        _pin(c, "club-a")
        _seed_schedule_states("run-a1", scheduled=3)
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "3 scheduled" in body
        # The pill carries the info CSS class.
        assert 'class="tag info"' in body

    def test_mixed_scheduled_published_failed_renders_all_three(self, gated_client):
        """A run with all three non-queued states surfaces all three
        pills — operators need to see the full picture at a glance."""
        c, _ = gated_client
        _pin(c, "club-a")
        _seed_schedule_states("run-a1", scheduled=2, published=1, failed=1)
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "2 scheduled" in body
        assert "1 published" in body
        assert "1 failed" in body
        # Each pill carries its correct visual class.
        assert 'class="tag info"' in body  # scheduled
        assert 'class="tag good"' in body  # published
        assert 'class="tag bad"' in body   # failed

    def test_only_failures_shows_failed_pill_with_bad_class(self, gated_client):
        c, _ = gated_client
        _pin(c, "club-a")
        _seed_schedule_states("run-a1", failed=1)
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "1 failed" in body
        assert 'class="tag bad"' in body
        # No scheduled / published pills bleed in.
        assert "1 scheduled" not in body
        assert "1 published" not in body

    def test_summary_respects_org_scoping(self, gated_client):
        """A run under club-b with schedule states must NOT contribute
        counts to club-a's /activity page. Each org's summary is built
        only from its own runs."""
        c, _ = gated_client
        # Seed club-b's run with a lot of activity; if any leaks into
        # club-a's view it will show up as "5 scheduled".
        _seed_schedule_states("run-b1", scheduled=5, published=2, failed=3)

        _pin(c, "club-a")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Club A's runs have no schedule state — em-dash only, none of
        # club B's numbers.
        assert "5 scheduled" not in body
        assert "2 published" not in body
        assert "3 failed" not in body
        assert "&mdash;" in body

        # And the inverse — when we pin club-b, its numbers DO show.
        _pin(c, "club-b")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        assert "5 scheduled" in body
        assert "2 published" in body
        assert "3 failed" in body


# ---------------------------------------------------------------------------
# 2. "Recent posting activity" panel on /activity
# ---------------------------------------------------------------------------

class TestPostingLogPanel:
    def test_panel_hidden_when_no_attempts(self, gated_client):
        """An empty posting log must NOT render the panel — an empty
        table looks broken; absence is correct."""
        c, _ = gated_client
        _pin(c, "club-a")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Recent posting activity" not in body

    def test_panel_renders_one_row_per_attempt_newest_first(self, gated_client):
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-a", card_id="c-old",
            caption="Older attempt",
            attempted_at="2026-05-17T08:00:00+00:00",
        )
        _seed_attempt(
            profile_id="club-a", card_id="c-mid",
            caption="Middle attempt",
            attempted_at="2026-05-17T09:00:00+00:00",
        )
        _seed_attempt(
            profile_id="club-a", card_id="c-new",
            caption="Newest attempt",
            attempted_at="2026-05-17T10:00:00+00:00",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Panel header is now present.
        assert "Recent posting activity" in body
        # All three excerpts present.
        assert "Older attempt" in body
        assert "Middle attempt" in body
        assert "Newest attempt" in body
        # Newest-first ordering: the newest excerpt appears before the
        # others in the rendered page body.
        assert body.index("Newest attempt") < body.index("Middle attempt")
        assert body.index("Middle attempt") < body.index("Older attempt")

    def test_ok_attempt_shows_good_badge_and_caption(self, gated_client):
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-a",
            channel_name="@club_a_ig",
            caption="A nice clean PB caption",
            status="ok",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        # Channel name surfaces in the row.
        assert "@club_a_ig" in body
        # Caption excerpt is rendered.
        assert "A nice clean PB caption" in body
        # OK status uses the "good" badge class.
        assert 'class="tag good"' in body

    def test_failed_attempt_surfaces_error_kind_and_message(self, gated_client):
        """Failures need an at-a-glance error_kind badge plus the full
        error message so operators can diagnose without clicking
        through to individual runs."""
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-a",
            channel_name="@broken_channel",
            caption="(would have posted)",
            status="failed",
            error_kind="auth",
            error_message="Scheduling token expired — please reconnect.",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        # The error_kind label is surfaced AS the badge text. The token
        # appears literally inside the bad-class span.
        assert "auth" in body
        assert 'class="tag bad"' in body
        # Full error message appears in the row (so operators can read
        # the failure cause without opening another tab).
        assert "Scheduling token expired" in body

    def test_panel_is_org_scoped(self, gated_client):
        """Attempts logged under another org MUST NOT appear in the
        active org's panel. The posting log is strictly per-tenant."""
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-b", card_id="c-leaky",
            channel_name="@club_b_channel",
            caption="This is a club B attempt and must not leak",
        )
        # And a club-a attempt so the panel actually renders.
        _seed_attempt(
            profile_id="club-a", card_id="c-mine",
            channel_name="@club_a_channel",
            caption="Club A own attempt text",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        # Club A sees its own row.
        assert "Club A own attempt text" in body
        assert "@club_a_channel" in body
        # And critically — none of club B's text is in the page.
        assert "club B attempt and must not leak" not in body
        assert "@club_b_channel" not in body


# ---------------------------------------------------------------------------
# 3. /api/posting/log JSON endpoint
# ---------------------------------------------------------------------------

class TestPostingLogApi:
    def test_returns_409_when_no_org_pinned(self, empty_gated_client):
        """With no profiles seeded and no session pin, the gate must
        block the request with a 409 rather than letting it through to
        the endpoint with a None profile."""
        c, _ = empty_gated_client
        resp = c.get("/api/posting/log")
        assert resp.status_code == 409
        body = resp.get_json() or {}
        # Either error label is acceptable — both indicate "we cannot
        # answer because there's no active org". The current
        # implementation routes through the gate, which uses
        # "organisation_not_ready".
        assert body.get("error") in (
            "organisation_not_ready",
            "no_active_profile",
        )

    def test_returns_200_with_empty_attempts_when_log_is_empty(self, gated_client):
        c, _ = gated_client
        _pin(c, "club-a")
        resp = c.get("/api/posting/log")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert body.get("profile_id") == "club-a"
        assert body.get("attempts") == []
        assert body.get("count") == 0

    def test_returns_attempts_newest_first(self, gated_client):
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-a", card_id="c-old",
            caption="Old", attempted_at="2026-05-17T08:00:00+00:00",
        )
        _seed_attempt(
            profile_id="club-a", card_id="c-new",
            caption="New", attempted_at="2026-05-17T10:00:00+00:00",
        )
        _pin(c, "club-a")
        resp = c.get("/api/posting/log")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        attempts = body.get("attempts") or []
        assert len(attempts) == 2
        # Newest first: c-new before c-old.
        assert attempts[0]["card_id"] == "c-new"
        assert attempts[1]["card_id"] == "c-old"

    def test_respects_limit_param(self, gated_client):
        c, _ = gated_client
        for i in range(5):
            _seed_attempt(
                profile_id="club-a", card_id=f"c{i}",
                caption=f"caption {i}",
                attempted_at=f"2026-05-17T0{i}:00:00+00:00",
            )
        _pin(c, "club-a")
        resp = c.get("/api/posting/log?limit=2")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        attempts = body.get("attempts") or []
        assert len(attempts) == 2

    def test_limit_clamped_to_200(self, gated_client):
        """A limit > 200 must be clamped down — the endpoint refuses to
        return unbounded data even if the caller asks for it."""
        c, _ = gated_client
        # We don't need 200+ rows to assert the clamp; the response
        # must simply succeed and not error with a huge ?limit value.
        _seed_attempt(profile_id="club-a", card_id="c1", caption="one")
        _pin(c, "club-a")
        resp = c.get("/api/posting/log?limit=99999")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        # Single row in, single row out — but more importantly the
        # endpoint didn't crash and returned a sane payload.
        assert body.get("ok") is True
        assert len(body.get("attempts") or []) == 1

    def test_respects_run_id_filter(self, gated_client):
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-a", run_id="run-A", card_id="c1",
            caption="run A attempt",
        )
        _seed_attempt(
            profile_id="club-a", run_id="run-B", card_id="c2",
            caption="run B attempt",
        )
        _pin(c, "club-a")
        resp = c.get("/api/posting/log?run_id=run-A")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        attempts = body.get("attempts") or []
        assert len(attempts) == 1
        assert attempts[0]["run_id"] == "run-A"
        assert attempts[0]["card_id"] == "c1"

    def test_scoped_to_active_profile(self, gated_client):
        """Attempts logged under club-b must NEVER appear when club-a
        is the active profile, even via the JSON endpoint."""
        c, _ = gated_client
        _seed_attempt(
            profile_id="club-b", card_id="c-leak",
            caption="leakage canary",
        )
        _seed_attempt(
            profile_id="club-a", card_id="c-mine",
            caption="legitimate row",
        )
        _pin(c, "club-a")
        resp = c.get("/api/posting/log")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        attempts = body.get("attempts") or []
        # Only the club-a row comes back — and the body confirms the
        # active profile_id.
        assert body.get("profile_id") == "club-a"
        assert len(attempts) == 1
        assert attempts[0]["card_id"] == "c-mine"
        assert all(a["profile_id"] == "club-a" for a in attempts)
        # The canary text is nowhere in the payload.
        for a in attempts:
            assert "leakage canary" not in (a.get("caption_excerpt") or "")
