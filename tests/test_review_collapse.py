"""Review page — Council UI verdict (2026-05-31): the approve-before-publish
list must stay navigable at real meet scale.

A real run carries 150-250 ranked achievements. Rendering every card's "Why
this card?" reasoning open produced a single ~70,000px-tall page — the core
workflow drowned in scroll. The verdict: collapse each card's reasoning by
default on the LIST, but keep it one click away, give the workflow controls a
sticky home, and never let a bulk-approve rubber-stamp reasoning the reviewer
never opened. These tests pin that behaviour.

The complementary invariant — that a *focused / eager* single-card render keeps
``<details open>`` ("visible intelligence") — is pinned in
tests/test_visible_intelligence.py and must stay green; this file only governs
the lazy review list.
"""
from __future__ import annotations

import importlib
import json
import uuid

import pytest


@pytest.fixture
def review_app(tmp_path, monkeypatch):
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
    save_profile(ClubProfile(profile_id="org-x", display_name="Org X",
                             brand_voice_summary="Bold."))

    def _ach(i):
        return {
            "achievement": {
                "swim_id": f"swim-{i}",
                "swimmer_name": f"Swimmer {i}",
                "event": "100m freestyle",
                "headline": f"Personal best #{i}",
                "type": "personal_best",
                "confidence_label": "high",
            },
            "quality_band": "elite" if i == 0 else "story",
            "priority": 0.9 - i * 0.1,
            "rank": i + 1,
            "factors": [{"name": "pb_margin", "value": 0.3, "reason": "0.3s faster"}],
            "suggested_post_type": "feed",
        }

    run_id = "run-x-" + uuid.uuid4().hex[:8]
    n = 6
    payload = {
        "run_id": run_id, "profile_id": "org-x", "profile_display": "Org X",
        "meet": {"name": "Regional LC Champs"},
        "our_swim_count": n,
        "recognition_report": {
            "ranked_achievements": [_ach(i) for i in range(n)],
            "n_elite": 1, "n_strong": 0, "n_story": n - 1,
            "n_achievements": n, "n_swims_analysed": n,
        },
        "cards": [], "parse_warnings": [], "self_check": {},
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, our_swims, n_cards, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?, 0, ?)",
        (run_id, "org-x", "Regional LC Champs", n, "x.hy3"),
    )
    conn.commit(); conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, run_id


def _review_body(app, run_id):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "org-x"
        r = c.get(f"/review/{run_id}")
        assert r.status_code == 200, r.status_code
        return r.get_data(as_text=True)


class TestReviewListCollapse:
    def test_list_reasoning_is_collapsed_by_default(self, review_app):
        body = _review_body(*review_app)
        # The lazy review rows render the explainer collapsed...
        assert '<details class="why-card"' in body
        # ...not open (open-by-default is the eager/single-card invariant only).
        assert '<details open class="why-card"' not in body

    def test_reasoning_is_one_click_away(self, review_app):
        body = _review_body(*review_app)
        # The collapsed card visibly advertises its hidden reasoning with an
        # interactive (underlined + chevron) "Show reasoning" toggle.
        assert "why-peek" in body
        assert "Show reasoning" in body
        assert "why-chev" in body
        # And the lazy body + load URL are still present for on-expand fetch.
        assert "why-body" in body and "data-why-url" in body

    def test_sticky_controls_and_expand_all(self, review_app):
        body = _review_body(*review_app)
        # "Expand all reasoning" lives in the already-sticky achievement
        # filters bar above the list (a second sticky bar collided with it —
        # caught in the Council audit round).
        assert "filters-bar" in body
        assert 'id="mh-expand-all-why"' in body
        assert "Expand all reasoning" in body

    def test_bulk_approve_is_informed_not_blind(self, review_app):
        body = _review_body(*review_app)
        # The bulk-approve confirm must warn about cards whose reasoning the
        # reviewer never opened — no silent rubber-stamp.
        assert "data-why-seen" in body
        assert "not yet opened" in body
