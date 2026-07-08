"""tests/test_org_setup_manual_gate_exempt.py — the manual + palette setup
POSTs bypass the org-ready gate (audit finding A-1).

Regression for the "Manual build silently discards the whole form" breakage:
``organisation_setup_manual`` (a multipart browser form POST) was missing from
``_SETUP_EXEMPT_ENDPOINTS``, so under the enforced org-setup gate a brand-new
volunteer's submit was 302'd back to /organisation/setup *before the handler
ran* — the org was never created and every field they typed vanished with no
error.

The fix exempts ``organisation_setup_manual`` /
``organisation_setup_palette`` / ``organisation_setup_palette_reorder`` from
the READY gate (each keeps its own display_name / active-profile / attestation
guards) and, as defence-in-depth, makes the gate stash a one-shot "not saved"
notice whenever it cancels a browser POST so the discard can never be silent.
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
    """App with ENFORCE_ORG_GATE=True and no active org in a clean tmp dir."""
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


def test_manual_setup_not_gated_creates_ready_org(gated_env):
    """A fresh session can complete manual setup end-to-end under the gate.

    The distinguishing signal is not the status code (the handler *also*
    302's back to /organisation/setup on success) but whether the org was
    actually created: a gate-cancel creates nothing.
    """
    app, cp = gated_env
    with app.test_client() as c:
        r = c.post(
            "/organisation/setup/manual",
            data={
                "display_name": "Otter Swimming Club",
                "org_type": "swimming_club",
                "caption_tone": "warm-club",
                "platforms": ["instagram"],
                "manual_primary": "#1E88E5",
                "manual_secondary": "#FFB300",
                "manual_accent": "#43A047",
            },
            content_type="multipart/form-data",
        )
        # Handler ran and redirected (to the setup preview), NOT a gate-cancel
        # that lost the body.
        assert r.status_code in (301, 302), r.status_code

        profiles = cp.list_profiles()
        assert profiles, (
            "manual setup created no profile — the gate cancelled the POST "
            "before the handler ran (finding A-1 regression)"
        )
        prof = next(
            (p for p in profiles if p.display_name == "Otter Swimming Club"),
            None,
        )
        assert prof is not None, [p.display_name for p in profiles]
        assert prof.is_ready(), "org created by manual setup should be usable immediately"
        assert prof.brand_palette_manual.get("primary") == "#1E88E5"

        with c.session_transaction() as sess:
            assert sess.get("active_profile_id") == prof.profile_id, (
                "manual setup should pin the new org as active"
            )


def test_content_route_still_gated(gated_env):
    """Control: a content-production route is still 302'd by the gate."""
    app, _ = gated_env
    with app.test_client() as c:
        r = c.get("/make")
        assert r.status_code in (301, 302), r.status_code


def test_gate_cancelled_post_is_not_silent(gated_env):
    """A non-exempt browser POST cancelled by the gate leaves a visible notice.

    Defence-in-depth: even for POSTs that are *meant* to be gated (e.g. a
    content POST attempted before setup finished, or after a session expiry),
    the setup page must tell the user their submit was not saved.
    """
    app, _ = gated_env
    with app.test_client() as c:
        # A non-exempt content POST with no active/ready org — the gate
        # intercepts before the handler and redirects to setup.
        posted = c.post("/upload", data={}, follow_redirects=False)
        assert posted.status_code in (301, 302), posted.status_code
        # The setup page now surfaces the one-shot "not saved" notice.
        page = c.get("/organisation/setup")
        assert page.status_code == 200, page.status_code
        assert b"Not saved" in page.data, "gate cancelled a POST silently (no notice)"
        # One-shot: a second load does not repeat it.
        again = c.get("/organisation/setup")
        assert b"Not saved" not in again.data, "gate notice should show only once"
