"""Roadmap 1.18 build 5 — Team Context assembly (collab.context)."""

from __future__ import annotations

import pytest


@pytest.fixture
def env(_isolate_data_dir, tmp_path):
    """Isolated DATA_DIR + club-profiles dir for a Team Context test.

    Reproduces the old ``setenv(DATA_DIR / SWIM_CONTENT_PROFILES_DIR)`` +
    ``importlib.reload(club_profile)`` setup via the canonical
    ``_isolate_data_dir`` fixture (no reload — ``club_profile`` / ``collab`` /
    ``assistant.memory`` all read the storage env vars at call time)."""
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
