"""Signed-in home rebuild + the Help page.

When a club is signed in (a ready organisation is pinned), the home page is now
a content-creation *workspace* — the "Ready to file" hero and a quick-action
grid — instead of the marketing landing page. The product-story explainer it
used to carry (how it works / what it does / who it's for / our promise / FAQ)
moved to a dedicated **Help** page, reached from the account-menu dropdown in
the top bar. Runs stay on the org-scoped /activity page (a deliberate
multi-tenant decision guarded by tests/test_activity_scoping.py), reached from
the workspace's "All activity" tile — they are NOT re-surfaced on the home.

These tests pin down:
  * the /help route renders the full explainer,
  * the account menu links to it,
  * the signed-in home is the workspace (quick actions) and no longer the pitch,
    with runs kept on /activity rather than on the home,
  * the signed-OUT landing page still carries the whole explainer (regression).
"""

from __future__ import annotations

import pytest

_TEST_ORG = "test-org"


@pytest.fixture()
def app(web_module):
    application = web_module.create_app()
    application.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=_TEST_ORG,
            display_name="Test Org",
            brand_voice_summary="Testing.",
            brand_capture_status="ok",
        )
    )
    return application


def _get(application, path: str, *, pinned: bool = False) -> str:
    with application.test_client() as c:
        if pinned:
            with c.session_transaction() as s:
                s["active_profile_id"] = _TEST_ORG
        resp = c.get(path)
        assert resp.status_code == 200, f"GET {path} -> {resp.status_code}"
        return resp.get_data(as_text=True)


# =========================================================================== #
# 1) The Help page renders the whole product-story explainer
# =========================================================================== #
class TestHelpPage:
    def test_route_exists(self, app):
        assert "/help" in {str(r.rule) for r in app.url_map.iter_rules()}

    def test_renders_header_and_closing(self, app):
        body = _get(app, "/help", pinned=True)
        assert "Help &amp; how it works" in body
        assert "How MediaHub" in body
        assert "Still stuck" in body

    def test_carries_every_explainer_section(self, app):
        body = _get(app, "/help", pinned=True)
        # how-it-works diagram (SVG text is markup-only)
        assert ">THE ENGINE</text>" in body
        # input -> output inline headline
        assert "From a results sheet" in body
        assert 'id="mh-pipeline-h"' in body
        # what the engine does (bento)
        assert 'id="mh-ch-engine"' in body
        assert "Real sample output" in body
        # who it's for (audience)
        assert 'id="mh-ch-audience"' in body
        assert "Club committees" in body
        # our promise
        assert 'id="mh-ch-promise"' in body
        assert "Human in the loop," in body
        # the FAQ, in full
        assert '<section class="mh-section mh-faq"' in body
        assert body.count('<details class="mh-faq-item">') == 7

    def test_help_is_public(self, app):
        # No org pinned — a signed-out visitor still reaches the same explainer.
        body = _get(app, "/help", pinned=False)
        assert ">THE ENGINE</text>" in body
        assert '<section class="mh-section mh-faq"' in body


# =========================================================================== #
# 2) The account menu links to Help (signed-in only)
# =========================================================================== #
class TestAccountMenuLink:
    def test_help_link_in_signed_in_dropdown(self, app):
        body = _get(app, "/", pinned=True)
        # The account-menu item: href to /help, a menuitem, labelled "Help".
        assert '<a href="/help" role="menuitem"' in body
        assert ">Help</a>" in body

    def test_no_account_menu_when_signed_out(self, app):
        # Signed-out visitors have no account dropdown, hence no Help menuitem.
        body = _get(app, "/", pinned=False)
        assert '<a href="/help" role="menuitem"' not in body


# =========================================================================== #
# 3) The signed-in home is a workspace, not the pitch
# =========================================================================== #
class TestSignedInHome:
    def test_shows_workspace_sections(self, app):
        body = _get(app, "/", pinned=True)
        assert "Test Org" in body, "pinned hero variant did not run"
        assert "Your workspace" in body
        # Quick-action tiles to the working surfaces.
        for label in (
            "Create new content",
            "Season Timeline",
            "Media library",
            "Brand &amp; profile",
            "All activity",
            "Help &amp; how it works",
        ):
            assert label in body, f"missing quick-action tile: {label!r}"

    def test_omits_the_marketing_explainer(self, app):
        body = _get(app, "/", pinned=True)
        # None of the explainer sections leak onto the workspace home.
        assert ">THE ENGINE</text>" not in body  # diagram
        assert "From a results sheet" not in body  # io headline
        assert "Real sample output" not in body  # bento
        assert "Club committees" not in body  # audience
        assert '<section class="mh-section mh-faq"' not in body  # FAQ

    def test_keeps_the_create_focused_final_cta(self, app):
        body = _get(app, "/", pinned=True)
        assert "mh-final-cta-headline" in body
        assert "Next weekend" in body and "in a sitting." in body

    def test_runs_stay_on_activity_not_on_the_home(self, app):
        # Deliberate multi-tenant decision (tests/test_activity_scoping.py):
        # runs live on the org-scoped /activity page, reached from the "All
        # activity" tile — never re-surfaced as a list on the home.
        body = _get(app, "/", pinned=True)
        assert "Recent activity" not in body
        # No per-run review links are surfaced as a list on the home.
        assert 'href="/review/' not in body
        # …but the route to them is one click away.
        assert '<a href="/activity"' in body


# =========================================================================== #
# 4) The signed-OUT landing is now BRIEF; the full explainer moved to /about.
#    (The landing keeps the hero, the demo, the input→output headline and a
#    clear path to the walkthrough; the deep sections live on /about.)
# =========================================================================== #
class TestSignedOutLandingAndAbout:
    def test_landing_is_brief_with_a_path_to_about(self, app):
        body = _get(app, "/", pinned=False)
        # Kept on the brief landing: the crisp "what it is" headline + a path
        # to the full, animated walkthrough on /about.
        assert "From a results sheet" in body  # io headline stays
        assert 'href="/about"' in body
        assert "Take the tour" in body
        # Moved off the landing to /about — must no longer appear here.
        for gone in (
            ">THE ENGINE</text>",  # diagram
            "Real sample output",  # bento
            "Club committees",  # audience
            "Human in the loop,",  # promise
        ):
            assert gone not in body, f"brief landing should no longer carry {gone!r}"
        assert '<section class="mh-section mh-faq"' not in body  # FAQ moved too

    def test_about_page_carries_the_whole_explainer(self, app):
        body = _get(app, "/about", pinned=False)
        for hook in (
            ">THE ENGINE</text>",  # diagram
            "From a results sheet",  # io headline
            "Real sample output",  # bento
            "Club committees",  # audience
            "Human in the loop,",  # promise
        ):
            assert hook in body, f"/about lost {hook!r}"
        assert '<section class="mh-section mh-faq"' in body
        assert body.count('<details class="mh-faq-item">') == 7

    def test_about_page_has_the_animated_walkthrough(self, app):
        body = _get(app, "/about", pinned=False)
        # The step-by-step animated walkthrough is the About page's centrepiece.
        assert 'id="mh-ch-flow"' in body
        assert "mh-about-flow" in body
        assert "mh-abs--upload" in body and "mh-abs--export" in body
