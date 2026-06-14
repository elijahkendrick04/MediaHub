"""tests/test_ui19_bulk_actions.py — UI 1.9 multi-select + bulk actions.

Covers the two surfaces the roadmap item names — the Media library and the
review queue — across both halves of "pure HTML form multi-select with
progressive JS enhancement":

  * the new content-negotiated bulk endpoints (JSON AJAX *and* no-JS form POST),
  * per-item isolation (one org can't bulk-act on another's photos / runs),
  * the safeguarding skip on bulk photo-approve,
  * the consent gate firing per-card on bulk card-approve without aborting,
  * and the rendered HTML actually carrying the checkboxes / select-all / bulk
    bar / form wiring (a 200 shell would otherwise pass a status-only check).
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixtures + seeding helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fresh DATA_DIR with two saved orgs; session pinned to org-test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    save_profile(ClubProfile(profile_id="org-other", display_name="Other Club"))

    app = wm.create_app()
    app.config["TESTING"] = True
    # Gate bypassed under TESTING (web.py:_gate_until_org_ready) — these tests
    # exercise the bulk actions + active-profile scoping, not the setup gate.

    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path, "app": app}


def _seed_asset(tmp_path, profile_id="org-test", *, filename="p.jpg",
                permission_status="approved_by_club", approval_status="draft",
                safe_for_minors=True, body=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"):
    from mediahub.media_library.store import get_store
    from mediahub.media_library.models import MediaAsset

    p = tmp_path / f"{profile_id}_{uuid.uuid4().hex[:6]}_{filename}"
    p.write_bytes(body)
    asset = MediaAsset(
        id="", filename=filename, path=str(p), type="athlete_photo",
        profile_id=profile_id, permission_status=permission_status,
        approval_status=approval_status, safe_for_minors=safe_for_minors,
    )
    return get_store().save(asset).id, p


def _make_run_payload(profile_id, swim_ids):
    run_id = "run-ui19-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "UI19 BULK TEST"},
        "cards": [{"card_id": f"card-{s}", "swim_id": s, "id": f"card-{s}"} for s in swim_ids],
        "trust": {"score": 0.9},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": s,
                        "swimmer_name": f"Swimmer {i}",
                        "event": "100 Free",
                        "headline": f"PB for Swimmer {i}",
                        "type": "pb",
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, s in enumerate(swim_ids)
            ],
            "n_achievements": len(swim_ids),
            "n_swims_analysed": len(swim_ids),
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


def _seed_run(tmp_path, wm, profile_id, swim_ids):
    payload = _make_run_payload(profile_id, swim_ids)
    run_id = payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


# ===========================================================================
# Module-level request helpers
# ===========================================================================

class TestRequestHelpers:
    def test_bulk_ids_dedup_and_order_json(self, env):
        wm = env["wm"]
        with env["app"].test_request_context(json={"ids": ["a", "b", "a", "", "c"]}):
            from flask import request
            assert wm._bulk_ids_from_request(request, "ids", "asset_ids") == ["a", "b", "c"]

    def test_bulk_ids_from_form_multiselect(self, env):
        wm = env["wm"]
        with env["app"].test_request_context(
            method="POST", data={"card_ids": ["x", "y", "y"]}
        ):
            from flask import request
            assert wm._bulk_ids_from_request(request, "ids", "card_ids") == ["x", "y"]

    def test_wants_json_negotiation(self, env):
        wm = env["wm"]
        with env["app"].test_request_context(json={"ids": []}):
            from flask import request
            assert wm._req_wants_json(request) is True
        with env["app"].test_request_context(method="POST", data={"ids": "z"}):
            from flask import request
            assert wm._req_wants_json(request) is False


# ===========================================================================
# Media library — bulk delete
# ===========================================================================

class TestMediaBulkDelete:
    def test_json_deletes_selected(self, env):
        c, tp = env["client"], env["tmp_path"]
        a1, p1 = _seed_asset(tp)
        a2, p2 = _seed_asset(tp)
        a3, p3 = _seed_asset(tp)
        r = c.post("/api/media-library/bulk-delete", json={"ids": [a1, a2]})
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True and body["n_ok"] == 2
        assert set(body["deleted"]) == {a1, a2}
        from mediahub.media_library.store import get_store
        s = get_store()
        assert s.get(a1) is None and s.get(a2) is None
        assert s.get(a3) is not None  # untouched
        assert not p1.exists() and not p2.exists() and p3.exists()

    def test_form_post_redirects_and_deletes(self, env):
        c, tp = env["client"], env["tmp_path"]
        a1, _ = _seed_asset(tp)
        r = c.post("/api/media-library/bulk-delete", data={"asset_ids": [a1]})
        assert r.status_code == 302
        assert "/media-library" in r.headers["Location"]
        from mediahub.media_library.store import get_store
        assert get_store().get(a1) is None

    def test_empty_selection_json_400(self, env):
        r = env["client"].post("/api/media-library/bulk-delete", json={"ids": []})
        assert r.status_code == 400
        assert r.get_json()["error"] == "no_selection"

    def test_foreign_asset_reported_forbidden_not_deleted(self, env):
        c, tp = env["client"], env["tmp_path"]
        mine, _ = _seed_asset(tp, "org-test")
        theirs, ppath = _seed_asset(tp, "org-other")
        r = c.post("/api/media-library/bulk-delete", json={"ids": [mine, theirs]})
        assert r.status_code == 200
        body = r.get_json()
        assert body["n_ok"] == 1 and body["deleted"] == [mine]
        forbidden = [x for x in body["results"] if x["id"] == theirs][0]
        assert forbidden["ok"] is False and forbidden["error"] == "forbidden"
        from mediahub.media_library.store import get_store
        assert get_store().get(theirs) is not None  # not reachable cross-org
        assert ppath.exists()

    def test_unknown_id_reported_not_found(self, env):
        r = env["client"].post("/api/media-library/bulk-delete", json={"ids": ["ma_nope"]})
        assert r.status_code == 200
        body = r.get_json()
        assert body["n_ok"] == 0
        assert body["results"][0]["error"] == "not_found"


# ===========================================================================
# Media library — bulk approve (+ safeguarding skip)
# ===========================================================================

class TestMediaBulkApprove:
    def test_sets_approval_status(self, env):
        c, tp = env["client"], env["tmp_path"]
        a1, _ = _seed_asset(tp, approval_status="draft")
        a2, _ = _seed_asset(tp, approval_status="pending")
        r = c.post("/api/media-library/bulk-approve", json={"ids": [a1, a2]})
        assert r.status_code == 200 and r.get_json()["n_ok"] == 2
        from mediahub.media_library.store import get_store
        s = get_store()
        assert s.get(a1).approval_status == "approved"
        assert s.get(a2).approval_status == "approved"

    def test_safeguarding_blocks_skipped(self, env):
        c, tp = env["client"], env["tmp_path"]
        ok, _ = _seed_asset(tp, approval_status="draft")
        consent, _ = _seed_asset(tp, permission_status="needs_parental_consent")
        donotuse, _ = _seed_asset(tp, permission_status="do_not_use")
        minors, _ = _seed_asset(tp, safe_for_minors=False)
        r = c.post(
            "/api/media-library/bulk-approve",
            json={"ids": [ok, consent, donotuse, minors]},
        )
        body = r.get_json()
        assert body["n_ok"] == 1 and body["n_skipped"] == 3
        assert body["approved"] == [ok]
        from mediahub.media_library.store import get_store
        s = get_store()
        # The three safeguarding-flagged assets stay un-promoted.
        assert s.get(consent).approval_status != "approved"
        assert s.get(donotuse).approval_status != "approved"
        assert s.get(minors).approval_status != "approved"

    def test_empty_selection_400(self, env):
        r = env["client"].post("/api/media-library/bulk-approve", json={"ids": []})
        assert r.status_code == 400


# ===========================================================================
# Media library — bulk export (ZIP of originals)
# ===========================================================================

class TestMediaBulkExport:
    def test_zip_contains_selected_originals(self, env):
        c, tp = env["client"], env["tmp_path"]
        a1, _ = _seed_asset(tp, filename="one.jpg", body=b"AAA-one")
        a2, _ = _seed_asset(tp, filename="two.jpg", body=b"BBB-two")
        _other, _ = _seed_asset(tp, "org-other", filename="hidden.jpg")
        r = c.post("/api/media-library/bulk-export", json={"ids": [a1, a2]})
        assert r.status_code == 200
        assert r.mimetype == "application/zip"
        assert "attachment" in r.headers.get("Content-Disposition", "")
        zf = zipfile.ZipFile(io.BytesIO(r.data))
        names = zf.namelist()
        assert len(names) == 2
        contents = sorted(zf.read(n) for n in names)
        assert contents == sorted([b"AAA-one", b"BBB-two"])

    def test_foreign_asset_excluded_from_zip(self, env):
        c, tp = env["client"], env["tmp_path"]
        mine, _ = _seed_asset(tp, "org-test", filename="mine.jpg", body=b"mine")
        theirs, _ = _seed_asset(tp, "org-other", filename="theirs.jpg", body=b"theirs")
        r = c.post("/api/media-library/bulk-export", json={"ids": [mine, theirs]})
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.data))
        assert len(zf.namelist()) == 1
        assert zf.read(zf.namelist()[0]) == b"mine"

    def test_nothing_exportable_404(self, env):
        r = env["client"].post(
            "/api/media-library/bulk-export", json={"ids": ["ma_missing"]}
        )
        assert r.status_code == 404
        assert r.get_json()["error"] == "nothing_to_export"

    def test_empty_selection_400(self, env):
        r = env["client"].post("/api/media-library/bulk-export", json={"ids": []})
        assert r.status_code == 400


# ===========================================================================
# Review queue — bulk status (approve / reject)
# ===========================================================================

class TestReviewBulkStatus:
    def test_bulk_approve_multiple(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1", "s2"])
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": ["s0", "s2"], "status": "approved"},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True and body["n_ok"] == 2 and body["n_blocked"] == 0
        assert body["summary"]["approved"] == 2
        from mediahub.workflow.status import CardStatus
        states = wm._get_wf_store().load(run_id)
        assert states["s0"].status == CardStatus.APPROVED
        assert states["s2"].status == CardStatus.APPROVED
        assert "s1" not in states or states["s1"].status != CardStatus.APPROVED

    def test_bulk_reject(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1"])
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": ["s0", "s1"], "status": "rejected"},
        )
        assert r.status_code == 200 and r.get_json()["summary"]["rejected"] == 2

    def test_form_post_redirects(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1"])
        # No-JS path: op carries the target status, card_ids the selection.
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            data={"op": "approved", "card_ids": ["s0", "s1"]},
        )
        assert r.status_code == 302 and f"/review/{run_id}" in r.headers["Location"]
        from mediahub.workflow.status import CardStatus
        states = wm._get_wf_store().load(run_id)
        assert states["s0"].status == CardStatus.APPROVED

    def test_invalid_status_400(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0"])
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": ["s0"], "status": "banana"},
        )
        assert r.status_code == 400

    def test_non_string_status_is_400_not_500(self, env):
        """A fuzzed/AJAX body with a non-string status must 400, never 500
        (the contract sweep sends arbitrary JSON types)."""
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0"])
        for bad in (123, ["approved"], {"x": 1}):
            r = c.post(
                f"/api/runs/{run_id}/cards/bulk-status",
                json={"ids": ["s0"], "status": bad},
            )
            assert r.status_code == 400, f"status={bad!r} gave {r.status_code}"

    def test_empty_selection_400(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0"])
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": [], "status": "approved"},
        )
        assert r.status_code == 400

    def test_foreign_run_404(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-other", ["s0"])  # belongs to another org
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": ["s0"], "status": "approved"},
        )
        assert r.status_code == 404
        from mediahub.workflow.status import CardStatus
        states = wm._get_wf_store().load(run_id)
        assert "s0" not in states or states["s0"].status != CardStatus.APPROVED

    def test_consent_gate_blocks_one_not_the_batch(self, env, monkeypatch):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s_ok", "s_blocked"])

        import mediahub.compliance.gate as gate

        def fake_block(profile_id, card):
            ach = (card or {}).get("achievement") or {}
            return "minor: parental consent missing" if ach.get("swim_id") == "s_blocked" else None

        monkeypatch.setattr(gate, "consent_block_reason_for_card", fake_block)
        r = c.post(
            f"/api/runs/{run_id}/cards/bulk-status",
            json={"ids": ["s_ok", "s_blocked"], "status": "approved"},
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["n_ok"] == 1 and body["n_blocked"] == 1
        blocked = [x for x in body["results"] if x["id"] == "s_blocked"][0]
        assert blocked["ok"] is False and blocked["error"] == "consent_blocked"
        from mediahub.workflow.status import CardStatus
        states = wm._get_wf_store().load(run_id)
        assert states["s_ok"].status == CardStatus.APPROVED
        assert "s_blocked" not in states or states["s_blocked"].status != CardStatus.APPROVED


# ===========================================================================
# Review queue — bulk export (selected cards as JSON)
# ===========================================================================

class TestReviewBulkExport:
    def test_exports_only_selected_cards(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1", "s2"])
        r = c.post(f"/api/runs/{run_id}/cards/bulk-export", json={"ids": ["s0", "s2"]})
        assert r.status_code == 200
        assert r.mimetype == "application/json"
        assert "attachment" in r.headers.get("Content-Disposition", "")
        data = json.loads(r.data)
        assert data["run_id"] == run_id
        assert data["requested"] == 2 and data["exported"] == 2
        ids = sorted(card["card_id"] for card in data["cards"])
        assert ids == ["s0", "s2"]

    def test_status_folded_in(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1"])
        from mediahub.workflow.status import CardStatus
        wm._get_wf_store().set_status(run_id, "s0", CardStatus.APPROVED)
        r = c.post(f"/api/runs/{run_id}/cards/bulk-export", json={"ids": ["s0", "s1"]})
        cards = {card["card_id"]: card for card in json.loads(r.data)["cards"]}
        assert cards["s0"]["status"] == "approved"
        assert cards["s1"]["status"] == "queue"

    def test_foreign_run_404(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-other", ["s0"])
        r = c.post(f"/api/runs/{run_id}/cards/bulk-export", json={"ids": ["s0"]})
        assert r.status_code == 404

    def test_empty_selection_400(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0"])
        r = c.post(f"/api/runs/{run_id}/cards/bulk-export", json={"ids": []})
        assert r.status_code == 400


# ===========================================================================
# Rendered HTML — the progressive-enhancement scaffolding is actually present
# ===========================================================================

class TestMediaLibraryHtml:
    def test_page_has_multiselect_scaffolding(self, env):
        c, tp = env["client"], env["tmp_path"]
        aid, _ = _seed_asset(tp)
        body = c.get("/media-library").get_data(as_text=True)
        assert 'id="mh-ml-bulk"' in body                      # wrapping form
        assert 'data-mh-bulkbar="media"' in body              # bulk bar
        assert 'id="mh-ml-all"' in body                       # select-all
        assert 'class="mh-row-check"' in body                 # per-row checkbox
        assert f'value="{aid}"' in body                       # checkbox carries id
        assert "/api/media-library/bulk-delete" in body
        assert "/api/media-library/bulk-approve" in body
        assert "/api/media-library/bulk-export" in body

    def test_row_delete_uses_formaction_not_nested_form(self, env):
        """Per-row delete became a formaction submit so the bulk form isn't nested."""
        c, tp = env["client"], env["tmp_path"]
        aid, _ = _seed_asset(tp)
        body = c.get("/media-library").get_data(as_text=True)
        # The per-row delete still reaches the single-delete route, via formaction.
        assert f'formaction="/api/media-library/{aid}/delete"' in body
        # …and it is NOT a nested <form> inside the bulk form (invalid HTML +
        # unpredictable submission). The first </form> after the bulk form opens
        # is the bulk form's own close, so its inner slice must hold no <form.
        start = body.index('id="mh-ml-bulk"')
        inner = body[start:body.index("</form>", start)]
        assert "<form" not in inner, "bulk form must not contain a nested form"


class TestReviewHtml:
    def test_page_has_multiselect_scaffolding(self, env):
        c, tp, wm = env["client"], env["tmp_path"], env["wm"]
        run_id = _seed_run(tp, wm, "org-test", ["s0", "s1"])
        body = c.get(f"/review/{run_id}").get_data(as_text=True)
        assert 'id="mh-review-bulk"' in body
        assert 'data-mh-bulkbar="review"' in body
        assert 'id="mh-rv-all"' in body
        assert 'class="mh-row-check"' in body
        assert 'value="s0"' in body and 'value="s1"' in body
        assert f"/api/runs/{run_id}/cards/bulk-status" in body
        assert f"/api/runs/{run_id}/cards/bulk-export" in body
        # The shared progressive-enhancement JS is wired in.
        assert "data-mh-bulkbar" in body and "mhRecountReview" in body
