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

    def test_drafts_index_hides_foreign_packs_shows_own_and_unstamped(self, two_orgs):
        """/drafts lists only the active org's packs plus unstamped legacy
        ones — a pack title is the first line of another org's free-text
        brief, so the index must be per-tenant filtered like the per-pack
        routes."""
        from mediahub.club_platform.stub_pack_store import save_pack

        beta_pack = save_pack(
            "free_text",
            {"free_text": "BETA OWN DRAFT"},
            [{"platform": "instagram", "caption": "Beta caption", "confidence": 0.9}],
            profile_id="org-beta",
        )
        legacy_pack = save_pack(
            "free_text",
            {"free_text": "LEGACY UNSTAMPED DRAFT"},
            [{"platform": "instagram", "caption": "Legacy caption", "confidence": 0.9}],
        )
        c = two_orgs["client"]
        _pin(c, "org-beta")
        body = c.get("/drafts").get_data(as_text=True)
        # Own + unstamped legacy visible; Alpha's title must not leak.
        assert "BETA OWN DRAFT" in body
        assert "LEGACY UNSTAMPED DRAFT" in body
        assert "ALPHA SECRET DRAFT" not in body
        # Alpha still sees her own.
        _pin(c, "org-alpha")
        body = c.get("/drafts").get_data(as_text=True)
        assert "ALPHA SECRET DRAFT" in body
        assert "BETA OWN DRAFT" not in body
        assert beta_pack["pack_id"] not in body
        assert legacy_pack["pack_id"]  # created OK (sanity)

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

    def test_api_cards_export_in_progress_run_is_404_for_foreign_org(self, two_orgs, tmp_path):
        """An IN-PROGRESS run (DB row, no JSON yet) must 404 for a foreign org
        on /cards and /export — the 202 in_progress short-circuit must not leak
        that another org's run exists / when it finishes. Owner still gets 202."""
        import mediahub.web.web as wm

        prog_id = "run-alpha-inprog-" + uuid.uuid4().hex[:8]
        conn = wm._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, file_name) VALUES (?, datetime('now'), 'running', ?, ?, ?)",
            (prog_id, "org-alpha", "SECRET ALPHA INPROGRESS", "alpha2.hy3"),
        )
        conn.commit()
        conn.close()
        # No JSON file on disk → _run_state is in_progress.
        assert not (tmp_path / "runs_v4" / f"{prog_id}.json").exists()

        c = two_orgs["client"]
        _pin(c, "org-beta")
        assert c.get(f"/api/runs/{prog_id}/cards").status_code == 404
        assert c.get(f"/api/runs/{prog_id}/export").status_code == 404

        # The owner still sees the honest 202 in_progress signal.
        _pin(c, "org-alpha")
        assert c.get(f"/api/runs/{prog_id}/cards").status_code == 202
        assert c.get(f"/api/runs/{prog_id}/export").status_code == 202

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


class TestVisualSidecarTenantScoped:
    """org-access audit: /api/visual/<vid> and its /png/<format> sibling
    iterate ALL of RUNS_DIR to resolve a visual id. Both must refuse a
    foreign org's visual — the sidecar carries the caption, alt text and
    athlete names, and the PNG is the branded graphic — so a signed-in
    member of one org can't read another org's visuals by id.
    """

    def _seed_alpha_visual(self, tmp_path, run_id, vid="v_alphasecret1"):
        vdir = tmp_path / "runs_v4" / run_id / "visuals" / "brief-alpha"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "visual.json").write_text(
            json.dumps(
                {
                    "id": vid,
                    "visual_ids": {vid: "feed_portrait"},
                    "caption": "ALPHA SECRET VISUAL CAPTION",
                    "alt_text": "Alpha Athlete winning the 100m freestyle",
                }
            )
        )
        # A 1x1 PNG so the /png route has something to serve on the owner path.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d4944415478da6360000002000154a24f1e0000000049454e44ae42"
            "6082"
        )
        (vdir / "feed_portrait.png").write_bytes(png)
        return vid

    def test_foreign_org_cannot_read_visual_sidecar(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        vid = self._seed_alpha_visual(tmp_path, two_orgs["run_id"])
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 404
        assert "ALPHA SECRET VISUAL CAPTION" not in r.get_data(as_text=True)

    def test_foreign_org_cannot_read_visual_png(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        vid = self._seed_alpha_visual(tmp_path, two_orgs["run_id"])
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/visual/{vid}/png/feed_portrait")
        assert r.status_code == 404
        assert not r.get_data()

    def test_owner_still_reads_her_own_visual(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        vid = self._seed_alpha_visual(tmp_path, two_orgs["run_id"])
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 200
        assert r.get_json()["caption"] == "ALPHA SECRET VISUAL CAPTION"
        r = c.get(f"/api/visual/{vid}/png/feed_portrait")
        assert r.status_code == 200
        assert r.data  # the branded PNG bytes

    def test_legacy_ownerless_visual_still_readable(self, two_orgs, tmp_path):
        """A visual under an ownerless (legacy) run stays readable, mirroring
        _can_access_run's ownerless-run tolerance."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        legacy_id = "legacy-vis-" + uuid.uuid4().hex[:8]
        (tmp_path / "runs_v4" / f"{legacy_id}.json").write_text(
            json.dumps({"run_id": legacy_id, "profile_id": "", "cards": []})
        )
        vid = self._seed_alpha_visual(tmp_path, legacy_id, vid="v_legacyvisual")
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 200

    # --- #17: the O(1) index behind the two routes ------------------------

    def test_slow_path_backfills_index(self, two_orgs, tmp_path):
        """A run whose sidecar predates the index resolves on the walk and
        self-heals: after one request the vid is indexed, so the next is O(1)."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        run_id = two_orgs["run_id"]
        vid = self._seed_alpha_visual(tmp_path, run_id, vid="v_backfill1")
        # Nothing indexed yet — the sidecar was written straight to disk.
        assert wm._vidx_lookup(vid) is None
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 200
        # The walk backfilled the index — a subsequent lookup is O(1).
        assert wm._vidx_lookup(vid) == (run_id, "brief-alpha")

    def test_fast_path_still_denies_foreign_org(self, two_orgs, tmp_path):
        """With the vid already indexed (fast path), the tenant gate must still
        refuse a foreign org — the folded _can_access_run, not the walk, guards."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        run_id = two_orgs["run_id"]
        vid = self._seed_alpha_visual(tmp_path, run_id, vid="v_indexed1")
        # Pre-stamp the index so the request takes the O(1) fast path.
        wm._vidx_index(run_id, "brief-alpha", {"id": vid, "visual_ids": {vid: "feed_portrait"}})
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 404
        assert "ALPHA SECRET VISUAL CAPTION" not in r.get_data(as_text=True)
        r = c.get(f"/api/visual/{vid}/png/feed_portrait")
        assert r.status_code == 404
        assert not r.get_data()
        # A genuine-but-forbidden hit is NOT a stale row — it stays indexed.
        assert wm._vidx_lookup(vid) == (run_id, "brief-alpha")

    def test_stale_index_row_self_heals(self, two_orgs, tmp_path):
        """An index row pointing at a vanished/renamed brief dir must fall back
        to the walk, serve the real sidecar, and repoint the index."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        run_id = two_orgs["run_id"]
        vid = self._seed_alpha_visual(tmp_path, run_id, vid="v_stale1")
        # Point the index at a brief dir that doesn't exist on disk.
        wm._vidx_index(run_id, "brief-GHOST", {"id": vid, "visual_ids": {vid: "feed_portrait"}})
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/api/visual/{vid}")
        assert r.status_code == 200
        assert r.get_json()["caption"] == "ALPHA SECRET VISUAL CAPTION"
        # The stale row was corrected to the real brief dir.
        assert wm._vidx_lookup(vid) == (run_id, "brief-alpha")

    def test_walk_and_index_paths_are_byte_identical(self, two_orgs, tmp_path):
        """The whole point of #17: the O(1) index only changes *how* a visual is
        located, never the bytes served. The first request resolves via the walk
        (cold index) and backfills; the second resolves via the index. Both the
        JSON payload and the PNG must be byte-for-byte identical."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        run_id = two_orgs["run_id"]
        vid = self._seed_alpha_visual(tmp_path, run_id, vid="v_identical1")
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        # Cold — resolved by the walk, then backfilled.
        assert wm._vidx_lookup(vid) is None
        g_walk = c.get(f"/api/visual/{vid}")
        p_walk = c.get(f"/api/visual/{vid}/png/feed_portrait")
        assert wm._vidx_lookup(vid) == (run_id, "brief-alpha")
        # Warm — resolved by the index.
        g_idx = c.get(f"/api/visual/{vid}")
        p_idx = c.get(f"/api/visual/{vid}/png/feed_portrait")
        assert g_walk.status_code == g_idx.status_code == 200
        assert p_walk.status_code == p_idx.status_code == 200
        assert g_walk.get_data() == g_idx.get_data()
        assert p_walk.get_data() == p_idx.get_data()

    def test_delete_run_cascades_visual_index(self, two_orgs, tmp_path):
        """Erasing a run must drop its vid→run rows, leaving no orphan mappings."""
        import mediahub.web.web as wm

        if not wm._v8_ok:
            import pytest

            pytest.skip("v8 media engine unavailable")
        run_id = two_orgs["run_id"]
        vid = self._seed_alpha_visual(tmp_path, run_id, vid="v_erase1")
        wm._vidx_index(run_id, "brief-alpha", {"id": vid, "visual_ids": {vid: "feed_portrait"}})
        assert wm._vidx_lookup(vid) == (run_id, "brief-alpha")
        wm._delete_run(run_id)
        assert wm._vidx_lookup(vid) is None
