"""Tests for video.avatars — opt-in + disclosure enforcement (roadmap 1.6).

The no-synthetic-people rule is enforced in code: off by default, explicit
per-call opt-in required, disclosure forced, no undisclosed path.
"""

from __future__ import annotations

import pytest

from mediahub.video.avatars import (
    DEFAULT_DISCLOSURE,
    AvatarConsentRequired,
    AvatarsUnavailable,
    avatar_status,
    build_request,
    is_available,
    select_avatar_provider,
    synthesize_avatar,
)


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_AVATAR_PROVIDER", raising=False)
    assert select_avatar_provider() == ""
    assert is_available() is False


def test_build_request_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_AVATAR_PROVIDER", "did")
    monkeypatch.setenv("DID_API_KEY", "x")
    with pytest.raises(AvatarConsentRequired):
        build_request("hello", explicit_opt_in=False)


def test_build_request_needs_provider(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_AVATAR_PROVIDER", raising=False)
    with pytest.raises(AvatarsUnavailable):
        build_request("hello", explicit_opt_in=True)


def test_build_request_forces_disclosure(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_AVATAR_PROVIDER", "heygen")
    monkeypatch.setenv("HEYGEN_API_KEY", "k")
    req = build_request("Welcome to the gala", explicit_opt_in=True, disclosure="")
    assert req.disclosure == DEFAULT_DISCLOSURE
    assert req.explicit_opt_in is True
    prov = req.provenance()
    assert prov["synthetic"] is True
    assert prov["disclosure"] == DEFAULT_DISCLOSURE
    assert prov["explicit_opt_in"] is True


def test_custom_disclosure_preserved(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_AVATAR_PROVIDER", "did")
    monkeypatch.setenv("DID_API_KEY", "k")
    req = build_request("hi", explicit_opt_in=True, disclosure="AI presenter — not a real person")
    assert "not a real person" in req.disclosure


def test_synthesize_is_honest_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_AVATAR_PROVIDER", "did")
    monkeypatch.setenv("DID_API_KEY", "k")
    req = build_request("hi", explicit_opt_in=True)
    with pytest.raises(AvatarsUnavailable):
        synthesize_avatar(req, tmp_path / "out.mp4")


def test_status_advertises_enforcement(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_AVATAR_PROVIDER", raising=False)
    s = avatar_status()
    assert s["requires_explicit_opt_in"] is True
    assert s["disclosure_enforced"] is True
    assert s["available"] is False
