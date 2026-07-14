"""Regression tests for the approval-state torn-write / lost-update fix (#76).

Under ``gunicorn --workers 2`` the workflow + approvals sidecars were persisted
non-atomically and guarded only by a per-process lock, so concurrent writes from
different workers could silently wipe or drop human approval decisions. The
stores now write atomically (unique tmp + os.replace) and hold an ``flock`` around
load -> mutate -> save. These tests exercise the multi-PROCESS path the in-process
lock never covered; they pass deterministically with the fix and lose data without
it.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

from mediahub.workflow.approvals import ApprovalLedger
from mediahub.workflow.status import CardStatus
from mediahub.workflow.store import WorkflowStore


def _record_vote(args):
    runs_dir, run_id, card_id, email = args
    ApprovalLedger(Path(runs_dir)).record(run_id, card_id, email)


def _approve_card(args):
    runs_dir, run_id, card_id = args
    WorkflowStore(Path(runs_dir)).set_status(run_id, card_id, CardStatus.APPROVED)


def test_concurrent_votes_on_one_card_all_survive(tmp_path: Path):
    run_id, card_id = "runV", "card1"
    n = 16
    ctx = mp.get_context("fork")
    with ctx.Pool(4) as pool:
        pool.map(
            _record_vote,
            [(str(tmp_path), run_id, card_id, f"voter{i}@club") for i in range(n)],
        )
    approvers = ApprovalLedger(tmp_path).approvers_for(run_id, card_id)
    assert sorted(approvers) == sorted(f"voter{i}@club" for i in range(n)), (
        f"lost votes under cross-process contention: {approvers}"
    )


def test_concurrent_status_writes_on_distinct_cards_all_survive(tmp_path: Path):
    run_id = "runS"
    n = 16
    ctx = mp.get_context("fork")
    with ctx.Pool(4) as pool:
        pool.map(
            _approve_card,
            [(str(tmp_path), run_id, f"card{i}") for i in range(n)],
        )
    summary = WorkflowStore(tmp_path).summary(run_id)
    assert summary["approved"] == n, f"lost status updates (last-writer-wins): {summary}"


def test_ledger_marks_machine_votes_but_leaves_human_votes_byte_identical(tmp_path: Path):
    """Finding #116: a public-API/MCP vote is stamped ``actor_kind=api_token`` so
    the group-approval trail can tell an agent from a human; a human vote stays
    exactly ``{email, at}`` on disk (no new key), and counting is unchanged."""
    ledger = ApprovalLedger(tmp_path)
    ledger.record("runK", "cardA", "member@club")  # human (default)
    ledger.record("runK", "cardA", "agent@club", actor_kind="api_token")

    raw = json.loads((tmp_path / "runK__approvals.json").read_text())["cardA"]
    human = next(v for v in raw if v["email"] == "member@club")
    machine = next(v for v in raw if v["email"] == "agent@club")

    assert set(human.keys()) == {"email", "at"}  # unchanged shape for humans
    assert machine.get("actor_kind") == "api_token"
    # Both still count as distinct approvers — attribution, not a power change.
    assert sorted(ledger.approvers_for("runK", "cardA")) == ["agent@club", "member@club"]


def test_corrupt_sidecar_is_preserved_not_wiped(tmp_path: Path):
    store = WorkflowStore(tmp_path)
    path = tmp_path / "runC__workflow.json"
    path.write_text("{ this is not valid json ", encoding="utf-8")  # simulate corruption

    # load() must not raise, and must not silently discard the evidence.
    assert store.load("runC") == {}
    assert (tmp_path / "runC__workflow.json.corrupt").exists(), "corrupt file was not preserved"

    # A subsequent mutation still works and yields a valid, re-readable file.
    store.set_status("runC", "cardX", CardStatus.APPROVED)
    reloaded = store.load("runC")
    assert reloaded["cardX"].status == CardStatus.APPROVED
    assert json.loads(path.read_text())  # the live file is valid JSON again
