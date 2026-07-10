"""Roadmap 1.14 — the Plan calendar (drag-reschedule + key dates).

Covers the calendar read model (six date sources fused, tenant-isolated,
deterministic, honest blanks), the curated key-date packs (exact deterministic
resolution, no fabricated dates), the draft planned-date schedule mutation, and
the web routes (calendar JSON, the month page, and the schedule endpoint with
its soft blackout gate + tenant isolation).
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from mediahub.content_engine.calendar import build_calendar, grid_bounds, month_matrix
from mediahub.content_engine.key_dates import (
    key_dates_in_range,
    load_key_date_pack,
)
from mediahub.content_engine.key_dates import _nth_weekday  # internal — math pin

ORG_A = "org-alpha"
ORG_B = "org-beta"


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_pack(
    data_dir,
    *,
    pack_id: str,
    profile_id: str,
    title: str,
    n_cards: int = 1,
    planned_date: str | None = None,
    stub_type: str = "free_text",
) -> None:
    packs = data_dir / "stub_packs"
    packs.mkdir(parents=True, exist_ok=True)
    rec = {
        "pack_id": pack_id,
        "profile_id": profile_id,
        "created_at": "2026-06-01T10:00:00+00:00",
        "stub_type": stub_type,
        "title": title,
        "cards": [{"caption": f"c{i}"} for i in range(n_cards)],
    }
    if planned_date:
        rec["planned_date"] = planned_date
    (packs / f"{pack_id}.json").write_text(json.dumps(rec), encoding="utf-8")


def _seed_run_posted(data_dir, *, run_id, profile_id, meet_name, finished, posted_on):
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "finished_at": f"{finished}T12:00:00+00:00",
                "meet": {"name": meet_name},
            }
        ),
        encoding="utf-8",
    )
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    store = WorkflowStore(runs)
    store.set_status(run_id, "card-1", CardStatus.POSTED, posted_at=f"{posted_on}T09:00:00+00:00")


# ---------------------------------------------------------------------------
# Key-date packs — exact, deterministic, honest
# ---------------------------------------------------------------------------


def test_key_date_pack_loads_and_resolves_exactly():
    pack = load_key_date_pack("swimming")
    assert pack is not None and pack.sport == "swimming"
    assert pack.key_dates, "swimming pack ships at least one key date"
    # Every shipped entry resolves to a real date (no malformed rules slip in).
    for kd in pack.key_dates:
        assert kd.resolve(2026) is not None
    names = {kd.name: kd.resolve(2026) for kd in pack.key_dates}
    # A known fixed UN observance lands on its exact day, every year.
    assert names.get("World Water Day") == date(2026, 3, 22)
    assert load_key_date_pack("swimming").key_dates[0].resolve(2027) is not None


def test_key_date_no_pack_is_honest_none():
    assert load_key_date_pack("quidditch") is None
    assert key_dates_in_range("quidditch", date(2026, 1, 1), date(2026, 12, 31)) == []


def test_nth_weekday_math():
    # 4th Wednesday of September 2026 is the 23rd; last Monday of May 2026 the 25th.
    assert _nth_weekday(2026, 9, 2, 4) == date(2026, 9, 23)
    assert _nth_weekday(2026, 5, 0, -1) == date(2026, 5, 25)
    assert _nth_weekday(2026, 2, 6, 5) is None  # no 5th Sunday in Feb 2026


def test_key_dates_in_range_spans_years_and_sorts():
    res = key_dates_in_range("swimming", date(2025, 12, 1), date(2026, 1, 31))
    # New-year hook resolves for 2026 inside the window.
    assert any(r.on == date(2026, 1, 1) for r in res)
    # Sorted ascending by date.
    assert [r.on for r in res] == sorted(r.on for r in res)


# ---------------------------------------------------------------------------
# Calendar assembler
# ---------------------------------------------------------------------------


def test_calendar_fuses_all_sources_and_isolates_tenants(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)

    _seed_pack(tmp_path, pack_id="p1", profile_id=ORG_A, title="Sponsor shoutout",
               planned_date="2026-06-08", n_cards=1)
    _seed_pack(tmp_path, pack_id="p2", profile_id=ORG_A, title="Gala preview", n_cards=2)
    _seed_pack(tmp_path, pack_id="leak", profile_id=ORG_B, title="Other club",
               planned_date="2026-06-08")  # must NOT appear for ORG_A
    _seed_run_posted(tmp_path, run_id="r1", profile_id=ORG_A, meet_name="County Champs",
                     finished="2024-06-15", posted_on="2026-06-10")

    from mediahub.content_engine.inputs import save_planner_inputs

    save_planner_inputs(
        ORG_A,
        {
            "upcoming_events": [{"name": "Open Day", "date": "2026-06-08", "venue": "Pool"}],
            "blackout_dates": ["2026-06-08"],
            "goals": [],
        },
    )

    model = build_calendar(ORG_A, "swimming", start=date(2026, 6, 1), end=date(2026, 6, 30))
    counts = model.counts()
    assert counts["planned_draft"] == 1
    assert counts["event"] == 1
    assert counts["blackout"] == 1
    assert counts["posted"] == 1
    assert counts["anniversary"] == 1  # 2 years since County Champs
    assert counts["key_date"] >= 1  # World Oceans Day / Olympic Day in June

    # Tenant isolation — the other org's planned draft never leaks in.
    titles = {e.title for e in model.entries}
    assert "Other club" not in titles

    # The unscheduled draft is in the side rail, not on the grid.
    rail = {d["pack_id"] for d in model.unscheduled_drafts}
    assert rail == {"p2"}

    # A planned draft on a blackout day is flagged for the soft gate.
    planned = [e for e in model.entries if e.kind == "planned_draft"]
    assert planned and planned[0].meta.get("on_blackout") is True


def test_calendar_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    _seed_pack(tmp_path, pack_id="p1", profile_id=ORG_A, title="A", planned_date="2026-06-09")
    a = build_calendar(ORG_A, "swimming", start=date(2026, 6, 1), end=date(2026, 6, 30))
    b = build_calendar(ORG_A, "swimming", start=date(2026, 6, 1), end=date(2026, 6, 30))
    assert a.to_dict() == b.to_dict()


def test_calendar_empty_window_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    # A window with no key dates / drafts / events for this org.
    model = build_calendar(ORG_A, "swimming", start=date(2030, 2, 1), end=date(2030, 2, 28))
    assert model.entries == []
    assert any("honest" in n.lower() or "nothing" in n.lower() for n in model.notes)


def test_month_matrix_is_monday_first_and_covers_month():
    weeks = month_matrix(2026, 6)
    assert all(len(w) == 7 for w in weeks)
    assert weeks[0][0].weekday() == 0  # Monday
    flat = [d for w in weeks for d in w]
    assert date(2026, 6, 1) in flat and date(2026, 6, 30) in flat
    start, end = grid_bounds(2026, 6)
    assert start == weeks[0][0] and end == weeks[-1][-1]


# ---------------------------------------------------------------------------
# Store — planned-date schedule mutation
# ---------------------------------------------------------------------------


def test_set_planned_date_set_clear_and_validate(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.club_platform import stub_pack_store as sps

    saved = sps.save_pack("free_text", {"free_text": "hi"}, [{"caption": "x"}], profile_id=ORG_A)
    pid = saved["pack_id"]

    # Set a valid date + channel.
    rec = sps.set_planned_date(pid, "2026-06-08", channel="instagram")
    assert rec["planned_date"] == "2026-06-08"
    assert rec["planned_channel"] == "instagram"
    assert sps.load_pack(pid)["planned_date"] == "2026-06-08"

    # list_packs surfaces it.
    listed = {p["pack_id"]: p for p in sps.list_packs()}
    assert listed[pid]["planned_date"] == "2026-06-08"

    # Invalid date is refused (None), pack unchanged.
    assert sps.set_planned_date(pid, "08/06/2026") is None
    assert sps.set_planned_date(pid, "2026-13-40") is None

    # Clearing removes both date + channel.
    rec = sps.set_planned_date(pid, "")
    assert "planned_date" not in rec and "planned_channel" not in rec

    # Missing pack → None.
    assert sps.set_planned_date("nope-nope", "2026-06-08") is None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    save_profile(ClubProfile(profile_id="org-other", display_name="Other Club"))

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def test_calendar_routes_require_an_org(app_with_org):
    with app_with_org.test_client() as client:
        assert client.get("/api/plan/calendar").status_code == 403
        assert client.post("/api/plan/calendar/schedule", json={"pack_id": "x"}).status_code == 403
        # The page redirects to sign-in rather than erroring.
        assert client.get("/plan/calendar").status_code == 302


def test_calendar_api_and_page_render(app_with_org, tmp_path):
    _seed_pack(tmp_path, pack_id="pp1", profile_id="org-test", title="Sponsor shoutout",
               planned_date="2026-06-09")
    _seed_pack(tmp_path, pack_id="pp2", profile_id="org-test", title="Unscheduled idea")
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        j = client.get("/api/plan/calendar?m=2026-06").get_json()
        assert j["ok"] is True and j["calendar"]["month"] == 6
        kinds = {e["kind"] for e in j["calendar"]["entries"]}
        assert "planned_draft" in kinds
        rail = {d["pack_id"] for d in j["calendar"]["unscheduled_drafts"]}
        assert "pp2" in rail

        page = client.get("/plan/calendar?m=2026-06")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "June 2026" in html
        assert "Sponsor shoutout" in html  # planned draft chip
        assert "Unscheduled idea" in html  # side rail
        assert 'draggable="true"' in html
        assert "World Oceans Day" in html  # a June key date surfaces


def test_calendar_schedule_endpoint_moves_and_warns(app_with_org, tmp_path):
    from mediahub.club_platform import stub_pack_store as sps
    from mediahub.content_engine.inputs import save_planner_inputs

    saved = sps.save_pack("free_text", {"free_text": "hi"}, [{"caption": "x"}],
                          profile_id="org-test")
    pid = saved["pack_id"]
    save_planner_inputs("org-test", {"upcoming_events": [], "blackout_dates": ["2026-06-08"],
                                     "goals": []})

    with app_with_org.test_client() as client:
        _with_org(client, "org-test")

        # Schedule on a normal day — no warning.
        r = client.post("/api/plan/calendar/schedule", json={"pack_id": pid, "date": "2026-06-09"})
        body = r.get_json()
        assert r.status_code == 200 and body["ok"] is True
        assert body["planned_date"] == "2026-06-09" and not body["warning"]

        # Move onto a blackout day — soft warning, but still scheduled.
        r = client.post("/api/plan/calendar/schedule", json={"pack_id": pid, "date": "2026-06-08"})
        body = r.get_json()
        assert body["planned_date"] == "2026-06-08" and body["warning"]

        # Invalid date → 400.
        assert client.post("/api/plan/calendar/schedule",
                           json={"pack_id": pid, "date": "nonsense"}).status_code == 400

        # Clear it.
        r = client.post("/api/plan/calendar/schedule", json={"pack_id": pid, "date": ""})
        assert r.get_json()["planned_date"] in (None, "")


def test_planned_chip_has_nondrag_reschedule_and_unschedule(app_with_org, tmp_path):
    """Audit (a11y / I-1 parity): a planned draft chip must carry the same non-drag
    date field (reschedule) + an unschedule control the rail cards have, so touch
    and keyboard users can move/clear it — not only mouse-drag it."""
    _seed_pack(tmp_path, pack_id="ppX", profile_id="org-test", title="Gala recap",
               planned_date="2026-06-12")
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        html = client.get("/plan/calendar?m=2026-06").get_data(as_text=True)
        assert "Gala recap" in html  # the planned chip rendered
        # The non-drag reschedule date field, pre-filled with the current day.
        assert 'class="mh-cal-plan-date"' in html and 'value="2026-06-12"' in html
        assert 'aria-label="Move Gala recap to another day"' in html
        # The unschedule control + its handler are present.
        assert 'class="mh-cal-unplan"' in html
        assert "function mhCalUnplan" in html


def test_calendar_schedule_is_tenant_isolated(app_with_org, tmp_path):
    from mediahub.club_platform import stub_pack_store as sps

    saved = sps.save_pack("free_text", {"free_text": "hi"}, [{"caption": "x"}],
                          profile_id="org-other")
    pid = saved["pack_id"]
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")  # different org
        r = client.post("/api/plan/calendar/schedule", json={"pack_id": pid, "date": "2026-06-09"})
        assert r.status_code == 404  # org-test can't reschedule org-other's draft
    # And the pack was not mutated.
    assert sps.load_pack(pid).get("planned_date") is None
