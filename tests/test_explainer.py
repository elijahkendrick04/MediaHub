"""
Tests for the "Why this card?" recognition explainer (V9).

Covers:
- A PB swim produces a PB-mention bullet (grounded in the factor list).
- A non-PB swim never falsely claims a PB.
- Source lines are returned with non-empty raw_text.
- A card with no factors / no evidence falls back to the safe message.
- The ranker's factors now carry a populated plain_summary field.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure src/ + legacy/ are importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class TestExplainerPB(unittest.TestCase):
    """A confirmed PB should produce a PB-mention in the headline / bullets."""

    def _pb_achievement(self) -> dict:
        return {
            "type": "pb_confirmed",
            "swim_id": "smith:100Free:LC:F:pb",
            "swimmer_id": "smith",
            "swimmer_name": "Jane Smith",
            "event": "100m Freestyle (LC)",
            "headline": "Jane Smith sets new PB: 1:02.10 in 100m Freestyle (LC) (was 1:03.50, -1.40s)",
            "angle_hint": "Personal best of 1:02.10, dropping 1.40s.",
            "confidence": 0.95,
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "results_file",
                    "source_name": "Meet results",
                    "statement": "Swam 1:02.10 in 100m Freestyle (LC)",
                    "confidence": "high",
                },
                {
                    "source_type": "pb_cache",
                    "source_name": "Swim England rankings",
                    "statement": "Prior best was 1:03.50",
                    "source_url": "https://example.invalid/pb/smith",
                    "confidence": "high",
                },
            ],
            "raw_facts": {
                "time_sec": 62.10,
                "time_str": "1:02.10",
                "prior_pb_sec": 63.50,
                "prior_pb_str": "1:03.50",
                "drop_seconds": 1.40,
                "drop_pct": 2.20,
                "magnitude": "big",
            },
            "uncertainty_notes": [],
            "detector_name": "pb_confirmed",
        }

    def _pb_factors(self) -> list[dict]:
        return [
            {
                "name": "magnitude",
                "value": 0.55,
                "weight": 0.30,
                "reason": "type pb_confirmed base magnitude 0.55",
                "plain_summary": "Solid result for this achievement type (pb confirmed).",
            },
            {
                "name": "rarity",
                "value": 0.3,
                "weight": 0.20,
                "reason": "rarity=0.30 at open meet",
                "plain_summary": "Common at a open meet.",
            },
            {
                "name": "meet_level",
                "value": 0.4,
                "weight": 0.15,
                "reason": "meet level 'open' → 0.40",
                "plain_summary": "Open-level competition.",
            },
            {
                "name": "narrative",
                "value": 0.4,
                "weight": 0.15,
                "reason": "narrative bonus 0.40 for pb_confirmed",
                "plain_summary": "Has a narrative angle that adds interest.",
            },
            {
                "name": "barrier",
                "value": 0.0,
                "weight": 0.10,
                "reason": "no barrier crossing",
                "plain_summary": "",
            },
            {
                "name": "certainty",
                "value": 0.95,
                "weight": 0.10,
                "reason": "confidence 0.95 - uncertainty penalty 0.00",
                "plain_summary": "High confidence in the underlying data (0.95).",
            },
            {
                "name": "profile_priority",
                "value": 1.0,
                "weight": 0.0,
                "reason": "no profile priority override",
                "plain_summary": "No club priority override.",
            },
        ]

    def test_pb_swim_mentions_pb_in_headline(self):
        from mediahub.recognition.explainer import explain_achievement
        exp = explain_achievement(self._pb_achievement(), self._pb_factors(), rank=1)
        headline = exp["headline"].lower()
        # The achievement-type phrase for pb_confirmed contains "personal best".
        self.assertIn("personal best", headline,
                      msg=f"PB headline should mention 'personal best', got: {exp['headline']}")

    def test_pb_swim_has_bullets_about_confidence_or_factors(self):
        from mediahub.recognition.explainer import explain_achievement
        exp = explain_achievement(self._pb_achievement(), self._pb_factors(), rank=1)
        bullets = exp["bullets"]
        self.assertTrue(3 <= len(bullets) <= 5,
                        msg=f"Expected 3-5 bullets, got {len(bullets)}: {bullets}")
        joined = " ".join(bullets).lower()
        # Either the confidence bullet ("Detector confidence: high")
        # or a factor plain_summary mentioning confidence should be present.
        self.assertTrue("confidence" in joined or "high" in joined,
                        msg=f"Expected a confidence reference in bullets: {bullets}")


class TestExplainerNonPB(unittest.TestCase):
    """A non-PB swim must NEVER falsely claim a PB."""

    def _medal_achievement(self) -> dict:
        return {
            "type": "medal_gold",
            "swim_id": "alex:200Back:LC:F:medal_gold",
            "swimmer_id": "alex",
            "swimmer_name": "Alex Doe",
            "event": "200m Backstroke (LC)",
            "headline": "Alex Doe wins gold in 200m Backstroke",
            "angle_hint": "Gold medal at county meet.",
            "confidence": 0.92,
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "results_file",
                    "source_name": "Meet results",
                    "statement": "Placed 1st in 200m Backstroke (LC) with 2:15.40",
                    "confidence": "high",
                },
            ],
            "raw_facts": {"time_str": "2:15.40", "place": 1},
            "uncertainty_notes": [],
            "detector_name": "medal_final",
        }

    def _medal_factors(self) -> list[dict]:
        return [
            {
                "name": "magnitude",
                "value": 1.0,
                "weight": 0.30,
                "reason": "type medal_gold base magnitude 1.00",
                "plain_summary": "Strong on-paper achievement (medal gold).",
            },
            {
                "name": "rarity",
                "value": 0.6,
                "weight": 0.20,
                "reason": "rarity=0.60 at county meet",
                "plain_summary": "Moderately rare at a county meet.",
            },
            {
                "name": "meet_level",
                "value": 0.6,
                "weight": 0.15,
                "reason": "meet level 'county' → 0.60",
                "plain_summary": "County-level competition.",
            },
            {
                "name": "narrative",
                "value": 0.0,
                "weight": 0.15,
                "reason": "narrative bonus 0.00 for medal_gold",
                "plain_summary": "",
            },
            {
                "name": "barrier",
                "value": 0.0,
                "weight": 0.10,
                "reason": "no barrier crossing",
                "plain_summary": "",
            },
            {
                "name": "certainty",
                "value": 0.92,
                "weight": 0.10,
                "reason": "confidence 0.92 - uncertainty penalty 0.00",
                "plain_summary": "High confidence in the underlying data (0.92).",
            },
            {
                "name": "profile_priority",
                "value": 1.0,
                "weight": 0.0,
                "reason": "no profile priority override",
                "plain_summary": "No club priority override.",
            },
        ]

    def test_medal_swim_does_not_mention_pb(self):
        from mediahub.recognition.explainer import explain_achievement
        exp = explain_achievement(self._medal_achievement(), self._medal_factors(), rank=1)
        full_text = (exp["headline"] + " " + " ".join(exp["bullets"])).lower()
        # A gold-medal-only card must NEVER falsely advertise a PB.
        self.assertNotIn("personal best", full_text,
                         msg=f"Non-PB card should not say 'personal best': {exp}")
        self.assertNotIn(" pb ", " " + full_text + " ",
                         msg=f"Non-PB card should not say 'PB': {exp}")
        # It should however mention "gold" / "medal" since that's the actual achievement.
        self.assertTrue("gold" in full_text or "medal" in full_text,
                        msg=f"Gold-medal headline should mention gold/medal: {exp}")


class TestExplainerSourceLines(unittest.TestCase):
    """Source lines must come back with non-empty raw_text and a label."""

    def test_source_lines_have_raw_text(self):
        from mediahub.recognition.explainer import explain_achievement
        ach = {
            "type": "pb_confirmed",
            "swimmer_name": "Sam Lee",
            "event": "50m Freestyle (SC)",
            "confidence": 0.9,
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "results_file",
                    "source_name": "Meet results",
                    "statement": "Swam 24.55 in 50m Freestyle (SC)",
                    "confidence": "high",
                },
                {
                    "source_type": "pb_cache",
                    "source_name": "Swim England",
                    "statement": "Prior best was 25.10",
                    "source_url": "https://example.invalid/pb/lee",
                    "confidence": "high",
                },
            ],
        }
        factors = [
            {
                "name": "magnitude",
                "value": 0.55,
                "weight": 0.3,
                "reason": "ok",
                "plain_summary": "Solid result for this achievement type (pb confirmed).",
            },
            {
                "name": "certainty",
                "value": 0.9,
                "weight": 0.1,
                "reason": "ok",
                "plain_summary": "High confidence in the underlying data (0.90).",
            },
        ]
        exp = explain_achievement(ach, factors, rank=1)
        self.assertGreaterEqual(len(exp["source_lines"]), 1)
        self.assertLessEqual(len(exp["source_lines"]), 3)
        for sl in exp["source_lines"]:
            self.assertIn("raw_text", sl)
            self.assertTrue(sl["raw_text"].strip(),
                            msg=f"source_line raw_text must be non-empty: {sl}")
            self.assertIn("label", sl)
            self.assertIn("file_offset", sl)

    def test_source_lines_are_verbatim_from_evidence(self):
        """The explainer must NOT reword evidence statements."""
        from mediahub.recognition.explainer import explain_achievement
        verbatim = "Swam 1:00.07 in 100m Butterfly (LC)"
        ach = {
            "type": "pb_confirmed",
            "swimmer_name": "Pat Q",
            "event": "100m Butterfly (LC)",
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "results_file",
                    "source_name": "Meet results",
                    "statement": verbatim,
                    "confidence": "high",
                },
            ],
        }
        factors = [
            {
                "name": "magnitude",
                "value": 0.55,
                "weight": 0.3,
                "reason": "ok",
                "plain_summary": "Solid result for this achievement type.",
            },
        ]
        exp = explain_achievement(ach, factors, rank=2)
        self.assertEqual(exp["source_lines"][0]["raw_text"], verbatim)


class TestExplainerFallback(unittest.TestCase):
    """When the explanation can't be grounded, return the safe fallback only."""

    def test_no_factors_no_evidence_returns_fallback(self):
        from mediahub.recognition.explainer import explain_achievement
        exp = explain_achievement({}, [], rank=7)
        self.assertEqual(exp["bullets"], [])
        self.assertEqual(exp["source_lines"], [])
        self.assertIn("top-7", exp["headline"])
        self.assertIn("ranked", exp["headline"].lower())

    def test_none_inputs_return_fallback(self):
        from mediahub.recognition.explainer import explain_achievement
        exp = explain_achievement(None, None)
        self.assertEqual(exp["bullets"], [])
        self.assertEqual(exp["source_lines"], [])
        self.assertIn("ranked", exp["headline"].lower())


class TestRankerProducesPlainSummary(unittest.TestCase):
    """After V9, every RankFactor returned by the ranker has a plain_summary."""

    def test_factors_have_plain_summary(self):
        from swim_content_v5.ranker import rank_achievements
        from swim_content_v5.schema import Achievement, MeetContext

        ach = Achievement(
            type="pb_confirmed",
            swim_id="x:50Free:LC:F:pb",
            swimmer_id="x",
            swimmer_name="Test Swimmer",
            event="50m Freestyle (LC)",
            headline="Test PB",
            angle_hint="hint",
            confidence=0.95,
            confidence_label="high",
            raw_facts={"drop_pct": 2.5, "drop_seconds": 0.6},
        )
        ctx = MeetContext(meet_name="Test", meet_level="county")
        ranked = rank_achievements([ach], ctx)
        self.assertEqual(len(ranked), 1)
        ra_dict = ranked[0].to_dict()
        self.assertIn("factors", ra_dict)
        # Every factor dict should expose a plain_summary key.
        for f in ra_dict["factors"]:
            self.assertIn("plain_summary", f,
                          msg=f"Factor {f.get('name')} missing plain_summary key")
        # At least one factor should have a non-empty summary (the certainty factor at 0.95).
        non_empty = [f for f in ra_dict["factors"] if (f.get("plain_summary") or "").strip()]
        self.assertGreater(len(non_empty), 0,
                           msg=f"Expected at least one populated plain_summary: {ra_dict['factors']}")


if __name__ == "__main__":
    unittest.main()
