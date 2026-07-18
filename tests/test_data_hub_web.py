"""Data hub + bulk web surface (roadmap 1.13 build 3)."""

from __future__ import annotations

import io
import json

import pytest


@pytest.fixture
def app_env(app, web_module, tmp_path, monkeypatch):
    # ``app`` / ``web_module`` (conftest) already point DATA_DIR + the derived
    # storage dirs at this test's ``tmp_path`` and build a TESTING app. Keep the
    # no-provider setup so the AI honest-error surfaces stay deterministic.
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    return app, web_module, tmp_path


def _make_profile(pid="club-a"):
    """An unbound org passes the members-only gate; ``_active_profile_id`` needs
    the profile to exist on disk."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.replace("-", " ").title()))


def _login(client, pid="club-a"):
    _make_profile(pid)
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_run(tmp_path, run_id="r1", profile_id="club-a"):
    def ach(swim_id, name, angle, atype):
        return {
            "achievement": {
                "swim_id": swim_id,
                "swimmer_id": "sw-" + swim_id,
                "swimmer_name": name,
                "event": "100m Freestyle",
                "headline": "PB!",
                "type": atype,
                "raw_facts": {"time_str": "1:05.32"},
            },
            "post_angle": angle,
            "rank": 1,
            "quality_band": "strong",
        }

    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {
            "name": "Spring Open",
            "start_date": "2026-03-14",
            "course": "LC",
            "swimmers": {
                "s1": {
                    "first_name": "Maya",
                    "last_name": "Patel",
                    "gender": "F",
                    "identity_confidence": "high",
                },
                "s2": {
                    "first_name": "Sam",
                    "last_name": "Okafor",
                    "gender": "M",
                    "identity_confidence": "high",
                },
            },
            "results": [
                {
                    "swimmer_key": "s1",
                    "distance": 100,
                    "stroke": "FR",
                    "course": "LC",
                    "finals_time_cs": 6532,
                    "place": 1,
                    "status": "completed",
                },
                {
                    "swimmer_key": "s2",
                    "distance": 50,
                    "stroke": "BK",
                    "course": "LC",
                    "finals_time_cs": None,
                    "status": "dq",
                },
            ],
        },
        "our_swim_count": 2,
        "recognition_report": {
            "n_achievements": 2,
            "ranked_achievements": [
                ach("s1", "Maya", "confirmed_official_pb", "pb_confirmed"),
                ach("s2", "Sam", "medal_gold", "medal_gold"),
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
    return run_id


# --------------------------------------------------------------------------- #
# page access + auth
# --------------------------------------------------------------------------- #
def test_data_hub_requires_org(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        r = c.get("/data-hub")
        assert r.status_code == 200
        assert b"Pick an organisation" in r.data


def test_data_hub_index_renders(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.get("/data-hub")
        assert r.status_code == 200
        # canonical singletons + bulk launcher present
        assert b"Athletes" in r.data
        assert b"Club records" in r.data
        assert b"Bulk generate" in r.data
        assert b"Spring Open" in r.data  # run available in the bulk picker


def test_feature_flag_off_shows_unavailable(app_env, monkeypatch):
    app, wm, _ = app_env
    monkeypatch.setattr(wm, "_data_hub_ok", False)
    with app.test_client() as c:
        _login(c)
        r = c.get("/data-hub")
        assert b"unavailable" in r.data.lower()


# --------------------------------------------------------------------------- #
# import / view / export round-trip
# --------------------------------------------------------------------------- #
def test_import_csv_creates_table_and_view(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        csv = b"First,Last,PBs\nMaya,Patel,3\nSam,Okafor,2\n"
        r = c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(csv), "roster.csv")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "/data-hub/table/org" in loc
        # The grid renders the imported values with a provenance badge.
        page = c.get(loc)
        assert page.status_code == 200
        assert b"Maya" in page.data
        assert b"Imported" in page.data  # provenance badge label


def test_import_rejects_bad_extension(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(b"x"), "evil.exe")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        assert "err=" in r.headers["Location"]


def test_import_rejects_row_flood_with_honest_error(app_env):
    """Rows persist one-by-one, so an uncapped 10^5-row CSV would turn the
    import into a multi-minute synchronous request. Past the cap (20k, far
    beyond any club spreadsheet) the import is refused with an honest message
    and nothing is partially imported."""
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        csv = b"a,b\n" + b"1,2\n" * 20_001
        r = c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(csv), "flood.csv")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "err=" in loc and "limit" in loc
        from mediahub.data_hub import store as dh_store

        assert dh_store.list_org_tables("club-a") == []


def test_export_csv_and_xlsx(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        csv = b"First,Last\nMaya,Patel\n"
        loc = c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(csv), "r.csv")},
            content_type="multipart/form-data",
        ).headers["Location"]
        tid = loc.rsplit("/", 1)[-1]
        rc = c.get(f"/data-hub/export/{tid}?fmt=csv")
        assert rc.status_code == 200
        assert "text/csv" in rc.headers["Content-Type"]
        assert b"Maya" in rc.data
        rx = c.get(f"/data-hub/export/{tid}?fmt=xlsx")
        assert rx.status_code == 200
        assert rx.data[:2] == b"PK"


def test_canonical_table_renders(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.get("/data-hub/table/results:r1")
        assert r.status_code == 200
        assert b"Maya" in r.data
        assert b"1:05.32" in r.data  # parsed time formatted


def test_table_not_found_is_404(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        r = c.get("/data-hub/table/orgDOESNOTEXIST")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# derived columns
# --------------------------------------------------------------------------- #
def test_derive_via_form(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        loc = c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(b"First,Last\nMaya,Patel\n"), "r.csv")},
            content_type="multipart/form-data",
        ).headers["Location"]
        tid = loc.rsplit("/", 1)[-1]
        r = c.post(
            f"/api/data-hub/table/{tid}/derive",
            data={
                "output_title": "Full name",
                "derivation_id": "full_name",
                "col1": "first",
                "col2": "last",
            },
        )
        assert r.status_code == 302
        page = c.get(f"/data-hub/table/{tid}")
        assert b"Maya Patel" in page.data
        assert b"Full name" in page.data


def test_derive_via_json(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        tid = (
            c.post(
                "/api/data-hub/import",
                data={"file": (io.BytesIO(b"Name,BirthYear\nMaya,2012\n"), "r.csv")},
                content_type="multipart/form-data",
            )
            .headers["Location"]
            .rsplit("/", 1)[-1]
        )
        r = c.post(
            f"/api/data-hub/table/{tid}/derive",
            json={
                "output_title": "Age",
                "derivation_id": "age_from_birth_year",
                "params": {"birth_year": "birthyear", "ref_year": 2026},
            },
        )
        assert r.status_code == 200
        assert r.get_json()["ok"] is True


def test_derive_key_collision_with_source_column_is_rejected(app_env):
    """A derived output slug that collides with an existing source column must
    400 (never silently overwrite data); recomputing a derived column in place
    still works."""
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        tid = (
            c.post(
                "/api/data-hub/import",
                data={"file": (io.BytesIO(b"Name,PB Time\nMaya,59.10\n"), "r.csv")},
                content_type="multipart/form-data",
            )
            .headers["Location"]
            .rsplit("/", 1)[-1]
        )
        # "PB Time" slugs to pb_time — the imported source column's key
        r = c.post(
            f"/api/data-hub/table/{tid}/derive",
            json={
                "output_title": "PB Time",
                "derivation_id": "initials",
                "params": {"name": "name"},
            },
        )
        assert r.status_code == 400
        assert "already exists" in r.get_json()["error"]
        # source data intact
        page = c.get(f"/data-hub/table/{tid}")
        assert b"59.10" in page.data
        # a derived column can still be recomputed in place (same title twice)
        for _ in range(2):
            ok = c.post(
                f"/api/data-hub/table/{tid}/derive",
                json={
                    "output_title": "Initials",
                    "derivation_id": "initials",
                    "params": {"name": "name"},
                },
            )
            assert ok.status_code == 200 and ok.get_json()["ok"] is True


# --------------------------------------------------------------------------- #
# AI surfaces honest-error with no provider
# --------------------------------------------------------------------------- #
def test_scaffold_honest_error(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        r = c.post("/api/data-hub/scaffold", json={"prompt": "a gala sign-up sheet"})
        assert r.status_code == 503
        assert "AI unavailable" in r.get_json()["error"]


def test_suggest_derivation_honest_error(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/suggest-derivation",
            json={"table_id": "athletes", "prompt": "an age group"},
        )
        assert r.status_code == 503


def test_create_table_json(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/create-table",
            json={
                "title": "Sponsors",
                "columns": [{"title": "Name", "type": "text"}, {"title": "Tier", "type": "text"}],
            },
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] and body["table_id"].startswith("org")


# --------------------------------------------------------------------------- #
# bulk generation queues for review
# --------------------------------------------------------------------------- #
def test_bulk_queues_cards_for_review(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/bulk",
            data={"run_id": "r1", "format_slug": "certificate", "pb_only": "1"},
        )
        assert r.status_code == 302
        assert "msg=" in r.headers["Location"]
    # The PB card is now in the review queue as QUEUE (never auto-approved).
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    states = WorkflowStore(tmp / "runs_v4").load("r1")
    assert "s1" in states  # the PB swimmer
    assert states["s1"].status == CardStatus.QUEUE
    assert "s2" not in states  # the medal-only card wasn't a PB target


def test_bulk_json_returns_job(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.post(
            "/api/data-hub/bulk",
            json={"run_id": "r1", "format_slug": "certificate", "pb_only": True},
        )
        assert r.status_code == 200
        job = r.get_json()["job"]
        job_id = job["job_id"]
        # status endpoint reflects the same job
        s = c.get(f"/api/data-hub/bulk/{job_id}")
        assert s.status_code == 200
        assert s.get_json()["progress"]["n_queued"] == 1


def test_bulk_rejects_cross_tenant_run(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp, profile_id="club-a")
    with app.test_client() as c:
        _login(c, "club-b")  # different org
        r = c.post("/api/data-hub/bulk", json={"run_id": "r1", "format_slug": "certificate"})
        assert r.status_code == 400


# --------------------------------------------------------------------------- #
# tenant isolation on org tables
# --------------------------------------------------------------------------- #
def test_tables_api_lists_canonical_and_org(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        c.post(
            "/api/data-hub/import",
            data={"file": (io.BytesIO(b"Name\nMaya\n"), "r.csv")},
            content_type="multipart/form-data",
        )
        r = c.get("/api/data-hub/tables")
        assert r.status_code == 200
        body = r.get_json()
        canon_ids = {t["table_id"] for t in body["canonical"]}
        assert {"athletes", "records", "meets"} <= canon_ids
        assert len(body["org"]) == 1


def test_delete_org_table_route(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c)
        tid = (
            c.post(
                "/api/data-hub/import",
                data={"file": (io.BytesIO(b"Name\nMaya\n"), "r.csv")},
                content_type="multipart/form-data",
            )
            .headers["Location"]
            .rsplit("/", 1)[-1]
        )
        r = c.post(f"/api/data-hub/table/{tid}/delete")
        assert r.status_code == 302
        # gone afterwards
        assert c.get(f"/data-hub/table/{tid}").status_code == 404


def test_grid_has_accessibility_affordances(app_env):
    app, wm, tmp = app_env
    _seed_run(tmp)
    with app.test_client() as c:
        _login(c)
        r = c.get("/data-hub/table/results:r1")
        assert r.status_code == 200
        html = r.data.decode()
        # Screen-reader caption + column scopes for the data grid.
        assert 'class="dh-sr"' in html
        assert 'scope="col"' in html
        # Provenance badge is announced, not just a hover tooltip.
        assert 'aria-label="Where this came from' in html
        # The filter box is labelled.
        assert 'aria-label="Filter rows in this table"' in html
        # The DQ swim is flagged → the marker carries an aria-label.
        assert 'aria-label="Needs review' in html


def test_org_table_tenant_isolation(app_env):
    app, wm, _ = app_env
    with app.test_client() as c:
        _login(c, "club-a")
        tid = (
            c.post(
                "/api/data-hub/import",
                data={"file": (io.BytesIO(b"Name\nMaya\n"), "r.csv")},
                content_type="multipart/form-data",
            )
            .headers["Location"]
            .rsplit("/", 1)[-1]
        )
    with app.test_client() as c2:
        _login(c2, "club-b")
        r = c2.get(f"/data-hub/table/{tid}")
        assert r.status_code == 404  # club-b can't see club-a's table
