"""G-3 — /organisation/setup is the canonical brand home.

Brand was edited on three overlapping pages; the setup page permanently branded
itself "First-run setup" even for long-standing clubs, and many in-app links
pointed at the legacy /organisation editor. Now: the brand-editing entry points
point at /organisation/setup, the setup hero is contextual (not "First-run
setup" once a brand exists), and the legacy /organisation page carries a banner
naming setup as the main editor.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def make_client(web_module, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    def _make(*, ready: bool):
        from mediahub.web.club_profile import ClubProfile, save_profile

        prof = ClubProfile(profile_id="club-a", display_name="Riverside SC")
        if ready:
            prof.brand_keywords = ["fast", "friendly"]  # a brand signal → is_ready()
        save_profile(prof)
        app = web_module.create_app()
        app.config["TESTING"] = True
        c = app.test_client()
        with c.session_transaction() as s:
            s["active_profile_id"] = "club-a"
        return c

    return _make


def test_setup_hero_is_first_run_for_new_org(make_client):
    c = make_client(ready=False)
    html = c.get("/organisation/setup").get_data(as_text=True)
    assert "First-run setup" in html


def test_setup_hero_is_contextual_for_returning_org(make_client):
    c = make_client(ready=True)
    html = c.get("/organisation/setup").get_data(as_text=True)
    # A club that already has a brand doesn't see the permanent first-run framing.
    assert "First-run setup" not in html
    assert "Organisation &amp; brand" in html


def test_legacy_org_page_points_to_setup(make_client):
    c = make_client(ready=True)
    html = c.get("/organisation").get_data(as_text=True)
    assert "This is the classic editor" in html
    assert "/organisation/setup" in html
    assert "Organisation &amp; brand setup" in html


def test_entry_points_link_to_setup_not_legacy(make_client):
    c = make_client(ready=True)
    home = c.get("/").get_data(as_text=True)
    import re

    # The signed-in home's "Edit profile" secondary CTA must specifically point
    # at the canonical setup route — assert the actual anchor, not just that the
    # substring appears somewhere on the page.
    m = re.search(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>\s*Edit profile\s*</a>', home)
    assert m is not None, "no 'Edit profile' CTA found on the signed-in home"
    assert m.group(1).endswith(
        "/organisation/setup"
    ), f"Edit-profile CTA points at {m.group(1)!r}, not the canonical setup page"
    # And it does NOT point at the demoted legacy /organisation editor.
    assert not m.group(1).endswith("/organisation")
