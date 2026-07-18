"""G-10 — Welsh mode covers the whole chrome and the primary review verbs.

The audit found Welsh mode half-translated: only ~7 nav sites went through
``t()`` while "Media library", "My Season", "Research", "Help", the
notifications header, the mobile bottom nav and the account menu stayed
hardcoded English, and the catalogue's ``action.approve/reject/export`` keys
were never referenced anywhere.

Now every top-nav, mobile-bottom-nav and account-menu label plus the
notifications-panel header resolves through the UI catalogue, and the review
page's primary verbs (Approve / Re-queue / Reject / Export / Download) render
in Welsh under ``?lang=cy`` while ``?lang=en`` stays byte-for-byte English.
"""

from __future__ import annotations

import json
import uuid

import pytest


@pytest.fixture
def env(web_module, app, client):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    assert (
        client.post("/api/organisation/active", data={"profile_id": "org-test"}).status_code == 200
    )
    return {"client": client, "wm": web_module, "app": app}


def _seed_run(env, swim_ids):
    wm = env["wm"]
    run_id = "run-g10-" + uuid.uuid4().hex[:8]
    payload = {
        "run_id": run_id,
        "profile_id": "org-test",
        "meet": {"name": "G10 WELSH TEST"},
        "cards": [{"card_id": f"card-{s}", "swim_id": s, "id": f"card-{s}"} for s in swim_ids],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": s,
                        "swimmer_name": f"Swimmer {i}",
                        "event": "100 Free",
                        "headline": f"PB for Swimmer {i}",
                        "type": "pb",
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, s in enumerate(swim_ids)
            ],
            "n_achievements": len(swim_ids),
        },
    }
    (wm.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', 'org-test', ?, ?)",
        (run_id, "G10 WELSH TEST", "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


class TestCatalogueKeys:
    def test_new_chrome_keys_ship_english_and_welsh(self):
        from mediahub.localize import ui_catalogue as UI

        assert UI.t("nav.media_library", "en") == "Media library"
        assert UI.t("nav.media_library", "cy") == "Llyfrgell cyfryngau"
        assert UI.t("nav.my_season", "cy") == "Fy Nhymor"
        assert UI.t("nav.research", "cy") == "Ymchwil"
        assert UI.t("nav.help", "cy") == "Cymorth"
        assert UI.t("nav.activity", "cy") == "Gweithgarwch"
        assert UI.t("nav.notifications", "cy") == "Hysbysiadau"

    def test_review_verb_keys(self):
        from mediahub.localize import ui_catalogue as UI

        assert UI.t("action.requeue", "en") == "Re-queue"
        assert UI.t("action.requeue", "cy") != "Re-queue"
        assert UI.t("action.approved", "cy") == "Cymeradwywyd"


class TestWelshChrome:
    def test_signed_in_chrome_is_welsh(self, env):
        html = env["client"].get("/?lang=cy").get_data(as_text=True)
        # Top nav
        assert "Llyfrgell cyfryngau" in html  # Media library
        assert "Gweithgarwch" in html  # Activity
        assert "Fy Nhymor" in html  # My Season
        # Account menu
        assert "Drafftiau" in html  # Drafts
        assert "Cymorth" in html  # Help
        assert "clwb" in html  # Data'r clwb (apostrophe is _h-escaped)
        # Notifications header (panel title)
        assert "Hysbysiadau" in html
        # Mobile bottom nav short labels
        assert "Hafan" in html  # Home
        assert "Cyfryngau" in html  # Media
        assert "Gosodiadau" in html  # Settings
        # The English labels these replace must be gone from the nav
        assert ">Media library</a>" not in html
        assert ">My Season</a>" not in html
        assert '"mh-notif-h-title">Notifications<' not in html

    def test_signed_out_chrome_is_welsh(self, env):
        app = env["app"]
        html = app.test_client().get("/?lang=cy").get_data(as_text=True)
        assert "Amdanom ni" in html  # About (signed-out marketing nav)
        assert "Prisiau" in html  # Pricing
        assert "Cofrestru" in html  # Sign up
        assert "Mewngofnodi" in html  # Log in
        assert "Gosodiadau" in html  # Settings (far-right for signed-out)
        # Feature links (e.g. Media library / Llyfrgell cyfryngau) are signed-in
        # only now, so they must NOT appear in the signed-out chrome.
        assert "Llyfrgell cyfryngau" not in html

    def test_english_chrome_unchanged(self, env):
        html = env["client"].get("/?lang=en").get_data(as_text=True)
        assert ">Media library</a>" in html
        assert ">My Season</a>" in html
        assert ">Drafts</a>" in html
        assert ">Help</a>" in html
        assert "Hafan" not in html
        assert "Llyfrgell" not in html


class TestWelshReviewVerbs:
    def test_review_strap_and_bulk_bar_verbs_are_welsh(self, env):
        run_id = _seed_run(env, ["s1", "s2"])
        html = env["client"].get(f"/review/{run_id}?lang=cy").get_data(as_text=True)
        # Per-card strap: Approve + Re-queue in Welsh
        assert "Cymeradwyo" in html
        assert "ciw</button>" in html  # "Yn ôl i'r ciw" (apostrophe _h-escaped)
        # Bulk bar: Reject + Export in Welsh (the audit's never-referenced keys)
        assert "Gwrthod" in html
        assert "Allforio" in html
        # No stray English verbs on the buttons the strap owns
        assert ">Approve</button>" not in html
        assert ">Re-queue</button>" not in html

    def test_approved_card_shows_welsh_state_and_download(self, env):
        wm = env["wm"]
        run_id = _seed_run(env, ["s1"])
        from mediahub.workflow.status import CardStatus

        ws = wm._get_wf_store()
        ws.set_status(run_id, "s1", CardStatus.APPROVED)
        html = env["client"].get(f"/review/{run_id}?lang=cy").get_data(as_text=True)
        assert "Cymeradwywyd" in html  # Approved ✓ state label
        assert "Lawrlwytho" in html  # Download link on the approved card

    def test_optimistic_js_repaint_reads_localized_labels(self, env):
        """The JS approve-flip must read the server-rendered labels, not
        hardcode English, so the optimistic paint keeps the page language."""
        run_id = _seed_run(env, ["s1"])
        html = env["client"].get(f"/review/{run_id}?lang=cy").get_data(as_text=True)
        assert "data-mh-label-approve=" in html
        assert "data-mh-label-approved=" in html
        assert "b.dataset.mhLabelApproved" in html

    def test_english_review_verbs_unchanged(self, env):
        run_id = _seed_run(env, ["s1"])
        html = env["client"].get(f"/review/{run_id}?lang=en").get_data(as_text=True)
        assert ">Approve</button>" in html
        assert ">Re-queue</button>" in html
        assert "Export data (JSON)" in html
        assert "Cymeradwyo" not in html
