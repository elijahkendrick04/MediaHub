"""
V7.3 unit tests for new modules:
- recognition.registry
- recognition.copy_text
- recognition.weekend_in_numbers
- content_pack.builder
- voice.profile + voice.store
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        # Reset registry between tests
        import mediahub.recognition.registry as reg
        reg._SPORTS.clear()

    def test_register_and_get(self):
        from mediahub.recognition.registry import register_sport, get_sport, list_sports
        register_sport("swimming", display_name="Swimming", detectors=[1, 2, 3])
        sc = get_sport("swimming")
        self.assertIsNotNone(sc)
        self.assertEqual(sc.sport, "swimming")
        self.assertEqual(sc.display_name, "Swimming")
        self.assertEqual(len(sc.detectors), 3)

    def test_list_sports(self):
        from mediahub.recognition.registry import register_sport, list_sports
        register_sport("basketball", display_name="Basketball", detectors=[])
        register_sport("swimming", display_name="Swimming", detectors=[])
        sports = list_sports()
        self.assertIn("basketball", sports)
        self.assertIn("swimming", sports)
        # Sorted
        self.assertEqual(sports, sorted(sports))

    def test_two_fake_sports(self):
        from mediahub.recognition.registry import register_sport, get_sport, list_sports
        register_sport("basketball", display_name="Basketball", detectors=["d1"])
        register_sport("athletics", display_name="Athletics", detectors=["d2", "d3"])
        self.assertEqual(len(get_sport("basketball").detectors), 1)
        self.assertEqual(len(get_sport("athletics").detectors), 2)
        self.assertIn("athletics", list_sports())
        self.assertIn("basketball", list_sports())

    def test_get_nonexistent_returns_none(self):
        from mediahub.recognition.registry import get_sport
        self.assertIsNone(get_sport("hockey"))


class TestCopyText(unittest.TestCase):
    def _make_card(self, headline="Great swim!", body="Smith swam 60.00", cta=""):
        return {
            "active_caption": {"headline": headline, "body": body, "cta": cta},
            "hashtags": ["#SwanseaUni", "#Swimming"],
            "suggested_post_type": "main_feed",
            "confidence": 0.95,
            "safe_to_post": {"level": "safe", "reason": "High confidence."},
            "post_angle": "pb_improvement",
        }

    def test_caption_only_no_html(self):
        from mediahub.recognition.copy_text import build_caption_text
        card = self._make_card()
        text = build_caption_text(card, mode="caption_only")
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertIn("Great swim!", text)
        self.assertNotIn("#SwanseaUni", text)

    def test_with_hashtags(self):
        from mediahub.recognition.copy_text import build_caption_text
        card = self._make_card()
        text = build_caption_text(card, mode="with_hashtags")
        self.assertIn("#SwanseaUni", text)
        self.assertNotIn("<", text)

    def test_full_brief(self):
        from mediahub.recognition.copy_text import build_caption_text
        card = self._make_card()
        text = build_caption_text(card, mode="full_brief")
        self.assertIn("Safe to post:", text)
        self.assertIn("Suggested format:", text)
        self.assertNotIn("<", text)
        self.assertNotIn("style=", text)

    def test_no_html_in_any_mode(self):
        from mediahub.recognition.copy_text import build_caption_text
        card = {
            "active_caption": {
                "headline": "<b>Alert!</b>",
                "body": "<script>bad()</script>",
            }
        }
        for mode in ("caption_only", "with_hashtags", "full_brief"):
            text = build_caption_text(card, mode=mode)
            self.assertNotIn("<b>", text, f"HTML in {mode}")
            self.assertNotIn("<script>", text, f"HTML in {mode}")


class TestWeekendInNumbers(unittest.TestCase):
    def _make_report(self):
        return {
            "meet_name": "Test Meet 2026",
            "n_swims_analysed": 50,
            "ranked_achievements": [
                {
                    "achievement": {
                        "type": "medal_gold",
                        "swimmer_id": "s1",
                        "swimmer_name": "Alice",
                        "event": "100m Freestyle (LC)",
                        "raw_facts": {},
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                },
                {
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_id": "s2",
                        "swimmer_name": "Bob",
                        "event": "200m Backstroke (LC)",
                        "raw_facts": {"drop_seconds": 0.5, "drop_pct": 0.83},
                    },
                    "quality_band": "nice",
                    "priority": 0.3,
                },
                {
                    "achievement": {
                        "type": "biggest_drop_of_meet",
                        "swimmer_id": "s3",
                        "swimmer_name": "Charlie",
                        "event": "100m Butterfly (LC)",
                        "raw_facts": {"drop_seconds": 1.45, "drop_pct": 2.1},
                    },
                    "quality_band": "strong",
                    "priority": 0.6,
                },
            ],
        }

    def test_produces_card(self):
        from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers
        report = self._make_report()
        card = build_weekend_in_numbers(report)
        self.assertIsInstance(card, dict)
        self.assertEqual(card["card_type"], "weekend_in_numbers")
        self.assertIn("Test Meet 2026", card["headline"])
        self.assertIn("stats", card)
        self.assertIn("caption_text", card)

    def test_counts_medals(self):
        from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers
        card = build_weekend_in_numbers(self._make_report())
        stats_dict = {s["label"]: s["value"] for s in card["stats"]}
        self.assertEqual(stats_dict.get("Medals"), "1")

    def test_biggest_drop_in_highlights(self):
        from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers
        card = build_weekend_in_numbers(self._make_report())
        highlights_text = " ".join(card.get("highlights", []))
        self.assertIn("Charlie", highlights_text)

    def test_safe_to_post_is_safe(self):
        from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers
        card = build_weekend_in_numbers(self._make_report())
        s2p = card.get("safe_to_post", {})
        self.assertEqual(s2p.get("level"), "safe")


class TestGroupedPack(unittest.TestCase):
    def _make_run_data(self):
        return {
            "run_id": "test-run",
            "profile_id": "test",
            "recognition_report": {
                "meet_name": "Test Meet",
                "n_swims_analysed": 10,
                "ranked_achievements": [
                    {
                        "achievement": {
                            "type": "medal_gold",
                            "swimmer_id": "s1",
                            "swimmer_name": "Alice",
                            "event": "100m Freestyle (LC)",
                            "headline": "Alice wins gold!",
                            "raw_facts": {},
                            "confidence": 0.98,
                            "confidence_label": "high",
                        },
                        "quality_band": "elite",
                        "priority": 0.92,
                        "suggested_post_type": "main_feed",
                        "rank": 1,
                    },
                    {
                        "achievement": {
                            "type": "pb_confirmed",
                            "swimmer_id": "s2",
                            "swimmer_name": "Bob",
                            "event": "200m Backstroke (LC)",
                            "headline": "Bob PBs!",
                            "raw_facts": {},
                            "confidence": 0.6,
                            "confidence_label": "medium",
                            "uncertainty_notes": ["entry time comparison only"],
                        },
                        "quality_band": "nice",
                        "priority": 0.35,
                        "suggested_post_type": "recap",
                        "rank": 2,
                    },
                ],
            },
            "cards": [],
        }

    def test_returns_8_buckets(self):
        from mediahub.content_pack.builder import build_grouped_pack
        grouped = build_grouped_pack(self._make_run_data(), "test")
        self.assertIn("main_feed", grouped)
        self.assertIn("stories", grouped)
        self.assertIn("athlete_spotlights", grouped)
        self.assertIn("weekend_recap", grouped)
        self.assertIn("weekend_in_numbers", grouped)
        self.assertIn("internal_notes", grouped)
        self.assertIn("needs_review", grouped)
        self.assertIn("rejected", grouped)

    def test_elite_safe_goes_to_main_feed(self):
        from mediahub.content_pack.builder import build_grouped_pack
        grouped = build_grouped_pack(self._make_run_data(), "test")
        # Alice (gold medal, elite) should be in main_feed
        main_names = [
            (item.get("achievement") or {}).get("swimmer_name", "")
            for item in grouped["main_feed"]
        ]
        self.assertIn("Alice", main_names)

    def test_weekend_in_numbers_generated(self):
        from mediahub.content_pack.builder import build_grouped_pack
        grouped = build_grouped_pack(self._make_run_data(), "test")
        self.assertIsNotNone(grouped["weekend_in_numbers"])

    def test_counts_in_underscore_counts(self):
        from mediahub.content_pack.builder import build_grouped_pack
        grouped = build_grouped_pack(self._make_run_data(), "test")
        counts = grouped["_counts"]
        self.assertIn("main_feed", counts)
        self.assertGreaterEqual(counts["main_feed"], 0)

    def test_runs_dir_fallback_is_data_dir_derived(self):
        """runs_dir=None must resolve the sidecar under DATA_DIR/runs_v4
        (env-derived, like the web layer) — not <repo>/src/runs_v4."""
        import json as _json
        from unittest import mock

        from mediahub.content_pack.builder import build_grouped_pack

        run_data = self._make_run_data()
        run_data["recognition_report"]["ranked_achievements"][0]["achievement"][
            "swim_id"
        ] = "card1"
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs_v4"
            runs.mkdir()
            (runs / "test-run__workflow.json").write_text(
                _json.dumps(
                    {
                        "card1": {
                            "card_id": "card1",
                            "status": "approved",
                            "last_changed_at": "2026-05-10T11:00:00Z",
                        }
                    }
                )
            )
            with mock.patch.dict(os.environ, {"DATA_DIR": td}, clear=False):
                os.environ.pop("RUNS_DIR", None)
                grouped = build_grouped_pack(run_data, "test")
        statuses = {
            (item.get("achievement") or {}).get("swimmer_name", ""): item.get("wf_status")
            for item in grouped["main_feed"]
        }
        self.assertEqual(statuses.get("Alice"), "approved")


class TestVoiceProfile(unittest.TestCase):
    def test_create_default(self):
        from mediahub.voice.profile import VoiceProfile
        vp = VoiceProfile(profile_id="test")
        self.assertEqual(vp.tone, "warm-club")
        self.assertEqual(vp.emoji_level, "moderate")
        self.assertEqual(vp.name_style, "first_name")

    def test_to_dict_from_dict_roundtrip(self):
        from mediahub.voice.profile import VoiceProfile, VoiceExemplar
        vp = VoiceProfile(
            profile_id="test",
            tone="hype",
            emoji_level="none",
            sign_off="—Swansea",
            preferred_phrases=["smashes it"],
            banned_phrases=["well done"],
            exemplars=[VoiceExemplar(title="Ex1", text="Great swim!")],
        )
        d = vp.to_dict()
        vp2 = VoiceProfile.from_dict(d)
        self.assertEqual(vp2.tone, "hype")
        self.assertEqual(vp2.sign_off, "—Swansea")
        self.assertEqual(len(vp2.exemplars), 1)

    def test_get_name_styles(self):
        from mediahub.voice.profile import VoiceProfile
        vp = VoiceProfile(profile_id="test")
        vp.name_style = "first_name"
        self.assertEqual(vp.get_name("Jane", "Smith"), "Jane")
        vp.name_style = "full_name"
        self.assertEqual(vp.get_name("Jane", "Smith"), "Jane Smith")
        vp.name_style = "surname"
        self.assertEqual(vp.get_name("Jane", "Smith"), "Smith")

    def test_apply_emoji_none(self):
        from mediahub.voice.profile import VoiceProfile
        vp = VoiceProfile(profile_id="test", emoji_level="none")
        text = "Great swim! 🏊‍♂️ Amazing! 🥇"
        clean = vp.apply_emoji(text)
        self.assertNotIn("🏊", clean)
        self.assertNotIn("🥇", clean)
        self.assertIn("Great swim!", clean)

    def test_apply_sign_off(self):
        from mediahub.voice.profile import VoiceProfile
        vp = VoiceProfile(profile_id="test", sign_off="—Swansea Uni")
        text = "Jane wins gold!"
        result = vp.apply_sign_off(text)
        self.assertIn("—Swansea Uni", result)

    def test_save_load_roundtrip(self):
        from mediahub.voice.profile import VoiceProfile
        from mediahub.voice.store import save_voice_profile, load_voice_profile
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            vp = VoiceProfile(profile_id="myclub", tone="data-led", sign_off="—Test")
            save_voice_profile(vp, base_dir=base)
            loaded = load_voice_profile("myclub", base_dir=base)
            self.assertEqual(loaded.tone, "data-led")
            self.assertEqual(loaded.sign_off, "—Test")


if __name__ == "__main__":
    unittest.main()
