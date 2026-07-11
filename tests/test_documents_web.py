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
                {
                    "achievement": {
                        "type": "pb_confirmed",
                        "swimmer_name": "Ada Lovelace",
                        "swimmer_id": "s1",
                        "event": "100m Free",
                        "swim_id": "a1",
                        "raw_facts": {"drop_seconds": 1.2},
                    }
                },
                {
                    "achievement": {
                        "type": "medal_gold",
                        "swimmer_name": "Ada Lovelace",
                        "swimmer_id": "s1",
                        "swim_id": "a1",
                    }
                },
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
            Section(
                blocks=[m.heading("The year", 2), m.bullet_list(["120 members"])], notes="Numbers."
            ),
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


def _insert_db_run(wm, run_id, profile_id, meet, *, n_achievements=3):
    """Seed a 'done' row in the runs DB table — the Documents/Sites source
    pickers list runs from there (via _doc_recent_runs), not from runs_v4 JSON."""
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES (?, ?, ?, 'done', ?, ?, ?, 10, 0, 0, ?, NULL)",
        (
            run_id,
            "2026-06-10T09:00:00Z",
            "2026-06-10T09:00:00Z",
            profile_id,
            meet,
            f"{meet[:40]}.pdf",
            n_achievements,
        ),
    )
    conn.commit()
    conn.close()


_BANNER_TITLE = (
    "Sussex County ASA- LC Champ - Organization License "
    "HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1"
)


def test_source_picker_cleans_stale_banner_title(app_env):
    """QA-008: a run parsed before the QA-002 fix stored the HY-TEK banner as
    its meet name. The Documents source picker must show the cleaned name."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    _insert_db_run(wm, "banner-1", "club-a", _BANNER_TITLE)
    body = c.get("/documents").get_data(as_text=True)
    assert "Sussex County ASA- LC Champ" in body
    assert "Organization License" not in body
    assert "HY-TEK" not in body
    assert "MEET MANAGER" not in body
    assert _BANNER_TITLE not in body


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
    r = c.post(
        "/api/documents/generate",
        json={"format": "meet_programme", "scope": "meet", "run_id": "r1", "with_ai": False},
    )
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

    spec = {
        "doc_id": doc_id,
        "title": "Renamed",
        "kind": "document",
        "sections": [{"blocks": [{"kind": "text", "props": {"text": "hi"}}]}],
    }
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

    src = DocumentSpec(
        title="Imported", sections=[Section(blocks=[m.heading("Hello", 1), m.text("World")])]
    )
    path = tmp_path / "x.docx"
    export.document_docx(src, path)
    data = path.read_bytes()
    r = c.post(
        "/api/documents/import",
        data={"file": (io.BytesIO(data), "x.docx")},
        content_type="multipart/form-data",
    )
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
# CSRF: the state-changing document controls must work under production CSRF
# enforcement. The multipart uploads (import / merge / images-to-pdf) can't use
# the JSON-content-type exemption, so they carry the token in an X-CSRF-Token
# header; the empty delete POST uses the JSON content-type exemption. These
# tests run with CSRF ENFORCED (the default TESTING mode disables it, which is
# why the earlier tests didn't catch the controls 403ing in production).
# ---------------------------------------------------------------------------


def _csrf_from_home(client):
    import re

    html = client.get("/documents").get_data(as_text=True)
    m = re.search(r'const CSRF = "([0-9a-f]+)"', html)
    assert m, "documents home must embed the CSRF token for its multipart uploads"
    return m.group(1)


def test_home_embeds_csrf_token_for_uploads(app_env):
    app, wm, _ = app_env
    app.config["ENFORCE_CSRF"] = True
    c = app.test_client()
    _login(c)
    html = c.get("/documents").get_data(as_text=True)
    # the token is wired into the multipart fetches, not left as a placeholder
    assert "__CSRF__" not in html
    assert "X-CSRF-Token" in html


def test_images_to_pdf_needs_csrf_token(app_env):
    app, wm, tmp_path = app_env
    app.config["ENFORCE_CSRF"] = True
    c = app.test_client()
    _login(c)
    from PIL import Image
    import io as _io

    def _png():
        b = _io.BytesIO()
        Image.new("RGB", (40, 30), "red").save(b, "PNG")
        b.seek(0)
        return b

    # no token -> blocked (guard intact)
    r0 = c.post(
        "/api/documents/tools/images-to-pdf",
        data={"files": (_png(), "a.png")},
        content_type="multipart/form-data",
    )
    assert r0.status_code == 403 and r0.get_json()["error"] == "csrf"

    # with the page's token -> succeeds
    tok = _csrf_from_home(c)
    r1 = c.post(
        "/api/documents/tools/images-to-pdf",
        data={"files": (_png(), "a.png")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": tok},
    )
    assert r1.status_code == 200 and r1.data[:4] == b"%PDF"


def test_import_needs_csrf_token(app_env):
    app, wm, tmp_path = app_env
    app.config["ENFORCE_CSRF"] = True
    c = app.test_client()
    _login(c)
    from mediahub.documents import export, models as mdl
    from mediahub.documents.models import DocumentSpec, Section

    src = DocumentSpec(title="I", sections=[Section(blocks=[mdl.heading("Hi", 1)])])
    path = tmp_path / "x.docx"
    export.document_docx(src, path)
    data = path.read_bytes()

    r0 = c.post(
        "/api/documents/import",
        data={"file": (io.BytesIO(data), "x.docx")},
        content_type="multipart/form-data",
    )
    assert r0.status_code == 403 and r0.get_json()["error"] == "csrf"

    tok = _csrf_from_home(c)
    r1 = c.post(
        "/api/documents/import",
        data={"file": (io.BytesIO(data), "x.docx")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": tok},
    )
    assert r1.get_json()["ok"]


def test_delete_document_works_under_csrf(app_env):
    app, wm, _ = app_env
    app.config["ENFORCE_CSRF"] = True
    c = app.test_client()
    _login(c)
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]
    # the delDoc() control posts with a JSON content-type (CSRF-exempt); a bare
    # POST with neither token nor JSON content-type would 403 in production.
    r_bad = c.post(f"/api/documents/{doc_id}/delete")
    assert r_bad.status_code == 403
    r_ok = c.post(f"/api/documents/{doc_id}/delete", headers={"Content-Type": "application/json"})
    assert r_ok.get_json()["ok"]


# ---------------------------------------------------------------------------
# Robustness: malformed spec / leaked paths / double-submit / kiosk cadence
# ---------------------------------------------------------------------------


def test_save_malformed_spec_does_not_500_and_stays_viewable(app_env):
    """A hand-edited spec (advanced JSON editor) with wrong-typed fields must not
    500 on save or on the subsequent view — it loads with the bad fields defaulted."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]
    for bad in (
        {"doc_id": doc_id, "title": "x", "meta": [1, 2], "sections": []},
        {"doc_id": doc_id, "title": "x", "sections": 5},
        {
            "doc_id": doc_id,
            "title": "x",
            "sections": [{"blocks": [{"kind": "text", "props": [1]}]}],
        },
        {"doc_id": doc_id, "title": "x", "source_refs": 9},
    ):
        r = c.post(f"/api/documents/{doc_id}/save", json={"spec": bad})
        assert r.status_code == 200 and r.get_json()["ok"], bad
        assert c.get(f"/documents/{doc_id}").status_code == 200


def test_tool_error_detail_does_not_leak_server_path(app_env):
    """A failed PDF-tool op must not echo the server's internal temp path."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    r = c.post(
        "/api/documents/tools/images-to-pdf",
        data={"files": (io.BytesIO(b"not an image"), "a.png")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422
    body = r.get_data(as_text=True)
    # no absolute path, no temp-file naming scheme leaked to the client
    assert "/tmp" not in body and "/img_" not in body and ".png'" not in body


def test_home_generate_has_reentrancy_guard(app_env):
    """The Generate control guards against a double-click making a duplicate doc
    (and double-charging the metered AI quota)."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    html = c.get("/documents").get_data(as_text=True)
    assert "_genBusy" in html


def test_audience_autoplay_honours_configured_cadence(app_env):
    """The kiosk audience view advances at the session's autoplay_seconds, not a
    hardcoded interval (regresses the dead autoplay_seconds field)."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_deck()
    from mediahub.documents import presenter as _pres

    sess = _pres.create_session(spec.doc_id, len(spec.sections), owner="club-a")
    body = c.get(f"/present/{sess.session_id}").get_data(as_text=True)
    assert "autoplay_seconds" in body
    assert ", 6000)" not in body  # no hardcoded 6s interval


def test_home_file_inputs_have_accessible_labels(app_env):
    """Each unlabelled file input carries an aria-label (accessible name)."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    html = c.get("/documents").get_data(as_text=True)
    assert html.count("aria-label=") >= 3  # import / merge / images inputs


def test_document_view_iframe_has_title(app_env):
    """The PDF-preview iframe has a title for screen readers."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    doc_id = c.post("/api/documents/generate", json={"format": "blank"}).get_json()["doc_id"]
    html = c.get(f"/documents/{doc_id}").get_data(as_text=True)
    assert 'title="Document preview"' in html


def test_present_console_reflects_toggle_state(app_env):
    """The Blackout/Autoplay toggles expose their on/off state (aria-pressed +
    a visible label) so the presenter can tell whether the room is blacked out
    or auto-advancing."""
    app, wm, _ = app_env
    c = app.test_client()
    _login(c)
    spec = _save_deck()
    html = c.get(f"/documents/{spec.doc_id}/present").get_data(as_text=True)
    assert 'id="btn-blackout"' in html and 'id="btn-autoplay"' in html
    assert "aria-pressed" in html and "toggleState(" in html


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
    doc_id = c.post(
        "/api/documents/generate",
        json={"format": "meet_programme", "scope": "meet", "run_id": "r1", "with_ai": False},
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
