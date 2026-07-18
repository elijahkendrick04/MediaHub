"""B-3 — /pack, /pack/grouped and /review were three overlapping views.

Owner decision — single-purpose pages:
  * /review  = triage (approve / re-queue) only.
  * /pack    = create + export.
  * /pack/grouped = a read-only "explore all recommendations" view: its
    duplicated Parent-newsletter card and its per-card Approve / Re-queue
    straps (_render_wf_actions) are gone; each card deep-links to its spot
    in the content builder instead ("Open in content builder →").

Deliberately KEPT on the grouped page (pinned here so a future tidy-up
doesn't over-remove): the D-12 motion job button (presentation of an
existing render), the G-8 link to the builder's shared reel composer, and
the reaction strips.
"""

from __future__ import annotations

import json
import pathlib
import uuid

import pytest


@pytest.fixture
def env(tmp_path, web_module, client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    wm = web_module

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-b3-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Spring Open"},
                "cards": [],
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "rank": 1,
                            "quality_band": "elite",
                            "priority": 0.9,
                            "safe_to_post": {"level": "safe", "reason": "ok"},
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Maya Patel",
                                "event": "100m Freestyle",
                                "headline": "New PB",
                                "type": "pb",
                                "raw_facts": {"time": "59.99"},
                            },
                        }
                    ],
                    "n_achievements": 1,
                },
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/organisation/active", data={"profile_id": "org-alpha"})
    assert r.status_code == 200
    yield {"client": client, "run_id": run_id, "wm": wm}


def _grouped(env) -> str:
    r = env["client"].get(f"/pack/{env['run_id']}/grouped")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    if "All recommendations" not in page:
        pytest.skip("v7.3 grouped pack unavailable in this environment")
    return page


def _approve(env, card_id: str = "swim-1") -> None:
    from mediahub.workflow.status import CardStatus

    ws = env["wm"]._get_wf_store()
    ws.set_status(env["run_id"], card_id, CardStatus.APPROVED)


# --------------------------------------------------------------------------- #
# 1. The duplicated newsletter card is gone from /pack/grouped — and the
#    surfacing still exists where exporting lives, the content builder.
# --------------------------------------------------------------------------- #
class TestNewsletterNotDuplicated:
    def test_grouped_has_no_newsletter_card(self, env):
        page = _grouped(env)
        assert "Parent newsletter" not in page
        assert f"/api/runs/{env['run_id']}/newsletter" not in page

    def test_builder_still_surfaces_the_newsletter(self, env):
        _approve(env)
        r = env["client"].get(f"/pack/{env['run_id']}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Parent newsletter" in body
        assert f"/api/runs/{env['run_id']}/newsletter" in body


# --------------------------------------------------------------------------- #
# 2. No approval primitives on the explore view — triage lives on /review.
# --------------------------------------------------------------------------- #
class TestGroupedIsReadOnly:
    def test_no_approve_or_requeue_buttons(self, env):
        page = _grouped(env)
        # The exact button markup _render_wf_actions emits (the bare
        # substrings appear inside the global _layout JS on every page).
        assert 'data-mh-wf="approved" data-mh-run-id' not in page
        assert 'data-mh-wf="queue" data-mh-run-id' not in page

    def test_no_status_strap(self, env):
        page = _grouped(env)
        assert 'data-mh-wf-target="swim-1"' not in page

    def test_review_keeps_its_approve_strap(self, env):
        """The strap was removed from the grouped PAGE, not from the shared
        helper — /review must still render it."""
        r = env["client"].get(f"/review/{env['run_id']}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'data-mh-wf="approved" data-mh-run-id' in body
        assert 'data-mh-wf-target="swim-1"' in body


# --------------------------------------------------------------------------- #
# 3. Each card deep-links to its spot in the content builder.
# --------------------------------------------------------------------------- #
class TestBuilderDeepLink:
    def test_card_links_to_its_builder_anchor(self, env):
        page = _grouped(env)
        assert f"/pack/{env['run_id']}#pc-swim-1" in page
        assert "Open in content builder" in page

    def test_builder_anchor_exists_once_approved(self, env):
        """The link's target: the builder renders the card under id
        pc-<card_id> once it is approved."""
        _approve(env)
        r = env["client"].get(f"/pack/{env['run_id']}")
        assert r.status_code == 200
        assert 'id="pc-swim-1"' in r.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# 4. The explore view keeps its presentation features (no over-removal).
# --------------------------------------------------------------------------- #
class TestGroupedKeepsPresentation:
    def test_motion_job_button_kept(self, env):
        page = _grouped(env)
        assert f"/api/runs/{env['run_id']}/card/swim-1/motion" in page
        assert "Motion video" in page

    def test_reel_composer_link_kept(self, env):
        page = _grouped(env)
        assert f"/pack/{env['run_id']}#mh-reel-composer" in page
        assert "Open the reel composer" in page

    def test_reaction_strip_kept(self, env):
        page = _grouped(env)
        assert 'data-mh-react-card="swim-1"' in page

    def test_read_only_framing_names_the_other_pages(self, env):
        page = _grouped(env)
        assert "read-only view" in page
        assert f"/review/{env['run_id']}" in page
