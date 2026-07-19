"""tests/test_org_colour_pickers_take_effect.py — the /organisation colour
pickers actually change the rendered palette (audit finding G-4).

The legacy page wrote the pickers straight to brand_primary/secondary, which
lose to brand_palette_manual/extracted in the resolution order. So any club
that went through AI setup (has brand_palette_extracted) could change colours
here, see "Organisation saved." and have every card and reel keep the old
palette — a silent no-op. The fix pins a *changed* colour into
brand_palette_manual (the winning slot) and recomputes the derived theme.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def env(web_module):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    import mediahub.web.club_profile as cp

    # A club that went through AI setup: an extracted palette, no manual override.
    prof = cp.ClubProfile(profile_id="otters", display_name="Otters SC")
    prof.brand_palette_extracted = {"primary": "#111111", "secondary": "#222222"}
    cp.save_profile(prof)
    assert prof.get_brand_kit().primary_colour.lower() == "#111111"

    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, cp


def _post_colours(client, primary, secondary):
    return client.post(
        "/organisation",
        data={
            "action": "save",
            "profile_id": "otters",
            "display_name": "Otters SC",
            "brand_primary": primary,
            "brand_secondary": secondary,
        },
    )


def test_changed_colour_pins_to_manual_and_takes_effect(env):
    app, cp = env
    with app.test_client() as c:
        # Change primary, leave secondary at the current effective value.
        _post_colours(c, "#ABCDEF", "#222222")
    prof = cp.load_profile("otters")
    # The changed colour is pinned into the winning slot...
    assert prof.brand_palette_manual.get("primary") == "#ABCDEF"
    # ...the unchanged secondary is NOT pinned (so the AI palette isn't locked)...
    assert "secondary" not in prof.brand_palette_manual
    # ...and it flows through to the rendered brand kit.
    assert prof.get_brand_kit().primary_colour.lower() == "#abcdef"
    # secondary still resolves from the extracted palette.
    assert prof.get_brand_kit().secondary_colour.lower() == "#222222"


def test_unchanged_save_does_not_lock_the_ai_palette(env):
    app, cp = env
    with app.test_client() as c:
        # Save without changing either colour (submit the current effective pair).
        _post_colours(c, "#111111", "#222222")
    prof = cp.load_profile("otters")
    # No manual override was created — the AI palette stays live and editable.
    assert not (prof.brand_palette_manual or {}).get("primary")
    assert prof.get_brand_kit().primary_colour.lower() == "#111111"
