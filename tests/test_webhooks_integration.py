"""1.21 webhooks — end-to-end through the app.

Proves the event chokepoints actually fire: approving a card (via the public
API) enqueues a signed delivery to a subscribed endpoint, and the API webhook
CRUD is scope-gated and tenant-isolated.
"""

from __future__ import annotations

import json
import sqlite3

import pytest


def _seed_run(runs_dir, db_path, run_id, profile_id):
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": profile_id,
        "meet_name": "Gala",
        "meet": {"name": "Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": {"swim_id": "swim-1", "swimmer_name": "Alice"}}
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name) "
        "VALUES (?,?,?,?,?)",
        (run_id, "2026-06-01T00:00:00Z", "done", profile_id, "Gala"),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def world(web_module, tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.api_public import _db as api_db
    from mediahub.webhooks import _db as wh_db

    api_db._initialized.clear()
    wh_db._initialized.clear()

    # Deliver synchronously + capture, so the assertion is deterministic.
    from mediahub.webhooks import delivery

    sent = []
    monkeypatch.setattr(
        delivery, "_http_post", lambda url, body, headers: (sent.append((url, headers)) or (200, None))
    )

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A SC"))

    app = web_module.create_app()
    app.config["TESTING"] = True

    from mediahub.api_public.tokens import ApiTokenStore

    class W:
        client = app.test_client()

        @staticmethod
        def token(scopes):
            _t, secret = ApiTokenStore().create("org-a", scopes=list(scopes), created_by="o@x.com")
            return {"Authorization": f"Bearer {secret}"}

        seed = staticmethod(lambda rid: _seed_run(tmp_path / "runs_v4", tmp_path / "data.db", rid, "org-a"))

    return W()


def test_approving_a_card_fires_the_webhook(world):
    # Register an endpoint subscribed to card.approved.
    h_manage = world.token(["webhooks:manage"])
    r = world.client.post(
        "/api/v1/webhooks", headers=h_manage, json={"url": "https://ex.com/h", "events": ["card.approved"]}
    )
    endpoint_id = r.get_json()["id"]

    # Approve a card via the API.
    world.seed("runwebhook01")
    h_approve = world.token(["cards:approve"])
    ar = world.client.post(
        "/api/v1/runs/runwebhook01/cards/swim-1/approve", headers=h_approve
    )
    assert ar.status_code == 200

    # A delivery row was enqueued for the endpoint (created synchronously in emit).
    h_read = world.token(["webhooks:read"])
    deliveries = world.client.get(
        f"/api/v1/webhooks/{endpoint_id}/deliveries", headers=h_read
    ).get_json()
    assert deliveries["count"] == 1
    assert deliveries["deliveries"][0]["event"] == "card.approved"


def test_webhook_crud_is_scope_gated(world):
    read_only = world.token(["webhooks:read"])
    # Cannot create with only read.
    assert (
        world.client.post(
            "/api/v1/webhooks", headers=read_only, json={"url": "https://x.com", "events": []}
        ).status_code
        == 403
    )
    # Listing is fine with read.
    assert world.client.get("/api/v1/webhooks", headers=read_only).status_code == 200


def test_webhook_is_tenant_isolated(world):
    h_manage = world.token(["webhooks:manage"])
    wid = world.client.post(
        "/api/v1/webhooks", headers=h_manage, json={"url": "https://ex.com/h", "events": ["run.finished"]}
    ).get_json()["id"]

    # A token for another org cannot see or delete it.
    from mediahub.api_public.tokens import ApiTokenStore

    _t, secret = ApiTokenStore().create("org-b", scopes=["webhooks:read", "webhooks:manage"], created_by="b@x.com")
    other = {"Authorization": f"Bearer {secret}"}
    assert world.client.get(f"/api/v1/webhooks/{wid}", headers=other).status_code == 404
    assert world.client.delete(f"/api/v1/webhooks/{wid}", headers=other).status_code == 404
