"""Motion ↔ audio wiring: cache-key discipline, manifests, honest fallback.

The contract under test (visual/motion.py + visual/audio_mux.py):

* audio OFF (the default) → the cache payload — and therefore every cache
  key — is byte-identical to the pre-audio era; no existing cache is
  orphaned;
* audio ON → the plan is folded into the key (a silent and a narrated
  render can never collide), the manifest records what was mixed, and the
  poster sidecar travels with the published MP4;
* a cache hit whose earlier audio attach failed retries the audio WITHOUT
  re-rendering the video;
* the free FFmpeg engine receives the exact same plan (engine symmetry).

No Node, no network: renders are stubbed, the TTS/mux seams are patched.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from mediahub.brand.kit import BrandKit
from mediahub.visual import audio_mux, motion

BRAND = BrandKit(
    profile_id="audio-wire",
    display_name="Audio Wire SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="AWSC",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-audio-{i}",
        "swim_id": f"swim-audio-{i}",
        "achievement": {
            "swim_id": f"swim-audio-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Audio Invitational",
    }


def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"0" * 2048)
    return out


def _silent_story_key(card: dict, *, duration: float = 6.0) -> str:
    """The audio-off cache key, computed exactly as the silent path does
    (including the story composition revision — see M15)."""
    brand_dict = motion._brand_to_dict(BRAND)
    card_dict = motion._card_to_props(card, variation_seed=0, brief=None, brand_kit=BRAND)
    return motion._content_hash(
        {
            "card": card_dict,
            "brand": brand_dict,
            "duration": duration,
            "size": [1080, 1920],
            "rev": motion.STORY_COMPOSITION_REVISION,
        },
        kind="story",
    )


def _voice_on(monkeypatch):
    monkeypatch.setattr(audio_mux, "voice_active", lambda: True)
    monkeypatch.setattr(audio_mux, "voice_name", lambda: "en-GB-SoniaNeural")


def _stub_finishing(monkeypatch, calls: list, *, outcomes: list | None = None):
    """Record apply_audio calls; make posters real files so publish copies them.

    ``outcomes`` scripts each call's returned status (default: always mixed).
    """

    def _apply(video, plan, *, duration_sec, cut_times=None):
        calls.append(
            {
                "video": Path(video),
                "plan": plan,
                "duration": duration_sec,
                "cut_times": cut_times,
            }
        )
        seq = outcomes or ["mixed"]
        status = seq[min(len(calls) - 1, len(seq) - 1)]
        if status == "mixed":
            return {
                "status": "mixed",
                "voice": plan.get("voice", ""),
                "music": "",
                "transcript": "",
            }
        return {"status": "silent_fallback", "reason": "endpoint unreachable"}

    def _poster(video, poster, *, at_sec):
        Path(poster).write_bytes(b"\x89PNG poster")
        return True

    monkeypatch.setattr(audio_mux, "apply_audio", _apply)
    monkeypatch.setattr(audio_mux, "write_poster", _poster)


def _manifests(cache_dir: Path) -> list[Path]:
    """The explainability manifests (excluding the audio-record sidecars)."""
    return [
        p
        for p in cache_dir.glob("*.json")
        if p.parent == cache_dir and not p.name.endswith(".audio.json")
    ]


# ---------------------------------------------------------------------------
# Cache-key discipline
# ---------------------------------------------------------------------------


def test_silent_path_cache_key_is_byte_identical_to_pre_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    expected = _silent_story_key(_card(1))
    assert (motion._cache_dir() / f"{expected}.mp4").exists(), (
        "audio-off renders must keep the historic cache key (no orphaned caches)"
    )


def test_audio_plan_changes_the_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    _stub_finishing(monkeypatch, [])
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    silent = _silent_story_key(_card(1))
    cached = list(motion._cache_dir().glob("*.mp4"))
    assert len(cached) == 1
    assert cached[0].stem != silent, "a narrated render must never collide with a silent one"


# ---------------------------------------------------------------------------
# Manifest + poster publication
# ---------------------------------------------------------------------------


def test_manifest_records_audio_and_poster_and_out_gets_the_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)
    out = tmp_path / "out" / "story.mp4"
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, out)

    assert len(calls) == 1
    plan = calls[0]["plan"]
    assert plan["voice"] == "en-GB-SoniaNeural"
    assert "Swimmer 1" in plan["script"], "narration must speak the card's own facts"

    manifests = _manifests(motion._cache_dir())
    assert manifests
    data = json.loads(manifests[0].read_text())
    assert data["audio"]["status"] == "mixed"
    assert data["poster"].endswith(".poster.png")
    assert (out.parent / "story.poster.png").exists(), "poster sidecar must ship with the MP4"


def test_silent_manifest_says_audio_off(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    data = json.loads(_manifests(motion._cache_dir())[0].read_text())
    assert data["audio"] == {"status": "off"}


# ---------------------------------------------------------------------------
# Cache-hit semantics: successful audio is never re-applied; failed audio is
# retried — and neither re-renders the video.
# ---------------------------------------------------------------------------


def _never_render(*a, **k):
    raise AssertionError("cache hit must not re-render the video")


def test_cache_hit_does_not_reapply_successful_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls, outcomes=["mixed"])

    out = tmp_path / "out" / "story.mp4"
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, out)
    assert len(calls) == 1
    with mock.patch.object(motion, "_run_remotion", side_effect=_never_render):
        motion.render_story_card(_card(1), BRAND, out)
    assert len(calls) == 1, "a successful mix must not be re-applied (double audio)"


def test_cache_hit_retries_failed_audio_without_rerendering(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls, outcomes=["silent_fallback", "mixed"])

    out = tmp_path / "out" / "story.mp4"
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, out)
    assert len(calls) == 1
    data = json.loads(_manifests(motion._cache_dir())[0].read_text())
    assert data["audio"]["status"] == "silent_fallback", "first attempt failed honestly"

    # Second request: video comes from cache, the audio attach is retried.
    with mock.patch.object(motion, "_run_remotion", side_effect=_never_render):
        motion.render_story_card(_card(1), BRAND, out)
    assert len(calls) == 2

    data = json.loads(_manifests(motion._cache_dir())[0].read_text())
    assert data["audio"]["status"] == "mixed", "manifest must reflect the retried outcome"


# ---------------------------------------------------------------------------
# Engine symmetry: the free FFmpeg engine gets the same plan
# ---------------------------------------------------------------------------


def test_ffmpeg_engine_receives_the_same_audio_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")
    _voice_on(monkeypatch)
    captured: dict = {}

    def _fake_ffmpeg_story(card_props, brand_dict, brand_kit, out_path, **kwargs):
        captured.update(kwargs)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    import mediahub.visual.reel_ffmpeg as reel_ffmpeg

    monkeypatch.setattr(reel_ffmpeg, "render_story_card_from_props", _fake_ffmpeg_story)
    motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    assert captured["audio_plan"] is not None
    assert "Swimmer 1" in captured["audio_plan"]["script"]


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def test_story_audio_plan_is_none_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    card_dict = motion._card_to_props(_card(1), variation_seed=0)
    assert motion._story_audio_plan(card_dict, {"displayName": "X"}) is None


def test_reel_audio_plan_budgets_to_the_reel_duration(monkeypatch):
    _voice_on(monkeypatch)
    cards = [motion._card_to_props(_card(i), variation_seed=0) for i in (1, 2, 3)]
    plan = motion._reel_audio_plan(
        cards, {"displayName": "Audio Wire SC"}, "Audio Invitational", duration_sec=15.0
    )
    assert plan is not None
    from mediahub.visual.narration import estimate_seconds

    assert "Audio Invitational" in plan["script"]
    assert estimate_seconds(plan["script"]) <= 15.0


# ---------------------------------------------------------------------------
# R1.20 — the reel's card-cut beat grid reaches the audio mux; stories don't
# ---------------------------------------------------------------------------


def test_reel_passes_the_beat_grid_to_the_mux(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)
    cards = [_card(1), _card(2), _card(3)]
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_meet_reel(cards, BRAND, tmp_path / "out" / "reel.mp4")
    assert len(calls) == 1
    duration = motion.reel_duration_for(3)
    assert calls[0]["cut_times"] == audio_mux.card_cut_times(duration, 3)
    assert calls[0]["cut_times"], "a reel must carry card cuts for beat-aware accents"


def test_story_passes_no_beat_grid(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    assert len(calls) == 1
    assert calls[0]["cut_times"] is None, "a single-scene story has no card cuts"


# ---------------------------------------------------------------------------
# Per-card audio-mix profiles (R1.19): the seam, and folding into the key
# ---------------------------------------------------------------------------


def test_card_mix_profile_seam_reads_payload_then_brief():
    assert motion._card_mix_profile({"audio_mix_profile": "voice_lead"}) == "voice_lead"
    assert motion._card_mix_profile({"audioMixProfile": "music_forward"}) == "music_forward"
    # The brief can carry it; a card field wins over the brief's.
    assert motion._card_mix_profile({}, {"audio_mix_profile": "voice_lead"}) == "voice_lead"
    assert (
        motion._card_mix_profile(
            {"audio_mix_profile": "music_forward"}, {"audio_mix_profile": "voice_lead"}
        )
        == "music_forward"
    )
    # Absent → None, so audio_mux's env-default → balanced precedence decides.
    assert motion._card_mix_profile({}, {}) is None
    assert motion._card_mix_profile(None, None) is None


def test_story_audio_plan_threads_the_mix_profile(monkeypatch):
    _voice_on(monkeypatch)
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    card_dict = motion._card_to_props(_card(1), variation_seed=0)
    plan = motion._story_audio_plan(card_dict, {"displayName": "X"}, mix_profile="voice_lead")
    assert plan is not None and plan["mix"] == "voice_lead"
    # Default keeps the plan free of a mix key (byte-identical cache identity).
    assert "mix" not in motion._story_audio_plan(card_dict, {"displayName": "X"})


def test_balanced_render_keeps_the_pre_profile_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "story.mp4")
    assert len(calls) == 1
    assert "mix" not in calls[0]["plan"], (
        "a balanced (default) narrated render must not fold a mix into the key"
    )


def test_per_card_mix_profile_folds_into_the_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)

    plain = _card(1)
    forward = dict(_card(1))
    forward["audio_mix_profile"] = "music_forward"  # identical facts, different mix

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(plain, BRAND, tmp_path / "out" / "a.mp4")
        plain_stems = {p.stem for p in motion._cache_dir().glob("*.mp4")}
        motion.render_story_card(forward, BRAND, tmp_path / "out" / "b.mp4")
    new_stems = {p.stem for p in motion._cache_dir().glob("*.mp4")} - plain_stems

    assert len(new_stems) == 1, "a different mix must mint a new cache key, not collide"
    assert calls[-1]["plan"]["mix"] == "music_forward"


def test_reel_takes_the_headline_cards_mix_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    _voice_on(monkeypatch)
    calls: list = []
    _stub_finishing(monkeypatch, calls)

    top = [_card(1), dict(_card(2), audio_mix_profile="voice_lead"), _card(3)]
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_meet_reel(top, BRAND, tmp_path / "out" / "reel.mp4", meet_name="Audio Inv")
    assert len(calls) == 1
    assert calls[0]["plan"]["mix"] == "voice_lead", "first card to name a profile drives the reel"
