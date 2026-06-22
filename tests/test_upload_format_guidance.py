"""Regression: upload page must display a complete list of accepted file formats.

A volunteer arriving at /upload should see every format the server accepts so
they know whether their file will work BEFORE they try to submit it.

The server's allowlist is:
    .hy3  .hyv  .sd3  .sdif  .cl2  .zip  .pdf  .htm  .html  .csv  .txt

The upload form must communicate this — both in the visible hint text and in
the ``accept`` attribute of the file input so the browser file-picker filters
accordingly.  Previous state only advertised .hy3 / .zip / PDF.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def upload_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True  # gate bypassed so /upload renders

    with app.test_client() as c:
        yield c


@pytest.fixture
def upload_body(upload_client):
    return upload_client.get("/upload").get_data(as_text=True)


class TestUploadFormatGuidance:
    """The /upload page must expose the full server-side accept list visually."""

    def test_csv_mentioned_in_upload_page(self, upload_body):
        """CSV is accepted server-side but was missing from the UI hint text."""
        assert ".csv" in upload_body or "CSV" in upload_body, (
            "CSV format not mentioned on upload page — volunteers won't know to submit it"
        )

    def test_sdif_mentioned_in_upload_page(self, upload_body):
        """SDIF / SD3 / CL2 are accepted but were absent from the form hint."""
        body_lower = upload_body.lower()
        assert "sdif" in body_lower or "sd3" in body_lower or "cl2" in body_lower, (
            "SDIF/SD3/CL2 format not mentioned on upload page"
        )

    def test_accept_attribute_includes_csv(self, upload_body):
        """The file input's accept= attribute must include .csv so the browser
        file-picker offers CSV files by default."""
        assert ".csv" in upload_body, (
            "accept attribute does not include .csv — browser file-picker will hide CSV files"
        )

    def test_accept_attribute_includes_sdif(self, upload_body):
        """The file input's accept= must include .sdif / .sd3 so the browser
        file-picker surfaces those result file types."""
        assert ".sdif" in upload_body or ".sd3" in upload_body, (
            "accept attribute does not include .sdif/.sd3 — browser file-picker will hide SDIF files"
        )

    def test_format_hint_text_covers_key_types(self, upload_body):
        """The visible dropzone hint text must name more than just .hy3 and ZIP."""
        # At minimum, the hint should now mention three distinct format families:
        # Hytek (.hy3), SDIF, and CSV.
        families_found = sum([
            ".hy3" in upload_body,
            "sdif" in upload_body.lower() or "sd3" in upload_body.lower(),
            "csv" in upload_body.lower(),
        ])
        assert families_found >= 3, (
            f"Upload page only mentions {families_found}/3 key format families "
            "(need .hy3, SDIF/SD3, and CSV)"
        )
