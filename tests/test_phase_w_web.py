"""Phase W web-surface integration tests.

True-integration coverage for the Phase W build (ADR-0016): the Club data
pages (athletes/consent, records, live meet, wraps), magic-link mobile
approvals, the approval-seam hooks (telemetry + records-on-approval), the
W.11/W.13 caption bundle response, and org isolation on every new surface.
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


def _run_payload(run_id: str, profile_id: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Org Alpha",
        "meet": {
            "name": "Spring Open",
            "start_date": "2026-06-06",
            "swimmers": {
                "k1": {
                    "first_name": "Maya",
                    "last_name": "Patel",
                    "club_code": "ALPH",
                    "dob": "2010-04-01",
                },
            },
            "results": [
                {
                    "swimmer_key": "k1",
                    "club_code": "ALPH",
                    "distance": 100,
                    "stroke": "FR",
                    "course": "LC",
                    "finals_time_cs": 6150,
                    "dq": False,
                },
            ],
        },
        "cards": [],
        "parse_warnings": [],
        "detector_summary": {},
        "dispatch_log": {},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_id": "k1",
                        "swimmer_name": "Maya Patel",
                        "event": "100m Freestyle (LC)",
                        "headline": "NEW CLUB RECORD: Maya Patel — 1:01.50",
                        "type": "club_record",
                        "confidence": 0.95,
                        "confidence_label": "high",
                        "raw_facts": {
                            "distance": 100,
                            "stroke": "FR",
                            "course": "LC",
                            "gender": "F",
                            "age_group": "open",
                            "new_time_cs": 6150,
                            "new_time": "1:01.50",
                            "old_time_cs": 6210,
                            "swim_date": "2026-06-06",
                        },
                    },
                    "quality_band": "elite",
                    "priority": 0.95,
                    "post_angle": "club_record",
                    "safe_to_post": {"level": "safe", "reason": "ok"},
                },
            ],
            "n_elite": 1,
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
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

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha", club_codes=["ALPH"]))
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))

    run_id = "run-w-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(_run_payload(run_id, "org-alpha"))
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield {"client": c, "run_id": run_id, "tmp": tmp_path, "wm": wm}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# Pages render, org-gated
# ---------------------------------------------------------------------------


class TestClubDataPages:
    def test_pages_render_for_pinned_org(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        for path, marker in [
            ("/club-data", b"Athletes"),
            ("/athletes", b"Roster"),
            ("/records", b"records sheet"),
            ("/live", b"live-results"),
            ("/wraps", b"Season"),
        ]:
            r = c.get(path)
            assert r.status_code == 200, path
            assert marker in r.data, path

    def test_pages_prompt_without_org(self, env):
        c = env["client"]
        r = c.get("/athletes")
        assert r.status_code == 200
        assert b"Pick an organisation" in r.data

    def test_actions_refused_without_org(self, env):
        c = env["client"]
        assert c.post("/athletes/action", data={"action": "backfill"}).status_code == 403
        assert c.post("/records/action", data={"action": "import"}).status_code == 403


# ---------------------------------------------------------------------------
# W.1/W.2 — athletes flow end-to-end through the web surface
# ---------------------------------------------------------------------------


class TestAthletesFlow:
    def test_backfill_consent_export_merge(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        # Backfill the roster from the seeded run snapshot.
        r = c.post("/athletes/action", data={"action": "backfill"}, follow_redirects=True)
        assert r.status_code == 200
        assert b"Maya Patel" in c.get("/athletes").data

        from mediahub.athletes import get_or_create, list_athletes

        roster = list_athletes("org-alpha")
        assert len(roster) == 1 and roster[0].race_count == 1
        maya = roster[0]

        # Set consent through the form action.
        r = c.post(
            "/athletes/action",
            data={"action": "set_consent", "athlete_id": maya.athlete_id, "level": "initials_only"},
            follow_redirects=True,
        )
        assert b"Consent updated" in r.data
        out = c.get("/athletes/consent.csv")
        assert out.status_code == 200
        assert b"Maya Patel,initials_only" in out.data

        # Merge a stray duplicate identity.
        dup = get_or_create("org-alpha", "Patel, M.")
        r = c.post(
            "/athletes/action",
            data={"action": "merge", "keep_id": maya.athlete_id, "merge_id": dup.athlete_id},
            follow_redirects=True,
        )
        assert b"Merged" in r.data
        assert len(list_athletes("org-alpha")) == 1

    def test_consent_csv_isolated_per_org(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        c.post("/athletes/action", data={"action": "backfill"})
        _pin(c, "org-beta")
        out = c.get("/athletes/consent.csv")
        assert b"Maya Patel" not in out.data


# ---------------------------------------------------------------------------
# W.3 — records via the web + update-on-approval through the workflow API
# ---------------------------------------------------------------------------


class TestRecordsFlow:
    def test_import_and_render(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.post(
            "/records/action",
            data={
                "action": "import",
                "csv_text": "100 Freestyle, LC, F, open, 1:02.10, Erin Jones, 2019-05-01",
            },
            follow_redirects=True,
        )
        assert b"Imported 1 records" in r.data
        page = c.get("/records").data
        assert b"Erin Jones" in page and b"1:02.10" in page

    def test_approval_updates_record_table(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        from mediahub.club_records import records_map, upsert_record

        upsert_record(
            "org-alpha",
            distance=100,
            stroke="FR",
            course="LC",
            gender="F",
            time_cs=6210,
            holder="Erin Jones",
        )
        r = c.post(
            f"/api/workflow/{env['run_id']}/swim-1",
            json={"action": "set_status", "status": "approved"},
        )
        assert r.status_code == 200 and r.get_json()["ok"]
        rec = records_map("org-alpha")[(100, "FR", "LC", "F", "open")]
        assert rec["time_cs"] == 6150 and rec["holder"] == "Maya Patel"

        # W.14: the decision is in the telemetry store with its angle.
        from mediahub.observability.approval_telemetry import preference_summary

        summary = preference_summary("org-alpha", min_events=1)
        assert summary["total_events"] >= 1
        assert any(a["post_angle"] == "club_record" for a in summary["angles"])


# ---------------------------------------------------------------------------
# W.9 — magic-link mobile approvals end-to-end
# ---------------------------------------------------------------------------


class TestMagicLinks:
    def test_mint_requires_run_access(self, env):
        c = env["client"]
        _pin(c, "org-beta")
        assert c.post(f"/api/runs/{env['run_id']}/magic-link").status_code == 404

    def test_phone_flow_end_to_end(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.post(f"/api/runs/{env['run_id']}/magic-link")
        assert r.status_code == 200
        url = r.get_json()["url"]
        path = url.split("://", 1)[-1].split("/", 1)[1]
        path = "/" + path

        # The lite page renders with no session at all (fresh client).
        env["wm"].app.config["TESTING"] = True
        with env["wm"].app.test_client() as anon:
            page = anon.get(path)
            assert page.status_code == 200
            assert b"Maya Patel" in page.data or b"NEW CLUB RECORD" in page.data
            assert b"Approve" in page.data

            # Approve from the phone.
            act = anon.post(path + "/card/swim-1", data={"action": "approve"})
            assert act.status_code == 302

        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(Path(env["tmp"]) / "runs_v4")
        state = ws.load(env["run_id"]).get("swim-1")
        assert state is not None and state.status.value == "approved"
        assert "magic link" in (state.notes or "")

        # Audit parity: the action is in the org's audit ledger.
        from mediahub.workflow.autonomy import AuditLog

        entries = AuditLog().read("org-alpha")
        kinds = {e.get("kind") for e in entries}
        assert "magic_link_action" in kinds

    def test_revoked_link_dies(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        url = c.post(f"/api/runs/{env['run_id']}/magic-link").get_json()["url"]
        path = "/" + url.split("://", 1)[-1].split("/", 1)[1]
        assert c.post(f"/api/runs/{env['run_id']}/magic-link/revoke").status_code == 200
        with env["wm"].app.test_client() as anon:
            r = anon.get(path)
            assert r.status_code == 410
            assert b"revoked" in r.data

    def test_garbage_token_is_410(self, env):
        with env["wm"].app.test_client() as anon:
            assert anon.get("/m/not-a-real-token").status_code == 410


# ---------------------------------------------------------------------------
# W.12 — certificates export guards
# ---------------------------------------------------------------------------


class TestCertificates:
    def test_cross_org_404(self, env):
        c = env["client"]
        _pin(c, "org-beta")
        assert c.get(f"/pack/{env['run_id']}/certificates.zip").status_code == 404

    def test_no_approved_cards_is_honest(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/pack/{env['run_id']}/certificates.zip")
        assert r.status_code == 200
        assert b"No approved cards yet" in r.data


# ---------------------------------------------------------------------------
# W.11/W.13 — caption endpoint returns the bundle fields
# ---------------------------------------------------------------------------


class TestCaptionBundleEndpoint:
    def test_alt_text_and_welsh_in_response(self, env, monkeypatch):
        c = env["client"]
        _pin(c, "org-alpha")
        from mediahub.web.club_profile import load_profile, save_profile

        prof = load_profile("org-alpha")
        prof.language = "bilingual"
        save_profile(prof)

        import mediahub.media_ai.llm as llm
        import mediahub.web.ai_caption as ac

        monkeypatch.setattr(llm, "is_available", lambda: True)
        monkeypatch.setattr(
            ac,
            "call_claude",
            lambda **kw: json.dumps(
                {
                    "caption": "Record smashed by Maya!",
                    "alt_text": "Maya Patel, 100m Freestyle, 1:01.50 — new club record.",
                    "caption_cy": "Record y clwb wedi'i chwalu gan Maya!",
                }
            ),
        )
        r = c.post(f"/api/runs/{env['run_id']}/swim/swim-1/caption?tone=ai")
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["caption"] == "Record smashed by Maya!"
        assert "1:01.50" in body["alt_text"]
        assert body["caption_cy"].startswith("Record y clwb")
        assert body["language"] == "bilingual"


# ---------------------------------------------------------------------------
# W.4/W.13 — organisation form saves language + standards picks
# ---------------------------------------------------------------------------


class TestOrganisationFormFields:
    def test_language_and_standards_roundtrip(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.post(
            "/organisation",
            data={
                "action": "save",
                "profile_id": "org-alpha",
                "display_name": "Org Alpha",
                "language": "cy",
                "important_standards": ["BUCS_LC_2026_27_CT"],
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        from mediahub.web.club_profile import load_profile

        prof = load_profile("org-alpha")
        assert prof.language == "cy"
        assert prof.important_standards == ["BUCS_LC_2026_27_CT"]

    def test_bad_language_falls_back(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        c.post(
            "/organisation",
            data={
                "action": "save",
                "profile_id": "org-alpha",
                "display_name": "Org Alpha",
                "language": "klingon",
            },
        )
        from mediahub.web.club_profile import load_profile

        assert load_profile("org-alpha").language == "en"
