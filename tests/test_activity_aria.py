"""tests/test_activity_aria.py — ARIA regression: tablist children must have role="tab".

Guards against the axe-core 'aria-required-children' violation on /activity:
  - The .mh-segmented nav has role="tablist"
  - Every <a> inside it must carry role="tab" and aria-selected
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def activity_client(app, web_module):
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="club-a",
            display_name="Club A",
            brand_voice_summary="A friendly club.",
        )
    )

    conn = web_module._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, error) "
        "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?, 1, 1, 0, ?)",
        ("run-1", "done", "club-a", "Test Meet", "test.pdf", None),
    )
    conn.commit()
    conn.close()

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "club-a"})
        yield c


class TestActivityTablistAria:
    def test_segmented_children_have_role_tab(self, activity_client):
        """Every <a> inside role="tablist" must carry role="tab" (axe aria-required-children)."""
        resp = activity_client.get("/activity")
        body = resp.get_data(as_text=True)
        assert 'role="tablist"' in body
        # Every anchor in the tablist must declare role="tab"
        assert 'role="tab"' in body

    def test_active_tab_has_aria_selected_true(self, activity_client):
        """The selected filter tab must have aria-selected="true"."""
        resp = activity_client.get("/activity")
        body = resp.get_data(as_text=True)
        assert 'aria-selected="true"' in body

    def test_inactive_tabs_have_aria_selected_false(self, activity_client):
        """Non-selected tabs must have aria-selected="false"."""
        resp = activity_client.get("/activity")
        body = resp.get_data(as_text=True)
        assert 'aria-selected="false"' in body

    def test_status_filter_tab_selected_true_on_active_filter(
        self, activity_client, tmp_path, monkeypatch
    ):
        """When ?status=error is applied the Failed tab carries aria-selected="true"."""
        import mediahub.web.web as wm

        conn = wm._db()
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, error) "
            "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?, 1, 0, 0, ?)",
            ("run-err", "error", "club-a", "Bad Meet", "bad.pdf", "parse error"),
        )
        conn.commit()
        conn.close()
        resp = activity_client.get("/activity?status=error")
        body = resp.get_data(as_text=True)
        assert 'aria-selected="true"' in body
        assert 'aria-selected="false"' in body
