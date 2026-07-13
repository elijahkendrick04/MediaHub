"""1.21 public API — the /api/v1 blueprint end-to-end.

Covers auth (bearer), scope enforcement, tenant isolation / IDOR, the
consent-gate parity on approval, rate limiting, and the read/write surface.
Uses the same reload-with-temp-DATA_DIR isolation the rest of the web suite uses.
"""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest


def _seed_run(runs_dir, db_path, run_id, profile_id, *, approved=False):
    """Write a run JSON + a runs-table row so the API can read it."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": profile_id,
        "meet_name": "Spring Gala 2026",
        "meet": {"name": "Spring Gala 2026"},
        "our_swim_count": 2,
        "recognition_report": {
            "n_achievements": 2,
            "ranked_achievements": [
                {
                    "id": "ra-1",
                    "rank": 1,
                    "priority_score": 0.9,
                    "post_angle": "pb",
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Alice Smith",
                        "event": "100m Freestyle",
                        "time": "59.10",
                        "type": "official_pb_confirmed",
                        "confidence": 0.98,
                    },
                },
                {
                    "id": "ra-2",
                    "rank": 2,
                    "achievement": {"swim_id": "swim-2", "swimmer_name": "Bob Jones"},
                },
            ],
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, "
        "our_swims, n_achievements) VALUES (?,?,?,?,?,?,?)",
        (run_id, "2026-06-01T00:00:00Z", "done", profile_id, "Spring Gala 2026", 2, 2),
    )
    conn.commit()
    conn.close()
    if approved:
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        WorkflowStore(runs_dir).set_status(run_id, "swim-1", CardStatus.APPROVED)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.api_public import _db as api_db

    api_db._initialized.clear()

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-a", display_name="Org A SC"))
    save_profile(ClubProfile(profile_id="org-b", display_name="Org B SC"))

    wm.app.config["TESTING"] = True
    runs_dir = tmp_path / "runs_v4"
    db_path = tmp_path / "data.db"

    from mediahub.api_public.tokens import ApiTokenStore

    store = ApiTokenStore()

    def mint(profile_id="org-a", scopes=("runs:read", "cards:read")):
        _t, secret = store.create(profile_id, name="t", scopes=list(scopes), created_by="o@org.com")
        return secret

    class W:
        client = wm.app.test_client()
        seed = staticmethod(lambda rid, pid="org-a", **kw: _seed_run(runs_dir, db_path, rid, pid, **kw))
        token = staticmethod(mint)

    return W()


def _h(secret):
    return {"Authorization": f"Bearer {secret}"}


# --- public + auth ----------------------------------------------------------
def test_public_endpoints_need_no_token(world):
    assert world.client.get("/api/v1/health").status_code == 200
    assert world.client.get("/api/v1/").status_code == 200
    assert world.client.get("/api/v1/openapi.json").status_code == 200


def test_missing_token_is_401(world):
    r = world.client.get("/api/v1/runs")
    assert r.status_code == 401
    assert r.get_json()["error"] == "unauthorized"
    assert "Bearer" in r.headers.get("WWW-Authenticate", "")


def test_bad_token_is_401(world):
    r = world.client.get("/api/v1/runs", headers=_h("mhk_nope"))
    assert r.status_code == 401


def test_me_reports_scopes(world):
    tok = world.token(scopes=["runs:read", "cards:approve"])
    body = world.client.get("/api/v1/me", headers=_h(tok)).get_json()
    assert body["profile_id"] == "org-a"
    assert set(body["scopes"]) == {"runs:read", "cards:approve"}


# --- scopes -----------------------------------------------------------------
def test_scope_is_enforced(world):
    tok = world.token(scopes=["runs:read"])  # lacks brand:read
    r = world.client.get("/api/v1/brand-kits", headers=_h(tok))
    assert r.status_code == 403
    assert r.get_json()["error"] == "insufficient_scope"
    assert r.get_json()["required_scope"] == "brand:read"


# --- reads + tenant isolation ----------------------------------------------
def test_list_runs_is_tenant_scoped(world):
    world.seed("runaaaaaaaa1", "org-a")
    world.seed("runbbbbbbbb1", "org-b")
    tok = world.token("org-a", scopes=["runs:read"])
    runs = world.client.get("/api/v1/runs", headers=_h(tok)).get_json()["runs"]
    ids = {r["id"] for r in runs}
    assert "runaaaaaaaa1" in ids and "runbbbbbbbb1" not in ids


def test_get_other_orgs_run_is_404(world):
    world.seed("runbbbbbbbb2", "org-b")
    tok = world.token("org-a", scopes=["runs:read"])
    r = world.client.get("/api/v1/runs/runbbbbbbbb2", headers=_h(tok))
    assert r.status_code == 404  # anti-enumeration: not 403


def test_get_run_and_cards(world):
    world.seed("runaaaaaaaa3", "org-a")
    tok = world.token("org-a", scopes=["runs:read", "cards:read"])
    run = world.client.get("/api/v1/runs/runaaaaaaaa3", headers=_h(tok)).get_json()
    assert run["meet_name"] == "Spring Gala 2026"
    cards = world.client.get("/api/v1/runs/runaaaaaaaa3/cards", headers=_h(tok)).get_json()
    assert cards["count"] == 2
    one = world.client.get("/api/v1/runs/runaaaaaaaa3/cards/swim-1", headers=_h(tok)).get_json()
    assert one["swimmer_name"] == "Alice Smith"


def test_cards_status_filter(world):
    world.seed("runaaaaaaaa4", "org-a", approved=True)
    tok = world.token("org-a", scopes=["cards:read"])
    approved = world.client.get(
        "/api/v1/runs/runaaaaaaaa4/cards?status=approved", headers=_h(tok)
    ).get_json()
    assert [c["id"] for c in approved["cards"]] == ["swim-1"]


# --- approval (the gated write) --------------------------------------------
def test_approve_card(world):
    world.seed("runaaaaaaaa5", "org-a")
    tok = world.token("org-a", scopes=["cards:approve"])
    r = world.client.post("/api/v1/runs/runaaaaaaaa5/cards/swim-1/approve", headers=_h(tok))
    assert r.status_code == 200
    assert r.get_json()["status"] == "approved"


def test_approve_needs_approve_scope(world):
    world.seed("runaaaaaaaa6", "org-a")
    tok = world.token("org-a", scopes=["cards:read"])
    r = world.client.post("/api/v1/runs/runaaaaaaaa6/cards/swim-1/approve", headers=_h(tok))
    assert r.status_code == 403


def test_approve_runs_consent_gate(world, monkeypatch):
    """The API approval path must honour the SAME consent gate as the UI."""
    import mediahub.compliance.gate as gate

    monkeypatch.setattr(
        gate, "consent_block_reason_for_card", lambda pid, card: "Athlete has not consented."
    )
    world.seed("runaaaaaaaa7", "org-a")
    tok = world.token("org-a", scopes=["cards:approve"])
    r = world.client.post("/api/v1/runs/runaaaaaaaa7/cards/swim-1/approve", headers=_h(tok))
    assert r.status_code == 403
    assert r.get_json()["error"] == "consent_blocked"


def test_cannot_approve_another_orgs_card(world):
    world.seed("runbbbbbbbb8", "org-b")
    tok = world.token("org-a", scopes=["cards:approve"])
    r = world.client.post("/api/v1/runs/runbbbbbbbb8/cards/swim-1/approve", headers=_h(tok))
    assert r.status_code == 404


def test_bearer_api_is_csrf_exempt(world):
    """A bearer-token POST must not be blocked by the session CSRF guard, even
    with CSRF enforcement on (the production posture)."""
    world.client.application.config["ENFORCE_CSRF"] = True
    try:
        world.seed("runaaaaaaa11", "org-a")
        tok = world.token("org-a", scopes=["cards:approve"])
        # Empty body (no JSON content-type) + no CSRF token: must reach the route.
        r = world.client.post(
            "/api/v1/runs/runaaaaaaa11/cards/swim-1/approve", headers=_h(tok)
        )
        assert r.status_code == 200
        assert r.get_json().get("error") != "csrf"
    finally:
        world.client.application.config["ENFORCE_CSRF"] = False


def test_reject_and_edit(world):
    world.seed("runaaaaaaaa9", "org-a")
    tok = world.token("org-a", scopes=["cards:approve", "cards:write"])
    assert (
        world.client.post(
            "/api/v1/runs/runaaaaaaaa9/cards/swim-1/reject", headers=_h(tok)
        ).get_json()["status"]
        == "rejected"
    )
    r = world.client.patch(
        "/api/v1/runs/runaaaaaaaa9/cards/swim-1",
        headers=_h(tok),
        json={"edits": {"headline": "Custom"}},
    )
    assert r.status_code == 200 and r.get_json()["status"] == "edited"


def test_api_approval_is_stamped_as_machine_originated(world):
    """Finding #116: a public-API/MCP token approval is recorded as
    machine-originated — ``api-token:<id>`` in the durable workflow state AND in
    the approval telemetry (via=api) — so it can never be mistaken for a human's
    sign-off. (MCP wraps this same route, so it stamps identically.)"""
    import os
    from pathlib import Path

    from mediahub.api_public.tokens import ApiTokenStore
    from mediahub.observability import approval_telemetry
    from mediahub.workflow.store import WorkflowStore

    world.seed("runactor0001", "org-a")
    tok, secret = ApiTokenStore().create(
        "org-a", name="agent", scopes=["cards:approve"], created_by="owner@org-a.com"
    )
    r = world.client.post("/api/v1/runs/runactor0001/cards/swim-1/approve", headers=_h(secret))
    assert r.status_code == 200

    # Durable per-card record: the token, not a bare human email.
    state = WorkflowStore(Path(os.environ["RUNS_DIR"])).load("runactor0001")["swim-1"]
    assert state.actor == f"api-token:{tok.id}"
    assert state.actor.startswith("api-token:")

    # Approval telemetry: same machine actor, recorded as an API action.
    conn = approval_telemetry._connect()
    try:
        row = conn.execute(
            "SELECT via, actor FROM approval_events "
            "WHERE run_id=? AND card_id=? AND action='approved'",
            ("runactor0001", "swim-1"),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["via"] == "api"
    assert row["actor"] == f"api-token:{tok.id}"


# --- export -----------------------------------------------------------------
def test_export_without_visuals_is_404(world):
    world.seed("runaaaaaaa10", "org-a")
    tok = world.token("org-a", scopes=["content:export"])
    r = world.client.get("/api/v1/runs/runaaaaaaa10/export", headers=_h(tok))
    assert r.status_code == 404  # honest: nothing rendered yet


# --- brand + data -----------------------------------------------------------
def test_brand_kits_and_data_tables(world):
    tok = world.token("org-a", scopes=["brand:read", "data:read"])
    kits = world.client.get("/api/v1/brand-kits", headers=_h(tok)).get_json()
    assert kits["count"] >= 1  # synthesised primary kit always present
    tables = world.client.get("/api/v1/data/tables", headers=_h(tok)).get_json()
    assert "tables" in tables


# --- rate limiting ----------------------------------------------------------
def test_rate_limit_returns_429(world, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "2")
    tok = world.token("org-a", scopes=["runs:read"])
    codes = [world.client.get("/api/v1/runs", headers=_h(tok)).status_code for _ in range(3)]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429


def test_rate_limit_headers_present(world):
    tok = world.token("org-a", scopes=["runs:read"])
    r = world.client.get("/api/v1/runs", headers=_h(tok))
    assert r.headers.get("X-RateLimit-Limit")
    assert r.headers.get("X-RateLimit-Remaining") is not None
