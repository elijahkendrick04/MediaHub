"""Tests for video.broll — the opt-in, disclosed generative-b-roll seam (1.6).

Mirrors the avatars/matting guard-rail contract: off by default, explicit
opt-in required, disclosure forced, honest-error throughout. No network.
"""

from __future__ import annotations

import pytest

from mediahub.video import broll
from mediahub.video.broll import BrollConsentRequired, BrollUnavailable


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_BROLL_PROVIDER", raising=False)
    assert broll.select_broll_provider() == ""
    assert broll.is_available() is False
    status = broll.broll_status()
    assert status["available"] is False
    assert status["requires_explicit_opt_in"] is True
    assert status["disclosure_enforced"] is True


def test_unknown_provider_is_honest_error(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BROLL_PROVIDER", "sora9000")
    with pytest.raises(BrollUnavailable):
        broll.select_broll_provider()


def test_provider_without_key_is_unavailable(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BROLL_PROVIDER", "veo")
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert broll.is_available() is False


def test_build_request_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BROLL_PROVIDER", "veo")
    monkeypatch.setenv("GEMINI_API_KEY", "x")  # not a real key; gate is presence-only
    with pytest.raises(BrollConsentRequired):
        broll.build_request("a calm pool at dawn", explicit_opt_in=False)


def test_build_request_forces_disclosure(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_BROLL_PROVIDER", "runway")
    monkeypatch.setenv("RUNWAY_API_KEY", "x")
    req = broll.build_request("a calm pool at dawn", explicit_opt_in=True, disclosure="")
    assert req.disclosure == broll.DEFAULT_DISCLOSURE
    assert req.provenance()["synthetic"] is True
    assert req.provenance()["explicit_opt_in"] is True
    assert req.seconds <= broll.MAX_BROLL_SECONDS


def test_build_request_without_provider_is_unavailable(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_BROLL_PROVIDER", raising=False)
    with pytest.raises(BrollUnavailable):
        broll.build_request("a swimmer", explicit_opt_in=True)


def test_generate_is_honest_error_not_a_fabricated_clip(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_BROLL_PROVIDER", "luma")
    monkeypatch.setenv("LUMA_API_KEY", "x")
    req = broll.build_request("a calm pool", explicit_opt_in=True)
    with pytest.raises(BrollUnavailable):
        broll.generate_broll(req, tmp_path / "out.mp4")
