"""tests/test_cross_tenant_access.py — cross-tenant data isolation.

Regression coverage for the tenant-isolation audit. Every resource that
identifies its owning organisation must refuse direct access from a
different organisation's session — and crucially, destructive routes
(``/privacy/run/<id>/delete``, ``/drafts/<id>/delete``) must no-op
instead of obliterating another org's data.

Each test seeds Alpha-owned data, pins Beta into the session, and hits
Alpha's URLs. The expected outcome is "not found" (404 or empty body),
never the leaked content. Then we re-pin Alpha to prove the owner still
gets her own data — i.e. the fix didn't lock the legitimate user out.
"""
from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixture: two orgs, one Alpha-owned run + draft pack, fresh DATA_DIR.
# ---------------------------------------------------------------------------

@pytest.fixture
def two_orgs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="org-alpha", display_name="Org Alpha",
        brand_voice_summary="Bold, energetic, club-focused.",
    ))
    save_profile(ClubProfile(
        profile_id="org-beta", display_name="Org Beta",
        brand_voice_summary="Calm and considered.",
    ))

    # Alpha-owned run JSON + matching DB row so /review, /pack, /privacy
    # can all find it.
    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    run_payload = {
        "run_id": run_id,
        "profile_id": "org-alpha",
        "profile_display": "Org Alpha",
        "meet": {"name": "SECRET ALPHA INVITATIONAL"},
        "cards": [{
            "card_id": "card-alpha-1",
            "swim_id": "swim-alpha-1",
            "swimmer_name": "Alpha Athlete",
            "event": "100m freestyle",
            "headline": "Alpha-only PB",
            "id": "card-alpha-1",
        }],
        "trust": {"score": 0.92},
        "recognition_report": {
            "ranked_achievements": [{
                "achievement": {
                    "swim_id": "swim-alpha-1",
                    "swimmer_name": "Alpha Athlete",
                    "event": "100m freestyle",
                    "headline": "Alpha-only secret achievement",
                },
            }],
            "n_elite": 1, "n_strong": 0, "n_story": 0,
            "n_achievements": 1, "n_swims_analysed": 1,
        },
        "parse_warnings": [], "self_check": {},
        "detector_summary": {}, "dispatch_log": {},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "SECRET ALPHA INVITATIONAL", "alpha.hy3"),
    )
    conn.commit()
    conn.close()

    # Alpha-owned draft pack with the new profile_id stamp.
    from mediahub.club_platform.stub_pack_store import save_pack
    pack = save_pack(
        "free_text",
        {"free_text": "ALPHA SECRET DRAFT"},
        [{"platform": "instagram", "caption": "Alpha-only secret caption",
          "confidence": 0.9}],
        profile_id="org-alpha",
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as c:
        yield {
            "client": c,
            "run_id": run_id,
            "card_id": "swim-alpha-1",
            "pack_id": pack["pack_id"],
        }


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# Read leaks — Beta probing Alpha's URLs must not return Alpha's content
# ---------------------------------------------------------------------------

class TestForeignReadDenied:
    def test_review_returns_recovery_page_not_alpha_data(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/review/{two_orgs['run_id']}")
        body = r.get_data(as_text=True)
        assert "SECRET ALPHA INVITATIONAL" not in body
        assert "Alpha-only" not in body
        assert "Alpha Athlete" not in body

    def test_pack_grouped_does_not_render_alpha_cards(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/pack/{two_orgs['run_id']}/grouped")
        body = r.get_data(as_text=True)
        assert "SECRET ALPHA INVITATIONAL" not in body
        assert "Alpha Athlete" not in body

    def test_pack_redirect_chain_does_not_render_alpha_cards(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/pack/{two_orgs['run_id']}", follow_redirects=True)
        body = r.get_data(as_text=True)
        assert "SECRET ALPHA INVITATIONAL" not in body
        assert "Alpha Athlete" not in body

    def test_drafts_view_does_not_render_alpha_caption(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/drafts/{two_orgs['pack_id']}")
        assert r.status_code == 404
        body = r.get_data(as_text=True)
        assert "ALPHA SECRET DRAFT" not in body
        assert "Alpha-only" not in body

    def test_api_cards_returns_404_not_alpha_cards(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/runs/{two_orgs['run_id']}/cards")
        assert r.status_code == 404
        body = r.get_data(as_text=True)
        assert "Alpha Athlete" not in body

    def test_api_status_returns_404(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/runs/{two_orgs['run_id']}/status")
        assert r.status_code == 404

    def test_api_export_returns_404(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/runs/{two_orgs['run_id']}/export")
        assert r.status_code == 404

    def test_create_graphic_returns_404(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.post(
            f"/api/runs/{two_orgs['run_id']}/cards/{two_orgs['card_id']}/create-graphic",
            json={},
        )
        # Either run_not_found (404 from the run guard) or forbidden
        # (403 from the older per-profile guard) is fine — both block
        # the leak. Anything 2xx is a regression.
        assert r.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Write/mutate leaks — Beta must not be able to modify Alpha's data
# ---------------------------------------------------------------------------

class TestForeignMutateDenied:
    def test_draft_card_status_refuses_foreign_org(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.post(
            f"/api/drafts/{two_orgs['pack_id']}/card/0/status",
            data={"status": "approved"},
        )
        # Must NOT return ok:true — that would mean Beta successfully
        # flipped Alpha's draft card.
        if r.status_code == 200:
            assert r.get_json().get("ok") is not True

    def test_workflow_set_refuses_foreign_org(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.post(
            f"/api/workflow/{two_orgs['run_id']}/{two_orgs['card_id']}",
            json={"action": "set_status", "status": "approved"},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Destructive leaks — these are the worst kind. Beta deleting Alpha's
# run or draft would be silent data loss.
# ---------------------------------------------------------------------------

class TestForeignDestructiveBlocked:
    def test_privacy_delete_run_does_not_delete_alpha_run(self, two_orgs, tmp_path):
        c = two_orgs["client"]
        run_path = tmp_path / "runs_v4" / f"{two_orgs['run_id']}.json"
        assert run_path.exists()
        _pin(c, "org-beta")
        c.post(f"/privacy/run/{two_orgs['run_id']}/delete")
        # CRITICAL: file must still be on disk after the foreign POST.
        assert run_path.exists(), "Beta deleted Alpha's run — cross-tenant data loss"

    def test_drafts_delete_does_not_delete_alpha_pack(self, two_orgs, tmp_path):
        c = two_orgs["client"]
        pack_path = tmp_path / "stub_packs" / f"{two_orgs['pack_id']}.json"
        assert pack_path.exists()
        _pin(c, "org-beta")
        c.post(f"/drafts/{two_orgs['pack_id']}/delete")
        assert pack_path.exists(), "Beta deleted Alpha's draft — cross-tenant data loss"


# ---------------------------------------------------------------------------
# Owner positive control — Alpha must still get her own data after the fix.
# Without these tests we'd never notice if the guard was over-strict.
# ---------------------------------------------------------------------------

class TestOwnerStillHasAccess:
    def test_alpha_can_open_her_own_review(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/review/{two_orgs['run_id']}")
        assert r.status_code == 200
        assert "SECRET ALPHA INVITATIONAL" in r.get_data(as_text=True)

    def test_alpha_can_open_her_own_drafts(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/drafts/{two_orgs['pack_id']}")
        assert r.status_code == 200
        assert "ALPHA SECRET DRAFT" in r.get_data(as_text=True)

    def test_alpha_can_delete_her_own_run(self, two_orgs, tmp_path):
        c = two_orgs["client"]
        run_path = tmp_path / "runs_v4" / f"{two_orgs['run_id']}.json"
        assert run_path.exists()
        _pin(c, "org-alpha")
        c.post(f"/privacy/run/{two_orgs['run_id']}/delete")
        assert not run_path.exists()

    def test_alpha_can_delete_her_own_draft(self, two_orgs, tmp_path):
        c = two_orgs["client"]
        pack_path = tmp_path / "stub_packs" / f"{two_orgs['pack_id']}.json"
        assert pack_path.exists()
        _pin(c, "org-alpha")
        c.post(f"/drafts/{two_orgs['pack_id']}/delete")
        assert not pack_path.exists()


# ---------------------------------------------------------------------------
# Spotlight landing — the meet picker dropdown and the ?run_id= roster
# render must both be tenant-scoped. Regression guard for the IDOR where
# Beta's /spotlight listed every org's meet names and a tampered
# ?run_id= surfaced another club's full swimmer roster (PII).
# ---------------------------------------------------------------------------

class TestSpotlightTenantScoped:
    def test_beta_spotlight_dropdown_omits_alpha_meet(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get("/spotlight")
        body = r.get_data(as_text=True)
        assert "SECRET ALPHA INVITATIONAL" not in body
        assert two_orgs["run_id"] not in body

    def test_beta_spotlight_run_id_param_hides_alpha_roster(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/spotlight?run_id={two_orgs['run_id']}")
        body = r.get_data(as_text=True)
        assert "Alpha Athlete" not in body
        assert "Alpha-only" not in body

    def test_alpha_spotlight_dropdown_shows_own_meet(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get("/spotlight")
        assert r.status_code == 200
        assert "SECRET ALPHA INVITATIONAL" in r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Legacy lenience — runs / packs with no owner stamped (pre-multi-tenant
# data) must remain accessible. Otherwise we'd orphan historical data.
# ---------------------------------------------------------------------------

class TestLegacyOrphansStillAccessible:
    def test_run_without_profile_id_is_readable_by_anyone(self, two_orgs, tmp_path):
        import mediahub.web.web as wm
        legacy_id = "legacy-run-" + uuid.uuid4().hex[:8]
        (tmp_path / "runs_v4" / f"{legacy_id}.json").write_text(json.dumps({
            "run_id": legacy_id,
            "profile_id": "",
            "meet": {"name": "Legacy meet"},
            "cards": [],
            "recognition_report": {},
        }))
        # DB row with no profile_id either.
        conn = wm._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, file_name) VALUES (?, datetime('now'), 'done', '', ?, ?)",
            (legacy_id, "Legacy meet", "legacy.hy3"),
        )
        conn.commit()
        conn.close()

        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/runs/{legacy_id}/cards")
        # Legacy un-owned runs stay readable so we don't break history.
        assert r.status_code == 200
