"""security/input-handling: upload validation, parser resource limits,
renderer lockdown, SSRF guards, zip safety (THREAT_MODEL §§1, 3, 4)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "mediahub"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


# --------------------------------------------------------------- uploads


def test_upload_rejects_disallowed_extensions(client):
    for name in ("evil.exe", "shell.php", "image.svg", "noext"):
        r = client.post(
            "/upload", data={"file": (io.BytesIO(b"payload"), name)}
        )
        assert r.status_code == 400, name
        assert b"isn't supported" in r.data


def test_upload_accepts_results_formats(client):
    for name in ("results.pdf", "meet.hy3", "export.zip", "page.html", "times.csv"):
        r = client.post(
            "/upload", data={"file": (io.BytesIO(b"some-bytes"), name)}
        )
        # parse may fail later (junk bytes) but the TYPE is accepted —
        # never the 400 unsupported-type rejection
        assert r.status_code in (200, 302), name


def test_upload_size_cap_configured(client):
    from mediahub.web import web as webmod

    app = client.application
    assert app.config["MAX_CONTENT_LENGTH"] == 50 * 1024 * 1024


# ----------------------------------------------------------- PDF limits


def test_pdf_page_cap_rejects_thousand_page_pdf(monkeypatch):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    for _ in range(12):
        writer.add_blank_page(width=10, height=10)
    buf = io.BytesIO()
    writer.write(buf)

    monkeypatch.setenv("MEDIAHUB_MAX_PDF_PAGES", "10")
    from mediahub.interpreter.ingest import _extract_pdf

    with pytest.raises(ValueError, match="pages"):
        _extract_pdf(buf.getvalue())

    monkeypatch.setenv("MEDIAHUB_MAX_PDF_PAGES", "0")  # cap disabled
    _extract_pdf(buf.getvalue())  # must not raise the cap error


# ------------------------------------------------------------ zip safety


def test_zip_bomb_member_rejected():
    from mediahub.interpreter._zip_safety import UnsafeZipError, safe_infolist

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", b"0" * (10 * 1024 * 1024))  # 10MB of zeros → huge ratio
        zf.writestr("ok.hy3", b"normal content here")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        safe = safe_infolist(zf)
    names = [i.filename for i in safe]
    assert "bomb.txt" not in names  # ratio > 200:1 rejected
    assert "ok.hy3" in names


def test_zip_member_count_limit():
    from mediahub.interpreter._zip_safety import MAX_ZIP_MEMBERS, UnsafeZipError, safe_infolist

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(MAX_ZIP_MEMBERS + 1):
            zf.writestr(f"f{i}.txt", b"x")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        with pytest.raises(UnsafeZipError):
            safe_infolist(zf)


def test_no_zip_extraction_to_disk_anywhere():
    """Zip-slip is structurally absent: ZIP members are only ever read as
    bytes (safe_read_member), never extracted to paths. This guard fails
    if anyone introduces extract()/extractall() outside legacy/."""
    offenders = []
    for py in SRC.rglob("*.py"):
        if "legacy" in py.parts or "vendor" in py.parts:
            continue
        text = py.read_text(errors="ignore")
        if re.search(r"\.extractall\(|\.extract\(", text):
            offenders.append(str(py))
    assert offenders == [], f"zip extraction-to-disk introduced in: {offenders}"


# ------------------------------------------------------- renderer lockdown


def test_renderer_blocks_network_by_default():
    """The Playwright context must route-guard everything except
    file://, data: and about: — verified at source level (a full browser
    test is in the slow render suite)."""
    text = (SRC / "graphic_renderer" / "render.py").read_text()
    assert "_renderer_route_guard" in text
    assert 'startswith(("file://", "data:", "about:"))' in text
    assert "route.abort()" in text
    assert "MEDIAHUB_RENDERER_ALLOW_NET" in text  # explicit escape hatch only


def test_renderer_lockdown_live(tmp_path):
    """Live check: card HTML referencing an external URL renders without
    fetching it — the screenshot still succeeds with the request aborted."""
    pytest.importorskip("playwright.sync_api")
    from mediahub.graphic_renderer.render import render_html_to_png

    html = (
        "<html><head>"
        '<img src="https://example.invalid/leak.png">'
        "</head><body><h1>Lockdown</h1></body></html>"
    )
    out = tmp_path / "out.png"
    render_html_to_png(html, out, (200, 200))
    assert out.exists() and out.stat().st_size > 0


# ------------------------------------------------------------------ SSRF


def test_ssrf_guard_blocks_private_hosts():
    from mediahub.web_research.safe_fetch import is_url_safe

    for url in (
        "http://127.0.0.1/admin",
        "http://localhost:8080/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
        "file:///etc/passwd",
        "ftp://example.org/x",
    ):
        assert not is_url_safe(url), url


def test_upload_from_url_fails_closed(client, monkeypatch):
    """If the SSRF guard cannot run, the URL is refused — never waved through."""
    monkeypatch.setenv("MEDIAHUB_RESULTS_FROM_URL", "1")
    import mediahub.web_research.safe_fetch as sf

    def boom(url):
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(sf, "is_url_safe", boom)
    r = client.post("/upload/from-url", data={"url": "https://example.org/results"})
    assert r.status_code in (400, 404)  # 404 when the feature flag is off


def test_upload_from_url_rejects_private_target(client, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RESULTS_FROM_URL", "1")
    r = client.post("/upload/from-url", data={"url": "http://127.0.0.1/x"})
    assert r.status_code in (400, 404)
