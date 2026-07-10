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
            ("/athletes", b"Roster"),
            ("/records", b"records sheet"),
            ("/live", b"live-results"),
            ("/wraps", b"Season"),
        ]:
            r = c.get(path)
            assert r.status_code == 200, path
            assert marker in r.data, path

    def test_club_data_tab_redirects_to_settings(self, env):
        # The Club-data top-nav tab was retired; its old URL now redirects
        # into Settings (records, athletes, etc. live there / on Create).
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.get("/club-data", follow_redirects=False)
        assert r.status_code == 302
        assert "/settings" in r.headers["Location"]

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
    def _arm(self, monkeypatch, payload: dict):
        import mediahub.media_ai.llm as llm
        import mediahub.web.ai_caption as ac

        monkeypatch.setattr(llm, "is_available", lambda: True)
        monkeypatch.setattr(ac, "call_claude", lambda **kw: json.dumps(payload))

    def _set_language(self, language: str):
        from mediahub.web.club_profile import load_profile, save_profile

        prof = load_profile("org-alpha")
        prof.language = language
        save_profile(prof)

    def test_alt_text_and_welsh_in_response(self, env, monkeypatch):
        c = env["client"]
        _pin(c, "org-alpha")
        # Legacy persisted value: pre-registry profiles stored "bilingual".
        self._set_language("bilingual")
        self._arm(
            monkeypatch,
            {
                "caption": "Record smashed by Maya!",
                "alt_text": "Maya Patel, 100m Freestyle, 1:01.50 — new club record.",
                "caption_secondary": "Record y clwb wedi'i chwalu gan Maya!",
            },
        )
        r = c.post(f"/api/runs/{env['run_id']}/swim/swim-1/caption?tone=ai")
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["caption"] == "Record smashed by Maya!"
        assert "1:01.50" in body["alt_text"]
        assert body["caption_secondary"].startswith("Record y clwb")
        assert body["secondary_language"] == "cy"
        assert body["secondary_language_label"] == "Cymraeg"
        assert body["secondary_rtl"] is False
        assert body["language"] == "en+cy"  # legacy value normalised

    def test_rtl_bilingual_response_metadata(self, env, monkeypatch):
        c = env["client"]
        _pin(c, "org-alpha")
        self._set_language("en+ur")
        self._arm(
            monkeypatch,
            {
                "caption": "Maya storms to 1:01.50!",
                "alt_text": "Maya Patel, 100m Freestyle, 1:01.50.",
                "caption_secondary": "مایا نے 1:01.50 کا ریکارڈ بنایا!",
            },
        )
        r = c.post(f"/api/runs/{env['run_id']}/swim/swim-1/caption?tone=ai")
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["secondary_language"] == "ur"
        assert body["secondary_language_label"] == "اردو"
        assert body["secondary_rtl"] is True
        assert body["language"] == "en+ur"

    def test_bundle_translation_is_persisted_on_the_card(self, env, monkeypatch):
        """The bilingual bundle's side-by-side translation must be SAVED on the
        card (like /translate does), so approving the card approves the pair and
        it rides into exports — not dropped after the review render."""
        import mediahub.web.web as webmod
        from mediahub.workflow.status import CardStatus

        c = env["client"]
        _pin(c, "org-alpha")
        self._set_language("en+cy")
        self._arm(
            monkeypatch,
            {
                "caption": "Record smashed by Maya!",
                "alt_text": "Maya Patel, 100m Freestyle, 1:01.50.",
                "caption_secondary": "Record y clwb wedi'i chwalu gan Maya!",
            },
        )
        r = c.post(f"/api/runs/{env['run_id']}/swim/swim-1/caption?tone=ai")
        assert r.status_code == 200, r.get_json()

        ws = webmod._get_wf_store()
        states = ws.load(env["run_id"])
        state = states.get("swim-1")
        assert state is not None and state.translations, "translation not persisted"
        variant = state.translations.get("cy")
        assert variant is not None, state.translations
        assert variant["slots"]["caption"].startswith("Record y clwb")
        assert variant["language_label"] == "Cymraeg"
        assert variant["rtl"] is False
        # Persisting a translation must not flip the card's status.
        assert state.status == CardStatus.QUEUE


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

    def test_bilingual_pair_roundtrip(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        c.post(
            "/organisation",
            data={
                "action": "save",
                "profile_id": "org-alpha",
                "display_name": "Org Alpha",
                "language": "en+bn",
            },
        )
        from mediahub.web.club_profile import load_profile

        assert load_profile("org-alpha").language == "en+bn"

    def test_legacy_bilingual_value_normalised_on_save(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        c.post(
            "/organisation",
            data={
                "action": "save",
                "profile_id": "org-alpha",
                "display_name": "Org Alpha",
                "language": "bilingual",
            },
        )
        from mediahub.web.club_profile import load_profile

        assert load_profile("org-alpha").language == "en+cy"

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

    def test_settings_picker_lists_registry_languages(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        html = c.get("/organisation").data.decode("utf-8")
        # Single languages and English-led bilingual pairs, registry-driven.
        assert 'value="ga"' in html and "Gaeilge (Irish)" in html
        assert 'value="en+cy"' in html and "English + Cymraeg (Welsh)" in html
        assert 'value="zh"' in html and "中文" in html
        # The legacy non-registry value is no longer offered as an option.
        assert 'value="bilingual"' not in html


# ---------------------------------------------------------------------------
# W.7 — Live meet page + action (audit/live-meet)
# ---------------------------------------------------------------------------


def _lenex_two_swims() -> bytes:
    """A minimal LENEX .lef the interpreter parses natively (2 timed swims)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><LENEX version="3.0">'
        '<CONSTRUCTOR name="t" registration="t" version="1.0">'
        '<CONTACT email="t@t.t"/></CONSTRUCTOR>'
        '<MEETS><MEET name="Live Test Gala 2026" city="Swansea" nation="GBR" course="LCM">'
        '<SESSIONS><SESSION number="1" date="2026-06-13"><EVENTS>'
        '<EVENT eventid="1" number="1" gender="M">'
        '<SWIMSTYLE distance="100" relaycount="1" stroke="FREE"/>'
        '<AGEGROUPS><AGEGROUP agegroupid="1" agemin="-1" agemax="-1"><RANKINGS>'
        '<RANKING place="1" resultid="101"/></RANKINGS></AGEGROUP></AGEGROUPS></EVENT>'
        '<EVENT eventid="2" number="2" gender="F">'
        '<SWIMSTYLE distance="50" relaycount="1" stroke="BREAST"/>'
        '<AGEGROUPS><AGEGROUP agegroupid="2" agemin="-1" agemax="-1"><RANKINGS>'
        '<RANKING place="1" resultid="201"/></RANKINGS></AGEGROUP></AGEGROUPS></EVENT>'
        "</EVENTS></SESSION></SESSIONS><CLUBS>"
        '<CLUB name="Test SC" code="TEST" nation="GBR"><ATHLETES>'
        '<ATHLETE athleteid="a101" firstname="Calum" lastname="Reid" gender="M" birthdate="2008-01-01">'
        '<RESULTS><RESULT resultid="101" eventid="1" swimtime="00:00:55.43"/></RESULTS></ATHLETE>'
        '<ATHLETE athleteid="a201" firstname="Mhairi" lastname="Watt" gender="M" birthdate="2008-01-01">'
        '<RESULTS><RESULT resultid="201" eventid="2" swimtime="00:00:41.07"/></RESULTS></ATHLETE>'
        "</ATHLETES></CLUB></CLUBS></MEET></MEETS></LENEX>"
    ).encode("utf-8")


class TestLiveMeet:
    _URL = "https://results.example.org.uk/live/index.htm"

    def _create(self, c, **over):
        data = {
            "action": "create",
            "url": self._URL,
            "label": "Test gala",
            "interval_minutes": "5",
            "hours": "12",
        }
        data.update(over)
        return c.post("/live/action", data=data)

    def test_real_runner_cards_a_poll(self, env, monkeypatch):
        """P0 regression (LM-RUNNER-DEAD): the production runner registered on
        the scheduler must actually run the pipeline and persist a run. Before
        the fix _live_watch_runner imported a non-existent module and called
        run_pipeline_v4 positionally against a keyword-only signature, so every
        real poll raised, no run was ever persisted, and no card ever queued."""
        import mediahub.scheduler as scheduler
        from mediahub.results_fetch import live_watch as lw

        c, tmp, wm = env["client"], env["tmp"], env["wm"]
        _pin(c, "org-alpha")
        assert self._create(c).status_code == 302
        watches = lw.list_watches("org-alpha")
        assert len(watches) == 1
        w = watches[0]

        # Feed the poller our fixture instead of hitting the network; the real
        # _live_watch_runner is baked into the scheduler handler by create_app.
        monkeypatch.setattr(lw, "_default_fetcher", lambda url: _lenex_two_swims())
        assert lw.TASK_TYPE in scheduler.registered_task_types()
        scheduler._REGISTRY[lw.TASK_TYPE]({})

        got = lw.get_watch(w.id)
        assert got.last_error == "", got.last_error  # runner did NOT fail
        assert got.new_swims_total == 2  # both timed swims carded
        # The pipeline persisted a run at the watch's run_id, so "Review cards"
        # resolves instead of dead-ending on "Run not found".
        assert (tmp / "runs_v4" / f"{w.run_id}.json").exists()
        assert wm._load_run(w.run_id) is not None

    def test_prohibited_url_shows_error_banner_not_success(self, env):
        """LM-BANNER-ALWAYS-GREEN: a rejected create must surface as an amber
        error (?err=), never a green success (?msg=)."""
        c = env["client"]
        _pin(c, "org-alpha")
        r = self._create(c, url="https://www.swimrankings.net/x")
        assert r.status_code == 302
        assert "err=" in r.headers["Location"] and "msg=" not in r.headers["Location"]
        page = c.get(r.headers["Location"]).data.decode("utf-8")
        assert "Could not start the watch" in page
        assert 'class="tag warn"' in page  # amber, not green "tag good"

    def test_non_numeric_interval_defaults_no_leak(self, env):
        """The interval parse must not leak a raw Python ValueError string; a
        bad value cleanly defaults and the watch is created."""
        from mediahub.results_fetch import live_watch as lw

        c = env["client"]
        _pin(c, "org-alpha")
        r = self._create(c, interval_minutes="abc")
        assert r.status_code == 302
        assert "invalid literal for int" not in r.headers["Location"]
        assert "msg=" in r.headers["Location"]
        watches = lw.list_watches("org-alpha")
        assert len(watches) == 1 and watches[0].interval_minutes == 5

    def test_huge_interval_no_500(self, env):
        """LM-INTERVAL-OVERFLOW-500: an absurd interval must not 500 (SQLite
        OverflowError); it is clamped to the ceiling."""
        from mediahub.results_fetch import live_watch as lw

        c = env["client"]
        _pin(c, "org-alpha")
        r = self._create(c, interval_minutes="99999999999999999999")
        assert r.status_code == 302  # not a 500
        watches = lw.list_watches("org-alpha")
        assert len(watches) == 1
        assert watches[0].interval_minutes == lw.MAX_INTERVAL_MINUTES

    def test_duplicate_url_reuses_watch(self, env):
        """LM-DUP-WATCH-POLITENESS: a repeat of the same URL for one org must
        not spawn a second active watch doubling the poll rate."""
        from mediahub.results_fetch import live_watch as lw

        c = env["client"]
        _pin(c, "org-alpha")
        assert self._create(c).status_code == 302
        r2 = self._create(c)
        assert r2.status_code == 302
        assert (
            "Already+watching" in r2.headers["Location"]
            or "Already watching" in r2.headers["Location"]
        )
        assert len(lw.list_watches("org-alpha")) == 1

    def test_review_link_hidden_until_carded(self, env):
        """LM-REVIEW-LINK-NO-RUN: a watch with no cards yet shows "No cards yet",
        not an active Review link that dead-ends on "Run not found"."""
        c = env["client"]
        _pin(c, "org-alpha")
        self._create(c)
        page = c.get("/live").data.decode("utf-8")
        assert "No cards yet" in page
        assert "Review cards" not in page

    def test_form_labels_are_associated(self, env):
        """LM-LABEL-NOT-ASSOCIATED: every create-form control has a for/id pair."""
        c = env["client"]
        _pin(c, "org-alpha")
        page = c.get("/live").data.decode("utf-8")
        for cid in ("lm-url", "lm-label", "lm-interval", "lm-hours"):
            assert f'for="{cid}"' in page and f'id="{cid}"' in page

    def test_stop_unknown_watch_is_amber_error(self, env):
        c = env["client"]
        _pin(c, "org-alpha")
        r = c.post("/live/action", data={"action": "stop", "watch_id": "nope"})
        assert r.status_code == 302
        assert "err=" in r.headers["Location"]
        assert (
            "Watch+not+found" in r.headers["Location"] or "Watch not found" in r.headers["Location"]
        )

    def test_action_requires_org(self, env):
        c = env["client"]
        assert self._create(c).status_code == 403
