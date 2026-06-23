"""1.21 public API — the per-token fixed-window rate limiter."""

from __future__ import annotations

import pytest

from mediahub.api_public.ratelimit import RateLimiter


@pytest.fixture(autouse=True)
def _default_limit(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_API_RATELIMIT_PER_MIN", raising=False)


def test_allows_up_to_the_limit_then_blocks(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "3")
    rl = RateLimiter()
    t = 1000.0
    assert [rl.check("k", now=t).allowed for _ in range(3)] == [True, True, True]
    blocked = rl.check("k", now=t)
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.reset_after > 0


def test_window_rolls_over(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "1")
    rl = RateLimiter()
    assert rl.check("k", now=1000.0).allowed is True
    assert rl.check("k", now=1000.0).allowed is False
    # 61s later → new window.
    assert rl.check("k", now=1061.0).allowed is True


def test_keys_are_independent(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "1")
    rl = RateLimiter()
    assert rl.check("a", now=1.0).allowed is True
    assert rl.check("b", now=1.0).allowed is True  # different key, own budget


def test_zero_disables_limiting(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "0")
    rl = RateLimiter()
    for _ in range(1000):
        assert rl.check("k", now=1.0).allowed is True


def test_remaining_counts_down(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_API_RATELIMIT_PER_MIN", "5")
    rl = RateLimiter()
    assert rl.check("k", now=1.0).remaining == 4
    assert rl.check("k", now=1.0).remaining == 3
