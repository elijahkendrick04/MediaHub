"""Pins for the web.py wiring landed from the Phase-C handoffs batch.

Covers the pure HTML helpers (caption-assist buttons driven from
``caption_assist.PRESET_LABELS``; the G1.18 colour-accessibility panel) and a
route-level check that the ``to_pdf`` quick action now dispatches (parity with
the ACTIONS catalogue) rather than returning ``bad_action``.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# Pure helpers — no request context needed
# --------------------------------------------------------------------------- #


def test_caption_assist_buttons_driven_from_preset_labels():
    import mediahub.web.web as w
    from mediahub.web.caption_assist import PRESET_LABELS

    html = w._caption_assist_buttons("card-xyz")
    # Every slug in the fixed order renders its PRESET_LABELS value and an
    # onclick whose transform slug is the PRESETS key.
    for slug in w._ASSIST_BUTTON_ORDER:
        assert PRESET_LABELS[slug] in html
        assert f"'card-xyz', '{slug}'" in html
    # fuller / calmer stay opt-in — no dedicated button unless added deliberately.
    assert "'card-xyz', 'fuller'" not in html
    assert "'card-xyz', 'calmer'" not in html


def test_colour_accessibility_panel_renders_details():
    import mediahub.web.web as w

    roles = {
        "--mh-primary": "#0A2540",
        "--mh-on-primary": "#FFFFFF",
        "--mh-accent": "#F5A623",
        "--mh-surface": "#0A0B11",
        "--mh-on-surface": "#FFFFFF",
    }
    html = w._colour_accessibility_panel_html(roles)
    assert "<details" in html
    assert "Colour accessibility" in html
    assert "<svg" in html  # swatch strip embedded


def test_colour_accessibility_panel_empty_when_no_roles():
    import mediahub.web.web as w

    assert w._colour_accessibility_panel_html(None) == ""
    assert w._colour_accessibility_panel_html({}) == ""


# --------------------------------------------------------------------------- #
# Route — quick-action to_pdf now dispatches (ACTIONS parity)
# --------------------------------------------------------------------------- #


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    return app, tmp_path


def _seed_png(tmp_path, profile_id="alpha", name="p.png"):
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    p = tmp_path / f"{profile_id}_{name}"
    Image.new("RGB", (80, 60), (120, 80, 40)).save(p)
    store = get_store()
    a = MediaAsset(
        id="",
        filename=name,
        path=str(p),
        type="athlete_action",
        profile_id=profile_id,
        permission_status="approved_by_club",
        approval_status="approved",
    )
    return store.save(a).id


def test_quick_action_to_pdf_dispatches(app_ctx):
    app, tmp_path = app_ctx
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        aid = _seed_png(tmp_path)
        r = c.post(f"/api/media-library/{aid}/quick-action", json={"action": "to_pdf"})
    # Must NOT be the bad_action 400 the ACTIONS catalogue previously advertised.
    assert r.status_code != 400 or (r.get_json() or {}).get("error") != "bad_action"
    if r.status_code == 200:
        assert r.mimetype == "application/pdf"
