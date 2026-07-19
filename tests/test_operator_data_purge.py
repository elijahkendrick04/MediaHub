"""Operator site-wide data purge — POST /operator/data/purge (PR #1190).

Unlike the sibling cache purge, this route removes SOURCE data — every
organisation's runs and every saved draft — and it is not re-derivable, so
the guard rails need pinning:

* the ``_require_operator`` gate: anonymous and plain signed-in sessions are
  bounced to the developer sign-in and nothing is deleted;
* the deletion scope: DB-row runs, disk-only runs (the DB ∪ disk union) and
  draft packs all go; uploads, club profiles and unrelated DATA_DIR trees
  survive; the success toast reports honest counts;
* the ``__`` sidecar guard: a lone ``<id>__workflow.json`` with no parent run
  is never treated as a phantom run id;
* the ``_delete_run`` sidecar sweep: the group-approver ledger
  (``<run_id>__approvals.json`` + ``.lock`` — approver email addresses) and
  the per-run pronunciation map are erased with the run, matching the GDPR
  Art. 17 framing of the cascade, and a neighbouring run id that shares a
  prefix is untouched.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PASSWORD = "twelve-chars-long"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Booted app on a fresh DATA_DIR with a test client."""
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
    if not app.secret_key:
        app.secret_key = "test-secret"

    with app.test_client() as client:
        yield {"client": client, "wm": wm, "tmp": tmp_path}


def _seed_run(env, run_id, *, profile_id="org-a", disk=True, db_row=True):
    """Seed a run on disk and/or in the DB (the purge enumerates the union)."""
    if disk:
        (env["tmp"] / "runs_v4" / f"{run_id}.json").write_text(
            json.dumps({"run_id": run_id, "profile_id": profile_id, "meet_name": "Test meet"}),
            encoding="utf-8",
        )
    if db_row:
        conn = env["wm"]._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, 'Test meet', 'f.hy3')",
            (run_id, profile_id),
        )
        conn.commit()
        conn.close()
    return run_id


def _seed_draft(profile_id="org-a"):
    from mediahub.club_platform.stub_pack_store import save_pack

    rec = save_pack(
        "free_text",
        {"free_text": "Great swim on Saturday"},
        [{"platform": "instagram", "caption": "Great swim!", "hashtags": []}],
        profile_id=profile_id,
    )
    return rec["pack_id"]


def _run_count(wm) -> int:
    conn = wm._db()
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    return int(n)


def _become_operator(client) -> None:
    with client.session_transaction() as s:
        s["dev_operator"] = True


def _toast_msg(client) -> str:
    with client.session_transaction() as s:
        return (s.get("mh_toast") or {}).get("msg", "")


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

def test_route_requires_operator(env):
    c, wm, tmp = env["client"], env["wm"], env["tmp"]
    _seed_run(env, "run-guard-1")
    pack_id = _seed_draft()

    # Anonymous → bounced to developer sign-in, nothing deleted.
    r = c.post("/operator/data/purge")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]

    # A signed-in regular user is still not the operator.
    c.post("/signup", data={"email": "user@club.org", "password": PASSWORD, "accept_terms": "1"})
    r = c.post("/operator/data/purge")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]

    # Source data survives both refused attempts.
    assert (tmp / "runs_v4" / "run-guard-1.json").exists()
    assert _run_count(wm) == 1
    assert (tmp / "stub_packs" / f"{pack_id}.json").exists()


# ---------------------------------------------------------------------------
# Deletion scope
# ---------------------------------------------------------------------------

def test_operator_purge_deletes_runs_and_drafts_spares_sources(env):
    c, wm, tmp = env["client"], env["wm"], env["tmp"]
    runs_dir = tmp / "runs_v4"

    # Run A: on disk AND in the DB, with the full sidecar family.
    _seed_run(env, "run-a-1")
    (runs_dir / "run-a-1__workflow.json").write_text('{"c1": {"status": "approved"}}')
    (runs_dir / "run-a-1__pronunciations.json").write_text('{"Maya": "MY-ah"}')
    from mediahub.workflow.approvals import ApprovalLedger

    ApprovalLedger(wm.RUNS_DIR).record("run-a-1", "c1", "approver@club.org")
    assert (runs_dir / "run-a-1__approvals.json").exists()
    assert (runs_dir / "run-a-1__approvals.lock").exists()

    # Run B: disk only (no DB row) — proves the DB ∪ disk enumeration.
    _seed_run(env, "run-b-1", db_row=False)
    # Run C: DB row only (no disk file) — proves the other side of the union.
    _seed_run(env, "run-c-1", disk=False)

    pack_id = _seed_draft()

    # Source data that must SURVIVE the purge.
    upload = tmp / "uploads_v4" / "meet.hy3"
    upload.write_bytes(b"HY3 bytes")
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A"))

    _become_operator(c)
    r = c.post("/operator/data/purge")
    assert r.status_code in (302, 303)
    assert "/settings/developer" in r.headers["Location"]

    # Every run gone — files, sidecars and DB rows.
    assert not (runs_dir / "run-a-1.json").exists()
    assert not (runs_dir / "run-b-1.json").exists()
    assert not list(runs_dir.glob("run-a-1__*")), "sidecars must not outlive the purge"
    assert _run_count(wm) == 0
    # Every draft gone.
    assert not (tmp / "stub_packs" / f"{pack_id}.json").exists()
    from mediahub.club_platform.stub_pack_store import list_packs

    assert list_packs() == []
    # Uploads and club profiles untouched.
    assert upload.exists()
    from mediahub.web.club_profile import load_profile

    assert load_profile("org-a") is not None
    # The toast reports honest counts (3 runs: A, B and the DB-only C).
    msg = _toast_msg(c)
    assert "3 run(s)" in msg
    assert "1 draft(s)" in msg


# ---------------------------------------------------------------------------
# Sidecar guard — no phantom run ids
# ---------------------------------------------------------------------------

def test_orphan_sidecar_is_not_a_phantom_run(env):
    c, tmp = env["client"], env["tmp"]
    runs_dir = tmp / "runs_v4"
    _seed_run(env, "run-real-1")
    # A lone workflow sidecar whose parent run never existed.
    orphan = runs_dir / "ghost__workflow.json"
    orphan.write_text("{}")

    _become_operator(c)
    r = c.post("/operator/data/purge")
    assert r.status_code in (302, 303)

    # Only the real run was counted — the sidecar never became run id
    # "ghost__workflow" (which _delete_run would have unlinked as
    # "ghost__workflow.json" and counted as a second run).
    assert "1 run(s)" in _toast_msg(c)
    assert orphan.exists()
    assert not (runs_dir / "run-real-1.json").exists()


# ---------------------------------------------------------------------------
# _delete_run sidecar sweep (single-run delete, purge and org deletion all
# route through it)
# ---------------------------------------------------------------------------

def test_delete_run_sweeps_approvals_and_pronunciation_sidecars(env):
    wm, tmp = env["wm"], env["tmp"]
    runs_dir = tmp / "runs_v4"
    _seed_run(env, "run-x")
    (runs_dir / "run-x__workflow.json").write_text("{}")
    (runs_dir / "run-x__pronunciations.json").write_text('{"Lee": "LEE"}')
    from mediahub.workflow.approvals import ApprovalLedger

    ApprovalLedger(wm.RUNS_DIR).record("run-x", "c1", "voter@club.org")
    assert (runs_dir / "run-x__approvals.json").exists()
    assert (runs_dir / "run-x__approvals.lock").exists()

    # A prefix-sharing neighbour whose sidecars must NOT be swept.
    _seed_run(env, "run-x2")
    (runs_dir / "run-x2__workflow.json").write_text("{}")

    assert wm._delete_run("run-x") is True

    assert not (runs_dir / "run-x.json").exists()
    assert not list(runs_dir.glob("run-x__*")), (
        "every run-x__* sidecar (workflow, approvals ledger + lock, "
        "pronunciations) must be erased with the run"
    )
    # The neighbour and its sidecar survive untouched.
    assert (runs_dir / "run-x2.json").exists()
    assert (runs_dir / "run-x2__workflow.json").exists()
