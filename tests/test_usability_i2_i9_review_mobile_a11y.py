"""I-2 & I-9 — review-page mobile overflow and pipeline-stage screen-reader
announcements.

I-2: at 375px the review page overflowed sideways — long tokenised parse-note
strings and bare wide diagnostics tables. Tokens now wrap and the diagnostics
tables scroll inside their own box.

I-9: the pipeline stage line (including the terminal "ready to review" /
"Something went wrong") was updated by JS but sat in a div with no aria-live, so
screen-reader users heard nothing. It's now role=status aria-live=polite.
"""

from __future__ import annotations

import importlib
import json

import pytest

ORG = "club-a"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": ORG})
    return {"client": c, "wm": wm, "tmp": tmp_path}


def _seed_run(env, run_id, status):
    payload = {
        "run_id": run_id,
        "profile_id": ORG,
        "meet": {"name": "Spring Open"},
        "recognition_report": {"ranked_achievements": []},
        "cards": [],
    }
    (env["tmp"] / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), ?, ?, ?, ?)",
        (run_id, status, ORG, "Spring Open", "s.hy3"),
    )
    conn.commit()
    conn.close()


def test_i9_progress_stage_is_aria_live(env):
    _seed_run(env, "runprog0001", "running")
    html = env["client"].get("/runs/runprog0001").get_data(as_text=True)
    # The stage container announces to screen readers.
    assert 'class="strap live" role="status" aria-live="polite"' in html
    assert 'id="mh-current-stage"' in html


def test_i2_review_tables_scroll_and_tokens_wrap(env):
    _seed_run(env, "runrev00001", "done")
    html = env["client"].get("/review/runrev00001").get_data(as_text=True)
    # Diagnostics tables are wrapped in a scroll container.
    assert "mh-table-scroll" in html
    # The CSS carries the token-wrap + table-scroll rules (BASE_CSS inlines
    # theme-components.css).
    assert "overflow-wrap: anywhere" in html
    assert ".mh-table-scroll" in html


def test_i2_review_page_tables_each_wrapped(env):
    _seed_run(env, "runrev00002", "done")
    html = env["client"].get("/review/runrev00002").get_data(as_text=True)
    # Every bare diagnostics <table> got a scroll wrapper (Card/Not-generated/
    # Sources); none is left unwrapped in the diagnostics region.
    assert html.count("mh-table-scroll") >= 3
