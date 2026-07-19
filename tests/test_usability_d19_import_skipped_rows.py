"""D-19 — a consent/records import must report WHICH rows failed, not just a
count.

The import copy promises "Rows we can't read are reported, never guessed", but
feedback was a single toast — "Imported 188. Skipped 12." — never saying which.
For a safeguarding consent register that silently leaves specific swimmers with
no permission on file and no way to find them. The skipped rows (line + name +
reason) are now listed on the page after import.
"""

from __future__ import annotations


def _client(app, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = pid
    return c


def test_consent_import_lists_skipped_rows(app):
    c = _client(app)
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


def test_records_import_lists_skipped_rows(app):
    c = _client(app)
    # Too few columns → skipped with its row number.
    r = c.post(
        "/records/action",
        data={"action": "import", "csv_text": "50 Free,LC"},
    )
    assert r.status_code == 302
    html = c.get(r.headers["Location"]).get_data(as_text=True)
    assert "couldn&rsquo;t be imported" in html
    assert "Row 1" in html
