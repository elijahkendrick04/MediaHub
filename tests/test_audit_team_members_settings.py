"""Audit regression locks — the "Team members" settings feature.

Covers the defects found auditing GET,POST /organisation/members end to end:

  * F1 (P2) — the global submit loader stuck on screen after a user *cancelled*
    an inline ``onsubmit="return confirm(...)"`` (e.g. dismissing the member
    "Remove" confirm). The shared ``bindForms`` submit handler now bails when an
    earlier handler already prevented the submit. Locked at the source-JS level
    (the pytest suite has no browser), mirroring test_usability_d27_planner_loaders.
  * F2 (P2) — the add-member form labels were not programmatically associated
    with their inputs and the email field had no ``autocomplete``.
  * F3 (P3) — the members table headers carried no ``scope``.
  * F4 (P3) — the route stored an un-activatable invite for an address with no
    TLD (e.g. ``coach@club``): the store only checks for an ``@`` while signup
    uses the stricter ``_looks_like_email``. The route now validates up front.

The membership store itself (tenancy.py) and the wider PC.3 binding invariant are
pinned by test_tenancy.py and test_workspace_membership_invariant.py; this file is
scoped to the members-page fixes only.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PASSWORD = "twelve-chars-long"
OWNER = "owner@club-a.org"


@pytest.fixture
def members_world(tmp_path, monkeypatch):
    """A bound single-owner workspace, signed in and pinned as the owner."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.auth import UserStore
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web import tenancy as t

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    UserStore().create(OWNER, PASSWORD)
    t.MembershipStore().add(OWNER, "club-a", role=t.ROLE_OWNER)  # bound workspace

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": wm}


def _owner_client(app):
    c = app.test_client()
    assert c.post("/login", data={"email": OWNER, "password": PASSWORD}).status_code in (302, 303)
    assert c.post("/api/organisation/active", data={"profile_id": "club-a"}).status_code in (
        200,
        302,
        303,
    )
    return c


# ---- F2 / F3 — accessibility of the members admin markup -------------------


def test_add_member_form_labels_are_associated(members_world):
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    # Label -> input association (for/id) and an autocomplete hint on email.
    assert 'for="mh-member-email"' in html
    assert 'id="mh-member-email"' in html
    assert 'autocomplete="email"' in html
    assert 'for="mh-member-role"' in html
    assert 'id="mh-member-role"' in html


def test_members_table_headers_carry_scope(members_world):
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    # Email / Role / Status / Invited by / (actions) — five column headers.
    assert html.count('<th scope="col"') == 5
    # The actions column has no visible text but is still named for screen readers.
    assert 'aria-label="Actions"' in html


# ---- F4 — the route rejects an address that can never activate --------------


def test_invalid_email_is_rejected_not_stored(members_world):
    from mediahub.web import tenancy as t

    c = _owner_client(members_world["app"])
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "coach@club", "role": "member"},  # no TLD
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Enter a valid email address" in r.get_data(as_text=True)
    # Nothing was written to the ledger for the bad address.
    assert t.MembershipStore().get("coach@club", "club-a") is None


def test_valid_email_is_still_invited(members_world):
    from mediahub.web import tenancy as t

    c = _owner_client(members_world["app"])
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "vol@club.org", "role": "member"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "activates when they sign up" in r.get_data(as_text=True)
    m = t.MembershipStore().get("vol@club.org", "club-a")
    assert m is not None and m.status == t.STATUS_INVITED


# ---- F1 — the submit loader must not stick after a cancelled confirm --------


def test_submit_loader_bails_when_default_prevented(members_world):
    """Source-level lock: the shared bindForms submit handler must skip the
    full-screen loader when an earlier handler (a cancelled confirm, or client
    validation) already prevented the submit — otherwise the "Working on it"
    overlay sticks until the 20s safety timeout. Behaviour is proven in the
    browser during the audit; this guards the guard against removal."""
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    assert "e.defaultPrevented" in html
    # The Remove control still guards with a confirm the user can cancel.
    assert "return confirm(" in html
    assert "lose access immediately" in html
