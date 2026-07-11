"""security/authn-authz: argon2id, account lockout, session rotation, TOTP 2FA.

ASVS L2 chapters 2 (authentication) and 3 (session management).
"""

from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web import auth as auth_mod
    from mediahub.web.web import create_app

    # lockout state is process-global — isolate per test
    auth_mod._failed_logins.clear()
    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _signup(client, email="coach@club.org", password="twelvechars1"):
    # accept_terms: the UK-legal baseline records versioned ToS acceptance
    # at signup (web/legal.py) — signup is refused without it.
    return client.post(
        "/signup", data={"email": email, "password": password, "accept_terms": "1"}
    )


# ------------------------------------------------------------- hashing


def test_new_passwords_hashed_with_argon2id(client, tmp_path):
    _signup(client)
    rec = json.loads((tmp_path / "users.jsonl").read_text().splitlines()[0])
    assert rec["hashed_password"].startswith("$argon2id$")
    assert "twelvechars1" not in json.dumps(rec)


def test_legacy_bcrypt_verifies_and_upgrades_on_login(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import bcrypt

    from mediahub.web.auth import UserStore

    legacy_hash = bcrypt.hashpw(b"twelvechars1", bcrypt.gensalt(rounds=4)).decode()
    (tmp_path / "users.jsonl").write_text(
        json.dumps({"email": "old@club.org", "hashed_password": legacy_hash, "plan": "free"})
        + "\n"
    )
    store = UserStore()
    user = store.authenticate("old@club.org", "twelvechars1")
    assert user.email == "old@club.org"
    # the ledger's latest record now carries an argon2id hash
    assert store.get("old@club.org").hashed_password.startswith("$argon2id$")
    # and the upgraded hash still verifies
    assert store.authenticate("old@club.org", "twelvechars1")


# ------------------------------------------------------------- lockout


def test_lockout_after_repeated_failures(client):
    _signup(client)
    client.post("/logout")
    for _ in range(5):
        r = client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
        assert r.status_code == 401
    # 6th attempt is rejected BEFORE password verification — even correct
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 429


def test_lockout_recorded_in_security_log(client, tmp_path):
    _signup(client)
    client.post("/logout")
    for _ in range(5):
        client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
    events = [
        json.loads(line)
        for line in (tmp_path / "security_log" / "events.jsonl").read_text().splitlines()
    ]
    kinds = [e["event"] for e in events]
    assert "login_failed" in kinds and "login_lockout" in kinds


def test_successful_login_clears_failure_count(client):
    _signup(client)
    client.post("/logout")
    for _ in range(3):
        client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    client.post("/logout")
    for _ in range(3):
        client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
    # 3+3 with a success between must NOT lock (counter reset)
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302


# ------------------------------------------------------ session rotation


def test_rotating_xff_first_hop_cannot_dodge_rate_limit(client):
    """Behind one trusted proxy the real client is the LAST X-Forwarded-For
    hop — the first hop is attacker-supplied. Rotating it must land every
    request in the SAME bucket and still 429 (ADR-0019's brute-force brake)."""
    last = None
    for i in range(12):
        last = client.post(
            "/login",
            data={"email": f"u{i}@club.org", "password": "wrong-pass"},
            # Attacker rotates the client-supplied hop; the proxy-appended
            # (trusted, rightmost) hop stays the same real address.
            headers={"X-Forwarded-For": f"10.0.{i}.{i}, 198.51.100.7"},
        )
    assert last.status_code == 429


def test_session_rotated_on_login(client):
    _signup(client)
    client.post("/logout")
    with client.session_transaction() as sess:
        sess["pre_login_marker"] = "planted"
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert "pre_login_marker" not in sess  # old session state dropped
        assert sess.get("user_email") == "coach@club.org"


# ----------------------------------------------------------------- TOTP


def test_totp_roundtrip_unit():
    from mediahub.web.auth import totp_generate_secret, totp_verify, _totp_code

    secret = totp_generate_secret()
    now = time.time()
    code = _totp_code(secret, int(now // 30))
    assert totp_verify(secret, code, at=now)
    assert not totp_verify(secret, "000000", at=now) or code == "000000"
    assert not totp_verify(secret, "12345", at=now)  # wrong length
    assert not totp_verify("", code, at=now)
    # ±1 step skew still honoured (fresh secret so the replay guard is cold).
    secret2 = totp_generate_secret()
    code2 = _totp_code(secret2, int(now // 30))
    assert totp_verify(secret2, code2, at=now + 29)


def test_totp_replay_within_window_rejected():
    """RFC 6238 §5.2: the same code must never be accepted twice."""
    from mediahub.web.auth import totp_generate_secret, totp_verify, _totp_code

    secret = totp_generate_secret()
    now = time.time()
    counter = int(now // 30)
    code = _totp_code(secret, counter)
    assert totp_verify(secret, code, at=now)  # first use accepted
    assert not totp_verify(secret, code, at=now)  # immediate replay rejected
    assert not totp_verify(secret, code, at=now + 29)  # replay via skew rejected
    # An older (previous-step) code is also refused once a newer one landed.
    assert not totp_verify(secret, _totp_code(secret, counter - 1), at=now)
    # The next time-step's code is still accepted.
    assert totp_verify(secret, _totp_code(secret, counter + 1), at=now + 30)


def test_totp_rfc6238_vector():
    """RFC 6238 SHA-1 test vector: secret '12345678901234567890', T=59s → 94287082."""
    import base64

    from mediahub.web.auth import _totp_code

    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert _totp_code(secret, 59 // 30) == "287082"[-6:] or _totp_code(secret, 1) == "94287082"[-6:]


def test_2fa_enable_and_login_flow(client, tmp_path):
    _signup(client)
    # enable: fetch setup page (plants secret in session), confirm with code
    r = client.get("/account/2fa")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    from mediahub.web.auth import _totp_code

    code = _totp_code(secret, int(time.time() // 30))
    r = client.post("/account/2fa", data={"action": "enable", "totp": code})
    # H-20: enable success renders the show-once recovery-codes page (200)
    # instead of redirecting straight back to the settings page.
    assert r.status_code == 200
    assert "recovery" in r.get_data(as_text=True).lower()

    # fresh login now requires the second factor
    client.post("/logout")
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]
    with client.session_transaction() as sess:
        assert sess.get("user_email") is None  # password alone is NOT a login

    r = client.post("/login/2fa", data={"totp": "000000"})
    assert r.status_code in (401, 429)
    # Next-step code: the enable step consumed the current counter, and the
    # replay guard (RFC 6238 §5.2) never accepts a counter twice.
    code = _totp_code(secret, int(time.time() // 30) + 1)
    r = client.post("/login/2fa", data={"totp": code})
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("user_email") == "coach@club.org"


def test_2fa_disable_requires_valid_code(client):
    _signup(client)
    client.get("/account/2fa")
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    from mediahub.web.auth import _totp_code

    client.post(
        "/account/2fa",
        data={"action": "enable", "totp": _totp_code(secret, int(time.time() // 30))},
    )
    r = client.post("/account/2fa", data={"action": "disable", "totp": "999999"})
    assert r.status_code == 400
    # Next-step code — the enable step consumed the current counter (replay guard).
    r = client.post(
        "/account/2fa",
        data={"action": "disable", "totp": _totp_code(secret, int(time.time() // 30) + 1)},
    )
    assert r.status_code == 302


# ---------------------------------------- logout & revocation (org-access audit)


def _seed_member_org(email="coach@club.org", pid="org-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.tenancy import ROLE_OWNER, MembershipStore

    save_profile(
        ClubProfile(profile_id=pid, display_name="Org A", brand_voice_summary="Bold and warm.")
    )
    MembershipStore().add(email, pid, role=ROLE_OWNER)


def test_login_lands_member_directly_on_their_org(client):
    """A1: sign-in binds the member's own organisation into the session and
    lands on the app — never on the organisation picker."""
    _signup(client)
    _seed_member_org()
    client.post("/logout")
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    assert "/make" in r.headers["Location"]
    with client.session_transaction() as sess:
        assert sess.get("active_profile_id") == "org-a"


def test_get_logout_is_inert_and_post_clears_everything(client):
    """/logout: GET only renders a confirmation (a cross-site link can't end
    a session); POST performs it and clears the WHOLE session — the org pin
    must never outlive the account that earned it."""
    _signup(client)
    _seed_member_org()
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "org-a"

    r = client.get("/logout")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get("user_email") == "coach@club.org"
        assert sess.get("active_profile_id") == "org-a"

    r = client.post("/logout")
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("user_email") is None
        assert sess.get("active_profile_id") is None


def test_replayed_prelogout_cookie_is_dead(client):
    """Logout revokes server-side (session epoch): a captured pre-logout
    cookie must not restore the account — or its organisation access."""
    _signup(client)
    _seed_member_org()
    stale = client.get_cookie("session")
    assert stale is not None
    stale_value = stale.value
    client.post("/logout")

    client.set_cookie("session", stale_value)
    r = client.get("/account/2fa")
    assert r.status_code == 302  # bounced to sign-in: identity refused
    # the org-scoped set-active API also refuses the replayed identity
    r = client.post("/api/organisation/active", data={"profile_id": "org-a"})
    assert r.status_code == 404

    # a fresh, real login still works (epoch re-synced at login)
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    r = client.get("/account/2fa")
    assert r.status_code == 200


def test_dev_logout_revokes_outstanding_dev_cookies(app, monkeypatch):
    """Operator logout writes the dev-session watermark: a replayed
    pre-logout operator cookie is refused at every operator gate."""
    import argon2

    monkeypatch.setenv("MEDIAHUB_DEV_USER", "op")
    monkeypatch.setenv(
        "MEDIAHUB_DEV_PASSWORD_HASH", argon2.PasswordHasher().hash("op-password-12")
    )
    client = app.test_client()
    r = client.post("/developer", data={"dev_user": "op", "dev_password": "op-password-12"})
    assert r.status_code == 302
    stale_value = client.get_cookie("session").value
    r = client.get("/operator/notify-users")
    assert r.status_code == 200  # live operator session

    client.post("/logout")
    client.set_cookie("session", stale_value)
    r = client.get("/operator/notify-users")
    assert r.status_code == 302
    assert "/developer" in r.headers["Location"]


def test_signed_in_html_is_no_store_but_anonymous_is_not(client):
    """Signed-in HTML carries Cache-Control: no-store so the back button on a
    shared machine cannot resurrect a signed-out page; anonymous pages keep
    normal caching."""
    r = client.get("/login")
    assert r.headers.get("Cache-Control") != "no-store"
    _signup(client)
    r = client.get("/")
    assert r.headers.get("Cache-Control") == "no-store"
