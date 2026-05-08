"""V8.1 issue 6 — two-step upload flow (and V8.2 issue 3 hardening).

Tests:
  - POST /upload (file only) redirects to /upload/configure?run_id=...
    The single-step / club_filter-up-front path was removed in V8.2.
  - GET /upload/configure shows a populated dropdown of clubs from the file
    (not from disk) — for the Manchester PDF this includes the Manchester clubs.
  - POST /upload/configure with a picked club + branding kicks off the
    pipeline and redirects to /runs/<run_id>.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SAMPLE_PDF = _ROOT / "sample_data" / "MISM-2024-Results.pdf"


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Boot the Flask app inside a tmp cwd so file writes are scoped."""
    monkeypatch.chdir(tmp_path)
    # Re-create runs/data dirs the app expects.
    (tmp_path / "runs_v4").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(exist_ok=True)

    import mediahub.web.web as web_module
    # Repoint module-level paths that were captured at import time.
    web_module.RUNS_DIR = tmp_path / "runs_v4"
    web_module.UPLOADS_DIR = tmp_path / "uploads_v4"
    a = web_module.create_app()
    a.config["TESTING"] = True
    return a


def test_upload_without_club_filter_redirects_to_configure(app):
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    c = app.test_client()
    data = {
        "file": (io.BytesIO(_SAMPLE_PDF.read_bytes()), "MISM-2024-Results.pdf"),
        # No club_filter
    }
    rv = c.post("/upload", data=data, content_type="multipart/form-data",
                follow_redirects=False)
    assert rv.status_code in (302, 303), rv.data[:300]
    loc = rv.headers["Location"]
    assert "/upload/configure" in loc
    assert "run_id=" in loc


def test_configure_lists_manchester_clubs(app):
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    c = app.test_client()
    rv = c.post("/upload", data={
        "file": (io.BytesIO(_SAMPLE_PDF.read_bytes()), "MISM-2024-Results.pdf"),
    }, content_type="multipart/form-data", follow_redirects=False)
    assert rv.status_code in (302, 303)
    loc = rv.headers["Location"]

    # Extract run_id and GET /upload/configure
    run_id = loc.split("run_id=")[-1]
    rv2 = c.get(f"/upload/configure?run_id={run_id}")
    assert rv2.status_code == 200, rv2.data[:300]
    body = rv2.data.decode("utf-8", errors="ignore").lower()
    # Manchester clubs should appear among the parsed list.
    assert "manchester" in body, "no manchester clubs in configure dropdown"
    # The select element should exist.
    assert '<select name="club_filter"' in body


def test_configure_post_kicks_off_pipeline_for_picked_club(app, monkeypatch):
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    # Stub the heavy pipeline so this test is fast and offline.
    import mediahub.web.web as web_module

    started: dict = {}

    def _fake_start_run(file_bytes, file_name, profile_id, use_cache, fetch_pbs,
                        club_filter=None):
        started["club_filter"] = club_filter
        started["filename"] = file_name
        started["profile_id"] = profile_id
        return "fakerun123"

    monkeypatch.setattr(web_module, "_start_run", _fake_start_run)

    c = app.test_client()
    rv = c.post("/upload", data={
        "file": (io.BytesIO(_SAMPLE_PDF.read_bytes()), "MISM-2024-Results.pdf"),
    }, content_type="multipart/form-data", follow_redirects=False)
    run_id = rv.headers["Location"].split("run_id=")[-1]

    # Pick a club that exists in the parsed list. We'll pull the first
    # from the meta JSON the configure step wrote.
    import json as _json
    meta = _json.loads((web_module.RUNS_DIR / run_id / "upload_meta.json").read_text())
    clubs = meta.get("clubs") or []
    assert clubs, "configure step did not produce any clubs"
    # Prefer a Manchester club for verisimilitude.
    pick = next((c for c in clubs if "manchester" in c.lower()), clubs[0])

    # V8.2: branding is required — supply a primary colour to satisfy validation.
    rv2 = c.post("/upload/configure", data={
        "run_id": run_id,
        "club_filter": pick,
        "primary_colour": "#A30D2D",
    }, content_type="multipart/form-data", follow_redirects=False)
    assert rv2.status_code in (302, 303), rv2.data[:300]
    assert "/runs/fakerun123" in rv2.headers["Location"]
    assert started["club_filter"] == pick


def test_upload_form_has_no_club_or_brand_fields(app):
    """V8.2 issue 3: /upload GET shows file input + submit only."""
    c = app.test_client()
    rv = c.get("/upload")
    assert rv.status_code == 200
    body = rv.data.decode("utf-8", errors="ignore")
    # Single file input + submit, no extra fields.
    assert 'name="file"' in body
    assert 'name="club_filter"' not in body
    assert 'name="profile_id"' not in body
    assert 'name="club_logo"' not in body
    assert 'name="primary_colour"' not in body


def test_configure_requires_branding(app, monkeypatch):
    """V8.2 issue 5: must upload logo or pick a colour before submit."""
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    import mediahub.web.web as web_module

    monkeypatch.setattr(web_module, "_start_run", lambda *a, **kw: "shouldnotrun")

    c = app.test_client()
    rv = c.post("/upload", data={
        "file": (io.BytesIO(_SAMPLE_PDF.read_bytes()), "MISM-2024-Results.pdf"),
    }, content_type="multipart/form-data", follow_redirects=False)
    run_id = rv.headers["Location"].split("run_id=")[-1]
    import json as _json
    meta = _json.loads((web_module.RUNS_DIR / run_id / "upload_meta.json").read_text())
    pick = (meta.get("clubs") or ["Anyclub"])[0]

    rv2 = c.post("/upload/configure", data={
        "run_id": run_id,
        "club_filter": pick,
        # No logo, no colours
        "primary_colour": "",
        "secondary_colour": "",
        "accent_colour": "",
    }, content_type="multipart/form-data", follow_redirects=False)
    # Should NOT redirect; it should re-render the configure form with an error.
    assert rv2.status_code == 200
    assert b"upload a logo or pick at least one brand colour" in rv2.data
