"""H-18 — upload validation must not dead-end or contradict the server.

Before: all three server-side rejections (no file / unsupported extension /
empty file) replaced the whole upload page with a one-line error card — no
form, no dropzone, nowhere to try again. The client-side preview contradicted
the server: ``inferFormat`` had no ``.xlsx`` branch (legit Excel was greeted
"Unknown extension") and its unknown-extension fallback promised "we'll try
every adapter; results may be partial" while the server 400'd the file.

Now: rejections re-render the FULL upload page with the error inline above
the dropzone; ``inferFormat`` mirrors the server's extension allowlist
exactly, with an honest blocker (message + disabled submit) for anything the
server would reject.
"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest

_WEB_SRC = (
    Path(__file__).resolve().parents[1] / "src" / "mediahub" / "web" / "web.py"
).read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _post_upload(client, data):
    return client.post("/upload", data=data, content_type="multipart/form-data")


class TestServerRejectionsKeepTheForm:
    """A rejected POST re-renders the full upload page, error inline."""

    def _assert_full_page_with_inline_error(self, r, fragment):
        body = r.get_data(as_text=True)
        assert r.status_code == 400
        # The full form survives: dropzone, file input, submit button.
        assert "mh-dropzone" in body
        assert "mh-upload-form" in body
        assert "mh-upload-submit" in body
        # The error is rendered into the visible message region (not hidden).
        assert fragment in body
        import re

        m = re.search(r'<div id="mh-upload-error"[^>]*>', body)
        assert m, "inline error region missing"
        assert "hidden" not in m.group(0), "server error region must be visible"
        assert fragment in body[m.end() : m.end() + 300]

    def test_no_file_selected(self, client):
        r = _post_upload(client, {})
        self._assert_full_page_with_inline_error(r, "Please choose a results file first.")

    def test_unsupported_extension(self, client):
        r = _post_upload(client, {"file": (io.BytesIO(b"payload"), "evil.exe")})
        self._assert_full_page_with_inline_error(r, "isn't supported")

    def test_empty_file(self, client):
        r = _post_upload(client, {"file": (io.BytesIO(b""), "meet.hy3")})
        self._assert_full_page_with_inline_error(r, "That file is empty")

    def test_good_upload_still_redirects_to_configure(self, client):
        r = _post_upload(client, {"file": (io.BytesIO(b"some-bytes"), "meet.hy3")})
        assert r.status_code in (302, 303)
        assert "/upload/configure" in r.headers["Location"]

    def test_get_page_error_region_stays_hidden(self, client):
        body = client.get("/upload").get_data(as_text=True)
        import re

        m = re.search(r'<div id="mh-upload-error"[^>]*>', body)
        assert m, "inline error region missing on GET"
        assert "hidden" in m.group(0)


class TestClientPreviewMirrorsServer:
    """inferFormat mirrors the server allowlist; unknowns honestly block."""

    def test_old_contradictory_fallback_gone(self):
        assert "results may be partial" not in _WEB_SRC
        assert "Unknown extension" not in _WEB_SRC

    def test_xlsx_has_a_good_branch(self):
        assert "n.endsWith('.xlsx')" in _WEB_SRC
        assert "Excel workbook (.xlsx)" in _WEB_SRC

    def test_xls_is_honestly_blocked_with_guidance(self):
        assert "n.endsWith('.xls')" in _WEB_SRC
        assert "save it as .xlsx and upload that instead" in _WEB_SRC

    def test_unknown_extension_blocks_the_submit(self):
        # The unknown branch says the honest thing…
        assert r"MediaHub can\\u2019t read ' + ext + ' files" in _WEB_SRC
        # …and refresh() disables the submit until a supported file is chosen.
        assert "btn.disabled = true;" in _WEB_SRC
        assert "info.kind === 'bad'" in _WEB_SRC

    def test_client_branches_cover_the_server_allowlist(self):
        # Every extension the server accepts has a 'good' preview branch.
        for ext in (
            ".hy3",
            ".hyv",
            ".sd3",
            ".sdif",
            ".cl2",
            ".zip",
            ".pdf",
            ".htm",
            ".csv",
            ".txt",
            ".xlsx",
        ):
            assert f"n.endsWith('{ext}')" in _WEB_SRC, ext
        assert "n.endsWith('.html')" in _WEB_SRC


class TestSupportedFormatsLineConsistent:
    """The visible format hints match the real allowlist."""

    def test_accept_attribute_matches_allowlist(self, client):
        body = client.get("/upload").get_data(as_text=True)
        assert 'accept=".hy3,.hyv,.sd3,.sdif,.cl2,.zip,.pdf,.htm,.html,.csv,.txt,.xlsx"' in body

    def test_fineprint_names_excel_and_txt(self, client):
        body = client.get("/upload").get_data(as_text=True)
        assert "Excel (.xlsx)" in body
        assert "TXT" in body
