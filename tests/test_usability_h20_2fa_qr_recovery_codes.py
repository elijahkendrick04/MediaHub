"""H-20: 2FA setup gets a QR code, a copyable secret, and one-time recovery codes.

- the enrolment page renders the otpauth URI as an inline QR (the secret never
  sits on a fetchable URL) plus a copy button for the raw secret, and is
  served Cache-Control: no-store
- enabling issues 8 one-time recovery codes shown exactly once; the ledger
  stores only salted argon2id hashes, never the plaintext
- a recovery code logs in at /login/2fa in place of a TOTP code and is
  consumed on use (single-use)
- the settings page shows the remaining-codes count and a regenerate action
  gated on a valid current TOTP code (same bar as disabling)
- old account records without the recovery_codes field still load fine
"""

from __future__ import annotations

import json
import re
import time

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web import auth as auth_mod
    from mediahub.web.web import create_app

    # lockout + TOTP replay state are process-global — isolate per test
    auth_mod._failed_logins.clear()
    auth_mod._totp_last_counter.clear()
    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


EMAIL = "coach@club.org"
PASSWORD = "twelvechars1"
# Recovery codes are uppercase hex grouped XXXX-XXXX. CSRF tokens are
# lowercase hex and inline colours carry no dash, so this cannot false-match.
CODE_RE = re.compile(r"\b[0-9A-F]{4}-[0-9A-F]{4}\b")


def _signup(client):
    return client.post(
        "/signup", data={"email": EMAIL, "password": PASSWORD, "accept_terms": "1"}
    )


def _totp_now(secret, step_offset=0):
    from mediahub.web.auth import _totp_code

    return _totp_code(secret, int(time.time() // 30) + step_offset)


def _enable_2fa(client):
    """GET the setup page (plants the secret), confirm with a valid code.

    Returns (secret, plaintext_recovery_codes_shown).
    """
    r = client.get("/account/2fa")
    assert r.status_code == 200
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    r = client.post("/account/2fa", data={"action": "enable", "totp": _totp_now(secret)})
    assert r.status_code == 200
    codes = CODE_RE.findall(r.get_data(as_text=True))
    return secret, codes, r


def _ledger_record(tmp_path, email=EMAIL):
    """Latest ledger record for the email (last line wins, like UserStore)."""
    rec = None
    for line in (tmp_path / "users.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("email") == email:
            rec = d
    return rec


# ------------------------------------------------------------- setup page


def test_setup_page_has_qr_copy_button_and_no_store(client):
    from mediahub.web import qr as qr_mod

    _signup(client)
    r = client.get("/account/2fa")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    with client.session_transaction() as sess:
        secret = sess["totp_setup_secret"]
    # secret stays visible as a copyable fallback, with a copy button
    assert secret in text
    assert 'data-copy-target="totp-setup-secret"' in text
    # the otpauth URI is rendered as an inline QR (no secret-bearing URL)
    if qr_mod.is_available():
        assert "<svg" in text
        assert "otpauth://" in text
    # a page carrying the raw secret must never be cached
    assert r.headers.get("Cache-Control") == "no-store"


# ---------------------------------------------------------- recovery codes


def test_enable_shows_codes_once_and_stores_only_hashes(client, tmp_path):
    _signup(client)
    _, codes, resp = _enable_2fa(client)
    assert len(codes) == 8
    text = resp.get_data(as_text=True)
    assert 'data-copy-target="recovery-codes"' in text  # copy-all
    assert "only time they are shown" in text  # plain warning
    assert resp.headers.get("Cache-Control") == "no-store"

    # ledger: salted hashes only — the plaintext never touches disk
    rec = _ledger_record(tmp_path)
    assert rec["totp_secret"]
    assert len(rec["recovery_codes"]) == 8
    assert all(h.startswith("$argon2id$") for h in rec["recovery_codes"])
    ledger_text = (tmp_path / "users.jsonl").read_text()
    for code in codes:
        assert code not in ledger_text
        assert code.replace("-", "") not in ledger_text

    # shown exactly once: the settings page shows a count, not the codes
    r = client.get("/account/2fa")
    text = r.get_data(as_text=True)
    assert not CODE_RE.findall(text)
    assert "<strong>8</strong>" in text
    assert "Regenerate recovery codes" in text


def test_recovery_code_logs_in_and_is_single_use(client, tmp_path):
    _signup(client)
    _, codes, _ = _enable_2fa(client)

    # password alone parks the login on the second-factor step
    client.get("/logout")
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 302 and "/login/2fa" in r.headers["Location"]

    # a recovery code (case-insensitive) logs in exactly like a TOTP success
    r = client.post("/login/2fa", data={"totp": codes[0].lower()})
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("user_email") == EMAIL

    # consumed on use: 7 left, and the same code never works again
    r = client.get("/account/2fa")
    assert "<strong>7</strong>" in r.get_data(as_text=True)
    client.get("/logout")
    client.post("/login", data={"email": EMAIL, "password": PASSWORD})
    r = client.post("/login/2fa", data={"totp": codes[0]})
    assert r.status_code == 401
    # a different unused code still works
    r = client.post("/login/2fa", data={"totp": codes[1]})
    assert r.status_code == 302


def test_regenerate_requires_valid_code_and_replaces_set(client, tmp_path):
    _signup(client)
    secret, old_codes, _ = _enable_2fa(client)

    # a wrong code re-renders the settings page with the error — nothing changes
    r = client.post("/account/2fa", data={"action": "regenerate", "totp": "999999"})
    assert r.status_code == 400
    assert len(_ledger_record(tmp_path)["recovery_codes"]) == 8

    # a valid current code (next step — the enable consumed this one) issues
    # a fresh show-once set of 8
    r = client.post(
        "/account/2fa", data={"action": "regenerate", "totp": _totp_now(secret, 1)}
    )
    assert r.status_code == 200
    new_codes = CODE_RE.findall(r.get_data(as_text=True))
    assert len(new_codes) == 8
    assert r.headers.get("Cache-Control") == "no-store"

    # the old set is dead; the new set works
    client.get("/logout")
    client.post("/login", data={"email": EMAIL, "password": PASSWORD})
    r = client.post("/login/2fa", data={"totp": old_codes[0]})
    assert r.status_code == 401
    r = client.post("/login/2fa", data={"totp": new_codes[0]})
    assert r.status_code == 302


def test_disable_clears_recovery_codes(client, tmp_path):
    _signup(client)
    secret, _, _ = _enable_2fa(client)
    r = client.post(
        "/account/2fa", data={"action": "disable", "totp": _totp_now(secret, 1)}
    )
    assert r.status_code == 302
    rec = _ledger_record(tmp_path)
    assert rec["totp_secret"] == ""
    assert rec["recovery_codes"] == []


# ------------------------------------------------------------- back-compat


def test_old_account_records_without_field_load_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.auth import User, UserStore, hash_password

    # a pre-H-20 record has no recovery_codes key at all
    (tmp_path / "users.jsonl").write_text(
        json.dumps(
            {
                "email": "old@club.org",
                "hashed_password": hash_password("twelvechars1"),
                "plan": "free",
            }
        )
        + "\n"
    )
    user = UserStore().authenticate("old@club.org", "twelvechars1")
    assert user.recovery_codes == []
    assert User.from_record({"email": "a@b.co", "hashed_password": "x"}).recovery_codes == []
    # and a consume attempt on an account with no codes is a clean False
    assert UserStore().consume_recovery_code("old@club.org", "ABCD-1234") is False
