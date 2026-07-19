"""Regression — a logo uploaded at /organisation/setup must count as the
org's logo on the run Configure step (and flow into graphics).

Bug: uploaded logos are stored on ``ClubProfile.brand_logos`` (a list of
local-file metadata dicts), which is distinct from the auto-detected
website ``brand_logo_url``. The Configure step only checked
``brand_logo_url``, so a user who uploaded a crest was still told
"No logo on your organisation profile" and the run never received it.

This pins the fix: when the org has an image entry on ``brand_logos`` but
no ``brand_logo_url``, the Configure step treats it as having a logo and
names it, instead of showing the "No logo" warning.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SAMPLE_PDF = _ROOT / "sample_data" / "MISM-2024-Results.pdf"
_LOGO_NAME = "wolfpack-crest.png"


def _configure_body(app, profile_id):
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = profile_id
    rv = c.post(
        "/upload",
        data={"file": (io.BytesIO(_SAMPLE_PDF.read_bytes()), "MISM-2024-Results.pdf")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert rv.status_code in (302, 303), rv.data[:300]
    run_id = rv.headers["Location"].split("run_id=")[-1]
    rv2 = c.get(f"/upload/configure?run_id={run_id}")
    assert rv2.status_code == 200, rv2.data[:300]
    return rv2.data.decode("utf-8", errors="ignore")


def test_uploaded_logo_counts_on_configure(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-logo",
            display_name="Logo Org",
            brand_voice_summary="Proud.",
            brand_logo_url="",  # no auto-detected website logo
            brand_logos=[
                {
                    "logo_id": "abc123def456",
                    "original_filename": _LOGO_NAME,
                    "stored_path": "club_logos/org-logo/abc123def456.png",
                    "mime": "image/png",
                    "byte_size": 1234,
                    "ai_description": "A howling wolf crest.",
                    "ai_dominant_colours": ["#3060d8", "#ffffff"],
                }
            ],
        )
    )
    body = _configure_body(app, "org-logo")
    assert "No logo on your organisation profile" not in body, (
        "Configure still warns about a missing logo even though the org "
        "has an uploaded brand_logos image."
    )
    assert _LOGO_NAME in body, "Configure did not name the uploaded logo."


def test_no_logo_warning_when_truly_absent(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-nologo",
            display_name="No Logo Org",
            brand_voice_summary="Plain.",
            brand_logo_url="",
            brand_logos=[],
        )
    )
    body = _configure_body(app, "org-nologo")
    assert "No logo on your organisation profile" in body, (
        "Configure should still warn when the org has neither a detected " "nor an uploaded logo."
    )
