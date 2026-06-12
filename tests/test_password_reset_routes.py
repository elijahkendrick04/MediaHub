"""PC.14 — password reset, email verification, invite delivery and the
operator breach channel, end to end through the routes.

The email seam is monkeypatched at the HTTP layer so the tests assert on
exactly what a provider would receive — and the unconfigured deployment
shows the honest unavailable page instead of pretending.
"""

from __future__ import annotations

import importlib
import json
import re

import pytest


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture
def app_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MEDIAHUB_EMAIL_FROM", raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.auth import UserStore

    UserStore().create("coach@club.org", "original-password-1")
    return {"app": app, "wm": wm, "tmp": tmp_path}


@pytest.fixture
def outbox(monkeypatch):
    """Configure the seam and capture every provider POST."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MEDIAHUB_EMAIL_FROM", "MediaHub <no-reply@example.org>")
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return _Resp(200)

    monkeypatch.setattr("requests.post", fake_post)
    return sent


def _reset_link_from(text: str) -> str:
    m = re.search(r"http://\S*/password/reset/(\S+)", text)
    assert m, f"no reset link in email body: {text!r}"
    return "/password/reset/" + m.group(1)


# ---- honest-unavailable state ----------------------------------------------


def test_forgot_password_unconfigured_is_honest(app_world):
    """Unconfigured email: the GET page explains honestly at 200 (the B5
    API contract pins that no GET surface answers 5xx); the POST action —
    the thing that genuinely can't be performed — answers 503."""
    c = app_world["app"].test_client()
    r = c.get("/password/forgot")
    assert r.status_code == 200
    assert "not" in r.get_data(as_text=True).lower()
    assert "configured" in r.get_data(as_text=True).lower()
    r = c.post("/password/forgot", data={"email": "coach@club.org"})
    assert r.status_code == 503


# ---- the reset flow ---------------------------------------------------------


def test_password_reset_end_to_end(app_world, outbox):
    c = app_world["app"].test_client()
    # Request the link.
    r = c.post("/password/forgot", data={"email": "coach@club.org"})
    assert r.status_code == 200
    assert len(outbox) == 1
    link = _reset_link_from(outbox[0]["text"])

    # The form renders.
    assert c.get(link).status_code == 200

    # Set the new password → signed in.
    r = c.post(link, data={"password": "brand-new-password-9"})
    assert r.status_code == 302

    # Old password dead, new password works.
    from mediahub.web.auth import AuthError, UserStore

    store = UserStore()
    with pytest.raises(AuthError):
        store.authenticate("coach@club.org", "original-password-1")
    assert store.authenticate("coach@club.org", "brand-new-password-9")

    # The link was single-use: reusing it is refused.
    assert c.post(link, data={"password": "another-password-22"}).status_code == 404


def test_forgot_password_does_not_enumerate_accounts(app_world, outbox):
    c = app_world["app"].test_client()
    real = c.post("/password/forgot", data={"email": "coach@club.org"})
    fake = c.post("/password/forgot", data={"email": "nobody@club.org"})
    # Same outward response either way; only the real account got mail.
    assert real.status_code == fake.status_code == 200
    assert real.get_data(as_text=True) == fake.get_data(as_text=True)
    assert len(outbox) == 1


def test_short_password_rejected_at_reset(app_world, outbox):
    c = app_world["app"].test_client()
    c.post("/password/forgot", data={"email": "coach@club.org"})
    link = _reset_link_from(outbox[0]["text"])
    r = c.post(link, data={"password": "short"})
    assert r.status_code == 400
    # Original password still works — nothing changed.
    from mediahub.web.auth import UserStore

    assert UserStore().authenticate("coach@club.org", "original-password-1")


# ---- verification -----------------------------------------------------------


def test_signup_sends_verification_and_route_marks_verified(app_world, outbox):
    c = app_world["app"].test_client()
    r = c.post(
        "/signup",
        data={"email": "new@club.org", "password": "password-xyz-1", "accept_terms": "1"},
    )
    assert r.status_code == 302
    assert len(outbox) == 1
    m = re.search(r"http://\S*/verify-email/(\S+)", outbox[0]["text"])
    assert m
    r = c.get("/verify-email/" + m.group(1))
    assert r.status_code == 200

    from mediahub.web.auth import UserStore

    assert UserStore().get("new@club.org").email_verified_at


def test_signup_without_email_seam_still_works(app_world):
    c = app_world["app"].test_client()
    r = c.post(
        "/signup",
        data={"email": "plain@club.org", "password": "password-xyz-1", "accept_terms": "1"},
    )
    assert r.status_code == 302  # signup never blocks on the seam


# ---- invite delivery --------------------------------------------------------


def test_member_invite_email_delivered(app_world, outbox):
    wm = app_world["wm"]
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.tenancy import MembershipStore, ROLE_OWNER, STATUS_ACTIVE

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A SC"))
    MembershipStore().add("coach@club.org", "org-a", role=ROLE_OWNER, status=STATUS_ACTIVE)

    import mediahub.web.legal as legal

    c = app_world["app"].test_client()
    with c.session_transaction() as s:
        s["user_email"] = "coach@club.org"
        s["terms_ok_version"] = legal.TERMS_VERSION
        s["active_profile_id"] = "org-a"
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "treasurer@club.org", "role": "member"},
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "invite email is on its way" in html
    assert len(outbox) == 1
    assert outbox[0]["to"] == ["treasurer@club.org"]
    assert "Org A SC" in outbox[0]["subject"]
    assert "/signup" in outbox[0]["text"]


def test_member_invite_without_seam_is_honest(app_world):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.tenancy import MembershipStore, ROLE_OWNER, STATUS_ACTIVE

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A SC"))
    MembershipStore().add("coach@club.org", "org-a", role=ROLE_OWNER, status=STATUS_ACTIVE)

    import mediahub.web.legal as legal

    c = app_world["app"].test_client()
    with c.session_transaction() as s:
        s["user_email"] = "coach@club.org"
        s["terms_ok_version"] = legal.TERMS_VERSION
        s["active_profile_id"] = "org-a"
    r = c.post(
        "/organisation/members",
        data={"action": "add", "email": "treasurer@club.org", "role": "member"},
    )
    assert "share the signup link" in r.get_data(as_text=True)


# ---- operator breach channel ------------------------------------------------


def test_notify_users_requires_operator(app_world):
    c = app_world["app"].test_client()
    # Non-operator → bounced to the public developer sign-in (not a 404).
    r = c.get("/operator/notify-users")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]


def test_notify_users_sends_to_all_and_records(app_world, outbox, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DEV_KEY", "op-key-123")
    c = app_world["app"].test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True
    r = c.get("/operator/notify-users")
    assert r.status_code == 200

    r = c.post(
        "/operator/notify-users",
        data={"subject": "Security notice", "message": "What happened, what we did."},
    )
    assert r.status_code == 200
    assert "Sent to 1 of 1" in r.get_data(as_text=True)
    assert outbox[0]["to"] == ["coach@club.org"]

    ledger = app_world["tmp"] / "operator_notices.jsonl"
    assert ledger.exists()
    rec = json.loads(ledger.read_text().splitlines()[-1])
    assert rec["subject"] == "Security notice"
    assert rec["recipients_sent"] == 1
