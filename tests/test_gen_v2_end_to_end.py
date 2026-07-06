"""Gen Engine v2 end-to-end — the shared upload→process→review flow under the
PRODUCTION default engine.

``tests/conftest.py`` pins ``MEDIAHUB_GEN_V2=0`` suite-wide so the many
legacy-layout tests stay stable — which means every other end-to-end flow test
exercises the LEGACY engine, while production runs with the var unset (v2 on:
``archetypes.is_enabled()`` is True). This file deletes the var (the exact
opt-in pattern conftest documents) and drives the real upload → configure →
process → review flow through the Flask client, so a v2-only regression in the
shared path fails CI instead of passing silently.

Offline + hermetic, modelled on test_qa015_large_meet_durability: a synthetic
HY-TEK-style printout, meet-identity research stubbed, PB fetch disabled.
"""

from __future__ import annotations

import importlib
import io
import json
import time

import pytest

CLUB = "Test Aquatics"

_SWIMMERS = [
    ("Eira", "Hughes", 14),
    ("Oscar", "Raleigh", 13),
    ("Maya", "Carden", 15),
    ("Leo", "Deeley", 14),
    ("Ava", "Morgan", 13),
    ("Noah", "Patel", 16),
    ("Mia", "Walsh", 14),
    ("Jack", "Frost", 15),
    ("Ella", "Quinn", 13),
    ("Finn", "Sharpe", 14),
    ("Ruby", "Vaughn", 15),
    ("Theo", "Blake", 13),
]
_EVENTS = [(50, "Freestyle"), (100, "Freestyle"), (50, "Backstroke"), (100, "Breaststroke")]


def _time_str(base_cs: int) -> str:
    mm, rest = divmod(base_cs, 6000)
    ss, cc = divmod(rest, 100)
    return f"{mm}:{ss:02d}.{cc:02d}" if mm else f"{ss}.{cc:02d}"


def _make_printout() -> bytes:
    """A small synthetic HY-TEK-style results printout, one club throughout."""
    lines = [
        "Spring Open - HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1",
        "Spring Open Meet 2026 - 14/02/2026 to 15/02/2026",
        "",
    ]
    for ev_idx, (dist, stroke) in enumerate(_EVENTS):
        lines.append(f"Event {ev_idx + 1}  Female 13 Year Olds {dist} LC Meter {stroke}")
        lines.append(
            "Name                    Age  Team                     Seed Time   Finals Time"
        )
        for place, (first, last, age) in enumerate(_SWIMMERS, start=1):
            base = 3000 + dist * 12 + (place * 7) % 400
            lines.append(
                f"{place} {last}, {first}  {age}  {CLUB}   "
                f"{_time_str(base + 80)}     {_time_str(base)}"
            )
        lines.append("")
    return ("\n".join(lines)).encode("utf-8")


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    # The production default: var unset → Gen Engine v2 on. This runs after the
    # conftest autouse pin, exactly as conftest's docstring prescribes.
    monkeypatch.delenv("MEDIAHUB_GEN_V2", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.web as wm

    importlib.reload(wm)

    # Keep "Researching meet identity…" offline + instant (purely additive
    # enrichment the pipeline already treats as best-effort).
    import context_engine.identity as _ident

    def _no_research(**_kw):
        raise RuntimeError("offline (test)")

    monkeypatch.setattr(_ident, "discover_meet_identity", _no_research, raising=False)
    app = wm.create_app()
    app.config["TESTING"] = True
    return wm, app


def _wait_terminal(wm, run_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    row = None
    while time.time() < deadline:
        conn = wm._db()
        row = conn.execute("SELECT status, error FROM runs WHERE id=?", (run_id,)).fetchone()
        conn.close()
        if row and row["status"] in ("done", "error"):
            return row
        time.sleep(0.1)
    raise AssertionError(
        f"run {run_id} never reached a terminal status (last={row and row['status']})"
    )


def test_upload_process_review_under_v2_default(web_env):
    wm, app = web_env
    from mediahub.graphic_renderer import archetypes

    assert archetypes.is_enabled(), "with the var deleted, v2 must be the default engine"

    c = app.test_client()

    # 1. Upload the meet file → staged, redirected to configure.
    r = c.post(
        "/upload",
        data={"file": (io.BytesIO(_make_printout()), "spring-open.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code in (302, 303), r.data[:300]
    temp_id = r.headers["Location"].split("run_id=")[-1]

    # Hermetic: the staged meta defaults fetch_pbs on — turn the network
    # PB lookup off for CI (same isolation qa015 uses via _start_run).
    meta_path = wm.RUNS_DIR / temp_id / "upload_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["fetch_pbs"] = False
    meta_path.write_text(json.dumps(meta))

    # 2. Configure: the parsed club is offered, pick it and start the run.
    r = c.get(f"/upload/configure?run_id={temp_id}")
    assert r.status_code == 200, r.data[:300]
    body = r.get_data(as_text=True)
    assert "club_filter" in body and CLUB in body

    r = c.post(f"/upload/configure?run_id={temp_id}", data={"club_filter": CLUB})
    assert r.status_code in (302, 303), r.data[:300]
    run_id = r.headers["Location"].rstrip("/").split("/")[-1]

    # 3. The real pipeline processes the meet to completion.
    row = _wait_terminal(wm, run_id)
    assert row["status"] == "done", row["error"]
    rd = wm._load_run(run_id)
    assert rd and len(rd.get("cards") or []) > 0
    assert (rd.get("recognition_report") or {}).get("n_achievements", 0) > 0

    # 4. Review renders real card content (not a 200 shell) under v2.
    r = c.get(f"/review/{run_id}")
    assert r.status_code == 200, r.data[:300]
    review = r.get_data(as_text=True)
    assert any(last in review for _first, last, _age in _SWIMMERS), (
        "review page rendered no swimmer from the meet"
    )
