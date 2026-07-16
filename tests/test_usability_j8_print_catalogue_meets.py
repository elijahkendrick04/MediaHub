"""J-8 — the /print catalogue was a dead end; two adjacent "Print" buttons.

/print listed product chips and engine status but linked to no
/print/<run_id> tool — its own copy told the user to "open a meet's print
tool" with no way to do so. And on the Content builder, "Print & merch…"
(the real tool) sat beside "Print / Export PDF" (window.print()), two
buttons that read like the same thing.

Now /print lists the active organisation's recent processed meets, each
linking straight to its print tool (owner vocabulary: "meet"/"results",
never "run"), with an honest empty state when nothing has been processed;
and the window.print() button is renamed "Print this page" so the pair
read differently.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import pytest


@pytest.fixture
def env(client, web_module, tmp_path):
    wm = web_module

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-j8-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Spring Open 2026"},
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
        " file_name) VALUES (?, '2026-05-02 10:00:00', 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open 2026", "spring.hy3"),
    )
    # A foreign org's meet — must never appear in org-alpha's /print list.
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, '2026-05-03 10:00:00', 'done', ?, ?, ?)",
        ("run-j8-foreign", "org-beta", "Rival Gala 2026", "rival.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(tmp_path / "runs_v4").set_status(run_id, "swim-1", CardStatus.APPROVED)

    r = client.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code == 200
    yield {"client": client, "run_id": run_id, "wm": wm}


def test_print_catalogue_lists_recent_meets_with_tool_links(env):
    r = env["client"].get("/print")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "Print from a meet" in page
    assert "Spring Open 2026" in page
    assert f'href="/print/{env["run_id"]}"' in page
    assert "processed 2026-05-02" in page
    # The instruction copy now points at the list on this page, not at an
    # unreachable tool.
    assert "Pick a meet below to proof and" in page


def test_print_catalogue_is_tenant_scoped(env):
    r = env["client"].get("/print")
    page = r.get_data(as_text=True)
    assert "Rival Gala 2026" not in page
    assert "run-j8-foreign" not in page


def test_print_catalogue_empty_state_is_honest(env):
    wm = env["wm"]
    conn = wm._db()
    conn.execute("DELETE FROM runs")
    conn.commit()
    conn.close()
    r = env["client"].get("/print")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "No results to print from yet" in page
    assert "Upload results" in page


def test_pack_page_print_buttons_read_differently(env):
    r = env["client"].get(f"/pack/{env['run_id']}")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "Print this page" in page
    assert "Print / Export PDF" not in page
    # The real print tool sits beside it, clearly a different thing.
    assert "Print &amp; merch" in page


# ---------------------------------------------------------------------------
# Source-level
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_owner_vocabulary_not_run():
    # The meets list speaks "meet"/"results", never "run".
    assert "Print from a meet" in _SRC
    assert "No results to print from yet" in _SRC


def test_old_button_label_gone_everywhere():
    assert "Print / Export PDF" not in _SRC
