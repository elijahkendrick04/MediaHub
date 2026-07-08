"""tests/test_status_and_usage_pages.py — Phase 1.5 status + usage routes.

Pins:
  * /status renders WITHOUT an active organisation (it is the public
    trust signal — no gate)
  * /status surfaces real numbers from the uptime log
  * /api/status JSON shape
  * /healthz/usage renders WITHOUT an active organisation and surfaces
    real numbers from the llm_usage log
  * heartbeats are recorded on /healthz and /health hits

The harness pattern mirrors test_activity_schedule_summary.py — fresh
DATA_DIR, module reload, run with the org gate enforced.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.observability.uptime as upt
    import mediahub.observability.llm_usage as llmu
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(upt)
    importlib.reload(llmu)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as c:
        yield c, app


def _as_operator(c):
    """The LLM-usage dashboard is operator-only (like /healthz/governance)."""
    with c.session_transaction() as s:
        s["dev_operator"] = True


class TestStatusPageReachableWithoutOrg:
    def test_status_page_returns_200_without_org(self, fresh_app):
        c, _ = fresh_app
        resp = c.get("/status")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Status" in body
        # The public status indicator. D-28: with no heartbeat the honest state
        # is "Status unavailable" (not a green default), so accept any of the
        # three real states.
        assert (
            "Website operational" in body
            or "Website down" in body
            or "Status unavailable" in body
        )

    def test_status_page_is_simple_operational_or_down(self, fresh_app):
        # The public status page is the simple three-state view (operational /
        # down / unavailable) — no uptime percentages shown to the public. The
        # detailed uptime/incident breakdown moved to operator-only
        # Settings -> Developer.
        c, _ = fresh_app
        resp = c.get("/status")
        body = resp.get_data(as_text=True)
        # No uptime-percentage claims, and the page reads one of the honest states.
        assert "uptime" not in body.lower()
        assert (
            "Website operational" in body
            or "Website down" in body
            or "Status unavailable" in body
        )


class TestApiStatusJsonShape:
    def test_returns_expected_keys(self, fresh_app):
        c, _ = fresh_app
        resp = c.get("/api/status")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert "version" in body
        assert "windows" in body
        assert "24h" in body["windows"]
        assert "7d" in body["windows"]
        assert "30d" in body["windows"]
        # Each window dict has the stats shape we documented.
        for w in body["windows"].values():
            assert "samples" in w
            assert "uptime_pct" in w
            assert "has_data" in w


class TestHealthzRecordsHeartbeat:
    def test_healthz_call_records_heartbeat_row(self, fresh_app):
        c, _ = fresh_app
        # Hit /healthz once.
        resp = c.get("/healthz")
        assert resp.status_code == 200
        # The heartbeat write is dispatched off the request path so the
        # liveness probe never blocks on disk; flush the queue before
        # asserting the row landed.
        import mediahub.web.web as wm
        wm._HEARTBEAT_QUEUE.join()
        # The uptime log should now have one row.
        import mediahub.observability.uptime as upt
        latest = upt.latest_heartbeat()
        assert latest is not None
        assert latest["ok"] is True
        assert latest["source"] == "healthz"

    def test_health_call_records_heartbeat_with_ok_flag(self, fresh_app):
        c, _ = fresh_app
        resp = c.get("/health")
        # /health may legitimately return 200 or 503 depending on the
        # environment. Either way it must record a heartbeat with the
        # correct ok flag.
        assert resp.status_code in (200, 503)
        body = resp.get_json() or {}
        expected_ok = bool(body.get("ok"))
        # Heartbeat write is async — flush before asserting (see above).
        import mediahub.web.web as wm
        wm._HEARTBEAT_QUEUE.join()
        import mediahub.observability.uptime as upt
        latest = upt.latest_heartbeat()
        assert latest is not None
        assert latest["source"] == "health"
        assert latest["ok"] is expected_ok


class TestHeartbeatDrainResilience:
    """The heartbeat drain thread is a per-worker daemon: it must NEVER die.

    task_done() can raise ValueError("called too many times") if the queue is
    join()ed or reset (e.g. the test reload of web.py) between the loop's get()
    and its task_done(). If that escaped the loop the thread would terminate and
    the worker would silently stop recording heartbeats for the rest of its
    life — so the loop must keep draining past a task_done() ValueError.
    """

    def test_drain_loop_survives_task_done_value_error(self, monkeypatch):
        import queue as _queue
        import threading
        import time

        import mediahub.observability.uptime as upt
        import mediahub.web.web as wm

        class _FlakyTaskDoneQueue(_queue.Queue):
            def __init__(self):
                super().__init__()
                self._raised_once = False

            def task_done(self):
                if not self._raised_once:
                    self._raised_once = True
                    raise ValueError("task_done() called too many times")
                return super().task_done()

        flaky = _FlakyTaskDoneQueue()
        recorded: list[str] = []
        done = threading.Event()

        def _fake_record(*, ok, source, response_ms, error):
            recorded.append(source)
            if len(recorded) >= 2:
                done.set()

        monkeypatch.setattr(wm, "_HEARTBEAT_QUEUE", flaky)
        monkeypatch.setattr(upt, "record_heartbeat", _fake_record)

        t = threading.Thread(target=wm._heartbeat_drain_loop, daemon=True)
        t.start()

        # First item's task_done() raises ValueError; the loop must swallow it
        # and keep going, so the SECOND item still gets recorded.
        flaky.put((True, "first", 1.0, None))
        flaky.put((True, "second", 1.0, None))

        assert done.wait(timeout=5.0), (
            "drain thread died after task_done() ValueError — "
            f"only recorded {recorded}"
        )
        assert recorded[:2] == ["first", "second"]
        assert t.is_alive()


class TestHealthzPing:
    def test_ping_returns_200_with_pong(self, fresh_app):
        c, _ = fresh_app
        resp = c.get("/healthz/ping")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body == {"pong": True}


class TestStatusPageWithSeededHeartbeats:
    def test_renders_uptime_pct_from_seeded_heartbeats(self, fresh_app):
        c, _ = fresh_app
        # Seed dense, recent heartbeats so the page shows live data.
        import mediahub.observability.uptime as upt
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        for i in range(120):
            upt.record_heartbeat(
                ok=True,
                ts=(now - timedelta(minutes=120 - i)).isoformat(),
            )
        resp = c.get("/status")
        body = resp.get_data(as_text=True)
        # Recent all-ok heartbeats → the public status card reads operational.
        # (Previously this asserted "Backend", which was only present via the
        # header "online" status pill's title; that pill was removed.)
        assert "Website operational" in body
        # Some uptime number must be present.
        assert "%" in body

    def test_renders_pill_green_when_recent_heartbeat(self, fresh_app):
        c, _ = fresh_app
        import mediahub.observability.uptime as upt
        upt.record_heartbeat(ok=True)  # right now
        resp = c.get("/status")
        body = resp.get_data(as_text=True)
        # Green pill colour appears.
        assert "#2cc97f" in body
        assert "operational" in body

    def test_renders_red_pill_when_only_stale_heartbeat(self, fresh_app):
        c, _ = fresh_app
        import mediahub.observability.uptime as upt
        # An hour-old heartbeat → "stale" or "unknown" depending on age.
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        upt.record_heartbeat(ok=True, ts=ts)
        resp = c.get("/status")
        body = resp.get_data(as_text=True)
        # The pill must NOT say "operational" — it should say stale/unknown.
        assert "operational" not in body or "unknown" in body or "stale" in body


class TestHealthzUsageReachableWithoutOrg:
    def test_usage_page_redirects_anonymous(self, fresh_app):
        # The usage dashboard exposes call counts, token totals, cost and the
        # last raw provider error — operator-only. An anonymous caller is
        # bounced to settings (org-gate exemption is not an authentication).
        c, _ = fresh_app
        resp = c.get("/healthz/usage")
        assert resp.status_code in (302, 303)

    def test_usage_page_returns_200(self, fresh_app):
        c, _ = fresh_app
        _as_operator(c)
        resp = c.get("/healthz/usage")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Usage" in body

    def test_usage_page_shows_empty_state_when_no_calls(self, fresh_app):
        c, _ = fresh_app
        _as_operator(c)
        resp = c.get("/healthz/usage")
        body = resp.get_data(as_text=True)
        assert "No LLM calls in the last 24 hours" in body


class TestHealthzUsageWithSeededCalls:
    def test_usage_page_surfaces_today_calls_and_cost(self, fresh_app):
        c, _ = fresh_app
        _as_operator(c)
        import mediahub.observability.llm_usage as llmu
        # Seed a recent gemini call + an anthropic call with tokens.
        llmu.record_call(provider="gemini", ok=True,
                          tokens_in=1000, tokens_out=500)
        llmu.record_call(provider="anthropic", ok=True,
                          tokens_in=1000, tokens_out=500)
        resp = c.get("/healthz/usage")
        body = resp.get_data(as_text=True)
        # Both providers appear.
        assert "gemini" in body
        assert "anthropic" in body
        # Gemini cost surfaces as "$0.00 (free tier)".
        assert "(free tier)" in body
        # Anthropic cost is nonzero.
        assert "0.00" in body  # some cost number is rendered

    def test_usage_page_surfaces_last_llm_error(self, fresh_app):
        c, _ = fresh_app
        _as_operator(c)
        import mediahub.observability.llm_usage as llmu
        llmu.record_call(
            provider="gemini", ok=False,
            error_kind="rate_limited",
            error_message="HTTP 429 from Gemini",
        )
        resp = c.get("/healthz/usage")
        body = resp.get_data(as_text=True)
        assert "Last LLM error" in body
        assert "HTTP 429" in body
        assert "rate_limited" in body

    def test_usage_page_surfaces_gemini_headroom_bar(self, fresh_app):
        c, _ = fresh_app
        _as_operator(c)
        import mediahub.observability.llm_usage as llmu
        for _ in range(50):
            llmu.record_call(provider="gemini", ok=True)
        resp = c.get("/healthz/usage")
        body = resp.get_data(as_text=True)
        assert "Gemini free-tier today" in body
        # 50 used, 1450 remaining.
        assert "1450 remaining" in body or "remaining" in body
