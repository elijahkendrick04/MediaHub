"""Roadmap 1.18 build 5 — Team Context assembly (collab.context)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp

    importlib.reload(cp)
    return tmp_path


def test_empty_org_degrades_gracefully(env):
    from mediahub.collab import context as ctx

    out = ctx.team_context("")
    assert out == {"brand": {}, "preferences": [], "recent": []}


def test_brand_block_from_profile(env):
    from mediahub.collab import context as ctx
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org1",
            display_name="City Swim",
            brand_voice_summary="Bold and proud.",
        )
    )
    out = ctx.team_context("org1")
    assert out["brand"]["display_name"] == "City Swim"
    assert out["brand"]["voice_summary"] == "Bold and proud."
    assert "preferences" in out and "recent" in out


def test_preferences_surface_assistant_memory(env):
    from mediahub.assistant import memory as _memory
    from mediahub.collab import context as ctx
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org1", display_name="City Swim"))
    try:
        _memory.remember("org1", "never show times for 8-and-unders")
    except Exception:
        pytest.skip("assistant memory store unavailable in this environment")
    out = ctx.team_context("org1")
    assert any("8-and-unders" in p for p in out["preferences"])


def test_never_raises_on_missing_db(env):
    from mediahub.collab import context as ctx

    # No data.db, no profile — must still return the empty shape, not raise.
    out = ctx.team_context("ghost-org")
    assert out["recent"] == []
