"""UK legal baseline — the MEDIAHUB_RETENTION_DAYS setting (Privacy Notice §8).

The single global window read by the Privacy page and used as a ceiling by
the compliance purge (``mediahub.compliance.retention.run_purge`` — covered
in tests/test_retention_minimisation.py). Unset/0 = disabled, matching the
documented default.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_retention_days_parsing(monkeypatch):
    from mediahub.privacy.retention import retention_days

    monkeypatch.delenv("MEDIAHUB_RETENTION_DAYS", raising=False)
    assert retention_days() == 0
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "90")
    assert retention_days() == 90
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "-5")
    assert retention_days() == 0
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "junk")
    assert retention_days() == 0


def test_privacy_page_states_retention(data_dir, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setenv("MEDIAHUB_RETENTION_DAYS", "60")
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    client = app.test_client()
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="sharks", display_name="Sharks"))
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "sharks"
        sess["login_seen_at"] = 2**62
    html = client.get("/privacy").get_data(as_text=True)
    assert "older than 60 days are deleted daily" in html
