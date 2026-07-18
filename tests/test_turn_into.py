"""
test_turn_into.py — deterministic-mode tests for the Turn-Into engine.

All tests run with ``deterministic=True`` so they never call the LLM and the
pack contents are stable.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import pytest


def _tempdir() -> "tempfile.TemporaryDirectory[str]":
    """A TemporaryDirectory tolerant of teardown races.

    These tests point DATA_DIR at the temp dir and build the web app, which
    starts the ``heartbeat-writer`` daemon. That daemon may write the uptime
    store into DATA_DIR *after* the test body, racing ``rmtree`` →
    ``OSError: [Errno 39] Directory not empty``. ``ignore_cleanup_errors``
    (3.10+) makes teardown best-effort instead of flaking the test.
    """
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def _run_data() -> dict:
    """Build a minimal but realistic run_data shape."""
    return {
        "run_id": "test-run",
        "profile_id": "test-profile",
        "profile_display": "Test Club",
        "meet": {
            "name": "Spring Open 2026",
            "start_date": "2026-04-10",
            "end_date": "2026-04-11",
            "course": "LC",
            "venue": "Demo Pool",
        },
        "recognition_report": {
            "meet_name": "Spring Open 2026",
            "n_swims_analysed": 18,
            "ranked_achievements": [
                {
                    "achievement": {
                        "swimmer_name": "Alice Lee",
                        "swimmer_id": "s1",
                        "event": "100m Freestyle",
                        "time": "57.95",
                        "headline": "New PB in 100 Free",
                        "type": "pb_confirmed",
                        "raw_facts": {"time_str": "57.95"},
                    },
                    "priority": 0.92,
                    "quality_band": "elite",
                },
                {
                    "achievement": {
                        "swimmer_name": "Bob Khan",
                        "swimmer_id": "s2",
                        "event": "200m Backstroke",
                        "time": "2:08.10",
                        "headline": "Silver medal",
                        "type": "medal_silver",
                        "raw_facts": {},
                    },
                    "priority": 0.80,
                    "quality_band": "strong",
                },
                {
                    "achievement": {
                        "swimmer_name": "Cara Diaz",
                        "swimmer_id": "s3",
                        "event": "50m Butterfly",
                        "time": "28.50",
                        "headline": "First time under 29",
                        "type": "first_sub_barrier",
                        "raw_facts": {},
                    },
                    "priority": 0.65,
                    "quality_band": "strong",
                },
                {
                    "achievement": {
                        "swimmer_name": "Dee Patel",
                        "swimmer_id": "s4",
                        "event": "400m IM",
                        "time": "5:01.10",
                        "headline": "Massive drop",
                        "type": "biggest_drop_of_meet",
                        "raw_facts": {"drop_seconds": 4.2},
                    },
                    "priority": 0.60,
                    "quality_band": "strong",
                },
            ],
        },
    }


def _profile(sponsor: str = "", notes: str = ""):
    from mediahub.web.club_profile import ClubProfile

    return ClubProfile(
        profile_id="test-profile",
        display_name="Test Club",
        short_name="Test",
        sponsor_name=sponsor,
        tone="warm-club",
        notes=notes,
    )


class TestTurnIntoStructure(unittest.TestCase):
    """Pack-shape assertions in deterministic mode."""

    def test_pack_has_required_top_level_keys(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
        for key in (
            "pack_id",
            "run_id",
            "generated_at",
            "meet_name",
            "profile_id",
            "voice_tone",
            "deterministic",
            "artefacts",
            "skipped",
        ):
            self.assertIn(key, pack, f"missing pack key: {key}")
        self.assertTrue(pack["deterministic"])
        self.assertEqual(pack["run_id"], "test-run")
        self.assertEqual(pack["meet_name"], "Spring Open 2026")

    def test_pack_with_no_sponsor_or_next_meet_produces_6_artefacts(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
        types = [a["type"] for a in pack["artefacts"]]
        # Always present: 6 artefacts (no sponsor, no next meet)
        self.assertEqual(
            set(types),
            {
                "meet_recap",
                "swimmer_spotlight",
                "data_thread",
                "parent_newsletter",
                "club_report",
                "coach_quote",
            },
        )
        skip_types = [s["type"] for s in pack["skipped"]]
        self.assertIn("sponsor_thank_you", skip_types)
        self.assertIn("next_meet_preview", skip_types)

    def test_pack_with_sponsor_only_includes_sponsor(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports"),
            deterministic=True,
        )
        types = [a["type"] for a in pack["artefacts"]]
        self.assertIn("sponsor_thank_you", types)
        skip_types = [s["type"] for s in pack["skipped"]]
        self.assertNotIn("sponsor_thank_you", skip_types)
        self.assertIn("next_meet_preview", skip_types)

    def test_pack_with_next_meet_in_notes_produces_preview(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(
            _run_data(),
            _profile(notes="Next meet: Nationals 2026 — 2026-06-10"),
            deterministic=True,
        )
        types = [a["type"] for a in pack["artefacts"]]
        self.assertIn("next_meet_preview", types)
        nm = next(a for a in pack["artefacts"] if a["type"] == "next_meet_preview")
        self.assertIn("Nationals 2026", nm["captions"]["default"])

    def test_full_profile_produces_all_eight(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
            deterministic=True,
        )
        self.assertEqual(len(pack["artefacts"]), 8)
        types = [a["type"] for a in pack["artefacts"]]
        self.assertEqual(
            set(types),
            {
                "meet_recap",
                "swimmer_spotlight",
                "data_thread",
                "parent_newsletter",
                "club_report",
                "sponsor_thank_you",
                "coach_quote",
                "next_meet_preview",
            },
        )
        self.assertEqual(pack["skipped"], [])

    def test_pack_never_exceeds_8_artefacts(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
            deterministic=True,
        )
        self.assertLessEqual(len(pack["artefacts"]), 8)


class TestArtefactPlatformVariants(unittest.TestCase):
    """Per-platform variant assertions."""

    def setUp(self):
        from mediahub.turn_into import turn_meet_into_pack

        self.pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
            deterministic=True,
        )
        self.by_type = {a["type"]: a for a in self.pack["artefacts"]}

    def test_x_thread_has_3_to_5_posts_under_280_chars(self):
        thread = self.by_type["data_thread"]
        posts = thread["captions"]["x_thread"]
        self.assertGreaterEqual(len(posts), 3)
        self.assertLessEqual(len(posts), 5)
        for i, p in enumerate(posts):
            self.assertLessEqual(len(p), 280, f"post {i} exceeds 280 chars: {p!r}")

    def test_linkedin_variant_present(self):
        thread = self.by_type["data_thread"]
        self.assertIn("linkedin", thread["captions"])
        self.assertGreater(len(thread["captions"]["linkedin"]), 30)

    def test_instagram_caption_within_2200_chars(self):
        recap = self.by_type["meet_recap"]
        ig = recap["captions"].get("instagram", "")
        self.assertGreater(len(ig), 0)
        self.assertLessEqual(len(ig), 2200)

    def test_newsletter_has_html_and_plain_text(self):
        newsletter = self.by_type["parent_newsletter"]
        self.assertIn("html", newsletter)
        self.assertIn("<p>", newsletter["html"])
        self.assertIn("plain_text", newsletter["captions"])

    def test_coach_quote_has_draft_flag(self):
        coach = self.by_type["coach_quote"]
        self.assertIn("DRAFT", coach.get("draft_flag", ""))
        self.assertIn("DRAFT", coach["captions"]["default"])

    def test_swimmer_spotlight_one_card_per_top_swimmer(self):
        spot = self.by_type["swimmer_spotlight"]
        self.assertGreater(len(spot["cards"]), 0)
        self.assertLessEqual(len(spot["cards"]), 3)
        names = [c["swimmer"] for c in spot["cards"]]
        self.assertEqual(
            len(names), len(set(names)), "spotlight should produce one card per distinct swimmer"
        )


class TestSkippedNotes(unittest.TestCase):
    def test_skipped_entries_have_type_and_reason(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
        self.assertGreater(len(pack["skipped"]), 0)
        for s in pack["skipped"]:
            self.assertIn("type", s)
            self.assertIn("reason", s)
            self.assertTrue(s["reason"])


class TestPackStorage(unittest.TestCase):
    """Round-trip save_pack / load_pack / list_packs through DATA_DIR."""

    def test_save_load_roundtrip(self):
        from mediahub.turn_into import turn_meet_into_pack, save_pack, load_pack, list_packs

        with _tempdir() as tmp:
            os.environ["DATA_DIR"] = tmp
            try:
                pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
                save_pack(pack, "test-run")
                loaded = load_pack("test-run", pack["pack_id"])
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded["pack_id"], pack["pack_id"])
                self.assertEqual(len(loaded["artefacts"]), len(pack["artefacts"]))

                packs = list_packs("test-run")
                self.assertEqual(len(packs), 1)
                self.assertEqual(packs[0]["pack_id"], pack["pack_id"])
            finally:
                os.environ.pop("DATA_DIR", None)

    def test_old_packs_preserved_when_regenerating(self):
        from mediahub.turn_into import turn_meet_into_pack, save_pack, list_packs

        with _tempdir() as tmp:
            os.environ["DATA_DIR"] = tmp
            try:
                p1 = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
                save_pack(p1, "test-run")
                p2 = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
                save_pack(p2, "test-run")
                self.assertNotEqual(p1["pack_id"], p2["pack_id"])
                self.assertEqual(len(list_packs("test-run")), 2)
            finally:
                os.environ.pop("DATA_DIR", None)


class TestVoiceProfileUsage(unittest.TestCase):
    """Verify the artefacts inherit the club voice (sign_off + tone)."""

    def test_sign_off_appended_to_recap_in_deterministic_mode(self):
        """When voice profile has a sign-off, recap caption ends with it."""
        from mediahub.voice.profile import VoiceProfile
        from mediahub.voice.store import save_voice_profile
        from mediahub.turn_into import turn_meet_into_pack

        with _tempdir() as tmp:
            base = Path(tmp)
            vp = VoiceProfile(profile_id="test-profile", sign_off="—Test SC")
            save_voice_profile(vp, base_dir=base)
            # Point voice loader at our tempdir by monkey-patching the default dir.
            import mediahub.voice.store as vs

            orig_dir = vs._DEFAULT_DIR
            vs._DEFAULT_DIR = base
            try:
                pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
            finally:
                vs._DEFAULT_DIR = orig_dir
            recap = next(a for a in pack["artefacts"] if a["type"] == "meet_recap")
            self.assertIn("—Test SC", recap["captions"]["default"])


class TestWebRoutes(unittest.TestCase):
    """Integration test via the Flask test client."""

    @pytest.fixture(autouse=True)
    def _wire_web(self, web_module, tmp_path):
        """Bind the shared, DATA_DIR-isolated web module and this test's
        tmp_path onto the instance.

        The ``web_module`` fixture (via ``_isolate_data_dir``) has already
        pointed DATA_DIR / RUNS_DIR / UPLOADS_DIR at ``tmp_path`` and repointed
        the module's path globals + cleared its per-run caches — the surgical,
        no-reload equivalent of the old ``importlib.reload(web)``.
        unittest.TestCase can't take fixture arguments directly, so this autouse
        fixture stashes them on ``self``."""
        self._wm = web_module
        self._tmp = tmp_path

    def _make_app(self):
        app = self._wm.create_app()
        # Bypass the first-run organisation gate — these tests assert
        # behaviour of downstream routes and don't seed a profile.
        app.config["TESTING"] = True
        return app

    def test_post_turn_into_then_view_pack(self):
        tmp = str(self._tmp)
        app = self._make_app()
        Path(tmp + "/runs_v4/run-x.json").write_text(
            json.dumps(
                {
                    **_run_data(),
                    "run_id": "run-x",
                }
            )
        )
        client = app.test_client()
        r = client.post("/api/runs/run-x/turn-into", json={"deterministic": True})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["n_artefacts"], 6)
        self.assertIn("sponsor_thank_you", data["skipped"])
        # View the rendered pack page
        r2 = client.get(data["pack_url"])
        self.assertEqual(r2.status_code, 200)
        body = r2.get_data(as_text=True)
        # J-4: the one user-facing name for the feature is "Repurpose pack".
        self.assertIn("Repurpose pack", body)
        self.assertIn("DRAFT", body)
        self.assertIn("X thread", body)

    def test_edit_caption_persists(self):
        tmp = str(self._tmp)
        app = self._make_app()
        Path(tmp + "/runs_v4/run-y.json").write_text(
            json.dumps(
                {
                    **_run_data(),
                    "run_id": "run-y",
                }
            )
        )
        client = app.test_client()
        r = client.post("/api/runs/run-y/turn-into", json={"deterministic": True})
        pid = r.get_json()["pack_id"]
        r2 = client.post(
            f"/api/runs/run-y/turn-into/{pid}/caption",
            json={"artefact_index": 0, "caption_key": "default", "text": "My edited recap."},
        )
        self.assertEqual(r2.status_code, 200)
        from mediahub.turn_into import load_pack

        pack = load_pack("run-y", pid, base_dir=Path(tmp) / "turn_into_packs")
        self.assertEqual(pack["artefacts"][0]["captions"]["default"], "My edited recap.")

    def test_existing_routes_still_200(self):
        app = self._make_app()
        client = app.test_client()
        # /settings now redirects to home (operator-config rewrite);
        # the routes here are the ones that still render 200.
        for path in ("/upload", "/organisation"):
            r = client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} != 200")

    def test_async_status_survives_cross_worker_poll(self):
        """Regression: with gunicorn --workers 2 the status poll often
        lands on a different worker than the POST that created the job.
        The job must still resolve from the shared on-disk record instead
        of the spurious 'job not found' the user saw in the UI."""
        import time as _time

        wm = self._wm
        tmp = str(self._tmp)
        app = self._make_app()
        Path(tmp + "/runs_v4/run-z.json").write_text(
            json.dumps(
                {
                    **_run_data(),
                    "run_id": "run-z",
                }
            )
        )
        client = app.test_client()
        r = client.post("/api/runs/run-z/turn-into", json={"deterministic": True, "async": True})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "running")
        job_id = body["job_id"]
        status_url = body["status_url"]

        # Wait for the background (deterministic) generation to finish.
        deadline = _time.time() + 5.0
        done = None
        while _time.time() < deadline:
            jr = wm._ti_job_read(job_id)
            if jr and jr.get("status") == "done":
                done = jr
                break
            _time.sleep(0.05)
        self.assertIsNotNone(done, "job never completed on disk")

        # Simulate the poll landing on the *other* worker: that worker
        # has nothing in its in-memory cache for this job_id.
        wm._turn_into_jobs.pop(job_id, None)
        self.assertNotIn(job_id, wm._turn_into_jobs)

        r2 = client.get(status_url)
        self.assertEqual(r2.status_code, 200, "cross-worker status poll must not 404")
        data = r2.get_json()
        self.assertEqual(data["status"], "done")
        self.assertTrue(data.get("pack_url"))

    def test_status_rejects_mismatched_run(self):
        """A job_id created under one run must not resolve via another
        run's status URL — defensive guard on the shared disk record."""
        wm = self._wm
        tmp = str(self._tmp)
        app = self._make_app()
        for rid in ("run-a", "run-b"):
            Path(tmp + f"/runs_v4/{rid}.json").write_text(
                json.dumps(
                    {
                        **_run_data(),
                        "run_id": rid,
                    }
                )
            )
        client = app.test_client()
        r = client.post("/api/runs/run-a/turn-into", json={"deterministic": True, "async": True})
        job_id = r.get_json()["job_id"]
        # Force the disk path (the record carries run_id="run-a").
        wm._turn_into_jobs.pop(job_id, None)
        r2 = client.get(f"/api/runs/run-b/turn-into-status/{job_id}")
        self.assertEqual(r2.status_code, 404)


class TestArtefactsAreAIMade(unittest.TestCase):
    """Regression: every artefact must be written by the LLM, not silently
    dropped to the heuristic fallback. Before the fix, aggregate artefacts
    (recap, thread intro/LinkedIn, newsletter, sponsor, coach quote,
    next-meet) passed payloads that narrate_achievement couldn't read, so
    generate_caption_for_tone raised and _gen_caption returned the
    hardcoded template — i.e. the pack was a template shop, not AI-made."""

    def test_all_artefacts_reach_the_llm(self):
        from unittest import mock

        os.environ["MEDIAHUB_TURNINTO_PARALLEL"] = "0"
        try:
            captured: list[str] = []

            def fake_call(system, user, max_tokens=400, **kw):
                captured.append(user)
                return "AI-WRITTEN :: " + user.splitlines()[0][:40]

            def fake_longform(prompt, *, system=None, max_tokens=1024, **kw):
                captured.append(prompt)
                return "AI-LONGFORM :: " + prompt.splitlines()[0][:40]

            with (
                mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call),
                mock.patch("mediahub.media_ai.llm.generate", side_effect=fake_longform),
                mock.patch(
                    "mediahub.media_ai.llm.generate_json",
                    return_value={"subject": "AI-SUBJECT line", "preheader": "AI-PREHEADER line"},
                ),
            ):
                from mediahub.turn_into import turn_meet_into_pack

                pack = turn_meet_into_pack(
                    _run_data(),
                    _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
                    deterministic=False,
                )
        finally:
            os.environ.pop("MEDIAHUB_TURNINTO_PARALLEL", None)

        by = {a["type"]: a for a in pack["artefacts"]}
        self.assertEqual(len(pack["artefacts"]), 8)

        # The long-form club report goes through media_ai.generate (the
        # caption primitive is capped at caption length) — it must be
        # AI-made too, and the newsletter's email envelope must carry the
        # AI-written subject/preheader.
        self.assertTrue(by["club_report"]["captions"]["default"].startswith("AI-LONGFORM"))
        self.assertEqual(by["parent_newsletter"]["captions"]["subject"], "AI-SUBJECT line")
        self.assertEqual(by["parent_newsletter"]["captions"]["preheader"], "AI-PREHEADER line")

        # Aggregate artefacts that previously fell back to heuristics.
        self.assertTrue(by["meet_recap"]["captions"]["default"].startswith("AI-WRITTEN"))
        self.assertTrue(by["meet_recap"]["captions"]["instagram"].startswith("AI-WRITTEN"))
        self.assertTrue(by["parent_newsletter"]["captions"]["default"].startswith("AI-WRITTEN"))
        self.assertTrue(by["sponsor_thank_you"]["captions"]["default"].startswith("AI-WRITTEN"))
        self.assertTrue(by["next_meet_preview"]["captions"]["default"].startswith("AI-WRITTEN"))
        # coach_quote prepends the DRAFT flag, so check the raw quote.
        self.assertTrue(by["coach_quote"]["captions"]["quote_only"].startswith("AI-WRITTEN"))
        # data_thread: intro + every numbered post + LinkedIn variant.
        self.assertTrue(all("AI-WRITTEN" in p for p in by["data_thread"]["captions"]["x_thread"]))
        self.assertTrue(by["data_thread"]["captions"]["linkedin"].startswith("AI-WRITTEN"))
        # Per-swimmer spotlight captions (these always worked, but assert
        # they still do).
        self.assertTrue(
            all(v.startswith("AI-WRITTEN") for v in by["swimmer_spotlight"]["captions"].values())
        )

        # The model actually received real meet context for the aggregate
        # briefs (not the empty prose that used to trigger the fallback).
        joined = "\n".join(captured)
        self.assertIn("Write a feed recap of", joined)
        self.assertIn("parent-and-supporter newsletter", joined)
        self.assertIn("Thank the sponsor Acme Sports", joined)

    def test_artefacts_carry_ai_source_marker(self):
        from unittest import mock

        os.environ["MEDIAHUB_TURNINTO_PARALLEL"] = "0"
        try:
            with (
                mock.patch("mediahub.web.ai_caption.call_claude", return_value="AI-WRITTEN copy"),
                mock.patch("mediahub.media_ai.llm.generate", return_value="AI-LONGFORM copy"),
                mock.patch(
                    "mediahub.media_ai.llm.generate_json",
                    return_value={"subject": "S", "preheader": "P"},
                ),
            ):
                from mediahub.turn_into import turn_meet_into_pack

                pack = turn_meet_into_pack(
                    _run_data(),
                    _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
                    deterministic=False,
                )
        finally:
            os.environ.pop("MEDIAHUB_TURNINTO_PARALLEL", None)
        for art in pack["artefacts"]:
            self.assertEqual(art.get("source"), "ai", art["type"])

    def test_llm_failure_marks_artefacts_fallback_not_silent(self):
        """A transient provider error must not ship template copy that looks
        AI-written: the artefact is marked source='fallback' and its notes say
        why (the review UI badges these)."""
        from unittest import mock

        os.environ["MEDIAHUB_TURNINTO_PARALLEL"] = "0"
        try:
            boom = RuntimeError("provider down")
            with (
                mock.patch("mediahub.web.ai_caption.call_claude", side_effect=boom),
                mock.patch("mediahub.media_ai.llm.generate", side_effect=boom),
                mock.patch("mediahub.media_ai.llm.generate_json", side_effect=boom),
            ):
                from mediahub.turn_into import turn_meet_into_pack

                pack = turn_meet_into_pack(
                    _run_data(),
                    _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
                    deterministic=False,
                )
        finally:
            os.environ.pop("MEDIAHUB_TURNINTO_PARALLEL", None)
        self.assertEqual(len(pack["artefacts"]), 8)
        for art in pack["artefacts"]:
            self.assertEqual(art.get("source"), "fallback", art["type"])
            self.assertTrue(
                any("template" in n and "not AI-written" in n for n in art["notes"]),
                f"no honesty note on {art['type']}",
            )

    def test_deterministic_pack_is_marked_deterministic(self):
        from mediahub.turn_into import turn_meet_into_pack

        pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
        for art in pack["artefacts"]:
            self.assertEqual(art.get("source"), "deterministic", art["type"])

    def test_aggregate_briefs_are_non_empty(self):
        from mediahub.turn_into.templates import _narrate_brief

        cases = [
            ("meet_recap", {"meet": "M"}),
            ("thread_intro", {"meet": "M", "n_top": 3}),
            ("thread_linkedin", {"meet": "M"}),
            ("newsletter", {"meet": "M"}),
            ("sponsor_thank_you", {"meet": "M", "sponsor": "S"}),
            ("coach_quote", {"meet": "M"}),
            ("next_meet_preview", {"next_meet": {"name": "N"}}),
        ]
        for kind, extra in cases:
            prose = _narrate_brief({"kind": kind, **extra})
            self.assertTrue(prose.strip(), f"empty brief for {kind}")
        # Unknown kind returns "" so the caller keeps the single-swim path.
        self.assertEqual(_narrate_brief({"kind": "totally_unknown"}), "")


if __name__ == "__main__":
    unittest.main()
