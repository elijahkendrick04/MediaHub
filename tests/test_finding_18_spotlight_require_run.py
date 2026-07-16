"""tests/test_finding_18_spotlight_require_run.py

Deep-review finding #18 — "Run-load + tenant guard copy-pasted across handlers".

The ``@require_run`` decorator is the single source of truth for the run-load +
tenant-isolation guard. This locks the migration of the last cleanly-migratable
decorated view, ``spotlight_view``, off its hand-rolled inline
``_load_run`` / ``_can_access_run`` copy and onto ``@require_run`` — so the
security-critical check can no longer drift out of sync with the canonical one.

Two locks:

  * structural — the handler body no longer carries its own load/tenant copy and
    the run arrives via the decorator-injected ``run_data`` kwarg;
  * behavioural — a foreign tenant still gets the honest "Run not found"
    recovery instead of another org's spotlight.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    for env in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="acme", display_name="ACME Aquatics"))
    save_profile(ClubProfile(profile_id="rival", display_name="Rival Swim"))

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _persist_run(runs_dir, run_id, swim_id, sid, sname, *, owner):
    ach = {
        "achievement": {
            "swim_id": swim_id,
            "swimmer_id": sid,
            "swimmer_name": sname,
            "event": "100m Freestyle (LC)",
            "time": "1:00.00",
            "place": 1,
            "type": "medal_gold",
            "pb": True,
        },
        "priority": 9.0,
        "quality_band": "elite",
    }
    doc = {
        "run_id": run_id,
        "profile_id": owner,
        "meet": {"name": "Test Meet"},
        "recognition_report": {"meet_name": "Test Meet", "ranked_achievements": [ach]},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(doc))


def _client(app, pid):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c


def test_spotlight_view_guard_lives_in_require_run(app_ctx):
    """The tenant gate is centralised in @require_run — the handler body must
    not carry its own load/access copy (that copy is what finding #18 is about).
    """
    app, _wm, _tmp = app_ctx
    view = app.view_functions["spotlight_view"]

    # @require_run wraps the view with functools.wraps, which sets __wrapped__.
    # Before the migration the raw view was registered directly (no wrapper),
    # so this attribute is the discriminator between old and new.
    assert hasattr(view, "__wrapped__"), "spotlight_view must be guarded by @require_run"

    underlying = view.__wrapped__
    src = inspect.getsource(underlying)
    assert "_can_access_run" not in src, "inline tenant check must be gone (use @require_run)"
    assert "_load_run(" not in src, "inline run load must be gone (use @require_run)"

    # The decorator injects the loaded run as the run_data kwarg.
    assert "run_data" in inspect.signature(underlying).parameters


def test_spotlight_view_denies_foreign_tenant(app_ctx):
    """A run owned by ACME must answer 'Run not found' to a Rival session."""
    app, _wm, tmp = app_ctx
    runs_dir = tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _persist_run(runs_dir, "rAcme", "rAcme:swim1", "swimmerX", "Sam Stroke", owner="acme")

    foreign = _client(app, "rival")
    resp = foreign.get("/spotlight/rAcme/swimmerX")
    body = resp.get_data(as_text=True)

    assert "Run not found" in body
    assert "Sam Stroke" not in body


def test_spotlight_view_serves_owner(app_ctx):
    """The owning tenant still reaches the spotlight (not a false 'Run not found')."""
    app, _wm, tmp = app_ctx
    runs_dir = tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    _persist_run(runs_dir, "rAcme", "rAcme:swim1", "swimmerX", "Sam Stroke", owner="acme")

    owner = _client(app, "acme")
    resp = owner.get("/spotlight/rAcme/swimmerX")
    body = resp.get_data(as_text=True)

    # The owner is not bounced to the tenant-denial recovery page.
    assert "This run isn't on disk" not in body
