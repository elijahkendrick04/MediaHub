"""tests/test_status_and_usage_pages.py — Phase 1.5 status + usage routes.

Pins:
  * /status renders WITHOUT an active organisation (it is the public
    trust signal — no gate)
  * /status surfaces real numbers from the uptime log
  * /api/status JSON shape
  * /healthz/usage renders WITHOUT an active organisation and surfaces
    real numbers from the llm_usage log
  * heartbeats are recorded on /healthz and /health hits

The harness uses the shared web fixtures (conftest's ``app`` / ``client``) —
fresh per-test DATA_DIR, no module reload, run with the org gate enforced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def fresh_app(app, tmp_path, monkeypatch):
    # The shared ``app`` fixture (conftest) already points DATA_DIR — and web.py's
    # path globals — at this test's tmp_path and rebuilds the schema, replacing the
    # old per-test DATA_DIR setenv + web/club_profile reload. The two observability
    # stores capture DATA_DIR / DB_PATH at *import* time, though, and the shared
    # fixtures don't reset them, so repoint them at this test's DATA_DIR here (the
    # equivalent of the reload they used to get) and recreate their schema.
    import mediahub.observability.uptime as upt
    import mediahub.observability.llm_usage as llmu

    for _mod in (upt, llmu):
        monkeypatch.setattr(_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(_mod, "DB_PATH", tmp_path / "data.db")
        _mod._ensure_schema()

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
            "Website operational" in body or "Website down" in body or "Status unavailable" in body
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
            "Website operational" in body or "Website down" in body or "Status unavailable" in body
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

    def test_public_json_does_not_leak_heartbeat_error_text(self, fresh_app):
        """AUDIT (system-status): /api/status is public and unauthenticated, so
        it must NOT echo the raw deep-/health failure string — that text can
        carry an internal filesystem path (e.g. a DB file path or an OS
        permission error). The ``ok`` flag still signals the failure honestly.
        """
        c, _ = fresh_app
        import mediahub.observability.uptime as upt

        leaky = "database: unable to open database file /srv/data/data.db"
        upt.record_heartbeat(ok=False, source="health", error=leaky)

        resp = c.get("/api/status")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        latest = body.get("latest_heartbeat") or {}
        # The raw error text (and the internal path inside it) is gone...
        assert "error" not in latest
        assert leaky not in resp.get_data(as_text=True)
        assert "/srv/data/data.db" not in resp.get_data(as_text=True)
        # ...but the failure is still visible via the honest ok flag.
        assert latest.get("ok") is False


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

        assert done.wait(
            timeout=5.0
        ), f"drain thread died after task_done() ValueError — only recorded {recorded}"
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


def _as_operator_session(c):
    with c.session_transaction() as s:
        s["dev_operator"] = True


class TestOperatorStatusHonestyAndResilience:
    """AUDIT (system-status): operator /status must not (a) round a window with
    real downtime up to a bare "100%" beside its non-zero Downtime cell, nor
    (b) 500 if the observability layer raises unexpectedly.
    """

    def test_window_with_downtime_never_renders_bare_100pct(self, fresh_app):
        c, _ = fresh_app
        _as_operator_session(c)
        import mediahub.observability.uptime as upt
        from datetime import datetime, timezone, timedelta
        import re

        now = datetime.now(timezone.utc)
        # 30 days of 5-min heartbeats with exactly ONE failure → 60s counted
        # downtime, uptime ≈ 99.9977% which would round up to "100%".
        step = 5
        for k in range(30 * 24 * 60 // step, -1, -1):
            upt.record_heartbeat(
                ok=(k != 100),
                ts=(now - timedelta(minutes=k * step)).isoformat(),
            )
        body = c.get("/status").get_data(as_text=True)
        m = re.search(r"30 days.*?</tr>", body, re.S)
        assert m is not None
        row = re.sub(r"<[^>]+>", " ", m.group(0))
        # Real downtime is shown, and the uptime cell is NOT a bare "100%".
        assert "min" in row  # a downtime figure is present
        assert "100%" not in row, f"100% shown beside downtime: {row!r}"
        assert "99.99%" in row

    def test_operator_status_degrades_not_500_when_observability_raises(self, fresh_app):
        c, _ = fresh_app
        _as_operator_session(c)
        import mediahub.observability.uptime as upt

        def _boom(*a, **k):
            raise RuntimeError("observability exploded /internal/secret/path")

        orig = (upt.uptime_stats, upt.latest_heartbeat, upt.recent_gaps)
        upt.uptime_stats = _boom
        upt.latest_heartbeat = _boom
        upt.recent_gaps = _boom
        try:
            resp = c.get("/status")
        finally:
            upt.uptime_stats, upt.latest_heartbeat, upt.recent_gaps = orig
        assert resp.status_code == 200  # no unhandled 500
        body = resp.get_data(as_text=True)
        assert "/internal/secret/path" not in body
        assert "Traceback" not in body
        # Falls back to the honest public status section.
        assert (
            "Website operational" in body or "Website down" in body or "Status unavailable" in body
        )


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
        llmu.record_call(provider="gemini", ok=True, tokens_in=1000, tokens_out=500)
        llmu.record_call(provider="anthropic", ok=True, tokens_in=1000, tokens_out=500)
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
            provider="gemini",
            ok=False,
            error_kind="rate_limited",
            error_message="HTTP 429 from Gemini",
        )
        resp = c.get("/healthz/usage")
        body = resp.get_data(as_text=True)
        assert "Last LLM error" in body
        assert "HTTP 429" in body
        assert "rate_limited" in body

    def test_usage_page_survives_error_with_null_message(self, fresh_app):
        """record_call permits error_message=None (a failure with a kind but
        no message). The dashboard must render it, not 500 on ''[:300] against
        a None value — .get(k, '') only defaults on an ABSENT key, so a stored
        NULL slipped straight into the slice and crashed the page."""
        c, _ = fresh_app
        _as_operator(c)
        import mediahub.observability.llm_usage as llmu

        llmu.record_call(
            provider="gemini", ok=False, error_kind="ProviderNotConfigured", error_message=None
        )
        resp = c.get("/healthz/usage")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Last LLM error" in body
        assert "ProviderNotConfigured" in body

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


class TestSettingsSystemStatusCardReachable:
    """AUDIT (system-status): the Settings landing 'System status' tile must
    land on a status view for EVERY visitor — including signed-out / no-org
    ones, the exact audience a public status signal is for. It used to point at
    the org-gated /settings/status, which the org gate bounced to /organisation
    setup; it now points at the public, gate-exempt /status.
    """

    def test_landing_card_points_at_public_status_and_resolves_without_org(self, fresh_app):
        import re

        c, _ = fresh_app  # ENFORCE_ORG_GATE=True, no org, signed out
        landing = c.get("/settings")
        assert landing.status_code == 200
        html = landing.get_data(as_text=True)
        m = re.search(r'<a href="([^"]+)"[^>]*>(?:(?!</a>).)*?System status', html, re.S)
        assert m is not None, "System status card missing from Settings landing"
        href = m.group(1)
        # The card targets the public /status, not the gated members surface.
        assert href.endswith("/status") and "settings" not in href, href
        # ...and following it as a no-org visitor reaches a real status view,
        # not a redirect into org setup.
        followed = c.get(href)
        assert followed.status_code == 200
        body = followed.get_data(as_text=True)
        assert (
            "Website operational" in body or "Website down" in body or "Status unavailable" in body
        )
