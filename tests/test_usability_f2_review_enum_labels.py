"""F-2 — the review surface must not leak raw engine enums or an engine-y tab
title.

The band and post-type filters rendered internal values verbatim ("not_worthy",
"medal_gold", "main_feed") with underscores, where every other part of the page
is humanised, and the browser tab read "Recognition". The filters now show
display labels (the <option value> keeps the raw enum for the JS filter) and the
tab is titled by the meet.
"""

from __future__ import annotations

import importlib
import json

import pytest

ORG = "c"


@pytest.fixture
def review_html(tmp_path, monkeypatch):
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

    save_profile(ClubProfile(profile_id=ORG, display_name="Club"))
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    payload = {
        "run_id": "r1",
        "profile_id": ORG,
        "meet": {"name": "Spring Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Ada",
                        "event": "100 Free",
                        "type": "medal_gold",
                        "headline": "Gold!",
                    },
                    "quality_band": "not_worthy",
                    "suggested_post_type": "main_feed",
                }
            ]
        },
    }
    (tmp_path / "runs_v4" / "r1.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id,created_at,status,profile_id,meet_name,file_name) "
        "VALUES ('r1',datetime('now'),'done',?,'Spring Gala','s.hy3')",
        (ORG,),
    )
    conn.commit()
    conn.close()
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c.get("/review/r1").get_data(as_text=True)


def test_filter_options_show_display_labels(review_html):
    assert "Below the bar" in review_html  # not "not_worthy"
    assert "Gold medal" in review_html  # not "medal_gold"
    assert "Feed post" in review_html  # not "main_feed"


def test_raw_enum_kept_as_option_value_for_js(review_html):
    # The JS filter still matches on the raw enum, so it stays as the value.
    assert 'value="not_worthy"' in review_html
    assert 'value="medal_gold"' in review_html
    assert 'value="main_feed"' in review_html


def test_tab_titled_by_meet_not_recognition(review_html):
    assert "<title>Review — Spring Gala" in review_html
    assert "<title>Recognition" not in review_html
