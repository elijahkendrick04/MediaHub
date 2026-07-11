"""tests/test_usability_g5_single_voice_ui.py — one voice-training surface on
/organisation (audit finding G-5).

The legacy page grew two "Analyse voice" buttons, two voice_examples
textareas, and rendered the "Voice profile preview" panel twice; a
first-built variant of the panel was overwritten before render (dead code).
G-5 keeps exactly one surface: the in-form "Voice examples" card with its
textarea, one Analyse voice button, and one preview panel.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    prof = cp.ClubProfile(profile_id="otters", display_name="Otters SC")
    prof.voice_examples = ["Great swim from the squad tonight", "PB city at the gala"]
    prof.voice_profile = {"sentence_length_avg": 6.0, "characteristic_openers": ["Great"]}
    cp.save_profile(prof)

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, cp


def _get_page(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "otters"
        return c.get("/organisation").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Source-level: the duplicated / dead voice UI is gone from web.py
# ---------------------------------------------------------------------------


def test_standalone_analyse_card_removed_from_source():
    assert "Analyse voice from past posts" not in _WEB_SRC
    assert 'value="analyse_voice"' not in _WEB_SRC  # the standalone form action
    assert "org-voice-examples" not in _WEB_SRC


def test_dead_first_built_panel_removed_from_source():
    # The first-built variant was overwritten before render — dead code.
    assert "Voice profile (from " not in _WEB_SRC
    assert "No voice profile yet" not in _WEB_SRC


def test_in_form_analyse_button_kept_in_source():
    assert 'name="analyse_voice" value="1"' in _WEB_SRC


# ---------------------------------------------------------------------------
# Behavioural: the rendered page has exactly one of each voice element
# ---------------------------------------------------------------------------


def test_exactly_one_voice_textarea_and_analyse_button(env):
    app, _cp = env
    html = _get_page(app)
    assert html.count('name="voice_examples"') == 1
    assert html.count(">Analyse voice") == 1


def test_voice_profile_preview_rendered_exactly_once(env):
    app, _cp = env
    html = _get_page(app)
    assert html.count("Voice profile preview") == 1


def test_in_form_analyse_still_analyses_and_saves(env, monkeypatch):
    app, cp = env
    import mediahub.brand.voice_imitation as vi

    monkeypatch.setattr(
        vi, "analyse_examples", lambda examples, **kw: {"sentence_length_avg": 9.5}
    )
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "otters"
        r = c.post(
            "/organisation",
            data={
                "action": "save",
                "profile_id": "otters",
                "display_name": "Otters SC",
                "analyse_voice": "1",
                "voice_examples": "Line one about the gala\nLine two about a big PB",
            },
        )
    assert r.status_code == 200
    prof = cp.load_profile("otters")
    assert prof.voice_profile.get("sentence_length_avg") == 9.5
