"""Tests for the pure helper functions inside `mediahub.publishing.buffer`.

`tests/test_buffer_integration.py` and friends already exercise the
HTTP-facing entry points. This module focuses on the small,
deterministic helpers used by the error-handling paths — the bits
that decide whether a 429 surfaces with a retry-after, whether
auth-token blanks raise the right exception, and what message the
user sees when Buffer returns garbage.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.publishing.buffer import (
    BUFFER_API_BASE,
    BufferAPIError,
    BufferAuthError,
    BufferError,
    BufferRateLimitError,
    _parse_retry_after,
    _PreparedToken,
    _summarise_error_dict,
)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_base_url_is_buffer_api(self) -> None:
        assert BUFFER_API_BASE == "https://api.bufferapp.com"

    def test_exception_hierarchy(self) -> None:
        assert issubclass(BufferAuthError, BufferError)
        assert issubclass(BufferAPIError, BufferError)
        assert issubclass(BufferRateLimitError, BufferAPIError)


# ---------------------------------------------------------------------------
# _PreparedToken.require
# ---------------------------------------------------------------------------


class TestPreparedTokenRequire:
    def test_valid_token_passes_through_stripped(self) -> None:
        prep = _PreparedToken.require("  abc123  ")
        assert prep.token == "abc123"

    def test_none_raises_auth_error(self) -> None:
        with pytest.raises(BufferAuthError):
            _PreparedToken.require(None)

    def test_blank_raises_auth_error(self) -> None:
        with pytest.raises(BufferAuthError):
            _PreparedToken.require("")
        with pytest.raises(BufferAuthError):
            _PreparedToken.require("   ")

    def test_error_message_is_user_safe(self) -> None:
        # The message must NOT reveal anything implementation-y and
        # MUST direct the user to the administrator.
        try:
            _PreparedToken.require("")
        except BufferAuthError as exc:
            msg = str(exc)
            assert "Buffer is not configured" in msg
            assert "administrator" in msg.lower()
            # And must not leak any token bytes — there shouldn't be any here.
            assert "None" not in msg


# ---------------------------------------------------------------------------
# _parse_retry_after
# ---------------------------------------------------------------------------


def _mock_response(headers: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {})


class TestParseRetryAfter:
    def test_integer_seconds_parsed(self) -> None:
        assert _parse_retry_after(_mock_response({"Retry-After": "120"})) == 120

    def test_floating_point_seconds_rounded(self) -> None:
        # Implementation uses int(float(x)) so fractional seconds truncate.
        assert _parse_retry_after(_mock_response({"Retry-After": "120.7"})) == 120

    def test_zero_floor_at_one(self) -> None:
        # max(1, …) guarantees we never report a 0 retry-after.
        assert _parse_retry_after(_mock_response({"Retry-After": "0"})) == 1

    def test_missing_header_returns_none(self) -> None:
        assert _parse_retry_after(_mock_response({})) is None

    def test_blank_header_returns_none(self) -> None:
        assert _parse_retry_after(_mock_response({"Retry-After": ""})) is None

    def test_http_date_format_returns_none(self) -> None:
        # We deliberately don't parse HTTP-date — implementation notes it.
        assert (
            _parse_retry_after(_mock_response({"Retry-After": "Wed, 21 Oct 2024 07:28:00 GMT"}))
            is None
        )

    def test_garbage_value_returns_none(self) -> None:
        assert _parse_retry_after(_mock_response({"Retry-After": "soon"})) is None

    def test_none_response_handled(self) -> None:
        assert _parse_retry_after(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _summarise_error_dict
# ---------------------------------------------------------------------------


class TestSummariseErrorDict:
    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"message": "Caption is required"}, "Caption is required"),
            ({"error": "Invalid scheduled_at"}, "Invalid scheduled_at"),
            ({"description": "Profile not found"}, "Profile not found"),
        ],
    )
    def test_extracts_named_field(self, payload: dict, expected: str) -> None:
        assert _summarise_error_dict(payload) == expected

    def test_strips_whitespace_in_message(self) -> None:
        assert _summarise_error_dict({"message": "  trim me  "}) == "trim me"

    def test_message_wins_over_error_when_both_present(self) -> None:
        # The function probes keys in order: message, error, description.
        out = _summarise_error_dict({"message": "M", "error": "E", "description": "D"})
        assert out == "M"

    def test_error_used_when_message_missing(self) -> None:
        out = _summarise_error_dict({"error": "E", "description": "D"})
        assert out == "E"

    def test_blank_values_fall_through(self) -> None:
        out = _summarise_error_dict({"message": "  ", "error": "real error"})
        assert out == "real error"

    def test_empty_dict_returns_default(self) -> None:
        assert _summarise_error_dict({}) == "Buffer returned an error."

    def test_non_dict_input_returns_default(self) -> None:
        # The function defensively handles non-dict (e.g. list/None payloads).
        assert _summarise_error_dict([1, 2, 3]) == "Unexpected Buffer response."  # type: ignore[arg-type]
        assert _summarise_error_dict(None) == "Unexpected Buffer response."  # type: ignore[arg-type]

    def test_non_string_values_ignored(self) -> None:
        # If the API returned a number where a string is expected, fall through.
        assert _summarise_error_dict({"message": 42}) == "Buffer returned an error."


# ---------------------------------------------------------------------------
# BufferRateLimitError carries retry_after
# ---------------------------------------------------------------------------


class TestBufferRateLimitError:
    def test_carries_retry_after_value(self) -> None:
        err = BufferRateLimitError("Slow down", retry_after=120)
        assert err.retry_after == 120
        assert "Slow down" in str(err)

    def test_retry_after_optional_none(self) -> None:
        err = BufferRateLimitError("Slow down")
        assert err.retry_after is None

    def test_is_a_buffer_api_error(self) -> None:
        err = BufferRateLimitError("x", retry_after=10)
        assert isinstance(err, BufferAPIError)
        assert isinstance(err, BufferError)
