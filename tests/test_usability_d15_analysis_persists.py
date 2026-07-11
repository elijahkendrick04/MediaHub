"""tests/test_usability_d15_analysis_persists.py — /organisation analysis
persists immediately with an explicit Discard (audit finding D-15).

"Re-analyse brand" and "Analyse voice" used to keep their 10-30s results
in memory, riding hidden inputs, and lost everything unless the user
scrolled down and clicked "Save organisation". Now a successful analysis
persists to the profile immediately (like the setup wizard's capture); the
previous values are stashed in the session as a one-shot undo behind a
"Discard this analysis" button; failures surface an honest error and
persist nothing; and the hidden-input plumbing is gone.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")

_OLD_VOICE_PROFILE = {"sentence_length_avg": 5.5, "characteristic_openers": ["Old"]}
_OLD_VOICE_EXAMPLES = ["Old caption one", "Old caption two"]


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
    prof.voice_examples = list(_OLD_VOICE_EXAMPLES)
    prof.voice_profile = dict(_OLD_VOICE_PROFILE)
    prof.brand_voice_summary = "The old summary."
    cp.save_profile(prof)

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, cp


def _analyse_post(client, **overrides):
    data = {
        "action": "save",
        "profile_id": "otters",
        "display_name": "Otters SC",
        "analyse_voice": "1",
        "voice_examples": "New line about the gala\nNew line about a relay win",
    }
    data.update(overrides)
    return client.post("/organisation", data=data)


_SOCIALS_RESULT = {
    "brand_capture_status": "ok",
    "brand_voice_summary": "A brand-new summary.",
    "brand_keywords": ["fast", "friendly"],
    "brand_palette_extracted": {"primary": "#123456", "secondary": "#654321"},
    "brand_source_url": "https://otters.example",
    "brand_captured_at": "2026-07-11T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Persist-on-success
# ---------------------------------------------------------------------------


def test_voice_analysis_persists_immediately(env, monkeypatch):
    app, cp = env
    import mediahub.brand.voice_imitation as vi

    monkeypatch.setattr(
        vi, "analyse_examples", lambda examples, **kw: {"sentence_length_avg": 9.0}
    )
    with app.test_client() as c:
        r = _analyse_post(c)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "analysed and saved" in html
        # The one-shot undo is offered right away.
        assert "Discard this analysis" in html
    prof = cp.load_profile("otters")
    assert prof.voice_profile == {"sentence_length_avg": 9.0}
    assert prof.voice_examples[0].startswith("New line")


def test_brand_reanalysis_persists_immediately(env, monkeypatch):
    app, cp = env
    import mediahub.brand.social_dna as sd

    monkeypatch.setattr(sd, "capture_from_socials", lambda **kw: dict(_SOCIALS_RESULT))
    with app.test_client() as c:
        r = c.post(
            "/organisation",
            data={
                "action": "capture_socials",
                "profile_id": "otters",
                "display_name": "Otters SC",
                "brand_source_url": "https://otters.example",
            },
        )
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Re-analysed" in html and "saved" in html
        assert "Discard this analysis" in html
    prof = cp.load_profile("otters")
    assert prof.brand_voice_summary == "A brand-new summary."
    assert prof.brand_palette_extracted == {"primary": "#123456", "secondary": "#654321"}


# ---------------------------------------------------------------------------
# Honest error persists nothing
# ---------------------------------------------------------------------------


def test_voice_analysis_failure_persists_nothing(env, monkeypatch):
    app, cp = env
    import mediahub.brand.voice_imitation as vi

    def _boom(examples, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(vi, "analyse_examples", _boom)
    with app.test_client() as c:
        r = _analyse_post(c, display_name="Renamed SC")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "Voice analysis failed" in html
        assert "Nothing was saved" in html
        assert "Discard this analysis" not in html
    prof = cp.load_profile("otters")
    # Nothing persisted: not the voice fields, not the rest of the form.
    assert prof.voice_profile == _OLD_VOICE_PROFILE
    assert prof.voice_examples == _OLD_VOICE_EXAMPLES
    assert prof.display_name == "Otters SC"


def test_voice_analysis_with_too_few_examples_persists_nothing(env):
    app, cp = env
    with app.test_client() as c:
        r = _analyse_post(c, voice_examples="", display_name="Renamed SC")
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "at least 3 captions" in html
        assert "Nothing was saved" in html
    prof = cp.load_profile("otters")
    assert prof.voice_examples == _OLD_VOICE_EXAMPLES
    assert prof.display_name == "Otters SC"


def test_brand_reanalysis_failure_persists_nothing(env, monkeypatch):
    app, cp = env
    import mediahub.brand.social_dna as sd

    def _boom(**kw):
        raise RuntimeError("socials unreachable")

    monkeypatch.setattr(sd, "capture_from_socials", _boom)
    with app.test_client() as c:
        r = c.post(
            "/organisation",
            data={
                "action": "capture_socials",
                "profile_id": "otters",
                "display_name": "Otters SC",
                "brand_source_url": "https://otters.example",
            },
        )
        assert r.status_code == 200
        assert "Capture failed" in r.get_data(as_text=True)
    prof = cp.load_profile("otters")
    assert prof.brand_voice_summary == "The old summary."
    assert prof.brand_palette_extracted == {}


# ---------------------------------------------------------------------------
# Discard restores the stashed previous values (one-shot)
# ---------------------------------------------------------------------------


def test_discard_restores_previous_voice_values(env, monkeypatch):
    app, cp = env
    import mediahub.brand.voice_imitation as vi

    monkeypatch.setattr(
        vi, "analyse_examples", lambda examples, **kw: {"sentence_length_avg": 9.0}
    )
    with app.test_client() as c:
        _analyse_post(c)
        assert cp.load_profile("otters").voice_profile == {"sentence_length_avg": 9.0}
        r = c.post("/organisation/analysis/discard")
        assert r.status_code == 302
        prof = cp.load_profile("otters")
        assert prof.voice_profile == _OLD_VOICE_PROFILE
        assert prof.voice_examples == _OLD_VOICE_EXAMPLES
        # One-shot: a second discard is a friendly no-op, not a restore/error.
        r2 = c.post("/organisation/analysis/discard")
        assert r2.status_code == 302
        assert cp.load_profile("otters").voice_profile == _OLD_VOICE_PROFILE


def test_discard_restores_previous_brand_values(env, monkeypatch):
    app, cp = env
    import mediahub.brand.social_dna as sd

    monkeypatch.setattr(sd, "capture_from_socials", lambda **kw: dict(_SOCIALS_RESULT))
    with app.test_client() as c:
        c.post(
            "/organisation",
            data={
                "action": "capture_socials",
                "profile_id": "otters",
                "display_name": "Otters SC",
                "brand_source_url": "https://otters.example",
            },
        )
        assert cp.load_profile("otters").brand_voice_summary == "A brand-new summary."
        r = c.post("/organisation/analysis/discard")
        assert r.status_code == 302
    prof = cp.load_profile("otters")
    assert prof.brand_voice_summary == "The old summary."
    assert prof.brand_palette_extracted == {}


# ---------------------------------------------------------------------------
# The in-memory-only plumbing is gone
# ---------------------------------------------------------------------------


def test_hidden_input_plumbing_removed_from_source():
    for token in (
        "voice_profile_json",
        "voice_examples_json",
        "brand_keywords_json",
        "brand_phrases_to_use_json",
        "brand_phrases_to_avoid_json",
        "brand_palette_extracted_json",
        "brand_source_url_saved",
        "brand_hidden_inputs",
    ):
        assert token not in _WEB_SRC, token


def test_in_memory_info_tags_removed_from_source():
    assert "Save organisation to persist" not in _WEB_SRC
    assert "kept in-memory only" not in _WEB_SRC
