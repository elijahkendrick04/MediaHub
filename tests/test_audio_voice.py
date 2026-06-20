"""Tests for audio/voice.py — catalogue, params, per-org lexicon (roadmap 1.8)."""

from __future__ import annotations

import pytest

from mediahub.audio import voice
from mediahub.audio.voice import OrgLexicon, VoiceParams
from mediahub.visual import pronunciation


# ---- catalogue ------------------------------------------------------------


def test_catalogue_has_local_default_and_welsh():
    voices = voice.list_voices()
    assert any(v.local and v.provider == "piper" for v in voices)
    welsh = voice.list_voices(language="cy")
    assert welsh and all(v.language.startswith("cy") for v in welsh)


def test_filter_by_provider():
    edge = voice.list_voices(provider="edge")
    assert edge and all(v.provider == "edge" for v in edge)


def test_get_and_default_voice():
    d = voice.default_voice()
    assert d.local and d.provider == "piper"
    assert voice.get_voice(d.id) == d
    assert voice.get_voice("does-not-exist") is None


# ---- params ---------------------------------------------------------------


def test_params_clamp_and_default():
    assert VoiceParams().is_default()
    p = VoiceParams.make(rate_pct=999, pitch_hz=-999, volume_pct=10)
    assert p.rate_pct == 100  # clamped to max
    assert p.pitch_hz == -50  # clamped to min
    assert p.volume_pct == 10
    assert not p.is_default()


def test_params_provider_mapping():
    p = VoiceParams.make(rate_pct=20, pitch_hz=3, volume_pct=-5)
    edge = p.to_edge()
    assert edge == {"rate": "+20%", "pitch": "+3Hz", "volume": "-5%"}
    piper = p.to_piper()
    assert piper["length_scale"] < 1.0  # faster → shorter


def test_cache_token_empty_when_default():
    assert VoiceParams().cache_token() == ""  # keeps pre-1.8 cache keys identical
    assert VoiceParams.make(rate_pct=10).cache_token() == "r10p0v0"


# ---- per-org lexicon ------------------------------------------------------


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


def test_org_lexicon_crud():
    lex = OrgLexicon("club-a")
    assert lex.entries() == {}
    lex.set("Saoirse", "Seer-sha")
    lex.set("Cadogan", "Ca-dug-an")
    assert lex.entries() == {"Saoirse": "Seer-sha", "Cadogan": "Ca-dug-an"}
    lex.remove("Cadogan")
    assert lex.entries() == {"Saoirse": "Seer-sha"}
    lex.clear()
    assert lex.entries() == {}


def test_org_lexicon_requires_both_fields():
    lex = OrgLexicon("club-a")
    with pytest.raises(ValueError):
        lex.set("", "x")
    with pytest.raises(ValueError):
        lex.set("x", "")


def test_lexicon_merges_into_pronunciation_chain(tmp_path):
    # global
    (tmp_path / "pronunciations.json").write_text('{"Lee": "Lee-global"}')
    # org
    OrgLexicon("club-a").set("Lee", "Lee-org")
    OrgLexicon("club-a").set("Maya", "My-ah")
    # per-run wins over both
    runs = tmp_path / "runs_v4"
    runs.mkdir()
    (runs / "run1__pronunciations.json").write_text('{"Lee": "Lee-run"}')

    merged = pronunciation.load_overrides(run_id="run1", profile_id="club-a")
    assert merged["Lee"] == "Lee-run"  # per-run most specific
    assert merged["Maya"] == "My-ah"  # org entry survives

    # org alone (no run) → org wins over global
    org_only = pronunciation.load_overrides(profile_id="club-a")
    assert org_only["Lee"] == "Lee-org"

    # backward-compatible: no profile_id → pre-1.8 behaviour (global only here)
    legacy = pronunciation.load_overrides()
    assert legacy["Lee"] == "Lee-global"


def test_profile_id_is_path_traversal_safe():
    p = pronunciation.org_overrides_path("../../etc/passwd")
    # The dangerous components are stripped; the file stays under lexicons/.
    assert "lexicons" in str(p)
    assert ".." not in p.name
