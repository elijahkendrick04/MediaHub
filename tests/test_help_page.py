"""Signed-in home rebuild + the Help page.

When a club is signed in (a ready organisation is pinned), the home page is now
a content-creation *workspace* — the "Ready to file" hero, a quick-action grid
and the org's own recent runs — instead of the marketing landing page. The
product-story explainer it used to carry (how it works / what it does / who it's
for / our promise / FAQ) moved to a dedicated **Help** page, reached from the
account-menu dropdown in the top bar.

These tests pin down:
  * the /help route renders the full explainer,
  * the account menu links to it,
  * the signed-in home is the workspace (quick actions + recent activity) and no
    longer the pitch, with a graceful empty state and a real recent-runs list,
  * the signed-OUT landing page still carries the whole explainer (regression).
"""

from __future__ import annotations

import importlib

import pytest

_TEST_ORG = "test-org"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs", "uploads", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    application = wm.create_app()
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
    # Hand the reloaded module back so a test can seed runs through the same
    # _db() the app uses.
    application._wm = wm  # type: ignore[attr-defined]
    return application


def _get(application, path: str, *, pinned: bool = False) -> str:
    with application.test_client() as c:
        if pinned:
            with c.session_transaction() as s:
                s["active_profile_id"] = _TEST_ORG
        resp = c.get(path)
        assert resp.status_code == 200, f"GET {path} -> {resp.status_code}"
        return resp.get_data(as_text=True)


def _seed_run(application, **cols) -> None:
    """Insert one run row for the test org straight into the runs table."""
    wm = application._wm  # type: ignore[attr-defined]
    row = {
        "id": "run-1",
        "created_at": "2026-06-20 09:00:00",
        "status": "done",
        "profile_id": _TEST_ORG,
        "meet_name": "County Champs 2026",
        "our_swims": 18,
        "n_achievements": 5,
        "file_name": "county.pdf",
    }
    row.update(cols)
    conn = wm._db()
    try:
        conn.execute(
            "INSERT INTO runs (id, created_at, status, profile_id, meet_name, "
            "our_swims, n_achievements, file_name) VALUES (?,?,?,?,?,?,?,?)",
            (
                row["id"],
                row["created_at"],
                row["status"],
                row["profile_id"],
                row["meet_name"],
                row["our_swims"],
                row["n_achievements"],
                row["file_name"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


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
        assert "Recent activity" in body
        # Quick-action tiles to the working surfaces.
        for label in ("Create new content", "My Season", "Media library", "Brand &amp; profile"):
            assert label in body, f"missing quick-action tile: {label!r}"

    def test_omits_the_marketing_explainer(self, app):
        body = _get(app, "/", pinned=True)
        # None of the explainer sections leak onto the workspace home.
        assert ">THE ENGINE</text>" not in body          # diagram
        assert "From a results sheet" not in body          # io headline
        assert "Real sample output" not in body            # bento
        assert "Club committees" not in body               # audience
        assert '<section class="mh-section mh-faq"' not in body  # FAQ

    def test_keeps_the_create_focused_final_cta(self, app):
        body = _get(app, "/", pinned=True)
        assert "mh-final-cta-headline" in body
        assert "Next weekend" in body and "in a sitting." in body

    def test_empty_recent_state_nudges_to_create(self, app):
        body = _get(app, "/", pinned=True)
        assert "No runs yet for this organisation" in body
        assert "Create your first piece" in body

    def test_recent_runs_listed_when_present(self, app):
        _seed_run(app)
        body = _get(app, "/", pinned=True)
        assert "County Champs 2026" in body
        assert "Open review" in body
        # The factual sub-line is drawn from the run row.
        assert "5 moments detected" in body
        assert "18 matched" in body
        # And it links into that run's review.
        assert 'href="/review/run-1"' in body
        # The empty-state nudge is gone now there is real activity.
        assert "No runs yet for this organisation" not in body


# =========================================================================== #
# 4) The signed-OUT landing page still carries the whole explainer
# =========================================================================== #
class TestSignedOutLandingUnchanged:
    def test_landing_still_has_explainer(self, app):
        body = _get(app, "/", pinned=False)
        for hook in (
            ">THE ENGINE</text>",      # diagram
            "From a results sheet",     # io headline
            "Real sample output",       # bento
            "Club committees",          # audience
            "Human in the loop,",       # promise
        ):
            assert hook in body, f"signed-out landing lost {hook!r}"
        assert '<section class="mh-section mh-faq"' in body
        assert body.count('<details class="mh-faq-item">') == 7
