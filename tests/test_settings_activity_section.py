"""tests/test_settings_activity_section.py — the Settings > Activity page.

G-2 (usability audit) consolidated the four run-history mirrors: the Settings
"Activity" section no longer re-renders its own copy of the results table
("Mirrors /activity") — it is a pointer card into the canonical ``/activity``
page, which carries everything the mirror had (achievements-first counts,
per-row delete with descriptive labels, failure explainers, search/filters,
bulk clear) plus the Table · Feed · Season views.

The mirror-table behaviours this file previously locked (achievements column,
tenant isolation, XSS escaping, delete affordances, failure callouts, the
100-run cap disclosure, db-failure honesty) are the canonical page's job now —
see tests/test_activity_scoping.py and
tests/test_usability_g2_history_consolidation.py.

These tests lock the replacement surface:
  * With an org pinned, the section renders a link card to ``/activity``
    (no run table — no second data path to drift out of sync again).
  * With no org pinned, the section degrades gracefully (Settings is
    reachable pre-org-setup) and offers the org picker.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def activity_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced; one org profile."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="club-a", display_name="Club A", brand_voice_summary="A friendly club."
        )
    )

    with app.test_client() as c:
        yield c, wm


def _pin(client, profile_id="club-a"):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


class TestLinkCard:
    def test_section_links_to_canonical_activity(self, activity_client):
        c, _ = activity_client
        _pin(c)
        resp = c.get("/settings/activity")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'href="/activity"' in html
        assert "Open Activity" in html

    def test_section_names_the_org(self, activity_client):
        c, _ = activity_client
        _pin(c)
        html = c.get("/settings/activity").get_data(as_text=True)
        assert "Club A" in html

    def test_no_mirror_table_rendered(self, activity_client):
        """The section must not re-render its own runs table — that second
        data path drifting out of sync is exactly what G-2 removed."""
        c, _ = activity_client
        _pin(c)
        html = c.get("/settings/activity").get_data(as_text=True)
        assert "/privacy/run/" not in html
        assert 'data-label="Matched"' not in html
        assert 'data-label="Achievements"' not in html


class TestNoOrgState:
    def test_degrades_gracefully_without_an_org(self, activity_client):
        c, _ = activity_client
        resp = c.get("/settings/activity")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "No organisation pinned" in html
        assert "Choose organisation" in html
