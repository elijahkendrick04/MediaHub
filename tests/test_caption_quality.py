"""tests/test_caption_quality.py — PAR-1 caption quality pack tests.

Covers:
  - AI-tell ban-list detection (_contains_ai_tell)
  - N-gram similarity + near-duplicate detection
  - generate_caption_candidates: dedupe filtering and ban-list rejection
  - Few-shot example injection into generate_caption_for_tone system prompt
  - record_approved_caption / caption_examples store (approval loop)
  - generate_platform_variants: per-platform output shape
  - ClaudeUnavailableError still raised when no provider configured

All LLM calls are mocked — no network required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_SAMPLE_ACH = {
    "swim_id": "swim_001",
    "swimmer_name": "Alex Jordan",
    "event": "100m Freestyle",
    "time": "58.12",
    "pb": True,
    "type": "pb",
    "headline": "New PB in 100m Freestyle",
}

_BRIEF = "Alex Jordan swam 100m Freestyle in 58.12, a new personal best."


# ---------------------------------------------------------------------------
# 1. Ban-list detection
# ---------------------------------------------------------------------------

class TestBanListDetection:
    def test_delve_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("Let us delve into the performance") is True

    def test_elevate_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("We elevate our game today") is True

    def test_in_the_world_of_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("In the world of swimming, this matters.") is True

    def test_elevating_variant_detected(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("elevating the standard for the club") is True

    def test_clean_caption_passes(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("Alex smashed his 100m PB with a 58.12.") is False

    def test_case_insensitive(self):
        from mediahub.web.ai_caption import _contains_ai_tell
        assert _contains_ai_tell("DELVE deeper into excellence") is True

    def test_ban_list_exported(self):
        from mediahub.web.ai_caption import AI_TELL_BAN_LIST
        assert "delve" in AI_TELL_BAN_LIST
        assert "elevate" in AI_TELL_BAN_LIST
        assert "in the world of" in AI_TELL_BAN_LIST


# ---------------------------------------------------------------------------
# 2. N-gram similarity / deduplication
# ---------------------------------------------------------------------------

class TestNgramSimilarity:
    def test_identical_strings_score_one(self):
        from mediahub.web.ai_caption import _ngram_similarity
        assert _ngram_similarity("hello world foo bar", "hello world foo bar") == 1.0

    def test_completely_different_strings_score_low(self):
        from mediahub.web.ai_caption import _ngram_similarity
        score = _ngram_similarity("red car parked outside", "blue fish swimming quickly")
        assert score < 0.3

    def test_empty_string_returns_zero(self):
        from mediahub.web.ai_caption import _ngram_similarity
        assert _ngram_similarity("", "some text here") == 0.0

    def test_near_duplicate_detected(self):
        from mediahub.web.ai_caption import _is_near_duplicate
        ref = ["Alex smashed his 100m PB with a 58.12 time tonight."]
        candidate = "Alex smashed his 100m PB with a 58.12 time this evening."
        assert _is_near_duplicate(candidate, ref, threshold=0.5) is True

    def test_distinct_caption_not_flagged(self):
        from mediahub.web.ai_caption import _is_near_duplicate
        ref = ["Alex smashed his 100m PB with a time of 58.12."]
        candidate = "What a night for the club — personal bests all round!"
        assert _is_near_duplicate(candidate, ref, threshold=0.55) is False

    def test_empty_reference_list_returns_false(self):
        from mediahub.web.ai_caption import _is_near_duplicate
        assert _is_near_duplicate("Any caption.", [], threshold=0.5) is False


# ---------------------------------------------------------------------------
# 3. generate_caption_candidates — filtering behaviour
# ---------------------------------------------------------------------------

class TestGenerateCaptionCandidates:
    def test_returns_list_of_strings(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        captions = [
            "Caption alpha.", "Caption beta.", "Caption gamma.",
            "Caption delta.", "Caption epsilon.", "Caption zeta.",
        ]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=captions):
            result = generate_caption_candidates(_SAMPLE_ACH, n=4, brief_prose=_BRIEF)
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_count_respects_target(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        captions = [
            "Caption alpha.", "Caption beta.", "Caption gamma.",
            "Caption delta.", "Caption epsilon.", "Caption zeta.",
        ]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=captions):
            result = generate_caption_candidates(_SAMPLE_ACH, n=4, brief_prose=_BRIEF)
        assert len(result) == 4

    def test_drops_near_duplicates(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        duplicate = "Alex smashed his 100m PB with a 58.12 time tonight."
        near_dup  = "Alex smashed his 100m PB with a 58.12 time this evening."
        distinct1 = "What a race — personal best for Alex in the 100m!"
        distinct2 = "Brilliant swim from Alex, clocking 58.12 for a new PB."
        distinct3 = "Club record alert: Alex goes 58.12 in the 100m freestyle."
        pool = [duplicate, near_dup, distinct1, distinct2, distinct3, distinct3]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=pool):
            result = generate_caption_candidates(
                _SAMPLE_ACH, n=4, brief_prose=_BRIEF, dedupe_threshold=0.5
            )
        assert near_dup not in result

    def test_drops_ai_tells(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        bad    = "Let us delve into Alex's brilliant swim tonight."
        good1  = "Alex goes 58.12 for a club PB in the 100m!"
        good2  = "Personal best for Alex Jordan — 58.12 in the 100m."
        good3  = "Great night for Alex with a new 100m PB."
        good4  = "Alex Jordan breaks 59 seconds — 58.12 in the 100m freestyle."
        pool = [bad, good1, good2, good3, good4, good1]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=pool):
            result = generate_caption_candidates(_SAMPLE_ACH, n=4, brief_prose=_BRIEF)
        assert bad not in result

    def test_raises_unavailable_when_no_provider(self):
        from mediahub.web.ai_caption import (
            generate_caption_candidates,
            ClaudeUnavailableError,
        )
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=ClaudeUnavailableError("no key"),
        ):
            with pytest.raises(ClaudeUnavailableError):
                generate_caption_candidates(_SAMPLE_ACH, brief_prose=_BRIEF)

    def test_n_clamped_to_minimum_four(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        captions = [
            "Cap A.", "Cap B.", "Cap C.", "Cap D.", "Cap E.", "Cap F.",
        ]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=captions):
            result = generate_caption_candidates(
                _SAMPLE_ACH, n=1, brief_prose=_BRIEF
            )
        assert len(result) == 4

    def test_n_clamped_to_maximum_six(self):
        from mediahub.web.ai_caption import generate_caption_candidates
        captions = [f"Caption {i}." for i in range(10)]
        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=captions):
            result = generate_caption_candidates(
                _SAMPLE_ACH, n=100, brief_prose=_BRIEF
            )
        assert len(result) <= 6

    def test_candidates_ranked_freshest_first(self):
        # The candidate least similar to the recent captions (and its
        # siblings) must lead the list; one sharing phrasing with a recent
        # caption — below the dedupe threshold, so it survives — ranks last.
        from mediahub.web.ai_caption import generate_caption_candidates
        recent = "Eira Hughes stormed to a new personal best in the 200m freestyle tonight"
        stale = "A new personal best in the 200m freestyle for our brilliant captain Eira"
        fresh = [
            "Gold standard swimming from our captain at county champs.",
            "What a way to finish the season — superb racing throughout.",
            "The squad celebrated loudly as the scoreboard confirmed it.",
        ]
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=[stale] + fresh,
        ):
            result = generate_caption_candidates(
                _SAMPLE_ACH, n=4, brief_prose=_BRIEF, recent_captions=[recent]
            )
        assert set(result) == {stale, *fresh}
        assert result[-1] == stale  # most-overlapping candidate ranks last
        assert result[0] != stale


# ---------------------------------------------------------------------------
# 4. Few-shot injection in generate_caption_for_tone
# ---------------------------------------------------------------------------

class TestFewShotInjection:
    def test_examples_appear_in_system_prompt(self):
        from mediahub.web.ai_caption import generate_caption_for_tone
        examples = ["First example caption.", "Second example caption."]
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Generated caption."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_caption_for_tone(
                _SAMPLE_ACH,
                brief_prose=_BRIEF,
                few_shot_examples=examples,
            )

        assert len(captured) == 1
        assert "First example caption." in captured[0]
        assert "Second example caption." in captured[0]

    def test_examples_capped_at_five(self):
        from mediahub.web.ai_caption import generate_caption_for_tone
        # 10 examples; only the last 5 should appear
        examples = [f"Example {i}." for i in range(10)]
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Generated caption."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_caption_for_tone(
                _SAMPLE_ACH,
                brief_prose=_BRIEF,
                few_shot_examples=examples,
            )

        sys_prompt = captured[0]
        assert "Example 9." in sys_prompt
        assert "Example 5." in sys_prompt
        assert "Example 4." not in sys_prompt

    def test_no_examples_no_injection(self):
        from mediahub.web.ai_caption import generate_caption_for_tone
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Generated caption."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_caption_for_tone(_SAMPLE_ACH, brief_prose=_BRIEF)

        assert "Voice examples" not in captured[0]

    def test_ban_list_instruction_always_present(self):
        from mediahub.web.ai_caption import generate_caption_for_tone
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Generated caption."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_caption_for_tone(_SAMPLE_ACH, brief_prose=_BRIEF)

        assert "delve" in captured[0].lower()

    def test_empty_examples_list_no_injection(self):
        from mediahub.web.ai_caption import generate_caption_for_tone
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Generated caption."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_caption_for_tone(
                _SAMPLE_ACH, brief_prose=_BRIEF, few_shot_examples=[]
            )

        assert "Voice examples" not in captured[0]


# ---------------------------------------------------------------------------
# 5. Approval-loop / caption_examples store
# ---------------------------------------------------------------------------

class TestApprovalLoop:
    def test_record_then_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.ai_caption import record_approved_caption
        from mediahub.web.caption_examples import load_examples
        record_approved_caption("test-club", "Great swim from the team tonight!")
        loaded = load_examples("test-club")
        assert "Great swim from the team tonight!" in loaded

    def test_load_capped_at_five(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.caption_examples import append_example, load_examples
        for i in range(10):
            append_example("test-club-cap", f"Caption number {i}.")
        loaded = load_examples("test-club-cap")
        assert len(loaded) <= 5

    def test_load_returns_most_recent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.caption_examples import append_example, load_examples
        for i in range(8):
            append_example("test-club-recent", f"Caption {i}.")
        loaded = load_examples("test-club-recent")
        assert "Caption 7." in loaded
        assert "Caption 0." not in loaded

    def test_append_caps_total_at_fifty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.caption_examples import append_example, load_examples
        import json
        for i in range(55):
            append_example("test-club-50", f"Caption {i}.")
        path = tmp_path / "caption_examples" / "test-club-50.json"
        stored = json.loads(path.read_text())
        assert len(stored) == 50

    def test_invalid_profile_id_raises_load(self):
        from mediahub.web.caption_examples import load_examples
        with pytest.raises(ValueError):
            load_examples("../evil/path")

    def test_invalid_profile_id_raises_append(self):
        from mediahub.web.caption_examples import append_example
        with pytest.raises(ValueError):
            append_example("../evil/path", "caption")

    def test_empty_caption_not_stored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.caption_examples import append_example, load_examples
        append_example("test-club-empty", "   ")
        loaded = load_examples("test-club-empty")
        assert loaded == []

    def test_append_is_idempotent_per_caption(self, tmp_path, monkeypatch):
        # The approval seam runs on every content-pack build, so re-approving
        # the same card must not fill the store with copies of one caption.
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.web.caption_examples import append_example, load_examples
        for _ in range(4):
            append_example("test-club-idem", "Same approved caption.")
        assert load_examples("test-club-idem") == ["Same approved caption."]


# ---------------------------------------------------------------------------
# 5b. Approval-seam wiring: build_content_pack feeds the few-shot store
# ---------------------------------------------------------------------------

class TestApprovalSeamWiring:
    """An APPROVED card's final caption must land in the PAR-1 voice store.

    This is the loop that makes few-shot injection live for every club: the
    content-pack builder (the same seam Cap-2b semantic capture uses) appends
    the human-approved caption — edits included — to ``caption_examples``,
    and the live caption route reads it back as voice examples.
    """

    def _seed_run(self, runs_dir, run_id):
        import json as _json
        run = {
            "recognition_report": {
                "ranked_achievements": [
                    {
                        "rank": 1,
                        "priority": 0.9,
                        "achievement": {
                            "swim_id": "swim-1",
                            "swimmer_name": "Eira Hughes",
                            "event": "200m Freestyle",
                            "time": "2:08.41",
                        },
                    }
                ]
            }
        }
        (runs_dir / f"{run_id}.json").write_text(_json.dumps(run))

    def test_approved_caption_lands_in_store(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        self._seed_run(runs_dir, "run-1")

        from mediahub.workflow.pack import build_content_pack
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(runs_dir)
        ws.set_status("run-1", "swim-1", CardStatus.APPROVED)

        approved_caption = "Eira flies to a 200 free PB — what a swim!"

        def fake_apply_brand(card, kit, tone, kind, templates):
            out = dict(card)
            out["brand_captions"] = {"warm-club": {"headline": approved_caption}}
            return out

        with mock.patch(
            "mediahub.brand.store.load_brand",
            return_value=(object(), "warm-club", {}),
        ), mock.patch(
            "mediahub.brand.apply.apply_brand",
            side_effect=fake_apply_brand,
        ):
            pack = build_content_pack("run-1", "seam-club", runs_dir=runs_dir)
            # build twice: the seam must be idempotent per caption
            build_content_pack("run-1", "seam-club", runs_dir=runs_dir)

        assert len(pack) == 1
        from mediahub.web.caption_examples import load_examples
        assert load_examples("seam-club") == [approved_caption]


# ---------------------------------------------------------------------------
# 6. generate_platform_variants
# ---------------------------------------------------------------------------

class TestPlatformVariants:
    def test_returns_all_four_platforms_by_default(self):
        from mediahub.web.ai_caption import generate_platform_variants
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=["Feed.", "Story.", "X.", "LinkedIn."],
        ):
            result = generate_platform_variants("Original caption.")
        assert set(result.keys()) == {"feed", "story", "x", "linkedin"}

    def test_subset_of_platforms(self):
        from mediahub.web.ai_caption import generate_platform_variants
        with mock.patch(
            "mediahub.web.ai_caption.call_claude", return_value="Variant."
        ):
            result = generate_platform_variants(
                "Original.", platforms=["feed", "x"]
            )
        assert set(result.keys()) == {"feed", "x"}

    def test_returns_string_values(self):
        from mediahub.web.ai_caption import generate_platform_variants
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=["Feed.", "Story.", "X.", "LinkedIn."],
        ):
            result = generate_platform_variants("Original caption.")
        assert all(isinstance(v, str) for v in result.values())

    def test_raises_on_empty_base_caption(self):
        from mediahub.web.ai_caption import generate_platform_variants, ClaudeUnavailableError
        with pytest.raises(ClaudeUnavailableError):
            generate_platform_variants("")

    def test_raises_on_whitespace_base_caption(self):
        from mediahub.web.ai_caption import generate_platform_variants, ClaudeUnavailableError
        with pytest.raises(ClaudeUnavailableError):
            generate_platform_variants("   ")

    def test_raises_unavailable_when_no_provider(self):
        from mediahub.web.ai_caption import generate_platform_variants, ClaudeUnavailableError
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=ClaudeUnavailableError("no key"),
        ):
            with pytest.raises(ClaudeUnavailableError):
                generate_platform_variants("Some caption.", platforms=["feed"])

    def test_unknown_platforms_ignored(self):
        from mediahub.web.ai_caption import generate_platform_variants
        with mock.patch(
            "mediahub.web.ai_caption.call_claude", return_value="Variant."
        ):
            result = generate_platform_variants(
                "Original.", platforms=["feed", "nonexistent"]
            )
        assert set(result.keys()) == {"feed"}

    def test_all_unknown_platforms_returns_empty(self):
        from mediahub.web.ai_caption import generate_platform_variants
        result = generate_platform_variants(
            "Original.", platforms=["nonexistent"]
        )
        assert result == {}

    def test_few_shot_examples_forwarded_to_system_prompt(self):
        from mediahub.web.ai_caption import generate_platform_variants
        captured: list[str] = []

        def fake_call(system, user, **_):
            captured.append(system)
            return "Variant."

        with mock.patch("mediahub.web.ai_caption.call_claude", side_effect=fake_call):
            generate_platform_variants(
                "Original caption.",
                platforms=["feed"],
                few_shot_examples=["Club example one.", "Club example two."],
            )

        assert len(captured) == 1
        assert "Club example one." in captured[0]
        assert "Club example two." in captured[0]


# ---------------------------------------------------------------------------
# 7. generate_ai_caption still works (no-provider path unchanged)
# ---------------------------------------------------------------------------

class TestGenerateAICaptionNoProvider:
    def test_returns_error_dict_on_unavailable(self):
        from mediahub.web.ai_caption import generate_ai_caption, ClaudeUnavailableError
        with mock.patch(
            "mediahub.web.ai_caption.call_claude",
            side_effect=ClaudeUnavailableError("no key"),
        ):
            result = generate_ai_caption(_SAMPLE_ACH)
        assert result["fallback"] is True
        assert result["caption"] == ""
        assert "error" in result
