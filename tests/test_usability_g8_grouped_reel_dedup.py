"""G-8 — the grouped page carried a third, drifted copy of the reel generator.

`generateReelGrouped` had no composer, claimed a "15-second" reel (the actual
default 3-card reel is ≈16.5s), and its `dims` lookup omitted "portrait" so
that cut rendered an empty size caption. The drifted copy is deleted; the
grouped page's meet-reel card now links straight to the shared reel composer
on the Content builder (`#mh-reel-composer`), which owns picks, rhythm,
formats and the correct data-driven duration readout.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import pytest


@pytest.fixture
def env(tmp_path, web_module, client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    wm = web_module

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-g8-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Spring Open"},
                "cards": [],
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "rank": 1,
                            "quality_band": "elite",
                            "priority": 0.9,
                            "safe_to_post": {"level": "safe", "reason": "ok"},
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Maya Patel",
                                "event": "100m Freestyle",
                                "headline": "New PB",
                                "type": "pb",
                                "raw_facts": {"time": "59.99"},
                            },
                        }
                    ],
                    "n_achievements": 1,
                },
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code == 200
    yield {"client": client, "run_id": run_id, "wm": wm}


def test_grouped_page_links_to_shared_composer(env):
    c = env["client"]
    r = c.get(f"/pack/{env['run_id']}/grouped")
    assert r.status_code == 200
    page = r.data.decode("utf-8")
    if "All recommendations" not in page:
        pytest.skip("v7.3 grouped pack unavailable in this environment")
    # The drifted generator and its private panel are gone…
    assert "generateReelGrouped" not in page
    assert "reel-panel-grouped" not in page
    # …replaced by a link to the shared composer section on the builder.
    assert f"/pack/{env['run_id']}#mh-reel-composer" in page
    assert "Open the reel composer" in page
    # The wrong duration claim is gone (the reel's length is data-driven).
    assert "15-second" not in page


def test_composer_anchor_exists_on_builder_source():
    # The link target is the composer card's real id on the Content builder.
    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert 'id="mh-reel-composer"' in src


_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_no_drifted_reel_generator_left_in_source():
    assert "generateReelGrouped" not in _SRC
    assert "reel-panel-grouped" not in _SRC
    assert "Generate reel from this meet" not in _SRC
    # Exactly one reel generator (plus its batch variant) remains, and only
    # the shared _MOTION_FMT_DIMS carries the size captions — the drifted
    # dims table that omitted "portrait" is gone.
    assert _SRC.count("function generateReel(") == 1
    assert _SRC.count("function generateReelBatch(") == 1
    assert "var dims = {{story:" not in _SRC
