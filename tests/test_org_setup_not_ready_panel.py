"""tests/test_org_setup_not_ready_panel.py — the setup page explains the
"not ready" state instead of silently locking the user out (audit finding A-2).

Before the fix, an org that was created but still failed ``is_ready()`` (a
name-only AI submit, or an AI capture that read the links but found no usable
brand signal) left the volunteer on an unchanged form while every nav click
bounced back to setup with no explanation — a hard lockout.

The fix keeps ``is_ready()`` strict (no anonymous/generic content) but renders
an explicit "what's missing / how to finish" panel with a one-click path to
the manual colours whenever a pinned org is not ready.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def gated_env(web_module):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    import mediahub.web.club_profile as cp

    app = web_module.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    return app, cp


def test_not_ready_org_shows_unlock_panel(gated_env):
    """A name-only org (not ready) lands on setup with a clear way forward."""
    app, cp = gated_env
    with app.test_client() as c:
        # Name only, no colours -> profile is created but not ready.
        c.post(
            "/organisation/setup/manual",
            data={"display_name": "Name Only SC"},
            content_type="multipart/form-data",
        )
        prof = next(p for p in cp.list_profiles() if p.display_name == "Name Only SC")
        assert not prof.is_ready(), "test premise: a name-only org is not ready"

        page = c.get("/organisation/setup")
        assert page.status_code == 200
        body = page.data.decode()
        assert "can’t make content yet" in body or "can&rsquo;t make content yet" in page.data.decode(
            "latin-1"
        ), "not-ready org must show the not-ready explanation panel (A-2)"
        assert "Pick your colours now" in body, "panel must offer the manual-finish shortcut"
        assert 'id="mh-setup-not-ready"' in body


def test_ready_org_does_not_show_unlock_panel(gated_env):
    """Once the org has a brand signal, the not-ready panel disappears."""
    app, cp = gated_env
    with app.test_client() as c:
        c.post(
            "/organisation/setup/manual",
            data={
                "display_name": "Ready SC",
                "manual_primary": "#123456",
                "manual_secondary": "#abcdef",
            },
            content_type="multipart/form-data",
        )
        prof = next(p for p in cp.list_profiles() if p.display_name == "Ready SC")
        assert prof.is_ready(), "test premise: an org with colours is ready"

        page = c.get("/organisation/setup")
        assert page.status_code == 200
        assert 'id="mh-setup-not-ready"' not in page.data.decode(), (
            "a ready org should not see the not-ready panel"
        )


def test_links_copy_is_honest_about_needing_a_brand_signal(gated_env):
    """The 'skip the links' copy no longer over-promises 'the AI works fine
    without it' — it states a brand signal is still required."""
    app, _ = gated_env
    with app.test_client() as c:
        page = c.get("/organisation/setup?fresh=1")
        body = page.data.decode()
        assert "works fine\n    without it" not in body
        assert "brand signal to unlock" in body, "links copy must state a signal is required"
