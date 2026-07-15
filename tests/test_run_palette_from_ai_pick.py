"""Regression — a run's palette must follow the AI-resolved brand, not the
stale legacy ``brand_primary``/``brand_secondary`` fields.

Bug (sibling of the C2 accent fix): the upload Configure step seeded the
run's primary/secondary colour pickers straight from
``ClubProfile.brand_primary``/``brand_secondary``. For an organisation whose
colours came purely from the AI pick — the common case where the user never
did a manual "Save brand colours" — those legacy fields stay at the class
default ``#A30D2D`` (a legacy red). So every generated card/reel/email was
seeded red while the site chrome (which resolves through
``effective_palette``) correctly showed the real brand.

This pins the fix: primary/secondary rendered into the Configure colour
pickers must be the resolved palette (manual override > AI extracted),
falling back to the legacy fields only when the resolver has nothing.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SAMPLE_PDF = _ROOT / "sample_data" / "MISM-2024-Results.pdf"

_LEGACY_DEFAULT = "#a30d2d"  # ClubProfile.brand_primary class default — must NOT win
_AI_PRIMARY = "#3060d8"  # the AI's extracted pick — must win
_AI_SECONDARY = "#1b2a55"
_AI_ACCENT = "#77a7ff"


def _make_app(web_module, profile):
    from mediahub.web.club_profile import save_profile

    save_profile(profile)

    a = web_module.create_app()
    a.config["TESTING"] = True
    return a


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


def test_ai_pick_drives_run_primary_secondary(web_module):
    """AI-extracted palette present, brand_primary still at legacy default."""
    from mediahub.web.club_profile import ClubProfile

    app = _make_app(
        web_module,
        ClubProfile(
            profile_id="org-ai",
            display_name="AI Org",
            brand_voice_summary="Proud.",
            # Legacy fields untouched -> class default red. This is the trap.
            brand_primary="#A30D2D",
            brand_secondary="#101820",
            brand_palette_extracted={
                "primary": _AI_PRIMARY,
                "secondary": _AI_SECONDARY,
                "accent": _AI_ACCENT,
            },
            brand_palette_manual={},
        ),
    )
    body = _configure_body(app, "org-ai")
    assert f'name="primary_colour" value="{_AI_PRIMARY}"' in body, (
        "Configure did not seed the AI-extracted primary; it likely fell back "
        "to the legacy red default."
    )
    assert (
        f'name="secondary_colour" value="{_AI_SECONDARY}"' in body
    ), "Configure did not seed the AI-extracted secondary."
    # No run colour picker may carry the legacy red default.
    assert (
        f'value="{_LEGACY_DEFAULT}"' not in body.lower()
    ), "Configure leaked the legacy #A30D2D default into a run colour picker."


def test_legacy_brand_primary_still_used_when_no_ai_pick(web_module):
    """No extracted/manual palette -> fall back to explicit legacy fields."""
    from mediahub.web.club_profile import ClubProfile

    legacy_primary = "#003da5"
    legacy_secondary = "#0b1f3a"
    app = _make_app(
        web_module,
        ClubProfile(
            profile_id="org-legacy",
            display_name="Legacy Org",
            brand_voice_summary="Classic.",
            brand_primary=legacy_primary,
            brand_secondary=legacy_secondary,
            brand_palette_extracted={},
            brand_palette_manual={},
        ),
    )
    body = _configure_body(app, "org-legacy")
    assert (
        f'name="primary_colour" value="{legacy_primary}"' in body
    ), "Configure dropped the explicit legacy primary when no AI pick exists."
    assert (
        f'name="secondary_colour" value="{legacy_secondary}"' in body
    ), "Configure dropped the explicit legacy secondary when no AI pick exists."
