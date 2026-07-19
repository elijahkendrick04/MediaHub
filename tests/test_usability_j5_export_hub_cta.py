"""J-5 — the /export hub must not misdirect users to the wrong page.

The hub's one instruction told users to "Open a meet's review page to bulk-export
its content pack" — but the bulk-export tool lives at /export/<run_id>, not the
review page. The hub now lists the profile's recent results linking straight into
the export tool (or, when there are none, honestly points at where to start), and
the misdirecting "review page" copy is gone.
"""

from __future__ import annotations

import pytest
from tests._helpers import web_surface_src


@pytest.fixture
def export_html(client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return client.get("/export").get_data(as_text=True)


def test_misdirecting_review_copy_gone(export_html):
    assert "Open a meet's review page to bulk-export" not in export_html


def test_hub_points_at_the_real_export_path(export_html):
    # With no runs yet, the fallback still routes users somewhere real.
    assert "Bulk-export" in export_html
    assert 'href="/"' in export_html or "Start with your results" in export_html


def test_source_lists_recent_runs_via_export_tool():
    import pathlib

    src = web_surface_src()
    # The hub queries the profile's recent done runs and links to export_run_tool_page.
    assert 'url_for("export_run_tool_page", run_id=r["id"])' in src
    assert "WHERE profile_id = ? AND status = 'done'" in src
