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
        for key in ("pack_id", "run_id", "generated_at", "meet_name",
                    "profile_id", "voice_tone", "deterministic",
                    "artefacts", "skipped"):
            self.assertIn(key, pack, f"missing pack key: {key}")
        self.assertTrue(pack["deterministic"])
        self.assertEqual(pack["run_id"], "test-run")
        self.assertEqual(pack["meet_name"], "Spring Open 2026")

    def test_pack_with_no_sponsor_or_next_meet_produces_5_artefacts(self):
        from mediahub.turn_into import turn_meet_into_pack
        pack = turn_meet_into_pack(_run_data(), _profile(), deterministic=True)
        types = [a["type"] for a in pack["artefacts"]]
        # Always present: 1 + 2 + 3 + 4 + 6 = 5 artefacts (no sponsor, no next meet)
        self.assertEqual(set(types), {
            "meet_recap", "swimmer_spotlight", "data_thread",
            "parent_newsletter", "coach_quote",
        })
        skip_types = [s["type"] for s in pack["skipped"]]
        self.assertIn("sponsor_thank_you", skip_types)
        self.assertIn("next_meet_preview", skip_types)

    def test_pack_with_sponsor_only_includes_sponsor(self):
        from mediahub.turn_into import turn_meet_into_pack
        pack = turn_meet_into_pack(
            _run_data(), _profile(sponsor="Acme Sports"),
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

    def test_full_profile_produces_all_seven(self):
        from mediahub.turn_into import turn_meet_into_pack
        pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
            deterministic=True,
        )
        self.assertEqual(len(pack["artefacts"]), 7)
        types = [a["type"] for a in pack["artefacts"]]
        self.assertEqual(set(types), {
            "meet_recap", "swimmer_spotlight", "data_thread",
            "parent_newsletter", "sponsor_thank_you", "coach_quote",
            "next_meet_preview",
        })
        self.assertEqual(pack["skipped"], [])

    def test_pack_never_exceeds_7_artefacts(self):
        from mediahub.turn_into import turn_meet_into_pack
        pack = turn_meet_into_pack(
            _run_data(),
            _profile(sponsor="Acme Sports", notes="Next meet: Nationals — 2026-06-10"),
            deterministic=True,
        )
        self.assertLessEqual(len(pack["artefacts"]), 7)


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
        self.assertEqual(len(names), len(set(names)),
                         "spotlight should produce one card per distinct swimmer")


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
        with tempfile.TemporaryDirectory() as tmp:
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
        with tempfile.TemporaryDirectory() as tmp:
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
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vp = VoiceProfile(profile_id="test-profile", sign_off="—Test SC")
            save_voice_profile(vp, base_dir=base)
            # Point voice loader at our tempdir by monkey-patching the default dir.
            import mediahub.voice.store as vs
            orig_dir = vs._DEFAULT_DIR
            vs._DEFAULT_DIR = base
            try:
                pack = turn_meet_into_pack(_run_data(), _profile(),
                                           deterministic=True)
            finally:
                vs._DEFAULT_DIR = orig_dir
            recap = next(a for a in pack["artefacts"] if a["type"] == "meet_recap")
            self.assertIn("—Test SC", recap["captions"]["default"])


class TestWebRoutes(unittest.TestCase):
    """Integration test via the Flask test client."""

    def _make_app(self, tmp: str):
        os.environ["DATA_DIR"] = tmp
        os.environ["RUNS_DIR"] = tmp + "/runs_v4"
        os.environ["UPLOADS_DIR"] = tmp + "/uploads_v4"
        Path(tmp + "/runs_v4").mkdir(parents=True, exist_ok=True)
        # Reset cached singletons in web module so DATA_DIR re-resolves.
        import importlib
        import mediahub.web.web as wm
        importlib.reload(wm)
        app = wm.create_app()
        # Bypass the first-run organisation gate — these tests assert
        # behaviour of downstream routes and don't seed a profile.
        app.config["TESTING"] = True
        return app

    def test_post_turn_into_then_view_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(tmp)
            Path(tmp + "/runs_v4/run-x.json").write_text(json.dumps({
                **_run_data(), "run_id": "run-x",
            }))
            client = app.test_client()
            r = client.post("/api/runs/run-x/turn-into",
                            json={"deterministic": True})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["n_artefacts"], 5)
            self.assertIn("sponsor_thank_you", data["skipped"])
            # View the rendered pack page
            r2 = client.get(data["pack_url"])
            self.assertEqual(r2.status_code, 200)
            body = r2.get_data(as_text=True)
            self.assertIn("Turn-Into pack", body)
            self.assertIn("DRAFT", body)
            self.assertIn("X thread", body)

    def test_edit_caption_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(tmp)
            Path(tmp + "/runs_v4/run-y.json").write_text(json.dumps({
                **_run_data(), "run_id": "run-y",
            }))
            client = app.test_client()
            r = client.post("/api/runs/run-y/turn-into",
                            json={"deterministic": True})
            pid = r.get_json()["pack_id"]
            r2 = client.post(
                f"/api/runs/run-y/turn-into/{pid}/caption",
                json={"artefact_index": 0, "caption_key": "default",
                      "text": "My edited recap."},
            )
            self.assertEqual(r2.status_code, 200)
            from mediahub.turn_into import load_pack
            pack = load_pack("run-y", pid, base_dir=Path(tmp) / "turn_into_packs")
            self.assertEqual(pack["artefacts"][0]["captions"]["default"],
                             "My edited recap.")

    def test_existing_routes_still_200(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self._make_app(tmp)
            client = app.test_client()
            for path in ("/upload", "/organisation", "/settings"):
                r = client.get(path)
                self.assertEqual(r.status_code, 200, f"{path} != 200")


if __name__ == "__main__":
    unittest.main()
