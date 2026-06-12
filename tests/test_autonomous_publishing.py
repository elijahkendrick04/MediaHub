"""P2.2 + P2.3 — the human-approval signal and the single publish gate.

Pins the Phase-2 exit criterion end-to-end:
  * a content type can be set to any AutonomyLevel (P2.4 store);
  * ``fully_autonomous`` publishes ONLY when every guardrail + the
    confidence gate pass (kill switch, per-type policy, provenance,
    confidence threshold, brand safety, safeguarding, rate limit);
  * the global kill switch halts publishing instantly — even mid-cycle;
  * every autonomous decision lands in the immutable per-org audit ledger;
  * gated types pause on the human signal; autonomy degrades to approval,
    never the other way round; human decisions are never revisited.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mediahub.publishing.kill_switch import KILL_SWITCH_ENV
from mediahub.publishing.per_type_policy import save_policy
from mediahub.publishing.publish_gate import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    PublishGateBlocked,
    assert_publish_gate,
    evaluate_publish_gate,
    load_thresholds,
    publish_gate_status,
    save_thresholds,
    threshold_for,
)
from mediahub.workflow.approval import apply_approval_signal
from mediahub.workflow.autonomy import AuditLog
from mediahub.workflow.status import CardStatus, ScheduleStatus
from mediahub.workflow.store import WorkflowStore

ORG = "org-auto"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated DATA_DIR/RUNS_DIR/profiles for every store the chain touches."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    monkeypatch.delenv("BUFFER_ACCESS_TOKEN", raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _good_card(**overrides) -> dict:
    card = {
        "safe_to_post": {"level": "safe", "reason": "High confidence evidence."},
        "confidence": 0.97,
        "age": 23,
        "raw_facts": {},
    }
    card.update(overrides)
    return card


GOOD_CAPTION = "Emma Jones takes gold in the 100m Free — a two-second PB at County Champs."


def _seed_run(tmp_path, *, run_id: str = "runX", profile_id: str = ORG, achievements=None):
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    ranked = []
    for i, ach in enumerate(achievements or [], start=1):
        ranked.append(
            {
                "rank": i,
                "priority": 100 - i,
                "achievement": ach,
                "safe_to_post": ach.pop("_safe_to_post", {"level": "safe", "reason": "ok"}),
            }
        )
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "recognition_report": {"ranked_achievements": ranked},
            }
        ),
        encoding="utf-8",
    )
    return run_id


def _ach(
    swim_id: str, *, confidence: float = 0.97, age: int = 25, headline: str = GOOD_CAPTION, **kw
):
    out = {"swim_id": swim_id, "confidence": confidence, "age": age, "headline": headline}
    out.update(kw)
    return out


# ---------------------------------------------------------------------------
# The gate — every guardrail, individually and together
# ---------------------------------------------------------------------------


class TestPublishGate:
    def test_default_policy_blocks_with_full_explanation(self, env):
        v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert not v.allowed
        assert any("approval_required" in b for b in v.blockers())
        # All checks are evaluated (no short-circuit) — the verdict answers
        # "what ALL would have to change", and is explainable per check.
        assert {c.name for c in v.checks} == {
            "kill_switch",
            "type_policy",
            "provenance",
            "confidence",
            "brand_safety",
            "safeguarding",
            "rate_limit",
        }
        assert all(c.detail for c in v.checks)

    def test_fully_autonomous_good_card_passes_and_is_audited(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        v = evaluate_publish_gate(
            ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION, run_id="r1", card_id="c1"
        )
        assert v.allowed and v.blockers() == []
        entries = AuditLog().read(ORG)
        assert any(e["kind"] == "publish_gate" and "ALLOWED" in e["result"] for e in entries)

    def test_blocked_verdicts_are_audited_too(self, env):
        v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert not v.allowed
        entries = AuditLog().read(ORG)
        assert any(e["kind"] == "publish_gate" and "BLOCKED" in e["result"] for e in entries)

    def test_kill_switch_blocks_instantly(self, env, monkeypatch):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        monkeypatch.setenv(KILL_SWITCH_ENV, "1")
        v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert not v.allowed
        assert any(b.startswith("kill_switch") for b in v.blockers())

    @pytest.mark.parametrize(
        "level,ok",
        [
            ("safe", True),
            ("post", True),  # the run trust report's vocabulary
            ("needs_review", False),
            ("review", False),
            ("do_not_post", False),
            ("hold", False),
            ("certainly", False),  # unknown vocabulary fails closed
        ],
    )
    def test_provenance_vocabularies(self, env, level, ok):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        v = evaluate_publish_gate(
            ORG, "meet_recap", card=_good_card(safe_to_post={"level": level}), caption=GOOD_CAPTION
        )
        assert ([b for b in v.blockers() if b.startswith("provenance")] == []) is ok

    def test_missing_provenance_fails_closed(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        card = _good_card()
        del card["safe_to_post"]
        v = evaluate_publish_gate(ORG, "meet_recap", card=card, caption=GOOD_CAPTION)
        assert any("no safe-to-post verdict" in b for b in v.blockers())

    def test_confidence_gate_default_and_per_type_threshold(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        v = evaluate_publish_gate(
            ORG, "meet_recap", card=_good_card(confidence=0.8), caption=GOOD_CAPTION
        )
        assert any(b.startswith("confidence") for b in v.blockers())
        # The operator lowers the bar for this type — 0.8 now clears it.
        save_thresholds(ORG, {"meet_recap": 0.7})
        assert threshold_for(ORG, "meet_recap") == 0.7
        v2 = evaluate_publish_gate(
            ORG, "meet_recap", card=_good_card(confidence=0.8), caption=GOOD_CAPTION
        )
        assert [b for b in v2.blockers() if b.startswith("confidence")] == []

    def test_thresholds_are_clamped_and_canonicalised(self, env):
        saved = save_thresholds(
            ORG, {"weekend_preview": 0.2, "meet_recap": "nonsense", "pb_spotlight": 0.9}
        )
        # Legacy slug canonicalises; 0.2 clamps up to the 0.5 floor; junk drops.
        assert saved == {"event_preview": 0.5, "pb_spotlight": 0.9}
        assert load_thresholds(ORG) == saved
        assert threshold_for(ORG, "meet_recap") == DEFAULT_CONFIDENCE_THRESHOLD

    def test_missing_confidence_fails_closed(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        card = _good_card()
        del card["confidence"]
        v = evaluate_publish_gate(ORG, "meet_recap", card=card, caption=GOOD_CAPTION)
        assert any("no numeric confidence" in b for b in v.blockers())

    def test_brand_safety_blocks_empty_ai_tells_and_org_banned_phrases(self, env):
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        save_profile(
            ClubProfile(profile_id=ORG, display_name="Auto SC", brand_phrases_to_avoid=["smash it"])
        )
        for caption, needle in [
            ("", "no caption"),
            ("We delve into a big weekend of racing.", "AI-tell"),
            ("Go on, SMASH IT this weekend!", "banned phrase"),
            ("x" * 2300, "platform cap"),
        ]:
            v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=caption)
            assert any(needle in b for b in v.blockers()), (caption[:30], v.blockers())
        ok = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert [b for b in ok.blockers() if b.startswith("brand_safety")] == []

    def test_safeguarding_blocks_minors_always(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(age=14), caption=GOOD_CAPTION)
        assert any("minor" in b and "ADR-0003" in b for b in v.blockers())
        # Age inside raw_facts is found too.
        card = _good_card(age=None, raw_facts={"age": 16})
        v2 = evaluate_publish_gate(ORG, "meet_recap", card=card, caption=GOOD_CAPTION)
        assert any("minor" in b for b in v2.blockers())

    def test_rate_limit_uses_posting_log_window(self, env, monkeypatch):
        from mediahub.publishing.posting_log import record_attempt

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        monkeypatch.setenv("MEDIAHUB_AUTONOMOUS_HOURLY_CAP", "2")
        now = datetime.now(timezone.utc)
        for i in range(2):
            record_attempt(
                profile_id=ORG,
                run_id="r1",
                card_id=f"c{i}",
                status="ok",
                attempted_at=(now - timedelta(minutes=5 * (i + 1))).isoformat(),
            )
        v = evaluate_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert any("hourly cap" in b for b in v.blockers())
        # Another org's posts never count against this org (isolation).
        v_other = evaluate_publish_gate(
            "org-other", "meet_recap", card=_good_card(), caption=GOOD_CAPTION
        )
        assert [b for b in v_other.blockers() if b.startswith("rate_limit")] == []

    def test_assert_raises_with_verdict(self, env):
        with pytest.raises(PublishGateBlocked) as exc:
            assert_publish_gate(ORG, "meet_recap", card=_good_card(), caption=GOOD_CAPTION)
        assert exc.value.verdict.allowed is False

    def test_status_summary_never_raises(self, env):
        save_thresholds(ORG, {"meet_recap": 0.75})
        status = publish_gate_status(ORG)
        assert status["thresholds"] == {"meet_recap": 0.75}
        assert status["hourly_cap"] >= 0 and status["daily_cap"] >= 0


# ---------------------------------------------------------------------------
# The approval signal — who drives QUEUE → APPROVED
# ---------------------------------------------------------------------------


class TestApprovalSignal:
    def test_gated_types_pause_on_the_signal(self, env):
        run_id = _seed_run(env, achievements=[_ach("s1"), _ach("s2")])
        out = apply_approval_signal(ORG, run_id)
        assert out["ok"] and out["policy_level"] == "approval_required"
        assert out["counts"] == {"awaiting_human": 2}
        # Nothing moved: the cards still await the human.
        states = WorkflowStore(env / "runs_v4").load(run_id)
        assert all(s.status == CardStatus.QUEUE for s in states.values()) or not states

    def test_draft_only_never_enters_the_queue(self, env):
        save_policy(ORG, {"meet_recap": "draft_only"})
        run_id = _seed_run(env, achievements=[_ach("s1")])
        out = apply_approval_signal(ORG, run_id)
        assert out["counts"] == {"draft_only": 1}

    def test_autonomous_type_skips_the_wait_when_the_gate_passes(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        run_id = _seed_run(env, achievements=[_ach("s1")])
        out = apply_approval_signal(ORG, run_id)
        assert out["counts"] == {"auto_approved": 1}
        state = WorkflowStore(env / "runs_v4").load(run_id)["s1"]
        assert state.status == CardStatus.APPROVED
        assert "Auto-approved" in (state.notes or "")
        # No channels configured → approved, honestly not published.
        assert out["published"] == 0
        assert "no autonomous channels" in out["outcomes"][0]["publish_detail"]
        # The decision chain is in the immutable ledger.
        kinds = [e["kind"] for e in AuditLog().read(ORG)]
        assert "publish_gate" in kinds and "auto_approve" in kinds

    def test_guardrail_failure_degrades_to_human_approval(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        run_id = _seed_run(
            env,
            achievements=[
                _ach("adult", age=25),
                _ach("minor", age=15),  # safeguarding must hold this one
            ],
        )
        out = apply_approval_signal(ORG, run_id)
        assert out["counts"] == {"auto_approved": 1, "held_for_human": 1}
        held = next(o for o in out["outcomes"] if o["decision"] == "held_for_human")
        assert held["card_id"] == "minor"
        assert any("minor" in b for b in held["blockers"])
        states = WorkflowStore(env / "runs_v4").load(run_id)
        assert states["adult"].status == CardStatus.APPROVED
        assert "minor" not in states or states["minor"].status == CardStatus.QUEUE

    def test_human_decisions_are_never_revisited(self, env):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        run_id = _seed_run(env, achievements=[_ach("s1"), _ach("s2")])
        store = WorkflowStore(env / "runs_v4")
        store.set_status(run_id, "s1", CardStatus.REJECTED)
        out = apply_approval_signal(ORG, run_id)
        assert out["considered"] == 1  # only s2
        assert store.load(run_id)["s1"].status == CardStatus.REJECTED

    def test_tenant_isolation_refuses_foreign_runs(self, env):
        run_id = _seed_run(env, profile_id="org-other", achievements=[_ach("s1")])
        out = apply_approval_signal(ORG, run_id)
        assert out["ok"] is False

    def test_autonomous_publish_rides_the_buffer_path(self, env, monkeypatch):
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        save_profile(
            ClubProfile(
                profile_id=ORG,
                display_name="Auto SC",
                buffer_access_token="tok-123",
                autonomy_channel_ids=["chan-1", "chan-2"],
            )
        )
        calls: list[dict] = []

        def fake_schedule_post(*, token, channel_id, text, media_urls=None, scheduled_at=None):
            calls.append({"token": token, "channel_id": channel_id, "text": text})
            return {"ok": True, "update_id": f"upd-{channel_id}", "channel_id": channel_id}

        import mediahub.workflow.approval as approval_mod

        monkeypatch.setattr("mediahub.publishing.buffer.schedule_post", fake_schedule_post)
        run_id = _seed_run(env, achievements=[_ach("s1")])
        out = approval_mod.apply_approval_signal(ORG, run_id)

        assert out["published"] == 1
        assert len(calls) == 2 and {c["channel_id"] for c in calls} == {"chan-1", "chan-2"}
        assert all(c["token"] == "tok-123" for c in calls)
        state = WorkflowStore(env / "runs_v4").load(run_id)["s1"]
        assert state.status == CardStatus.APPROVED
        assert state.schedule_status == ScheduleStatus.SCHEDULED
        assert "upd-chan-1" in (state.buffer_update_id or "")
        # Every attempt is in the posting log; the decision is in the ledger.
        from mediahub.publishing.posting_log import recent_attempts

        rows = recent_attempts(ORG, limit=10)
        assert len(rows) == 2 and all(r["status"] == "ok" for r in rows)
        assert any(e["kind"] == "auto_publish" for e in AuditLog().read(ORG))

    def test_buffer_failure_is_honest_card_stays_approved(self, env, monkeypatch):
        from mediahub.publishing.buffer import BufferAuthError
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        save_profile(
            ClubProfile(
                profile_id=ORG,
                display_name="Auto SC",
                buffer_access_token="tok-bad",
                autonomy_channel_ids=["chan-1"],
            )
        )

        def failing_schedule_post(**kw):
            raise BufferAuthError("Buffer rejected the token")

        monkeypatch.setattr("mediahub.publishing.buffer.schedule_post", failing_schedule_post)
        run_id = _seed_run(env, achievements=[_ach("s1")])
        out = apply_approval_signal(ORG, run_id)
        assert out["published"] == 0
        assert "publish failed" in out["outcomes"][0]["publish_detail"]
        state = WorkflowStore(env / "runs_v4").load(run_id)["s1"]
        assert state.status == CardStatus.APPROVED  # approved, honestly unposted
        assert state.schedule_status == ScheduleStatus.FAILED

    def test_kill_switch_halts_the_whole_cycle_instantly(self, env, monkeypatch):
        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        run_id = _seed_run(env, achievements=[_ach("s1"), _ach("s2")])
        monkeypatch.setenv(KILL_SWITCH_ENV, "1")
        out = apply_approval_signal(ORG, run_id)
        assert out["counts"] == {"held_for_human": 2}
        assert out["published"] == 0
        states = WorkflowStore(env / "runs_v4").load(run_id)
        assert all(s.status != CardStatus.APPROVED for s in states.values()) or not states

    def test_scheduler_task_type_registers(self, env):
        from mediahub.scheduler import _REGISTRY
        from mediahub.workflow.approval import register_approval_signal_task

        register_approval_signal_task()
        assert "approval_signal" in _REGISTRY


# ---------------------------------------------------------------------------
# The Phase-2 exit criterion, end to end
# ---------------------------------------------------------------------------


def test_phase2_exit_criterion_end_to_end(env, monkeypatch):
    """Any level settable; fully_autonomous publishes only via the guardrails
    + confidence gate; the kill switch halts instantly; every autonomous
    decision is in the immutable audit trail."""
    from mediahub.publishing.per_type_policy import load_policy
    from mediahub.web.club_profile import ClubProfile, save_profile

    # 1. A content type can be set to any AutonomyLevel.
    for level in ("draft_only", "approval_required", "fully_autonomous"):
        save_policy(ORG, {"meet_recap": level})
        assert load_policy(ORG)["meet_recap"] == level

    # 2. fully_autonomous publishes ONLY when guardrails + confidence pass.
    save_profile(
        ClubProfile(
            profile_id=ORG,
            display_name="Auto SC",
            buffer_access_token="tok-123",
            autonomy_channel_ids=["chan-1"],
        )
    )
    published: list[str] = []
    monkeypatch.setattr(
        "mediahub.publishing.buffer.schedule_post",
        lambda **kw: (published.append(kw["channel_id"]), {"ok": True, "update_id": "u1"})[1],
    )
    run_id = _seed_run(
        env,
        achievements=[
            _ach("good", confidence=0.97, age=25),
            _ach("lowconf", confidence=0.6, age=25),  # confidence gate holds it
        ],
    )
    out = apply_approval_signal(ORG, run_id)
    assert out["counts"] == {"auto_approved": 1, "held_for_human": 1}
    assert out["published"] == 1 and published == ["chan-1"]

    # 3. The kill switch halts publishing instantly.
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    run2 = _seed_run(env, run_id="runY", achievements=[_ach("g2")])
    out2 = apply_approval_signal(ORG, run2)
    assert out2["published"] == 0 and out2["counts"] == {"held_for_human": 1}

    # 4. Every autonomous decision is recorded, immutably and explainably.
    entries = AuditLog().read(ORG, limit=100)
    kinds = {e["kind"] for e in entries}
    assert {"publish_gate", "auto_approve", "auto_publish"} <= kinds
    blocked = [e for e in entries if e["kind"] == "publish_gate" and "BLOCKED" in e["result"]]
    assert any("confidence" in e["result"] for e in blocked)
    assert any("kill switch" in e["result"] for e in blocked)


# ---------------------------------------------------------------------------
# Web surface — org-scoped sweep + threshold/channel controls + healthz
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_org(env, monkeypatch):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="Auto SC"))
    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str = ORG):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


class TestWebSurface:
    def test_sweep_requires_org_and_run(self, app_with_org):
        with app_with_org.test_client() as client:
            assert client.post("/api/autonomy/sweep", json={"run_id": "x"}).status_code == 403
            _with_org(client)
            # No run_id sweeps the org's recent runs (the settings-page
            # "Run autonomy check now" path) — fine even with zero runs.
            resp = client.post("/api/autonomy/sweep", json={})
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ok"] is True and body["swept_runs"] == 0
            # A foreign/missing run is refused, not leaked.
            assert client.post("/api/autonomy/sweep", json={"run_id": "nope"}).status_code == 404

    def test_sweep_reports_the_signal(self, app_with_org, env):
        run_id = _seed_run(env, achievements=[_ach("s1")])
        with app_with_org.test_client() as client:
            _with_org(client)
            body = client.post("/api/autonomy/sweep", json={"run_id": run_id}).get_json()
        assert body["ok"] is True
        assert body["counts"] == {"awaiting_human": 1}  # default policy pauses

    def test_policy_save_carries_thresholds_and_channels(self, app_with_org, env):
        from mediahub.web.club_profile import load_profile

        with app_with_org.test_client() as client:
            _with_org(client)
            resp = client.post(
                "/api/autonomy/policy",
                data={
                    "meet_recap": "fully_autonomous",
                    "threshold_meet_recap": "0.7",
                    "autonomy_channel_ids": "chan-1, chan-2,,",
                },
            )
            assert resp.status_code == 200
        from mediahub.publishing.per_type_policy import load_policy

        assert load_policy(ORG)["meet_recap"] == "fully_autonomous"
        assert load_thresholds(ORG) == {"meet_recap": 0.7}
        assert load_profile(ORG).autonomy_channel_ids == ["chan-1", "chan-2"]

    def test_settings_tab_renders_threshold_and_channel_controls(self, app_with_org):
        with app_with_org.test_client() as client:
            _with_org(client)
            html = client.get("/settings").get_data(as_text=True)
        assert "Auto-publish confidence" in html
        assert 'name="threshold_meet_recap"' in html
        assert "Autonomous channels" in html

    def test_healthz_reports_publish_gate(self, app_with_org):
        with app_with_org.test_client() as client:
            _with_org(client)
            deps = client.get("/healthz/deps").get_json()["deps"]
        gate = deps["publish_gate"]
        assert gate["hourly_cap"] >= 0 and gate["daily_cap"] >= 0
        assert "kill_switch_engaged" in gate


def test_audit_log_never_corrupts_on_oversized_args(env):
    """The P2.1 fix: a huge args payload must neither crash the audited
    operation nor write an unparseable line."""
    log = AuditLog()
    log.record(ORG, "s1", "tool_call", tool="t", args={"ids": ["x" * 50] * 200}, result="ok")
    entries = log.read(ORG)
    assert entries, "the oversized entry must still be written and parseable"
    assert "_truncated" in entries[-1]["args"]


class TestApprovalSignalCadence:
    """The cadence that makes fully_autonomous real: one hourly scheduled
    approval_signal task per opted-in org, reconciled on every policy save."""

    def _tasks(self, org_id=ORG):
        from mediahub.workflow.schedule import list_tasks

        return [
            t
            for t in list_tasks()
            if t.task_type == "approval_signal" and (t.params or {}).get("org_id") == org_id
        ]

    def test_opt_in_creates_task_and_revert_removes_it(self, env):
        from mediahub.workflow.approval import ensure_approval_signal_cadence

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        assert ensure_approval_signal_cadence(ORG) is True
        tasks = self._tasks()
        assert len(tasks) == 1 and tasks[0].schedule_kind == "cron"

        save_policy(ORG, {"meet_recap": "approval_required"})
        assert ensure_approval_signal_cadence(ORG) is False
        assert self._tasks() == []

    def test_reconcile_is_idempotent_and_collapses_duplicates(self, env):
        from mediahub.workflow.approval import ensure_approval_signal_cadence
        from mediahub.workflow.schedule import create_task

        save_policy(ORG, {"meet_recap": "fully_autonomous"})
        ensure_approval_signal_cadence(ORG)
        ensure_approval_signal_cadence(ORG)
        # Simulate a startup race writing a second row.
        create_task(
            name="dup",
            task_type="approval_signal",
            schedule_kind="cron",
            schedule_expr="0 * * * *",
            params={"org_id": ORG},
        )
        ensure_approval_signal_cadence(ORG)
        assert len(self._tasks()) == 1

    def test_policy_save_route_reconciles_cadence(self, app_with_org):
        with app_with_org.test_client() as client:
            _with_org(client)
            resp = client.post("/api/autonomy/policy", data={"meet_recap": "fully_autonomous"})
            assert resp.get_json()["ok"] is True
            assert len(self._tasks()) == 1
            resp = client.post("/api/autonomy/policy", data={"meet_recap": "approval_required"})
            assert resp.get_json()["ok"] is True
            assert self._tasks() == []

    def test_settings_page_shows_activity_log_and_operations(self, app_with_org):
        AuditLog().record(ORG, "s1", "auto_approve", tool="apply_approval_signal", result="ok")
        with app_with_org.test_client() as client:
            _with_org(client)
            html = client.get("/settings").get_data(as_text=True)
        assert "Autonomy activity log" in html
        assert "auto_approve" in html
        assert "Run autonomy check now" in html
