"""P6.2 — Magic-Write caption text-tools added to caption_assist."""

from __future__ import annotations

from unittest import mock

from mediahub.web import caption_assist as ca


def test_new_text_tools_are_registered():
    for slug in ("summarise", "expand", "rewrite"):
        assert slug in ca.PRESETS
        assert slug in ca.PRESET_LABELS
        assert ca.resolve_instruction(slug)  # non-empty instruction


def test_original_presets_still_present():
    for slug in ("shorter", "punchier", "add_time", "tidy"):
        assert slug in ca.PRESETS


def test_resolve_instruction_custom_and_unknown():
    assert ca.resolve_instruction("custom", "make it rhyme") == "make it rhyme"
    assert ca.resolve_instruction("not_a_preset", "") == ""


def test_build_requirements_preserves_facts_instruction():
    req = ca.build_requirements("Alice Lee, 57.95 — new PB.", ca.PRESETS["summarise"])
    assert "Revise the existing caption" in req
    assert "Keep every" in req
    assert "57.95" in req  # the current caption is embedded verbatim


def test_assist_caption_routes_through_writer_with_requirements():
    seen = {}

    def fake_writer(achievement, club_brand=None, *, tone="warm-club", voice_profile=None, club_profile=None, requirements="", **kw):
        seen["requirements"] = requirements
        seen["tone"] = tone
        return "Alice Lee smashed a new PB — 57.95 in the 100 Free."

    with mock.patch("mediahub.web.ai_caption.generate_caption_for_tone", fake_writer):
        out = ca.assist_caption(
            {"swimmer_name": "Alice Lee"},
            "Alice Lee, 57.95 — new PB.",
            "rewrite",
            tone="hype",
        )
    assert out.startswith("Alice Lee")
    assert "fresh angle" in seen["requirements"]
    assert seen["tone"] == "hype"  # tone-shift rides the existing tone arg
