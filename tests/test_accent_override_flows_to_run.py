"""C2 regression — confirmed brand accent override must flow to the run.

Bug: when a user overrides their brand **accent** on /organisation/setup
and saves, it is stored as ``brand_palette_manual["accent"]`` (and the
canonical ``effective_palette`` resolver makes the manual slot win per-slot
over the AI's ``brand_palette_extracted`` pick). Primary/secondary already
honoured the override on the upload Configure step because they read
``brand_primary``/``brand_secondary``, which the save keeps in step. But
the Configure step loaded the accent straight from the *stale* AI extraction
(``brand_palette_extracted["accent"]``), ignoring the manual override — so a
confirmed accent never reached graphics/reels/captions.

This pins the fix: the accent rendered into the Configure colour picker must
be the user's confirmed manual accent, not the extracted AI pick.
"""

from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SAMPLE_PDF = _ROOT / "sample_data" / "MISM-2024-Results.pdf"

_EXTRACTED_ACCENT = "#00de84"  # the AI's original (stale) pick — must NOT win
_MANUAL_ACCENT = "#34e2e4"  # the user's confirmation override — must win


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles", "data"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    # An org that has BOTH an AI-extracted palette and a confirmed manual
    # override. The manual accent differs from the extracted accent — that
    # is the whole point of this regression.
    save_profile(
        ClubProfile(
            profile_id="org-accent",
            display_name="Accent Org",
            brand_voice_summary="Bold.",
            brand_primary="#0a2540",
            brand_secondary="#101820",
            brand_palette_extracted={
                "primary": "#0a2540",
                "secondary": "#101820",
                "accent": _EXTRACTED_ACCENT,
            },
            brand_palette_manual={
                "primary": "#0a2540",
                "secondary": "#101820",
                "accent": _MANUAL_ACCENT,
            },
        )
    )

    wm.RUNS_DIR = tmp_path / "runs_v4"
    wm.UPLOADS_DIR = tmp_path / "uploads_v4"
    a = wm.create_app()
    a.config["TESTING"] = True
    return a


def _configure_body_for_active_profile(app):
    """POST the sample PDF, pin the override profile active, GET configure."""
    if not _SAMPLE_PDF.exists():
        pytest.skip("sample PDF missing")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "org-accent"
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


def test_configure_renders_manual_accent_not_extracted(app):
    body = _configure_body_for_active_profile(app)
    # The accent colour input must carry the user's confirmed override.
    assert f'name="accent_colour" value="{_MANUAL_ACCENT}"' in body, (
        "Configure step did not render the confirmed manual accent. "
        f"Expected {_MANUAL_ACCENT}, body excerpt around accent input did not match."
    )
    # And must NOT carry the stale AI-extracted accent.
    assert f'value="{_EXTRACTED_ACCENT}"' not in body, (
        "Configure step rendered the stale extracted accent instead of the "
        f"confirmed override ({_EXTRACTED_ACCENT})."
    )
