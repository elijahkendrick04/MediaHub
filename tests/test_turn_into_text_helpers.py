"""Tests for the small text helpers in `mediahub.turn_into.templates`.

The artefact *builders* in this module call out to the cloud LLM and
aren't directly testable without provider mocks. The string helpers
they reuse (`_truncate`, `_ensure_numbered`, `_esc`, `_top_swimmers`,
`_format_name`) are pure and deterministic — pinning them here is a
cheap safety net for the artefact-rendering path.
"""
from __future__ import annotations

import pytest

from mediahub.turn_into.templates import (
    _ensure_numbered,
    _esc,
    _format_name,
    _top_swimmers,
    _truncate,
)


# ---------------------------------------------------------------------------
# _truncate — ellipsis-truncate-on-limit
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_returned_intact(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        out = _truncate("hello world", 7)
        # The implementation uses a single-char ellipsis.
        assert out.endswith("…")
        assert len(out) <= 7

    def test_empty_safe(self) -> None:
        assert _truncate("", 10) == ""
        assert _truncate(None, 10) == ""  # type: ignore[arg-type]

    def test_strips_whitespace_before_check(self) -> None:
        # The implementation strips first, then measures.
        assert _truncate("   hi   ", 10) == "hi"

    def test_limit_exactly_at_length(self) -> None:
        assert _truncate("abcde", 5) == "abcde"


# ---------------------------------------------------------------------------
# _ensure_numbered — Twitter-style "1/" prefix
# ---------------------------------------------------------------------------


class TestEnsureNumbered:
    def test_prepends_when_missing(self) -> None:
        assert _ensure_numbered("first post", 1) == "1/ first post"

    @pytest.mark.parametrize(
        "raw, n",
        [
            ("1/ first post", 1),
            ("1. first post", 1),
            ("1) first post", 1),
            ("2/ second post", 2),
        ],
    )
    def test_preserves_existing_marker(self, raw: str, n: int) -> None:
        assert _ensure_numbered(raw, n) == raw

    def test_strips_whitespace(self) -> None:
        assert _ensure_numbered("  body  ", 3) == "3/ body"

    def test_empty_input_still_prefixed(self) -> None:
        # Returns "<n>/ " with the empty body.
        assert _ensure_numbered("", 1) == "1/ "


# ---------------------------------------------------------------------------
# _esc — HTML entity escape for newsletter strings
# ---------------------------------------------------------------------------


class TestEsc:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("&", "&amp;"),
            ("<b>", "&lt;b&gt;"),
            ('"hi"', "&quot;hi&quot;"),
            ("ok", "ok"),
            ("a & b < c", "a &amp; b &lt; c"),
        ],
    )
    def test_escapes_html_metacharacters(self, raw: str, expected: str) -> None:
        assert _esc(raw) == expected

    def test_handles_empty(self) -> None:
        assert _esc("") == ""
        assert _esc(None) == ""  # type: ignore[arg-type]

    def test_does_not_double_escape(self) -> None:
        # _esc is a single pass — calling it on already-escaped output is NOT
        # idempotent (& becomes &amp; → &amp;amp;). Pin that so a contributor
        # doesn't accidentally double-escape elsewhere.
        out = _esc(_esc("a & b"))
        assert out == "a &amp;amp; b"


# ---------------------------------------------------------------------------
# _format_name — voice profile name preference
# ---------------------------------------------------------------------------


class _FakeVoiceProfile:
    def __init__(self, formatted: str | None = None, raise_on_get: bool = False):
        self._formatted = formatted
        self._raise = raise_on_get

    def get_name(self, first: str, last: str) -> str:
        if self._raise:
            raise RuntimeError("voice failed")
        return self._formatted or first


class TestFormatName:
    def test_none_voice_returns_first_name(self) -> None:
        assert _format_name(None, "Jane", "Smith") == "Jane"

    def test_none_voice_falls_back_to_last(self) -> None:
        assert _format_name(None, "", "Smith") == "Smith"

    def test_none_voice_with_blank_names_returns_generic(self) -> None:
        assert _format_name(None, "", "") == "the swimmer"

    def test_voice_get_name_used(self) -> None:
        vp = _FakeVoiceProfile(formatted="Smith, J")
        assert _format_name(vp, "Jane", "Smith") == "Smith, J"

    def test_voice_exception_falls_back_to_first_name(self) -> None:
        vp = _FakeVoiceProfile(raise_on_get=True)
        assert _format_name(vp, "Jane", "Smith") == "Jane"


# ---------------------------------------------------------------------------
# _top_swimmers — pick top-N distinct swimmers
# ---------------------------------------------------------------------------


def _ra(swimmer_id: str | None = None, swimmer_name: str | None = None) -> dict:
    ach: dict = {}
    if swimmer_id:
        ach["swimmer_id"] = swimmer_id
    if swimmer_name:
        ach["swimmer_name"] = swimmer_name
    return {"achievement": ach}


class TestTopSwimmers:
    def test_distinct_swimmers_picked(self) -> None:
        items = [
            _ra(swimmer_id="a"),
            _ra(swimmer_id="b"),
            _ra(swimmer_id="a"),  # duplicate
            _ra(swimmer_id="c"),
        ]
        out = _top_swimmers(items, n=3)
        assert len(out) == 3
        # Order preserved by first appearance.
        keys = [r["achievement"]["swimmer_id"] for r in out]
        assert keys == ["a", "b", "c"]

    def test_n_caps_result(self) -> None:
        items = [_ra(swimmer_id=f"s{i}") for i in range(10)]
        assert len(_top_swimmers(items, n=3)) == 3

    def test_empty_input_yields_empty(self) -> None:
        assert _top_swimmers([], n=5) == []

    def test_swimmer_without_id_uses_name(self) -> None:
        items = [
            _ra(swimmer_name="Jane Smith"),
            _ra(swimmer_name="Jane Smith"),
            _ra(swimmer_name="Eve Adams"),
        ]
        out = _top_swimmers(items, n=5)
        assert len(out) == 2

    def test_anonymous_swimmers_skipped(self) -> None:
        items = [
            _ra(),
            _ra(swimmer_id="real"),
            _ra(),
        ]
        out = _top_swimmers(items, n=5)
        assert len(out) == 1
        assert out[0]["achievement"]["swimmer_id"] == "real"
