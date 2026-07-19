"""Regression tests for deep-review batch 8 (concurrency / state hardening).

  #79 schedule.create_task validates cron/once up front (a malformed schedule is
       rejected, not accepted and then silently never fired).
  #80 autonomy tools._wf_status fails CLOSED (None) on a read error, so the
       runner never re-queues over a status a human may have set.
  #83 AuditLog.read(limit=0) returns [] (not the whole log).
  #87 app_env._owns_run rejects a whitespace-only org id (tenant boundary).
  #90 notify.channels._latin1_header keeps an emoji/diacritic title deliverable.
"""

from __future__ import annotations

import pytest

from mediahub.autonomy.tools import AutonomyEnv, ToolContext, _wf_status
from mediahub.workflow.status import CardStatus


# ── #79 create_task validation ──────────────────────────────────────────────


def test_create_task_rejects_bad_once(tmp_path):
    from mediahub.workflow import schedule

    with pytest.raises(ValueError):
        schedule.create_task("n", "t", "once", "not-a-datetime", db_path=tmp_path / "s.db")


def test_create_task_rejects_bad_cron(tmp_path):
    # create_task deliberately tolerates croniter's absence (validation is
    # skipped, matching the fire path) — so without it this is a skip, not a fail.
    pytest.importorskip("croniter")
    from mediahub.workflow import schedule

    with pytest.raises(ValueError):
        schedule.create_task("n", "t", "cron", "not a valid cron", db_path=tmp_path / "s.db")


def test_create_task_accepts_valid_cron_and_once(tmp_path):
    from mediahub.workflow import schedule

    t1 = schedule.create_task("n", "t", "cron", "0 9 * * 1", db_path=tmp_path / "s.db")
    assert t1.id
    t2 = schedule.create_task("n", "t", "once", "2027-01-01T09:00:00", db_path=tmp_path / "s.db")
    assert t2.id


# ── #80 _wf_status fails closed ─────────────────────────────────────────────


class _RaisingWF:
    def load(self, run_id):  # noqa: ARG002
        raise RuntimeError("workflow sidecar unreadable")


class _EmptyWF:
    def load(self, run_id):  # noqa: ARG002
        return {}


def _ctx(wf) -> ToolContext:
    env = AutonomyEnv(
        load_run=lambda r: None,
        list_runs=lambda o: [],
        owns_run=lambda o, r: True,
        workflow=wf,
        gen_caption=lambda a, i: "",
    )
    return ToolContext(org_id="org", session_id="s", env=env)


def test_wf_status_fails_closed_on_read_error():
    # A read failure must NOT masquerade as QUEUE (which _queue_for_approval is
    # allowed to overwrite) — it returns None so the card is skipped.
    assert _wf_status(_ctx(_RaisingWF()), "run", "card") is None


def test_wf_status_absent_card_is_queue():
    # A genuinely-absent card (successful read, no state yet) is still QUEUE.
    assert _wf_status(_ctx(_EmptyWF()), "run", "card") == CardStatus.QUEUE


# ── #83 AuditLog.read(limit<=0) ─────────────────────────────────────────────


def test_auditlog_read_zero_limit_returns_empty(tmp_path):
    from mediahub.workflow.autonomy import AuditLog

    log = AuditLog(tmp_path)
    log.record("org", "sess", "tool_call", tool="draft_caption")
    assert log.read("org", limit=5)  # the row is there
    assert log.read("org", limit=0) == []  # ...but limit 0 means none
    assert log.read("org", limit=-1) == []


# ── #87 _owns_run whitespace org ────────────────────────────────────────────


def test_owns_run_rejects_whitespace_org(monkeypatch):
    from mediahub.autonomy import app_env

    # An unowned run (empty profile_id) must not be claimable by a blank org id.
    monkeypatch.setattr(app_env, "_load_run", lambda rid: {"profile_id": ""})
    assert app_env._owns_run("   ", "run1") is False
    assert app_env._owns_run("", "run1") is False
    # A real match still works.
    monkeypatch.setattr(app_env, "_load_run", lambda rid: {"profile_id": "clubA"})
    assert app_env._owns_run("clubA", "run1") is True


# ── #90 latin-1-safe ntfy title ─────────────────────────────────────────────


def test_latin1_header_keeps_emoji_title_deliverable():
    from mediahub.notify.channels import _latin1_header

    out = _latin1_header("🏊 Riverside Swimming Club")
    out.encode("latin-1")  # must not raise (requests encodes headers latin-1)
    # An already-clean title is passed through untouched.
    assert _latin1_header("Riverside Swimming Club") == "Riverside Swimming Club"


def test_latin1_header_long_title_stays_single_line():
    from mediahub.notify.channels import _latin1_header

    # A non-Latin-1 title whose RFC 2047 encoding exceeds Header's ~76-char
    # fold point must NOT come back folded ("\n ") — requests rejects any
    # header value containing CR/LF, which would kill the push outright.
    title = "🏊 Riverside Swimming Club — County Championships Day 2 Finals résumé"
    out = _latin1_header(title)
    assert "\n" not in out and "\r" not in out
    out.encode("latin-1")  # must not raise
    # The unfolded encoded-words still decode back to the full title.
    import email.header as eh

    decoded = "".join(
        (b.decode(c or "ascii") if isinstance(b, bytes) else b)
        for b, c in eh.decode_header(out)
    )
    assert decoded == title
