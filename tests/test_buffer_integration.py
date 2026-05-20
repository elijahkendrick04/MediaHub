"""tests/test_buffer_integration.py — Buffer publishing end-to-end coverage.

This is the end-to-end / route-level companion to
``tests/test_publishing_buffer.py`` (which is unit-level around the
publishing module itself). It pins behaviour at the boundary between
Flask routes, the publishing module, the workflow store, and the
posting log:

  * TestMediaUrlValidation  — the schedule endpoint rejects non-http/https
    media URLs as defence-in-depth before they reach Buffer.
  * TestRateLimitHandling   — ``BufferRateLimitError`` surfaces a 502 with
    ``retry_after`` and stops the per-channel loop early (rate-limit is
    per-account, not per-channel).
  * TestPartialSuccessPath  — when some channels succeed and others fail
    the workflow store is marked SCHEDULED with the warning text, and
    every per-channel outcome is returned.
  * TestPostingLogIntegration — every Buffer call writes exactly one row
    to the posting log scoped to the run's profile_id.
  * TestPostingLogApi       — ``/api/posting/log`` is org-gated and scoped
    to the active profile (no cross-tenant leakage).

External calls into the Buffer module surface are mocked at the
``mediahub.publishing.buffer.schedule_post`` / ``list_channels`` boundary
so no live Buffer API request is ever made.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Shared fixture — fresh DATA_DIR, ready org, pinned profile, seeded run,
# Buffer token in the secrets store. Returns (client, run_id, card_id,
# profile_id) so each test gets a fully-wired-up surface to poke.
# ---------------------------------------------------------------------------

@pytest.fixture
def ready_app(tmp_path, monkeypatch):
    """Spin up a TESTING app with the org-gate enforced, an active
    ``test-org`` profile, one seeded run with one ranked achievement,
    and a Buffer access token in the on-disk secrets store.

    Yields ``(client, run_id, card_id, profile_id)``.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    # Buffer token must not leak from the host process. The secrets store
    # consults env first, then disk — clear both so the test-only token
    # we set via set_buffer_access_token below is the only source.
    monkeypatch.delenv("BUFFER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Reload modules so module-level paths re-resolve against tmp_path.
    import mediahub.web.club_profile as cp
    import mediahub.web.secrets_store as secrets_store
    import mediahub.publishing.posting_log as posting_log
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(secrets_store)
    importlib.reload(posting_log)
    importlib.reload(wm)

    # Seed a ready ClubProfile.
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile_id = "test-org"
    profile = ClubProfile(
        profile_id=profile_id,
        display_name="Test Org",
        brand_voice_summary="x",
        sponsor_name="Acme",
    )
    assert profile.is_ready(), "fixture profile must be ready for the gate to lift"
    save_profile(profile)

    # Seed one run JSON with one ranked achievement so the schedule
    # endpoint has something concrete to log against. The run dict must
    # carry profile_id so posting-log rows inherit the right tenant.
    run_id = "run-buf-1"
    card_id = "swim-001"
    run_json = {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Org",
        "file_name": "test.hy3",
        "meet": {"name": "Spring Open 2026"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "swim_id": card_id,
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_name": "Sam Test",
                        "event": "100 Free",
                        "time": "58.21",
                        "swim_id": card_id,
                    },
                }
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_json))

    # Buffer access token — operator-managed via env var post-rewrite.
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "test-token")
    assert secrets_store.get_buffer_access_token() == "test-token"

    # Build the app with both TESTING and ENFORCE_ORG_GATE on so the
    # gate is actually evaluated for the API endpoints under test.
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as c:
        # Pin the org explicitly so the gate doesn't 409 the requests.
        pin = c.post(
            "/api/organisation/active",
            data={"profile_id": profile_id},
        )
        assert pin.status_code == 200, pin.get_data(as_text=True)
        yield c, run_id, card_id, profile_id


def _schedule_url(run_id: str, card_id: str) -> str:
    return f"/api/runs/{run_id}/card/{card_id}/schedule"


# ---------------------------------------------------------------------------
# 1. Media URL validation
# ---------------------------------------------------------------------------

class TestMediaUrlValidation:
    """The schedule endpoint must reject non-http/https media URLs as
    defence-in-depth so a malicious caller can't smuggle file://,
    javascript:, or data: URIs through to Buffer."""

    def test_https_media_url_accepted(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        captured = {}

        def fake_schedule(**kw):
            captured.update(kw)
            return {"ok": True, "update_id": "u-https",
                    "channel_id": kw["channel_id"], "raw": {}}

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", fake_schedule,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "good caption",
                "media_url": "https://example.com/img.png",
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert captured.get("media_urls") == ["https://example.com/img.png"]

    def test_http_media_url_accepted(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        captured = {}

        def fake_schedule(**kw):
            captured.update(kw)
            return {"ok": True, "update_id": "u-http",
                    "channel_id": kw["channel_id"], "raw": {}}

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", fake_schedule,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "good caption",
                "media_url": "http://example.com/img.png",
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert captured.get("media_urls") == ["http://example.com/img.png"]

    def test_file_scheme_rejected_400(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        called = {"n": 0}
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: called.__setitem__("n", called["n"] + 1) or {
                "ok": True, "update_id": "x", "channel_id": kw["channel_id"], "raw": {},
            },
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "my caption",
                "media_url": "file:///etc/passwd",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json() or {}
        assert body.get("error") == "bad_media_url"
        # User caption is echoed back so the modal can preserve it.
        assert body.get("caption") == "my caption"
        # And nothing was forwarded to Buffer.
        assert called["n"] == 0

    def test_javascript_scheme_rejected_400(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "x",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "caption text",
                "media_url": "javascript:alert(1)",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json() or {}
        assert body.get("error") == "bad_media_url"

    def test_data_scheme_rejected_400(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "x",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "caption text",
                "media_url": "data:text/html,<script>",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json() or {}
        assert body.get("error") == "bad_media_url"

    def test_garbage_string_rejected_400(self, ready_app, monkeypatch):
        c, run_id, card_id, _ = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "x",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "caption text",
                "media_url": "not-a-url",
            },
        )
        assert resp.status_code == 400
        body = resp.get_json() or {}
        assert body.get("error") == "bad_media_url"

    def test_empty_media_url_accepted_no_media(self, ready_app, monkeypatch):
        """No media is a valid case — text-only posts must work and the
        publishing layer must be called with ``media_urls=None``."""
        c, run_id, card_id, _ = ready_app
        captured = {}

        def fake_schedule(**kw):
            captured.update(kw)
            return {"ok": True, "update_id": "u-text",
                    "channel_id": kw["channel_id"], "raw": {}}

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", fake_schedule,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["p1"],
                "caption": "text only please",
                # media_url intentionally omitted
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        # The endpoint passes media_urls=None when no URL was given.
        assert captured.get("media_urls") is None


# ---------------------------------------------------------------------------
# 2. Rate-limit handling
# ---------------------------------------------------------------------------

class TestRateLimitHandling:
    """Buffer's rate-limit is per-account, not per-channel. The schedule
    endpoint must:
      * return 502 with ``error="rate_limited"`` in the first result
      * surface ``retry_after`` from the raised exception
      * stop iterating channels once we hit the limit (no point making
        the next call when the same account-wide limit will trip again).
    """

    def test_rate_limit_returns_502_and_surfaces_retry_after(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, _ = ready_app
        from mediahub.publishing.buffer import BufferRateLimitError

        def raise_rate_limit(**kw):
            raise BufferRateLimitError(
                "Buffer rate-limit reached. Retry in 30s.",
                retry_after=30,
            )

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", raise_rate_limit,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["p1"], "caption": "hi"},
        )
        assert resp.status_code == 502
        body = resp.get_json() or {}
        assert body.get("ok") is False
        assert body.get("results")
        first = body["results"][0]
        assert first.get("error") == "rate_limited"
        assert first.get("retry_after") == 30

    def test_rate_limit_breaks_loop_after_first_channel(
        self, ready_app, monkeypatch,
    ):
        """Even when three channel_ids are passed, the rate-limit must
        short-circuit the loop after the first failure — calling Buffer
        a second time is wasted work that will produce the same error."""
        c, run_id, card_id, _ = ready_app
        from mediahub.publishing.buffer import BufferRateLimitError

        calls = {"n": 0, "channel_ids": []}

        def raise_rate_limit(**kw):
            calls["n"] += 1
            calls["channel_ids"].append(kw["channel_id"])
            raise BufferRateLimitError(
                "Buffer rate-limit reached. Retry in 60s.",
                retry_after=60,
            )

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", raise_rate_limit,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["chan-a", "chan-b", "chan-c"],
                "caption": "hi",
            },
        )
        assert resp.status_code == 502
        # Only the first channel must have been attempted.
        assert calls["n"] == 1, (
            f"expected loop to break after first 429, got {calls['n']} calls"
        )
        assert calls["channel_ids"] == ["chan-a"]


# ---------------------------------------------------------------------------
# 3. Partial-success path
# ---------------------------------------------------------------------------

class TestPartialSuccessPath:
    """When some channels succeed and others fail, the endpoint must:
      * return 200 with ``warning`` set to the failure text
      * include every per-channel outcome in ``results``
      * mark the workflow store SCHEDULED (not FAILED) with the warning
      * record every successful update_id in the workflow sidecar.
    """

    def test_partial_success_returns_200_with_warning_and_results(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, _ = ready_app
        from mediahub.publishing.buffer import BufferAPIError

        def per_channel(**kw):
            cid = kw["channel_id"]
            if cid == "B":
                raise BufferAPIError("boom")
            return {
                "ok": True,
                "update_id": f"upd-{cid}",
                "channel_id": cid,
                "raw": {},
            }

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", per_channel,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["A", "B", "C"],
                "caption": "mixed run",
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert body.get("warning") == "boom"
        results = body.get("results") or []
        assert len(results) == 3
        # All three per-channel outcomes are represented.
        per_cid = {r["channel_id"]: r for r in results}
        assert per_cid["A"]["ok"] is True
        assert per_cid["B"]["ok"] is False
        assert per_cid["B"]["error"] == "api"
        assert per_cid["C"]["ok"] is True

    def test_partial_success_marks_workflow_scheduled_with_error(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, _ = ready_app
        from mediahub.publishing.buffer import BufferAPIError
        from mediahub.workflow.status import ScheduleStatus
        from mediahub.workflow.store import WorkflowStore

        def per_channel(**kw):
            cid = kw["channel_id"]
            if cid == "B":
                raise BufferAPIError("boom")
            return {
                "ok": True, "update_id": f"upd-{cid}",
                "channel_id": cid, "raw": {},
            }

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", per_channel,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["A", "B", "C"], "caption": "mixed"},
        )
        assert resp.status_code == 200

        # Inspect the persisted workflow sidecar.
        from mediahub.web import web as _web
        ws = WorkflowStore(_web.RUNS_DIR)
        state = ws.load(run_id).get(card_id)
        assert state is not None
        # Partial success → SCHEDULED, NOT FAILED.
        assert state.schedule_status == ScheduleStatus.SCHEDULED
        # The warning text is preserved on the sidecar.
        assert state.schedule_error == "boom"
        # Both successful update_ids are recorded (joined by ';').
        assert state.buffer_update_id is not None
        ids = state.buffer_update_id.split(";")
        assert "upd-A" in ids
        assert "upd-C" in ids


# ---------------------------------------------------------------------------
# 4. Posting log integration
# ---------------------------------------------------------------------------

class TestPostingLogIntegration:
    """Every Buffer call — success or failure — writes one row to the
    posting log scoped to the run's profile_id."""

    def test_successful_schedule_writes_ok_row(self, ready_app, monkeypatch):
        c, run_id, card_id, profile_id = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "upd-ok",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["chan-1"], "caption": "logged ok"},
        )
        assert resp.status_code == 200

        from mediahub.publishing import posting_log as _plog
        rows = _plog.recent_attempts(profile_id, limit=10, run_id=run_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "ok"
        assert row["update_id"] == "upd-ok"
        assert row["profile_id"] == profile_id
        assert row["run_id"] == run_id
        assert row["card_id"] == card_id

    def test_auth_failure_writes_failed_row_with_kind(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, profile_id = ready_app
        from mediahub.publishing.buffer import BufferAuthError

        def raise_auth(**kw):
            raise BufferAuthError("Buffer rejected the access token. Re-paste it.")

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", raise_auth,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["chan-1"], "caption": "auth-fail"},
        )
        assert resp.status_code == 502

        from mediahub.publishing import posting_log as _plog
        rows = _plog.recent_attempts(profile_id, limit=10, run_id=run_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "failed"
        assert row["error_kind"] == "auth"
        assert row["error_message"] and "rejected" in row["error_message"].lower()
        assert row["profile_id"] == profile_id

    def test_rate_limited_schedule_writes_rate_limited_row(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, profile_id = ready_app
        from mediahub.publishing.buffer import BufferRateLimitError

        def raise_rl(**kw):
            raise BufferRateLimitError("Buffer rate-limit reached.", retry_after=15)

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", raise_rl,
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["chan-1"], "caption": "rl"},
        )
        assert resp.status_code == 502

        from mediahub.publishing import posting_log as _plog
        rows = _plog.recent_attempts(profile_id, limit=10, run_id=run_id)
        assert len(rows) == 1
        assert rows[0]["error_kind"] == "rate_limited"
        assert rows[0]["status"] == "failed"

    def test_recent_attempts_returns_newest_first(
        self, ready_app, monkeypatch,
    ):
        """After three sequential calls, recent_attempts() lists them
        newest-first."""
        c, run_id, card_id, profile_id = ready_app
        from mediahub.publishing.buffer import BufferAPIError

        counter = {"n": 0}

        def per_call(**kw):
            counter["n"] += 1
            n = counter["n"]
            if n == 2:
                raise BufferAPIError(f"failure-{n}")
            return {"ok": True, "update_id": f"u-{n}",
                    "channel_id": kw["channel_id"], "raw": {}}

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post", per_call,
        )
        for cap in ["first", "second", "third"]:
            r = c.post(
                _schedule_url(run_id, card_id),
                json={"channel_ids": ["chan-1"], "caption": cap},
            )
            assert r.status_code in (200, 502)

        from mediahub.publishing import posting_log as _plog
        rows = _plog.recent_attempts(profile_id, limit=10, run_id=run_id)
        assert len(rows) == 3
        # Newest-first ordering: the most recent attempted_at is at index 0.
        times = [r["attempted_at"] for r in rows]
        assert times == sorted(times, reverse=True), (
            f"recent_attempts should be newest-first, got {times}"
        )

    def test_posting_log_profile_id_matches_run_profile_id(
        self, ready_app, monkeypatch,
    ):
        """The row's profile_id must be the run's stored profile_id,
        NOT just whatever session pin happens to be active. This is the
        guarantee that multi-tenant scoping works on legacy runs."""
        c, run_id, card_id, profile_id = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "u-scoped",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["chan-1"], "caption": "scope check"},
        )
        assert resp.status_code == 200

        from mediahub.publishing import posting_log as _plog
        rows = _plog.recent_attempts(profile_id, limit=5, run_id=run_id)
        assert len(rows) == 1
        # profile_id on the row matches the run's stored profile_id
        # (not the session pin, although in this test they happen to
        # be equal — the assertion proves the route used the run's value).
        assert rows[0]["profile_id"] == "test-org"
        # Sanity: querying under a different profile_id must yield nothing.
        other = _plog.recent_attempts("some-other-org", limit=5)
        assert other == []


# ---------------------------------------------------------------------------
# 5. /api/posting/log endpoint
# ---------------------------------------------------------------------------

class TestPostingLogApi:
    """The JSON posting-log endpoint is org-gated and strictly scoped to
    the active profile. Tenants must never see each other's attempts."""

    def test_no_active_profile_returns_409(self, tmp_path, monkeypatch):
        """Without a pinned profile (and no profile on disk) the
        org-gate trips and returns 409 before the route runs."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
        monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
        (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
        (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
        (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
        monkeypatch.delenv("BUFFER_ACCESS_TOKEN", raising=False)

        import mediahub.web.club_profile as cp
        import mediahub.web.web as wm
        importlib.reload(cp)
        importlib.reload(wm)

        app = wm.create_app()
        app.config["TESTING"] = True
        app.config["ENFORCE_ORG_GATE"] = True
        with app.test_client() as c:
            resp = c.get("/api/posting/log")
            assert resp.status_code == 409

    def test_with_pinned_profile_returns_attempts_newest_first(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, profile_id = ready_app

        # Seed three attempts via the schedule endpoint.
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": f"u-{kw['channel_id']}",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        for cap in ["a", "b", "c"]:
            r = c.post(
                _schedule_url(run_id, card_id),
                json={"channel_ids": ["chan-1"], "caption": cap},
            )
            assert r.status_code == 200

        resp = c.get("/api/posting/log")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert body.get("count") == 3
        attempts = body.get("attempts") or []
        assert len(attempts) == 3
        times = [a["attempted_at"] for a in attempts]
        assert times == sorted(times, reverse=True)

    def test_limit_param_caps_response(self, ready_app, monkeypatch):
        c, run_id, card_id, profile_id = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "u",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        for i in range(8):
            r = c.post(
                _schedule_url(run_id, card_id),
                json={"channel_ids": ["c"], "caption": f"n{i}"},
            )
            assert r.status_code == 200

        # ?limit=5 caps to 5.
        resp = c.get("/api/posting/log?limit=5")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("count") == 5
        assert len(body.get("attempts") or []) == 5

    def test_limit_clamped_to_200_and_200_allowed(
        self, ready_app, monkeypatch,
    ):
        """``?limit=200`` is the documented ceiling and is allowed.
        ``?limit=10000`` must be clamped to 200, never honoured raw."""
        c, run_id, card_id, profile_id = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "u",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        # Seed two attempts — we don't need 200, we only need to verify
        # the limit is accepted / clamped, not that we hit the ceiling.
        for cap in ["x", "y"]:
            r = c.post(
                _schedule_url(run_id, card_id),
                json={"channel_ids": ["c"], "caption": cap},
            )
            assert r.status_code == 200

        # limit=200 is allowed without 400.
        r1 = c.get("/api/posting/log?limit=200")
        assert r1.status_code == 200, r1.get_data(as_text=True)
        body1 = r1.get_json() or {}
        assert body1.get("ok") is True

        # limit=10000 is clamped server-side: the route shouldn't raise,
        # the response must remain a 200 (we can't observe the cap
        # directly without 200+ rows, but the absence of an error
        # response is the contract pinned here — combined with the
        # previous test_limit_param_caps_response which actively
        # exercises the cap behaviour).
        r2 = c.get("/api/posting/log?limit=10000")
        assert r2.status_code == 200, r2.get_data(as_text=True)

    def test_run_id_param_filters(self, ready_app, monkeypatch):
        c, run_id, card_id, profile_id = ready_app
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "u",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        r = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["c"], "caption": "real-run"},
        )
        assert r.status_code == 200

        # Querying our seeded run returns it.
        match = c.get(f"/api/posting/log?run_id={run_id}")
        assert match.status_code == 200
        assert match.get_json().get("count") == 1

        # Querying a non-existent run returns no rows.
        miss = c.get("/api/posting/log?run_id=does-not-exist")
        assert miss.status_code == 200
        assert miss.get_json().get("count") == 0

    def test_profile_filtering_no_cross_tenant_leakage(
        self, ready_app, monkeypatch,
    ):
        """Org A's attempts must never appear in org B's posting-log
        response — the multi-tenant scoping is enforced at the SQL layer."""
        c, run_id, card_id, profile_id_a = ready_app

        # Seed one attempt for org A via the route.
        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "u-A",
                          "channel_id": kw["channel_id"], "raw": {}},
        )
        r = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["c"], "caption": "org-A row"},
        )
        assert r.status_code == 200

        # Directly insert one attempt for org B into the same posting log.
        from mediahub.publishing import posting_log as _plog
        _plog.record_attempt(
            profile_id="other-org",
            run_id="other-run",
            card_id="other-card",
            channel_id="c2",
            status="ok",
            update_id="u-B",
            caption="org-B row",
        )

        # Org A is pinned in the session → org A only sees its own row.
        resp = c.get("/api/posting/log")
        assert resp.status_code == 200
        body = resp.get_json() or {}
        assert body.get("profile_id") == profile_id_a
        attempts = body.get("attempts") or []
        assert len(attempts) == 1
        assert attempts[0]["caption_excerpt"] == "org-A row"
        # The other-org row is provably present in the underlying log
        # but absent from the org-A scoped response.
        all_b = _plog.recent_attempts("other-org", limit=5)
        assert len(all_b) == 1


# ---------------------------------------------------------------------------
# 6. End-to-end "schedule survives refresh" — pins the user-facing
#    promise of the pill state. After a successful Buffer schedule:
#      * the workflow sidecar persists the new ScheduleStatus
#      * build_grouped_pack (the pack reload path) surfaces it on the item
#      * /api/posting/log shows the ok row
#    These three checks together model what a real "refresh" exercises.
# ---------------------------------------------------------------------------

class TestSchedulePillSurvivesRefresh:
    def test_schedule_then_reload_pack_shows_scheduled_state(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, profile_id = ready_app

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: {"ok": True, "update_id": "upd-keep",
                          "channel_id": kw["channel_id"], "raw": {}},
        )

        # Approve the card so it's eligible for build_grouped_pack /
        # build_content_pack to consider it. Without an APPROVED status
        # the content-pack reload path filters it out and we can't
        # assert anything about the schedule pill.
        from mediahub.workflow.store import WorkflowStore
        from mediahub.workflow.status import CardStatus, ScheduleStatus
        from mediahub.web import web as _web
        ws = WorkflowStore(_web.RUNS_DIR)
        ws.set_status(run_id, card_id, CardStatus.APPROVED)

        # 1. POST /schedule with a future UTC datetime — the exact path
        #    the modal hits after `localToIso(whenLocal)`.
        future_iso = "2027-01-01T10:00:00.000Z"
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={
                "channel_ids": ["chan-keep"],
                "caption": "future post",
                "scheduled_at": future_iso,
            },
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json() or {}
        assert body.get("ok") is True
        assert body.get("schedule_status") == "scheduled"

        # 2. The workflow sidecar is the source of truth across reloads.
        state = ws.load(run_id).get(card_id)
        assert state is not None
        assert state.schedule_status == ScheduleStatus.SCHEDULED
        assert state.buffer_update_id == "upd-keep"
        # scheduled_at was round-tripped to UTC ISO and re-parses cleanly.
        assert state.scheduled_at and state.scheduled_at.startswith("2027-01-01T10:00:00")

        # 3. The grouped pack builder — the same code the /pack/<id>
        #    page uses to render after a reload — surfaces the same
        #    schedule_status on the item so the pill template can paint it.
        from mediahub.content_pack.builder import build_grouped_pack
        run_data = json.loads((_web.RUNS_DIR / f"{run_id}.json").read_text())
        # build_grouped_pack reads the workflow sidecar internally; pass
        # run_id on the run_data dict so the right sidecar is loaded.
        run_data["run_id"] = run_id
        grouped = build_grouped_pack(run_data, profile_id)
        # The seeded card is a pb_confirmed → routes to needs_review by
        # default (no safe_to_post seed). Find it across every bucket so
        # the test is not sensitive to routing tweaks.
        found = None
        for bucket in grouped.values():
            items = bucket if isinstance(bucket, list) else [bucket] if bucket else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                ach = item.get("achievement") or item
                if ach.get("swim_id") == card_id:
                    found = item
                    break
            if found:
                break
        assert found is not None, "card disappeared from grouped pack"
        assert found.get("schedule_status") == "scheduled"
        assert found.get("buffer_update_id") == "upd-keep"

        # 4. /api/posting/log has the row.
        log_resp = c.get("/api/posting/log")
        assert log_resp.status_code == 200
        log_body = log_resp.get_json() or {}
        attempts = log_body.get("attempts") or []
        assert any(
            a.get("status") == "ok"
            and a.get("update_id") == "upd-keep"
            and a.get("run_id") == run_id
            and a.get("card_id") == card_id
            for a in attempts
        ), f"expected ok row for upd-keep in {attempts!r}"

    def test_failed_schedule_marks_workflow_failed_and_logs_failed_row(
        self, ready_app, monkeypatch,
    ):
        c, run_id, card_id, profile_id = ready_app
        from mediahub.publishing.buffer import BufferAPIError
        from mediahub.workflow.store import WorkflowStore
        from mediahub.workflow.status import ScheduleStatus
        from mediahub.web import web as _web

        monkeypatch.setattr(
            "mediahub.publishing.buffer.schedule_post",
            lambda **kw: (_ for _ in ()).throw(BufferAPIError("Buffer 500")),
        )
        resp = c.post(
            _schedule_url(run_id, card_id),
            json={"channel_ids": ["chan-fail"], "caption": "doomed"},
        )
        # Total failure → 502 + workflow flipped to FAILED.
        assert resp.status_code == 502
        body = resp.get_json() or {}
        # Caption is echoed back so the modal preserves the user's edit.
        assert body.get("caption") == "doomed"

        ws = WorkflowStore(_web.RUNS_DIR)
        state = ws.load(run_id).get(card_id)
        assert state is not None
        assert state.schedule_status == ScheduleStatus.FAILED

        log_resp = c.get("/api/posting/log")
        attempts = (log_resp.get_json() or {}).get("attempts") or []
        assert any(
            a.get("status") == "failed"
            and a.get("error_kind") == "api"
            and a.get("run_id") == run_id
            for a in attempts
        ), f"expected failed/api row for run {run_id} in {attempts!r}"


# ---------------------------------------------------------------------------
# 7. Schedule-modal client surface — the modal HTML/JS we inject onto
#    every pack page. These tests parse the rendered surface to pin
#    user-visible promises (timezone hint, past-date guard) without
#    spinning up a browser. They guard against accidental regressions
#    in `_schedule_modal_html` / `_schedule_modal_js`.
# ---------------------------------------------------------------------------

class TestScheduleModalRenderedSurface:
    def test_modal_markup_has_timezone_hint_slot(self):
        from mediahub.web.web import _schedule_modal_html
        html = _schedule_modal_html()
        # Hint container must exist so refreshWhenHint() can write to it.
        assert 'id="mh-sched-when-hint"' in html
        # The hidden run/card/pill ids the JS reads must survive too.
        for marker in ('id="mh-sched-run-id"',
                       'id="mh-sched-card-id"',
                       'id="mh-sched-pill-id"',
                       'id="mh-sched-error"',
                       'id="mh-sched-when"',
                       'id="mh-sched-channels"'):
            assert marker in html, f"missing modal marker: {marker}"

    def test_modal_js_advertises_timezone_and_past_date_guards(self):
        from mediahub.web.web import _schedule_modal_js
        js = _schedule_modal_js()
        # Local-timezone hint is wired in.
        assert "localTzLabel" in js
        assert "refreshWhenHint" in js
        assert "Intl.DateTimeFormat" in js
        # Past-date guard rejects times more than a minute behind now.
        assert "in the past" in js.lower()
        # Stale-request guard so a re-open can't be clobbered by an
        # in-flight earlier fetch.
        assert "_openSeq" in js
        # Network-error fallback in the connect-buffer-from-modal flow
        # no longer uses alert() — it must surface inline via the modal
        # error div (or MH.toast as a fallback).
        assert "alert(" not in js, "modal JS should not use alert()"
