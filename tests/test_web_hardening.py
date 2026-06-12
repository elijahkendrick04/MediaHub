"""security/web-hardening: headers, CSRF, error pages (THREAT_MODEL §6)."""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def strict_client(app):
    app.config["ENFORCE_CSRF"] = True
    return app.test_client()


# ---------------------------------------------------------------- headers


def test_security_headers_on_every_page(client):
    for path in ("/", "/privacy", "/complaints", "/legal/subprocessors"):
        r = client.get(path)
        h = r.headers
        assert "Content-Security-Policy" in h, path
        csp = h["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "form-action 'self'" in csp
        assert h.get("X-Content-Type-Options") == "nosniff"
        assert h.get("X-Frame-Options") == "DENY"
        assert h.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in h


def test_hsts_only_when_secure_cookies(app, client):
    r = client.get("/privacy")
    assert "Strict-Transport-Security" not in r.headers  # http test context
    app.config["SESSION_COOKIE_SECURE"] = True
    r = client.get("/privacy")
    assert "max-age=31536000" in r.headers.get("Strict-Transport-Security", "")


def test_wall_embed_keeps_frame_permission(client):
    r = client.get("/wall/some-token/embed")
    # whatever the status (404 for a bogus token), the embed surface must
    # not carry the global frame refusal
    assert r.headers.get("X-Frame-Options") != "DENY"
    assert "frame-ancestors *" in r.headers.get("Content-Security-Policy", "")
    r2 = client.get("/privacy")
    assert r2.headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in r2.headers.get("Content-Security-Policy", "")


# ------------------------------------------------------------------ CSRF


def test_csrf_token_injected_into_post_forms(client):
    r = client.get("/complaints")
    html = r.data.decode()
    m = re.search(r'name="csrf_token" value="([0-9a-f]{32})"', html)
    assert m, "every rendered POST form carries the hidden CSRF token"


def test_csrf_blocks_form_post_without_token(strict_client):
    r = strict_client.post(
        "/complaints",
        data={"name": "A", "contact": "a@b.c", "details": "no token"},
    )
    assert r.status_code == 403


def test_csrf_allows_form_post_with_token(strict_client):
    page = strict_client.get("/complaints")
    token = re.search(r'name="csrf_token" value="([0-9a-f]{32})"', page.data.decode()).group(1)
    r = strict_client.post(
        "/complaints",
        data={
            "csrf_token": token,
            "name": "A",
            "contact": "a@b.c",
            "details": "with token",
        },
    )
    assert r.status_code == 200


def test_csrf_exempts_json_posts(strict_client):
    # a cross-site form cannot send application/json without a preflight,
    # so JSON APIs authenticate via SameSite session + content-type
    r = strict_client.post("/api/workflow/nope/c1", json={"action": "set_status"})
    assert r.status_code != 403  # not CSRF-rejected (404/503 are fine)


def test_csrf_exempts_signature_verified_webhook(strict_client):
    r = strict_client.post("/webhooks/stripe", data="{}", content_type="application/json")
    assert r.status_code != 403 or b"csrf" not in r.data.lower()


def test_csrf_rejections_logged(strict_client, tmp_path):
    strict_client.post("/complaints", data={"details": "x", "contact": "y"})
    from mediahub.compliance.security_log import read_events

    assert any(e["event"] == "csrf_rejected" for e in read_events())


# ------------------------------------------------------------ error pages


def test_500_page_is_generic_no_traceback(app):
    @app.route("/_boom_test_route")
    def _boom():
        raise RuntimeError("secret internal detail abc123")

    # An org must exist + be pinned (with an idle stamp) so the org-setup
    # gate doesn't 302 us away before the route raises.
    import time

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="err-org", display_name="Err Org", brand_voice_summary="x")
    )
    app.config["TESTING"] = False  # let the errorhandler run
    app.config["PROPAGATE_EXCEPTIONS"] = False
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "err-org"
        sess["login_seen_at"] = int(time.time())
    r = client.get("/_boom_test_route")
    assert r.status_code == 500
    assert b"abc123" not in r.data  # no internal detail
    assert b"Traceback" not in r.data
    r_api = client.get("/_boom_test_route", headers={"Accept": "application/json"})
    assert r_api.get_json() == {"error": "internal_error"}


def test_404_page_is_branded_not_default(client):
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404
    assert b"Werkzeug" not in r.data


# ----------------------------------------------------- autoescape position


def test_fstring_templates_escape_user_content():
    """The monolith's templating is f-strings + _h() (markupsafe.escape),
    not Jinja files — so the autoescape audit is: user-influenced values
    pass through _h(). Spot-pinned end-to-end by the complaints XSS test
    (test_compliance_complaints) and the caption escaping in web.py; this
    test asserts the helper itself escapes."""
    from mediahub.web.web import _h

    assert str(_h("<script>alert(1)</script>")) == "&lt;script&gt;alert(1)&lt;/script&gt;"
