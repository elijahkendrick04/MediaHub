"""C-20 — the Create page rendered three competing "start here" prompts at
once: the Plan hero ("Plan · Start here"), the START HERE ribbon on the first
implemented tile (Meet Recap), and the sample-pack card.

Exactly one remains: the Meet Recap ribbon (the audience's actual first step,
painted by CSS from the single .mh-template-primary class). The Plan hero is
relabelled as the strategic aid ("Not sure what to post? Plan it.") and the
sample-pack card keeps its non-"start" copy.
"""

from __future__ import annotations

import pytest

from mediahub.web.club_profile import ClubProfile, save_profile

ORG = "org-c20"


@pytest.fixture
def env(app, web_module):
    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": c, "wm": web_module}


def test_create_page_has_exactly_one_start_here(env):
    import re

    html = env["client"].get("/make").get_data(as_text=True)
    # The only "start here" is the CSS ribbon carried by the single tile
    # whose class attribute includes mh-template-primary (page CSS/JS also
    # mentions the class name, so count class attributes, not substrings) —
    # no competing text prompts.
    ribbon_tiles = re.findall(r'class="[^"]*\bmh-template-primary\b[^"]*"', html)
    assert len(ribbon_tiles) == 1
    assert "Start here" not in html
    # The ribbon text exists exactly once — as the inlined CSS content rule
    # that paints the primary tile — never as page copy.
    assert html.count("START HERE") == 1
    assert "content: 'START HERE'" in html


def test_plan_hero_is_relabelled_not_a_start_prompt(env):
    html = env["client"].get("/make").get_data(as_text=True)
    assert '<span class="mh-plan-tile-eyebrow">Plan</span>' in html
    assert "Not sure what to post?" in html
    assert "Plan it." in html


def test_sample_pack_card_copy_does_not_say_start(env):
    html = env["client"].get("/make").get_data(as_text=True)
    if "mh-sample-cta" not in html:
        pytest.skip("sample meet PDF not present on this checkout")
    # The first-run sample card is an offer to see the engine run, not a
    # third "start here".
    frag = html.split("mh-sample-cta", 1)[1].split("</div>", 3)[0]
    assert "start" not in frag.lower()
    assert "Generate a sample pack" in html
