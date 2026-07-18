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
def two_orgs(web_module, tmp_path):
    wm = web_module

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-alpha",
            display_name="Org Alpha",
            brand_voice_summary="Bold, energetic, club-focused.",
        )
    )
    save_profile(
        ClubProfile(
            profile_id="org-beta",
            display_name="Org Beta",
            brand_voice_summary="Calm and considered.",
        )
    )

    # Alpha-owned run JSON + matching DB row so /review, /pack, /privacy
    # can all find it.
    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    run_payload = {
        "run_id": run_id,
        "profile_id": "org-alpha",
        "profile_display": "Org Alpha",
        "meet": {"name": "SECRET ALPHA INVITATIONAL"},
        "cards": [
            {
                "card_id": "card-alpha-1",
                "swim_id": "swim-alpha-1",
                "swimmer_name": "Alpha Athlete",
                "event": "100m freestyle",
                "headline": "Alpha-only PB",
                "id": "card-alpha-1",
            }
        ],
        "trust": {"score": 0.92},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-alpha-1",
                        "swimmer_name": "Alpha Athlete",
                        "event": "100m freestyle",
                        "headline": "Alpha-only secret achievement",
                    },
                }
            ],
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
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
        [{"platform": "instagram", "caption": "Alpha-only secret caption", "confidence": 0.9}],
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
        (tmp_path / "runs_v4" / f"{legacy_id}.json").write_text(
            json.dumps(
                {
                    "run_id": legacy_id,
                    "profile_id": "",
                    "meet": {"name": "Legacy meet"},
                    "cards": [],
                    "recognition_report": {},
                }
            )
        )
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


# ---------------------------------------------------------------------------
# @require_run migration (deep-review finding #18) — batch 1.
#
# These handlers had the copy-pasted
#     if not _can_access_run(run_id, _load_run(run_id), _active_profile_id()):
#         return jsonify({"error": "run_not_found"}), 404
# guard replaced by the single-source-of-truth ``@require_run`` decorator. The
# contract must be unchanged: a foreign org gets exactly the run_not_found 404
# (no leak, no existence oracle), and the owner still passes the gate into the
# body. If a future edit drops ``@require_run`` from any of these, the foreign
# case flips to 2xx / a downstream error and these fail loudly.
# ---------------------------------------------------------------------------

# (method, url_template, json_body) — {rid}/{cid}/{tok} filled from the fixture.
_BATCH1_ENDPOINTS = [
    ("GET", "/api/runs/{rid}/card/{cid}/revisions", None),
    ("GET", "/api/runs/{rid}/card/{cid}/revisions/diff", None),
    ("POST", "/api/runs/{rid}/card/{cid}/revisions/restore", {}),
    ("GET", "/api/runs/{rid}/card/{cid}/locks", None),
    ("POST", "/api/runs/{rid}/card/{cid}/locks", {"element": "headline", "locked": True}),
    ("GET", "/api/runs/{rid}/shares", None),
    ("POST", "/api/runs/{rid}/shares", {"perm": "view"}),
    ("POST", "/api/runs/{rid}/shares/{tok}/revoke", {}),
    ("GET", "/api/runs/{rid}/card/{cid}/motion/manifest", None),
    ("POST", "/api/runs/{rid}/export-share", {"job": "0" * 32}),
]

# A synthetic, obviously-fake share token — never a real credential. Kept
# low-entropy (a repeated "deadbeef") so gitleaks' generic-api-key entropy
# rule doesn't flag it; the value is only used as a URL path segment for the
# revoke route, where a foreign org is refused before the token is ever read.
_TOKEN = "deadbeefdeadbeefdeadbeefdeadbeef"


def _fill(url, run_id):
    return url.format(rid=run_id, cid="card-alpha-1", tok=_TOKEN)


def _hit(client, method, url, body):
    if method == "GET":
        return client.get(url)
    return client.post(url, json=body)


class TestRequireRunBatch1:
    @pytest.mark.parametrize("method,url,body", _BATCH1_ENDPOINTS)
    def test_foreign_org_gets_run_not_found_404(self, two_orgs, method, url, body):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r = _hit(c, method, _fill(url, two_orgs["run_id"]), body)
        assert r.status_code == 404, (method, url, r.get_data(as_text=True))
        text = r.get_data(as_text=True)
        # The exact denial shape the copy-pasted guard produced, and no leak.
        assert r.get_json() == {"error": "run_not_found"}, text
        assert "Alpha Athlete" not in text
        assert "SECRET ALPHA" not in text

    @pytest.mark.parametrize("method,url,body", _BATCH1_ENDPOINTS)
    def test_owner_passes_the_gate(self, two_orgs, method, url, body):
        """The owner must reach the body — never the run_not_found 404. A
        downstream 404 (revision_not_found / manifest_not_found /
        export_not_found) is fine; run_not_found from the tenant gate is not."""
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = _hit(c, method, _fill(url, two_orgs["run_id"]), body)
        if r.status_code == 404:
            assert r.get_json() != {"error": "run_not_found"}, (method, url)
        else:
            assert r.status_code in (200, 201), (method, url, r.status_code)

    def test_endpoint_names_preserved_for_url_for(self, two_orgs):
        """functools.wraps keeps each view's __name__, so url_for still resolves
        the migrated endpoints (a broken wrapper would raise BuildError)."""
        import mediahub.web.web as wm

        app = wm.create_app()
        with app.test_request_context():
            from flask import url_for

            rid, cid = "r1", "c1"
            assert url_for("api_card_revisions", run_id=rid, card_id=cid)
            assert url_for("api_card_locks", run_id=rid, card_id=cid)
            assert url_for("api_run_shares", run_id=rid)
            assert url_for("api_run_share_revoke", run_id=rid, token=_TOKEN)
            assert url_for("api_card_motion_manifest", run_id=rid, card_id=cid)
            assert url_for("api_run_export_share", run_id=rid)


# ---------------------------------------------------------------------------
# @require_run decorator unit tests — the guard's own semantics, isolated from
# any particular route. _load_run / _can_access_run are module-level, so they
# monkeypatch cleanly; the pid from _active_profile_id() only feeds
# _can_access_run, which we stub, so no session wiring is needed.
# ---------------------------------------------------------------------------


class TestRequireRunDecorator:
    def test_injects_run_data_only_when_declared(self, app, monkeypatch):
        import mediahub.web.web as wm

        sentinel = {"run_id": "r1", "sentinel": True}
        monkeypatch.setattr(wm, "_load_run", lambda rid: dict(sentinel, run_id=rid))
        monkeypatch.setattr(wm, "_can_access_run", lambda rid, data, pid: True)

        @app.require_run
        def wants(run_id, run_data=None):
            return ("wants", run_data)

        @app.require_run
        def plain(run_id):
            return "plain"

        with app.test_request_context("/"):
            label, injected = wants(run_id="r1")
            assert label == "wants"
            assert injected == {"run_id": "r1", "sentinel": True}
            # A view that doesn't declare run_data is called without it.
            assert plain(run_id="r1") == "plain"

    def test_default_deny_is_run_not_found_404(self, app, monkeypatch):
        import mediahub.web.web as wm

        monkeypatch.setattr(wm, "_load_run", lambda rid: {"run_id": rid})
        monkeypatch.setattr(wm, "_can_access_run", lambda rid, data, pid: False)

        @app.require_run
        def view(run_id):
            return "should-not-run"

        with app.test_request_context("/"):
            resp, status = view(run_id="r1")
            assert status == 404
            assert resp.get_json() == {"error": "run_not_found"}

    def test_custom_deny_response_is_used(self, app, monkeypatch):
        import mediahub.web.web as wm

        monkeypatch.setattr(wm, "_load_run", lambda rid: {"run_id": rid})
        monkeypatch.setattr(wm, "_can_access_run", lambda rid, data, pid: False)

        @app.require_run(deny=lambda: ("nope", 418))
        def view(run_id):
            return "should-not-run"

        with app.test_request_context("/"):
            assert view(run_id="r1") == ("nope", 418)

    def test_require_exists_denies_missing_run_even_when_readable(self, app, monkeypatch):
        import mediahub.web.web as wm

        # Missing run, but _can_access_run says "allowed" (the ownerless-readable
        # path). Without require_exists the body runs; with it, we 404.
        monkeypatch.setattr(wm, "_load_run", lambda rid: None)
        monkeypatch.setattr(wm, "_can_access_run", lambda rid, data, pid: True)

        @app.require_run(require_exists=True)
        def strict(run_id):
            return "body-ran"

        @app.require_run
        def lenient(run_id):
            return "body-ran"

        with app.test_request_context("/"):
            resp, status = strict(run_id="missing")
            assert status == 404
            assert resp.get_json() == {"error": "run_not_found"}
            # Same conditions, no require_exists → the body still runs.
            assert lenient(run_id="missing") == "body-ran"

    def test_wraps_preserves_view_name(self, app):
        @app.require_run
        def my_view(run_id):
            return "ok"

        assert my_view.__name__ == "my_view"


# ---------------------------------------------------------------------------
# @require_run migration — batch 2 (finding #18). 38 more run-scoped handlers
# had their copy-pasted _can_access_run guard replaced by @require_run, across
# web.py and the routes_api_runs.py blueprint module (finding #15). We drive
# every route of every migrated endpoint off the url_map: for the FOREIGN org
# the tenant gate (now the decorator) must fire before any body code, so the
# response is never 2xx and never leaks Alpha's data — whatever each handler's
# deny shape (404 json / recovery page / 302 redirect / abort). A dropped
# @require_run on any of them turns its foreign probe 2xx and reddens here.
# ---------------------------------------------------------------------------

_BATCH2_ENDPOINTS = [
    "api_caption_assist", "api_caption_platforms", "api_card_download",
    "api_card_elements", "api_card_reaction_toggle", "api_card_translate",
    "api_cards", "api_cards_bulk_download", "api_cards_bulk_export",
    "api_cards_bulk_status", "api_element_suggestions", "api_export",
    "api_live_caption", "api_recognition", "api_run_bulk_export",
    "api_run_certificates_job", "api_run_reactions", "api_status",
    "api_swim_trace", "api_trust", "api_turn_into", "api_turn_into_edit_caption",
    "api_turn_into_status", "api_why_card", "api_workflow_set",
    "export_run_tool_page", "ground_truth", "pack_certificates_zip",
    "pack_print_separations", "pb_audit_page", "pb_ground_truth", "pb_ignore",
    "pb_verify_form", "rerun_run", "review", "run_results_table", "run_status",
    "turn_into_pack_view",
]

_B2_PARAM_FILL = {
    "swimmer_key": "alpha-athlete-001", "swim_id": "swim-alpha-1",
    "pack_id": "pk0000000000", "job_id": "0" * 32, "job": "0" * 32,
    "token": _TOKEN, "brief_id": "brief-probe", "task_id": "task0000",
    "ach_index": "0", "idx": "0", "n": "1", "fmt": "feed_portrait",
}


def _batch2_urls(two_orgs):
    import mediahub.web.web as wm

    app = wm.create_app()
    app.config["TESTING"] = True
    rid, cid = two_orgs["run_id"], "card-alpha-1"
    out = []
    with app.test_request_context():
        from flask import url_for
        for rule in app.url_map.iter_rules():
            if rule.endpoint not in _BATCH2_ENDPOINTS:
                continue
            args = {}
            for a in rule.arguments:
                args[a] = rid if a == "run_id" else (cid if a == "card_id"
                          else _B2_PARAM_FILL.get(a, "probe-dummy"))
            try:
                url = url_for(rule.endpoint, **args)
            except Exception:
                continue
            for m in sorted(rule.methods & {"GET", "POST", "PUT", "DELETE", "PATCH"}):
                out.append((rule.endpoint, m, url))
    return out


class TestRequireRunBatch2ForeignDenied:
    def test_every_migrated_endpoint_denies_foreign_org(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-beta")
        checked, failures = 0, []
        for ep, method, url in _batch2_urls(two_orgs):
            r = c.open(url, method=method, json={} if method != "GET" else None)
            checked += 1
            body = r.get_data(as_text=True)
            leak = "Alpha Athlete" in body or "SECRET ALPHA" in body
            if (200 <= r.status_code < 300) or leak:
                failures.append((ep, method, url, r.status_code, leak))
        assert not failures, f"foreign org not denied on: {failures}"
        assert checked >= 38, f"only {checked} routes probed"

    def test_owner_reaches_body_on_read_endpoints(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        reads = {"api_cards", "api_status", "api_trust", "api_recognition",
                 "review", "run_status", "api_card_elements", "api_run_reactions"}
        for ep, method, url in _batch2_urls(two_orgs):
            if ep not in reads or method != "GET":
                continue
            r = c.get(url)
            if r.status_code == 404:
                body = r.get_json(silent=True) or {}
                assert body.get("error") != "run_not_found", (ep, url)
