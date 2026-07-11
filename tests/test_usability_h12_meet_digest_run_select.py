"""H-12 — the Meet digest newsletter lets the user pick WHICH meet.

Before: the digest's generate call posted only {format, range, with_ai}; the
server derived a date window and swept up every run inside it, so there was
no way to say "this newsletter is about Saturday's gala" when two meets fell
in the same period.

Now: the Meet digest tile carries a meet <select> (same recent-meets query
the Documents "Meet programme" tile uses; default option keeps the old
latest-in-range behaviour). The chosen ``run_id`` rides the generate POST;
the server tenant-gates it via ``_can_access_run`` and pins the newsletter's
facts to exactly that run (``gather_facts(run_id=...)``), with the period
label following the pinned meet's own date.
"""

from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path

import pytest

_WEB_SRC = (
    Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"
).read_text(encoding="utf-8")


# ---- engine: gather_facts run pinning -------------------------------------


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    return tmp_path


def _make_run(tmp_path, run_id, profile_id, meet_date, swimmer, swim_id):
    rd = tmp_path / "runs_v4"
    rd.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": f"Meet {run_id}", "date": meet_date},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": swim_id,
                        "swimmer_name": swimmer,
                        "event": "100 Free",
                        "time": "1:02.34",
                        "type": "pb_confirmed",
                        "confidence": 0.92,
                    },
                    "priority": 0.9,
                    "rank": 1,
                }
            ]
        },
        "cards": [],
    }
    (rd / f"{run_id}.json").write_text(json.dumps(data))
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(rd).set_status(run_id, swim_id, CardStatus.APPROVED)
    return rd


class TestGatherFactsRunPinning:
    def test_pinned_run_only_includes_that_meet(self, data_dir):
        from mediahub.email_design.grounding import gather_facts

        rd = _make_run(data_dir, "run1", "club-a", "2026-06-12", "Maya", "s1")
        _make_run(data_dir, "run2", "club-a", "2026-06-20", "Tom", "s2")
        facts = gather_facts(
            "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30),
            runs_dir=rd, run_id="run2",
        )
        titles = " ".join(r["title"] for r in facts.recaps)
        assert "Tom" in titles and "Maya" not in titles

    def test_pinned_run_wins_even_outside_the_range(self, data_dir):
        from mediahub.email_design.grounding import gather_facts

        rd = _make_run(data_dir, "r_may", "club-a", "2026-05-20", "Maya", "s1")
        facts = gather_facts(
            "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30),
            runs_dir=rd, run_id="r_may",
        )
        assert len(facts.recaps) == 1
        # The period follows the pinned meet's own date, not the range picker.
        assert facts.date_start == "2026-05-20"
        assert facts.date_end == "2026-05-20"

    def test_pinned_foreign_run_yields_nothing(self, data_dir):
        from mediahub.email_design.grounding import gather_facts

        rd = _make_run(data_dir, "run1", "club-b", "2026-06-12", "Maya", "s1")
        facts = gather_facts(
            "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30),
            runs_dir=rd, run_id="run1",
        )
        assert facts.recaps == []

    def test_no_run_id_keeps_window_behaviour(self, data_dir):
        from mediahub.email_design.grounding import gather_facts

        rd = _make_run(data_dir, "run1", "club-a", "2026-06-12", "Maya", "s1")
        _make_run(data_dir, "run2", "club-a", "2026-06-20", "Tom", "s2")
        facts = gather_facts(
            "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd,
        )
        titles = " ".join(r["title"] for r in facts.recaps)
        assert "Tom" in titles and "Maya" in titles


# ---- web surface -----------------------------------------------------------


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    if not wm._email_design_ok:
        pytest.skip("email_design not available")
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_db_run(wm, run_id, profile_id, meet_name):
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, error) "
        "VALUES (?, datetime('now'), datetime('now'), 'done', ?, ?, ?, 1, 1, 0, NULL)",
        (run_id, profile_id, meet_name, f"{meet_name}.pdf"),
    )
    conn.commit()
    conn.close()


class TestNewslettersPage:
    def test_digest_tile_has_meet_select(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        _seed_db_run(wm, "run-x1", "club-a", "Spring Gala")
        body = c.get("/newsletters").get_data(as_text=True)
        assert 'id="nl-digest-run"' in body
        assert "Latest meet in range" in body  # default keeps old behaviour
        assert "Spring Gala" in body  # completed meets listed by name
        # The JS reads the select and posts run_id with the generate call.
        assert "nl-digest-run" in _WEB_SRC
        assert "payload.run_id=runId" in _WEB_SRC

    def test_foreign_meets_not_listed(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        _seed_db_run(wm, "run-b1", "club-b", "Rival Champs")
        body = c.get("/newsletters").get_data(as_text=True)
        assert "Rival Champs" not in body


class TestGenerateWithRunId:
    def _seed_disk_run(self, tmp, run_id, profile_id, swimmer, swim_id):
        return _make_run(tmp, run_id, profile_id, date.today().isoformat(), swimmer, swim_id)

    def test_digest_pins_the_chosen_meet(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        self._seed_disk_run(tmp, "run1", "club-a", "Maya", "s1")
        self._seed_disk_run(tmp, "run2", "club-a", "Tom", "s2")
        r = c.post(
            "/api/newsletters/generate",
            json={"format": "meet_digest", "range": "this_month",
                  "with_ai": False, "run_id": "run2"},
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        j = r.get_json()
        assert j["ok"] is True
        page = c.get(j["url"]).get_data(as_text=True)
        assert "Tom" in page and "Maya" not in page

    def test_foreign_run_id_is_404_like_missing(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        self._seed_disk_run(tmp, "run-b", "club-b", "Maya", "s1")
        r = c.post(
            "/api/newsletters/generate",
            json={"format": "meet_digest", "range": "this_month",
                  "with_ai": False, "run_id": "run-b"},
        )
        assert r.status_code == 404
        assert r.get_json()["error"] == "run_not_found"

    def test_no_run_id_keeps_range_behaviour(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        self._seed_disk_run(tmp, "run1", "club-a", "Maya", "s1")
        self._seed_disk_run(tmp, "run2", "club-a", "Tom", "s2")
        r = c.post(
            "/api/newsletters/generate",
            json={"format": "meet_digest", "range": "this_month", "with_ai": False},
        )
        assert r.status_code == 200
        j = r.get_json()
        assert j["ok"] is True
        page = c.get(j["url"]).get_data(as_text=True)
        assert "Tom" in page and "Maya" in page

    def test_run_id_ignored_for_other_formats(self, app_env):
        app, wm, tmp = app_env
        c = app.test_client()
        _login(c)
        self._seed_disk_run(tmp, "run1", "club-a", "Maya", "s1")
        # A bogus run_id on a non-digest format is ignored, never a 404.
        r = c.post(
            "/api/newsletters/generate",
            json={"format": "monthly_roundup", "range": "this_month",
                  "with_ai": False, "run_id": "does-not-exist"},
        )
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
