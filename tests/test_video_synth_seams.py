"""Tests for the gated generative seams: dub, object_removal, eye_contact (1.6).

All mirror the avatars/matting/broll guard-rail contract: off by default, explicit
opt-in required, disclosure forced, honest-error throughout. No network.
"""

from __future__ import annotations

import pytest

from mediahub.video import dub, eye_contact, object_removal


# --- dub (lip-sync / dubbing) ---------------------------------------------


def test_dub_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_DUB_PROVIDER", raising=False)
    assert dub.is_available() is False
    assert dub.dub_status()["available"] is False


def test_dub_requires_opt_in(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DUB_PROVIDER", "sync")
    monkeypatch.setenv("SYNC_API_KEY", "x")
    with pytest.raises(dub.DubConsentRequired):
        dub.build_request("cy", explicit_opt_in=False)


def test_dub_forces_disclosure_and_provenance(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_DUB_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    req = dub.build_request("Welsh", explicit_opt_in=True, voice_clone=True, disclosure="")
    assert req.disclosure == dub.DEFAULT_DISCLOSURE
    prov = req.provenance()
    assert prov["synthetic"] is True and prov["voice_cloned"] is True
    assert prov["target_language"] == "Welsh"


def test_dub_unknown_provider_and_generate_honest_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_DUB_PROVIDER", "nope")
    with pytest.raises(dub.DubUnavailable):
        dub.select_dub_provider()
    monkeypatch.setenv("MEDIAHUB_DUB_PROVIDER", "rask")
    monkeypatch.setenv("RASK_API_KEY", "x")
    req = dub.build_request("fr", explicit_opt_in=True)
    with pytest.raises(dub.DubUnavailable):
        dub.dub_clip(req, tmp_path / "in.mp4", tmp_path / "out.mp4")


# --- object_removal (inpainting) ------------------------------------------


def test_object_removal_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_OBJECT_REMOVAL_PROVIDER", raising=False)
    assert object_removal.is_available() is False


def test_object_removal_opt_in_and_honest_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_OBJECT_REMOVAL_PROVIDER", "replicate")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "x")
    with pytest.raises(object_removal.ObjectRemovalConsentRequired):
        object_removal.build_request(explicit_opt_in=False)
    req = object_removal.build_request(explicit_opt_in=True)
    assert req.provenance()["synthetic"] is True
    with pytest.raises(object_removal.ObjectRemovalUnavailable):
        object_removal.remove_object(req, tmp_path / "a.mp4", tmp_path / "m.png", tmp_path / "o.mp4")


# --- eye_contact (gaze correction — a pixel edit, NOT synthesis) -----------


def test_eye_contact_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_EYE_CONTACT_PROVIDER", raising=False)
    assert eye_contact.is_available() is False


def test_eye_contact_marks_edit_not_synthesis(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_EYE_CONTACT_PROVIDER", "replicate")
    monkeypatch.setenv("REPLICATE_API_TOKEN", "x")
    with pytest.raises(eye_contact.EyeContactConsentRequired):
        eye_contact.build_request(explicit_opt_in=False)
    req = eye_contact.build_request(explicit_opt_in=True)
    # The key distinction: it EDITS existing pixels, it does not fabricate a person.
    assert req.provenance()["synthetic"] is False
    assert eye_contact.status()["edits_not_synthesises"] is True
    with pytest.raises(eye_contact.EyeContactUnavailable):
        eye_contact.correct_gaze(req, tmp_path / "a.mp4", tmp_path / "o.mp4")
