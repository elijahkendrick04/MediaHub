"""Roadmap 1.22 — offline-tolerant approval queue (build 2).

The service worker intercepts approve / reject / caption-edit POSTs to
``/api/workflow/``; offline it stashes them in IndexedDB and replays them via
Background Sync when the connection returns. Because the workflow API is
idempotent, replay is always safe.

Coverage:
  * the served service worker carries the full queue machinery (interception,
    IndexedDB store, Background Sync, idempotent drain, 202 "queued" response,
    client message protocol) while preserving the network-first GET shell;
  * the client indicator script + global queue-aware approval handler + the
    indicator CSS are wired into the page;
  * a functional check that the workflow API is genuinely idempotent, so the
    SW's replay can't double-apply or error.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def sw_body(client):
    return client.get("/sw.js").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Service worker: queue machinery
# ---------------------------------------------------------------------------


def test_sw_intercepts_workflow_posts(sw_body):
    assert "/api/workflow/" in sw_body
    assert "handleWorkflowPost" in sw_body
    # Only POSTs to the workflow API are queued; everything else keeps shell behaviour.
    assert "req.method === 'POST'" in sw_body and "WF_RX.test" in sw_body


def test_sw_persists_to_indexeddb(sw_body):
    assert "indexedDB.open" in sw_body
    assert "approval-queue" in sw_body  # object store name
    for fn in ("idbAdd", "idbGetAll", "idbDelete"):
        assert fn in sw_body


def test_sw_registers_background_sync(sw_body):
    assert "mediahub-approval-queue" in sw_body  # the sync tag
    assert "sync.register" in sw_body
    assert "addEventListener('sync'" in sw_body


def test_sw_returns_queued_202_when_offline(sw_body):
    assert "queued: true" in sw_body
    assert "status: 202" in sw_body


def test_sw_drain_is_idempotent_safe(sw_body):
    """A 5xx/network error keeps the entry for the next sync (transient); a final
    server decision drops it — so replay never loops or double-errors."""
    assert "drainQueue" in sw_body
    # Transient failures are kept and retried; only final decisions are dropped.
    assert "res.status >= 500" in sw_body
    assert "idbDelete(it.id)" in sw_body


def test_sw_client_message_protocol(sw_body):
    assert "addEventListener('message'" in sw_body
    assert "mediahub-queue-status" in sw_body
    assert "mediahub-queue-replay" in sw_body
    assert "notifyClients" in sw_body


def test_sw_preserves_network_first_get_shell(sw_body):
    # The existing invariant: GETs try the network before ever touching cache.
    assert "await fetch(req)" in sw_body
    assert sw_body.index("await fetch(req)") < sw_body.index("caches.match")
    # The offline page now reassures the volunteer their work is safe.
    assert "sync when you reconnect" in sw_body.lower()


# ---------------------------------------------------------------------------
# Client wiring: indicator script, queue-aware handler, CSS
# ---------------------------------------------------------------------------


def test_offline_queue_client_script_served(client):
    body = client.get("/static/js/offline-queue.js").get_data(as_text=True)
    assert "mediahub-queue" in body
    assert 'addEventListener("online"' in body or "addEventListener('online'" in body
    assert "mediahub-queue-replay" in body
    assert "mediahub-queue-status" in body


def test_pages_load_offline_queue_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "js/offline-queue.js" in html


def test_approval_handler_is_queue_aware(client):
    """The global [data-mh-wf] handler distinguishes a queued (offline) result
    from a live success so the volunteer gets honest feedback."""
    html = client.get("/").get_data(as_text=True)
    assert "result.queued" in html
    assert "Saved offline" in html


def test_indicator_css_present(client):
    # BASE_CSS folds in theme-components.css, so the pill rule ships inline.
    html = client.get("/").get_data(as_text=True)
    assert "#mh-offline-queue" in html


# ---------------------------------------------------------------------------
# Functional: the API the replay depends on is idempotent
# ---------------------------------------------------------------------------


@pytest.fixture
def approval_world(app, web_module, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A",
            brand_voice_summary="Bold, energetic, club-focused.",
        )
    )

    run_id = "run-a-" + uuid.uuid4().hex[:8]
    payload = {
        "run_id": run_id,
        "profile_id": "org-a",
        "profile_display": "Org A",
        "meet": {"name": "Spring Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-a-1",
                        "swimmer_name": "A Athlete",
                        "event": "100m freestyle",
                        "headline": "A PB",
                    },
                    "safe_to_post": {"level": "safe"},
                }
            ],
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = web_module._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-a", "Spring Gala", "a.hy3"),
    )
    conn.commit()
    conn.close()

    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "org-a"})
    return c, run_id, "swim-a-1"


def test_workflow_approve_is_idempotent_for_safe_replay(approval_world):
    """Replaying a queued approval must be a no-op on the second apply — never a
    double-count or an error — which is exactly what makes SW replay safe."""
    c, run_id, card_id = approval_world
    url = f"/api/workflow/{run_id}/{card_id}"
    body = {"action": "set_status", "status": "approved"}

    r1 = c.post(url, json=body)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    j1 = r1.get_json()
    assert j1.get("ok") is True and j1.get("status") == "approved"

    # The SW would replay the identical request on reconnect.
    r2 = c.post(url, json=body)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    j2 = r2.get_json()
    assert j2.get("ok") is True and j2.get("status") == "approved"

    # Idempotent: still exactly one approved card, no error, no double-apply.
    assert j2["summary"]["approved"] == 1
    assert j1["summary"]["approved"] == j2["summary"]["approved"]
