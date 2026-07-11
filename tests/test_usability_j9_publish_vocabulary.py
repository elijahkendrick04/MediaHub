"""J-9 — one publish vocabulary across every token-URL surface, plus one
"Share publicly" chooser.

The two surfaces where content goes live behind a token URL (the public wall
and hosted newsletters) used three different verb pairs — "Switch on / Switch
off & revoke the link", "Publish / Take offline" — for the same action. Owner
decision: the vocabulary is "Publish" / "Unpublish" everywhere.

Pinned here:
  * wall buttons say "Publish wall" / "Unpublish & revoke link"; the old
    switch-on/off button copy is gone (E-12's consequence confirm copy is
    deliberately kept word-for-word — it is asserted unchanged, not removed);
  * newsletter buttons say "Unpublish" (not "Take offline"), and the progress
    message says "Unpublishing…";
  * the Content builder carries ONE "Share publicly" chooser card — its own
    card outside the export row — linking the public wall and the Newsletters
    composer with one-line explanations, publishing nothing by itself;
  * the run-page "Parent newsletter" block carries a clarifying line linking
    the recurring-email composer (both the Content builder and the grouped
    page carry it).
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Source-level: unified verbs, old verbs gone from customer copy
# --------------------------------------------------------------------------- #
class TestUnifiedVocabularySource:
    def test_wall_buttons_use_publish_vocabulary(self):
        assert ">Publish wall</button>" in _SRC
        assert "Unpublish &amp; revoke link</button>" in _SRC

    def test_old_wall_button_copy_is_gone(self):
        assert "Switch on the public wall" not in _SRC
        assert "Switch off &amp; revoke the link" not in _SRC
        assert "switch on and off" not in _SRC
        assert "Your public wall is off." not in _SRC

    def test_wall_off_lede_speaks_publish(self):
        assert "Your public wall is not published." in _SRC
        assert "Publishing it creates an unguessable public link" in _SRC
        assert "Unpublishing later revokes" in _SRC

    def test_newsletter_buttons_use_publish_vocabulary(self):
        assert '"nlPublish(false)">Unpublish</button>' in _SRC
        assert "'Unpublishing…'" in _SRC

    def test_old_newsletter_verbs_are_gone(self):
        assert ">Take offline<" not in _SRC
        assert "Taking offline" not in _SRC

    def test_e12_consequence_confirm_copy_kept_word_for_word(self):
        # Owner decision: the E-12 confirm copy stays exactly as shipped.
        assert "Switch off the public wall?" in _SRC
        assert "'Switch off & revoke'" in _SRC
        assert "Your public link, website embed, feeds and any QR codes will stop working." in _SRC
        assert "Switching back on creates a DIFFERENT link." in _SRC


# --------------------------------------------------------------------------- #
# 2. Source-level: the Share-publicly chooser + the composer hint
# --------------------------------------------------------------------------- #
class TestChooserSource:
    def test_chooser_is_its_own_card_with_both_options(self):
        i = _SRC.index('id="mh-share-publicly"')
        frag = _SRC[i : i + 1200]
        assert "Share publicly" in frag
        assert 'url_for("public_wall_settings")' in frag
        assert "a live page of your approved cards" in frag
        # The newsletter option (flag-gated) sits in the adjacent row builder.
        j = max(0, i - 1600)
        block = _SRC[j : i + 1200]
        assert 'url_for("newsletters_home")' in block
        assert "a digest you publish or email" in block
        # Nothing auto-publishes from the chooser.
        assert "Nothing goes public until" in block

    def test_chooser_sits_outside_the_export_row(self):
        # Rendered after the export row's closing tag, as a sibling card —
        # not inside the export button flex row.
        i = _SRC.index("{_share_publicly_html}")
        before = _SRC[:i]
        assert before.rstrip().endswith("</div>"), (
            "the chooser placeholder must follow a closed block, not sit " "inside the export row"
        )

    def test_run_page_newsletter_block_links_the_composer(self):
        # Both pack surfaces (Content builder + grouped) carry the hint.
        assert _SRC.count("Building a recurring email? Use ") == 2
        first = _SRC.index("Building a recurring email? Use ")
        frag = _SRC[first : first + 220]
        assert 'url_for("newsletters_home")' in frag


# --------------------------------------------------------------------------- #
# 3. Behavioural
# --------------------------------------------------------------------------- #
ORG = "org-j9"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="J9 Swimming Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["active_profile_id"] = ORG
        sess["login_seen_at"] = 2**62
    return {"client": client, "wm": wm, "tmp": tmp_path}


def _seed_approved_run(world, run_id="j9run0001"):
    run = {
        "run_id": run_id,
        "profile_id": ORG,
        "meet": {"name": "J9 Spring Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Nia Morgan",
                        "event": "100m Freestyle",
                        "time": "59.90",
                        "type": "pb_confirmed",
                        "headline": "Nia Morgan breaks a minute",
                        "pb": True,
                    },
                }
            ]
        },
    }
    (world["tmp"] / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run))
    from mediahub.workflow.status import CardStatus

    world["wm"]._get_wf_store().set_status(run_id, "s1", CardStatus.APPROVED)
    return run_id


class TestWallPageVerbs:
    def test_unpublished_wall_offers_publish_wall(self, world):
        html = world["client"].get("/public-wall").get_data(as_text=True)
        assert "Publish wall" in html
        assert "Your public wall is not published." in html
        assert "Switch on" not in html

    def test_published_wall_offers_unpublish_and_keeps_e12_confirm(self, world):
        c = world["client"]
        c.post("/public-wall/update", data={"action": "enable"})
        html = c.get("/public-wall").get_data(as_text=True)
        assert "Unpublish &amp; revoke link" in html
        assert "Switch off &amp; revoke the link" not in html
        # E-12's consequence confirm still ships, word-for-word.
        assert "mhWallOffConfirm" in html
        assert "Switching back on creates a DIFFERENT link." in html


class TestNewsletterVerbs:
    def _make_newsletter(self, world):
        if not world["wm"]._email_design_ok:
            pytest.skip("email_design not available")
        _seed_approved_run(world)
        r = world["client"].post(
            "/api/newsletters/generate",
            json={"format": "monthly_roundup", "range": "this_season", "with_ai": False},
        )
        j = r.get_json()
        assert j and j.get("ok"), j
        return j["newsletter_id"], j["url"]

    def test_unpublished_newsletter_offers_publish(self, world):
        nid, url = self._make_newsletter(world)
        html = world["client"].get(url).get_data(as_text=True)
        assert ">Publish</button>" in html
        assert "Take offline" not in html

    def test_published_newsletter_offers_unpublish_not_take_offline(self, world):
        nid, url = self._make_newsletter(world)
        pub = world["client"].post(
            f"/api/newsletters/{nid}/publish", headers={"Content-Type": "application/json"}
        )
        assert pub.get_json()["ok"] is True
        html = world["client"].get(url).get_data(as_text=True)
        assert ">Unpublish</button>" in html
        assert "Re-publish latest" in html
        assert "Take offline" not in html


class TestContentBuilderChooser:
    def test_chooser_renders_with_both_options_and_links(self, world):
        run_id = _seed_approved_run(world)
        html = world["client"].get(f"/pack/{run_id}").get_data(as_text=True)
        assert 'id="mh-share-publicly"' in html
        assert "Share publicly" in html
        assert 'href="/public-wall"' in html
        assert "a live page of your approved cards" in html
        if world["wm"]._email_design_ok:
            assert 'href="/newsletters"' in html
            assert "a digest you publish or email" in html

    def test_newsletter_block_carries_the_composer_hint(self, world):
        if not world["wm"]._email_design_ok:
            pytest.skip("email_design not available")
        run_id = _seed_approved_run(world)
        html = world["client"].get(f"/pack/{run_id}").get_data(as_text=True)
        assert "Building a recurring email? Use " in html
        assert 'href="/newsletters"' in html

    def test_grouped_page_carries_the_composer_hint_too(self, world):
        if not world["wm"]._email_design_ok:
            pytest.skip("email_design not available")
        run_id = _seed_approved_run(world)
        resp = world["client"].get(f"/pack/{run_id}/grouped")
        # Redirects to the classic pack when v7.3 isn't loaded in the sandbox.
        if resp.status_code == 200:
            assert "Building a recurring email? Use " in resp.get_data(as_text=True)
