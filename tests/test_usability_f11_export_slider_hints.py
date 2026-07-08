"""F-11 — the bulk-export form must show its quality value and explain formats.

The Quality control was a bare range input — the user couldn't see whether they'd
picked 90 or 45 — and the format checkboxes were raw codec labels (PNG/JPG/WebP/
AVIF) with no guidance. There's now a live value readout beside the slider and a
one-line plain-English hint per format.
"""

from __future__ import annotations

import importlib
import json
import pathlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "club-a"})
    (tmp_path / "runs_v4" / "run-a1.json").write_text(
        json.dumps(
            {"run_id": "run-a1", "profile_id": "club-a", "meet": {"name": "Manchester Open"}}
        )
    )
    return c


def test_quality_slider_has_live_value_readout(client):
    html = client.get("/export/run-a1").get_data(as_text=True)
    # An <output> bound to the slider gives a visible current value.
    assert '<output id="bx-quality-out"' in html
    assert 'for="bx-quality"' in html
    # And a plain-English note on what quality trades off.
    assert "Higher = sharper" in html


def test_format_checkboxes_carry_plain_english_hints(client):
    html = client.get("/export/run-a1").get_data(as_text=True)
    assert "works everywhere" in html  # JPG hint
    assert "sharpest text" in html  # PNG hint
    assert "some apps can't open it yet" in html  # AVIF hint


def test_bulk_export_js_syncs_the_readout():
    js = pathlib.Path("src/mediahub/web/static/js/bulk_export.js").read_text(encoding="utf-8")
    assert "bx-quality-out" in js
    assert 'addEventListener("input"' in js
