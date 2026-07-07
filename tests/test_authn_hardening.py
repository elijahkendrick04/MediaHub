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
    client.get("/logout")
    for _ in range(5):
        r = client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
        assert r.status_code == 401
    # 6th attempt is rejected BEFORE password verification — even correct
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 429


def test_lockout_recorded_in_security_log(client, tmp_path):
    _signup(client)
    client.get("/logout")
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
    client.get("/logout")
    for _ in range(3):
        client.post("/login", data={"email": "coach@club.org", "password": "wrong-pass"})
    r = client.post("/login", data={"email": "coach@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    client.get("/logout")
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
    client.get("/logout")
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
    assert r.status_code == 302

    # fresh login now requires the second factor
    client.get("/logout")
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
