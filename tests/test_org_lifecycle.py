"""PC.13 — whole-org deletion cascade + org takeout ZIP.

Deletion must verifiably remove the organisation's data from every store
under DATA_DIR while a second org's data stays byte-for-byte intact
(ADR-0003/0014 isolation invariants); the takeout ZIP must contain the
org's stores and nothing cross-tenant.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest


def _seed_run(runs_dir, run_id, profile_id, swimmer):
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "meet_name": "Test Gala",
                "cards": [{"card_id": "c1", "name": swimmer, "caption": f"{swimmer} swam well"}],
            }
        )
    )
    (runs_dir / f"{run_id}__workflow.json").write_text(json.dumps({"c1": {"status": "approved"}}))
    side = runs_dir / run_id
    side.mkdir(exist_ok=True)
    (side / "c1.png").write_bytes(b"\x89PNG fake")


@pytest.fixture
def org_world(web_module, tmp_path, monkeypatch):
    wm = web_module

    import mediahub.media_library.store as mls

    from mediahub.web.club_profile import ClubProfile, save_profile

    for pid, name, token in (
        ("org-a", "Org A SC", "wall-token-a"),
        ("org-b", "Org B SC", "wall-token-b"),
    ):
        save_profile(
            ClubProfile(
                profile_id=pid,
                display_name=name,
                public_wall_enabled=True,
                public_wall_token=token,
            )
        )

    runs_dir = tmp_path / "runs_v4"
    _seed_run(runs_dir, "run-a-1", "org-a", "Alice Smith")
    _seed_run(runs_dir, "run-b-1", "org-b", "Beth Brook")

    app = wm.create_app()
    app.config["TESTING"] = True
    conn = wm._db()
    for run_id, pid in (("run-a-1", "org-a"), ("run-b-1", "org-b")):
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
            "VALUES (?, datetime('now'), 'done', ?, 'Test Gala', 'gala.hy3')",
            (run_id, pid),
        )
    conn.commit()
    conn.close()

    # Media library on the same tmp DATA_DIR db + uploads tree; pin the
    # process-wide singleton so the routes hit the same store.
    store = mls.MediaLibraryStore(
        db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads_v4" / "media_library"
    )
    monkeypatch.setattr(mls, "_default_store", store)
    from mediahub.media_library.models import MediaAsset

    assets = {}
    for pid, fname in (("org-a", "a.jpg"), ("org-b", "b.jpg")):
        path = store.store_blob(b"fake-image-bytes", fname, profile_id=pid)
        asset = store.save(
            MediaAsset(id=f"asset-{pid}", filename=fname, path=str(path), profile_id=pid)
        )
        assets[pid] = asset

    # Consent + athletes for both orgs.
    from mediahub.athletes.registry import get_or_create
    from mediahub.safeguarding.consent import set_consent

    for pid, name in (("org-a", "Alice Smith"), ("org-b", "Beth Brook")):
        rec = get_or_create(pid, name, source="manual")
        set_consent(pid, rec.athlete_id, "initials_only", actor="test")

    # Sponsor exposure + autonomy audit ledgers.
    for pid in ("org-a", "org-b"):
        sp = tmp_path / "sponsors" / f"{pid}__exposure.jsonl"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"sponsor": "Acme", "run_id": f"run-{pid[-1]}-1"}) + "\n")
        au = tmp_path / "autonomy_audit" / f"{pid}.jsonl"
        au.parent.mkdir(parents=True, exist_ok=True)
        au.write_text(json.dumps({"org": pid, "kind": "test"}) + "\n")

    # Memberships: one active owner each.
    from mediahub.web.tenancy import MembershipStore, ROLE_OWNER, STATUS_ACTIVE

    ms = MembershipStore()
    ms.add("owner-a@club.org", "org-a", role=ROLE_OWNER, status=STATUS_ACTIVE)
    ms.add("owner-b@club.org", "org-b", role=ROLE_OWNER, status=STATUS_ACTIVE)

    # Accounts for the owners (password re-verify on delete).
    from mediahub.web.auth import UserStore

    UserStore().create("owner-a@club.org", "password-a-12345")
    UserStore().create("owner-b@club.org", "password-b-12345")

    return {"app": app, "wm": wm, "tmp": tmp_path, "store": store}


def _signin(client, email):
    import mediahub.web.legal as legal

    with client.session_transaction() as s:
        s["user_email"] = email
        s["terms_ok_version"] = legal.TERMS_VERSION
        s["active_profile_id"] = email.replace("owner-", "org-").split("@")[0]


# ---- the cascade ----------------------------------------------------------


def test_delete_org_cascades_everywhere_and_isolates(org_world):
    tmp, wm, store = org_world["tmp"], org_world["wm"], org_world["store"]
    from mediahub.privacy import delete_org

    report = delete_org("org-a", delete_run=wm._delete_run, media_store=store)

    # Runs: JSON, sidecar dir, workflow file and DB row all gone.
    assert report["runs_deleted"] == 1
    assert not (tmp / "runs_v4" / "run-a-1.json").exists()
    assert not (tmp / "runs_v4" / "run-a-1").exists()
    assert not (tmp / "runs_v4" / "run-a-1__workflow.json").exists()
    conn = wm._db()
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE profile_id='org-a'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs WHERE profile_id='org-b'").fetchone()[0] == 1
    # Org-keyed DB rows gone; org-b rows intact.
    for table in ("athletes", "athlete_consent"):
        assert (
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE profile_id='org-a'").fetchone()[0]
            == 0
        ), table
        assert (
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE profile_id='org-b'").fetchone()[0]
            == 1
        ), table
    conn.close()

    # Media: rows + blobs gone for org-a, intact for org-b.
    assert report["media_assets_deleted"] == 1
    assert store.list(profile_id="org-a") == []
    assert len(store.list(profile_id="org-b")) == 1
    assert not (tmp / "uploads_v4" / "media_library" / "org-a").exists()
    assert (tmp / "uploads_v4" / "media_library" / "org-b").exists()

    # Ledgers and profile.
    assert not (tmp / "sponsors" / "org-a__exposure.jsonl").exists()
    assert (tmp / "sponsors" / "org-b__exposure.jsonl").exists()
    assert not (tmp / "autonomy_audit" / "org-a.jsonl").exists()
    assert (tmp / "autonomy_audit" / "org-b.jsonl").exists()
    assert report["profile_deleted"] is True
    assert not (tmp / "club_profiles" / "org-a.json").exists()

    # Wall token dead structurally; org-b's wall still resolves.
    from mediahub.web.public_wall import profile_for_token

    assert profile_for_token("wall-token-a") is None
    assert profile_for_token("wall-token-b") is not None

    # Memberships: org-a rows physically gone, org-b intact.
    from mediahub.web.tenancy import MembershipStore

    ms = MembershipStore()
    assert report["memberships_deleted"] == 1
    assert ms.get("owner-a@club.org", "org-a") is None
    assert ms.is_active_owner("owner-b@club.org", "org-b")

    # The retained list is honest about Stripe + acceptance evidence.
    assert any("Stripe" in r for r in report["retained"])


# ---- the takeout ZIP -------------------------------------------------------


def test_org_export_zip_contents_are_tenant_scoped(org_world, tmp_path):
    store = org_world["store"]
    from mediahub.privacy import org_export_zip

    out = tmp_path / "takeout.zip"
    manifest = org_export_zip("org-a", out, media_store=store)
    assert manifest["runs"] == 1
    assert manifest["media_assets"] == 1
    assert manifest["athletes"] == 1

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        for expected in (
            "profile.json",
            "runs/run-a-1.json",
            "runs/run-a-1__workflow.json",
            "media_assets.json",
            "consent_registry.csv",
            "athletes.json",
            "club_records.json",
            "corrections.json",
            "sponsor_exposure.jsonl",
            "audit_log.jsonl",
            "memberships.json",
            "README.txt",
            "manifest.json",
        ):
            assert expected in names, f"takeout missing {expected}: {sorted(names)}"
        # The media blob rides along (stored as media/<id>_<filename>).
        assert any(n.startswith("media/") and n.endswith("a.jpg") for n in names)
        # Nothing cross-tenant.
        assert "runs/run-b-1.json" not in names
        consent_csv = zf.read("consent_registry.csv").decode()
        assert "Alice Smith" in consent_csv
        assert "Beth Brook" not in consent_csv
        profile = json.loads(zf.read("profile.json"))
        assert profile["profile_id"] == "org-a"
        members = json.loads(zf.read("memberships.json"))
        assert {m["email"] for m in members} == {"owner-a@club.org"}


# ---- routes ----------------------------------------------------------------


def test_export_route_owner_gets_zip(org_world):
    c = org_world["app"].test_client()
    _signin(c, "owner-a@club.org")
    r = c.get("/organisation/export")
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.data)) as zf:
        assert "profile.json" in zf.namelist()


def test_export_route_denied_for_non_member(org_world):
    c = org_world["app"].test_client()
    # owner-b signed in but pinned to org-a (forged pin): the active-profile
    # choke point self-heals the pin (PC.3) → redirected to sign-in, never
    # the handler.
    import mediahub.web.legal as legal

    with c.session_transaction() as s:
        s["user_email"] = "owner-b@club.org"
        s["terms_ok_version"] = legal.TERMS_VERSION
        s["active_profile_id"] = "org-a"
    assert c.get("/organisation/export").status_code == 302


def test_export_and_delete_denied_for_member_who_is_not_owner(org_world):
    from mediahub.web.auth import UserStore
    from mediahub.web.tenancy import MembershipStore, ROLE_MEMBER, STATUS_ACTIVE

    UserStore().create("member-a@club.org", "password-m-12345")
    MembershipStore().add("member-a@club.org", "org-a", role=ROLE_MEMBER, status=STATUS_ACTIVE)

    c = org_world["app"].test_client()
    import mediahub.web.legal as legal

    with c.session_transaction() as s:
        s["user_email"] = "member-a@club.org"
        s["terms_ok_version"] = legal.TERMS_VERSION
        s["active_profile_id"] = "org-a"
    # A plain member may use the workspace but not take it out or delete it.
    assert c.get("/organisation/export").status_code == 404
    r = c.post(
        "/organisation/delete",
        data={"confirm_profile_id": "org-a", "password": "password-m-12345"},
    )
    assert r.status_code == 404
    assert (org_world["tmp"] / "club_profiles" / "org-a.json").exists()


def test_delete_route_wrong_confirmation_deletes_nothing(org_world):
    tmp = org_world["tmp"]
    c = org_world["app"].test_client()
    _signin(c, "owner-a@club.org")
    r = c.post(
        "/organisation/delete",
        data={"confirm_profile_id": "wrong", "password": "password-a-12345"},
    )
    assert r.status_code == 400
    assert (tmp / "club_profiles" / "org-a.json").exists()


def test_delete_route_wrong_password_deletes_nothing(org_world):
    tmp = org_world["tmp"]
    c = org_world["app"].test_client()
    _signin(c, "owner-a@club.org")
    r = c.post(
        "/organisation/delete",
        data={"confirm_profile_id": "org-a", "password": "nope-nope-nope"},
    )
    assert r.status_code == 403
    assert (tmp / "club_profiles" / "org-a.json").exists()


def test_delete_route_end_to_end(org_world):
    tmp = org_world["tmp"]
    c = org_world["app"].test_client()
    _signin(c, "owner-a@club.org")
    r = c.post(
        "/organisation/delete",
        data={"confirm_profile_id": "org-a", "password": "password-a-12345"},
    )
    assert r.status_code == 200
    assert "Organisation" in r.get_data(as_text=True)
    assert not (tmp / "club_profiles" / "org-a.json").exists()
    assert not (tmp / "runs_v4" / "run-a-1.json").exists()
    # org-b untouched.
    assert (tmp / "club_profiles" / "org-b.json").exists()
    assert (tmp / "runs_v4" / "run-b-1.json").exists()
    # The session pin is gone.
    with c.session_transaction() as s:
        assert "active_profile_id" not in s
