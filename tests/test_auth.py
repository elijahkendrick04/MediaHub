"""PC.1 — self-serve signup + login + session auth (Appendix B Step 7).

Covers signup, login, logout, bcrypt hashing, the wrong-password clean-error
path (must be a 4xx, never a 500), and the security invariants: passwords are
stored as bcrypt hashes (never plaintext), the session cookie is HttpOnly +
signed, and an unauthenticated /billing redirects to /login.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Auth must work with no billing configured (self-host path).
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    application._data_dir = tmp_path  # for tests that read the ledger
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _users_file(tmp_path):
    return tmp_path / "users.jsonl"


# ---- store-level unit tests --------------------------------------------


def test_password_is_hashed_with_bcrypt(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    store = auth.UserStore()
    user = store.create("a@club.org", "swimswim1234")
    # Stored hash is a bcrypt $2b$ string, NOT the plaintext.
    assert user.hashed_password.startswith("$2b$")
    assert "swimswim1234" not in user.hashed_password
    # Round-trips: correct verifies, wrong does not.
    assert auth.verify_password("swimswim1234", user.hashed_password) is True
    assert auth.verify_password("nope", user.hashed_password) is False


def test_verify_password_never_raises_on_garbage():
    from mediahub.web import auth

    # A corrupted / empty stored hash must yield False, not an exception.
    assert auth.verify_password("anything", "") is False
    assert auth.verify_password("anything", "not-a-hash") is False
    assert auth.verify_password("", "") is False


def test_store_rejects_duplicate_and_short_password(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    store = auth.UserStore()
    store.create("dup@club.org", "longenough123")
    with pytest.raises(auth.AuthError):
        store.create("dup@club.org", "longenough123")  # duplicate
    with pytest.raises(auth.AuthError):
        store.create("short@club.org", "abc")  # < 8 chars
    with pytest.raises(auth.AuthError):
        store.create("not-an-email", "longenough123")  # invalid email


def test_email_is_normalised_lowercase(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    store = auth.UserStore()
    store.create("MixedCase@Club.ORG", "longenough123")
    # Lookup is case-insensitive; the stored key is lowercased.
    assert store.get("mixedcase@club.org") is not None
    assert store.exists("MIXEDCASE@CLUB.ORG") is True
    # Authentication is case-insensitive on the email.
    assert store.authenticate("MIXEDCASE@club.org", "longenough123").email == "mixedcase@club.org"


def test_authenticate_wrong_password_raises_autherror(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    store = auth.UserStore()
    store.create("c@club.org", "correcthorse1")
    with pytest.raises(auth.AuthError):
        store.authenticate("c@club.org", "wrongpassword")
    with pytest.raises(auth.AuthError):
        store.authenticate("ghost@club.org", "whatever12345")  # unknown email


def test_set_plan_and_customer_id(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web import auth

    store = auth.UserStore()
    store.create("p@club.org", "longenough123")
    updated = store.set_plan("p@club.org", "club", stripe_customer_id="cus_123")
    assert updated is not None
    assert updated.plan == "club"
    assert updated.stripe_customer_id == "cus_123"
    # Re-read coalesces to the latest record.
    assert store.get("p@club.org").plan == "club"
    assert store.find_by_customer_id("cus_123").email == "p@club.org"
    # Unknown plan strings coerce back to free (defensive).
    assert store.set_plan("p@club.org", "garbage").plan == "free"


# ---- route-level integration tests -------------------------------------


def test_signup_creates_user_hashes_and_logs_in(client, tmp_path):
    r = client.post(
        "/signup",
        data={"email": "coach@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    # Redirects into the app and sets a session cookie.
    assert r.status_code == 302
    assert "/make" in r.headers["Location"]
    set_cookie = "\n".join(v for k, v in r.headers if k == "Set-Cookie")
    assert "session=" in set_cookie
    # HttpOnly is set on the session cookie.
    assert "HttpOnly" in set_cookie

    # Ledger holds a bcrypt hash, never the plaintext.
    ledger = _users_file(tmp_path).read_text()
    rec = json.loads(ledger.splitlines()[0])
    assert rec["email"] == "coach@club.org"
    assert rec["plan"] == "free"
    assert rec["hashed_password"].startswith("$2b$")
    assert "twelvechars1" not in ledger


def test_signup_duplicate_shows_clean_error_not_500(client):
    client.post("/signup", data={"email": "dup@club.org", "password": "twelvechars1", "accept_terms": "1"})
    # Fresh client (no session) re-signing up the same email.
    r = client.post("/signup", data={"email": "dup@club.org", "password": "twelvechars1", "accept_terms": "1"})
    assert r.status_code == 400  # clean rejection, not a crash
    assert b"already exists" in r.data


def test_login_logout_round_trip(client):
    client.post("/signup", data={"email": "rt@club.org", "password": "twelvechars1", "accept_terms": "1"})
    # Log out, then the create page should no longer treat us as the account.
    client.get("/logout")
    # Log back in.
    r = client.post("/login", data={"email": "rt@club.org", "password": "twelvechars1"})
    assert r.status_code == 302
    assert "/make" in r.headers["Location"]


def test_login_wrong_password_is_clean_error_not_500(client):
    client.post("/signup", data={"email": "wp@club.org", "password": "twelvechars1", "accept_terms": "1"})
    client.get("/logout")
    r = client.post("/login", data={"email": "wp@club.org", "password": "WRONGWRONG"})
    # A wrong password is a clean 401, never a 500.
    assert r.status_code == 401
    assert b"Incorrect email or password" in r.data


def test_login_unknown_email_is_clean_error(client):
    r = client.post("/login", data={"email": "ghost@club.org", "password": "twelvechars1"})
    assert r.status_code == 401
    # Same generic message as wrong-password (no account enumeration).
    assert b"Incorrect email or password" in r.data


def test_unauthenticated_billing_redirects_to_login(client):
    r = client.get("/billing")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_session_cookie_is_httponly_and_signed(app, client):
    # HttpOnly configured; Secure off in test/dev (so HTTP cookies survive).
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    r = client.post("/signup", data={"email": "sec@club.org", "password": "twelvechars1", "accept_terms": "1"})
    set_cookie = "\n".join(v for k, v in r.headers if k == "Set-Cookie")
    assert "HttpOnly" in set_cookie
    # The signed cookie value is itimsdangerous-tagged, not the raw email.
    assert "sec@club.org" not in set_cookie


def test_signup_redirects_authenticated_user_away(client):
    client.post("/signup", data={"email": "again@club.org", "password": "twelvechars1", "accept_terms": "1"})
    # Visiting /signup or /login while already signed in bounces into the app.
    r = client.get("/signup")
    assert r.status_code == 302
    r = client.get("/login")
    assert r.status_code == 302


def test_pages_render_for_anonymous_visitor(client):
    # The auth pages themselves must render without an account / org.
    assert client.get("/signup").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/pricing").status_code == 200


# ---- cross-account isolation on the commercial surface (PC.1/PC.2) ------
#
# With billing configured, /billing renders an account panel showing the
# *current* signed-in account's email + plan. This regression locks the
# invariant that one account never sees another account's email, plan, or
# Stripe customer id — the commercial-surface analogue of the cross-tenant
# run-isolation invariant (ADR-0003).


@pytest.fixture
def billing_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Obviously-fake Stripe placeholders (never real secrets) so
    # billing_configured() is True and /billing renders the account panel
    # instead of the "not configured" stub. These are test fixtures only.
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder_not_a_real_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_placeholder")
    monkeypatch.setenv("STRIPE_PRICE_CLUB", "price_club_test")
    monkeypatch.setenv("STRIPE_PRICE_FEDERATION", "price_federation_test")
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    application._data_dir = tmp_path  # for tests that read the ledger
    return application


@pytest.fixture
def billing_client(billing_app):
    return billing_app.test_client()


def test_billing_does_not_leak_another_accounts_plan(billing_client):
    from mediahub.web import auth

    # --- Account B: a premium CLUB subscriber with a Stripe customer id. ---
    b_email = "owner-b@premium-federation.example"
    b_customer_id = "cus_ISOLATIONLEAKB999"
    billing_client.post("/signup", data={"email": b_email, "password": "twelvechars1", "accept_terms": "1"})
    # Stamp B onto the paid Club plan via the REAL auth API (no invented names).
    store = auth.UserStore()
    updated = store.set_plan(b_email, auth.PLAN_CLUB, stripe_customer_id=b_customer_id)
    assert updated is not None and updated.plan == auth.PLAN_CLUB
    # Log B out so the next request is a clean session for a different account.
    billing_client.get("/logout")

    # --- Account A: a brand-new Free user. ---
    a_email = "viewer-a@grassroots.example"
    billing_client.post("/signup", data={"email": a_email, "password": "twelvechars1", "accept_terms": "1"})

    r = billing_client.get("/billing")
    assert r.status_code == 200
    html = r.data.decode()

    # A sees their own identity and Free plan label...
    assert a_email in html
    # The plan-value markup is matched specifically (the bare word "Club"
    # appears in an unrelated JS comment in the shared layout, so only the
    # rendered plan cell is a real leak signal).
    assert 'margin-top:4px">Free</div>' in html
    # ...and never B's email, B's Club plan, or B's Stripe customer id.
    assert b_email not in html
    assert b_customer_id not in html
    assert 'margin-top:4px">Club</div>' not in html
    # B's plan label ("Club") must not surface in A's rendered plan cell.
    assert auth.plan_label(auth.PLAN_CLUB) == "Club"
