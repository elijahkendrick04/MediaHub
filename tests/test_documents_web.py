"""Document engine (roadmap 1.15) — build 5: the web surface."""

from __future__ import annotations

import importlib
import io
import json

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.replace("-", " ").title()))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_run(tmp_path, run_id="r1", profile_id="club-a"):
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "canonical_meet": {
            "name": "County Champs",
            "swimmers": {"s1": {}, "s2": {}},
            "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}],
        },
        "recognition_report": {
            "meet_name": "County Champs",
            "meet_date": "June 2026",
            "n_swims_analysed": 12,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Ada Lovelace", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.2}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Ada Lovelace", "swimmer_id": "s1", "swim_id": "a1"}},
            ],
        },
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
    return run_id


def _save_deck(pid="club-a", title="AGM 2026"):
    from mediahub.documents import models as m
    from mediahub.documents.models import DocumentSpec, Section
    from mediahub.documents.store import save_document

    spec = DocumentSpec(
        title=title,
        kind="deck",
        doc_format="agm_deck",
        geometry="slide_16_9",
        brand_profile_id=pid,
        sections=[
            Section(layout="cover", blocks=[m.heading(title, 1)], notes="Welcome."),
            Section(blocks=[m.heading("The year", 2), m.bullet_list(["120 members"])], notes="Numbers."),
            Section(layout="closing", blocks=[m.heading("Thanks", 1)]),
        ],
    )
    save_document(pid, spec)
    return spec


# ---------------------------------------------------------------------------
# Home + generate
# ---------------------------------------------------------------------------


def test_home_requires_org(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    r = c.get("/documents")
    assert r.status_code == 200
    assert b"organisation" in r.data.lower()


def test_home_signed_in(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.get("/documents")
    assert r.status_code == 200
    assert b"Documents" in r.data
    assert b"Season report" in r.data


def test_generate_blank_then_view(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post("/api/documents/generate", json={"format": "blank"})
    j = r.get_json()
    assert j["ok"] and j["doc_id"]
    v = c.get(j["url"])
    assert v.status_code == 200


def test_generate_meet_from_seeded_run(app_env):
    app, wm, tmp_path = app_env
    c = app.test_client()
    _login(c)
    _seed_run(tmp_path)
    r = c.post("/api/documents/generate",
               json={"format": "meet_programme", "scope": "meet", "run_id": "r1", "with_ai": False})
    j = r.get_json()
    assert j["ok"], j
    v = c.get(j["url"])
    assert v.status_code == 200
    assert b"County Champs" in v.data


def test_generate_meet_without_run_id_400(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post("/api/documents/generate", json={"format": "meet_programme", "scope": "meet"})
    assert r.status_code == 400


def test_generate_season_no_data(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post("/api/documents/generate", json={"format": "season_report", "scope": "season"})
    j = r.get_json()
    assert j["ok"] is False and j["error"] == "no_data"


def test_generate_requires_sign_in(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    r = c.post("/api/documents/generate", json={"format": "blank"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Save / delete / multi-tenant
# ---------------------------------------------------------------------------


def test_save_and_delete(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]

    spec = {"doc_id": doc_id, "title": "Renamed", "kind": "document",
            "sections": [{"blocks": [{"kind": "text", "props": {"text": "hi"}}]}]}
    r = c.post(f"/api/documents/{doc_id}/save", json={"spec": spec})
    assert r.get_json()["ok"]
    assert b"Renamed" in c.get(f"/documents/{doc_id}").data

    assert c.post(f"/api/documents/{doc_id}/delete").get_json()["ok"]
    assert c.get(f"/documents/{doc_id}").status_code == 404


def test_multi_tenant_isolation(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c, "club-a")
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]
    # switch to another org
    _login(c, "club-b")
    assert c.get(f"/documents/{doc_id}").status_code == 404
    assert c.get(f"/api/documents/{doc_id}/pdf").status_code == 404


# ---------------------------------------------------------------------------
# Import + PDF tools
# ---------------------------------------------------------------------------


def test_import_docx(app_env):
    app, wm, tmp_path = app_env
    c = app.test_client()
    _login(c)
    from mediahub.documents import export, models as m
    from mediahub.documents.models import DocumentSpec, Section

    src = DocumentSpec(title="Imported", sections=[Section(blocks=[m.heading("Hello", 1), m.text("World")])])
    path = tmp_path / "x.docx"
    export.document_docx(src, path)
    data = path.read_bytes()
    r = c.post("/api/documents/import",
               data={"file": (io.BytesIO(data), "x.docx")}, content_type="multipart/form-data")
    j = r.get_json()
    assert j["ok"] and j["doc_id"]


def test_merge_pdfs_tool(app_env):
    app, wm, tmp_path = app_env
    c = app.test_client()
    _login(c)
    from PIL import Image
    from mediahub.documents.pdf_utils import images_to_pdf

    pdfs = []
    for i, col in enumerate(["red", "blue"]):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (100, 80), col).save(p)
        out = tmp_path / f"p{i}.pdf"
        images_to_pdf([p], out)
        pdfs.append(out.read_bytes())
    r = c.post(
        "/api/documents/tools/merge",
        data={"files": [(io.BytesIO(pdfs[0]), "a.pdf"), (io.BytesIO(pdfs[1]), "b.pdf")]},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Presenter surface
# ---------------------------------------------------------------------------


def test_present_non_deck_is_rejected(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]
    r = c.get(f"/documents/{doc_id}/present")
    assert r.status_code == 404  # recovery page (not a deck)


def test_present_deck_creates_session(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_deck()
    r = c.get(f"/documents/{spec.doc_id}/present")
    assert r.status_code == 200
    assert b"Phone remote" in r.data
    # a live session now exists
    from mediahub.documents import presenter as _pres

    assert any(True for _ in _pres._iter_live())


def test_presenter_state_action_and_owner_gate(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c, "club-a")
    spec = _save_deck("club-a")
    from mediahub.documents import presenter as _pres

    sess = _pres.create_session(spec.doc_id, len(spec.sections), owner="club-a")

    # state is public by capability
    st = c.get(f"/api/present/{sess.session_id}/state").get_json()
    assert st["total"] == 3 and st["current"] == 0

    # owner can drive
    r = c.post(f"/api/present/{sess.session_id}/action", json={"action": "next"})
    assert r.get_json()["state"]["current"] == 1

    # a different org cannot drive
    _login(c, "club-b")
    r2 = c.post(f"/api/present/{sess.session_id}/action", json={"action": "next"})
    assert r2.status_code == 403


def test_audience_view_and_remote(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_deck()
    from mediahub.documents import presenter as _pres

    sess = _pres.create_session(spec.doc_id, len(spec.sections), owner="club-a")

    # audience view (capability = session id), no sign-in needed
    aud = app.test_client()
    r = aud.get(f"/present/{sess.session_id}")
    assert r.status_code == 200 and b"<html" in r.data.lower()

    # remote by code drives without sign-in
    rc = aud.get(f"/remote/{sess.pairing_code}")
    assert rc.status_code == 200
    act = aud.post(f"/api/remote/{sess.pairing_code}/action", json={"action": "next"})
    assert act.get_json()["state"]["current"] == 1
    # bad code → recovery
    assert aud.get("/remote/ZZZZZZ").status_code == 404


def test_remote_landing(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    r = c.get("/remote")
    assert r.status_code == 200
    assert b"code" in r.data.lower()


# ---------------------------------------------------------------------------
# Rendered outputs (need Chromium; skip cleanly otherwise)
# ---------------------------------------------------------------------------


def _skip_if_no_chromium(resp):
    if resp.status_code == 503:
        try:
            detail = (resp.get_json() or {}).get("detail", "")
        except Exception:
            detail = ""
        if any(t in detail.lower() for t in ("playwright", "chromium", "browser", "executable")):
            pytest.skip(f"needs Chromium: {detail}")


def test_pdf_download(app_env):
    app, wm, tmp_path = app_env
    c = app.test_client()
    _login(c)
    _seed_run(tmp_path)
    doc_id = c.post("/api/documents/generate",
                    json={"format": "meet_programme", "scope": "meet", "run_id": "r1", "with_ai": False}
                    ).get_json()["doc_id"]
    r = c.get(f"/api/documents/{doc_id}/pdf")
    _skip_if_no_chromium(r)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:4] == b"%PDF"


def test_slide_png_by_session(app_env):
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_deck()
    from mediahub.documents import presenter as _pres

    sess = _pres.create_session(spec.doc_id, len(spec.sections), owner="club-a")
    r = c.get(f"/api/present/{sess.session_id}/slide/0.png")
    _skip_if_no_chromium(r)
    assert r.status_code == 200
    assert r.mimetype == "image/png"
