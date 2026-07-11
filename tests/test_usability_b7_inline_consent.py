"""B-7 — consent is no longer one athlete at a time with a full reload per save.

The /athletes roster now saves permissions inline: the per-row dropdown
auto-saves via a JSON endpoint (POST /api/athletes/consent) with a row-level
"Saved" tick and an MH.toast — no page reload, scroll preserved — and a bulk
bar ("Apply permission to selected…") posts once for every ticked swimmer.
The old /athletes/action form post stays as the no-JS fallback. The endpoint
is tenant-gated: an id that isn't on the active organisation's roster 404s.
"""

from __future__ import annotations

import importlib

import pytest

ORG = "club-a"
FOREIGN_ORG = "club-b"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club A"))
    save_profile(ClubProfile(profile_id=FOREIGN_ORG, display_name="Club B"))
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c


def _seed_roster(profile_id, names):
    from mediahub.athletes import get_or_create

    return [get_or_create(profile_id, n) for n in names]


# ---------------------------------------------------------------- endpoint


def test_single_inline_save_updates_consent(client):
    (maya,) = _seed_roster(ORG, ["Maya Patel"])
    r = client.post(
        "/api/athletes/consent",
        json={"athlete_id": maya.athlete_id, "level": "initials_only"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["updated"] == 1
    assert body["label"] == "Initials only, no photos"

    from mediahub.safeguarding import list_consent

    assert list_consent(ORG)[maya.athlete_id]["level"] == "initials_only"


def test_bulk_apply_updates_every_selected_athlete(client):
    roster = _seed_roster(ORG, ["Maya Patel", "Joe Bloggs", "Eira Hughes"])
    ids = [a.athlete_id for a in roster]
    r = client.post("/api/athletes/consent", json={"athlete_ids": ids, "level": "no_photo"})
    assert r.status_code == 200
    assert r.get_json()["updated"] == 3

    from mediahub.safeguarding import list_consent

    consent = list_consent(ORG)
    assert all(consent[aid]["level"] == "no_photo" for aid in ids)


def test_invalid_level_and_empty_selection_rejected(client):
    (maya,) = _seed_roster(ORG, ["Maya Patel"])
    r = client.post(
        "/api/athletes/consent", json={"athlete_ids": [maya.athlete_id], "level": "bogus"}
    )
    assert r.status_code == 400
    # The "unknown" pseudo-level cannot be set manually either.
    r = client.post("/api/athletes/consent", json={"athlete_ids": [maya.athlete_id], "level": ""})
    assert r.status_code == 400
    r = client.post("/api/athletes/consent", json={"athlete_ids": [], "level": "full"})
    assert r.status_code == 400
    r = client.post("/api/athletes/consent", json={"athlete_ids": "not-a-list", "level": "full"})
    assert r.status_code == 400

    from mediahub.safeguarding import list_consent

    assert list_consent(ORG) == {}


def test_anonymous_session_refused(client):
    (maya,) = _seed_roster(ORG, ["Maya Patel"])
    with client.session_transaction() as s:
        s.clear()
    r = client.post(
        "/api/athletes/consent", json={"athlete_ids": [maya.athlete_id], "level": "full"}
    )
    assert r.status_code == 403


def test_foreign_org_athlete_id_404s_and_writes_nothing(client):
    """Tenant isolation: an id from another organisation's roster 404s the
    whole request — including when smuggled into a mixed bulk list."""
    (own,) = _seed_roster(ORG, ["Maya Patel"])
    (foreign,) = _seed_roster(FOREIGN_ORG, ["Other Club Kid"])

    r = client.post(
        "/api/athletes/consent", json={"athlete_ids": [foreign.athlete_id], "level": "full"}
    )
    assert r.status_code == 404

    r = client.post(
        "/api/athletes/consent",
        json={"athlete_ids": [own.athlete_id, foreign.athlete_id], "level": "full"},
    )
    assert r.status_code == 404

    from mediahub.safeguarding import list_consent

    # Nothing written anywhere — not even the caller's own athlete.
    assert list_consent(ORG) == {}
    assert list_consent(FOREIGN_ORG) == {}


# ---------------------------------------------------------------- page UI


def test_roster_page_carries_inline_and_bulk_ui(client):
    _seed_roster(ORG, ["Maya Patel"])
    html = client.get("/athletes").get_data(as_text=True)
    # Per-row: enhanced form + saved tick; the form post is kept as fallback.
    assert 'class="mh-consent-form"' in html
    assert 'name="action" value="set_consent"' in html
    assert "mh-consent-tick" in html
    # Bulk bar: checkboxes, select-all, one select + Apply.
    assert 'id="mh-consent-bulk"' in html
    assert "Apply permission to selected" in html
    assert 'id="mh-consent-check-all"' in html
    assert 'class="mh-consent-check"' in html
    # The enhancement script posts to the JSON endpoint.
    assert "/api/athletes/consent" in html
    # Summary toast copy lives in the script ("Updated 43 swimmers").
    assert "swimmers." in html


def test_form_post_fallback_still_works(client):
    (maya,) = _seed_roster(ORG, ["Maya Patel"])
    r = client.post(
        "/athletes/action",
        data={"action": "set_consent", "athlete_id": maya.athlete_id, "level": "full"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Consent updated" in r.data

    from mediahub.safeguarding import list_consent

    assert list_consent(ORG)[maya.athlete_id]["level"] == "full"


# ------------------------------------------------------- CON2-4 (follow-up)


def test_set_consent_many_is_all_or_nothing(tmp_path, monkeypatch):
    """CON2-4 — one connection, one transaction: a failure on the Nth upsert
    rolls back every earlier row and re-raises; a clean run lands everything
    and returns the count."""
    import sqlite3

    import mediahub.safeguarding.consent as consent

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db = tmp_path / "consent.db"
    consent.set_consent("org", "a1", "full", db_path=db)

    calls = {"n": 0}
    real_now = consent._now

    def _flaky_now():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise sqlite3.OperationalError("disk I/O error")
        return real_now()

    monkeypatch.setattr(consent, "_now", _flaky_now)
    with pytest.raises(sqlite3.OperationalError):
        consent.set_consent_many("org", ["a1", "a2", "a3"], "no_photo", db_path=db)
    monkeypatch.setattr(consent, "_now", real_now)

    rows = consent.list_consent("org", db_path=db)
    assert rows["a1"]["level"] == "full"  # the already-executed upsert rolled back
    assert "a2" not in rows and "a3" not in rows

    assert consent.set_consent_many("org", ["a1", "a2"], "initials_only", db_path=db) == 2
    rows = consent.list_consent("org", db_path=db)
    assert rows["a1"]["level"] == "initials_only"
    assert rows["a2"]["level"] == "initials_only"


def test_bulk_failure_mid_way_writes_nothing(client, monkeypatch):
    """CON2-4 — the bulk endpoint is transactional: a mid-batch failure
    returns an honest error and leaves every row exactly as it was."""
    import sqlite3

    import mediahub.safeguarding.consent as consent

    roster = _seed_roster(ORG, ["Maya Patel", "Joe Bloggs", "Eira Hughes"])
    ids = [a.athlete_id for a in roster]
    assert client.post(
        "/api/athletes/consent", json={"athlete_ids": ids, "level": "full"}
    ).get_json()["updated"] == 3

    calls = {"n": 0}
    real_now = consent._now

    def _flaky_now():
        calls["n"] += 1
        if calls["n"] >= 3:
            raise sqlite3.OperationalError("disk I/O error")
        return real_now()

    monkeypatch.setattr(consent, "_now", _flaky_now)
    r = client.post("/api/athletes/consent", json={"athlete_ids": ids, "level": "no_photo"})
    assert r.status_code == 500
    assert "nothing was changed" in (r.get_json().get("error") or "").lower()
    monkeypatch.setattr(consent, "_now", real_now)

    from mediahub.safeguarding import list_consent

    rows = list_consent(ORG)
    assert all(rows[aid]["level"] == "full" for aid in ids)


def test_single_save_path_keeps_set_consent(client, monkeypatch):
    """The one-row save still goes through set_consent (same audit shape)."""
    import mediahub.safeguarding as safeguarding

    (maya,) = _seed_roster(ORG, ["Maya Patel"])

    def _no_bulk(*a, **kw):
        raise AssertionError("single saves must not use set_consent_many")

    # The route imports from the package namespace, so patch it there.
    monkeypatch.setattr(safeguarding, "set_consent_many", _no_bulk)
    r = client.post(
        "/api/athletes/consent", json={"athlete_id": maya.athlete_id, "level": "no_photo"}
    )
    assert r.status_code == 200 and r.get_json()["updated"] == 1
