"""Tests for mediahub.log_sentinel — Render log watchdog with bounded auto-fix.

Offline: every Render API and notify call is faked. Covers the API client's
paging/parsing, the deterministic detectors (including the routine-recycle
false-positive guard), every playbook gate, state persistence, and full
run_once cycles in notify-only and auto-fix modes.
"""
from __future__ import annotations

import json
import time

import pytest
import requests

from mediahub.log_sentinel import detectors, github_issues, playbook, render_api, sentinel
from mediahub.log_sentinel import state as st
from mediahub.log_sentinel.render_api import LogLine


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (
        "RENDER_API_KEY",
        "RENDER_SERVICE_ID",
        "RENDER_OWNER_ID",
        "RENDER_API_BASE",
        "MEDIAHUB_SENTINEL_AUTOFIX",
        "MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT",
        "MEDIAHUB_SENTINEL_AUTOFIX_OUT_OF_MEMORY",
        "MEDIAHUB_SENTINEL_KILL",
        "MEDIAHUB_SENTINEL_MAX_ACTIONS_PER_DAY",
        "MEDIAHUB_SENTINEL_ACTION_COOLDOWN",
        "MEDIAHUB_SENTINEL_NOTIFY_COOLDOWN",
        "MEDIAHUB_SENTINEL_RESTART_GRACE",
        "MEDIAHUB_SENTINEL_GITHUB_TOKEN",
        "MEDIAHUB_SENTINEL_GITHUB_REPO",
        "MEDIAHUB_SENTINEL_GITHUB_API",
        "MEDIAHUB_NTFY_TOPIC",
        "MEDIAHUB_NOTIFY_WEBHOOK",
    ):
        monkeypatch.delenv(k, raising=False)
    render_api._owner_cache = None
    render_api._time_style["style"] = "rfc3339"
    github_issues._label_ready = False
    yield


def _line(msg: str, epoch: float = 1000.0) -> LogLine:
    return LogLine(epoch=epoch, timestamp="2026-06-12T08:00:00Z", message=msg)


# --- render_api ---------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def test_render_api_inert_unconfigured():
    assert render_api.is_configured() is False
    with pytest.raises(render_api.RenderApiUnavailable):
        render_api.fetch_log_lines(0.0)


def test_fetch_log_lines_pages_and_advances_cursor(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "rnd-key")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc")
    monkeypatch.setenv("RENDER_OWNER_ID", "own-1")
    calls = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "params": dict(params or {})})
        assert headers["Authorization"] == "Bearer rnd-key"
        if len(calls) == 1:
            return _FakeResp(200, {
                "logs": [
                    {"timestamp": "2026-06-12T08:00:01Z", "message": "first"},
                    {"timestamp": "2026-06-12T08:00:02Z", "message": "second"},
                ],
                "hasMore": True,
                "nextStartTime": "2026-06-12T08:00:02Z",
            })
        return _FakeResp(200, {
            "logs": [{"timestamp": "2026-06-12T08:00:03Z", "message": "third"}],
            "hasMore": False,
        })

    monkeypatch.setattr(requests, "request", fake_request)
    lines, newest = render_api.fetch_log_lines(0.0)
    assert [ln.message for ln in lines] == ["first", "second", "third"]
    assert newest == pytest.approx(render_api._parse_epoch("2026-06-12T08:00:03Z"))
    assert len(calls) == 2
    p = calls[0]["params"]
    assert p["ownerId"] == "own-1"
    assert p["resource"] == ["srv-abc"]
    assert p["direction"] == "forward"


def test_fetch_log_lines_skips_boundary_duplicates(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "k")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc")
    monkeypatch.setenv("RENDER_OWNER_ID", "own-1")
    cursor = render_api._parse_epoch("2026-06-12T08:00:02Z")

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        return _FakeResp(200, {
            "logs": [
                {"timestamp": "2026-06-12T08:00:02Z", "message": "already seen"},
                {"timestamp": "2026-06-12T08:00:03Z", "message": "new"},
            ],
            "hasMore": False,
        })

    monkeypatch.setattr(requests, "request", fake_request)
    lines, newest = render_api.fetch_log_lines(cursor)
    assert [ln.message for ln in lines] == ["new"]
    assert newest > cursor


def test_fetch_log_lines_falls_back_to_epoch_params(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "k")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc")
    monkeypatch.setenv("RENDER_OWNER_ID", "own-1")
    seen_styles = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        seen_styles.append(params["startTime"])
        if isinstance(params["startTime"], str):
            return _FakeResp(400, {}, text="bad startTime")
        return _FakeResp(200, {"logs": [], "hasMore": False})

    monkeypatch.setattr(requests, "request", fake_request)
    lines, _ = render_api.fetch_log_lines(1000.0)
    assert lines == []
    assert isinstance(seen_styles[0], str) and isinstance(seen_styles[1], int)
    # The working style is remembered for subsequent polls.
    render_api.fetch_log_lines(1000.0)
    assert isinstance(seen_styles[2], int)


def test_restart_service_posts(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "k")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc")
    hit = {}

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        hit.update(method=method, url=url)
        return _FakeResp(200, {})

    monkeypatch.setattr(requests, "request", fake_request)
    render_api.restart_service()
    assert hit["method"] == "POST"
    assert hit["url"].endswith("/services/srv-abc/restart")


# --- detectors ------------------------------------------------------------------

def test_detects_searxng_spam():
    lines = [_line("SearXNG unavailable, falling back to DuckDuckGo: boom")] * 3
    found = {f.issue_id: f for f in detectors.detect(lines)}
    assert found["searxng_unavailable"].count == 3
    assert "healthz/search" in found["searxng_unavailable"].suggestion


def test_routine_worker_recycle_is_not_churn():
    lines = [
        _line("[INFO] Autorestarting worker after current request."),
        _line("[INFO] Worker exiting (pid: 82)"),
    ] * 5
    assert detectors.detect(lines) == []


def test_sigterm_churn_needs_threshold():
    two = [_line("[WARNING] Worker was sent SIGTERM!")] * 2
    assert not any(f.issue_id == "worker_sigterm_churn" for f in detectors.detect(two))
    three = [_line("[WARNING] Worker was sent SIGTERM!")] * 3
    assert any(f.issue_id == "worker_sigterm_churn" for f in detectors.detect(three))


def test_http_5xx_threshold_and_evidence_cap():
    ok = [_line('10.0.0.1 "GET /healthz HTTP/1.1" 200 71 0ms "-"')] * 50
    assert detectors.detect(ok) == []
    bad = [_line(f'10.0.0.1 "GET /runs/{i} HTTP/1.1" 500 0 4ms "-"') for i in range(8)]
    found = {f.issue_id: f for f in detectors.detect(bad)}
    assert found["http_5xx"].count == 8
    assert len(found["http_5xx"].evidence) == detectors.MAX_EVIDENCE


def test_detects_worker_timeout_and_oom_and_disk():
    lines = [
        _line("[CRITICAL] WORKER TIMEOUT (pid:90)"),
        _line("MemoryError"),
        _line("OSError: [Errno 28] No space left on device"),
        _line("mediahub.web.ai_caption.ClaudeUnavailableError: provider down"),
        _line("Traceback (most recent call last):"),
    ]
    ids = {f.issue_id for f in detectors.detect(lines)}
    assert {"worker_timeout", "out_of_memory", "disk_full", "llm_provider_down",
            "unhandled_traceback"} <= ids


# --- playbook gates ---------------------------------------------------------------

def test_notify_only_issue_never_acts(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    allowed, reason = playbook.action_decision(
        "searxng_unavailable", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is False
    assert "notify-only" in reason


def test_autofix_requires_double_opt_in(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_RESTART_GRACE", "0")
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is False and "not enabled" in reason
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is False and "WORKER_TIMEOUT" in reason
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is True


def test_kill_switch_blocks_even_when_opted_in(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_RESTART_GRACE", "0")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_KILL", "1")
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is False and "kill switch" in reason


def test_daily_cap_and_cooldown_block(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_RESTART_GRACE", "0")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=4
    )
    assert allowed is False and "cap" in reason
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=time.time() - 60, actions_today=0
    )
    assert allowed is False and "cooldown" in reason


def test_boot_grace_blocks(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    # default grace is 600s and the test process started moments ago
    allowed, reason = playbook.action_decision(
        "worker_timeout", last_acted_epoch=0.0, actions_today=0
    )
    assert allowed is False and "grace" in reason


# --- state -----------------------------------------------------------------------

def test_state_round_trip_and_action_counter(tmp_path):
    d = str(tmp_path)
    state = st.load_state(d)
    assert state == {}
    state["cursor_epoch"] = 123.0
    st.remember_issue(state, "worker_timeout", last_notified=1.0)
    st.record_action(state)
    st.save_state(state, d)
    loaded = st.load_state(d)
    assert loaded["cursor_epoch"] == 123.0
    assert st.issue_memory(loaded, "worker_timeout")["last_notified"] == 1.0
    assert st.actions_today(loaded) == 1


def test_audit_append_and_tail(tmp_path):
    d = str(tmp_path)
    for i in range(5):
        st.append_audit({"kind": "finding", "i": i}, d)
    tail = st.read_audit_tail(3, d)
    assert [e["i"] for e in tail] == [2, 3, 4]
    assert all("ts" in e for e in tail)


def test_leader_lock_excludes_and_recovers_stale(tmp_path):
    d = str(tmp_path)
    assert st.acquire_leader("w1", ttl=60.0, data_dir=d) is True
    assert st.acquire_leader("w2", ttl=60.0, data_dir=d) is False
    assert st.acquire_leader("w1", ttl=60.0, data_dir=d) is True  # refresh own
    # Stale heartbeat → takeover allowed.
    lock = st.state_dir(d) / "leader.json"
    lock.write_text(json.dumps({"worker": "w1", "ts": time.time() - 1000}))
    assert st.acquire_leader("w2", ttl=60.0, data_dir=d) is True
    st.release_leader("w2", d)
    assert not lock.exists()


# --- sentinel cycles ---------------------------------------------------------------

def test_run_once_unconfigured_idles(tmp_path):
    s = sentinel.Sentinel(str(tmp_path))
    summary = s.run_once()
    assert summary["configured"] is False
    assert st.read_status(str(tmp_path))["configured"] is False


def _configure(monkeypatch):
    monkeypatch.setenv("RENDER_API_KEY", "k")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-abc")
    monkeypatch.setenv("RENDER_OWNER_ID", "own-1")


def test_run_once_notify_only_by_default(tmp_path, monkeypatch):
    _configure(monkeypatch)
    d = str(tmp_path)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    restarted = {"n": 0}
    monkeypatch.setattr(
        render_api, "restart_service", lambda: restarted.__setitem__("n", restarted["n"] + 1)
    )
    summary = sentinel.Sentinel(d).run_once()
    assert summary["findings"] == ["worker_timeout"]
    assert restarted["n"] == 0  # auto-fix is off by default
    kinds = [e["kind"] for e in st.read_audit_tail(20, d)]
    assert "finding" in kinds and "notify" in kinds and "action_decision" in kinds
    assert "action_attempt" not in kinds
    assert st.load_state(d)["cursor_epoch"] == 2000.0


def test_run_once_applies_gated_autofix(tmp_path, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_RESTART_GRACE", "0")
    d = str(tmp_path)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    restarted = {"n": 0}
    monkeypatch.setattr(
        render_api, "restart_service", lambda: restarted.__setitem__("n", restarted["n"] + 1)
    )
    sentinel.Sentinel(d).run_once()
    assert restarted["n"] == 1
    entries = st.read_audit_tail(20, d)
    kinds = [e["kind"] for e in entries]
    # Claim is persisted before the attempt; result is recorded after.
    assert kinds.index("action_attempt") < kinds.index("action_result")
    result = [e for e in entries if e["kind"] == "action_result"][0]
    assert result["ok"] is True
    state = st.load_state(d)
    assert st.actions_today(state) == 1
    assert st.issue_memory(state, "worker_timeout")["last_acted"] > 0


def test_run_once_cooldown_prevents_second_action(tmp_path, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_AUTOFIX_WORKER_TIMEOUT", "1")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_RESTART_GRACE", "0")
    d = str(tmp_path)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    restarted = {"n": 0}
    monkeypatch.setattr(
        render_api, "restart_service", lambda: restarted.__setitem__("n", restarted["n"] + 1)
    )
    s = sentinel.Sentinel(d)
    s.run_once()
    s.run_once()  # same finding again, within the 6h issue cooldown
    assert restarted["n"] == 1


def test_run_once_notify_cooldown_dedupes(tmp_path, monkeypatch):
    _configure(monkeypatch)
    d = str(tmp_path)
    lines = [_line("SearXNG unavailable, falling back to DuckDuckGo: x", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    s = sentinel.Sentinel(d)
    s.run_once()
    s.run_once()
    notifies = [e for e in st.read_audit_tail(50, d) if e["kind"] == "notify"]
    assert len(notifies) == 1  # second cycle stayed within the notify cooldown


def test_run_once_survives_api_outage(tmp_path, monkeypatch):
    _configure(monkeypatch)

    def boom(c, **k):
        raise render_api.RenderApiUnavailable("HTTP 503")

    monkeypatch.setattr(render_api, "fetch_log_lines", boom)
    summary = sentinel.Sentinel(str(tmp_path)).run_once()
    assert summary["last_poll_ok"] is False
    assert "503" in summary["detail"]


# --- GitHub issue escalation ----------------------------------------------------

def _gh_configure(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SENTINEL_GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("MEDIAHUB_SENTINEL_GITHUB_REPO", "owner/repo")


def _finding(issue_id="worker_timeout", title="Gunicorn worker timeout (wedged request)"):
    return detectors.Finding(
        issue_id=issue_id,
        severity="critical",
        title=title,
        suggestion="Do the thing.",
        count=2,
        evidence=("2026-06-12T08:00:00Z [CRITICAL] WORKER TIMEOUT (pid:90)",),
    )


def test_github_issues_inert_unconfigured():
    assert github_issues.is_configured() is False
    with pytest.raises(github_issues.GithubIssuesUnavailable):
        github_issues.create_issue(_finding())


def test_github_issues_create_ensures_label_and_posts(monkeypatch):
    _gh_configure(monkeypatch)
    calls = []

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json})
        assert headers["Authorization"] == "Bearer ghp_test"
        if method == "GET" and url.endswith("/labels/sentinel"):
            return _FakeResp(404, {})
        if method == "POST" and url.endswith("/labels"):
            return _FakeResp(201, {"name": "sentinel"})
        if method == "POST" and url.endswith("/issues"):
            assert json["labels"] == ["sentinel"]
            assert json["title"].startswith("[sentinel] ")
            assert "WORKER TIMEOUT" in json["body"]
            return _FakeResp(201, {"number": 42, "html_url": "https://gh/i/42"})
        raise AssertionError(f"unexpected call {method} {url}")

    monkeypatch.setattr(requests, "request", fake_request)
    out = github_issues.create_issue(_finding(), "https://app.example")
    assert out == {"number": 42, "url": "https://gh/i/42"}
    # Label ensured exactly once per process even across creates.
    github_issues.create_issue(_finding())
    label_checks = [c for c in calls if c["url"].endswith("/labels/sentinel")]
    assert len(label_checks) == 1


def test_github_issue_state(monkeypatch):
    _gh_configure(monkeypatch)
    monkeypatch.setattr(
        requests, "request", lambda *a, **k: _FakeResp(200, {"state": "closed"})
    )
    assert github_issues.issue_state(7) == "closed"
    monkeypatch.setattr(requests, "request", lambda *a, **k: _FakeResp(500, {}))
    assert github_issues.issue_state(7) is None


def test_sentinel_files_issue_once_while_open(tmp_path, monkeypatch):
    _configure(monkeypatch)
    _gh_configure(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_SENTINEL_NOTIFY_COOLDOWN", "0")
    d = str(tmp_path)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    created = {"n": 0}

    def fake_create(finding, base=""):
        created["n"] += 1
        return {"number": 10 + created["n"], "url": "https://gh/i"}

    monkeypatch.setattr(github_issues, "create_issue", fake_create)
    states = {"value": "open"}
    monkeypatch.setattr(github_issues, "issue_state", lambda n: states["value"])
    s = sentinel.Sentinel(d)
    s.run_once()
    assert created["n"] == 1  # filed
    s.run_once()
    assert created["n"] == 1  # still open => deduped
    states["value"] = "closed"
    s.run_once()
    assert created["n"] == 2  # closed + recurred => fresh issue
    issue_audit = [e for e in st.read_audit_tail(50, d) if e["kind"] == "issue"]
    assert [e["created"] for e in issue_audit] == [True, False, True]
    assert st.issue_memory(st.load_state(d), "worker_timeout")["issue_number"] == 12


def test_sentinel_skips_issue_on_api_doubt(tmp_path, monkeypatch):
    _configure(monkeypatch)
    _gh_configure(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_SENTINEL_NOTIFY_COOLDOWN", "0")
    d = str(tmp_path)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    created = {"n": 0}

    def fake_create(finding, base=""):
        created["n"] += 1
        return {"number": 11, "url": "https://gh/i"}

    monkeypatch.setattr(github_issues, "create_issue", fake_create)
    monkeypatch.setattr(github_issues, "issue_state", lambda n: None)  # API erring
    s = sentinel.Sentinel(d)
    s.run_once()  # no remembered issue yet => files
    s.run_once()  # state check fails => must NOT file a duplicate
    assert created["n"] == 1


def test_notification_delivery_via_webhook(tmp_path, monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_NOTIFY_WEBHOOK", "https://hooks.example/x")
    sent = {}

    def fake_post(url, json=None, data=None, headers=None, timeout=None):
        sent.update(url=url, payload=json)

        class R:
            status_code = 200

        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    lines = [_line("[CRITICAL] WORKER TIMEOUT (pid:90)", epoch=2000.0)]
    monkeypatch.setattr(render_api, "fetch_log_lines", lambda c, **k: (lines, 2000.0))
    sentinel.Sentinel(str(tmp_path)).run_once()
    assert sent["url"] == "https://hooks.example/x"
    assert "WORKER TIMEOUT" in json.dumps(sent["payload"]) or "worker" in sent["payload"]["title"].lower()
    d = str(tmp_path)
    notify_entries = [e for e in st.read_audit_tail(20, d) if e["kind"] == "notify"]
    assert notify_entries[0]["sent"] is True
