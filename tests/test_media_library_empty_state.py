"""QA-009 — an org with no media must see a clean empty state, not an error.

Repro: an organisation that has never uploaded media (e.g. a brand-new club on
a fresh data volume) opens ``/media-library``. The asset DB is created lazily
on first write, so on a not-yet-provisioned / read-only deployment volume the
very first read can RAISE (sqlite can't open a file that was never created)
rather than return an empty list.

The page used to treat *any* read failure as "the store wasn't readable —
check the data volume", which is alarming and wrong for the common "nobody has
uploaded here yet" case. These tests pin the corrected behaviour:

  * store read fails but the DB file is NOT on disk  -> clean empty state
  * the store can't even be constructed + no DB file -> clean empty state
  * the DB file IS on disk but won't read (corrupt)  -> recovery message kept

The discriminator is "is the DB file actually on disk?" — missing-but-fine vs
genuinely-corrupt.
"""

from __future__ import annotations

import sqlite3

import pytest

# Distinctive fragments of each rendered state (HTML entities stripped to the
# ASCII-safe core so the match doesn't depend on &rsquo;/&mdash; encoding).
_ERROR_SENTINEL = "load library assets"  # the "store wasn't readable" message
# The clean empty state — since M33 (Phase E) it is the three-step
# get-photos-onto-cards onboarding checklist, not a bare "no assets" line.
_EMPTY_SENTINEL = "photos onto cards in three steps"


@pytest.fixture
def org_app(web_module, tmp_path):
    """A fresh Flask app with one saved profile, all storage under tmp_path.

    DATA_DIR isolation + one-time web.py import come from the autouse
    ``_isolate_data_dir`` fixture in conftest.py."""
    app = web_module.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    # Echo the QA repro: a real-named club with zero uploaded assets.
    save_profile(ClubProfile(profile_id="swansea", display_name="Swansea University Swimming Team"))

    return app, tmp_path


def _get_library(app):
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "swansea"})
        resp = c.get("/media-library")
    return resp, resp.get_data(as_text=True)


def test_missing_store_renders_empty_state_not_error(org_app, monkeypatch):
    """list() raises but the DB file was never created -> clean empty state."""
    app, tmp_path = org_app
    import mediahub.web.web as wm

    missing_db = tmp_path / "never_created" / "assets.db"  # guaranteed absent

    class _MissingStore:
        db_path = missing_db

        def list(self, **_kw):
            # Mirrors sqlite failing to open a DB that was never created on a
            # not-yet-provisioned / read-only data volume.
            raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(wm, "_v8_get_media_store", lambda: _MissingStore())

    resp, body = _get_library(app)
    assert resp.status_code == 200
    assert not missing_db.exists()  # sanity: the file really is absent
    assert _ERROR_SENTINEL not in body, (
        "an org with no media store yet must NOT see the alarming "
        "'store wasn't readable / check the data volume' message"
    )
    assert _EMPTY_SENTINEL in body, "an org with no media store yet must see the clean empty state"


def test_store_construction_failure_with_no_db_renders_empty_state(org_app, monkeypatch):
    """get_store() itself raises (e.g. can't create dirs on a read-only code
    dir) AND the default DB file is absent -> clean empty state.

    This is the real production path on Render: the media store's default DB
    lives in the (read-only) application directory, so the first call can't
    construct the store at all.
    """
    app, tmp_path = org_app
    import mediahub.web.web as wm
    import mediahub.media_library.store as ml_store

    def _boom():
        raise OSError("Read-only file system")

    monkeypatch.setattr(wm, "_v8_get_media_store", _boom)
    # Point the fallback default DB at a path that does not exist, mirroring a
    # deploy where the DB was never (and could never be) created.
    monkeypatch.setattr(ml_store, "_default_db_path", lambda: tmp_path / "absent" / "data.db")

    resp, body = _get_library(app)
    assert resp.status_code == 200
    assert _ERROR_SENTINEL not in body, (
        "a deployment where the media store can't be constructed and has no "
        "DB on disk must render the empty state, not the recovery error"
    )
    assert _EMPTY_SENTINEL in body


def test_genuinely_corrupt_store_still_shows_recovery_message(org_app, monkeypatch):
    """The DB file IS on disk but won't read -> keep the recovery message.

    Guards the discriminator's other side: a real corruption must not be
    silently hidden behind a misleading empty state.
    """
    app, tmp_path = org_app
    import mediahub.web.web as wm

    corrupt_db = tmp_path / "corrupt.db"
    corrupt_db.write_bytes(b"this is not a sqlite database at all")  # exists, unreadable

    class _CorruptStore:
        db_path = corrupt_db

        def list(self, **_kw):
            raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(wm, "_v8_get_media_store", lambda: _CorruptStore())

    resp, body = _get_library(app)
    assert resp.status_code == 200
    assert corrupt_db.exists()  # sanity: the file really is present
    assert _ERROR_SENTINEL in body, (
        "a genuinely corrupt/unreadable store (DB file present but invalid) "
        "must still surface the 'check the data volume' recovery message"
    )
