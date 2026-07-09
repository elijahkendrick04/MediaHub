"""C-16 — the interface language must be switchable deliberately, with an off-ramp.

The UI locale could only be changed by hand-typing ?lang=cy, which pinned to the
session with no visible way back to English. There's now a visible interface-
language switcher (footer on every page + a Settings card) that POSTs to a route
setting session['ui_lang'], with English always an option (the off-ramp), and it
returns to the same page.
"""

from __future__ import annotations

import importlib
import re

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_switcher_renders_in_footer(client):
    html = client.get("/activity").get_data(as_text=True)
    assert 'name="ui_lang"' in html
    assert "Cymraeg (Welsh)" in html
    assert "English" in html


def test_settings_has_interface_language_card(client):
    html = client.get("/settings").get_data(as_text=True)
    assert "Interface language" in html
    # It's explicitly distinguished from caption output.
    assert "caption-output language is set" in html


def test_set_welsh_then_english_off_ramp(client):
    # Switch to Welsh — the chrome uses the Welsh catalogue (nav home = "Hafan").
    # The switcher returns the user via the Referer, not an echoed form field.
    r = client.post(
        "/settings/interface-language",
        data={"ui_lang": "cy"},
        headers={"Referer": "http://localhost/activity"},
    )
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/activity")
    html = client.get("/activity").get_data(as_text=True)
    assert "Hafan" in html  # nav.home in Welsh — the interface really switched

    # Off-ramp: switch back to English.
    client.post(
        "/settings/interface-language",
        data={"ui_lang": "en"},
        headers={"Referer": "http://localhost/activity"},
    )
    html2 = client.get("/activity").get_data(as_text=True)
    assert "Hafan" not in html2


def test_invalid_locale_is_ignored(client):
    client.post("/settings/interface-language", data={"ui_lang": "cy"})
    # A bogus code doesn't change or crash the pin.
    client.post("/settings/interface-language", data={"ui_lang": "zz"})
    with client.session_transaction() as s:
        assert s.get("ui_lang") == "cy"


def test_referer_open_redirect_is_blocked(client):
    # An off-site Referer is never honoured — falls back to Settings.
    r = client.post(
        "/settings/interface-language",
        data={"ui_lang": "en"},
        headers={"Referer": "https://evil.example/x"},
    )
    assert r.status_code == 302
    assert "evil.example" not in r.headers["Location"]
    assert r.headers["Location"].endswith("/settings")


def test_backslash_path_referer_is_blocked(client):
    # A same-origin Referer whose path is protocol-relative-ish (/\ or //) must
    # not be used verbatim — browsers resolve "/\host" as "//host" (off-site).
    for bad in ("http://localhost/\\evil.com", "http://localhost//evil.com"):
        r = client.post(
            "/settings/interface-language",
            data={"ui_lang": "en"},
            headers={"Referer": bad},
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert loc.endswith("/settings"), f"unsafe redirect to {loc!r}"


def test_switcher_does_not_echo_request_path(client):
    # The switcher must not echo the current request path into the page — the
    # path can carry PII in its segments (a swimmer name), and the footer renders
    # on every page including foreign 404s (run-route isolation invariant).
    html = client.get("/spotlight/some-run/Jane%20Doe").get_data(as_text=True)
    assert "Jane Doe" not in html
    assert 'name="next"' not in html


# ---------------------------------------------------------------------------
# Regression: the switcher must work through the REAL app gates.
#
# The tests above run under plain TESTING, where BOTH the org-setup gate and
# CSRF are disabled — which is exactly why a production break went unnoticed.
# The switcher renders in the footer of every page (including the signed-out
# home, where a Welsh-speaking prospect would use it), but set_interface_language
# was NOT in _SETUP_EXEMPT_ENDPOINTS, so a visitor with no ready organisation had
# their POST intercepted by the org-setup gate (302 -> /organisation/setup) and
# the language never changed — the visible control silently failed. These tests
# enforce the gate (and CSRF) so that class of bug cannot recur.
# ---------------------------------------------------------------------------


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """Client with the org-setup gate ENFORCED and no active organisation — the
    real signed-out-visitor scenario the footer switcher must serve."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    return app.test_client()


def test_switch_works_for_signed_out_visitor_through_the_gate(gated_client):
    # No active org, gate enforced (the public-home footer scenario). The POST
    # must reach the handler, switch the locale, and return to the same page —
    # NOT get bounced into /organisation/setup or /sign-in.
    r = gated_client.post(
        "/settings/interface-language",
        data={"ui_lang": "cy"},
        headers={"Referer": "http://localhost/"},
    )
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "/organisation/setup" not in loc and "/sign-in" not in loc
    assert loc.endswith("/")
    # The chrome really switched: the signed-out home nav is now Welsh.
    html = gated_client.get("/").get_data(as_text=True)
    assert "Hafan" in html  # nav.home in Welsh
    assert '<html lang="cy"' in html


def test_switcher_form_carries_a_working_csrf_token(tmp_path, monkeypatch):
    # Under real CSRF enforcement, the rendered switcher <form> must carry a
    # token the server accepts — otherwise the control 403s in production even
    # though the plain-TESTING tests (CSRF off) pass.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_CSRF"] = True
    client = app.test_client()
    with client.session_transaction() as s:
        s["active_profile_id"] = "club-a"

    # A token-less POST is rejected (proves CSRF really is enforced here).
    r_no_tok = client.post("/settings/interface-language", data={"ui_lang": "cy"})
    assert r_no_tok.status_code == 403

    # The token auto-injected into the rendered switcher form is accepted.
    page = client.get("/activity").get_data(as_text=True)
    m = re.search(
        r"<form[^>]*interface-language[^>]*>\s*"
        r'<input[^>]*name="csrf_token"[^>]*value="([a-f0-9]+)"',
        page,
    )
    assert m, "switcher form is missing an auto-injected csrf_token"
    token = m.group(1)
    r_ok = client.post(
        "/settings/interface-language",
        data={"ui_lang": "cy", "csrf_token": token},
        headers={"Referer": "http://localhost/activity"},
    )
    assert r_ok.status_code == 302
    assert r_ok.headers["Location"].endswith("/activity")
