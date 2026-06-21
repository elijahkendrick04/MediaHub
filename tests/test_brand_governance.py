"""Roadmap 1.12 build 4 — brand governance: token locks + group approvers.

Unit-tests the pure rule evaluator and the votes ledger, then exercises the
approval-route enforcement: a locked palette blocks an off-brand approval, and
a group-approver rule on a bound workspace holds a card until enough distinct
people approve. All of it is opt-in — a club that configures neither sees the
old behaviour unchanged.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from mediahub.workflow import governance as gov
from mediahub.workflow.approvals import ApprovalLedger

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---- governance rule evaluator (pure) ----------------------------------


def test_normalise_rule_trivial_is_empty():
    assert gov.normalise_approver_rule({}) == {}
    assert gov.normalise_approver_rule({"min_approvers": 1}) == {}
    assert gov.normalise_approver_rule("nonsense") == {}


def test_normalise_rule_clamps_and_keeps():
    assert gov.normalise_approver_rule({"min_approvers": 3}) == {"min_approvers": 3}
    assert gov.normalise_approver_rule({"min_approvers": 99}) == {"min_approvers": 10}
    assert gov.normalise_approver_rule({"min_approvers": "x"}) == {}
    assert gov.normalise_approver_rule({"require_owner": True}) == {"require_owner": True}


def test_rule_is_active():
    assert gov.rule_is_active({}) is False
    assert gov.rule_is_active({"min_approvers": 2}) is True
    assert gov.rule_is_active({"require_owner": True}) is True


def test_evaluate_counts_distinct_approvers():
    rule = {"min_approvers": 2}
    ok, need, _ = gov.evaluate(rule, approver_emails=["a@x"], owner_emails=[])
    assert (ok, need) == (False, 1)
    ok2, need2, _ = gov.evaluate(rule, approver_emails=["a@x", "b@y"], owner_emails=[])
    assert (ok2, need2) == (True, 0)


def test_evaluate_requires_owner():
    rule = {"min_approvers": 1, "require_owner": True}
    ok, _, reason = gov.evaluate(rule, approver_emails=["vol@x"], owner_emails=["boss@x"])
    assert ok is False
    assert "owner" in reason.lower()
    ok2, _, _ = gov.evaluate(rule, approver_emails=["boss@x"], owner_emails=["boss@x"])
    assert ok2 is True


# ---- approval-votes ledger ---------------------------------------------


def test_ledger_records_distinct_votes(tmp_path):
    led = ApprovalLedger(tmp_path)
    led.record("run1", "card1", "A@Club.org")
    led.record("run1", "card1", "a@club.org")  # same person, different case → no dup
    led.record("run1", "card1", "b@club.org")
    assert sorted(led.approvers_for("run1", "card1")) == ["a@club.org", "b@club.org"]


def test_ledger_clear(tmp_path):
    led = ApprovalLedger(tmp_path)
    led.record("run1", "card1", "a@club.org")
    led.clear("run1", "card1")
    assert led.approvers_for("run1", "card1") == []


# ---- web: token-lock approval gate -------------------------------------


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    # the workflow / approval stores are module-global singletons — reset them so
    # they bind to this test's RUNS_DIR
    wm._wf_store = None
    wm._approval_ledger = None
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, cp, wm, tmp_path


def _seed_run_with_brief(tmp_path, pid, *, palette, run_id="run-g", card_id="swim_1"):
    runs = tmp_path / "runs_v4"
    (runs / run_id / "briefs").mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {"run_id": run_id, "profile_id": pid, "recognition_report": {"ranked_achievements": []}}
        ),
        encoding="utf-8",
    )
    from mediahub.creative_brief.generator import CreativeBrief

    brief = CreativeBrief(
        id="cb_g1",
        content_item_id=card_id,
        profile_id=pid,
        achievement_summary="",
        objective="",
        primary_hook="PB",
        confidence_label="NEW PB",
        tone="data-led",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={"headline_line1": "PB"},
        palette=palette,
        format_priority=["story"],
    )
    (runs / run_id / "briefs" / "cb_g1.json").write_text(
        json.dumps(brief.to_dict()), encoding="utf-8"
    )
    return run_id, card_id


def _make_default_kit(cp, pid, **kit_over):
    from mediahub.brand.kits import BrandKitRef, set_default_kit, upsert_kit

    prof = cp.load_profile(pid)
    kit = BrandKitRef(kit_id="govkit", name="Gov kit", role="event", **kit_over)
    upsert_kit(prof, kit)
    set_default_kit(prof, "govkit")
    cp.save_profile(prof)
    return kit


def test_locked_palette_blocks_off_brand_approval(app_client):
    client, cp, _wm, tmp_path = app_client
    prof = cp.ClubProfile(profile_id="lockclub", display_name="Lock Club")
    cp.save_profile(prof)
    _make_default_kit(cp, "lockclub", palette={"primary": "#0E2A47"}, locks=["palette"])
    # brief uses a wildly off-palette colour vs the kit's #0E2A47
    run_id, card_id = _seed_run_with_brief(
        tmp_path, "lockclub", palette={"primary": "#FF00FF", "secondary": "#101820"}
    )
    with client.session_transaction() as s:
        s["active_profile_id"] = "lockclub"
    r = client.post(
        f"/api/workflow/{run_id}/{card_id}",
        json={"action": "set_status", "status": "approved"},
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "brand_locked"


def test_unlocked_kit_allows_approval(app_client):
    client, cp, _wm, tmp_path = app_client
    prof = cp.ClubProfile(profile_id="freeclub", display_name="Free Club")
    cp.save_profile(prof)
    _make_default_kit(cp, "freeclub", palette={"primary": "#0E2A47"})  # no locks
    run_id, card_id = _seed_run_with_brief(
        tmp_path, "freeclub", palette={"primary": "#FF00FF", "secondary": "#101820"}
    )
    with client.session_transaction() as s:
        s["active_profile_id"] = "freeclub"
    r = client.post(
        f"/api/workflow/{run_id}/{card_id}",
        json={"action": "set_status", "status": "approved"},
    )
    assert r.status_code == 200
    assert r.get_json()["status"] == "approved"


# ---- web: group-approver hold (bound workspace) ------------------------


def test_group_rule_holds_card_until_quorum(app_client):
    client, cp, _wm, tmp_path = app_client
    pid = "govclub"
    prof = cp.ClubProfile(profile_id=pid, display_name="Gov Club")
    cp.save_profile(prof)
    _make_default_kit(cp, pid, approver_rule={"min_approvers": 2})
    # bind the workspace with two active members → group rules apply
    from mediahub.web import tenancy as _tenancy

    store = _tenancy.MembershipStore()
    store.add("owner@club.org", pid, role=_tenancy.ROLE_OWNER, status=_tenancy.STATUS_ACTIVE)
    store.add("vol@club.org", pid, role=_tenancy.ROLE_MEMBER, status=_tenancy.STATUS_ACTIVE)

    # on-brand brief (kit has no locks → brand-lock gate is inert)
    run_id, card_id = _seed_run_with_brief(
        tmp_path, pid, palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"}
    )

    # first approver: held in queue, one more needed
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
        s["user_email"] = "vol@club.org"
    r1 = client.post(
        f"/api/workflow/{run_id}/{card_id}",
        json={"action": "set_status", "status": "approved"},
    )
    body1 = r1.get_json()
    assert body1["status"] == "queue"
    assert body1.get("pending_approval") is True
    assert body1.get("approvals_needed") == 1

    # second, distinct approver: quorum met → approved
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
        s["user_email"] = "owner@club.org"
    r2 = client.post(
        f"/api/workflow/{run_id}/{card_id}",
        json={"action": "set_status", "status": "approved"},
    )
    body2 = r2.get_json()
    assert body2["status"] == "approved"


def test_group_rule_inert_on_pilot_workspace(app_client):
    # An unbound (pilot) workspace has no distinct approvers — the rule must not
    # hold the card, so a solo pilot user can still approve.
    client, cp, _wm, tmp_path = app_client
    pid = "pilotclub"
    prof = cp.ClubProfile(profile_id=pid, display_name="Pilot Club")
    cp.save_profile(prof)
    _make_default_kit(cp, pid, approver_rule={"min_approvers": 2})
    run_id, card_id = _seed_run_with_brief(
        tmp_path, pid, palette={"primary": "#0E5BFF", "secondary": "#101820", "accent": "#F4D58D"}
    )
    with client.session_transaction() as s:
        s["active_profile_id"] = pid  # no user_email, no membership → pilot
    r = client.post(
        f"/api/workflow/{run_id}/{card_id}",
        json={"action": "set_status", "status": "approved"},
    )
    assert r.get_json()["status"] == "approved"
