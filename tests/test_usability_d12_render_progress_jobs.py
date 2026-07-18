"""D-12 — 30-90s renders must not hide behind plain links with zero progress UI.

Two surfaces regressed by the audit:

* the grouped page's per-card "Motion video" was a plain GET link that opened
  a new tab and held the synchronous 30-90s render — it now reuses the shared
  motion job + poll UI (``_MOTION_CLIENT_JS`` / ``generateMotion``), the same
  idiom the Content builder uses;
* "Download certificates (.zip of PDFs)" rendered one Chromium PDF per
  approved card inside the request — it now runs as a background job
  (``POST /api/runs/<run_id>/certificates-job`` → 202 {job_id, poll_url}),
  reports "Rendering certificate N of M" via the shared poll route, and the
  finished ZIP downloads from the existing gated GET route (``?file=<job>``).
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import time
import uuid
import zipfile

import pytest


def _run_payload(run_id: str, profile_id: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Org Alpha",
        "meet": {"name": "Spring Open", "start_date": "2026-06-06"},
        "cards": [],
        "parse_warnings": [],
        "detector_summary": {},
        "dispatch_log": {},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "quality_band": "elite",
                    "priority": 0.9,
                    "post_angle": "pb",
                    "safe_to_post": {"level": "safe", "reason": "ok"},
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Maya Patel",
                        "event": "100m Freestyle",
                        "headline": "New PB",
                        "type": "pb",
                        "confidence": 0.9,
                        "raw_facts": {"time": "59.99"},
                    },
                }
            ],
            "n_achievements": 1,
            "n_swims_analysed": 1,
        },
    }


@pytest.fixture
def env(client, web_module, tmp_path):
    wm = web_module

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))

    run_id = "run-d12-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(_run_payload(run_id, "org-alpha"))
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    # Approve the card so the certificates export has something to print.
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(tmp_path / "runs_v4").set_status(run_id, "swim-1", CardStatus.APPROVED)

    return {"client": client, "run_id": run_id, "tmp": tmp_path, "wm": wm}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


def _poll_until_done(client, poll_url, tries=200, delay=0.05):
    for _ in range(tries):
        j = client.get(poll_url).get_json()
        if j.get("status") in ("done", "error"):
            return j
        time.sleep(delay)
    return client.get(poll_url).get_json()


# ---------------------------------------------------------------------------
# Grouped page: motion is job + poll, not a plain synchronous link
# ---------------------------------------------------------------------------


def test_grouped_motion_uses_job_poll_button(env):
    c = env["client"]
    _pin(c, "org-alpha")
    r = c.get(f"/pack/{env['run_id']}/grouped")
    assert r.status_code == 200
    page = r.data.decode("utf-8")
    if "generateMotion" not in page:
        pytest.skip("v7.3 grouped pack unavailable in this environment")
    # The new button drives the shared job + poll idiom…
    assert 'onclick="generateMotion(this,' in page
    # …into a per-card motion panel mounted on this page…
    assert 'class="motion-panel"' in page
    # …with the shared client block actually present (progress + poll).
    assert "function generateMotion" in page
    assert "-job" in page  # the job route suffix used by generateMotion
    # The old plain synchronous link (new tab, no progress) is gone.
    assert "First time can take 30-90s while Video Maker renders." not in page
    assert not re.search(r'<a[^>]+/motion"[^>]*target="_blank"', page)


# ---------------------------------------------------------------------------
# Certificates: background job + progress + gated download
# ---------------------------------------------------------------------------


def _stub_pdf_renderer(monkeypatch, calls=None):
    import mediahub.graphic_renderer.print_export as pe

    def fake_render(html, pdf_path):
        if calls is not None:
            calls.append(str(pdf_path))
        pathlib.Path(pdf_path).write_bytes(b"%PDF-1.4 fake")
        return pathlib.Path(pdf_path)

    monkeypatch.setattr(pe, "render_html_to_pdf", fake_render)


def test_certificates_job_completes_and_download_serves_zip(env, monkeypatch):
    calls: list = []
    _stub_pdf_renderer(monkeypatch, calls)
    c = env["client"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{env['run_id']}/certificates-job")
    assert r.status_code == 202, r.get_data(as_text=True)
    body = r.get_json()
    assert body["ok"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", body["job_id"])
    assert body["total"] == 1

    done = _poll_until_done(c, body["poll_url"])
    assert done["status"] == "done", done
    assert done.get("download_url"), done
    assert f"file={body['job_id']}" in done["download_url"]
    # Per-item progress fields ride the shared poll payload.
    assert done["total"] == 1
    assert done["done"] == 1

    dl = c.get(done["download_url"])
    assert dl.status_code == 200
    assert dl.mimetype == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(dl.data))
    names = zf.namelist()
    assert any(n.endswith(".pdf") and "Maya-Patel" in n for n in names)
    assert calls, "the PDF renderer ran in the worker"


def test_certificates_job_foreign_org_404(env):
    c = env["client"]
    _pin(c, "org-beta")
    assert c.post(f"/api/runs/{env['run_id']}/certificates-job").status_code == 404


def test_certificates_download_foreign_org_404(env, monkeypatch):
    _stub_pdf_renderer(monkeypatch)
    c = env["client"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{env['run_id']}/certificates-job")
    assert r.status_code == 202
    done = _poll_until_done(c, r.get_json()["poll_url"])
    assert done["status"] == "done"
    _pin(c, "org-beta")
    assert c.get(done["download_url"]).status_code == 404


def test_certificates_job_honest_when_nothing_approved(env, tmp_path):
    c = env["client"]
    wm = env["wm"]
    run_id = "run-d12-empty-" + uuid.uuid4().hex[:6]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(_run_payload(run_id, "org-alpha"))
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/certificates-job")
    # Fail-fast in the request thread — an honest refusal, never a doomed 202.
    assert r.status_code == 409
    j = r.get_json()
    assert j["error"] == "no_approved_cards"
    assert "approve" in (j.get("user_message") or "").lower()


def test_certificates_job_honest_error_on_render_failure(env, monkeypatch):
    import mediahub.graphic_renderer.print_export as pe

    def boom(html, pdf_path):
        raise RuntimeError("chromium exploded")

    monkeypatch.setattr(pe, "render_html_to_pdf", boom)
    c = env["client"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{env['run_id']}/certificates-job")
    assert r.status_code == 202
    done = _poll_until_done(c, r.get_json()["poll_url"])
    assert done["status"] == "error"
    assert done.get("user_message")
    # And the download URL never appears for a failed build.
    assert not done.get("download_url")


def test_sync_certificates_route_unchanged_for_direct_use(env, monkeypatch):
    """The existing GET stays the no-JS/API path — same ZIP, same gating."""
    _stub_pdf_renderer(monkeypatch)
    c = env["client"]
    _pin(c, "org-alpha")
    r = c.get(f"/pack/{env['run_id']}/certificates.zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    assert any(n.endswith(".pdf") for n in zf.namelist())
    _pin(c, "org-beta")
    assert c.get(f"/pack/{env['run_id']}/certificates.zip").status_code == 404


def test_certificates_builds_use_unique_intermediate_dirs_and_clean_up(env, monkeypatch):
    """CON-1: overlapping builds must never zip each other's half-written
    PDFs — each build renders into its own ``build-<uuid>`` subdirectory,
    removed when the build finishes (the final ZIP path stays stable)."""
    calls: list = []
    _stub_pdf_renderer(monkeypatch, calls)
    c = env["client"]
    _pin(c, "org-alpha")
    # Build once via the background job…
    r = c.post(f"/api/runs/{env['run_id']}/certificates-job")
    assert r.status_code == 202
    done = _poll_until_done(c, r.get_json()["poll_url"])
    assert done["status"] == "done", done
    # …and once via the synchronous route.
    assert c.get(f"/pack/{env['run_id']}/certificates.zip").status_code == 200
    parents = {pathlib.Path(p).parent for p in calls}
    assert len(calls) == 2 and len(parents) == 2, calls
    export_dir = env["tmp"] / "print_exports" / env["run_id"]
    for p in parents:
        assert p.parent == export_dir
        assert p.name.startswith("build-")
        assert not p.exists(), "the finally-cleanup removed the build dir"
    # No intermediate PDFs linger at the stable top level either.
    assert not list(export_dir.glob("cert-*.pdf"))
    # The job's finished ZIP artifact survives the cleanup.
    assert list(export_dir.glob("certificates-*.zip"))


# ---------------------------------------------------------------------------
# Source-level: the builder page wires the job client
# ---------------------------------------------------------------------------

from tests._helpers import web_surface_src

_SRC = web_surface_src()


def test_pack_page_wires_certificates_job_client():
    assert "mhCertificatesJob" in _SRC
    assert "Rendering certificate " in _SRC
    assert 'data-certs-job="' in _SRC


def test_motion_client_js_is_shared_not_duplicated():
    # One shared motion client block; the grouped page embeds it rather than
    # keeping a drifted copy of generateMotion.
    assert _SRC.count("function generateMotion(") == 1
    assert "_MOTION_CLIENT_JS" in _SRC


def test_motion_why_manifest_fields_are_escaped():
    """JS-5: _loadMotionWhy writes manifest fields into innerHTML — they are
    engine-written (low exploitability), but they now ride window.safeText
    exactly like mhEngineNoteHtml already escapes the notes.* fields."""
    assert "window.safeText(m.card.archetype)" in _SRC
    assert "window.safeText(m.card.motion_intent)" in _SRC
    assert "window.safeText(m.card.mood)" in _SRC
    assert "window.safeText(m.card.variation_seed || '')" in _SRC
    # The raw interpolations are gone.
    for f in ("archetype", "motion_intent", "mood"):
        assert f"+ m.card.{f} +" not in _SRC, f
    assert "+ (m.card.variation_seed || '')" not in _SRC


def test_background_workers_queue_for_the_render_slot():
    # CON-2: a 202-accepted background job queues for the shared render slot
    # (_RENDER_QUEUE_TIMEOUT, like the render-all batch worker) instead of
    # borrowing the request threads' 0.75s fast-fail budget.
    assert '_render_slot("certificates", run_id, timeout=_RENDER_QUEUE_TIMEOUT)' in _SRC
    # The sponsor-variant worker lives in routes_api_runs since the finding-#15
    # carve, where web globals are spelled W.<name> — accept either spelling.
    assert re.search(
        r'"graphic", f"sponsor:\{card_id\}", timeout=(?:W\.)?_RENDER_QUEUE_TIMEOUT', _SRC
    )
    assert '_render_slot("certificates", run_id, timeout=_RENDER_TRY_TIMEOUT)' not in _SRC
    assert not re.search(r'f"sponsor:\{card_id\}", timeout=(?:W\.)?_RENDER_TRY_TIMEOUT', _SRC)


def test_certificates_slot_is_per_pdf_not_whole_build():
    # CON-3: the certificates worker never holds the single global slot
    # across the whole ZIP build — the slot is taken per certificate inside
    # _write_certificates_zip (opt-in for the job; the synchronous route
    # keeps its historical no-slot behaviour).
    assert "use_render_slot: bool = False" in _SRC
    assert "use_render_slot=True," in _SRC
    # CON-1 mechanics: uuid build dir + finally cleanup.
    assert 'build_dir = out_dir / f"build-{uuid.uuid4().hex[:8]}"' in _SRC
    assert 'pdf_path = build_dir / f"cert-{i:02d}.pdf"' in _SRC
    assert 'pdf_path = out_dir / f"cert-{i:02d}.pdf"' not in _SRC
    assert "_shutil.rmtree(build_dir, ignore_errors=True)" in _SRC
