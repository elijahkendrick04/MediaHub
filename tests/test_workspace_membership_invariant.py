"""tests/test_workspace_membership_invariant.py — the PC.3 workspace-binding invariant.

ADR-0003's sweep (`test_run_route_isolation_invariant.py`) proves no *run route*
leaks across orgs — but the profile-PINNING choke point (`_active_profile_id()`,
``POST /api/organisation/active``, ``/sign-in``, the ``/organisation`` editor,
``/sign-in/delete``) historically accepted ANY ``profile_id`` after a bare
existence check. That was correct for single-instance-per-club and fatal for the
shared instance PC.3 introduces. This file pins the per-org binding schema
decided in ADR-0014:

  - an org with ≥1 ACTIVE membership ("bound") is members-only at every pinning
    / editing / deleting surface, and invisible in foreign sessions' pickers;
  - an org with zero active memberships ("unbound") behaves exactly as today,
    so pilot deployments and the existing anonymous fixtures are untouched;
  - operator pre-bind (an ``invited`` row) does NOT lock the org, and signup
    auto-activates it — the zero-founder-involvement first-claim path;
  - ownerless legacy runs — readable-by-design on a single-org box — are NOT
    readable by a *signed-in foreign* account on a shared instance (the
    blast-radius change the Council required closing before this schema
    shipped), while anonymous/legacy and operator access are preserved.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_ALPHA_SECRETS = ("SECRET ALPHA INVITATIONAL", "Alpha Athlete", "Alpha-only")
_ORPHAN_SECRETS = ("SECRET ORPHAN GALA", "Orphan Athlete", "Orphan-only")

_ARG_FILL = {
    "ach_index": "0",
    "swim_id": "swim-orphan-1",
    "card_id": "card-orphan-1",
    "swimmer_key": "Orphan Athlete",
    "job_id": "job-x",
    # UI 1.8 reel review-comment mutate route — the ownerless-run blast-radius
    # sweep reaches it with a junk id; a foreign account must be refused before
    # the comment is ever looked up.
    "comment_id": "no-such-comment",
    # PC.10: the public wall's card route carries a per-org token. An
    # unknown token must 404 before any run data is touched, so sweeping
    # it with a junk token is exactly the guarantee to pin.
    "token": "no-such-wall-token",
    "pack_id": "no-such-pack",
    # 1.11: the charts SVG route carries a chart id. A foreign account must be
    # refused by _can_access_run before any chart (which embeds athlete names)
    # is ever rendered, so sweeping it with a junk id pins that guarantee.
    "chart_id": "no-such-chart",
    # 1.16: the microsite draft-preview card route carries a site id. A junk id
    # is right — a foreign account is refused (the site load returns nothing, and
    # the run is _can_access_run-guarded) before any card image is served.
    "site_id": "no-such-site",
    # 1.17: the newsletter editor-preview card route carries a newsletter id. A
    # junk id is right — a foreign account is refused (the newsletter isn't
    # theirs and the run is _can_access_run-guarded) before any image is served.
    "newsletter_id": "no-such-newsletter",
}
_ARG_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

OWNER_EMAIL = "owner-a@cluba.org"
STRANGER_EMAIL = "stranger@clubg.org"
PILOT_EMAIL = "pilot@clubbeta.org"
PASSWORD = "twelve-chars-long"


def _seed_run(
    runs_dir, run_id: str, profile_id: str | None, meet: str, athlete: str, headline: str
):
    data = {
        "run_id": run_id,
        "meet": {"name": meet},
        "cards": [
            {
                "card_id": "card-orphan-1" if profile_id is None else "card-alpha-1",
                "swim_id": "swim-orphan-1" if profile_id is None else "swim-alpha-1",
                "swimmer_name": athlete,
                "event": "100m freestyle",
                "headline": headline,
                "id": "card-orphan-1" if profile_id is None else "card-alpha-1",
            }
        ],
        "trust": {"score": 0.9},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-x",
                        "swimmer_name": athlete,
                        "event": "100m freestyle",
                        "headline": headline,
                    }
                }
            ],
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }
    if profile_id is not None:
        data["profile_id"] = profile_id
        data["profile_display"] = profile_id
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


@pytest.fixture
def shared_instance(tmp_path, monkeypatch):
    """A shared-instance world: bound org (alpha), unbound org (beta), a
    signed-up owner, a signed-up stranger with their own org (gamma), an
    alpha-owned run, and an ownerless legacy run."""
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

    from mediahub.web.club_profile import ClubProfile, save_profile

    for pid, name in (
        ("org-alpha", "Org Alpha"),
        ("org-beta", "Org Beta"),
        ("org-gamma", "Org Gamma"),
    ):
        save_profile(
            ClubProfile(
                profile_id=pid,
                display_name=name,
                brand_voice_summary="Bold, energetic, club-focused.",
            )
        )

    run_alpha = "run-alpha-" + uuid.uuid4().hex[:8]
    _seed_run(
        tmp_path / "runs_v4",
        run_alpha,
        "org-alpha",
        "SECRET ALPHA INVITATIONAL",
        "Alpha Athlete",
        "Alpha-only PB",
    )
    run_orphan = "run-orphan-" + uuid.uuid4().hex[:8]
    _seed_run(
        tmp_path / "runs_v4",
        run_orphan,
        None,
        "SECRET ORPHAN GALA",
        "Orphan Athlete",
        "Orphan-only PB",
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_alpha, "org-alpha", "SECRET ALPHA INVITATIONAL", "alpha.hy3"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', NULL, ?, ?)",
        (run_orphan, "SECRET ORPHAN GALA", "orphan.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.web.auth import UserStore
    from mediahub.web.tenancy import ROLE_OWNER, MembershipStore

    users = UserStore()
    users.create(OWNER_EMAIL, PASSWORD)
    users.create(STRANGER_EMAIL, PASSWORD)
    memberships = MembershipStore()
    memberships.add(OWNER_EMAIL, "org-alpha", role=ROLE_OWNER)  # alpha is BOUND
    memberships.add(STRANGER_EMAIL, "org-gamma", role=ROLE_OWNER)  # gamma is BOUND
    # org-beta has no memberships — UNBOUND (pilot/legacy behaviour).

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    return {
        "app": app,
        "wm": wm,
        "run_alpha": run_alpha,
        "run_orphan": run_orphan,
        "memberships": memberships,
        "users": users,
    }


@pytest.fixture
def legacy_instance(tmp_path, monkeypatch):
    """A no-accounts deployment: orgs exist, nobody has signed up. Everything
    must behave exactly as before PC.3."""
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

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-pilot",
            display_name="Pilot SC",
            brand_voice_summary="Bold, energetic, club-focused.",
        )
    )
    run_orphan = "run-orphan-" + uuid.uuid4().hex[:8]
    _seed_run(
        tmp_path / "runs_v4",
        run_orphan,
        None,
        "SECRET ORPHAN GALA",
        "Orphan Athlete",
        "Orphan-only PB",
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', NULL, ?, ?)",
        (run_orphan, "SECRET ORPHAN GALA", "orphan.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    return {"app": app, "run_orphan": run_orphan}


def _login(client, email, password=PASSWORD):
    r = client.post("/login", data={"email": email, "password": password})
    assert r.status_code in (302, 303), r.status_code


def _login_operator(client):
    # Grant the operator session directly; the /developer credential flow is
    # covered by test_dev_login.py.
    with client.session_transaction() as s:
        s["dev_operator"] = True


def _pin(client, profile_id):
    return client.post("/api/organisation/active", data={"profile_id": profile_id})


def _active_pid(client):
    return (client.get("/api/organisation/active").get_json() or {}).get("profile_id")


def _run_rules(app):
    return [r for r in app.url_map.iter_rules() if "run_id" in r.arguments]


def _build_path(rule_str, fill):
    missing = None

    def sub(m):
        nonlocal missing
        name = m.group(1)
        if name not in fill:
            missing = name
            return m.group(0)
        return quote(str(fill[name]), safe="")

    return _ARG_RE.sub(sub, rule_str), missing


class TestBoundOrgPinning:
    def test_anonymous_cannot_pin_a_bound_org(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            r = _pin(c, "org-alpha")
            assert r.status_code == 404
            assert r.get_json()["error"] == "unknown_profile"
            assert _active_pid(c) is None

    def test_signed_in_non_member_cannot_pin_a_bound_org(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            r = _pin(c, "org-alpha")
            assert r.status_code == 404  # indistinguishable from nonexistent
            assert _active_pid(c) is None

    def test_member_and_operator_can_pin_a_bound_org(self, shared_instance):
        app = shared_instance["app"]
        with app.test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            assert _active_pid(c) == "org-alpha"
        with app.test_client() as c:
            _login_operator(c)
            assert _pin(c, "org-alpha").status_code == 200

    def test_anyone_can_still_pin_an_unbound_org(self, shared_instance):
        # Step-14 standalone semantics: org-beta has no members and stays open.
        app = shared_instance["app"]
        with app.test_client() as c:
            assert _pin(c, "org-beta").status_code == 200  # anonymous
        with app.test_client() as c:
            _login(c, STRANGER_EMAIL)
            assert _pin(c, "org-beta").status_code == 200  # foreign signed-in

    def test_sign_in_post_refuses_bound_org_for_non_members(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            c.post("/sign-in", data={"profile_id": "org-alpha"})
            assert _active_pid(c) is None

    def test_resolver_unpins_when_membership_is_removed(self, shared_instance):
        ms = shared_instance["memberships"]
        from mediahub.web.tenancy import ROLE_OWNER

        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            # Transfer ownership away, then remove the pinned member mid-session.
            ms.add("new-owner@cluba.org", "org-alpha", role=ROLE_OWNER)
            ms.remove(OWNER_EMAIL, "org-alpha")
            assert _active_pid(c) is None  # self-healed on the next request


class TestPickerScoping:
    def test_anonymous_picker_hides_bound_orgs(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            body = c.get("/sign-in").get_data(as_text=True)
            assert "Org Beta" in body  # unbound stays visible
            assert "Org Alpha" not in body
            assert "Org Gamma" not in body

    def test_member_picker_shows_their_org_not_foreign_bound_orgs(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            body = c.get("/sign-in").get_data(as_text=True)
            assert "Org Gamma" in body
            assert "Org Beta" in body  # unbound stays visible
            assert "Org Alpha" not in body

    def test_operator_picker_shows_everything(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login_operator(c)
            body = c.get("/sign-in").get_data(as_text=True)
            assert "Org Alpha" in body and "Org Beta" in body and "Org Gamma" in body


class TestSettingsAndDeleteGates:
    def test_non_member_cannot_edit_a_bound_org(self, shared_instance):
        from mediahub.web.club_profile import load_profile

        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            r = c.post(
                "/organisation",
                data={"profile_id": "org-alpha", "display_name": "HACKED", "action": "save"},
            )
            assert r.status_code == 404
        assert load_profile("org-alpha").display_name == "Org Alpha"

    def test_anonymous_cannot_edit_a_bound_org(self, shared_instance):
        from mediahub.web.club_profile import load_profile

        with shared_instance["app"].test_client() as c:
            r = c.post(
                "/organisation",
                data={"profile_id": "org-alpha", "display_name": "HACKED", "action": "save"},
            )
            assert r.status_code == 404
        assert load_profile("org-alpha").display_name == "Org Alpha"

    def test_member_can_edit_their_bound_org(self, shared_instance):
        from mediahub.web.club_profile import load_profile

        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            r = c.post(
                "/organisation",
                data={
                    "profile_id": "org-alpha",
                    "display_name": "Org Alpha Updated",
                    "action": "save",
                },
            )
            assert r.status_code == 200
        assert load_profile("org-alpha").display_name == "Org Alpha Updated"

    def test_non_owner_cannot_delete_a_bound_org(self, shared_instance):
        from mediahub.web.club_profile import load_profile

        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            c.post("/sign-in/delete", data={"profile_id": "org-alpha"})
        assert load_profile("org-alpha") is not None
        with shared_instance["app"].test_client() as c:  # anonymous
            c.post("/sign-in/delete", data={"profile_id": "org-alpha"})
        assert load_profile("org-alpha") is not None

    def test_owner_can_delete_their_bound_org(self, shared_instance):
        from mediahub.web.club_profile import load_profile

        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            c.post("/sign-in/delete", data={"profile_id": "org-alpha"})
        assert load_profile("org-alpha") is None


class TestCreationBinding:
    def test_signed_in_creation_binds_creator_as_owner(self, shared_instance):
        ms = shared_instance["memberships"]
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            r = c.post(
                "/organisation",
                data={"profile_id": "new-club", "display_name": "New Club", "action": "save"},
            )
            assert r.status_code == 200
        assert ms.is_active_owner(STRANGER_EMAIL, "new-club") is True
        assert ms.is_bound("new-club") is True

    def test_anonymous_creation_stays_unbound(self, shared_instance):
        ms = shared_instance["memberships"]
        with shared_instance["app"].test_client() as c:
            r = c.post(
                "/organisation",
                data={
                    "profile_id": "walkin-club",
                    "display_name": "Walk-in Club",
                    "action": "save",
                },
            )
            assert r.status_code == 200
        assert ms.is_bound("walkin-club") is False

    def test_editing_an_unbound_org_does_not_grab_it(self, shared_instance):
        # The Council's grab-risk: a signed-in stranger editing an EXISTING
        # unbound org must not become its owner as a side effect.
        ms = shared_instance["memberships"]
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)
            r = c.post(
                "/organisation",
                data={"profile_id": "org-beta", "display_name": "Org Beta", "action": "save"},
            )
            assert r.status_code == 200
        assert ms.is_bound("org-beta") is False


class TestInviteFirstClaimPath:
    def test_invite_then_signup_binds_with_zero_operator_requests(self, shared_instance):
        from mediahub.web.tenancy import ROLE_OWNER, STATUS_INVITED

        ms = shared_instance["memberships"]
        app = shared_instance["app"]
        # Operator pre-binds the pilot's contact email (one-time founder action).
        ms.add(
            PILOT_EMAIL,
            "org-beta",
            role=ROLE_OWNER,
            status=STATUS_INVITED,
            invited_by="developer@mediahub.local",
            invited_via_profile_id="org-beta",
        )
        # The invite must NOT lock the org — the pilot keeps working anonymously.
        assert ms.is_bound("org-beta") is False
        with app.test_client() as c:
            assert _pin(c, "org-beta").status_code == 200

        # The pilot signs up — no operator involved — and the org binds.
        with app.test_client() as c:
            r = c.post("/signup", data={"email": PILOT_EMAIL, "password": PASSWORD, "accept_terms": "1"})
            assert r.status_code in (302, 303)
        assert ms.is_bound("org-beta") is True
        assert ms.is_active_owner(PILOT_EMAIL, "org-beta") is True

        # Members-only from this moment on.
        with app.test_client() as c:
            assert _pin(c, "org-beta").status_code == 404  # anonymous
        with app.test_client() as c:
            _login(c, PILOT_EMAIL)
            assert _pin(c, "org-beta").status_code == 200


class TestOwnerlessRunBlastRadius:
    def test_ownerless_run_not_reachable_by_foreign_signed_in_account(self, shared_instance):
        """Sweep EVERY run route as a signed-in stranger pinned to their own
        org: the ownerless legacy run's markers must never appear."""
        app = shared_instance["app"]
        fill = dict(_ARG_FILL)
        fill["run_id"] = shared_instance["run_orphan"]
        with app.test_client() as c:
            _login(c, STRANGER_EMAIL)
            assert _pin(c, "org-gamma").status_code == 200
            swept, uncoverable, leaked = [], [], []
            for rule in _run_rules(app):
                path, missing = _build_path(rule.rule, fill)
                if missing is not None:
                    uncoverable.append(f"{rule.rule}  (unknown arg <{missing}>)")
                    continue
                methods = rule.methods or set()
                method = "GET" if "GET" in methods else ("POST" if "POST" in methods else None)
                if method is None:
                    continue
                resp = c.open(path, method=method, data={}, follow_redirects=True)
                body = resp.get_data(as_text=True)
                hit = [s for s in _ORPHAN_SECRETS if s in body]
                if hit:
                    leaked.append(f"{method} {rule.rule} -> {resp.status_code} leaked {hit}")
                swept.append(rule.rule)
            assert not uncoverable, (
                "Run routes the ownerless-run invariant can't reach — extend _ARG_FILL:\n  "
                + "\n  ".join(uncoverable)
            )
            assert len(swept) >= 20, f"Only swept {len(swept)} run routes."
            assert not leaked, (
                "An ownerless legacy run leaked to a signed-in foreign account "
                "(the shared-instance blast radius ADR-0014 closes):\n  " + "\n  ".join(leaked)
            )

    def test_owned_run_not_reachable_by_foreign_signed_in_account(self, shared_instance):
        app = shared_instance["app"]
        with app.test_client() as c:
            _login(c, STRANGER_EMAIL)
            assert _pin(c, "org-gamma").status_code == 200
            r = c.get(f"/review/{shared_instance['run_alpha']}", follow_redirects=True)
            assert "SECRET ALPHA INVITATIONAL" not in r.get_data(as_text=True)

    def test_operator_still_sees_ownerless_run(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login_operator(c)
            assert _pin(c, "org-beta").status_code == 200
            r = c.get(f"/review/{shared_instance['run_orphan']}")
            assert r.status_code == 200
            assert "SECRET ORPHAN GALA" in r.get_data(as_text=True)

    def test_owner_still_sees_her_own_run(self, shared_instance):
        # ADR-0003 positive control, now under account-mode.
        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            r = c.get(f"/review/{shared_instance['run_alpha']}")
            assert r.status_code == 200
            assert "SECRET ALPHA INVITATIONAL" in r.get_data(as_text=True)


class TestMembersPage:
    def test_owner_adds_member_who_activates_at_signup(self, shared_instance):
        ms = shared_instance["memberships"]
        app = shared_instance["app"]
        with app.test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            r = c.post(
                "/organisation/members",
                data={"action": "add", "email": "volunteer@cluba.org", "role": "member"},
            )
            assert r.status_code == 200
            assert "activates when they sign up" in r.get_data(as_text=True)
        m = ms.get("volunteer@cluba.org", "org-alpha")
        assert m.status == "invited"
        assert m.invited_by == OWNER_EMAIL
        assert m.invited_via_profile_id == "org-alpha"
        with app.test_client() as c:
            c.post("/signup", data={"email": "volunteer@cluba.org", "password": PASSWORD, "accept_terms": "1"})
        assert ms.is_active_member("volunteer@cluba.org", "org-alpha") is True
        # The new member can now pin the bound org.
        with app.test_client() as c:
            _login(c, "volunteer@cluba.org")
            assert _pin(c, "org-alpha").status_code == 200

    def test_non_owner_member_cannot_manage_members(self, shared_instance):
        ms = shared_instance["memberships"]
        from mediahub.web.tenancy import ROLE_MEMBER

        ms.add("volunteer@cluba.org", "org-alpha", role=ROLE_MEMBER)
        shared_instance["users"].create("volunteer@cluba.org", PASSWORD)
        with shared_instance["app"].test_client() as c:
            _login(c, "volunteer@cluba.org")
            assert _pin(c, "org-alpha").status_code == 200
            r = c.post(
                "/organisation/members",
                data={"action": "add", "email": "friend@elsewhere.org", "role": "owner"},
            )
            assert r.status_code == 404
        assert ms.get("friend@elsewhere.org", "org-alpha") is None

    def test_owner_cannot_remove_last_owner_via_page(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            r = c.post(
                "/organisation/members",
                data={"action": "remove", "email": OWNER_EMAIL},
            )
            assert r.status_code == 200
            assert "Cannot remove the last owner" in r.get_data(as_text=True)
        assert shared_instance["memberships"].is_active_owner(OWNER_EMAIL, "org-alpha") is True

    def test_members_page_requires_an_active_org(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            r = c.get("/organisation/members")
            assert r.status_code in (302, 303)  # bounced to the picker

    def test_anon_on_open_workspace_cannot_read_member_emails(self, shared_instance):
        """Unbound (open) orgs are pinnable by any anonymous visitor, so a
        pre-seeded pilot invite email (customer PII) must NOT render on GET —
        only the operator, an active owner, or an active member sees rows."""
        ms = shared_instance["memberships"]
        # Operator pre-seeds a pilot invite on the OPEN org-beta (invited
        # status does not bind the workspace).
        from mediahub.web.tenancy import STATUS_INVITED

        ms.add(
            "pilot-contact@clubb.org",
            "org-beta",
            status=STATUS_INVITED,
            invited_by="operator@host",
        )
        assert ms.is_bound("org-beta") is False
        with shared_instance["app"].test_client() as c:
            assert _pin(c, "org-beta").status_code == 200  # open org: anon pin ok
            body = c.get("/organisation/members").get_data(as_text=True)
        assert "pilot-contact@clubb.org" not in body
        assert "operator@host" not in body
        assert "Member details are hidden" in body

    def test_signed_in_stranger_on_open_workspace_sees_no_emails(self, shared_instance):
        ms = shared_instance["memberships"]
        from mediahub.web.tenancy import STATUS_INVITED

        ms.add(
            "pilot-contact@clubb.org",
            "org-beta",
            status=STATUS_INVITED,
            invited_by="operator@host",
        )
        with shared_instance["app"].test_client() as c:
            _login(c, STRANGER_EMAIL)  # a real account, but no org-beta seat
            assert _pin(c, "org-beta").status_code == 200
            body = c.get("/organisation/members").get_data(as_text=True)
        assert "pilot-contact@clubb.org" not in body
        assert "Member details are hidden" in body

    def test_owner_still_sees_member_emails(self, shared_instance):
        with shared_instance["app"].test_client() as c:
            _login(c, OWNER_EMAIL)
            assert _pin(c, "org-alpha").status_code == 200
            body = c.get("/organisation/members").get_data(as_text=True)
        assert OWNER_EMAIL in body


class TestLegacyModeUnchanged:
    def test_no_accounts_means_no_gates(self, legacy_instance):
        with legacy_instance["app"].test_client() as c:
            assert _pin(c, "org-pilot").status_code == 200  # anonymous pin works
            r = c.get(f"/review/{legacy_instance['run_orphan']}")
            assert r.status_code == 200  # ownerless run readable, as always
            assert "SECRET ORPHAN GALA" in r.get_data(as_text=True)
            body = c.get("/sign-in").get_data(as_text=True)
            assert "Pilot SC" in body
