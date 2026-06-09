"""Tests for the reel-engine selection seam (roadmap P0.1).

Covers:
  - select_reel_engine() defaults and validation
  - reel_engine_status() shape and values
  - render_story_card / render_meet_reel dispatch (mock subprocess)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mediahub.visual.reel_engine import (
    ReelEngineUnavailable,
    reel_engine_status,
    select_reel_engine,
)
from mediahub.brand.kit import BrandKit
from mediahub.visual import motion


# ---------------------------------------------------------------------------
# select_reel_engine
# ---------------------------------------------------------------------------


def test_default_engine_is_remotion(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    assert select_reel_engine() == "remotion"


def test_blank_env_var_defaults_to_remotion(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "")
    assert select_reel_engine() == "remotion"


def test_whitespace_only_env_var_defaults_to_remotion(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "   ")
    assert select_reel_engine() == "remotion"


def test_explicit_remotion_is_accepted(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "remotion")
    assert select_reel_engine() == "remotion"


def test_engine_name_normalised_to_lowercase(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "REMOTION")
    assert select_reel_engine() == "remotion"


def test_satori_is_a_recognised_registered_engine(monkeypatch):
    """satori is registered as a future placeholder — select_reel_engine
    returns 'satori' rather than raising, so reel_engine_status() can
    surface the configured engine name.  The render functions raise
    ReelEngineUnavailable before touching Node (tested separately).
    """
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "satori")
    assert select_reel_engine() == "satori"


def test_unknown_engine_raises_unavailable(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg_standalone")
    with pytest.raises(ReelEngineUnavailable, match="not a recognised engine"):
        select_reel_engine()


def test_unknown_engine_error_names_valid_choices(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "bogus")
    with pytest.raises(ReelEngineUnavailable) as exc_info:
        select_reel_engine()
    msg = str(exc_info.value)
    assert "remotion" in msg
    assert "satori" in msg


# ---------------------------------------------------------------------------
# reel_engine_status
# ---------------------------------------------------------------------------


def test_reel_engine_status_has_required_keys(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    status = reel_engine_status()
    required = {
        "configured",
        "active",
        "remotion_available",
        "satori_available",
        "available_engines",
    }
    missing = required - set(status.keys())
    assert not missing, f"reel_engine_status() missing keys: {missing}"


def test_reel_engine_status_default_active_is_remotion(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    status = reel_engine_status()
    assert status["active"] == "remotion"
    assert status["configured"] == ""


def test_reel_engine_status_satori_available_always_false(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    status = reel_engine_status()
    assert status["satori_available"] is False


def test_reel_engine_status_available_engines_is_list(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    status = reel_engine_status()
    assert isinstance(status["available_engines"], list)


def test_reel_engine_status_surfaces_satori_as_active(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "satori")
    status = reel_engine_status()
    assert status["configured"] == "satori"
    assert status["active"] == "satori"


def test_reel_engine_status_surfaces_bad_engine_verbatim(monkeypatch):
    """An unrecognised engine value should not raise from status(); it
    surfaces the raw configured value so operators can see the bad input."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "not_a_real_engine")
    status = reel_engine_status()
    assert status["configured"] == "not_a_real_engine"
    assert status["active"] == "not_a_real_engine"


# ---------------------------------------------------------------------------
# Dispatch in render_story_card / render_meet_reel — mock subprocess so
# no Node process is spawned and the test runs in < 1 ms.
# ---------------------------------------------------------------------------


def _fake_brand() -> BrandKit:
    return BrandKit(
        profile_id="eng-test",
        display_name="Engine Test Club",
        primary_colour="#112233",
        secondary_colour="#445566",
        accent_colour="#778899",
        short_name="ETC",
    )


def _fake_card() -> dict:
    return {
        "id": "eng_c1",
        "achievement": {
            "swimmer_name": "Engine Tester",
            "event_name": "100m Free LC",
            "result_time": "00:55.00",
        },
    }


def _fake_run_remotion(**kwargs):
    """Writes a minimal stub MP4 to the requested out_path."""
    out = Path(kwargs["out_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
    return out


def test_render_story_card_uses_remotion_by_default(tmp_path, monkeypatch):
    """render_story_card routes through _run_remotion when engine is default."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion) as mock_run:
        out = tmp_path / "story.mp4"
        result = motion.render_story_card(_fake_card(), _fake_brand(), out)
        assert mock_run.called, "_run_remotion must be called for the remotion engine"
    assert Path(result).exists()


def test_render_meet_reel_uses_remotion_by_default(tmp_path, monkeypatch):
    """render_meet_reel routes through _run_remotion when engine is default."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion) as mock_run:
        out = tmp_path / "reel.mp4"
        result = motion.render_meet_reel([_fake_card()], _fake_brand(), out)
        assert mock_run.called, "_run_remotion must be called for the remotion engine"
    assert Path(result).exists()


def test_render_story_card_explicit_remotion_still_uses_run_remotion(tmp_path, monkeypatch):
    """Explicit MEDIAHUB_REEL_ENGINE=remotion must also call _run_remotion."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "remotion")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion) as mock_run:
        out = tmp_path / "story.mp4"
        motion.render_story_card(_fake_card(), _fake_brand(), out)
        assert mock_run.called


def test_render_story_card_raises_for_satori_engine(tmp_path, monkeypatch):
    """render_story_card raises ReelEngineUnavailable for satori; never emits
    a fake/placeholder asset (CLAUDE.md AI-surfaces honest-error rule)."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "satori")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    out = tmp_path / "story.mp4"
    with pytest.raises(ReelEngineUnavailable):
        motion.render_story_card(_fake_card(), _fake_brand(), out)
    assert not out.exists(), "No file must be written when the engine raises"


def test_render_meet_reel_raises_for_satori_engine(tmp_path, monkeypatch):
    """render_meet_reel raises ReelEngineUnavailable for satori; never emits
    a fake/placeholder asset."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "satori")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    out = tmp_path / "reel.mp4"
    with pytest.raises(ReelEngineUnavailable):
        motion.render_meet_reel([_fake_card()], _fake_brand(), out)
    assert not out.exists(), "No file must be written when the engine raises"


def test_satori_error_message_is_honest(tmp_path, monkeypatch):
    """The ReelEngineUnavailable message for satori must tell the operator
    what happened and how to fix it — not a vague crash."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "satori")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    out = tmp_path / "story.mp4"
    with pytest.raises(ReelEngineUnavailable) as exc_info:
        motion.render_story_card(_fake_card(), _fake_brand(), out)
    msg = str(exc_info.value).lower()
    assert "satori" in msg
    assert "not yet implemented" in msg or "remotion" in msg


def test_reelengine_unavailable_is_re_exported_from_motion():
    """ReelEngineUnavailable is accessible from mediahub.visual.motion so
    web-layer callers don't need a separate import."""
    from mediahub.visual.motion import ReelEngineUnavailable as _ReuseAlias  # noqa: F401

    assert _ReuseAlias is ReelEngineUnavailable
