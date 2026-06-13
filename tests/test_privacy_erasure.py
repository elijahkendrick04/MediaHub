"""UK legal baseline — erasure cascades and account export (Arts. 15/17/20).

The point of these tests is to prove deletion actually removes the data from
EVERY store that holds it: run JSON, rendered assets, PB caches (warm +
per-run), research cache, caption memory, posting-log excerpts, users
ledger, acceptance ledger, memberships.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _seed_run(data_dir, run_id="run1", profile_id="sharks", athlete="Jane Smith"):
    runs = data_dir / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {
            "name": "Spring Open",
            "swims": [
                {"first_name": "Jane", "last_name": "Smith", "event": "100 Free", "time": "58.21"},
                {"first_name": "Tom", "last_name": "Jones", "event": "100 Free", "time": "55.10"},
            ],
        },
        "cards": [
            {
                "card_id": "c-jane",
                "title": f"PB for {athlete}!",
                "caption": f"{athlete} smashed it",
            },
            {
                "card_id": "c-tom",
                "title": "PB for Tom Jones!",
                "caption": "Tom Jones flying — and Jane Smith cheered",
            },
        ],
    }
    (runs / f"{run_id}.json").write_text(json.dumps(payload))
    side = runs / run_id
    side.mkdir(exist_ok=True)
    (side / "c-jane__story.png").write_bytes(b"png")
    (side / "c-tom__story.png").write_bytes(b"png")
    return runs / f"{run_id}.json"


def _seed_pb_caches(data_dir, athlete="Jane Smith", club="Sharks", run_id="run1"):
    from mediahub.pb_discovery.cache import make_swimmer_key

    key = make_swimmer_key(athlete, club)
    warm = data_dir / "data" / "discovered" / "swimmers"
    warm.mkdir(parents=True, exist_ok=True)
    (warm / f"{key}.json").write_text(json.dumps({"name": athlete, "pbs": {"100 Free": "58.50"}}))
    per_run = data_dir / "data" / "discovered" / "pbs" / run_id
    per_run.mkdir(parents=True, exist_ok=True)
    (per_run / f"{key}.json").write_text(json.dumps({"name": athlete}))
    research = data_dir / ".cache" / "pb_lookup"
    research.mkdir(parents=True, exist_ok=True)
    (research / "q1.json").write_text(json.dumps({"query": f'"{athlete}" Sharks', "hits": []}))
    return warm / f"{key}.json", per_run / f"{key}.json", research / "q1.json"


def _seed_posting_log(profile_id="sharks", run_id="run1", caption="Jane Smith PB!"):
    from mediahub.publishing import posting_log

    posting_log._ensure_schema()
    rid = posting_log.record_attempt(
        profile_id=profile_id,
        run_id=run_id,
        card_id="c-jane",
        status="ok",
        caption=caption,
    )
    assert rid > 0


# ---- athlete erasure --------------------------------------------------------


def test_athlete_erasure_cascades_everywhere(data_dir):
    run_file = _seed_run(data_dir)
    warm, per_run, research = _seed_pb_caches(data_dir)
    _seed_posting_log()
    from mediahub.privacy import erase_athlete

    report = erase_athlete("sharks", "Jane Smith", "Sharks")

    # Run JSON: Jane's card gone, her swim row gone, Tom's card kept but
    # her mention redacted.
    data = json.loads(run_file.read_text())
    card_ids = [c["card_id"] for c in data["cards"]]
    assert "c-jane" not in card_ids and "c-tom" in card_ids
    serialised = json.dumps(data).lower()
    assert "jane smith" not in serialised
    assert "[removed]" in json.dumps(data)
    swims = data["meet"]["swims"]
    assert all(s.get("last_name") != "Smith" for s in swims)
    assert any(s.get("last_name") == "Jones" for s in swims)

    # Rendered asset for the removed card gone; the other kept.
    side = data_dir / "runs_v4" / "run1"
    assert not (side / "c-jane__story.png").exists()
    assert (side / "c-tom__story.png").exists()

    # Caches gone.
    assert not warm.exists() and not per_run.exists() and not research.exists()

    # Posting-log excerpt blanked (row kept).
    from mediahub.publishing import posting_log

    rows = posting_log.recent_attempts("sharks")
    assert rows and all("jane" not in (r["caption_excerpt"] or "").lower() for r in rows)

    assert report.cards_removed == 1
    assert report.swims_removed == 1
    assert report.runs_touched == ["run1"]
    assert report.posting_excerpts >= 1


def test_athlete_erasure_is_tenant_scoped(data_dir):
    _seed_run(data_dir, run_id="run1", profile_id="sharks")
    _seed_run(data_dir, run_id="run2", profile_id="orcas")
    from mediahub.privacy import erase_athlete

    erase_athlete("sharks", "Jane Smith")
    other = json.loads((data_dir / "runs_v4" / "run2.json").read_text())
    assert "Jane Smith" in json.dumps(other)  # other org untouched


def test_athlete_erasure_reaches_caption_memory(data_dir):
    pytest.importorskip("sqlite_vec")
    from mediahub.memory import store as memory_store

    if not memory_store.is_available():
        pytest.skip("sqlite-vec unavailable")
    memory_store.upsert(
        tenant_id="sharks",
        vector=[0.1, 0.2, 0.3],
        model_id="m",
        caption="Jane Smith with a storming 100 Free PB",
        event_context="100 Free",
        card_id="c-jane",
        run_id="run1",
    )
    from mediahub.privacy import erase_athlete

    report = erase_athlete("sharks", "Jane Smith")
    assert report.memory_rows == 1
    assert memory_store.count(tenant_id="sharks") == 0


# ---- run deletion cascade ---------------------------------------------------


def test_run_deletion_cascade_clears_per_run_stores(data_dir):
    _seed_run(data_dir)
    _, per_run, _ = _seed_pb_caches(data_dir)
    _seed_posting_log()
    from mediahub.privacy import run_deletion_cascade

    report = run_deletion_cascade("run1", "sharks")
    assert not per_run.exists()
    assert report["pb_cache_files"] >= 1
    from mediahub.publishing import posting_log

    rows = posting_log.recent_attempts("sharks")
    assert rows and all((r["caption_excerpt"] or "") == "" for r in rows)


def test_run_deletion_cascade_purges_athlete_swims(data_dir):
    # A deleted run must not leave its swims behind in the milestone log —
    # otherwise athlete race counts and history survive across the site.
    from mediahub.athletes.registry import list_athletes, milestone_context, record_run_swims
    from mediahub.privacy import run_deletion_cascade

    record_run_swims(
        "sharks", "run1", [{"name": "Maya Patel", "event": "100FRLC", "time_cs": 6500}]
    )
    record_run_swims(
        "sharks", "run2", [{"name": "Maya Patel", "event": "50FRLC", "time_cs": 3000}]
    )
    report = run_deletion_cascade("run1", "sharks")
    assert report["athlete_swims"] == 1
    # Only run2's swim remains in the active history.
    assert milestone_context("sharks")["maya patel"]["prior_events"] == ["50FRLC"]
    assert [a.race_count for a in list_athletes("sharks")] == [1]


# ---- account erasure + export ----------------------------------------------


def test_account_erasure_removes_user_acceptances_memberships(data_dir):
    from mediahub.web import legal, tenancy
    from mediahub.web.auth import UserStore

    store = UserStore()
    store.create("officer@club.org", "twelvechars1")
    legal.AcceptanceStore().record("officer@club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    tenancy.MembershipStore().add(
        "officer@club.org", "sharks", role=tenancy.ROLE_OWNER, status=tenancy.STATUS_ACTIVE
    )
    from mediahub.privacy import erase_account

    report = erase_account("officer@club.org")
    assert report["user_removed"] is True
    assert report["acceptances_removed"] == 1
    assert report["memberships_removed"] == 1
    assert store.get("officer@club.org") is None
    # The raw ledger file no longer contains the email at all (no tombstone).
    assert "officer@club.org" not in (data_dir / "users.jsonl").read_text()


def test_account_export_contains_account_but_never_hash(data_dir):
    from mediahub.web import legal
    from mediahub.web.auth import UserStore

    UserStore().create("officer@club.org", "twelvechars1")
    legal.AcceptanceStore().record("officer@club.org", legal.DOC_TERMS, legal.TERMS_VERSION)
    from mediahub.privacy import account_export

    out = account_export("officer@club.org")
    assert out["account"]["email"] == "officer@club.org"
    assert out["legal_acceptances"]
    assert "$2b$" not in json.dumps(out)  # bcrypt hash never exported


# ---- web routes --------------------------------------------------------------


@pytest.fixture
def app(data_dir, monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def test_account_delete_route_requires_password(app, data_dir):
    client = app.test_client()
    client.post(
        "/signup",
        data={"email": "del@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    r = client.post("/account/delete", data={"password": "wrong-password"})
    assert r.status_code == 403
    from mediahub.web.auth import UserStore

    assert UserStore().get("del@club.org") is not None
    r = client.post("/account/delete", data={"password": "twelvechars1"})
    assert r.status_code == 302
    assert UserStore().get("del@club.org") is None


def test_account_export_route(app, data_dir):
    client = app.test_client()
    client.post(
        "/signup",
        data={"email": "ex@club.org", "password": "twelvechars1", "accept_terms": "1"},
    )
    r = client.get("/account/export")
    assert r.status_code == 200
    assert r.headers["Content-Disposition"].startswith("attachment")
    assert r.get_json()["account"]["email"] == "ex@club.org"


def test_run_delete_route_triggers_cascade(app, data_dir, monkeypatch):
    _seed_run(data_dir)
    _, per_run, _ = _seed_pb_caches(data_dir)
    # RUNS_DIR is frozen at module import; point it at this test's tree.
    from mediahub.web import web as webmod

    monkeypatch.setattr(webmod, "RUNS_DIR", data_dir / "runs_v4")
    # Register the run in the DB so the delete route can resolve ownership.
    conn = webmod._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, status, profile_id) VALUES (?,?,?)",
        ("run1", "done", ""),
    )
    conn.commit()
    conn.close()
    client = app.test_client()
    r = client.post("/privacy/run/run1/delete")
    assert r.status_code == 302
    assert not (data_dir / "runs_v4" / "run1.json").exists()
    assert not per_run.exists()
