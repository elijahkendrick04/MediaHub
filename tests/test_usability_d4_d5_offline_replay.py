"""D-4 & D-5 — offline approval replay must not silently discard server
refusals/holds, and must drain on load for browsers without Background Sync.

D-4: the service worker deleted every queued approval on any response below 500
— including a 403 consent/brand/task block or a 200 "held for another approver"
vote — and the pill then flashed "All changes synced", silently losing the
volunteer's approval intent. drainQueue now inspects each replay's body and
reports refusals/holds; the client shows a "review needed" state.

D-5: iOS Safari has no Background Sync, so an app reopened while already online
stranded the queue. The client now drains on load when online and offers a
"Sync now" control.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.web as wm

    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.secret_key = app.secret_key or "test-secret"
    return app.test_client()


# --- D-4: the service worker inspects replay outcomes ------------------------


def test_sw_inspects_replay_body_not_just_status(client):
    sw = client.get("/sw.js").get_data(as_text=True)
    # Transient failures kept; final decisions inspected via the JSON body.
    assert "res.status >= 500" in sw
    assert "res.clone().json()" in sw
    # A 4xx gate refusal or a body ok:false is a block; a differing status is a hold.
    assert "res.status >= 400" in sw
    assert "j.status !== requested" in sw


def test_sw_collects_and_reports_problems(client):
    sw = client.get("/sw.js").get_data(as_text=True)
    assert "problems.push" in sw
    assert "notifyClients(problems)" in sw
    # The queue message now carries the problem list to the client.
    assert "problems: problems || []" in sw


def test_client_surfaces_replay_problems_not_false_synced(client):
    js = client.get("/static/js/offline-queue.js").get_data(as_text=True)
    assert "review needed" in js
    assert "couldn't be saved" in js
    assert 'data-state="problem"' in client.get("/").get_data(as_text=True)


# --- D-5: drain on load + manual Sync now ------------------------------------


def test_client_drains_on_load_when_online(client):
    js = client.get("/static/js/offline-queue.js").get_data(as_text=True)
    # On serviceWorker.ready, an online client nudges a replay immediately.
    assert 'navigator.onLine) ping("mediahub-queue-replay")' in js


def test_client_offers_sync_now_button(client):
    js = client.get("/static/js/offline-queue.js").get_data(as_text=True)
    assert "Sync now" in js
    assert "mh-oq-sync" in js
    # The button style ships inline via theme-components.css.
    assert "mh-oq-sync" in client.get("/").get_data(as_text=True)
