"""tests/test_season_timeline.py — UI2.3 Season / audit Timeline view.

The /season route renders the active organisation's meet-recap (run)
history as a vertical timeline using the UI-uplift kit's `.mh-timeline`
node list and the scroll-driven `.mh-tracing-beam` rail. It is a
read-only "season story" lens on the SAME `runs` rows the Activity log
lists — so the same hard rules apply:

  * multi-tenant isolation — only the pinned org's runs are ever shown;
  * XSS-safe — every user-derived field (meet name, error text) escaped;
  * fail-soft — a missing/locked data.db surfaces a recovery hero, not a 500;
  * the kit markup contract is honoured so the beam + timeline actually wire.

Modelled on tests/test_activity_scoping.py (the proven org-gated fixture).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _insert_run(
    conn,
    run_id,
    profile_id,
    meet,
    *,
    created_at="2026-06-10T09:00:00Z",
    status="done",
    our_swims=10,
    n_achievements=3,
    error=None,
):
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
        (
            run_id,
            created_at,
            created_at,
            status,
            profile_id,
            meet,
            f"{meet}.pdf",
            our_swims,
            n_achievements,
            error,
        ),
    )


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced, two seeded clubs, and a
    set of club-a runs spanning two months (with one failed run)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(
        profile_id="club-a", display_name="Dolphins SC",
        brand_voice_summary="A friendly club.",
    ))
    save_profile(ClubProfile(
        profile_id="club-b", display_name="Sharks SC",
        brand_voice_summary="A serious club.",
    ))

    conn = wm._db()
    # club-a: two June meets + one May meet (one of them failed).
    _insert_run(conn, "a-jun-1", "club-a", "June Open Meet",
                created_at="2026-06-10T09:00:00Z", our_swims=24, n_achievements=7)
    _insert_run(conn, "a-jun-2", "club-a", "June Sprint Gala",
                created_at="2026-06-02T09:00:00Z", our_swims=40, n_achievements=15)
    _insert_run(conn, "a-may-1", "club-a", "May Distance Meet",
                created_at="2026-05-18T09:00:00Z", status="error",
                our_swims=0, n_achievements=0, error="Parser blew up\nfull stack trace")
    # club-b: a separate meet that must never leak into club-a's view.
    _insert_run(conn, "b-1", "club-b", "Sharks County Champs",
                created_at="2026-06-09T09:00:00Z", our_swims=12, n_achievements=4)
    conn.commit()
    conn.close()

    with app.test_client() as c:
        yield c, app, wm


def _pin(client, profile_id):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


# ---------------------------------------------------------------------------
# 1. Multi-tenant isolation — the core data-leak guard.
# ---------------------------------------------------------------------------

class TestScoping:
    def test_shows_only_active_org_runs(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "June Open Meet" in body
        assert "June Sprint Gala" in body
        assert "May Distance Meet" in body
        # Critical: club-b's meet must NOT appear.
        assert "Sharks County Champs" not in body

    def test_other_org_sees_its_own_runs_only(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-b")
        body = c.get("/season").get_data(as_text=True)
        assert "Sharks County Champs" in body
        assert "June Open Meet" not in body
        assert "May Distance Meet" not in body


# ---------------------------------------------------------------------------
# 2. The UI2.3 kit contract — timeline nodes + scroll-driven tracing beam.
# ---------------------------------------------------------------------------

class TestKitMarkup:
    def test_renders_tracing_beam_and_timeline(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        # The two kit components UI2.3 is built on.
        assert "mh-tracing-beam" in body
        assert "mh-tracing-beam__rail" in body
        assert "mh-timeline" in body
        # One node per club-a run (3 runs -> 3 items).
        assert body.count('class="mh-timeline__item"') == 3

    def test_beam_classes_are_defined_globally(self, gated_client):
        """The kit CSS that drives the beam ships on the page (it is part of
        the globally-injected motion layer), so the effect actually wires."""
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert ".mh-tracing-beam__rail" in body  # the rail rule
        assert "--mh-progress" in body            # the scroll-driven fill var

    def test_page_title_and_eyebrow(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "Season timeline" in body


# ---------------------------------------------------------------------------
# 3. Month grouping + per-item content.
# ---------------------------------------------------------------------------

class TestGroupingAndContent:
    def test_groups_by_month(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert 'mh-tl-month">June 2026' in body
        assert 'mh-tl-month">May 2026' in body
        # Newest-first: the June header precedes the May header.
        assert body.index('mh-tl-month">June 2026') < body.index('mh-tl-month">May 2026')

    def test_each_item_links_to_its_review(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        # Review deep-links are present for the runs.
        assert "/review/a-jun-1" in body or "a-jun-1" in body
        # And a cross-link to the activity log lens.
        assert "/activity" in body

    def test_stats_line_shows_swims_and_moments(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "24 swims matched" in body
        assert "7 moments detected" in body
        # The 40-swim gala.
        assert "40 swims matched" in body
        assert "15 moments detected" in body


# ---------------------------------------------------------------------------
# 4. Season totals (count-up stat strip).
# ---------------------------------------------------------------------------

class TestTotals:
    def test_totals_count_up_values(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        # 3 meets, 24+40+0 = 64 swims, 7+15+0 = 22 moments.
        assert 'data-mh-count="3"' in body
        assert 'data-mh-count="64"' in body
        assert 'data-mh-count="22"' in body

    def test_meet_count_in_hero(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "3 meets" in body


# ---------------------------------------------------------------------------
# 5. Status badges + failed-run explainability.
# ---------------------------------------------------------------------------

class TestStatusAndErrors:
    def test_failed_run_shows_reason(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "Why did this run fail?" in body
        assert "Parser blew up" in body

    def test_status_badges_present(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert "tag good" in body  # done runs
        assert "tag bad" in body   # the failed run


# ---------------------------------------------------------------------------
# 6. Security — XSS in user-derived fields.
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_meet_name_is_escaped(self, gated_client):
        c, _, wm = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(
            profile_id="club-x", display_name="XSS SC",
            brand_voice_summary="x",
        ))
        conn = wm._db()
        _insert_run(conn, "x-1", "club-x", "<script>alert(1)</script>")
        conn.commit()
        conn.close()
        _pin(c, "club-x")
        body = c.get("/season").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_error_text_is_escaped(self, gated_client):
        c, _, wm = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(
            profile_id="club-e", display_name="Err SC",
            brand_voice_summary="x",
        ))
        conn = wm._db()
        _insert_run(conn, "e-1", "club-e", "Bad Meet", status="error",
                    error="<img src=x onerror=alert(1)>")
        conn.commit()
        conn.close()
        _pin(c, "club-e")
        body = c.get("/season").get_data(as_text=True)
        assert "<img src=x onerror=alert(1)>" not in body
        assert "&lt;img" in body


# ---------------------------------------------------------------------------
# 7. Empty state + auth gate + fail-soft + robustness.
# ---------------------------------------------------------------------------

class TestEmptyAndGuards:
    def test_empty_state_for_new_club(self, gated_client):
        c, _, wm = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(
            profile_id="club-c", display_name="New SC",
            brand_voice_summary="x",
        ))
        _pin(c, "club-c")
        resp = c.get("/season")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Your season starts here" in body
        # No other club's data, and no timeline nodes.
        assert "June Open Meet" not in body
        assert "Sharks County Champs" not in body
        assert 'class="mh-timeline__item"' not in body

    def test_requires_org_pin(self, gated_client):
        """With the gate enforced and no org pinned, /season redirects out
        rather than rendering anyone's data."""
        c, _, _ = gated_client
        resp = c.get("/season")
        assert resp.status_code in (301, 302)

    def test_db_failure_surfaces_recovery_hero(self, gated_client, monkeypatch):
        c, _, wm = gated_client
        _pin(c, "club-a")

        def _boom():
            raise RuntimeError("data.db unreachable")

        monkeypatch.setattr(wm, "_db", _boom)
        resp = c.get("/season")
        assert resp.status_code == 200  # fail-soft, never a 500
        body = resp.get_data(as_text=True)
        assert "Couldn&rsquo;t load your" in body or "Couldn't load your" in body
        # No node leaked through despite the failure.
        assert 'class="mh-timeline__item"' not in body

    def test_undated_run_does_not_crash(self, gated_client):
        c, _, wm = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(
            profile_id="club-u", display_name="Undated SC",
            brand_voice_summary="x",
        ))
        conn = wm._db()
        # NULL created_at and a garbage value — both must group as "Undated".
        _insert_run(conn, "u-null", "club-u", "No date meet", created_at=None)
        _insert_run(conn, "u-bad", "club-u", "Bad date meet", created_at="not-a-date")
        conn.commit()
        conn.close()
        _pin(c, "club-u")
        resp = c.get("/season")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Undated" in body
        assert "No date meet" in body
        assert "Bad date meet" in body


# ---------------------------------------------------------------------------
# 8. Navigation — Season is a first-class signed-in nav item.
# ---------------------------------------------------------------------------

class TestNavigation:
    def test_season_link_in_nav(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert ">Season<" in body

    def test_season_nav_marked_active_on_page(self, gated_client):
        c, _, _ = gated_client
        _pin(c, "club-a")
        body = c.get("/season").get_data(as_text=True)
        assert 'class="active">Season<' in body
