"""tests/test_finding18_latent_fixes.py — regression guards for the deep-review
finding #18 latent-bug fixes (the security/robustness hardening that followed the
@require_run migration).

Each class locks in ONE fix: it asserts the new, correct behaviour AND that the
old-bad behaviour is gone, so the guard fails on the unfixed code and passes on
the fixed code. The seeding mirrors tests/test_cross_tenant_access.py (org-alpha
owns a run; a pinned org-beta session is the foreign prober).
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
# Shared fixture: two orgs, one Alpha-owned run + draft pack, fresh DATA_DIR.
# ---------------------------------------------------------------------------

@pytest.fixture
def two_orgs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha",
                             brand_voice_summary="Bold, energetic, club-focused."))
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta",
                             brand_voice_summary="Calm and considered."))

    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    run_payload = {
        "run_id": run_id, "profile_id": "org-alpha", "profile_display": "Org Alpha",
        "meet": {"name": "SECRET ALPHA INVITATIONAL"},
        "cards": [{"card_id": "card-alpha-1", "swim_id": "swim-alpha-1",
                   "swimmer_name": "Alpha Athlete", "event": "100m freestyle",
                   "headline": "Alpha-only PB", "id": "card-alpha-1"}],
        "trust": {"score": 0.92},
        "recognition_report": {
            "ranked_achievements": [{"achievement": {
                "swim_id": "swim-alpha-1", "swimmer_name": "Alpha Athlete",
                "event": "100m freestyle", "headline": "Alpha-only secret achievement"}}],
            "n_elite": 1, "n_strong": 0, "n_story": 0,
            "n_achievements": 1, "n_swims_analysed": 1,
        },
        "parse_warnings": [], "self_check": {}, "detector_summary": {}, "dispatch_log": {},
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

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield {"client": c, "run_id": run_id, "card_id": "card-alpha-1"}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


def _write_corrupt_nested_run(tmp_path, run_id):
    """A nested runs_v4/<id>/run.json that exists but does not parse — the path
    the per-card handlers used to 500 on with the raw exception text."""
    nested = tmp_path / "runs_v4" / run_id
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "run.json").write_text("{ this is not valid json, definitely ")
    return run_id


# ---------------------------------------------------------------------------
# Fix 1 — corrupt-run 500 oracle: a corrupt run must answer exactly like a
# missing run (run_not_found 404), never 500 + raw exception text, and never
# before the tenant gate.
# ---------------------------------------------------------------------------

class TestCorruptRunNotAnOracle:
    def test_motion_file_corrupt_run_matches_missing_run(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        corrupt_id = _write_corrupt_nested_run(tmp_path, "run-corrupt-mf-" + uuid.uuid4().hex[:8])
        assert wm._load_run(corrupt_id) is None
        c = two_orgs["client"]
        _pin(c, "org-beta")
        r_corrupt = c.get(f"/api/runs/{corrupt_id}/card/card-x/motion-file")
        r_missing = c.get(f"/api/runs/run-missing-mf-{uuid.uuid4().hex[:8]}/card/card-x/motion-file")
        assert r_corrupt.status_code != 500, r_corrupt.get_data(as_text=True)
        assert "run_load_failed" not in r_corrupt.get_data(as_text=True)
        assert r_corrupt.status_code == r_missing.status_code == 404
        assert r_corrupt.get_json() == r_missing.get_json() == {"error": "run_not_found"}

    def test_assemble_card_motion_inputs_corrupt_run_is_404_not_500(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        corrupt_id = _write_corrupt_nested_run(tmp_path, "run-corrupt-asm-" + uuid.uuid4().hex[:8])
        assert wm._load_run(corrupt_id) is None
        app = wm.create_app()
        app.config["TESTING"] = True
        with app.test_request_context(f"/api/runs/{corrupt_id}/card/card-x/motion"):
            inputs, err = wm._assemble_card_motion_inputs(corrupt_id, "card-x")
        assert inputs is None
        resp, status = err
        assert status == 404
        assert resp.get_json() == {"error": "run_not_found"}
        assert "run_load_failed" not in resp.get_data(as_text=True)

    def test_create_graphic_corrupt_run_matches_missing_run(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        if not wm._v8_ok:
            pytest.skip("v8 media engine unavailable")
        corrupt_id = _write_corrupt_nested_run(tmp_path, "run-corrupt-cg-" + uuid.uuid4().hex[:8])
        c = two_orgs["client"]
        _pin(c, "org-beta")
        url = "/api/runs/{rid}/cards/card-x/create-graphic"
        r_corrupt = c.post(url.format(rid=corrupt_id), json={})
        r_missing = c.post(url.format(rid="run-missing-cg-" + uuid.uuid4().hex[:8]), json={})
        assert r_corrupt.status_code != 500, r_corrupt.get_data(as_text=True)
        assert "run_load_failed" not in r_corrupt.get_data(as_text=True)
        assert r_corrupt.status_code == r_missing.status_code == 404
        assert r_corrupt.get_json() == r_missing.get_json() == {"error": "run_not_found"}


# ---------------------------------------------------------------------------
# Fix 2 (in-progress timing oracle) + Fix 5 (pb_ignore mutation-without-existence)
# ---------------------------------------------------------------------------

class TestInProgressAndPbIgnore:
    def test_pack_pages_in_progress_run_hidden_from_foreign_org(self, two_orgs, tmp_path):
        import mediahub.web.web as wm

        prog_id = "run-alpha-inprog-pack-" + uuid.uuid4().hex[:8]
        conn = wm._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, file_name) VALUES (?, datetime('now'), 'running', ?, ?, ?)",
            (prog_id, "org-alpha", "SECRET ALPHA INPROGRESS PACK", "alpha3.hy3"),
        )
        conn.commit()
        conn.close()
        assert not (tmp_path / "runs_v4" / f"{prog_id}.json").exists()
        assert wm._run_state(prog_id) == "in_progress"

        c = two_orgs["client"]
        _pin(c, "org-beta")
        for path in (f"/pack/{prog_id}", f"/pack/{prog_id}/grouped"):
            body = c.get(path).get_data(as_text=True)
            assert "Still processing your run" not in body, path
            assert "Run not found" in body, path
            assert "SECRET ALPHA" not in body, path

        _pin(c, "org-alpha")
        for path in (f"/pack/{prog_id}", f"/pack/{prog_id}/grouped"):
            r = c.get(path)
            assert r.status_code == 200, path
            assert "Still processing your run" in r.get_data(as_text=True), path

    def test_pb_ignore_missing_run_does_not_mutate_corrections(self, two_orgs):
        from swim_content_pb.corrections import CorrectionsStore, _corrections_path

        c = two_orgs["client"]
        _pin(c, "org-beta")
        fake_run = "run-does-not-exist-" + uuid.uuid4().hex[:8]
        swimmer_key = "name:GHOST, SWIMMER"
        cpath = _corrections_path(fake_run)
        r = c.post(f"/audit/{fake_run}/ignore/{swimmer_key}", data={"reason": "attacker-supplied"})
        assert r.status_code in (302, 303), r.status_code
        assert f"/audit/{fake_run}" not in r.headers["Location"]
        assert CorrectionsStore().get_override(fake_run, swimmer_key) is None
        assert not cpath.exists()

    def test_pb_ignore_owner_happy_path_still_writes(self, two_orgs):
        from swim_content_pb.corrections import CorrectionsStore

        c = two_orgs["client"]
        _pin(c, "org-alpha")
        run_id = two_orgs["run_id"]
        swimmer_key = "name:ALPHA, ATHLETE"
        r = c.post(f"/audit/{run_id}/ignore/{swimmer_key}", data={"reason": "genuine"})
        assert r.status_code in (302, 303)
        assert CorrectionsStore().get_override(run_id, swimmer_key) is not None


# ---------------------------------------------------------------------------
# Fix 3 — 404-body enumeration oracle: missing run == foreign run (both
# run_not_found), never card_not_found for a nonexistent run.
# ---------------------------------------------------------------------------

class TestNotFoundBodyParity:
    _ROUTES = [
        ("POST", "/api/runs/{rid}/cards/{cid}/photo-confirm", {"asset_id": "whatever"}),
        ("POST", "/api/runs/{rid}/cards/{cid}/clip-unlink", {"asset_id": "whatever"}),
        ("GET", "/api/runs/{rid}/card/{cid}/thumb.png", None),
    ]

    @staticmethod
    def _hit(client, method, url, body):
        return client.get(url) if method == "GET" else client.post(url, json=body)

    @pytest.mark.parametrize("method,url,body", _ROUTES)
    def test_missing_run_matches_foreign_run(self, two_orgs, method, url, body):
        import mediahub.web.web as wm

        if not wm._v8_ok:
            pytest.skip("v8 media engine unavailable")
        c = two_orgs["client"]
        _pin(c, "org-beta")
        cid = two_orgs["card_id"]
        foreign = self._hit(c, method, url.format(rid=two_orgs["run_id"], cid=cid), body)
        missing = self._hit(c, method, url.format(rid="run-ghost-" + uuid.uuid4().hex[:8], cid=cid), body)
        assert foreign.status_code == missing.status_code == 404, (method, url,
                                                                    foreign.status_code, missing.status_code)
        assert foreign.get_json() == {"error": "run_not_found"}, foreign.get_data(as_text=True)
        assert missing.get_json() == {"error": "run_not_found"}, missing.get_data(as_text=True)
        assert missing.get_json() != {"error": "card_not_found"}


# ---------------------------------------------------------------------------
# Fix 6 — _run_data_any must delegate to _load_run (traversal guard + no
# corrupt-flat masking), while still loading the legacy nested layout.
# ---------------------------------------------------------------------------

class TestRunDataAnyDelegatesToLoadRun:
    def test_nested_only_layout_still_loads(self, two_orgs):
        import mediahub.web.web as wm

        rid = "run-nested-" + uuid.uuid4().hex[:8]
        nested = wm.RUNS_DIR / rid / "run.json"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text(json.dumps({"run_id": rid, "meet": {"name": "NESTED MEET"}}))
        rd = wm._run_data_any(rid)
        assert rd is not None
        assert rd["meet"]["name"] == "NESTED MEET"

    def test_traversal_hostile_id_is_refused(self, two_orgs):
        import mediahub.web.web as wm

        outside = wm.RUNS_DIR.parent / "escape" / "run.json"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text(json.dumps({"secret": "ESCAPED"}))
        assert wm._run_data_any("../escape") is None

    def test_corrupt_flat_is_not_masked_by_nested(self, two_orgs):
        import mediahub.web.web as wm

        rid = "run-corrupt-" + uuid.uuid4().hex[:8]
        (wm.RUNS_DIR / f"{rid}.json").write_text("{ this is not valid json ")
        nested = wm.RUNS_DIR / rid / "run.json"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text(json.dumps({"run_id": rid, "meet": {"name": "MASKED"}}))
        assert wm._run_data_any(rid) is None


# ---------------------------------------------------------------------------
# Fix 7 — api_run_render_all_job: run_data=None -> honest run_not_found 404,
# never a 500 from a bare run_data.get(...).
# ---------------------------------------------------------------------------

class TestRenderAllNoneRunNotFound:
    def _render_all(self, c, run_id):
        return c.post(f"/api/runs/{run_id}/render-all-job")

    def test_missing_run_is_run_not_found_not_no_approved_cards(self, two_orgs):
        import mediahub.web.web as wm

        c = two_orgs["client"]
        _pin(c, "org-alpha")
        ghost = "run-ghost-ra-" + uuid.uuid4().hex[:8]
        assert wm._load_run(ghost) is None
        r = self._render_all(c, ghost)
        if r.status_code == 503:
            pytest.skip("v8 media engine unavailable in this environment")
        assert r.status_code != 500, r.get_data(as_text=True)
        assert (r.get_json() or {}).get("error") != "no_approved_cards"
        assert r.status_code == 404
        assert r.get_json() == {"error": "run_not_found"}

    def test_corrupt_flat_run_matches_missing_run(self, two_orgs):
        import mediahub.web.web as wm

        c = two_orgs["client"]
        _pin(c, "org-alpha")
        corrupt = "run-corrupt-ra-" + uuid.uuid4().hex[:8]
        (wm.RUNS_DIR / f"{corrupt}.json").write_text("{ this is not valid json ")
        assert wm._load_run(corrupt) is None
        r_corrupt = self._render_all(c, corrupt)
        r_missing = self._render_all(c, "run-missing-ra-" + uuid.uuid4().hex[:8])
        if r_corrupt.status_code == 503 or r_missing.status_code == 503:
            pytest.skip("v8 media engine unavailable in this environment")
        assert r_corrupt.status_code != 500, r_corrupt.get_data(as_text=True)
        assert r_corrupt.status_code == r_missing.status_code == 404
        assert r_corrupt.get_json() == r_missing.get_json() == {"error": "run_not_found"}

    def test_owner_happy_path_unchanged(self, two_orgs):
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = self._render_all(c, two_orgs["run_id"])
        if r.status_code == 503:
            pytest.skip("v8 media engine unavailable in this environment")
        assert r.status_code != 404
        assert (r.get_json() or {}).get("error") != "run_not_found"
        assert r.status_code == 400
        assert (r.get_json() or {}).get("error") == "no_approved_cards"


# ---------------------------------------------------------------------------
# Fix 4 — api_turn_into_edit_caption must gate on CAP_EDIT. Needs a BOUND
# workspace (real owner + real read-only viewer) so seats aren't collapsed to
# owner.
# ---------------------------------------------------------------------------

_CAP_PASSWORD = "twelve-chars-long"
_CAP_OWNER = "owner@cap-alpha.org"
_CAP_VIEWER = "viewer@cap-alpha.org"


@pytest.fixture
def bound_pack_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web import tenancy as t
    from mediahub.web.auth import UserStore
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha",
                             brand_voice_summary="Bold, energetic, club-focused."))
    UserStore().create(_CAP_OWNER, _CAP_PASSWORD)
    UserStore().create(_CAP_VIEWER, _CAP_PASSWORD)
    t.MembershipStore().add(_CAP_OWNER, "org-alpha", role=t.ROLE_OWNER)
    t.MembershipStore().add(_CAP_VIEWER, "org-alpha", role=t.ROLE_VIEWER)

    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    run_payload = {"run_id": run_id, "profile_id": "org-alpha", "profile_display": "Org Alpha",
                   "meet": {"name": "SECRET ALPHA INVITATIONAL"}, "cards": []}
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "SECRET ALPHA INVITATIONAL", "alpha.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.turn_into import save_pack

    base = tmp_path / "turn_into_packs"
    pack = {"artefacts": [{"captions": {"default": "ORIGINAL ALPHA CAPTION"}}]}
    save_pack(pack, run_id, base_dir=base)
    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as c:
        yield {"wm": wm, "client": c, "run_id": run_id, "pack_id": pack["pack_id"], "pack_base": base}


def _cap_login_pin(client, email):
    r = client.post("/login", data={"email": email, "password": _CAP_PASSWORD})
    assert r.status_code in (302, 303), r.status_code
    r = client.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code in (200, 302, 303), r.get_data(as_text=True)


def _stored_caption(base, run_id, pack_id):
    from mediahub.turn_into import load_pack

    pk = load_pack(run_id, pack_id, base_dir=base)
    return pk["artefacts"][0]["captions"]["default"]


class TestTurnIntoCaptionEditCapGate:
    def test_viewer_cannot_edit_pack_caption(self, bound_pack_world):
        w = bound_pack_world
        c = w["client"]
        _cap_login_pin(c, _CAP_VIEWER)
        url = f"/api/runs/{w['run_id']}/turn-into/{w['pack_id']}/caption"
        r = c.post(url, json={"artefact_index": 0, "caption_key": "default", "text": "HACKED"})
        assert r.status_code == 403, r.get_data(as_text=True)
        assert (r.get_json() or {}).get("error") == "forbidden", r.get_json()
        assert _stored_caption(w["pack_base"], w["run_id"], w["pack_id"]) == "ORIGINAL ALPHA CAPTION"

    def test_owner_can_still_edit_pack_caption(self, bound_pack_world):
        w = bound_pack_world
        c = w["client"]
        _cap_login_pin(c, _CAP_OWNER)
        url = f"/api/runs/{w['run_id']}/turn-into/{w['pack_id']}/caption"
        r = c.post(url, json={"artefact_index": 0, "caption_key": "default", "text": "OWNER EDIT"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _stored_caption(w["pack_base"], w["run_id"], w["pack_id"]) == "OWNER EDIT"
