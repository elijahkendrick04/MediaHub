"""tests/test_sign_in_next_destination.py — org re-entry resumes the page the
user was heading to (audit finding A-6).

When the idle timeout drops the org pin, the next navigation is bounced to the
sign-in picker. Previously the picker always redirected home, so a volunteer
who opened a deep link to a run/review page had to re-navigate from scratch.
The gate now threads a same-site ?next= through the picker and sign_in_post
resumes it (validated by the existing open-redirect guard).
"""

from __future__ import annotations

import pytest

from mediahub.web.club_profile import ClubProfile, save_profile


@pytest.fixture
def env(app):
    # Seed a ready, unbound (membership-free => usable by anyone) profile so
    # the gate bounces to the picker rather than to first-run setup.
    prof = ClubProfile(profile_id="otters", display_name="Otters SC")
    prof.brand_palette_manual = {"primary": "#123456"}
    save_profile(prof)
    assert prof.is_ready()

    app.config["ENFORCE_ORG_GATE"] = True
    return app


def test_gate_threads_next_into_picker(env):
    with env.test_client() as c:
        r = c.get("/season")  # a gated content page, no active pin
        assert r.status_code in (301, 302)
        loc = r.headers["Location"]
        assert "/sign-in" in loc
        assert "next=" in loc and "%2Fseason" in loc or "/season" in loc, loc


def test_picker_carries_next_hidden_field(env):
    with env.test_client() as c:
        r = c.get("/sign-in?next=/season")
        assert r.status_code == 200
        body = r.data.decode()
        assert 'name="next"' in body and "/season" in body


def test_sign_in_resumes_next(env):
    with env.test_client() as c:
        r = c.post("/sign-in", data={"profile_id": "otters", "next": "/season"})
        assert r.status_code in (301, 302)
        assert r.headers["Location"].endswith("/season"), r.headers["Location"]


def test_sign_in_without_next_still_goes_home(env):
    with env.test_client() as c:
        r = c.post("/sign-in", data={"profile_id": "otters"})
        assert r.status_code in (301, 302)
        assert (
            r.headers["Location"].rstrip("/").endswith("")
            and "/season" not in r.headers["Location"]
        )


def test_next_rejects_offsite_redirect(env):
    """The open-redirect guard drops an absolute/off-site next."""
    with env.test_client() as c:
        r = c.post("/sign-in", data={"profile_id": "otters", "next": "https://evil.example/x"})
        assert r.status_code in (301, 302)
        assert "evil.example" not in r.headers["Location"]
