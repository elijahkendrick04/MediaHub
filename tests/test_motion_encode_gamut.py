"""bit-depth-gamut — opt-in 10-bit / wide-gamut ENCODE profile.

Motion renders default to 8-bit ``h264 / yuv420p`` with no colour tag.
``MEDIAHUB_MOTION_ENCODE`` selects a named profile from the closed
``MOTION_ENCODE_PROFILES`` vocabulary that re-ENCODES the same brand-locked,
APCA-gated colours at higher bit-depth precision and tags the container's
gamut/transfer metadata. Off by default and folded into the cache key only when
active, so every default render stays byte-identical. The free FFmpeg engine
declares the capability ``unsupported-on-engine`` rather than faking it.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion
from mediahub.visual import reel_ffmpeg


# ---------------------------------------------------------------------------
# Profile resolver
# ---------------------------------------------------------------------------


def test_encode_profile_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    assert motion._motion_encode_profile() is None
    # empty / the two default aliases / an unknown name all resolve to None so
    # the render stays byte-identical and no arbitrary codec can be smuggled.
    for raw in ("", "  ", "default", "h264", "H264", "garbage", "prores", "av1"):
        monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", raw)
        assert motion._motion_encode_profile() is None, raw


def test_encode_profile_resolves_known_names(monkeypatch):
    for name, prof in motion.MOTION_ENCODE_PROFILES.items():
        monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", name)
        got = motion._motion_encode_profile()
        assert got == prof, name
        # case-insensitive selection
        monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", name.upper())
        assert motion._motion_encode_profile() == prof, name


def test_encode_profile_returns_a_copy(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10")
    got = motion._motion_encode_profile()
    got["codec"] = "TAMPERED"
    # Mutating the returned dict must not corrupt the shared table.
    assert motion.MOTION_ENCODE_PROFILES["h265-10"]["codec"] == "h265"
    assert motion._motion_encode_profile()["codec"] == "h265"


def _remotion_valid_sets():
    """Parse Remotion's own valid codec / pixel-format / color-space arrays from
    the installed dist so the closed vocabulary is checked against the real
    renderer. Returns (codecs, pixel_formats, color_spaces) or None if absent."""
    dist = motion.REMOTION_DIR / "node_modules" / "@remotion" / "renderer" / "dist"
    pf = dist / "pixel-format.js"
    cd = dist / "codec.js"
    cs = dist / "options" / "color-space.js"
    if not (pf.exists() and cd.exists() and cs.exists()):
        return None

    def _arr(text: str, name: str) -> set[str]:
        m = re.search(rf"{re.escape(name)}\s*=\s*\[(.*?)\]", text, re.DOTALL)
        assert m, f"could not find {name}"
        return set(re.findall(r"'([^']+)'", m.group(1)))

    codecs = _arr(cd.read_text(encoding="utf-8"), "exports.validCodecs")
    pixels = _arr(pf.read_text(encoding="utf-8"), "exports.validPixelFormats")
    # validColorSpaces is a V4/V5 ternary; the v4 list (this pin) is the literal
    # ``validV4ColorSpaces`` array — parse that directly.
    spaces = _arr(cs.read_text(encoding="utf-8"), "validV4ColorSpaces")
    return codecs, pixels, spaces


def test_profiles_are_mp4_and_valid_remotion_values():
    valid = _remotion_valid_sets()
    for prof in motion.MOTION_ENCODE_PROFILES.values():
        # All shipped profiles are MP4-container so the video/mp4 serving routes
        # need no change; ProRes/.mov is a deferred follow-up.
        assert prof["container"] == ".mp4", prof
        assert prof["colorSpace"] in (None, "bt709", "bt2020-ncl"), prof
        if valid is not None:
            codecs, pixels, spaces = valid
            assert prof["codec"] in codecs, prof["codec"]
            assert prof["pixelFormat"] in pixels, prof["pixelFormat"]
            if prof["colorSpace"] is not None:
                assert prof["colorSpace"] in spaces, prof["colorSpace"]


# ---------------------------------------------------------------------------
# _run_remotion argv threading
# ---------------------------------------------------------------------------


def _capture_run_remotion(monkeypatch):
    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run_capture(cmd, *, cwd=None, timeout=None):
        captured["cmd"] = list(cmd)
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"x" * 4096)
        return _Proc()

    monkeypatch.setattr(motion, "node_available", lambda: True)
    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)
    return captured


def test_run_remotion_cmd_byte_identical_when_off(tmp_path, monkeypatch):
    captured = _capture_run_remotion(monkeypatch)
    out = tmp_path / "card.mp4"
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=out,
        duration_sec=6.0,
        size=(1080, 1920),
        encode=None,
    )
    cmd = captured["cmd"]
    assert "--codec" not in cmd
    assert "--pixel-format" not in cmd
    assert "--color-space" not in cmd
    # temp path stays .mp4-suffixed on the OFF path
    tmp_arg = cmd[cmd.index("--output") + 1]
    assert tmp_arg.endswith(".tmp.mp4"), tmp_arg


def test_run_remotion_cmd_appends_flags_when_on(tmp_path, monkeypatch):
    captured = _capture_run_remotion(monkeypatch)
    # A colour-tagged profile appends all three flags.
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=tmp_path / "a.mp4",
        duration_sec=6.0,
        size=(1080, 1920),
        encode=motion.MOTION_ENCODE_PROFILES["h265-10-bt2020"],
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--codec") + 1] == "h265"
    assert cmd[cmd.index("--pixel-format") + 1] == "yuv420p10le"
    assert cmd[cmd.index("--color-space") + 1] == "bt2020-ncl"

    # An untagged profile (colorSpace None) appends codec+pixel-format but NOT
    # --color-space, matching Remotion's no-args 'default' behaviour.
    captured.clear()
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=tmp_path / "b.mp4",
        duration_sec=6.0,
        size=(1080, 1920),
        encode=motion.MOTION_ENCODE_PROFILES["h265-10"],
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--codec") + 1] == "h265"
    assert cmd[cmd.index("--pixel-format") + 1] == "yuv420p10le"
    assert "--color-space" not in cmd


# ---------------------------------------------------------------------------
# Cache-key fold (record-only-when-active)
# ---------------------------------------------------------------------------


def test_encode_folds_into_story_cache_key_only_when_active():
    base = {"card": {"a": 1}, "size": [1080, 1920]}
    h_plain = motion._content_hash(base, kind="story")
    assert h_plain == motion._content_hash(base, kind="story")
    h_a = motion._content_hash({**base, "encode": "h265-10"}, kind="story")
    h_b = motion._content_hash({**base, "encode": "h265-10-bt709"}, kind="story")
    assert h_plain != h_a
    assert h_a != h_b  # distinct profile names → distinct keys


def test_encode_folds_into_reel_cache_key_only_when_active():
    base = {"cards": [{"a": 1}], "size": [1080, 1920]}
    h_plain = motion._content_hash(base, kind="reel")
    assert h_plain == motion._content_hash(base, kind="reel")
    h_a = motion._content_hash({**base, "encode": "h265-10"}, kind="reel")
    h_b = motion._content_hash({**base, "encode": "h265-10-bt2020"}, kind="reel")
    assert h_plain != h_a
    assert h_a != h_b


# ---------------------------------------------------------------------------
# Story / reel path integration (mock _run_remotion — no Node)
# ---------------------------------------------------------------------------


def _fake_brand() -> BrandKit:
    return BrandKit(
        profile_id="enc-test",
        display_name="Encode Club",
        primary_colour="#0A2540",
        secondary_colour="#000000",
        accent_colour="#FFFFFF",
        short_name="EC",
    )


def _fake_card() -> dict:
    return {
        "id": "enc_c1",
        "achievement": {
            "swimmer_name": "Encode Tester",
            "event_name": "100m Free LC",
            "result_time": "00:55.00",
        },
    }


def _fake_run_remotion_factory(sink: dict):
    def _fake(**kwargs):
        sink.update(kwargs)
        out = Path(kwargs["out_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
        return out

    return _fake


def test_story_render_folds_encode_and_passes_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10-bt709")
    sink: dict = {}
    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)):
        out = tmp_path / "story.mp4"
        motion.render_story_card(_fake_card(), _fake_brand(), out)
    # The story path resolved the profile and threaded it into _run_remotion.
    assert sink.get("encode") == motion.MOTION_ENCODE_PROFILES["h265-10-bt709"]


def test_story_render_no_encode_kw_profile_when_off(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sink: dict = {}
    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)):
        out = tmp_path / "story.mp4"
        motion.render_story_card(_fake_card(), _fake_brand(), out)
    assert sink.get("encode") is None


def test_encode_forces_supersample_off(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10")
    monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", "2")
    sink: dict = {}
    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)):
        out = tmp_path / "story.mp4"
        motion.render_story_card(_fake_card(), _fake_brand(), out)
    # Mutual exclusion: encode wins, supersample forced to 1.0.
    assert sink.get("supersample") == 1.0
    assert sink.get("encode") == motion.MOTION_ENCODE_PROFILES["h265-10"]
    # Manifest records the supersample as requested-but-not-applied.
    manifest = _read_manifest(tmp_path)
    assert manifest["encode"]["profile"] == "h265-10"
    assert manifest["supersample"]["applied"] is False
    assert manifest["supersample"]["requested"] == 2.0


def _read_manifest(tmp_path: Path) -> dict:
    import json

    cache = tmp_path / "motion_cache"
    jsons = [p for p in cache.glob("*.json") if not p.name.endswith(".audio.json")]
    assert jsons, "no render manifest written"
    return json.loads(jsons[0].read_text(encoding="utf-8"))


def test_reel_forces_serial_when_encode_active(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10-bt2020")
    sink: dict = {}
    parallel_calls: list = []

    def _fake_parallel(**kwargs):
        parallel_calls.append(kwargs)
        return Path(kwargs["cached"])  # would-be success, must NOT be reached

    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=_fake_parallel),
    ):
        out = tmp_path / "reel.mp4"
        motion.render_meet_reel([_fake_card()], _fake_brand(), out)
    # The parallel composite cannot thread the profile, so it is never entered.
    assert parallel_calls == []
    assert sink.get("encode") == motion.MOTION_ENCODE_PROFILES["h265-10-bt2020"]


def test_reel_manifest_records_encode(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10")
    with patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory({})):
        out = tmp_path / "reel.mp4"
        motion.render_meet_reel([_fake_card()], _fake_brand(), out)
    manifest = _read_manifest(tmp_path)
    assert manifest["render_strategy"] == "serial"
    assert manifest["encode"]["profile"] == "h265-10"
    assert manifest["encode"]["codec"] == "h265"
    assert manifest["encode"]["color_space"] == "untagged"


# ---------------------------------------------------------------------------
# FFmpeg fallback — honest capability note
# ---------------------------------------------------------------------------


def test_ffmpeg_fallback_encode_requested_helper(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    assert reel_ffmpeg._motion_encode_requested() is False
    for raw in ("", "default", "h264"):
        monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", raw)
        assert reel_ffmpeg._motion_encode_requested() is False, raw
    for raw in ("h265-10", "garbage", "h265-10-bt2020"):
        monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", raw)
        assert reel_ffmpeg._motion_encode_requested() is True, raw


def test_ffmpeg_manifests_declare_encode_unsupported():
    """Both the story and reel FFmpeg manifests degrade honestly: the
    fold-only-when-requested ``encode: unsupported-on-engine`` note appears in
    each (guarded by ``_motion_encode_requested()``), never a faked 10-bit file."""
    src = (
        Path(reel_ffmpeg.__file__).read_text(encoding="utf-8")
        if hasattr(reel_ffmpeg, "__file__")
        else ""
    )
    assert (
        src.count('{"encode": "unsupported-on-engine"} if _motion_encode_requested() else {}') == 2
    )


# ---------------------------------------------------------------------------
# render.js byte-identity guard (source-level; no Node runtime needed)
# ---------------------------------------------------------------------------


def test_render_js_default_call_shape():
    """The JS seam must default to h264 / yuv420p / no colorSpace and spread
    colorSpace conditionally, so a render with no encode flags issues the exact
    same renderMedia call as before this feature."""
    src = (motion.REMOTION_DIR / "render.js").read_text(encoding="utf-8")
    assert 'const codecArg = args.codec || "h264";' in src
    assert 'const pixelFormatArg = args["pixel-format"] || "yuv420p";' in src
    assert 'const colorSpaceArg = args["color-space"] || null;' in src
    # renderMedia uses the resolved args and spreads colorSpace only when present.
    assert "codec: codecArg," in src
    assert "pixelFormat: pixelFormatArg," in src
    assert "...(colorSpaceArg ? { colorSpace: colorSpaceArg } : {})," in src
    # The hardcoded literals must be gone from the renderMedia call.
    assert 'codec: "h264"' not in src
    assert 'pixelFormat: "yuv420p"' not in src
