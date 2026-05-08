"""
tests_v75/test_voice_induce.py — Tests for the V7.5 voice induction engine.

Verifies:
1. extract_features() returns correct measurements (within tolerance) for
   posts with known characteristics.
2. induce_voice() produces a well-formed VoiceProfile.
3. Save + load round-trip is lossless.
4. render_caption() produces non-empty output for any loaded profile.
5. list_voices() returns the three seed voices.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Make sure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mediahub.voice.learned.feature_extract import extract_features
from mediahub.voice.learned.induce import induce_voice
from mediahub.voice.learned.models import VoiceFeatures, VoiceProfile
from mediahub.voice.learned.render import render_caption
from mediahub.voice.learned.store import (
    delete_voice,
    list_voices,
    load_voice,
    save_voice,
)

# ---------------------------------------------------------------------------
# Fixtures — posts with predictable characteristics
# ---------------------------------------------------------------------------

# Posts with lots of emojis, hashtags and exclamations
HYPE_POSTS = [
    "🔥🔥 AMAZING swim!! Josh just SMASHED his PB in the 100m Free!! 51.34!! 🚀🚀 #SwimHard #FastSwim",
    "INCREDIBLE result!! 🥇🥇 Gold medal for Mia!! What a performance!! 🔥🔥🔥 #Champion #SwimLife",
    "WOW!! THREE PBs in one day!! 💥💥 This squad is UNSTOPPABLE!! Huge day!! 🙌🙌 #SquadGoals #PBSzn",
]

# Posts that are warm / community-focused, sentence-case, fewer emojis
WARM_POSTS = [
    "Well done to Emma on her new personal best in the 200m Backstroke at the county championships! 🏊\n"
    "Emma touched the wall in 2:23.45 — a fantastic improvement.\n"
    "So proud of everyone who swam this weekend! Keep it up.\n"
    "#SwimClub #TeamWork",

    "Huge congratulations to our relay team on their bronze medal performance at regionals! 🥉\n"
    "The boys swam a brilliant 3:45.12 in the 4×100 Medley.\n"
    "Really proud of the hard work the whole squad has put in.\n"
    "#ClubSwim #RelayTeam",

    "A special mention to young Ben, age 10, who broke the 30-second barrier in the 50m Freestyle today!\n"
    "Ben swam 29.77 — what a milestone! Looking forward to seeing more from this talented swimmer.\n"
    "#JuniorSwim #FutureStars",
]

# Posts with analytical, data-heavy, low-emoji content
DATA_POSTS = [
    "Meet recap | 400m IM — Open Women\nHarriet Clarke: 4:51.07 (PB, −3.44s)\nSplit: Fly 65.3 | Back 74.1 | Breast 86.2 | Free 65.47\n#SwimData",
    "Club summary: 47 swims, 14 PBs (29.8%). Average improvement: −0.7%.\nTop drop: Ryan Bowen 50m Fly −2.8% (26.03 → 25.30).\n#Analytics",
    "Training metrics: avg RPE 6.2 (vs 6.8 prior year). Pace in main sets: 1:04.3 (vs 1:05.1).\nConclusion: squad trending ahead of taper profile.\n#TrainingData",
]


# ---------------------------------------------------------------------------
# 1. extract_features — known characteristics
# ---------------------------------------------------------------------------


class TestExtractFeatures:
    def test_hype_emoji_density_high(self):
        feats = extract_features(HYPE_POSTS)
        # Hype posts are emoji-heavy
        assert feats.emoji_density > 1.0, (
            f"Expected emoji_density > 1.0, got {feats.emoji_density}"
        )

    def test_hype_exclamation_density_high(self):
        feats = extract_features(HYPE_POSTS)
        assert feats.exclamation_density > 1.0, (
            f"Expected exclamation_density > 1.0, got {feats.exclamation_density}"
        )

    def test_hype_emoji_palette_non_empty(self):
        feats = extract_features(HYPE_POSTS)
        assert len(feats.emoji_palette) > 0

    def test_hype_capitalisation_all_caps_emphasis(self):
        feats = extract_features(HYPE_POSTS)
        assert feats.capitalisation_style == "all_caps_emphasis"

    def test_warm_emoji_density_lower_than_hype(self):
        warm_feats = extract_features(WARM_POSTS)
        hype_feats = extract_features(HYPE_POSTS)
        assert warm_feats.emoji_density < hype_feats.emoji_density

    def test_warm_hashtags_present(self):
        feats = extract_features(WARM_POSTS)
        assert feats.hashtag_density > 0
        assert len(feats.common_hashtags) > 0

    def test_warm_starting_phrases_extracted(self):
        feats = extract_features(WARM_POSTS)
        # At least one starting phrase should be captured
        assert len(feats.starting_phrases) >= 1

    def test_data_emoji_density_low(self):
        feats = extract_features(DATA_POSTS)
        # Data posts have no emojis
        assert feats.emoji_density == 0.0

    def test_data_time_format_detected(self):
        feats = extract_features(DATA_POSTS)
        # Posts have centisecond times like 4:51.07
        assert feats.time_format in ("m:ss.cc", "m:ss"), (
            f"Unexpected time_format: {feats.time_format}"
        )

    def test_data_achievement_words_extracted(self):
        feats = extract_features(DATA_POSTS)
        assert isinstance(feats.achievement_words, list)

    def test_avg_sentence_len_positive(self):
        for posts in (HYPE_POSTS, WARM_POSTS, DATA_POSTS):
            feats = extract_features(posts)
            assert feats.avg_sentence_len > 0

    def test_second_person_density_warm(self):
        feats = extract_features(WARM_POSTS)
        # Warm posts don't use much second-person
        assert feats.second_person_density >= 0

    def test_empty_input_returns_defaults(self):
        feats = extract_features([])
        assert feats.avg_sentence_len == 0.0
        assert feats.emoji_density == 0.0

    def test_single_post(self):
        feats = extract_features(["Hello world! Great swim 🏊"])
        assert feats.avg_sentence_len > 0
        assert feats.emoji_density > 0

    def test_features_values_in_range(self):
        feats = extract_features(HYPE_POSTS)
        assert feats.emoji_density >= 0
        assert feats.hashtag_density >= 0
        assert feats.exclamation_density >= 0
        assert feats.second_person_density >= 0
        assert feats.avg_sentence_len >= 0
        assert feats.capitalisation_style in ("sentence", "title", "all_caps_emphasis")
        assert feats.name_format in ("first_only", "full", "first_initial")
        assert feats.time_format in ("m:ss.cc", "m:ss", "prose")


# ---------------------------------------------------------------------------
# 2. induce_voice
# ---------------------------------------------------------------------------


class TestInduceVoice:
    def test_returns_voice_profile(self):
        profile = induce_voice("test_warm", "Test Warm", WARM_POSTS)
        assert isinstance(profile, VoiceProfile)

    def test_voice_id_set(self):
        profile = induce_voice("my_voice", "My Voice", WARM_POSTS)
        assert profile.voice_id == "my_voice"

    def test_display_name_set(self):
        profile = induce_voice("my_voice", "My Voice", WARM_POSTS)
        assert profile.display_name == "My Voice"

    def test_exemplars_stored(self):
        profile = induce_voice("x", "X", WARM_POSTS)
        assert profile.exemplars == WARM_POSTS

    def test_description_set(self):
        profile = induce_voice("x", "X", WARM_POSTS, description="Test desc")
        assert profile.description == "Test desc"

    def test_features_computed(self):
        profile = induce_voice("x", "X", HYPE_POSTS)
        assert isinstance(profile.features, VoiceFeatures)
        assert profile.features.emoji_density > 0

    def test_timestamps_set(self):
        profile = induce_voice("x", "X", WARM_POSTS)
        assert profile.created_at != ""
        assert profile.updated_at != ""


# ---------------------------------------------------------------------------
# 3. Save + Load round-trip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    def test_save_creates_file(self, tmp_path):
        profile = induce_voice("round_trip_test", "Round Trip", WARM_POSTS)
        path = save_voice(profile, base_dir=tmp_path)
        assert path.exists()

    def test_load_by_id(self, tmp_path):
        profile = induce_voice("round_trip_test", "Round Trip", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("round_trip_test", base_dir=tmp_path)
        assert loaded.voice_id == "round_trip_test"

    def test_round_trip_display_name(self, tmp_path):
        profile = induce_voice("test_voice", "Display Name Test", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.display_name == "Display Name Test"

    def test_round_trip_exemplars(self, tmp_path):
        profile = induce_voice("test_voice", "X", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.exemplars == WARM_POSTS

    def test_round_trip_features(self, tmp_path):
        profile = induce_voice("test_voice", "X", HYPE_POSTS)
        original_density = profile.features.emoji_density
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert abs(loaded.features.emoji_density - original_density) < 0.0001

    def test_round_trip_capitalisation(self, tmp_path):
        profile = induce_voice("test_voice", "X", HYPE_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.features.capitalisation_style == profile.features.capitalisation_style

    def test_round_trip_emoji_palette(self, tmp_path):
        profile = induce_voice("test_voice", "X", HYPE_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.features.emoji_palette == profile.features.emoji_palette

    def test_round_trip_common_hashtags(self, tmp_path):
        profile = induce_voice("test_voice", "X", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.features.common_hashtags == profile.features.common_hashtags

    def test_round_trip_starting_phrases(self, tmp_path):
        profile = induce_voice("test_voice", "X", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        loaded = load_voice("test_voice", base_dir=tmp_path)
        assert loaded.features.starting_phrases == profile.features.starting_phrases

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_voice("does_not_exist", base_dir=tmp_path)

    def test_to_dict_from_dict_round_trip(self):
        profile = induce_voice("test_voice", "X", HYPE_POSTS)
        d = profile.to_dict()
        reloaded = VoiceProfile.from_dict(d)
        assert reloaded.voice_id == profile.voice_id
        assert reloaded.features.emoji_density == profile.features.emoji_density

    def test_json_file_is_valid_json(self, tmp_path):
        profile = induce_voice("json_test", "JSON Test", DATA_POSTS)
        path = save_voice(profile, base_dir=tmp_path)
        # Must be valid JSON
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["voice_id"] == "json_test"

    def test_delete_voice(self, tmp_path):
        profile = induce_voice("delete_me", "Delete Me", WARM_POSTS)
        save_voice(profile, base_dir=tmp_path)
        result = delete_voice("delete_me", base_dir=tmp_path)
        assert result is True
        assert not (tmp_path / "delete_me.json").exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        result = delete_voice("nonexistent", base_dir=tmp_path)
        assert result is False


# ---------------------------------------------------------------------------
# 4. list_voices — seed files
# ---------------------------------------------------------------------------


class TestListVoices:
    def test_list_voices_returns_seed_voices(self):
        """list_voices with include_seed=True must return at least the 3 seeds."""
        voices = list_voices(include_seed=True)
        ids = {v.voice_id for v in voices}
        assert "warm_club" in ids, f"warm_club not found in {ids}"
        assert "hype" in ids, f"hype not found in {ids}"
        assert "data_led" in ids, f"data_led not found in {ids}"

    def test_list_voices_returns_voice_profiles(self):
        voices = list_voices(include_seed=True)
        for v in voices:
            assert isinstance(v, VoiceProfile)

    def test_list_voices_sorted_by_display_name(self):
        voices = list_voices(include_seed=True)
        names = [v.display_name.lower() for v in voices]
        assert names == sorted(names)

    def test_list_voices_from_tmp_dir(self, tmp_path):
        """list_voices from an empty directory returns empty list."""
        voices = list_voices(base_dir=tmp_path, include_seed=False)
        assert voices == []

    def test_list_voices_custom_dir(self, tmp_path):
        for i, (posts, label) in enumerate([(WARM_POSTS, "Warm"), (HYPE_POSTS, "Hype")]):
            p = induce_voice(f"voice_{i}", label, posts)
            save_voice(p, base_dir=tmp_path)
        voices = list_voices(base_dir=tmp_path, include_seed=False)
        assert len(voices) == 2


# ---------------------------------------------------------------------------
# 5. render_caption — uses loaded profiles
# ---------------------------------------------------------------------------

SAMPLE_ACHIEVEMENT = {
    "swimmer_first": "Emma",
    "swimmer_last": "Davies",
    "event": "200m Backstroke",
    "time": "2:23.45",
    "pb": True,
    "meet": "County Championships",
    "place": "1st",
}


class TestRenderCaption:
    def _load_seed(self, voice_id: str) -> VoiceProfile:
        seed_dir = Path(__file__).resolve().parents[1] / "data" / "voices" / "seed"
        from mediahub.voice.learned.store import load_voice_from_path
        return load_voice_from_path(seed_dir / f"{voice_id}.json")

    def test_render_returns_list(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, n_variants=1, seed=42)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_render_non_empty_string(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert result[0].strip() != ""

    def test_render_multiple_variants(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, n_variants=3, seed=42)
        assert len(result) == 3

    def test_render_includes_swimmer_name(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        # First name should appear in the caption
        assert "Emma" in result[0]

    def test_render_includes_time(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        # Time (or part of it) should appear
        assert "2:23" in result[0]

    def test_render_pb_flag(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert "PB" in result[0] or "pb" in result[0].lower()

    def test_render_warm_seed(self):
        profile = self._load_seed("warm_club")
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert len(result) == 1
        assert result[0].strip() != ""

    def test_render_hype_seed(self):
        profile = self._load_seed("hype")
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert len(result) == 1
        assert result[0].strip() != ""

    def test_render_data_led_seed(self):
        profile = self._load_seed("data_led")
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert len(result) == 1
        assert result[0].strip() != ""

    def test_render_empty_achievement(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result = render_caption({}, profile, seed=42)
        assert len(result) == 1
        assert isinstance(result[0], str)

    def test_render_deterministic_with_seed(self):
        profile = induce_voice("render_test", "Render Test", WARM_POSTS)
        result1 = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=99)
        result2 = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=99)
        assert result1 == result2

    def test_render_hype_seed_includes_emojis(self):
        """Hype profile has high emoji_density — caption should have emojis."""
        profile = self._load_seed("hype")
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        # Check there are some emoji characters in the output
        import re
        emoji_re = re.compile(
            r"[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0001F600-\U0001F64F"
            r"\U0001F680-\U0001F6FF]+",
            flags=re.UNICODE,
        )
        assert emoji_re.search(result[0]), "Hype caption should contain emojis"

    def test_render_data_led_seed_has_hashtags(self):
        """Data-led profile has hashtags — caption should include them."""
        profile = self._load_seed("data_led")
        result = render_caption(SAMPLE_ACHIEVEMENT, profile, seed=42)
        assert "#" in result[0], "Data-led caption should contain hashtags"
