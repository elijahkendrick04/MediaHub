"""Subtitle / caption burn-in engine — roadmap R1.3.

The contract under test (visual/subtitle_burn.py + the motion wiring + the
Remotion overlay + the FFmpeg burn):

* the engine *reads the voiceover SRT* and turns it into a frame-timed track;
* the caption colour is **APCA-gated** against the card's own brand ground —
  legible by construction, never a hard-coded white;
* captions are the **verbatim** narration (the phonetic name fixes never leak
  on screen);
* it is deterministic and honest (a synthesis failure → no captions, never a
  crash or a fabricated cue);
* it is **off by default**: with MEDIAHUB_SUBTITLES unset the card props carry
  no caption track, so the cache key stays byte-identical to before R1.3;
* the Remotion overlay (captions.tsx) and the FFmpeg ASS burn both consume it.

Network-free: the one online seam (voiceover._synthesize_raw) is monkeypatched.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.theming.contrast import apca
from mediahub.visual import audio_mux, motion, subtitle_burn
from mediahub.visual.subtitle_burn import Cue
from mediahub.visual.voiceover import WordBoundary


# ---------------------------------------------------------------------------
# parse_srt — read the voiceover SRT
# ---------------------------------------------------------------------------


def test_parse_srt_empty_is_empty_list():
    assert subtitle_burn.parse_srt("") == []
    assert subtitle_burn.parse_srt("   \n\n  ") == []


def test_parse_srt_reads_cues_with_indices_and_timestamps():
    srt = (
        "1\n00:00:00,000 --> 00:00:00,900\nMaya set a new PB\n\n"
        "2\n00:00:00,900 --> 00:00:02,100\ntoday again\n"
    )
    cues = subtitle_burn.parse_srt(srt)
    assert len(cues) == 2
    assert cues[0] == Cue(0, 900, "Maya set a new PB")
    assert cues[1] == Cue(900, 2100, "today again")


def test_parse_srt_accepts_dot_fractions_and_flattens_multiline():
    srt = "00:00:01.250 --> 00:00:03.000\nline one\nline two\n"
    cues = subtitle_burn.parse_srt(srt)
    assert cues == [Cue(1250, 3000, "line one line two")]


def test_parse_srt_skips_garbled_blocks():
    srt = "not a cue\n\n1\n00:00:00,000 --> 00:00:01,000\nreal cue\n\njunk --> junk\n"
    cues = subtitle_burn.parse_srt(srt)
    assert cues == [Cue(0, 1000, "real cue")]


def test_parse_srt_round_trips_voiceover_build_srt():
    from mediahub.visual.voiceover import build_srt

    bounds = [WordBoundary("Maya", 0, 500), WordBoundary("PB", 500, 400)]
    cues = subtitle_burn.parse_srt(build_srt(bounds))
    assert cues and "Maya PB" in cues[0].text


# ---------------------------------------------------------------------------
# cues_from_text — synthetic even distribution (no SRT, e.g. a reel beat)
# ---------------------------------------------------------------------------


def test_cues_from_text_empty_inputs():
    assert subtitle_burn.cues_from_text("", 4000) == []
    assert subtitle_burn.cues_from_text("hi", 0) == []


def test_cues_from_text_single_group_spans_window():
    cues = subtitle_burn.cues_from_text("New personal best", 4000)
    assert len(cues) == 1
    assert cues[0] == Cue(0, 4000, "New personal best")


def test_cues_from_text_multi_group_stays_within_window():
    text = " ".join(f"w{i}" for i in range(20))  # 3 groups of <=7 words
    cues = subtitle_burn.cues_from_text(text, 6000)
    assert len(cues) == 3
    assert cues[0].start_ms == 0
    # The last cue never outlives the clip window.
    assert cues[-1].end_ms <= 6000
    # Cues are contiguous and ordered.
    for a, b in zip(cues, cues[1:]):
        assert b.start_ms >= a.start_ms


# ---------------------------------------------------------------------------
# caption_colours — deterministic APCA gating
# ---------------------------------------------------------------------------


def test_caption_colours_scrim_is_the_ground():
    text, scrim = subtitle_burn.caption_colours("#0A2540", "#FFFFFF", "#FFD86E")
    assert scrim == "#0A2540"
    assert text == "#FFFFFF"  # white is the most legible candidate on navy


def test_caption_colours_clears_the_apca_floor_on_any_ground():
    for ground in ("#0A2540", "#FFD86E", "#7F7F7F", "#C9A227", "#101418"):
        text, scrim = subtitle_burn.caption_colours(ground, "", "")
        assert abs(apca(text, scrim)) >= subtitle_burn.CAPTION_APCA_MIN, ground


def test_caption_colours_rejects_an_illegible_onground():
    # White onGround on a white ground is illegible — the gate must drop it and
    # fall back to a high-contrast ink rather than ship white-on-white.
    text, scrim = subtitle_burn.caption_colours("#FFFFFF", "#FFFFFF", "")
    assert text == "#000000"
    assert abs(apca(text, scrim)) >= subtitle_burn.CAPTION_APCA_MIN


def test_caption_colours_blank_ground_uses_safe_default():
    text, scrim = subtitle_burn.caption_colours("", "", "")
    assert scrim == "#0A0B11"
    assert abs(apca(text, scrim)) >= subtitle_burn.CAPTION_APCA_MIN


def test_caption_colours_normalises_short_hex():
    text, scrim = subtitle_burn.caption_colours("#fff", "#000", "")
    assert scrim == "#FFFFFF" and text == "#000000"


# ---------------------------------------------------------------------------
# cues_to_frames + build_track
# ---------------------------------------------------------------------------


def test_cues_to_frames_converts_ms_to_frames_at_fps():
    frames = subtitle_burn.cues_to_frames([Cue(0, 1000, "a"), Cue(1000, 2000, "b")], fps=30)
    assert frames == [
        {"from": 0, "dur": 30, "text": "a"},
        {"from": 30, "dur": 30, "text": "b"},
    ]


def test_cues_to_frames_clamps_to_total_frames():
    # A cue overrunning the clip is truncated; one starting past the end drops.
    frames = subtitle_burn.cues_to_frames(
        [Cue(0, 5000, "long"), Cue(7000, 8000, "after")], fps=30, total_frames=120
    )
    assert len(frames) == 1
    assert frames[0]["from"] == 0
    assert frames[0]["from"] + frames[0]["dur"] <= 120


def test_cues_to_frames_drops_empty_text_and_guarantees_min_duration():
    frames = subtitle_burn.cues_to_frames([Cue(0, 10, "x"), Cue(20, 20, "  ")], fps=30)
    assert all(f["dur"] >= 1 for f in frames)
    assert [f["text"] for f in frames] == ["x"]


def test_build_track_none_when_no_cues():
    assert subtitle_burn.build_track([], fps=30, total_frames=180) is None


def test_build_track_shape_and_colours():
    track = subtitle_burn.build_track(
        [Cue(0, 1000, "New PB")], fps=30, total_frames=180, ground="#0A2540", onground="#FFFFFF"
    )
    assert track is not None
    assert set(track) == {"color", "scrim", "cues"}
    assert track["scrim"] == "#0A2540"
    assert track["color"] == "#FFFFFF"
    assert track["cues"] == [{"from": 0, "dur": 30, "text": "New PB"}]


def test_track_json_none_is_empty_string_and_round_trips():
    assert subtitle_burn.track_json(None) == ""
    track = subtitle_burn.build_track([Cue(0, 1000, "hi")], fps=30, total_frames=60)
    s = subtitle_burn.track_json(track)
    assert json.loads(s) == track
    # Deterministic: same inputs → identical serialisation.
    assert s == subtitle_burn.track_json(
        subtitle_burn.build_track([Cue(0, 1000, "hi")], fps=30, total_frames=60)
    )


# ---------------------------------------------------------------------------
# story_caption_track — reads the synthesised voiceover SRT
# ---------------------------------------------------------------------------


def _fake_synth_echo(text, voice):
    """Echo each word as a 400ms boundary so the SRT mirrors the input."""
    bounds, t = [], 0
    for w in text.split():
        bounds.append(WordBoundary(w, t, 400))
        t += 400
    return b"ID3audio", bounds


def test_story_caption_track_reads_the_srt(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    track = subtitle_burn.story_caption_track(
        "Maya set a new PB", voice="en-GB-SoniaNeural", duration_sec=6.0, ground="#0A2540"
    )
    assert track is not None
    joined = " ".join(c["text"] for c in track["cues"])
    assert "Maya" in joined and "PB" in joined
    assert track["scrim"] == "#0A2540"


def test_story_caption_track_shows_original_spelling_not_pronunciation(tmp_path, monkeypatch):
    """A phonetic override is for the TTS, never the screen — captions read the
    original caption spelling (apply_pronunciation=False)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    (tmp_path / "pronunciations.json").write_text(json.dumps({"Siobhan": "Shiv-awn"}))
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    track = subtitle_burn.story_caption_track(
        "Well done Siobhan", voice="v", duration_sec=6.0, ground="#0A2540"
    )
    assert track is not None
    joined = " ".join(c["text"] for c in track["cues"])
    assert "Siobhan" in joined
    assert "Shiv-awn" not in joined


def test_story_caption_track_none_on_empty_or_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert subtitle_burn.story_caption_track("  ", voice="v", duration_sec=6.0) is None

    def _boom(text, voice):
        raise RuntimeError("backend down")

    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _boom)
    assert subtitle_burn.story_caption_track("real", voice="v", duration_sec=6.0) is None


def test_story_caption_track_uses_voiceover_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls = {"n": 0}

    def _counting(text, voice):
        calls["n"] += 1
        return _fake_synth_echo(text, voice)

    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _counting)
    subtitle_burn.story_caption_track("Maya PB", voice="v", duration_sec=6.0)
    subtitle_burn.story_caption_track("Maya PB", voice="v", duration_sec=6.0)
    assert calls["n"] == 1  # second call is a cache hit


# ---------------------------------------------------------------------------
# text_caption_track — reel-beat path (no synthesis)
# ---------------------------------------------------------------------------


def test_text_caption_track_builds_without_synthesis():
    track = subtitle_burn.text_caption_track(
        "New PB Maya Smith 54.32 seconds", total_frames=120, ground="#0A2540"
    )
    assert track is not None
    assert track["cues"]
    assert all(c["from"] + c["dur"] <= 120 for c in track["cues"])


def test_text_caption_track_none_on_empty():
    assert subtitle_burn.text_caption_track("", total_frames=120) is None
    assert subtitle_burn.text_caption_track("hi", total_frames=0) is None


# ---------------------------------------------------------------------------
# ASS document + filter (FFmpeg burn-in)
# ---------------------------------------------------------------------------


def _track() -> dict:
    return {
        "color": "#FFFFFF",
        "scrim": "#0A2540",
        "cues": [{"from": 0, "dur": 30, "text": "New PB"}, {"from": 30, "dur": 30, "text": "Maya"}],
    }


def test_ass_document_structure_and_timestamps():
    doc = subtitle_burn.ass_document(_track(), width=1080, height=1920)
    assert "[Script Info]" in doc and "[V4+ Styles]" in doc and "[Events]" in doc
    assert "Style: Caption," in doc
    assert doc.count("Dialogue:") == 2
    assert "New PB" in doc and "Maya" in doc
    # 30 frames @ 30fps == 1.00s; bottom-centre opaque box (BorderStyle 4, Align 2).
    assert "0:00:00.00" in doc and "0:00:01.00" in doc
    assert ",4,0,0,2," in doc


def test_ass_document_uses_apca_gated_primary_colour():
    doc = subtitle_burn.ass_document(_track(), width=1080, height=1920)
    assert "&H00FFFFFF" in doc  # opaque white text (ASS &HAABBGGRR)


def test_ass_filter_escapes_path_metacharacters():
    assert subtitle_burn.ass_filter("/tmp/a/c.ass") == "ass=/tmp/a/c.ass"
    assert subtitle_burn.ass_filter("/t:mp/c.ass") == "ass=/t\\:mp/c.ass"


# ---------------------------------------------------------------------------
# Motion wiring — off by default, opt-in, cache-key discipline, manifest
# ---------------------------------------------------------------------------

BRAND = BrandKit(
    profile_id="subs",
    display_name="Subs SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="SUBS",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-sub-{i}",
        "swim_id": f"swim-sub-{i}",
        "achievement": {
            "swim_id": f"swim-sub-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Subtitle Invitational",
    }


def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"0" * 2048)
    return out


def _voice_on(monkeypatch):
    monkeypatch.setattr(audio_mux, "voice_active", lambda: True)
    monkeypatch.setattr(audio_mux, "voice_name", lambda: "en-GB-SoniaNeural")


def _stub_finishing(monkeypatch):
    def _apply(video, plan, *, duration_sec):
        return {"status": "mixed", "voice": plan.get("voice", ""), "music": "", "transcript": ""}

    def _poster(video, poster, *, at_sec):
        Path(poster).write_bytes(b"\x89PNG")
        return True

    monkeypatch.setattr(audio_mux, "apply_audio", _apply)
    monkeypatch.setattr(audio_mux, "write_poster", _poster)


def test_subtitles_off_by_default_no_caption_prop(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_SUBTITLES", raising=False)
    _voice_on(monkeypatch)
    _stub_finishing(monkeypatch)
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return _fake_run(**kwargs)

    with mock.patch.object(motion, "_run_remotion", side_effect=_capture):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "s.mp4")
    assert "captionsJson" not in captured["props"]["card"]


def test_subtitles_off_keeps_cache_key_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_SUBTITLES", raising=False)
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "s.mp4")
    # The historic (pre-R1.3) key: card props with no captionsJson.
    brand_dict = motion._brand_to_dict(BRAND)
    card_dict = motion._card_to_props(_card(1), variation_seed=0, brief=None, brand_kit=BRAND)
    expected = motion._content_hash(
        {"card": card_dict, "brand": brand_dict, "duration": 6.0, "size": [1080, 1920]},
        kind="story",
    )
    assert (motion._cache_dir() / f"{expected}.mp4").exists()


def test_subtitles_on_injects_caption_track_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_SUBTITLES", "1")
    _voice_on(monkeypatch)
    _stub_finishing(monkeypatch)
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return _fake_run(**kwargs)

    with mock.patch.object(motion, "_run_remotion", side_effect=_capture):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "s.mp4")

    cap_json = captured["props"]["card"]["captionsJson"]
    track = json.loads(cap_json)
    assert track["cues"], "a caption track must be injected when subtitles are on"
    # Narration speaks the card's own facts → the captions carry them.
    joined = " ".join(c["text"] for c in track["cues"])
    assert "Swimmer 1" in joined
    # APCA-legible on the resolved ground.
    assert abs(apca(track["color"], track["scrim"])) >= subtitle_burn.CAPTION_APCA_MIN

    manifest = json.loads(
        next(
            p
            for p in motion._cache_dir().glob("*.json")
            if p.parent == motion._cache_dir() and not p.name.endswith(".audio.json")
        ).read_text()
    )
    assert manifest["captions"]["status"] == "on"
    assert manifest["captions"]["cues"] == len(track["cues"])


def test_subtitles_change_the_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _voice_on(monkeypatch)
    _stub_finishing(monkeypatch)
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)

    monkeypatch.setenv("MEDIAHUB_SUBTITLES", "1")
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "on.mp4")
    on_keys = {p.stem for p in motion._cache_dir().glob("*.mp4")}

    monkeypatch.delenv("MEDIAHUB_SUBTITLES", raising=False)
    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_story_card(_card(1), BRAND, tmp_path / "out" / "off.mp4")
    all_keys = {p.stem for p in motion._cache_dir().glob("*.mp4")}
    # A captioned render and a silent one never share a cache entry.
    assert len(all_keys) == 2 and on_keys < all_keys


def test_story_caption_json_helper_gating(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    brand_dict = motion._brand_to_dict(BRAND)
    card_dict = motion._card_to_props(_card(1), variation_seed=0, brief=None, brand_kit=BRAND)
    plan = {"voice": "en-GB-SoniaNeural", "script": "Swimmer 1, 100m Freestyle, 1 minute."}

    monkeypatch.delenv("MEDIAHUB_SUBTITLES", raising=False)
    assert motion._story_caption_json(card_dict, brand_dict, plan, duration_sec=6.0) == ""

    monkeypatch.setenv("MEDIAHUB_SUBTITLES", "1")
    assert motion._story_caption_json(card_dict, brand_dict, None, duration_sec=6.0) == ""
    assert motion._story_caption_json(card_dict, brand_dict, {"music": "x.mp3"}, duration_sec=6.0) == ""
    assert motion._story_caption_json(card_dict, brand_dict, plan, duration_sec=6.0) != ""


def test_reel_subtitles_inject_per_beat_tracks(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_SUBTITLES", "1")
    _voice_on(monkeypatch)
    _stub_finishing(monkeypatch)
    monkeypatch.setattr("mediahub.visual.voiceover._synthesize_raw", _fake_synth_echo)
    captured: dict = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return _fake_run(**kwargs)

    with mock.patch.object(motion, "_run_remotion", side_effect=_capture):
        motion.render_meet_reel([_card(1), _card(2)], BRAND, tmp_path / "out" / "reel.mp4")

    cards = captured["props"]["cards"]
    assert all(c.get("captionsJson") for c in cards), "each beat must carry its own captions"
    track0 = json.loads(cards[0]["captionsJson"])
    assert "Swimmer 1" in " ".join(c["text"] for c in track0["cues"])

    manifest = json.loads(
        next(
            p
            for p in motion._cache_dir().glob("*.json")
            if p.parent == motion._cache_dir() and not p.name.endswith(".audio.json")
        ).read_text()
    )
    assert manifest["captions"]["status"] == "on"
    assert len(manifest["captions"]["cues_per_card"]) == 2


def test_reel_caption_json_builds_from_card_line():
    brand_dict = motion._brand_to_dict(BRAND)
    card_dict = motion._card_to_props(_card(1), variation_seed=0, brief=None, brand_kit=BRAND)
    cj = motion._reel_caption_json(card_dict, brand_dict, beat_frames=120)
    assert cj
    track = json.loads(cj)
    assert "Swimmer 1" in " ".join(c["text"] for c in track["cues"])


# ---------------------------------------------------------------------------
# FFmpeg story burn (engine parity)
# ---------------------------------------------------------------------------


def test_story_ffmpeg_args_appends_ass_filter_when_given():
    from mediahub.visual import reel_ffmpeg

    args = reel_ffmpeg.story_ffmpeg_args(
        Path("s.png"), Path("o.mp4"), 6.0, ass_path=Path("/tmp/cap.ass")
    )
    vf = args[args.index("-vf") + 1]
    assert "ass=/tmp/cap.ass" in vf

    plain = reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0)
    assert "ass=" not in plain[plain.index("-vf") + 1]


def test_write_caption_ass_helper(tmp_path):
    from mediahub.visual import reel_ffmpeg

    good = subtitle_burn.track_json(
        subtitle_burn.build_track([Cue(0, 1000, "hi")], fps=30, total_frames=60, ground="#0A2540")
    )
    p = reel_ffmpeg._write_caption_ass(good, tmp_path, "story")
    assert p is not None and p.exists() and "Dialogue:" in p.read_text()

    assert reel_ffmpeg._write_caption_ass("", tmp_path, "x") is None
    assert reel_ffmpeg._write_caption_ass("{not json", tmp_path, "x") is None


# ---------------------------------------------------------------------------
# TSX / schema source contracts (no Node needed)
# ---------------------------------------------------------------------------


def _compositions() -> Path:
    return motion.REMOTION_DIR / "src" / "compositions"


def test_captions_layer_source_contract():
    src = (_compositions() / "sprint" / "layers" / "captions.tsx").read_text()
    assert "card.captionsJson" in src, "the layer must read the caption track prop"
    assert "Sequence" in src, "one cue at a time via <Sequence> windows"
    assert "useCurrentFrame" in src, "frame-pure entrance"
    assert "tabular-nums" in src, "times must not wobble"
    assert "export default" in src and "order" in src, "drop-in contract"
    # Self-hosted fonts only — never a CDN.
    assert "googleapis" not in src and "gstatic" not in src


def test_card_schema_declares_captions_json():
    src = (_compositions() / "StoryCard.tsx").read_text()
    assert "captionsJson: z.string().default" in src


def test_root_default_card_includes_captions_json():
    src = (motion.REMOTION_DIR / "src" / "Root.tsx").read_text()
    assert 'captionsJson: ""' in src
