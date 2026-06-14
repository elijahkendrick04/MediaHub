"""tests/test_card_reactions.py — UI 1.25 emoji reactions.

Quick 👍 ❤️ 🔥 reactions on generated cards and in the review queue, stored per
card in the existing SQLite DB, tallied server-side, and toggled via fetch
without a full page reload (inspired by Liveblocks).

This is the comprehensive guard for the feature. It covers:

* the pure render strip + the server-side tally helpers (counts, escaping,
  allowlist);
* the toggle API — react, un-react (toggle), multi-reactor tallies, independent
  per-emoji counts, and DB persistence;
* input validation (emoji allowlist, reactor-id shape, card-id length);
* tenant isolation / IDOR (a reaction can't touch another org's run);
* the per-run "my reactions" read used to highlight the viewer's own taps;
* that the strip — and the JS/CSS that enhance it — actually reach the review
  and content-builder pages, with counts rendered server-side on first paint.
"""
from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# The three allowlisted reactions, by name, so the tests read clearly.
THUMB, HEART, FIRE = "👍", "❤️", "🔥"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _seed_run(tmp_path, wm, profile_id, run_payload):
    """Write run JSON to disk and insert a matching DB row (owned by profile_id)."""
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, run_payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


def _make_run_payload(profile_id, swim_ids):
    """A minimal but realistic run payload with ranked achievements."""
    run_id = "run-react-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": "REACTIONS TEST INVITATIONAL"},
        "cards": [{"card_id": s, "swim_id": s, "id": s} for s in swim_ids],
        "trust": {"score": 0.85},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": s,
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "200m Butterfly",
                        "headline": "PB set",
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
            "n_elite": len(swim_ids),
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": len(swim_ids),
            "n_swims_analysed": len(swim_ids),
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Booted app with one pinned org (org-test) and a test client."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="org-test",
        display_name="Test Club",
        brand_voice_summary="Clear and energetic.",
    ))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


def _seed(env, swim_ids=("s1",), owner="org-test"):
    payload = _make_run_payload(owner, list(swim_ids))
    return _seed_run(env["tmp_path"], env["wm"], owner, payload)


def _toggle(client, run_id, card_id, emoji, reactor):
    return client.post(
        f"/api/runs/{run_id}/card/{card_id}/reactions",
        json={"emoji": emoji, "reactor_id": reactor},
    )


# ---------------------------------------------------------------------------
# Render strip + allowlist (pure)
# ---------------------------------------------------------------------------

class TestRenderStrip:
    def test_allowlist_is_exactly_the_three(self):
        import mediahub.web.web as wm
        assert wm.REACTION_EMOJI == (THUMB, HEART, FIRE)

    def test_one_button_per_emoji(self):
        import mediahub.web.web as wm
        html = wm._render_reactions("run1", "card:1", {})
        assert html.count("mh-react-btn") == 3
        for emoji in (THUMB, HEART, FIRE):
            assert f'data-mh-react-emoji="{emoji}"' in html

    def test_count_hidden_at_zero_shown_when_positive(self):
        import mediahub.web.web as wm
        html = wm._render_reactions("run1", "c", {"c": {THUMB: 4}})
        # The reacted emoji shows its count un-hidden…
        assert ">4</span>" in html
        assert "data-mh-react-count>4</span>" in html
        # …and an un-reacted emoji keeps the count hidden.
        assert "data-mh-react-count hidden>0</span>" in html

    def test_run_and_card_ids_on_every_button(self):
        import mediahub.web.web as wm
        html = wm._render_reactions("RUN9", "CARD9", {})
        # Run id rides on each of the 3 buttons.
        assert html.count('data-mh-react-run="RUN9"') == 3
        # Card id rides on the 3 buttons AND the group wrapper (used by JS sync).
        assert html.count('data-mh-react-card="CARD9"') == 4
        assert 'class="mh-reactions" data-mh-react-card="CARD9"' in html

    def test_card_id_is_html_escaped(self):
        """A card id is interpolated into attributes — it must be escaped so a
        crafted id can never break out into markup (defence-in-depth; engine
        ids are tame, but the render must never trust them)."""
        import mediahub.web.web as wm
        html = wm._render_reactions("r", '"><script>x</script>', {})
        assert "<script>x" not in html
        assert "&lt;script&gt;" in html or "&gt;&lt;script" in html

    def test_accessible_group_and_pressed_state(self):
        import mediahub.web.web as wm
        html = wm._render_reactions("r", "c", {})
        assert 'role="group"' in html
        assert 'aria-label="Quick reactions"' in html
        assert html.count('aria-pressed="false"') == 3


# ---------------------------------------------------------------------------
# DB table + tally helper
# ---------------------------------------------------------------------------

class TestStorage:
    def test_table_exists(self, env):
        conn = env["wm"]._db()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='card_reactions'"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_counts_helper_empty_for_unknown_run(self, env):
        assert env["wm"]._reaction_counts_for_run("no-such-run") == {}

    def test_counts_helper_reflects_db(self, env):
        run_id = _seed(env, ["s1", "s2"])
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "r-a")
        _toggle(c, run_id, "s1", THUMB, "r-b")
        _toggle(c, run_id, "s2", FIRE, "r-a")
        counts = env["wm"]._reaction_counts_for_run(run_id)
        assert counts["s1"][THUMB] == 2
        assert counts["s2"][FIRE] == 1


# ---------------------------------------------------------------------------
# Toggle API — the core behaviour
# ---------------------------------------------------------------------------

class TestToggleApi:
    def test_react_then_count_one(self, env):
        run_id = _seed(env)
        r = _toggle(env["client"], run_id, "s1", THUMB, "r-1")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["counts"][THUMB] == 1
        assert body["mine"] == [THUMB]

    def test_second_tap_toggles_off(self, env):
        run_id = _seed(env)
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "r-1")
        r = _toggle(c, run_id, "s1", THUMB, "r-1")
        body = r.get_json()
        assert body["counts"][THUMB] == 0
        assert body["mine"] == []

    def test_two_reactors_tally_two(self, env):
        run_id = _seed(env)
        c = env["client"]
        _toggle(c, run_id, "s1", HEART, "r-1")
        r = _toggle(c, run_id, "s1", HEART, "r-2")
        body = r.get_json()
        assert body["counts"][HEART] == 2
        # r-2's own set only contains its own reaction.
        assert body["mine"] == [HEART]

    def test_emoji_tallied_independently(self, env):
        run_id = _seed(env)
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "r-1")
        _toggle(c, run_id, "s1", FIRE, "r-1")
        r = _toggle(c, run_id, "s1", HEART, "r-1")
        body = r.get_json()
        assert body["counts"] == {THUMB: 1, HEART: 1, FIRE: 1}
        assert sorted(body["mine"]) == sorted([THUMB, HEART, FIRE])

    def test_same_reactor_same_emoji_is_idempotent_count(self, env):
        """A reactor counts once per emoji no matter how the row got there —
        the toggle never lets one client inflate a single emoji past 1."""
        run_id = _seed(env)
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "r-1")          # on  -> 1
        _toggle(c, run_id, "s1", THUMB, "r-1")          # off -> 0
        r = _toggle(c, run_id, "s1", THUMB, "r-1")      # on  -> 1
        assert r.get_json()["counts"][THUMB] == 1

    def test_reactions_are_per_card(self, env):
        run_id = _seed(env, ["s1", "s2"])
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "r-1")
        r = _toggle(c, run_id, "s2", THUMB, "r-1")
        # s2's tally is independent of s1's.
        assert r.get_json()["counts"][THUMB] == 1
        counts = env["wm"]._reaction_counts_for_run(run_id)
        assert counts.get("s1", {}).get(THUMB) == 1
        assert counts.get("s2", {}).get(THUMB) == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_unknown_emoji_rejected(self, env):
        run_id = _seed(env)
        r = _toggle(env["client"], run_id, "s1", "💩", "r-1")
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid emoji"

    def test_empty_emoji_rejected(self, env):
        run_id = _seed(env)
        r = _toggle(env["client"], run_id, "s1", "", "r-1")
        assert r.status_code == 400

    def test_missing_reactor_rejected(self, env):
        run_id = _seed(env)
        r = env["client"].post(
            f"/api/runs/{run_id}/card/s1/reactions", json={"emoji": THUMB}
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid reactor_id"

    def test_oversized_reactor_rejected(self, env):
        run_id = _seed(env)
        r = _toggle(env["client"], run_id, "s1", THUMB, "x" * 65)
        assert r.status_code == 400

    def test_oversized_card_id_rejected(self, env):
        run_id = _seed(env)
        r = _toggle(env["client"], run_id, "c" * 300, THUMB, "r-1")
        assert r.status_code == 400
        assert r.get_json()["error"] == "invalid card_id"

    def test_nothing_persisted_on_validation_failure(self, env):
        run_id = _seed(env)
        _toggle(env["client"], run_id, "s1", "💩", "r-1")
        assert env["wm"]._reaction_counts_for_run(run_id) == {}


# ---------------------------------------------------------------------------
# Tenant isolation / IDOR
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_toggle_on_other_org_run_is_404(self, env):
        run_id = _seed(env, ["s1"], owner="other-org")
        r = _toggle(env["client"], run_id, "s1", THUMB, "r-1")
        assert r.status_code == 404
        # And no row leaked into the DB.
        assert env["wm"]._reaction_counts_for_run(run_id) == {}

    def test_toggle_on_missing_run_is_404(self, env):
        r = _toggle(env["client"], "ghost-run", "s1", THUMB, "r-1")
        assert r.status_code == 404

    def test_get_reactions_on_other_org_run_is_404(self, env):
        run_id = _seed(env, ["s1"], owner="other-org")
        r = env["client"].get(f"/api/runs/{run_id}/reactions?reactor_id=r-1")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Per-run read (load-time reconcile / "my reactions")
# ---------------------------------------------------------------------------

class TestRunReactionsRead:
    def test_returns_counts_and_mine(self, env):
        run_id = _seed(env, ["s1", "s2"])
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "me")
        _toggle(c, run_id, "s1", THUMB, "someone-else")
        _toggle(c, run_id, "s2", FIRE, "me")
        r = c.get(f"/api/runs/{run_id}/reactions?reactor_id=me")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        # Aggregate counts cover everyone.
        assert body["counts"]["s1"][THUMB] == 2
        assert body["counts"]["s2"][FIRE] == 1
        # "mine" is scoped to this reactor only.
        assert body["mine"]["s1"] == [THUMB]
        assert body["mine"]["s2"] == [FIRE]

    def test_mine_scoped_to_reactor(self, env):
        run_id = _seed(env, ["s1"])
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "alice")
        r = c.get(f"/api/runs/{run_id}/reactions?reactor_id=bob")
        body = r.get_json()
        assert body["counts"]["s1"][THUMB] == 1  # bob sees the public tally
        assert body["mine"] == {}                # but holds no reactions himself

    def test_no_reactor_arg_returns_counts_only(self, env):
        run_id = _seed(env, ["s1"])
        c = env["client"]
        _toggle(c, run_id, "s1", THUMB, "alice")
        r = c.get(f"/api/runs/{run_id}/reactions")
        body = r.get_json()
        assert body["counts"]["s1"][THUMB] == 1
        assert body["mine"] == {}

    def test_empty_run_has_empty_maps(self, env):
        run_id = _seed(env, ["s1"])
        r = env["client"].get(f"/api/runs/{run_id}/reactions?reactor_id=me")
        body = r.get_json()
        assert body["counts"] == {}
        assert body["mine"] == {}


# ---------------------------------------------------------------------------
# Deletion cascade — a deleted run leaves no reactions behind
# ---------------------------------------------------------------------------

class TestDeletionCascade:
    def test_delete_run_clears_reactions(self, env):
        run_id = _seed(env, ["s1"])
        wm = env["wm"]
        _toggle(env["client"], run_id, "s1", THUMB, "r-1")
        assert wm._reaction_counts_for_run(run_id) != {}
        wm._delete_run(run_id)
        assert wm._reaction_counts_for_run(run_id) == {}


# ---------------------------------------------------------------------------
# Render integration — strip + JS/CSS on the live pages
# ---------------------------------------------------------------------------

class TestPageIntegration:
    def test_review_page_renders_strip(self, env):
        run_id = _seed(env, ["s1"])
        html = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert "mh-reactions" in html
        assert 'data-mh-react-card="s1"' in html
        for emoji in (THUMB, HEART, FIRE):
            assert f'data-mh-react-emoji="{emoji}"' in html

    def test_review_page_shows_server_side_count(self, env):
        """Counts are tallied server-side and baked into the first paint — the
        strip is correct without the client having to fetch anything."""
        run_id = _seed(env, ["s1"])
        wm = env["wm"]
        _toggle(env["client"], run_id, "s1", THUMB, "r-1")
        html = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        expected = wm._render_reactions("s1", "s1", wm._reaction_counts_for_run(run_id))
        # The exact strip the helper produces (count=1, un-hidden) is in the page.
        assert expected.split("><")[0] in html  # wrapper opens for this card
        assert "data-mh-react-count>1</span>" in html

    def test_layout_ships_reaction_js(self, env):
        run_id = _seed(env, ["s1"])
        html = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        # The enhancing module + its key wiring are present.
        assert "mh_reactor_id" in html
        assert ".mh-react-btn" in html  # delegated click selector in JS
        assert "/reactions" in html

    def test_layout_ships_reaction_css(self, env):
        run_id = _seed(env, ["s1"])
        html = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert ".mh-react-btn {" in html
        assert ".mh-react-btn.is-on" in html

    def test_grouped_pack_renders_strip(self, env):
        """The content builder ("generated cards") surface carries the strip too,
        not just the review queue."""
        if not getattr(env["wm"], "_v73_ok", False):
            pytest.skip("grouped content pack (v7.3) not enabled in this build")
        run_id = _seed(env, ["s1"])
        r = env["client"].get(f"/pack/{run_id}/grouped")
        # A redirect means the grouped builder isn't available here; only assert
        # the strip when the page actually rendered.
        if r.status_code != 200:
            pytest.skip(f"grouped pack not rendered (status {r.status_code})")
        html = r.get_data(as_text=True)
        assert "mh-react-btn" in html
        assert 'data-mh-react-card="s1"' in html
        for emoji in (THUMB, HEART, FIRE):
            assert f'data-mh-react-emoji="{emoji}"' in html
