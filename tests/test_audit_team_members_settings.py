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

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

PASSWORD = "twelve-chars-long"
OWNER = "owner@club-a.org"


@pytest.fixture
def members_world(web_module, monkeypatch):
    """A bound single-owner workspace, signed in and pinned as the owner."""
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    from mediahub.web.auth import UserStore
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web import tenancy as t

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    # An unbound (open) workspace for the open-state copy tests — no members.
    save_profile(ClubProfile(profile_id="open-club", display_name="Open Club"))
    UserStore().create(OWNER, PASSWORD)
    t.MembershipStore().add(OWNER, "club-a", role=t.ROLE_OWNER)  # bound workspace

    app = web_module.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": web_module}


def _owner_client(app):
    c = app.test_client()
    assert c.post("/login", data={"email": OWNER, "password": PASSWORD}).status_code in (302, 303)
    assert c.post("/api/organisation/active", data={"profile_id": "club-a"}).status_code in (
        200,
        302,
        303,
    )
    return c


def _anon_open_client(app):
    """Anonymous session pinned to the open (unbound) workspace."""
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "open-club"})
    return c


def _seed_owner(email: str):
    """Add a second signed-up active OWNER to the bound club-a workspace."""
    from mediahub.web.auth import UserStore
    from mediahub.web import tenancy as t

    UserStore().create(email, PASSWORD)
    t.MembershipStore().add(email, "club-a", role=t.ROLE_OWNER)


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
    # A removable (non-sole-owner) member must exist for a confirm-guarded
    # Remove form to render — the sole owner's Remove is disabled (L8).
    _seed_second_active_member("removable@club.org")
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    assert "e.defaultPrevented" in html
    # The Remove control still guards with a confirm the user can cancel.
    assert "return confirm(" in html
    assert "lose access immediately" in html


# ---- F5 — editing an invited member's role must not re-send the invite ------


def _seed_second_active_member(email: str):
    """Add a second signed-up active member to the bound club-a workspace."""
    from mediahub.web.auth import UserStore
    from mediahub.web import tenancy as t

    UserStore().create(email, PASSWORD)
    t.MembershipStore().add(email, "club-a", role=t.ROLE_MEMBER)


def test_editing_invited_member_role_does_not_resend_invite(members_world, monkeypatch):
    """The per-row role picker reuses action=add. For a member who is still only
    *invited*, that upsert must not fire a fresh invite email on every tweak."""
    import mediahub.notify.email as email_mod

    sent: list[str] = []
    monkeypatch.setattr(email_mod, "email_configured", lambda: True)
    monkeypatch.setattr(
        email_mod, "send_email", lambda to, subject, text, html=None: (sent.append(to), True)[1]
    )

    c = _owner_client(members_world["app"])
    # A brand-new invite via the Add form sends exactly one email.
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "vol@club.org", "role": "member", "via": "add_form"},
        follow_redirects=True,
    )
    assert "An invite email is on its way" in r.get_data(as_text=True)
    assert sent == ["vol@club.org"]

    # Changing that invited member's role via the picker (action=add, no via)
    # must NOT send another email, and must not falsely claim one is on its way.
    r2 = c.post(
        "/organisation/members",
        data={"action": "add", "email": "vol@club.org", "role": "viewer"},
        follow_redirects=True,
    )
    body = r2.get_data(as_text=True)
    assert sent == ["vol@club.org"], "invite email was re-sent on a role change"
    assert "on its way" not in body
    assert "still invited" in body

    from mediahub.web import tenancy as t

    assert t.MembershipStore().get("vol@club.org", "club-a").role == t.ROLE_VIEWER


# ---- F6 — the original inviter is preserved through a role change ------------


def test_invited_by_is_preserved_on_role_change(members_world):
    from mediahub.web import tenancy as t

    # OWNER invites x via the Add form -> invited_by == OWNER.
    c = _owner_client(members_world["app"])
    c.post(
        "/organisation/members",
        data={"action": "add", "email": "x@club.org", "role": "member", "via": "add_form"},
        follow_redirects=True,
    )
    assert t.MembershipStore().get("x@club.org", "club-a").invited_by == OWNER

    # A different admin (the operator) later changes x's role via the picker.
    oc = members_world["app"].test_client()
    with oc.session_transaction() as s:
        s["dev_operator"] = True
    oc.post("/api/organisation/active", data={"profile_id": "club-a"})
    oc.post(
        "/organisation/members",
        data={"action": "add", "email": "x@club.org", "role": "viewer"},
        follow_redirects=True,
    )
    m = t.MembershipStore().get("x@club.org", "club-a")
    assert m.role == t.ROLE_VIEWER
    assert m.invited_by == OWNER, "invited_by was overwritten to the last editor"


# ---- F7 — the Add form never silently changes an existing member's role -----


def test_add_form_refuses_an_existing_active_member(members_world):
    from mediahub.web import tenancy as t

    _seed_second_active_member("m2@club.org")
    c = _owner_client(members_world["app"])
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "m2@club.org", "role": "viewer", "via": "add_form"},
        follow_redirects=True,
    )
    assert "already a member" in r.get_data(as_text=True)
    # Role unchanged — no silent downgrade from the "add" affordance.
    assert t.MembershipStore().get("m2@club.org", "club-a").role == t.ROLE_MEMBER


def test_picker_can_still_change_an_active_member_role(members_world):
    """The per-row picker (action=add, no via) is the legitimate way to change
    an active member's role and must keep working."""
    from mediahub.web import tenancy as t

    _seed_second_active_member("m3@club.org")
    c = _owner_client(members_world["app"])
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "m3@club.org", "role": "viewer"},
        follow_redirects=True,
    )
    assert "role updated to viewer" in r.get_data(as_text=True)
    assert t.MembershipStore().get("m3@club.org", "club-a").role == t.ROLE_VIEWER


def test_email_with_line_separator_is_rejected(members_world):
    """A U+2028/U+2029/U+0085 in the address would tear the JSON-lines ledger on
    read-back (splitlines), losing the row after a 'success'. Reject it up front."""
    from mediahub.web import tenancy as t

    c = _owner_client(members_world["app"])
    bad = "a\u2028b@club.org"
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": bad, "role": "member", "via": "add_form"},
        follow_redirects=True,
    )
    assert "Enter a valid email address" in r.get_data(as_text=True)
    assert t.MembershipStore().get(bad, "club-a") is None


# ---- F8 (P1) — erasing the last owner must not brick the workspace ----------


def test_erasing_last_owner_promotes_a_remaining_member(tmp_path):
    """Self-serve account deletion (erase_email) has no last-owner guard — right,
    a GDPR erasure can't be refused. But it must not leave a still-populated
    workspace bound-but-ownerless (every remaining member locked out of admin).
    Ownership passes to the longest-standing remaining active member."""
    from mediahub.web import tenancy as t

    s = t.MembershipStore(path=tmp_path / "memberships.jsonl")
    s.add("owner@club.org", "club-z", role=t.ROLE_OWNER)
    s.add("editor@club.org", "club-z", role=t.ROLE_EDITOR)
    s.add("viewer@club.org", "club-z", role=t.ROLE_VIEWER)

    s.erase_email("owner@club.org")

    assert s.get("owner@club.org", "club-z") is None  # erased in full
    assert s.is_bound("club-z") is True  # still a members-only workspace
    # The earliest-joined remaining active member inherits ownership.
    assert s.is_active_owner("editor@club.org", "club-z") is True
    assert s.is_active_member("viewer@club.org", "club-z") is True


def test_erasing_sole_member_still_unbinds(tmp_path):
    """The documented zero-member model is preserved: erasing the only member of
    a workspace leaves it unbound, with no phantom promotion."""
    from mediahub.web import tenancy as t

    s = t.MembershipStore(path=tmp_path / "memberships.jsonl")
    s.add("solo@club.org", "club-solo", role=t.ROLE_OWNER)
    s.erase_email("solo@club.org")
    assert s.is_bound("club-solo") is False
    assert s.list_for_profile("club-solo") == []


# ---- F9 (P2) — status badges must actually render as pills ------------------


def test_status_badges_are_self_styled(members_world):
    """The bare ``.pill`` class has no base CSS rule outside a profile card, so the
    Active/Invited badges must carry their own shape inline — else "Active"
    renders as plain text. Guards the self-contained styling against removal."""
    _seed_second_active_member("active2@club.org")  # an Active row
    # And an invited row so both badge variants render.
    from mediahub.web import tenancy as t

    t.MembershipStore().add("pending@club.org", "club-a", status=t.STATUS_INVITED)
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    # Both badges are pill-shaped (border-radius) rather than unstyled text.
    assert html.count("border-radius:999px") >= 2
    assert ">Active</span>" in html
    assert "Invited — activates at signup" in html


# ---- F10 (P2) — the invite notice must show the signup link it references ----


def test_invite_notice_shows_the_signup_link_when_mail_unconfigured(members_world, monkeypatch):
    """When no email seam is configured the owner has to pass the signup link on
    themselves — so the page must actually show it, not refer to a 'signup link'
    that appears nowhere."""
    import mediahub.notify.email as _email

    # Force the "no mail seam" branch deterministically.
    monkeypatch.setattr(_email, "email_configured", lambda: False, raising=True)
    c = _owner_client(members_world["app"])
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "linkme@club.org", "role": "member"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    # Keep the wording aligned with the pre-existing invite-copy assertion in
    # test_password_reset_routes.py ("share the signup link") — the fix ADDS the
    # URL, it must not change the phrase other tests pin.
    assert "share the signup link" in body
    assert "/signup" in body  # the actual url_for('signup_page') target is rendered


# ======================================================================
# Caveat round — the logged P2/P3 items, now fixed.
# ======================================================================


# ---- L4 (P3) — last-owner demotion is refused atomically in the store -------


def test_store_add_refuses_last_owner_demotion(tmp_path):
    """The route pre-checks the last-owner invariant, but a demotion is an
    upsert (``add`` with a lower role) — two owners demoting each other could
    both pass a non-atomic pre-check and leave the org ownerless. The store now
    enforces it under the ledger lock, so a lone owner can never be demoted."""
    from mediahub.web import tenancy as t

    s = t.MembershipStore(path=tmp_path / "memberships.jsonl")
    s.add("owner@club.org", "club-z", role=t.ROLE_OWNER)
    s.add("editor@club.org", "club-z", role=t.ROLE_EDITOR)
    with pytest.raises(t.TenancyError):
        s.add("owner@club.org", "club-z", role=t.ROLE_EDITOR)  # demote the only owner
    assert s.is_active_owner("owner@club.org", "club-z") is True
    # With a second owner present the demotion is allowed.
    s.add("editor@club.org", "club-z", role=t.ROLE_OWNER)
    s.add("owner@club.org", "club-z", role=t.ROLE_EDITOR)
    assert s.is_active_owner("editor@club.org", "club-z") is True
    assert s.is_active_owner("owner@club.org", "club-z") is False


def test_store_add_still_allows_promotion_and_creation(tmp_path):
    """The guard must only bite a *demotion of the last owner* — never a
    creation, an invite, or a promotion."""
    from mediahub.web import tenancy as t

    s = t.MembershipStore(path=tmp_path / "memberships.jsonl")
    s.add("owner@club.org", "club-z", role=t.ROLE_OWNER)  # first owner (creation)
    s.add("vol@club.org", "club-z", role=t.ROLE_MEMBER)  # add a member
    s.add("vol@club.org", "club-z", role=t.ROLE_OWNER)  # promote to owner
    assert s.is_active_owner("vol@club.org", "club-z") is True


# ---- L8 (P3) — the sole owner's controls are disabled, not live-and-doomed --


def test_sole_owner_controls_are_disabled(members_world):
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    # Role picker replaced by a static label + hint for the sole owner.
    assert "· sole owner" in html
    # Remove is a disabled button with the reason, not a live form.
    assert "Make another member an owner before removing" in html
    assert "disabled" in html
    # No live Update/Remove control targets the sole owner.
    assert f"Update role for {OWNER}" not in html


def test_second_owner_reenables_the_role_picker(members_world):
    _seed_owner("owner2@club-a.org")
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    # With two owners neither is the sole owner, so both get a live picker.
    assert "· sole owner" not in html
    assert f"Change role for {OWNER}" in html
    assert "Change role for owner2@club-a.org" in html


# ---- L12 (P3) — per-row Update/Remove carry an accessible name --------------


def test_row_buttons_have_per_member_accessible_names(members_world):
    _seed_second_active_member("vol@club-a.org")
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    assert "Update role for vol@club-a.org" in html
    assert "Remove vol@club-a.org" in html


# ---- L9 (P2) — self-demotion drops admin controls in the same render --------


def test_self_demotion_drops_admin_controls_immediately(members_world):
    """An owner who hands off ownership and demotes themselves must not see the
    admin surface linger for one render (stale ``can_admin``)."""
    _seed_owner("owner2@club-a.org")
    c = _owner_client(members_world["app"])
    # OWNER demotes THEMSELVES to viewer (owner2 remains, so it's allowed).
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": OWNER, "role": "viewer"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "role updated to viewer" in body
    # The same response must already reflect the lost admin rights: no add-member
    # form (viewers can't manage members).
    assert 'name="via" value="add_form"' not in body


# ---- L10 / L11 (P3) — consistent heading + plain-English open-state copy -----


def test_heading_matches_the_team_members_tile(members_world):
    html = _owner_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    assert "<h1>Team members</h1>" in html


def test_open_workspace_copy_is_plain_english(members_world):
    html = (
        _anon_open_client(members_world["app"]).get("/organisation/members").get_data(as_text=True)
    )
    assert "pre-multi-tenant" not in html  # jargon gone (L11)
    assert "it has no members yet" in html
    # The CTA no longer promises a non-existent owner to "log in as" (L3).
    assert "Only an owner or the deployment operator can add members" in html
    assert "as a workspace owner to manage members" not in html


# ---- residual — the global .pill base rule exists in the shared cascade ------


def test_pill_has_a_global_base_rule():
    from pathlib import Path

    css = (
        Path(__file__).resolve().parents[1] / "src/mediahub/web/static/theme/theme-components.css"
    ).read_text(encoding="utf-8")
    # A bare `.pill { ... }` base rule now exists (previously only the scoped
    # `.mh-profile-card .meta-line .pill` did), so status/token/webhook pills
    # render as pills everywhere, not plain text.
    import re

    assert re.search(r"(?m)^\.pill\s*\{", css), "no base .pill rule in the cascade"
