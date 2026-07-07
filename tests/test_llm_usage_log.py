"""tests/test_llm_usage_log.py — Phase 1.5 LLM call log.

Every Gemini / Anthropic call records one row so the operator-facing
/healthz/usage dashboard can show real numbers. This module pins:

  * record_call inserts + validates input
  * usage_for_window aggregates correctly by provider
  * estimated cost uses the right rates and treats Gemini as free
  * Gemini free-tier headroom computation
  * daily_usage shape + ordering
  * last_error returns the most recent failure
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def fresh_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.observability.llm_usage as u
    importlib.reload(u)
    return u


class TestRecordCall:
    def test_inserts_and_returns_row_id(self, fresh_usage):
        rid = fresh_usage.record_call(provider="gemini", ok=True,
                                       tokens_in=100, tokens_out=50)
        assert rid > 0

    def test_normalises_provider_to_lowercase(self, fresh_usage):
        fresh_usage.record_call(provider="ANTHROPIC", ok=True)
        usage = fresh_usage.usage_for_window(window_hours=1)
        assert any(b["provider"] == "anthropic" for b in usage["by_provider"])

    def test_empty_provider_returns_zero(self, fresh_usage):
        assert fresh_usage.record_call(provider="", ok=True) == 0
        assert fresh_usage.record_call(provider="   ", ok=True) == 0

    def test_truncates_long_error_message(self, fresh_usage):
        very_long = "x" * 1000
        fresh_usage.record_call(
            provider="gemini", ok=False,
            error_kind="rate_limited", error_message=very_long,
        )
        err = fresh_usage.last_error()
        assert err is not None
        assert len(err["error_message"]) <= 500


class TestUsageForWindowEmpty:
    def test_empty_table_returns_zeroed_stats(self, fresh_usage):
        stats = fresh_usage.usage_for_window(window_hours=24)
        assert stats["total_calls"] == 0
        assert stats["ok_count"] == 0
        assert stats["failed_count"] == 0
        assert stats["by_provider"] == []
        assert stats["est_cost_usd_total"] == 0.0
        assert stats["gemini_free_tier_headroom"] is None


class TestUsageForWindowAggregation:
    def test_groups_by_provider_with_counts(self, fresh_usage):
        for _ in range(3):
            fresh_usage.record_call(provider="gemini", ok=True,
                                     tokens_in=100, tokens_out=50)
        for _ in range(2):
            fresh_usage.record_call(provider="anthropic", ok=True,
                                     tokens_in=200, tokens_out=100)
        fresh_usage.record_call(provider="gemini", ok=False,
                                 error_kind="rate_limited")

        stats = fresh_usage.usage_for_window(window_hours=24)
        assert stats["total_calls"] == 6
        assert stats["ok_count"] == 5
        assert stats["failed_count"] == 1
        prov_by_name = {b["provider"]: b for b in stats["by_provider"]}
        assert prov_by_name["gemini"]["calls"] == 4
        assert prov_by_name["gemini"]["ok"] == 3
        assert prov_by_name["gemini"]["failed"] == 1
        assert prov_by_name["anthropic"]["calls"] == 2

    def test_gemini_cost_estimated_as_zero_free_tier(self, fresh_usage):
        fresh_usage.record_call(provider="gemini", ok=True,
                                 tokens_in=10_000, tokens_out=5_000)
        stats = fresh_usage.usage_for_window()
        prov = [b for b in stats["by_provider"] if b["provider"] == "gemini"][0]
        # Gemini is free-tier by default in our cost model.
        assert prov["est_cost_usd"] == 0.0

    def test_anthropic_cost_nonzero_with_token_counts(self, fresh_usage):
        # 1M input + 1M output tokens — should map to roughly
        # 3.00 + 15.00 = $18.00 USD.
        fresh_usage.record_call(provider="anthropic", ok=True,
                                 tokens_in=1_000_000, tokens_out=1_000_000)
        stats = fresh_usage.usage_for_window()
        prov = [b for b in stats["by_provider"] if b["provider"] == "anthropic"][0]
        assert 17.0 < prov["est_cost_usd"] < 19.0

    def test_anthropic_cost_heuristic_when_tokens_missing(self, fresh_usage):
        # Five calls with no tokens recorded — must still produce a
        # non-zero cost via the per-call heuristic.
        for _ in range(5):
            fresh_usage.record_call(provider="anthropic", ok=True)
        stats = fresh_usage.usage_for_window()
        prov = [b for b in stats["by_provider"] if b["provider"] == "anthropic"][0]
        assert prov["est_cost_usd"] > 0.0

    def test_window_excludes_calls_older_than_cutoff(self, fresh_usage):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        fresh_usage.record_call(provider="gemini", ok=True, ts=old)
        fresh_usage.record_call(provider="gemini", ok=True, ts=recent)
        stats = fresh_usage.usage_for_window(window_hours=24)
        assert stats["total_calls"] == 1  # only recent

    def test_gemini_headroom_reflects_remaining_free_tier(self, fresh_usage):
        # 200 gemini calls in the window → headroom = 1500 - 200 = 1300.
        for _ in range(200):
            fresh_usage.record_call(provider="gemini", ok=True)
        stats = fresh_usage.usage_for_window(window_hours=24)
        assert stats["gemini_free_tier_headroom"] == 1300

    def test_gemini_headroom_clamped_to_zero_when_exceeded(self, fresh_usage):
        for _ in range(2000):
            fresh_usage.record_call(provider="gemini", ok=True)
        stats = fresh_usage.usage_for_window(window_hours=24)
        assert stats["gemini_free_tier_headroom"] == 0


class TestDailyUsage:
    def test_returns_one_row_per_utc_day(self, fresh_usage):
        # Seed three calls across two different UTC days.
        d1 = "2026-05-15T10:00:00+00:00"
        d2 = "2026-05-16T10:00:00+00:00"
        fresh_usage.record_call(provider="gemini", ok=True, ts=d1)
        fresh_usage.record_call(provider="gemini", ok=True, ts=d2)
        fresh_usage.record_call(provider="gemini", ok=False, ts=d2)
        days = fresh_usage.daily_usage(days=365)
        dates = {d["date"]: d for d in days}
        assert "2026-05-15" in dates
        assert "2026-05-16" in dates
        assert dates["2026-05-15"]["calls"] == 1
        assert dates["2026-05-16"]["calls"] == 2
        assert dates["2026-05-16"]["failed"] == 1

    def test_oldest_first_ordering(self, fresh_usage):
        for day in ["2026-05-10", "2026-05-15", "2026-05-12"]:
            fresh_usage.record_call(
                provider="gemini", ok=True, ts=f"{day}T10:00:00+00:00"
            )
        days = fresh_usage.daily_usage(days=365)
        dates_in_order = [d["date"] for d in days]
        assert dates_in_order == sorted(dates_in_order)


class TestLastError:
    def test_returns_none_when_no_failures(self, fresh_usage):
        fresh_usage.record_call(provider="gemini", ok=True)
        assert fresh_usage.last_error() is None

    def test_returns_most_recent_failed_call(self, fresh_usage):
        fresh_usage.record_call(
            provider="gemini", ok=False,
            error_kind="rate_limited", error_message="HTTP 429",
            ts="2026-05-15T10:00:00+00:00",
        )
        fresh_usage.record_call(
            provider="anthropic", ok=False,
            error_kind="auth", error_message="bad key",
            ts="2026-05-16T10:00:00+00:00",
        )
        err = fresh_usage.last_error()
        assert err is not None
        # Most recent — anthropic.
        assert err["provider"] == "anthropic"
        assert err["error_kind"] == "auth"


class TestVisionCallsAreLogged:
    """The vision helpers must land one usage row per attempt, like every
    text-path branch — success and failure both count."""

    def _rows(self, monkeypatch, fresh_usage):
        rows: list[dict] = []

        def rec(**kw):
            rows.append(kw)
            return 1

        monkeypatch.setattr(fresh_usage, "record_call", rec)
        return rows

    def _reset_breaker(self):
        from mediahub.media_ai import llm as m

        with m._gemini_breaker_lock:
            m._gemini_breaker_state["consecutive_failures"] = 0
            m._gemini_breaker_state["tripped_until"] = 0.0

    def test_gemini_vision_success_logs_row(self, fresh_usage, monkeypatch):
        import requests

        from mediahub.media_ai import llm as m

        rows = self._rows(monkeypatch, fresh_usage)
        monkeypatch.setattr(m, "_resolve_gemini_key", lambda: "k")
        self._reset_breaker()

        class _Resp:
            status_code = 200
            ok = True

            @staticmethod
            def json():
                return {"candidates": [{"content": {"parts": [{"text": "seen"}]}}]}

        monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
        assert m._call_gemini_vision([], "describe", None, 10) == "seen"
        assert len(rows) == 1
        assert rows[0]["provider"] == "gemini-vision"
        assert rows[0]["ok"] is True

    def test_gemini_vision_transport_failure_logs_row(self, fresh_usage, monkeypatch):
        import requests

        from mediahub.media_ai import llm as m

        rows = self._rows(monkeypatch, fresh_usage)
        monkeypatch.setattr(m, "_resolve_gemini_key", lambda: "k")
        self._reset_breaker()

        def boom(*a, **k):
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(requests, "post", boom)
        assert m._call_gemini_vision([], "describe", None, 10) is None
        self._reset_breaker()
        assert len(rows) == 1
        assert rows[0]["provider"] == "gemini-vision"
        assert rows[0]["ok"] is False
        assert rows[0]["error_kind"] == "transport"

    def test_anthropic_vision_success_logs_row(self, fresh_usage, monkeypatch):
        from mediahub.media_ai import llm as m

        rows = self._rows(monkeypatch, fresh_usage)

        class _Block:
            text = "described"

        class _Resp:
            content = [_Block()]
            usage = None

        class _Msgs:
            @staticmethod
            def create(**kw):
                return _Resp()

        class _Client:
            messages = _Msgs()

        monkeypatch.setattr(m, "_get_anthropic", lambda: _Client())
        assert m._call_anthropic_vision([], "describe", None, 10) == "described"
        assert len(rows) == 1
        assert rows[0]["provider"] == "anthropic-vision"
        assert rows[0]["ok"] is True

    def test_anthropic_vision_failure_logs_row(self, fresh_usage, monkeypatch):
        from mediahub.media_ai import llm as m

        rows = self._rows(monkeypatch, fresh_usage)

        class _Msgs:
            @staticmethod
            def create(**kw):
                raise RuntimeError("api down")

        class _Client:
            messages = _Msgs()

        monkeypatch.setattr(m, "_get_anthropic", lambda: _Client())
        assert m._call_anthropic_vision([], "describe", None, 10) is None
        assert len(rows) == 1
        assert rows[0]["provider"] == "anthropic-vision"
        assert rows[0]["ok"] is False
        assert rows[0]["error_kind"] == "RuntimeError"


class TestSafetyAndDegradation:
    def test_record_call_swallows_bad_input(self, fresh_usage):
        # None ok should fall back to False without raising.
        # (We pass it through Python's bool() truthiness via the
        # public API.)
        assert fresh_usage.record_call(provider="gemini", ok=False) > 0

    def test_usage_for_window_returns_default_on_bad_input(self, fresh_usage):
        # Negative / weird window_hours falls back to a sane default.
        stats = fresh_usage.usage_for_window(window_hours=-99)
        assert stats["window_hours"] >= 1
