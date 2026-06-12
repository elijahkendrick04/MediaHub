"""PC.8 — sponsor registry, deterministic rotation, exposure report."""

from __future__ import annotations

import pytest

from mediahub.club_platform.sponsors import (
    active_sponsors,
    exposure_report,
    normalise_sponsor,
    record_exposure,
    registry_for,
    sponsor_for_card,
    sponsor_rotation_seed,
)
from mediahub.web.club_profile import ClubProfile


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _profile(**kwargs) -> ClubProfile:
    return ClubProfile(profile_id="testclub", display_name="Test Club", **kwargs)


# ---- registry ----------------------------------------------------------


def test_normalise_sponsor_fills_id_and_tier():
    s = normalise_sponsor({"name": "Acme Pools"})
    assert s["name"] == "Acme Pools"
    assert s["sponsor_id"]  # derived, stable
    assert s["tier"] == "partner"
    assert (
        normalise_sponsor({"name": "Acme"})["sponsor_id"]
        == normalise_sponsor({"name": "acme"})["sponsor_id"]
    )


def test_normalise_sponsor_rejects_nameless():
    assert normalise_sponsor({}) is None
    assert normalise_sponsor({"name": "  "}) is None
    assert normalise_sponsor("not a dict") is None


def test_registry_drops_invalid_entries():
    p = _profile(sponsors=[{"name": "Acme"}, {}, {"name": ""}, "junk"])
    assert [s["name"] for s in registry_for(p)] == ["Acme"]


def test_active_window_filtering():
    p = _profile(
        sponsors=[
            {"name": "Always"},
            {"name": "Past", "active_until": "2025-12-31"},
            {"name": "Future", "active_from": "2099-01-01"},
            {"name": "Window", "active_from": "2026-01-01", "active_until": "2026-12-31"},
        ]
    )
    names = [s["name"] for s in active_sponsors(p, on_date="2026-06-11")]
    assert names == ["Always", "Window"]


# ---- rotation ----------------------------------------------------------


def test_rotation_is_deterministic_and_spreads():
    p = _profile(sponsors=[{"name": "A"}, {"name": "B"}, {"name": "C"}])
    picks = {f"card{i}": sponsor_for_card(p, "run1", f"card{i}")["name"] for i in range(30)}
    # Re-running gives the identical assignment (stills ↔ motion parity).
    again = {f"card{i}": sponsor_for_card(p, "run1", f"card{i}")["name"] for i in range(30)}
    assert picks == again
    # Rotation actually uses more than one sponsor across 30 cards.
    assert len(set(picks.values())) > 1


def test_rotation_seed_matches_run_card_identity():
    assert sponsor_rotation_seed("r", "c") == sponsor_rotation_seed("r", "c")
    assert sponsor_rotation_seed("r", "c1") != sponsor_rotation_seed("r", "c2")


def test_no_sponsors_returns_none():
    assert sponsor_for_card(_profile(), "run1", "card1") is None


def test_legacy_single_sponsor_name_fallback():
    p = _profile(sponsor_name="Legacy Sponsor Ltd")
    s = sponsor_for_card(p, "run1", "card1")
    assert s["name"] == "Legacy Sponsor Ltd"


def test_registry_wins_over_legacy_field():
    p = _profile(sponsor_name="Legacy", sponsors=[{"name": "New"}])
    assert sponsor_for_card(p, "run1", "card1")["name"] == "New"


def test_expired_registry_falls_back_to_legacy():
    p = _profile(
        sponsor_name="Legacy",
        sponsors=[{"name": "Old", "active_until": "2020-01-01"}],
    )
    assert sponsor_for_card(p, "run1", "card1", on_date="2026-06-11")["name"] == "Legacy"


# ---- exposure ledger + report ------------------------------------------


class _FakeState:
    def __init__(self, status):
        self.status = status


class _FakeWorkflow:
    def __init__(self, states):
        self._states = states

    def load(self, run_id):
        return self._states.get(run_id, {})


def test_exposure_recording_is_idempotent(tmp_path):
    for _ in range(3):
        record_exposure(
            "testclub",
            run_id="run1",
            card_id="card1",
            sponsor_id="s1",
            sponsor_name="Acme",
        )
    ledger = tmp_path / "sponsors" / "testclub__exposure.jsonl"
    assert len(ledger.read_text().strip().splitlines()) == 1


def test_exposure_report_counts_by_month_and_status():
    record_exposure("testclub", run_id="run1", card_id="c1", sponsor_id="s1", sponsor_name="Acme")
    record_exposure("testclub", run_id="run1", card_id="c2", sponsor_id="s1", sponsor_name="Acme")
    record_exposure("testclub", run_id="run1", card_id="c3", sponsor_id="s2", sponsor_name="Bolt")
    # Motion render of an already-counted card must not double-count.
    record_exposure(
        "testclub",
        run_id="run1",
        card_id="c1",
        sponsor_id="s1",
        sponsor_name="Acme",
        surface="motion",
    )

    wf = _FakeWorkflow(
        {
            "run1": {
                "c1": _FakeState("approved"),
                "c2": _FakeState("posted"),
                "c3": _FakeState("queue"),
            }
        }
    )
    import time

    month = time.strftime("%Y-%m", time.gmtime())
    report = exposure_report("testclub", month, workflow_store=wf)
    by_name = {s["sponsor_name"]: s for s in report["sponsors"]}
    assert by_name["Acme"]["cards"] == 2
    assert by_name["Acme"]["approved"] == 2  # approved + posted both count as approved
    assert by_name["Acme"]["posted"] == 1
    assert by_name["Bolt"]["cards"] == 1
    assert by_name["Bolt"]["approved"] == 0


def test_exposure_report_other_month_is_empty():
    record_exposure("testclub", run_id="run1", card_id="c1", sponsor_id="s1", sponsor_name="Acme")
    report = exposure_report("testclub", "1999-01", workflow_store=_FakeWorkflow({}))
    assert report["sponsors"] == []


# ---- routes: sponsor manager + report + rotation wiring -------------------


@pytest.fixture
def sponsor_app(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="testclub", display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": wm, "tmp": tmp_path}


def _pin(client, profile_id="testclub"):
    return client.post("/api/organisation/active", data={"profile_id": profile_id})


def test_sponsors_page_requires_org(sponsor_app):
    c = sponsor_app["app"].test_client()
    assert c.get("/sponsors").status_code == 302


def test_sponsor_add_list_delete_roundtrip(sponsor_app):
    from mediahub.web.club_profile import load_profile

    c = sponsor_app["app"].test_client()
    assert _pin(c).status_code == 200

    r = c.post(
        "/sponsors/add",
        data={"name": "Acme Pools", "tier": "gold", "active_from": "2026-01-01"},
    )
    assert r.status_code == 302
    prof = load_profile("testclub")
    assert len(prof.sponsors) == 1
    assert prof.sponsors[0]["name"] == "Acme Pools"
    assert prof.sponsors[0]["tier"] == "gold"

    page = c.get("/sponsors").get_data(as_text=True)
    assert "Acme Pools" in page

    sid = prof.sponsors[0]["sponsor_id"]
    c.post("/sponsors/delete", data={"sponsor_id": sid})
    assert load_profile("testclub").sponsors == []


def test_sponsor_report_route(sponsor_app):
    import time

    c = sponsor_app["app"].test_client()
    assert _pin(c).status_code == 200
    record_exposure("testclub", run_id="run1", card_id="c1", sponsor_id="s1", sponsor_name="Acme")
    month = time.strftime("%Y-%m", time.gmtime())
    r = c.get(f"/sponsors/report?month={month}")
    assert r.status_code == 200
    assert b"Acme" in r.data
    dl = c.get(f"/sponsors/report?month={month}&download=1")
    assert "attachment" in dl.headers.get("Content-Disposition", "")


def _seed_owned_run(world, run_id="runsponsor01"):
    runs_dir = world["tmp"] / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    import json as _json

    data = {
        "profile_id": "testclub",
        "meet_name": "Sponsor Gala",
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Alice Smith",
                        "event": "100m Freestyle",
                        "time": "59.10",
                        "type": "pb_confirmed",
                    }
                }
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(_json.dumps(data))
    conn = world["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', 'testclub', 'Sponsor Gala', 's.hy3')",
        (run_id,),
    )
    conn.commit()
    conn.close()


def test_create_graphic_rotates_registry_sponsor_and_records_exposure(sponsor_app, monkeypatch):
    """The standard card render carries the rotated registry sponsor and
    appends to the exposure ledger; legacy single-name profiles do not."""
    from mediahub.web.club_profile import load_profile, save_profile

    wm = sponsor_app["wm"]
    if not wm._v8_ok:
        pytest.skip("v8 visual pipeline unavailable in this environment")
    _seed_owned_run(sponsor_app)

    prof = load_profile("testclub")
    prof.sponsors = [{"name": "Acme Pools"}, {"name": "Bolt Timing"}]
    save_profile(prof)

    seen = {}

    def fake_create_visual(item, brand_kit, **kw):
        seen["sponsor_name"] = kw.get("sponsor_name")
        return {
            "visuals": [{"id": "v1", "format_name": "feed_portrait", "file_path": "/tmp/x.png"}],
            "brief": {},
            "errors": [],
        }

    monkeypatch.setattr(wm, "_v8_create_visual_for_item", fake_create_visual)

    c = sponsor_app["app"].test_client()
    assert _pin(c).status_code == 200
    r = c.post("/api/runs/runsponsor01/cards/swim-1/create-graphic")
    assert r.status_code == 200, r.get_json()
    assert seen["sponsor_name"] in ("Acme Pools", "Bolt Timing")

    ledger = sponsor_app["tmp"] / "sponsors" / "testclub__exposure.jsonl"
    assert ledger.exists()
    rec = __import__("json").loads(ledger.read_text().strip().splitlines()[-1])
    assert rec["run_id"] == "runsponsor01" and rec["card_id"] == "swim-1"
    assert rec["sponsor_name"] == seen["sponsor_name"]


def test_create_graphic_legacy_sponsor_name_not_rotated(sponsor_app, monkeypatch):
    from mediahub.web.club_profile import load_profile, save_profile

    wm = sponsor_app["wm"]
    if not wm._v8_ok:
        pytest.skip("v8 visual pipeline unavailable in this environment")
    _seed_owned_run(sponsor_app, run_id="runsponsor02")

    prof = load_profile("testclub")
    prof.sponsor_name = "Legacy Sponsor"  # legacy field only, no registry
    prof.sponsors = []
    save_profile(prof)

    seen = {}

    def fake_create_visual(item, brand_kit, **kw):
        seen["sponsor_name"] = kw.get("sponsor_name")
        return {
            "visuals": [{"id": "v1", "format_name": "feed_portrait", "file_path": "/tmp/x.png"}],
            "brief": {},
            "errors": [],
        }

    monkeypatch.setattr(wm, "_v8_create_visual_for_item", fake_create_visual)

    c = sponsor_app["app"].test_client()
    assert _pin(c).status_code == 200
    r = c.post("/api/runs/runsponsor02/cards/swim-1/create-graphic")
    assert r.status_code == 200
    # Pre-PC.8 behaviour preserved: no sponsor on standard cards.
    assert seen["sponsor_name"] == ""
    assert not (sponsor_app["tmp"] / "sponsors" / "testclub__exposure.jsonl").exists()
