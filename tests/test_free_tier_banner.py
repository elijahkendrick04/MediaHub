"""Free-tier banner (soft limit, sub_33-1 regression).

The "last free run" nudge must actually be reachable: quiet below cap-1,
nudge at exactly cap-1, over-state at >= cap — and the copy interpolates
FREE_TIER_RUNS_PER_MONTH rather than hardcoding "3".
"""
from __future__ import annotations

import pytest


@pytest.fixture
def world(web_module):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, web_module


def _seed_runs(wm, n: int) -> None:
    conn = wm._db()
    for i in range(n):
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
            "VALUES (?, datetime('now'), 'done', NULL, 'Meet', 'f.hy3')",
            (f"run-ft-{i}",),
        )
    conn.commit()
    conn.close()


def _banner(app) -> str:
    # Anonymous visitors count as Free-plan; render inside a request context.
    with app.test_request_context("/"):
        return app._free_tier_banner_html()


def test_banner_states_walk_the_cap(world):
    app, wm = world
    from mediahub.web import auth as _auth

    cap = _auth.FREE_TIER_RUNS_PER_MONTH
    assert cap >= 2, "test assumes a cap of at least 2"

    # Well under the cap: silent.
    _seed_runs(wm, cap - 2)
    assert _banner(app) == ""

    # Exactly cap-1: the last-free-run nudge (previously unreachable).
    _seed_runs(wm, cap - 1)
    nudge = _banner(app)
    assert "last of your" in nudge
    assert str(cap) in nudge
    assert "used all" not in nudge

    # At the cap: the over state, still a soft limit (link to pricing).
    _seed_runs(wm, cap)
    over = _banner(app)
    assert "used all" in over
    assert str(cap) in over
    assert "/pricing" in over


def test_banner_copy_interpolates_cap_constant(world, monkeypatch):
    """No hardcoded '3': a different cap value flows into the copy."""
    app, wm = world
    from mediahub.web import auth as _auth

    monkeypatch.setattr(_auth, "FREE_TIER_RUNS_PER_MONTH", 5)
    _seed_runs(wm, 4)  # cap-1 under the patched cap
    nudge = _banner(app)
    assert "last of your 5 free runs" in nudge
