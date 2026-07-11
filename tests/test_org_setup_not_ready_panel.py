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

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
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
