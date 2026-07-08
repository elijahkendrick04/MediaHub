"""D-19 — a consent/records import must report WHICH rows failed, not just a
count.

The import copy promises "Rows we can't read are reported, never guessed", but
feedback was a single toast — "Imported 188. Skipped 12." — never saying which.
For a safeguarding consent register that silently leaves specific swimmers with
no permission on file and no way to find them. The skipped rows (line + name +
reason) are now listed on the page after import.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _client(app, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = pid
    return c


def test_consent_import_lists_skipped_rows(app_env):
    c = _client(app_env)
    # One unreadable level → skipped, with the swimmer named.
    r = c.post(
        "/athletes/action",
        data={"action": "import_consent", "csv_text": "Ada Lovelace,platinum-vip"},
    )
    assert r.status_code == 302
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "couldn&rsquo;t be imported" in html
    assert "Ada Lovelace" in html
    assert "unrecognised level" in html
    # One-shot: it doesn't persist to the next visit.
    assert "Ada Lovelace" not in c.get("/athletes").get_data(as_text=True)


def test_records_import_lists_skipped_rows(app_env):
    c = _client(app_env)
    # Too few columns → skipped with its row number.
    r = c.post(
        "/records/action",
        data={"action": "import", "csv_text": "50 Free,LC"},
    )
    assert r.status_code == 302
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "couldn&rsquo;t be imported" in html
    assert "Row 1" in html
