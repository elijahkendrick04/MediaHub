"""P1.3 — the cross-source planner (strategy brain).

Pins the Phase-1 exit criterion: a profile-driven planner produces a ranked,
explainable content plan for ≥2 sport profiles (swimming + football),
grounded in the three signal sources — own / external / direct — with
deterministic scoring, source-grounded reasons, honest gaps, and per-org
isolation.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from mediahub.content_engine.inputs import load_planner_inputs, save_planner_inputs
from mediahub.content_engine.planner import (
    build_content_plan,
    load_latest_plan,
    save_plan,
)
from mediahub.content_engine.signals import (
    gather_all_signals,
    gather_direct_signals,
    gather_external_signals,
    gather_own_signals,
)

TODAY = date(2026, 6, 10)
ORG_A = "org-alpha"
ORG_B = "org-beta"


# ---------------------------------------------------------------------------
# Seeding helpers — minimal real store shapes under a tmp DATA_DIR
# ---------------------------------------------------------------------------


def _seed_run(
    data_dir,
    *,
    run_id: str,
    profile_id: str,
    meet_name: str,
    finished: date,
    n_achievements: int = 0,
    queued: int = 0,
    approved: int = 0,
) -> None:
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "finished_at": f"{finished.isoformat()}T12:00:00+00:00",
                "meet": {"name": meet_name},
                "recognition_report": {"n_achievements": n_achievements},
            }
        ),
        encoding="utf-8",
    )
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    store = WorkflowStore(runs)
    idx = 0
    for status, n in ((CardStatus.QUEUE, queued), (CardStatus.APPROVED, approved)):
        for _ in range(n):
            idx += 1
            store.set_status(run_id, f"card-{idx}", status)


def _seed_pack(data_dir, *, profile_id: str, stub_type: str, created: date) -> None:
    packs = data_dir / "stub_packs"
    packs.mkdir(parents=True, exist_ok=True)
    pack_id = f"pk{abs(hash((profile_id, stub_type, created))) % 10**8:08d}"
    (packs / f"{pack_id}.json").write_text(
        json.dumps(
            {
                "pack_id": pack_id,
                "profile_id": profile_id,
                "created_at": f"{created.isoformat()}T09:00:00+00:00",
                "stub_type": stub_type,
                "title": "seeded",
                "form_data": {},
                "cards": [],
            }
        ),
        encoding="utf-8",
    )


def _seed_discovered_meet(data_dir, *, name: str) -> None:
    d = data_dir / "discovered" / "meets"
    d.mkdir(parents=True, exist_ok=True)
    (d / "seeded_meet.json").write_text(
        json.dumps(
            {
                "payload": {
                    "canonical_name": name,
                    "governing_body": "Swim England",
                    "meet_level": "Level 2",
                }
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Direct-input store
# ---------------------------------------------------------------------------


def test_inputs_round_trip_validates_and_canonicalises(tmp_path):
    saved = save_planner_inputs(
        ORG_A,
        {
            "upcoming_events": [
                {"name": "County Champs", "date": "2026-06-13", "venue": "Wales National Pool"},
                {"name": "bad date", "date": "13/06/2026"},
                {"date": "2026-06-20"},  # no name → dropped
            ],
            "goals": [
                {"post_type": "sponsor_post", "note": "thank Acme monthly"},  # legacy slug
                {"post_type": "", "note": "dropped"},
            ],
            "blackout_dates": ["2026-06-15", "2026-06-15", "nonsense"],
        },
        data_dir=tmp_path,
    )
    assert [e["name"] for e in saved["upcoming_events"]] == ["County Champs"]
    assert saved["goals"] == [{"post_type": "sponsor_activation", "note": "thank Acme monthly"}]
    assert saved["blackout_dates"] == ["2026-06-15"]
    assert load_planner_inputs(ORG_A, data_dir=tmp_path) == saved
    # Unknown org loads empty, never errors.
    assert load_planner_inputs("never-saved", data_dir=tmp_path) == {
        "upcoming_events": [],
        "goals": [],
        "blackout_dates": [],
    }


def test_inputs_org_filename_is_sanitised(tmp_path):
    inputs_dir = tmp_path / "planner_inputs"
    save_planner_inputs("../evil/org", {"blackout_dates": ["2026-07-01"]}, data_dir=tmp_path)
    files = list(inputs_dir.iterdir())
    assert len(files) == 1
    # The org id can never escape the storage directory: separators are
    # stripped and the file resolves inside planner_inputs/.
    assert "/" not in files[0].name and "\\" not in files[0].name
    assert files[0].resolve().parent == inputs_dir.resolve()


# ---------------------------------------------------------------------------
# Signals — three sources, grounded, isolated
# ---------------------------------------------------------------------------


def test_signals_cover_all_three_sources(tmp_path):
    _seed_run(
        tmp_path,
        run_id="runA1",
        profile_id=ORG_A,
        meet_name="Spring Open",
        finished=TODAY - timedelta(days=2),
        n_achievements=7,
        queued=3,
        approved=1,
    )
    _seed_pack(tmp_path, profile_id=ORG_A, stub_type="weekend_preview", created=TODAY - timedelta(days=30))
    _seed_discovered_meet(tmp_path, name="Spring Open")
    save_planner_inputs(
        ORG_A,
        {
            "upcoming_events": [{"name": "County Champs", "date": (TODAY + timedelta(days=3)).isoformat()}],
            "goals": [{"post_type": "behind_the_scenes", "note": ""}],
            "blackout_dates": [(TODAY + timedelta(days=5)).isoformat()],
        },
        data_dir=tmp_path,
    )

    sigs = gather_all_signals(ORG_A, data_dir=tmp_path, now=TODAY)
    sources = {s.source for s in sigs}
    assert sources == {"own", "external", "direct"}
    for s in sigs:
        assert s.summary and s.provenance, s

    run_sig = next(s for s in sigs if s.kind == "run_results")
    assert run_sig.payload["queued"] == 3
    assert run_sig.payload["n_achievements"] == 7
    assert "Spring Open" in run_sig.summary

    # Legacy pack stub_type is canonicalised in the signal.
    pack_sig = next(s for s in sigs if s.kind == "pack_recency")
    assert pack_sig.payload["post_type"] == "event_preview"


def test_signals_are_tenant_isolated(tmp_path):
    _seed_run(
        tmp_path,
        run_id="runB1",
        profile_id=ORG_B,
        meet_name="Beta Gala",
        finished=TODAY - timedelta(days=1),
        n_achievements=4,
        queued=2,
    )
    _seed_pack(tmp_path, profile_id=ORG_B, stub_type="free_text", created=TODAY - timedelta(days=1))
    save_planner_inputs(
        ORG_B,
        {"upcoming_events": [{"name": "Beta Cup", "date": (TODAY + timedelta(days=2)).isoformat()}]},
        data_dir=tmp_path,
    )

    own_a = gather_own_signals(ORG_A, data_dir=tmp_path, now=TODAY)
    direct_a = gather_direct_signals(ORG_A, data_dir=tmp_path, now=TODAY)
    assert own_a == []
    assert all(s.kind != "upcoming_event" for s in direct_a)
    # And org B sees its own.
    assert any(s.kind == "run_results" for s in gather_own_signals(ORG_B, data_dir=tmp_path, now=TODAY))


def test_anniversary_signal_from_year_old_meet(tmp_path):
    _seed_run(
        tmp_path,
        run_id="runOld",
        profile_id=ORG_A,
        meet_name="Last Year's Nationals",
        finished=TODAY - timedelta(days=365),
        n_achievements=9,
    )
    ext = gather_external_signals(ORG_A, data_dir=tmp_path, now=TODAY)
    ann = [s for s in ext if s.kind == "anniversary"]
    assert ann and "Last Year's Nationals" in ann[0].summary
    assert ann[0].payload["years"] == 1


# ---------------------------------------------------------------------------
# The plan — ranked, explainable, ≥2 sport profiles, deterministic
# ---------------------------------------------------------------------------


def _full_org_a(tmp_path):
    _seed_run(
        tmp_path,
        run_id="runA1",
        profile_id=ORG_A,
        meet_name="Spring Open",
        finished=TODAY - timedelta(days=2),
        n_achievements=7,
        queued=3,
        approved=1,
    )
    _seed_discovered_meet(tmp_path, name="Spring Open")
    save_planner_inputs(
        ORG_A,
        {
            "upcoming_events": [{"name": "County Champs", "date": (TODAY + timedelta(days=3)).isoformat()}],
            "goals": [{"post_type": "milestone_celebration", "note": "celebrate club captain's 100th meet"}],
        },
        data_dir=tmp_path,
    )


def test_swimming_plan_is_ranked_grounded_and_explainable(tmp_path):
    _full_org_a(tmp_path)
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)

    assert plan.sport == "swimming" and plan.engine_sport == "swimming"
    assert plan.items and plan.items == sorted(plan.items, key=lambda i: (-i.score, i.post_type))

    # Fresh results with queued cards put the result-led recap on top.
    assert plan.items[0].post_type == "meet_recap"
    top = plan.items[0]
    assert "own" in top.sources_used
    assert any("cards awaiting review" in r for r in top.reasons)
    assert any(ref.startswith("runs_v4/") for ref in top.signal_refs)

    # All three sources ground the plan as a whole (exit criterion).
    used = {src for item in plan.items for src in item.sources_used}
    assert used == {"own", "external", "direct"}

    # Every item is explainable and canonical.
    from mediahub.club_platform.post_types import canonical_slug

    for item in plan.items:
        assert item.reasons, item.post_type
        assert item.post_type == canonical_slug(item.post_type)
        assert item.default_autonomy in {"draft_only", "approval_required"}

    # The operator goal boosted its target type.
    goal_item = next(i for i in plan.items if i.post_type == "milestone_celebration")
    assert any("operator goal" in r.lower() for r in goal_item.reasons)
    assert "direct" in goal_item.sources_used

    # Implemented surfaces carry their badge; planning vocabulary does not.
    assert next(i for i in plan.items if i.post_type == "meet_recap").implemented
    assert not next(i for i in plan.items if i.post_type == "pb_spotlight").implemented


def test_plan_is_deterministic(tmp_path):
    _full_org_a(tmp_path)
    p1 = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    p2 = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    strip = lambda p: [
        {k: v for k, v in i.to_dict().items()} for i in p.items
    ]  # noqa: E731
    assert strip(p1) == strip(p2)


def test_football_plan_builds_with_honest_result_gap(tmp_path):
    """Exit criterion: the same planner serves a second sport profile."""
    _full_org_a(tmp_path)  # org has SWIM runs only
    plan = build_content_plan("football", ORG_A, data_dir=tmp_path, now=TODAY)

    assert plan.sport == "football"
    slugs = {i.post_type for i in plan.items}
    assert {"full_time_score", "matchday_lineup", "event_preview"} <= slugs

    # Swim runs must NOT boost football result types — the gap is stated.
    ft = next(i for i in plan.items if i.post_type == "full_time_score")
    assert any("no football results ingested yet" in r for r in ft.reasons)
    assert "own" not in ft.sources_used

    # The upcoming event still boosts pre-event football types (direct source).
    preview = next(i for i in plan.items if i.post_type == "event_preview")
    assert any("County Champs" in r for r in preview.reasons)
    assert preview.score > ft.score


def test_event_proximity_and_blackout(tmp_path):
    when = (TODAY + timedelta(days=2)).isoformat()
    save_planner_inputs(
        ORG_A,
        {
            "upcoming_events": [{"name": "Gala", "date": when}],
            "blackout_dates": [when],
        },
        data_dir=tmp_path,
    )
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    preview = next(i for i in plan.items if i.post_type == "event_preview")
    assert any("event in 2d" in r.lower() for r in preview.reasons)
    assert any("blackout" in r.lower() for r in preview.reasons)


def test_sponsor_needs_configuration_to_rise(tmp_path):
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    sponsor = next(i for i in plan.items if i.post_type == "sponsor_activation")
    assert any("no sponsor configured" in r.lower() for r in sponsor.reasons)


def test_anniversary_boosts_history_type(tmp_path):
    _seed_run(
        tmp_path,
        run_id="runOld",
        profile_id=ORG_A,
        meet_name="Last Year's Nationals",
        finished=TODAY - timedelta(days=365),
        n_achievements=9,
    )
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    milestone = next(i for i in plan.items if i.post_type == "milestone_celebration")
    assert any("Last Year's Nationals" in r for r in milestone.reasons)
    assert "external" in milestone.sources_used


def test_no_signal_plan_is_honest(tmp_path):
    plan = build_content_plan("swimming", "empty-org", data_dir=tmp_path, now=TODAY)
    assert plan.items  # the profile still yields a baseline plan
    assert any("No processed swimming results" in n for n in plan.notes)
    for source in ("own", "external", "direct"):
        assert any(f"No {source} signals" in n for n in plan.notes)
    recap = next(i for i in plan.items if i.post_type == "meet_recap")
    assert any("no swimming results ingested yet" in r for r in recap.reasons)


# ---------------------------------------------------------------------------
# Persistence + isolation
# ---------------------------------------------------------------------------


def test_plan_persistence_and_isolation(tmp_path):
    _full_org_a(tmp_path)
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    save_plan(plan, data_dir=tmp_path)

    latest = load_latest_plan(ORG_A, data_dir=tmp_path)
    assert latest is not None
    assert latest["plan_id"] == plan.plan_id
    assert latest["profile_id"] == ORG_A
    assert latest["source_counts"]["own"] >= 1
    assert latest["items"][0]["post_type"] == "meet_recap"
    assert latest["items"][0]["reasons"]

    # Another org has no plan — and can never read org A's.
    assert load_latest_plan(ORG_B, data_dir=tmp_path) is None


def test_latest_plan_ownership_check(tmp_path):
    _full_org_a(tmp_path)
    plan = build_content_plan("swimming", ORG_A, data_dir=tmp_path, now=TODAY)
    save_plan(plan, data_dir=tmp_path)
    # Tamper: copy org A's latest under org B's directory — ownership check
    # refuses to serve it.
    src = tmp_path / "content_plans" / ORG_A / "latest.json"
    dst_dir = tmp_path / "content_plans" / ORG_B
    dst_dir.mkdir(parents=True)
    (dst_dir / "latest.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_latest_plan(ORG_B, data_dir=tmp_path) is None


def test_unknown_sport_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_content_plan("quidditch", ORG_A, data_dir=tmp_path, now=TODAY)


# ---------------------------------------------------------------------------
# Web surface — org-scoped plan routes + page
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_org(tmp_path, monkeypatch):
    """Flask test app with a seeded org pinned via session (P2.4 pattern)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def test_plan_routes_require_an_org(app_with_org):
    with app_with_org.test_client() as client:
        assert client.get("/api/plan/latest").status_code == 403
        assert client.post("/api/plan/generate", json={"sport": "swimming"}).status_code == 403
        assert client.get("/api/plan/inputs").status_code == 403
        # The page redirects to sign-in instead of erroring.
        assert client.get("/plan").status_code == 302


def test_plan_generate_persist_and_page_render(app_with_org, tmp_path):
    _seed_run(
        tmp_path,
        run_id="runT1",
        profile_id="org-test",
        meet_name="Test Gala",
        finished=date.today() - timedelta(days=1),
        n_achievements=5,
        queued=2,
    )
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        # No plan yet.
        body = client.get("/api/plan/latest").get_json()
        assert body["ok"] is True and body["plan"] is None

        # Save direct inputs through the API.
        resp = client.post(
            "/api/plan/inputs",
            json={
                "upcoming_events": [
                    {"name": "County Champs", "date": (date.today() + timedelta(days=4)).isoformat()}
                ],
                "blackout_dates": [],
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["inputs"]["upcoming_events"][0]["name"] == "County Champs"

        # Generate + persist.
        resp = client.post("/api/plan/generate", json={"sport": "swimming"})
        assert resp.status_code == 200
        plan = resp.get_json()["plan"]
        assert plan["profile_id"] == "org-test"
        # Fresh queued results put a result-led type on top (which one wins
        # the tiebreak depends on the achievement mix — both are correct).
        assert plan["items"][0]["post_type"] in {"meet_recap", "pb_spotlight"}
        assert plan["items"][0]["reasons"]

        # Latest now serves it.
        body = client.get("/api/plan/latest").get_json()
        assert body["plan"]["plan_id"] == plan["plan_id"]

        # Unknown sport is honest.
        assert client.post("/api/plan/generate", json={"sport": "quidditch"}).status_code == 404

        # The page renders the ranked plan with its reasoning.
        page = client.get("/plan")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "What should we" in html
        assert "Meet Recap" in html
        assert "Test Gala" in html  # signal text surfaces in reasons
        assert "OWN" in html and "DIRECT" in html


def test_plan_latest_is_org_scoped(app_with_org, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-other", display_name="Other Club"))
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        client.post("/api/plan/generate", json={"sport": "swimming"})
    with app_with_org.test_client() as client:
        _with_org(client, "org-other")
        body = client.get("/api/plan/latest").get_json()
        assert body["plan"] is None  # org B never sees org A's plan


# ---------------------------------------------------------------------------
# QA-016 — the /plan landing page must not 500
# ---------------------------------------------------------------------------


def test_plan_index_renders_in_empty_state(app_with_org):
    """The /plan index must render (200), not 500, when the org has no plan yet
    — the state a freshly-signed-in org lands in. Every /plan/<view> sub-view
    already handles this; the index must too."""
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        page = client.get("/plan")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        # The default plan view, with the honest empty state.
        assert "What should we" in html and "post next?" in html
        assert "No plan yet" in html


def test_plan_index_survives_legacy_persisted_plan(app_with_org):
    """QA-016 root cause — DATA_DIR is a durable mounted disk, so the index can
    load a plan an *older* planner wrote whose item carries a None/blank field
    (``score`` / ``default_autonomy`` / ``horizon_days`` / source counts) the
    current engine no longer emits. The index is the only handler that renders
    plan items, so such a plan 500'd just the index while every /plan/<view>
    sub-view (none of which read the plan) stayed up — exactly the reported
    scope. It must now coerce defensively (200), never crash on ``int(None)``
    or ``None.replace(...)``.

    Fails before the fix (TypeError), passes after.
    """
    from mediahub.content_engine.planner import _plans_dir

    plans_dir = _plans_dir("org-test")
    legacy_plan = {
        "plan_id": "legacy-1",
        "profile_id": "org-test",
        "sport": "swimming",
        "sport_display": "Swimming",
        "engine_sport": "swimming",
        "generated_at": "2026-01-01T09:00:00+00:00",
        "horizon_days": None,  # legacy/blank numeric — int(None) used to 500
        "version": 1,
        "notes": [],
        "signals": [],
        "source_counts": {"own": None, "external": None, "direct": None},
        "items": [
            {
                "post_type": "meet_recap",
                "title": "Weekend recap",
                "score": None,  # legacy/blank numeric — int(None) used to 500
                "reasons": ["legacy item"],
                "sources_used": ["own"],
                # no "default_autonomy" key at all → None.replace used to 500
                "implemented": True,
            }
        ],
    }
    (plans_dir / "latest.json").write_text(json.dumps(legacy_plan), encoding="utf-8")

    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        page = client.get("/plan")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        # The legacy plan's item still renders, with coerced numerics.
        assert "Weekend recap" in html
        assert "What should we" in html
