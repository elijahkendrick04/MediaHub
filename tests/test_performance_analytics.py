"""Roadmap 1.14 — the first-party performance-analytics loop.

Pins the metric store (record/clean/delete, engagement scoring, tenant isolation),
the deterministic attribution (per-type index, best time, reproducibility), the
planner feedback (a bounded, source-grounded, deterministic nudge that is absent
without data), the number-guarded AI digest (honest-errors without a provider),
and the web routes.
"""

from __future__ import annotations

import pytest

from mediahub.analytics.attribution import MIN_SAMPLES, attribute
from mediahub.analytics.store import (
    delete_metric,
    engagement_score,
    load_metrics,
    record_metric,
)

ORG_A = "org-alpha"
ORG_B = "org-beta"


def _seed(org, data_dir, **kw):
    base = {"impressions": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0}
    return record_metric(
        org,
        kw["post_type"],
        kw["posted_date"],
        {**base, **kw.get("metrics", {})},
        posted_hour=kw.get("posted_hour"),
        data_dir=data_dir,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_engagement_score_weights_are_fixed():
    assert engagement_score({"likes": 10}) == 10
    assert engagement_score({"likes": 1, "comments": 1, "shares": 1, "saves": 1}) == 1 + 2 + 3 + 2
    assert engagement_score({}) == 0
    assert engagement_score({"impressions": 9999}) == 0  # reach isn't engagement


def test_record_clean_and_delete(tmp_path):
    rec = _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="2026-06-10",
                metrics={"likes": 50}, posted_hour=18)
    assert rec is not None and rec.post_type == "pb_spotlight"

    # Invalid post type / date → None (honest, not a blank row).
    assert _seed(ORG_A, tmp_path, post_type="", posted_date="2026-06-10") is None
    assert _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="not-a-date") is None
    # Out-of-range hour is dropped to None, not stored wrong.
    r2 = _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="2026-06-11",
               posted_hour=99, metrics={"likes": 5})
    assert r2.posted_hour is None
    # Negative metrics clamp to 0 (dropped).
    r3 = _seed(ORG_A, tmp_path, post_type="meet_recap", posted_date="2026-06-12",
               metrics={"likes": -5})
    assert r3.metrics.get("likes", 0) == 0

    # 3 valid records stored (the two invalid ones returned None, never stored).
    assert len(load_metrics(ORG_A, data_dir=tmp_path)) == 3
    assert delete_metric(ORG_A, rec.id, data_dir=tmp_path) is True
    assert delete_metric(ORG_A, rec.id, data_dir=tmp_path) is False
    assert len(load_metrics(ORG_A, data_dir=tmp_path)) == 2


def test_store_is_tenant_isolated(tmp_path):
    _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="2026-06-10", metrics={"likes": 1})
    _seed(ORG_B, tmp_path, post_type="meet_recap", posted_date="2026-06-10", metrics={"likes": 1})
    assert {m.post_type for m in load_metrics(ORG_A, data_dir=tmp_path)} == {"pb_spotlight"}
    assert {m.post_type for m in load_metrics(ORG_B, data_dir=tmp_path)} == {"meet_recap"}


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_attribution_index_and_best_time(tmp_path):
    for i in range(3):
        _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date=f"2026-06-1{i}",
              posted_hour=18, metrics={"likes": 100, "comments": 20})
    for i in range(3):
        _seed(ORG_A, tmp_path, post_type="meet_recap", posted_date=f"2026-06-0{i + 1}",
              posted_hour=9, metrics={"likes": 10})

    a = attribute(load_metrics(ORG_A, data_dir=tmp_path))
    assert a.n_posts == 6
    idx = a.type_index()
    assert idx["pb_spotlight"].index > 1.0 > idx["meet_recap"].index  # spotlights outperform
    # Highest-index type sorts first.
    assert a.by_type[0].post_type == "pb_spotlight"
    assert a.best_hour == 18  # the high-engagement hour wins
    # Deterministic.
    assert attribute(load_metrics(ORG_A, data_dir=tmp_path)).to_dict() == a.to_dict()


def test_attribution_empty_is_honest():
    a = attribute([])
    assert a.n_posts == 0 and a.by_type == [] and a.best_hour is None and a.best_dow is None


# ---------------------------------------------------------------------------
# Planner feedback (deterministic, bounded, source-grounded)
# ---------------------------------------------------------------------------


def test_performance_signals_respect_min_samples(tmp_path):
    from mediahub.content_engine.signals import gather_performance_signals

    # One post only → below MIN_SAMPLES → no signal (one post can't move the plan).
    _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="2026-06-10", metrics={"likes": 99})
    assert gather_performance_signals(ORG_A, data_dir=tmp_path) == []
    assert MIN_SAMPLES == 2

    _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date="2026-06-11", metrics={"likes": 99})
    _seed(ORG_A, tmp_path, post_type="meet_recap", posted_date="2026-06-12", metrics={"likes": 1})
    _seed(ORG_A, tmp_path, post_type="meet_recap", posted_date="2026-06-13", metrics={"likes": 1})
    sigs = gather_performance_signals(ORG_A, data_dir=tmp_path)
    kinds = {s.kind for s in sigs}
    assert kinds == {"performance"}
    assert all(s.source == "own" for s in sigs)


def test_planner_uses_performance_deterministically_and_is_inert_without_data(tmp_path):
    from mediahub.content_engine.planner import build_content_plan

    # No metrics: plan is unaffected by the analytics loop (existing behaviour).
    base = build_content_plan("swimming", ORG_A, data_dir=tmp_path).to_dict()
    assert not any(
        "your average" in r for i in base["items"] for r in i["reasons"]
    )

    # Record a clear over/under-performer pair.
    for i in range(3):
        _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date=f"2026-06-1{i}",
              metrics={"likes": 200, "comments": 30})
    for i in range(3):
        _seed(ORG_A, tmp_path, post_type="meet_recap", posted_date=f"2026-06-0{i + 1}",
              metrics={"likes": 5})

    p1 = build_content_plan("swimming", ORG_A, data_dir=tmp_path).to_dict()
    p2 = build_content_plan("swimming", ORG_A, data_dir=tmp_path).to_dict()
    assert p1["items"] == p2["items"]  # deterministic

    def reasons(plan, slug):
        return next(i["reasons"] for i in plan["items"] if i["post_type"] == slug)

    assert any("outperforms your average" in r for r in reasons(p1, "pb_spotlight"))
    assert any("underperforms your average" in r for r in reasons(p1, "meet_recap"))
    # The nudge is bounded: never more than +8 / -6 from one signal line.
    for slug in ("pb_spotlight", "meet_recap"):
        for r in reasons(p1, slug):
            if "average" in r:
                delta = int(r.split()[0])
                assert -6 <= delta <= 8


# ---------------------------------------------------------------------------
# Digest — honest, number-guarded
# ---------------------------------------------------------------------------


def test_digest_honest_errors_without_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from mediahub.analytics.digest import performance_digest
    from mediahub.media_ai.llm import ClaudeUnavailableError

    for i in range(2):
        _seed(ORG_A, tmp_path, post_type="pb_spotlight", posted_date=f"2026-06-1{i}",
              metrics={"likes": 10})
    a = attribute(load_metrics(ORG_A, data_dir=tmp_path))
    with pytest.raises(ClaudeUnavailableError):
        performance_digest(a)
    # Empty attribution returns empty (no provider needed, nothing to say).
    assert performance_digest(attribute([]))["takeaways"] == []


def test_digest_number_guard_drops_smuggled_numbers():
    from mediahub.analytics.digest import _validate

    allowed = {5.0, 100.0}
    raw = {
        "summary": "Up 100 on likes",  # 100 allowed
        "takeaways": [
            {"text": "You had 5 great posts"},  # 5 allowed → kept
            {"text": "Engagement tripled to 999"},  # 999 not allowed → dropped
        ],
    }
    out = _validate(raw, allowed, "test", 4)
    assert out["summary"] == "Up 100 on likes"
    assert [t["text"] for t in out["takeaways"]] == ["You had 5 great posts"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club",
                             org_type="swimming_club"))
    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def test_analytics_routes_require_org(app_with_org):
    with app_with_org.test_client() as client:
        assert client.get("/plan/analytics").status_code == 302
        assert client.post("/api/plan/analytics/record", json={}).status_code == 403
        assert client.post("/api/plan/analytics/digest", json={}).status_code == 403


def test_analytics_page_record_and_digest(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        assert client.get("/plan/analytics").status_code == 200

        r = client.post(
            "/api/plan/analytics/record",
            json={"post_type": "pb_spotlight", "posted_date": "2026-06-10",
                  "posted_hour": 18, "metrics": {"likes": 100}},
        )
        assert r.status_code == 200 and r.get_json()["ok"] is True
        # Invalid → 400.
        assert client.post(
            "/api/plan/analytics/record", json={"post_type": "", "posted_date": "x"}
        ).status_code == 400

        html = client.get("/plan/analytics").get_data(as_text=True)
        assert "What" in html and "mh-an-table" in html

        # Digest honest-errors without a provider (503), not a fake.
        assert client.post("/api/plan/analytics/digest", json={}).status_code == 503
