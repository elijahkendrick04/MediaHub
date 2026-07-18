"""Contract guard for the shared conftest fixtures (deep-review #130).

These tests pin the isolation guarantees every other test relies on, so a future
change to ``_isolate_data_dir`` / ``_reset_web_module_state`` that quietly breaks
per-test tenant isolation fails here first. Every assertion is order-independent
(safe under ``pytest-xdist`` / ``pytest-randomly``): each checks an invariant that
must hold at the *start* of any test, regardless of what ran before.
"""

from __future__ import annotations

import json


def test_data_dir_is_isolated_per_test(web_module, tmp_path):
    """The shared web module is pointed at *this* test's tmp_path, and the derived
    storage dirs live under it — never a previous test's directory."""
    wm = web_module
    assert wm.DATA_DIR == tmp_path
    assert wm.RUNS_DIR == tmp_path / "runs_v4"
    assert wm.UPLOADS_DIR == tmp_path / "uploads_v4"
    assert wm.DB_PATH == tmp_path / "data.db"


def test_db_starts_empty_with_schema(web_module):
    """Each test gets a freshly-initialised, empty DB: the schema exists (no
    "no such table") but carries no rows leaked from another test."""
    wm = web_module
    conn = wm._db()
    try:
        # schema present
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM card_reactions").fetchone()[0] == 0
    finally:
        conn.close()


def test_runs_dir_and_profiles_start_empty(web_module):
    """No run JSON or club profile leaks in from a previous test."""
    wm = web_module
    from mediahub.web.club_profile import list_profiles

    assert list(wm.RUNS_DIR.glob("*.json")) == []
    assert list_profiles() == []


def test_writes_are_confined_to_this_test(web_module):
    """A write in one test lands under its own DATA_DIR and is visible to itself
    (the flip side — invisibility to the *next* test — is covered by the
    empty-at-start guards above, which hold for every test)."""
    wm = web_module
    conn = wm._db()
    try:
        conn.execute(
            "INSERT INTO runs (id, created_at, status) VALUES (?, datetime('now'), 'done')",
            ("fixture-guard-run",),
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    finally:
        conn.close()
    (wm.RUNS_DIR / "fixture-guard-run.json").write_text(json.dumps({"run_id": "x"}))
    assert (wm.RUNS_DIR / "fixture-guard-run.json").exists()


def test_client_fixture_serves_the_isolated_app(client, web_module, tmp_path):
    """The canonical ``client`` fixture yields a working test client wired to the
    isolated app/data dir."""
    assert web_module.DATA_DIR == tmp_path
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)  # reachable either way; not a 404/500
