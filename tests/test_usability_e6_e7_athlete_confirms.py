"""E-6 / E-7 — the two irreversible /athletes actions must confirm, and
enforcement must preview its club-wide impact.

E-6: "Same swimmer twice?" fused two swimmers' entire race histories with no
confirmation and no undo. The merge form now confirms, naming both swimmers
(the option text carries each one's race count).

E-7: "Switch enforcement on" blocked every athlete with no consent on file with
one unconfirmed click. Enabling now confirms and shows the impact
("N of M athletes have no consent and would be blocked"); switching it off (only
unblocks) needs no confirm.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def athletes_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_merge_form_confirms(athletes_client):
    html = athletes_client.get("/athletes").get_data(as_text=True)
    assert 'onsubmit="return athMergeConfirm(this)"' in html
    assert "function athMergeConfirm(f)" in html
    # The confirm names both swimmers (from the selected option text).
    assert "keep.options[keep.selectedIndex].text" in html
    assert "cannot be undone" in html


def test_enforce_toggle_confirms_only_when_enabling(athletes_client):
    html = athletes_client.get("/athletes").get_data(as_text=True)
    assert 'onsubmit="return athEnforceConfirm(this)"' in html
    assert "function athEnforceConfirm(f)" in html
    # A fresh club has no regime yet → about to enable → data-enforcing=1 + impact.
    assert 'data-enforcing="1"' in html
    assert "would be blocked from all content" in html
    # Impact is a real count of 0 of 0 with an empty roster (honest, not invented).
    assert "0 of 0 athletes have no" in html
