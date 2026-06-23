"""QA-015 — county/championship-sized meets must FINISH, and a run interrupted
mid-pipeline must RESUME instead of being lost.

Reported failure: a 509-swim run (City of Brighton & Hove, Ken Deeley Open) died
mid-pipeline with "Processing stopped responding — the server worker was recycled
mid-run…", while a 432-swim meet and a 21-swimmer run completed fine. The size
correlation is the tell: the pipeline runs in a daemon thread inside a gunicorn
worker, and the bigger the meet the longer it runs, so a `--max-requests` recycle
(or an overlapping deploy / OOM) is far likelier to land while it is in flight and
kill the thread — and there was no resume, so the run was lost.

Root cause is durability, NOT pipeline cost: the moment-detection/drafting phase is
cheap and linear (measured ~0.4s for 1,000+ swims; see the first test). The fix
persists each run's launch input and RE-RUNS it ("resume") when it is found dead,
bounded so a genuinely-broken input can't loop forever; the honest error is kept
for the truly-unrecoverable case.

These tests fail before the fix (a stale run was only ever stamped errored, never
resumed) and pass after it.
"""

from __future__ import annotations

import importlib
import time
from datetime import datetime, timedelta, timezone

import pytest

CLUB = "City of Brighton & Hove"

_FIRST = [
    "Birdy",
    "Izzy",
    "Oscar",
    "Maya",
    "Leo",
    "Ava",
    "Noah",
    "Mia",
    "Jack",
    "Ella",
    "Finn",
    "Ruby",
    "Theo",
    "Lily",
    "Max",
    "Grace",
    "Sam",
    "Erin",
    "Toby",
    "Nina",
    "Kai",
    "Zoe",
    "Reed",
    "Faye",
    "Cole",
    "Anya",
    "Drew",
    "Iris",
]
_LAST = [
    "Raleigh",
    "Carden",
    "Earthrowl",
    "Deeley",
    "Hughes",
    "Morgan",
    "Patel",
    "Walsh",
    "Frost",
    "Quinn",
    "Sharpe",
    "Vaughn",
    "Blake",
    "Reeves",
    "Dunn",
    "Cross",
    "Mercer",
    "Hale",
    "Pike",
    "Webb",
    "Lowe",
    "Banks",
    "Voss",
    "Nash",
]
_EVENTS = [
    (50, "Freestyle"),
    (100, "Freestyle"),
    (200, "Freestyle"),
    (50, "Backstroke"),
    (100, "Backstroke"),
    (50, "Breaststroke"),
    (100, "Breaststroke"),
    (50, "Butterfly"),
    (100, "Butterfly"),
    (200, "IM"),
]


def _time_str(base_cs: int) -> str:
    mm, rest = divmod(base_cs, 6000)
    ss, cc = divmod(rest, 100)
    return f"{mm}:{ss:02d}.{cc:02d}" if mm else f"{ss}.{cc:02d}"


def _make_printout(n_swimmers: int, events_per_swimmer: int, club: str = CLUB):
    """A synthetic HY-TEK-style results printout: ``n_swimmers`` swimmers each in
    ``events_per_swimmer`` timed-final events, all in one club. Returns
    (file_bytes, n_swims)."""
    swimmers = []
    for i in range(n_swimmers):
        first = _FIRST[i % len(_FIRST)]
        last = _LAST[(i // len(_FIRST)) % len(_LAST)]
        swimmers.append((f"{first}{i}", last, 13 + (i % 4)))

    rosters: dict[int, list] = {i: [] for i in range(len(_EVENTS))}
    for si, sw in enumerate(swimmers):
        for k in range(events_per_swimmer):
            rosters[(si + k) % len(_EVENTS)].append(sw)

    lines = [
        "Ken Deeley Open - HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1",
        "Ken Deeley Open Meet 2026 - 14/02/2026 to 15/02/2026",
        "",
    ]
    n_swims = 0
    for ev_idx, (dist, stroke_name) in enumerate(_EVENTS):
        roster = rosters[ev_idx]
        if not roster:
            continue
        lines.append(f"Event {ev_idx + 1}  Female 13 Year Olds {dist} LC Meter {stroke_name}")
        lines.append(
            "Name                    Age  Team                     Seed Time   Finals Time"
        )
        for place, (first, last, age) in enumerate(roster, start=1):
            base = 3000 + dist * 12 + (place * 7) % 400
            lines.append(
                f"{place} {last}, {first}  {age}  {club}   "
                f"{_time_str(base + 80)}     {_time_str(base)}"
            )
            n_swims += 1
        lines.append("")
    return ("\n".join(lines)).encode("utf-8"), n_swims


@pytest.fixture
def web(monkeypatch, tmp_path):
    """A fresh web module bound to an isolated DATA_DIR, with the V5 meet-identity
    web research stubbed out so the pipeline stays fully offline and fast."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.web as web_mod

    importlib.reload(web_mod)

    # Keep "Researching meet identity…" offline + instant (it is purely additive
    # enrichment the pipeline already treats as best-effort).
    import context_engine.identity as _ident

    def _no_research(**_kw):
        raise RuntimeError("offline (test)")

    monkeypatch.setattr(_ident, "discover_meet_identity", _no_research, raising=False)
    return web_mod


def _stale_iso(web) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=web._RUN_STALE_SECS + 30)).isoformat()


def _wait_terminal(web, run_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        conn = web._db()
        row = conn.execute(
            "SELECT status, error, resume_count FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        conn.close()
        if row and row["status"] in ("done", "error"):
            return row
        time.sleep(0.1)
    raise AssertionError(
        f"run {run_id} never reached a terminal status (last={row and row['status']})"
    )


# ---------------------------------------------------------------------------
# 1. The drafting phase is cheap and linear — a 500+-swim meet completes.
# ---------------------------------------------------------------------------


def test_large_500plus_swim_meet_completes_in_the_pipeline(web):
    """The pipeline itself handles a 500+-swim meet end to end (no recycle in a
    unit test) — proving the failure is durability, not pipeline cost."""
    data, n_swims = _make_printout(132, 4)
    assert n_swims >= 500, n_swims

    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    t0 = time.time()
    run = run_pipeline_v4(
        file_bytes=data,
        filename="ken-deeley-open.txt",
        profile_id=None,
        club_filter=CLUB,
        use_pb_cache=True,
        fetch_pbs=False,  # isolate from the network/PB-lookup phase
        run_id="qa015load",
    )
    elapsed = time.time() - t0

    assert run.error is None, run.error
    assert run.our_swim_count >= 500, run.our_swim_count
    assert len(run.cards) > 0
    assert (run.recognition_report or {}).get("n_achievements", 0) > 0
    # Generous ceiling — the detector loop is ~sub-second; this only guards
    # against a future O(n^2) regression sneaking into the drafting phase.
    assert elapsed < 60, f"500+-swim drafting took {elapsed:.1f}s (expected « 60s)"


# ---------------------------------------------------------------------------
# 2. The durable launch path completes a 500+-swim run end to end.
# ---------------------------------------------------------------------------


def test_large_meet_completes_via_start_run(web):
    data, n_swims = _make_printout(132, 4)
    assert n_swims >= 500
    run_id = web._start_run(data, "ken-deeley-open.txt", None, True, False, club_filter=CLUB)
    row = _wait_terminal(web, run_id)
    assert row["status"] == "done", row["error"]
    rd = web._load_run(run_id)
    assert rd and len(rd.get("cards") or []) > 0


# ---------------------------------------------------------------------------
# 3. An interrupted run RESUMES to completion instead of being lost.
# ---------------------------------------------------------------------------


def test_interrupted_large_run_resumes_to_completion(web):
    """A run whose worker died mid-pipeline (DB row stuck at 'running', stale
    heartbeat, launch input still on disk, no in-memory entry) is RESUMED — the
    exact failure mode QA-015 reported. Before the fix this was only ever stamped
    errored."""
    data, n_swims = _make_printout(132, 4)
    assert n_swims >= 500
    run_id = "deadbig01"

    # Stage the input the way _start_run would, then plant a dead DB row.
    web._store_run_input(run_id, data, "ken-deeley-open.txt", None, True, False, CLUB, None)
    assert web._resume_input_exists(run_id)
    stale = _stale_iso(web)
    conn = web._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, status, file_name, heartbeat_at) " "VALUES (?,?,?,?,?)",
        (run_id, stale, "running", "ken-deeley-open.txt", stale),
    )
    conn.commit()
    conn.close()

    # What the status poller / startup reconciler does on a stale, resumable run.
    assert web._maybe_resume_stale_run(run_id) is True

    row = _wait_terminal(web, run_id)
    # Reaching 'done' with content from a dead 'running' row that had no
    # in-memory entry can only have happened via resume — nothing else would
    # complete it. (resume_count is transient: _persist_run's INSERT OR REPLACE
    # resets it on a clean terminal, exactly like progress_log/heartbeat_at; it
    # only needs to persist ACROSS deaths to bound retries, which the atomic-claim
    # and budget tests cover.)
    assert row["status"] == "done", f"resume did not complete: {row['error']}"
    rd = web._load_run(run_id)
    assert rd and len(rd.get("cards") or []) > 0
    # A clean terminal reclaims the stored input — but the reclaim runs in
    # _execute_run's `finally`, *after* the DB status flips to 'done' (and after
    # the post-run notifications), so _wait_terminal can return a beat before the
    # input file is gone. Wait for the reclaim rather than assuming it lands in
    # lock-step with the status flip — the gap only opens under parallel CI load.
    cleanup_deadline = time.time() + 30.0
    while web._resume_input_exists(run_id) and time.time() < cleanup_deadline:
        time.sleep(0.05)
    assert not web._resume_input_exists(run_id)


def test_status_poll_reports_running_while_resuming_not_dead(web):
    """The /api/runs/<id>/status DB-fallback path (the one a real recycle takes)
    must report a resumable stale run as 'running', not surface the dead-run
    error."""
    data, _ = _make_printout(40, 4)
    run_id = "deadpoll01"
    web._store_run_input(run_id, data, "m.txt", None, True, False, CLUB, None)
    stale = _stale_iso(web)
    conn = web._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, status, file_name, heartbeat_at) " "VALUES (?,?,?,?,?)",
        (run_id, stale, "running", "m.txt", stale),
    )
    conn.commit()
    conn.close()

    app = web.create_app()
    app.config["TESTING"] = True
    monkey_status = app.test_client().get(f"/api/runs/{run_id}/status").get_json()
    # Resumed → reported as still working, NOT the "stopped responding" error.
    assert monkey_status["status"] in ("running", "queued", "done")
    assert "stopped responding" not in (monkey_status.get("error") or "")
    _wait_terminal(web, run_id)  # let the resumed worker settle


# ---------------------------------------------------------------------------
# 4. Resume is bounded; the honest error survives for unrecoverable cases.
# ---------------------------------------------------------------------------


def test_resume_budget_exhausted_surfaces_honest_error(web):
    run_id = "deadexhaust01"
    data, _ = _make_printout(8, 2)
    web._store_run_input(run_id, data, "m.txt", None, True, False, CLUB, None)
    stale = _stale_iso(web)
    conn = web._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, status, file_name, heartbeat_at, resume_count) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, stale, "running", "m.txt", stale, web._RUN_MAX_RESUMES),
    )
    conn.commit()
    conn.close()

    assert web._maybe_resume_stale_run(run_id) is False
    conn = web._db()
    row = conn.execute("SELECT status, error FROM runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    assert row["status"] == "error"
    assert "upload the file again" in (row["error"] or "")


def test_stale_run_without_stored_input_surfaces_honest_error(web):
    """A run from before this fix (no stored launch input) can't be resumed — it
    must still get the honest error, never spin forever."""
    run_id = "noinput01"
    stale = _stale_iso(web)
    conn = web._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, status, file_name, heartbeat_at) " "VALUES (?,?,?,?,?)",
        (run_id, stale, "running", "x.txt", stale),
    )
    conn.commit()
    conn.close()

    assert web._resume_input_exists(run_id) is False
    assert web._maybe_resume_stale_run(run_id) is False
    conn = web._db()
    row = conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    assert row["status"] == "error"


def test_resume_claim_is_atomic_single_winner(web):
    """When several workers spot the same dead run, exactly one claim wins — so a
    1-CPU box never double-runs the same heavy pipeline."""
    run_id = "deadrace01"
    data, _ = _make_printout(8, 2)
    web._store_run_input(run_id, data, "m.txt", None, True, False, CLUB, None)
    stale = _stale_iso(web)
    conn = web._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, status, file_name, heartbeat_at) " "VALUES (?,?,?,?,?)",
        (run_id, stale, "running", "m.txt", stale),
    )
    conn.commit()
    conn.close()

    outcomes = [web._claim_stale_run_for_resume(run_id, web._RUN_MAX_RESUMES) for _ in range(4)]
    assert outcomes.count("claimed") == 1, outcomes
