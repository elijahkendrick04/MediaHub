"""D-35 — close the silent-feedback gaps around auth and the progress page.

- A password reset logged the user in and redirected with no confirmation.
- Signup fired a verification email but never told the user one was sent (so
  most accounts never verified).
- The 8-minute pipeline progress page framed staying on the page as the
  mechanism, with an ambiguous "View on home" as the only escape.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import time

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
    if not app.secret_key:
        app.secret_key = "x"
    from mediahub.web.auth import UserStore

    UserStore().create("coach@club.org", "original-password-1")
    return {"app": app, "wm": wm}


@pytest.fixture
def outbox(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MEDIAHUB_EMAIL_FROM", "MediaHub <no-reply@example.org>")
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append(json)
        return _Resp(200)

    monkeypatch.setattr("requests.post", fake_post)
    return sent


def _wait(box, n, timeout=3.0):
    deadline = time.time() + timeout
    while len(box) < n and time.time() < deadline:
        time.sleep(0.01)
    return box


def test_password_reset_flashes_confirmation(app_world, outbox):
    app = app_world["app"]
    c = app.test_client()
    c.post("/password/forgot", data={"email": "coach@club.org"})
    _wait(outbox, 1)
    body = "\n".join(str(m) for m in outbox)
    link = "/password/reset/" + re.search(r"/password/reset/(\S+?)[\\\"\s]", body).group(1)
    r = c.post(link, data={"password": "brand-new-password-9"})
    assert r.status_code == 302
    with c.session_transaction() as s:
        toast = s.get("mh_toast") or {}
    assert "Password updated" in (toast.get("msg") or "")


def test_signup_flashes_verification_notice(app_world, outbox):
    app = app_world["app"]
    c = app.test_client()
    r = c.post(
        "/signup",
        data={"email": "newcoach@club.org", "password": "a-strong-password-1", "accept_terms": "1"},
    )
    assert r.status_code == 302
    with c.session_transaction() as s:
        toast = s.get("mh_toast") or {}
    msg = toast.get("msg") or ""
    assert "Account created" in msg
    assert "verification link" in msg and "newcoach@club.org" in msg


def test_signup_without_email_seam_gives_honest_flash(app_world):
    app = app_world["app"]
    c = app.test_client()
    r = c.post(
        "/signup",
        data={"email": "noseat@club.org", "password": "a-strong-password-1", "accept_terms": "1"},
    )
    assert r.status_code == 302
    with c.session_transaction() as s:
        toast = s.get("mh_toast") or {}
    msg = toast.get("msg") or ""
    # No email seam → account confirmed, but NO false "we sent a link" claim.
    assert "Account created" in msg
    assert "verification link" not in msg


def test_progress_page_reassures_run_survives_leaving():
    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert "You can leave this page" in src
    assert "it finishes on Home" in src
    assert "the run keeps going on our server" in src
