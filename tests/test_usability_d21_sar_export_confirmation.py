"""D-21 — running a SAR export must visibly action the request.

"Run export" streamed a JSON attachment and marked the request complete
server-side, but returned no redirect — so the officer stayed on the old table
where the request still showed open with the same buttons, with no confirmation.
It now redirects back with a success flash (request flips to completed, clock
stopped) and offers the export via a persistent download link.
"""

from __future__ import annotations

import importlib
import json

import pytest

ATHLETE = "Eira Hughes"


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

    save_profile(ClubProfile(profile_id="clubx", display_name="Club X"))
    app = wm.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "x"
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "clubx"
    return c


def _open_access(client):
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": ATHLETE, "request_type": "access"},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    return DsrRequestLog().all(profile_id="clubx")[0].id


def test_run_export_redirects_and_completes(client):
    rid = _open_access(client)
    r = client.post(f"/organisation/athlete-rights/{rid}/run")
    assert r.status_code == 302  # redirect back, not a dead-end attachment
    from mediahub.compliance.dsr import DsrRequestLog

    assert DsrRequestLog().get(rid).status == "completed"
    # A success flash is queued for the refreshed page.
    with client.session_transaction() as s:
        assert "request marked complete" in ((s.get("mh_toast") or {}).get("msg") or "")


def test_completed_request_offers_working_download(client):
    rid = _open_access(client)
    client.post(f"/organisation/athlete-rights/{rid}/run")
    page = client.get("/organisation/athlete-rights").get_data(as_text=True)
    assert f"/organisation/athlete-rights/{rid}/export.json" in page
    dl = client.get(f"/organisation/athlete-rights/{rid}/export.json")
    assert dl.status_code == 200 and dl.mimetype == "application/json"
    export = json.loads(dl.data)
    assert export["athlete_name"] == ATHLETE
    assert "attachment" in dl.headers.get("Content-Disposition", "")


def test_export_download_is_tenant_scoped(client):
    rid = _open_access(client)
    client.post(f"/organisation/athlete-rights/{rid}/run")
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="other", display_name="Other"))
    with client.session_transaction() as s:
        s["active_profile_id"] = "other"
    assert client.get(f"/organisation/athlete-rights/{rid}/export.json").status_code == 404
