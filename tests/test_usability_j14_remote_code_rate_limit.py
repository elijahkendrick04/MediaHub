"""J-14 — the slide-remote rate limit must never lock out a correct code.

Failed pairing-code lookups were throttled at 20/5min keyed on client IP alone,
and the limit was checked BEFORE the code lookup — so a venue behind one NAT
could be locked out entirely, and even someone holding the CORRECT code was
refused with "Too many attempts". Now: the lookup runs first (a valid code
always connects); confirmed-wrong attempts are throttled per (client IP,
submitted code) with a generous per-IP ceiling as the enumeration backstop;
and the "Too many attempts" page shows the actual wait time instead of an
immediately-retryable dead loop.
"""

from __future__ import annotations

import importlib

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
    if not wm._documents_ok:
        pytest.skip("documents feature not available")
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app.test_client()


def _mk_session():
    from mediahub.documents import presenter

    return presenter.create_session("docJ14", 3, owner="club-a")


def _spam_wrong(client, code: str, n: int) -> None:
    for _ in range(n):
        client.get(f"/remote/{code}")


# --- a correct code always connects ------------------------------------------


def test_correct_code_connects_despite_exhausted_failure_history(client):
    s = _mk_session()
    # Burn well past the per-code budget on a wrong code from this IP.
    _spam_wrong(client, "WRONGA", 25)
    # The wrong code is now limited…
    assert client.get("/remote/WRONGA").status_code == 429
    # …but the CORRECT code still connects: lookup happens before the throttle.
    r = client.get(f"/remote/{s.pairing_code}")
    assert r.status_code == 200
    assert "Too many wrong code attempts" not in r.get_data(as_text=True)
    # And the action API drives the deck too.
    act = client.post(f"/api/remote/{s.pairing_code}/action", json={"action": "next"})
    assert act.status_code == 200
    assert act.get_json()["state"]["current"] == 1


# --- throttle is keyed per (IP, code), not per IP alone -----------------------


def test_wrong_code_spam_does_not_block_a_different_code(client):
    _spam_wrong(client, "WRONGA", 25)
    assert client.get("/remote/WRONGA").status_code == 429
    # A different wrong code from the same IP is still a plain "Code not
    # found" — one member's typo-hammering doesn't burn the venue budget.
    r = client.get("/remote/WRONGB")
    assert r.status_code == 404
    assert "Code not found" in r.get_data(as_text=True)


def test_per_ip_ceiling_still_trips_as_enumeration_backstop(client):
    # 100 distinct wrong codes (each under the per-code budget) trip the
    # per-IP ceiling, so brute-force enumeration is still braked.
    for i in range(100):
        client.get(f"/remote/ENUM{i:02d}")
    r = client.get("/remote/FRESHX")
    assert r.status_code == 429
    # Even then, a correct code connects.
    s = _mk_session()
    assert client.get(f"/remote/{s.pairing_code}").status_code == 200


# --- the limited page shows the actual wait -----------------------------------


def test_limited_page_shows_retry_after_and_no_instant_retry_loop(client):
    _spam_wrong(client, "WRONGA", 25)
    r = client.get("/remote/WRONGA")
    assert r.status_code == 429
    html = r.get_data(as_text=True)
    assert "Too many" in html
    assert "wait about" in html and "minute" in html
    # The CTA is "check again in about N minutes" (reload), not an instant
    # "Try again" loop straight back to code entry.
    assert "Check again in about" in html
    assert ">Try again<" not in html


def test_limited_api_returns_retry_after(client):
    _spam_wrong(client, "WRONGA", 25)
    r = client.post("/api/remote/WRONGA/action", json={"action": "next"})
    assert r.status_code == 429
    j = r.get_json()
    assert j["error"] == "rate_limited"
    assert isinstance(j["retry_after_s"], int) and j["retry_after_s"] >= 1
    assert r.headers.get("Retry-After") == str(j["retry_after_s"])
