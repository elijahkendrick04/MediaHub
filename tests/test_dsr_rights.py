"""Data subject rights — SAR export, rectification, erasure propagation, Art 12A clock.

The definition-of-done test lives here: an erasure request provably removes
the athlete from every store in the data map (runs, rendered visuals,
workflow state, PB caches incl. raw search HTML, media library, caption
memory, club-profile text), keeps a suppression record, and honestly reports
what it could not reach (raw uploads naming other athletes; published posts).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ATHLETE = "Eira Hughes"
OTHER = "Amelia Osborne"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    return tmp_path


def _seed_world(data_dir: Path, profile_id="clubx", run_id="runE"):
    """A miniature deployment: run + visuals + workflow + caches + uploads."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    profile = ClubProfile(profile_id=profile_id, display_name="Club X")
    profile.voice_examples = [f"What a swim from {ATHLETE} tonight!", "Great club night."]
    save_profile(profile)

    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Test Meet"},
        "cards": [
            {"id": "cardA", "swim_id": "cardA", "swimmer_name": ATHLETE, "headline": f"{ATHLETE} PB"},
            {"id": "cardB", "swim_id": "cardB", "swimmer_name": OTHER, "headline": f"{OTHER} medal"},
        ],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "achievement": {"swim_id": "cardA", "swimmer_name": ATHLETE, "event": "100 Free"},
                },
                {
                    "rank": 2,
                    "achievement": {"swim_id": "cardB", "swimmer_name": OTHER, "event": "50 Back"},
                },
            ],
            "n_achievements": 2,
        },
        "results": [
            {"name": ATHLETE, "time": "57.10"},
            {"name": OTHER, "time": "31.20"},
        ],
    }
    (runs / f"{run_id}.json").write_text(json.dumps(run))
    (runs / f"{run_id}__workflow.json").write_text(
        json.dumps({"cardA": {"status": "approved"}, "cardB": {"status": "queue"}})
    )
    visuals = runs / run_id / "visuals"
    visuals.mkdir(parents=True)
    (visuals / "cardA_story.png").write_bytes(b"png-bytes")
    (visuals / "eira-hughes-100-free.png").write_bytes(b"png-bytes")
    (visuals / "cardB_story.png").write_bytes(b"png-bytes")

    discovered = data_dir / "data" / "discovered"
    (discovered / "swimmers").mkdir(parents=True)
    (discovered / "swimmers" / "abc123.json").write_text(
        json.dumps({"name": ATHLETE, "pbs": [{"event": "100 Free", "time": "57.50"}]})
    )
    (discovered / "swimmers" / "def456.json").write_text(
        json.dumps({"name": OTHER, "pbs": []})
    )
    (discovered / "search_cache").mkdir(parents=True)
    (discovered / "search_cache" / "deadbeef.json").write_text(
        json.dumps({"html": f"<tr><td>{ATHLETE}</td><td>57.50</td></tr>"})
    )

    uploads = data_dir / "uploads_v4" / run_id
    uploads.mkdir(parents=True)
    (uploads / "results.pdf").write_bytes(b"%PDF fake " + ATHLETE.encode())

    packs = data_dir / "turn_into_packs" / run_id
    packs.mkdir(parents=True)
    (packs / "pack1.json").write_text(
        json.dumps({"artefacts": [{"caption": f"Huge PB for {ATHLETE}!", "swimmer_name": ATHLETE}]})
    )
    return run_id


@pytest.fixture
def media_store(data_dir, monkeypatch):
    from mediahub.media_library import store as ml

    test_store = ml.MediaLibraryStore(
        db_path=data_dir / "data.db", uploads_dir=data_dir / "uploads_v4" / "media_library"
    )
    monkeypatch.setattr(ml, "_default_store", test_store)
    return test_store


def _seed_media(media_store, data_dir, profile_id="clubx"):
    from mediahub.media_library.models import MediaAsset

    solo_path = data_dir / "uploads_v4" / "media_library" / "solo.jpg"
    solo_path.parent.mkdir(parents=True, exist_ok=True)
    solo_path.write_bytes(b"jpg")
    group_path = solo_path.parent / "group.jpg"
    group_path.write_bytes(b"jpg")
    solo = MediaAsset(
        id="solo1",
        filename="solo.jpg",
        path=str(solo_path),
        type="photo",
        linked_athlete_names=[ATHLETE],
        profile_id=profile_id,
    )
    group = MediaAsset(
        id="group1",
        filename="group.jpg",
        path=str(group_path),
        type="photo",
        linked_athlete_names=[ATHLETE, OTHER],
        profile_id=profile_id,
    )
    media_store.save(solo)
    media_store.save(group)
    return solo_path, group_path


# ------------------------------------------------------------------ export


def test_sar_export_collects_every_store(data_dir, media_store):
    _seed_world(data_dir)
    _seed_media(media_store, data_dir)
    from mediahub.compliance.dsr import export_athlete

    export = export_athlete("clubx", ATHLETE)
    assert export["runs"] and export["runs"][0]["run_id"] == "runE"
    assert "cardA" in export["runs"][0]["card_ids"]
    assert {a["id"] for a in export["media_assets"]} == {"solo1", "group1"}
    cache_paths = " ".join(c["path"] for c in export["pb_caches"])
    assert "abc123" in cache_paths and "deadbeef" in cache_paths
    assert "def456" not in cache_paths  # other athlete's cache not exported
    # honesty note about published content
    assert any("independent controllers" in n for n in export["notes"])


def test_export_and_erase_never_cross_match_name_prefixes(data_dir):
    """'Sam Lee' must never match 'Sam Leeson' in the global PB caches.

    A substring scan crossed data subjects (and tenants): export embedded
    another swimmer's cache file; erasure deleted it. Whole-name matching
    plus row redaction keeps each subject's SAR to their own data.
    """
    discovered = data_dir / "discovered"
    (discovered / "swimmers").mkdir(parents=True)
    (discovered / "swimmers" / "leeson.json").write_text(
        json.dumps({"name": "Sam Leeson", "pbs": [{"event": "50 Free", "time": "29.10"}]})
    )
    mixed = discovered / "swimmers" / "mixed.json"
    mixed.write_text(
        json.dumps(
            {
                "meet": "Spring Open",
                "rows": [
                    {"name": "Sam Lee", "time": "57.10"},
                    {"name": "Rival Kid", "time": "58.00"},
                ],
            }
        )
    )
    from mediahub.compliance.dsr import erase_athlete, export_athlete

    export = export_athlete("clubx", "Sam Lee")
    cache_paths = " ".join(c["path"] for c in export["pb_caches"])
    assert "leeson" not in cache_paths  # prefix collision never exported
    assert "mixed" in cache_paths
    mixed_entry = next(c for c in export["pb_caches"] if "mixed" in c["path"])
    blob = json.dumps(mixed_entry["content"])
    assert "Sam Lee" in blob
    assert "Rival Kid" not in blob  # other subjects' rows redacted
    assert mixed_entry["rows_redacted"] == 1

    report = erase_athlete("clubx", "Sam Lee")
    assert (discovered / "swimmers" / "leeson.json").exists(), report
    assert not mixed.exists()


# ----------------------------------------------------------------- erasure


def test_erasure_propagates_to_every_store(data_dir, media_store):
    _seed_world(data_dir)
    solo_path, group_path = _seed_media(media_store, data_dir)
    from mediahub.compliance.dsr import erase_athlete

    report = erase_athlete("clubx", ATHLETE, recorded_by="coach@clubx.org")

    # run JSON: achievements + cards gone, results row redacted
    run = json.loads((data_dir / "runs_v4" / "runE.json").read_text())
    text = json.dumps(run).lower()
    assert "eira" not in text
    names = [ra["achievement"]["swimmer_name"] for ra in run["recognition_report"]["ranked_achievements"]]
    assert names == [OTHER]
    assert run["recognition_report"]["n_achievements"] == 1
    assert [c["swimmer_name"] for c in run["cards"]] == [OTHER]
    assert run["results"][0]["name"] == "[erased]"
    assert run["results"][1]["name"] == OTHER

    # rendered visuals for the athlete deleted; other athlete's kept
    visuals = data_dir / "runs_v4" / "runE" / "visuals"
    assert not (visuals / "cardA_story.png").exists()
    assert not (visuals / "eira-hughes-100-free.png").exists()
    assert (visuals / "cardB_story.png").exists()

    # workflow entry for the card removed
    wf = json.loads((data_dir / "runs_v4" / "runE__workflow.json").read_text())
    assert "cardA" not in wf and "cardB" in wf

    # PB caches (incl. raw search HTML) deleted; other athlete's kept. The
    # discovered store migrates from the legacy doubled "data/discovered"
    # path to the canonical <DATA_DIR>/discovered on first access, so the
    # erased athlete must be gone from BOTH roots and the kept athlete's
    # cache survives at the canonical one.
    for discovered in (data_dir / "data" / "discovered", data_dir / "discovered"):
        assert not (discovered / "swimmers" / "abc123.json").exists()
        assert not (discovered / "search_cache" / "deadbeef.json").exists()
    assert (data_dir / "discovered" / "swimmers" / "def456.json").exists()

    # turn-into pack redacted
    pack = json.loads((data_dir / "turn_into_packs" / "runE" / "pack1.json").read_text())
    assert "eira" not in json.dumps(pack).lower()

    # media: solo photo deleted (record + file); group photo unlinked but kept
    assert media_store.get("solo1") is None
    assert not solo_path.exists()
    group = media_store.get("group1")
    assert group is not None and group.linked_athlete_names == [OTHER]
    assert group_path.exists()

    # club profile voice example redacted
    from mediahub.web.club_profile import load_profile

    profile = load_profile("clubx")
    assert all("eira" not in v.lower() for v in profile.voice_examples)

    # suppression record exists → the gate blocks any future reappearance
    from mediahub.compliance.gate import consent_block_reason

    assert consent_block_reason("clubx", ATHLETE, age=14) is not None

    # honest residuals: raw upload + published posts
    residuals = " ".join(report["residuals"])
    assert "results.pdf" in residuals or "raw uploaded results" in residuals
    assert "platform" in residuals

    # report numbers reflect the work
    assert report["cards_removed"] >= 2
    assert report["pb_cache_files_deleted"]
    assert report["media_assets_deleted"] == ["solo1"]
    assert report["media_assets_unlinked"] == ["group1"]


def test_erasure_then_new_pack_excludes_athlete(data_dir, media_store):
    """Definition of done: an erased/opted-out athlete disappears from NEW packs."""
    _seed_world(data_dir)
    from mediahub.compliance.dsr import erase_athlete
    from mediahub.compliance.gate import filter_consent_blocked

    erase_athlete("clubx", ATHLETE)
    fresh_run = {
        "run_id": "runF",
        "profile_id": "clubx",
        "cards": [],
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": {"swim_id": "x1", "swimmer_name": ATHLETE, "event": "200 IM"}},
                {"achievement": {"swim_id": "x2", "swimmer_name": OTHER, "event": "50 Fly"}},
            ]
        },
    }
    filtered, excluded = filter_consent_blocked("clubx", fresh_run)
    kept = [ra["achievement"]["swimmer_name"] for ra in filtered["recognition_report"]["ranked_achievements"]]
    assert kept == [OTHER]
    assert excluded == [ATHLETE]


def test_erasure_in_memory_db_when_available(data_dir):
    from mediahub.memory import store as memory_store

    if not memory_store.is_available():
        pytest.skip("sqlite-vec not available in this environment")
    memory_store.upsert(
        tenant_id="clubx",
        entry_id="m1",
        vector=[0.1] * 8,
        model_id="test-model",
        caption=f"{ATHLETE} smashed her PB tonight!",
        event_context="100 Free",
        card_id="cardA",
        run_id="runE",
    )
    from mediahub.compliance.dsr import erase_athlete

    report = erase_athlete("clubx", ATHLETE)
    # either layer may do the deletion (the privacy cascade sweeps caption
    # memory too) — what matters is the row is GONE
    cascade_rows = (report.get("cascade") or {}).get("memory_rows", 0)
    assert report["memory_rows_deleted"] + cascade_rows >= 1
    from mediahub.compliance.dsr import _memory_rows_matching
    from mediahub.compliance.consent import athlete_key

    assert _memory_rows_matching(memory_store, "clubx", athlete_key(ATHLETE)) == []


# ------------------------------------------------------------ rectification


def test_rectification_renames_across_stores(data_dir, media_store):
    _seed_world(data_dir)
    _seed_media(media_store, data_dir)
    from mediahub.compliance.consent import ConsentRegistry
    from mediahub.compliance.dsr import rectify_athlete_name

    ConsentRegistry("clubx").record(athlete_name=ATHLETE, status="granted", parental=True, under_18=True)
    report = rectify_athlete_name("clubx", ATHLETE, "Eira Hughes-Williams")

    run = json.loads((data_dir / "runs_v4" / "runE.json").read_text())
    names = {ra["achievement"]["swimmer_name"] for ra in run["recognition_report"]["ranked_achievements"]}
    assert "Eira Hughes-Williams" in names
    assert report["fields_updated"] >= 2

    group = media_store.get("group1")
    assert "Eira Hughes-Williams" in group.linked_athlete_names

    rec = ConsentRegistry("clubx").get("Eira Hughes-Williams")
    assert rec is not None and rec.status == "granted" and rec.parental is True


# ------------------------------------------------------ Art 12A request log


def test_request_log_clock_stop_extends_due_date(data_dir):
    from mediahub.compliance.dsr import DsrRequestLog

    log = DsrRequestLog()
    req = log.open(profile_id="clubx", athlete_name=ATHLETE, request_type="access")
    assert req.status == "open"
    base_due = req.due_at

    stopped = log.stop_clock(req.id, note="awaiting ID verification")
    assert stopped.status == "clock_stopped"
    resumed = log.resume_clock(req.id)
    assert resumed.status == "open"
    assert resumed.due_at >= base_due  # paused time pushes the deadline out

    done = log.complete(req.id, note="export sent")
    assert done.status == "completed" and done.completed_at


def test_request_log_scoped_per_tenant(data_dir):
    from mediahub.compliance.dsr import DsrRequestLog

    log = DsrRequestLog()
    log.open(profile_id="club-a", athlete_name="A", request_type="access")
    log.open(profile_id="club-b", athlete_name="B", request_type="erasure")
    assert [r.athlete_name for r in log.all(profile_id="club-a")] == ["A"]


# ------------------------------------------------------------- web routes


@pytest.fixture
def client(data_dir):
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application.test_client()


def test_rights_page_requires_active_org(client):
    assert client.get("/organisation/athlete-rights").status_code == 404


def test_rights_workflow_via_routes(client, data_dir, media_store):
    _seed_world(data_dir)
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"

    r = client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": ATHLETE, "request_type": "access", "note": "parent email"},
    )
    assert r.status_code == 302

    from mediahub.compliance.dsr import DsrRequestLog

    req = DsrRequestLog().all(profile_id="clubx")[0]
    page = client.get("/organisation/athlete-rights")
    assert req.id.encode() in page.data

    r = client.post(f"/organisation/athlete-rights/{req.id}/run")
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    export = json.loads(r.data)
    assert export["athlete_name"] == ATHLETE
    assert DsrRequestLog().get(req.id).status == "completed"

    # cross-tenant: another org cannot run this tenant's requests
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "other-org"
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="other-org", display_name="Other"))
    r = client.post(f"/organisation/athlete-rights/{req.id}/run")
    assert r.status_code == 404


def test_erasure_route_records_security_event(client, data_dir, media_store):
    _seed_world(data_dir)
    with client.session_transaction() as sess:
        sess["active_profile_id"] = "clubx"
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": ATHLETE, "request_type": "erasure"},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    req = DsrRequestLog().all(profile_id="clubx")[0]
    r = client.post(f"/organisation/athlete-rights/{req.id}/run")
    assert r.status_code == 200
    assert b"Erasure report" in r.data

    from mediahub.compliance.security_log import read_events

    events = [e for e in read_events() if e["event"] == "dsr_erasure"]
    assert events, "erasure must be recorded in the security event log"
    # pseudonymised: the athlete's name is NOT in the log
    assert ATHLETE.lower() not in json.dumps(events).lower()
    assert events[0]["subject_pseudonym"]


def test_account_erasure_rewrites_users_ledger(data_dir):
    users = data_dir / "users.jsonl"
    users.write_text(
        json.dumps({"email": "keep@x.org", "hashed_password": "$2b$x", "plan": "free"})
        + "\n"
        + json.dumps({"email": "gone@x.org", "hashed_password": "$2b$y", "plan": "club"})
        + "\n"
    )
    from mediahub.compliance.dsr import erase_user_account

    assert erase_user_account("GONE@x.org") is True
    text = users.read_text()
    assert "gone@x.org" not in text and "keep@x.org" in text
    assert erase_user_account("gone@x.org") is False
