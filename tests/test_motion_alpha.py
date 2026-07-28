"""alpha-export — opt-in transparent-background (alpha) motion export.

Motion renders default to opaque ``h264 / yuv420p`` ``.mp4``. ``?alpha=``
(``prores4444`` / ``vp9``) is an opt-in Remotion-only compositing export: the
composition's outer full-bleed ground fill is suppressed via a false-default
``transparentBg`` prop, the render is encoded into an alpha container
(``.mov``/``.webm``) with a distinct cache key, the whole-composition
supersample is forced off, and the asset is silent by design. Off by default and
folded into the cache key only when active, so every default render stays
byte-identical. The free FFmpeg engine cannot produce a transparent asset, so an
alpha request there raises ``AlphaUnsupportedError`` (a deliberate deviation from
degrade-and-ship — a mislabeled opaque file would be a lie).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion
from mediahub.visual import reel_ffmpeg


# ---------------------------------------------------------------------------
# Profile resolver + closed vocabulary
# ---------------------------------------------------------------------------


def test_resolve_alpha_profile():
    # "" / whitespace / unknown → None (alpha OFF, byte-identical default).
    for raw in ("", "  ", "default", "h264", "garbage", "prores", "av1", "mp4"):
        assert motion.resolve_alpha_profile(raw) is None, raw
    # Known names resolve to the canonical tuple; case-insensitive + trimmed.
    pr = motion.resolve_alpha_profile("prores4444")
    assert pr == motion._AlphaProfile(
        "prores4444", "prores", "yuva444p10le", "4444", "mov", "video/quicktime"
    )
    assert motion.resolve_alpha_profile("  PRORES4444 ") == pr
    vp = motion.resolve_alpha_profile("vp9")
    assert vp == motion._AlphaProfile("vp9", "vp9", "yuva420p", "", "webm", "video/webm")
    assert motion.resolve_alpha_profile("VP9") == vp
    # vp9 carries NO prores profile (Remotion throws if proResProfile is set with
    # a non-prores codec) — the empty string is the sentinel for "drop it".
    assert vp.prores_profile == ""


def _remotion_valid_sets():
    """Parse Remotion's own valid codec / pixel-format arrays + the ProRes profile
    list from the installed dist, so the alpha vocabulary is checked against the
    real renderer. Returns (codecs, pixel_formats, prores_profiles) or None."""
    dist = motion.REMOTION_DIR / "node_modules" / "@remotion" / "renderer" / "dist"
    rmt = motion.REMOTION_DIR / "node_modules" / "remotion" / "dist" / "cjs"
    pf = dist / "pixel-format.js"
    cd = dist / "codec.js"
    if not (pf.exists() and cd.exists()):
        return None

    def _arr(text: str, name: str) -> set[str]:
        m = re.search(rf"{re.escape(name)}\s*=\s*\[(.*?)\]", text, re.DOTALL)
        assert m, f"could not find {name}"
        return set(re.findall(r"'([^']+)'", m.group(1)))

    codecs = _arr(cd.read_text(encoding="utf-8"), "exports.validCodecs")
    pixels = _arr(pf.read_text(encoding="utf-8"), "exports.validPixelFormats")
    # ProRes profiles live in remotion/dist/.../prores_profile.js as
    # proResProfileOptions; parse loosely (path varies), else skip that check.
    profiles: set[str] = set()
    for p in motion.REMOTION_DIR.glob("node_modules/remotion/dist/**/prores_profile.js"):
        m = re.search(
            r"proResProfileOptions\s*=\s*\[(.*?)\]", p.read_text(encoding="utf-8"), re.DOTALL
        )
        if m:
            profiles = set(re.findall(r"'([^']+)'", m.group(1)))
            break
    return codecs, pixels, profiles


def test_alpha_profiles_are_valid_remotion_values():
    valid = _remotion_valid_sets()
    if valid is None:
        pytest.skip("Remotion dist not installed")
    codecs, pixels, profiles = valid
    for prof in motion.ALPHA_PROFILES.values():
        assert prof.codec in codecs, prof.codec
        assert prof.pixel_format in pixels, prof.pixel_format
        assert prof.ext in ("mov", "webm"), prof.ext
        assert prof.content_type in ("video/quicktime", "video/webm"), prof.content_type
        if prof.prores_profile and profiles:
            assert prof.prores_profile in profiles, prof.prores_profile
    # Internal consistency: proResProfile only ever rides with the prores codec.
    for prof in motion.ALPHA_PROFILES.values():
        if prof.prores_profile:
            assert prof.codec == "prores", prof


def test_alpha_encode_dict_shape():
    pr = motion._alpha_encode(motion.resolve_alpha_profile("prores4444"))
    assert pr["codec"] == "prores"
    assert pr["pixelFormat"] == "yuva444p10le"
    assert pr["proResProfile"] == "4444"
    assert pr["colorSpace"] is None
    assert pr["container"] == ".mov"
    assert pr["alpha"] is True
    vp = motion._alpha_encode(motion.resolve_alpha_profile("vp9"))
    assert vp["codec"] == "vp9"
    assert vp["pixelFormat"] == "yuva420p"
    # No proResProfile key at all for vp9 (never send it with a non-prores codec).
    assert "proResProfile" not in vp
    assert vp["container"] == ".webm"


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
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=tmp_path / "card.mp4",
        duration_sec=6.0,
        size=(1080, 1920),
        encode=None,
    )
    cmd = captured["cmd"]
    assert "--codec" not in cmd
    assert "--pixel-format" not in cmd
    assert "--prores-profile" not in cmd
    # The atomic temp file stays a .tmp.mp4 dotfile on the OFF path.
    out_arg = cmd[cmd.index("--output") + 1]
    assert out_arg.endswith(".tmp.mp4")


def test_run_remotion_cmd_appends_prores_flags(tmp_path, monkeypatch):
    captured = _capture_run_remotion(monkeypatch)
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=tmp_path / "card.mov",
        duration_sec=6.0,
        size=(1080, 1920),
        encode=motion._alpha_encode(motion.resolve_alpha_profile("prores4444")),
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--codec") + 1] == "prores"
    assert cmd[cmd.index("--pixel-format") + 1] == "yuva444p10le"
    assert cmd[cmd.index("--prores-profile") + 1] == "4444"
    assert "--color-space" not in cmd
    out_arg = cmd[cmd.index("--output") + 1]
    assert out_arg.endswith(".tmp.mov")


def test_run_remotion_cmd_appends_vp9_flags_no_prores(tmp_path, monkeypatch):
    captured = _capture_run_remotion(monkeypatch)
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=tmp_path / "card.webm",
        duration_sec=6.0,
        size=(1080, 1920),
        encode=motion._alpha_encode(motion.resolve_alpha_profile("vp9")),
    )
    cmd = captured["cmd"]
    assert cmd[cmd.index("--codec") + 1] == "vp9"
    assert cmd[cmd.index("--pixel-format") + 1] == "yuva420p"
    # vp9 must NOT carry a --prores-profile (Remotion throws otherwise).
    assert "--prores-profile" not in cmd
    out_arg = cmd[cmd.index("--output") + 1]
    assert out_arg.endswith(".tmp.webm")


# ---------------------------------------------------------------------------
# Story / reel path integration (mock _run_remotion — no Node)
# ---------------------------------------------------------------------------


def _fake_brand() -> BrandKit:
    return BrandKit(
        profile_id="alpha-test",
        display_name="Alpha Club",
        primary_colour="#0A2540",
        secondary_colour="#000000",
        accent_colour="#FFFFFF",
        short_name="AC",
    )


def _fake_card() -> dict:
    return {
        "id": "alpha_c1",
        "achievement": {
            "swimmer_name": "Alpha Tester",
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


def _capture_cache_payload():
    """Patch _content_hash to record the last cache_payload it hashed."""
    seen: dict = {}
    real = motion._content_hash

    def _spy(payload, *, kind):
        seen["payload"] = dict(payload)
        seen["kind"] = kind
        return real(payload, kind=kind)

    return seen, _spy


def _read_manifest(tmp_path: Path) -> dict:
    import json

    cache = tmp_path / "motion_cache"
    jsons = [p for p in cache.glob("*.json") if not p.name.endswith(".audio.json")]
    assert jsons, "no render manifest written"
    return json.loads(jsons[0].read_text(encoding="utf-8"))


def test_story_cache_key_byte_identical_without_alpha(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_story_card(
            _fake_card(), _fake_brand(), tmp_path / "story.mp4", alpha_profile=""
        )
    payload = seen["payload"]
    # No alpha fold, no transparentBg prop, .mp4 slot, no encode kw.
    assert "alpha" not in payload
    assert "transparentBg" not in payload["card"]
    assert sink.get("encode") is None
    assert Path(sink["out_path"]).suffix == ".mp4"


def test_story_alpha_folds_key_prop_and_ext(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", "2")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_story_card(
            _fake_card(), _fake_brand(), tmp_path / "story.mov", alpha_profile="prores4444"
        )
    payload = seen["payload"]
    assert payload["alpha"] == "prores4444"
    # Alpha uses a dedicated key, never the bit-depth "encode" fold.
    assert "encode" not in payload
    # No audio fold (silent by design).
    assert "audio" not in payload
    assert payload["card"]["transparentBg"] is True
    # Alpha forces supersample off even though MEDIAHUB_MOTION_SUPERSAMPLE=2.
    assert sink.get("supersample") == 1.0
    # Encode dict threaded with the prores profile; cached slot ends .mov.
    enc = sink.get("encode")
    assert enc["codec"] == "prores" and enc["proResProfile"] == "4444"
    assert Path(sink["out_path"]).suffix == ".mov"
    # Manifest carries the honest alpha block, not the bit-depth encode block.
    manifest = _read_manifest(tmp_path)
    assert manifest["alpha"]["profile"] == "prores4444"
    assert manifest["alpha"]["container"] == "mov"
    assert "encode" not in manifest
    # …and records the suppressed supersample honestly, like the encode branch.
    ss = manifest["supersample"]
    assert ss["requested"] == 2.0
    assert ss["applied"] is False
    assert "alpha" in ss["reason"]


def test_reel_alpha_forces_serial_and_props(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    parallel_calls: list = []

    def _fake_parallel(**kwargs):
        parallel_calls.append(kwargs)
        return Path(kwargs["cached"])  # would-be success, must NOT be reached

    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=_fake_parallel),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.webm", alpha_profile="vp9"
        )
    # Parallel composite cannot thread alpha, so it is never entered.
    assert parallel_calls == []
    payload = seen["payload"]
    assert payload["alpha"] == "vp9"
    assert "audio" not in payload
    # Reel-level prop drives the cover/outro; every card beat carries its own.
    reel_props = sink["props"]
    assert reel_props["transparentBg"] is True
    assert all(cp.get("transparentBg") is True for cp in reel_props["cards"])
    assert Path(sink["out_path"]).suffix == ".webm"
    manifest = _read_manifest(tmp_path)
    assert manifest["render_strategy"] == "serial"
    assert manifest["alpha"]["profile"] == "vp9"


def test_reel_cache_key_byte_identical_without_alpha(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory({})),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.mp4", alpha_profile=""
        )
    assert "alpha" not in seen["payload"]


def _assemble_with_captions(monkeypatch):
    """Wrap _assemble_reel_props so every beat carries a baked caption track, as a
    voiceover+subtitles reel would — WITHOUT setting up narration/audio. Returns the
    call counter so a test can prove the captions really existed before any strip."""
    real = motion._assemble_reel_props
    counter = {"beats_captioned": 0}

    def _wrapped(*a, **k):
        result = real(*a, **k)
        cards = result[0]
        for cp in cards:
            cp["captionsJson"] = '[{"t":0,"d":1,"text":"HI"}]'
            counter["beats_captioned"] += 1
        return result

    monkeypatch.setattr(motion, "_assemble_reel_props", _wrapped)
    return counter


def test_reel_alpha_strips_burn_in_captions(tmp_path, monkeypatch):
    """A transparent (alpha) reel is silent by design, so a burn-in caption track
    baked upstream by _assemble_reel_props must be dropped — otherwise it would ship a
    silent transparent asset with hardcoded narration captions, contradicting the
    'clean compositing asset' contract and the story path (which nulls audio before its
    caption build). The strip lands before the cache-payload fold, so a caption-free
    alpha reel keys distinctly and never collides with a captioned opaque reel."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    counter = _assemble_with_captions(monkeypatch)
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.webm", alpha_profile="vp9"
        )
    # Captions WERE baked (real strip, not a never-created no-op)…
    assert counter["beats_captioned"] >= 1
    # …and every rendered beat had the track removed under alpha (cover/outro carry none).
    cards = sink["props"]["cards"]
    assert cards and all("captionsJson" not in cp for cp in cards)


def test_reel_non_alpha_keeps_burn_in_captions(tmp_path, monkeypatch):
    """Control: the strip is alpha-ONLY. The same baked caption track rides through an
    ordinary opaque reel unchanged (byte-identical to today)."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _assemble_with_captions(monkeypatch)
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.mp4", alpha_profile=""
        )
    cards = sink["props"]["cards"]
    assert cards and all(cp.get("captionsJson") for cp in cards)


# ---------------------------------------------------------------------------
# FFmpeg engine — honest typed error (deliberate deviation from degrade-and-ship)
# ---------------------------------------------------------------------------


def test_story_alpha_raises_on_ffmpeg_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "_dispatch_engine", lambda: "ffmpeg")
    with pytest.raises(motion.AlphaUnsupportedError):
        motion.render_story_card(
            _fake_card(), _fake_brand(), tmp_path / "story.mov", alpha_profile="prores4444"
        )


def test_reel_alpha_raises_on_ffmpeg_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "_dispatch_engine", lambda: "ffmpeg")
    with pytest.raises(motion.AlphaUnsupportedError):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.webm", alpha_profile="vp9"
        )


def test_ffmpeg_engine_no_alpha_still_renders_normally(tmp_path, monkeypatch):
    """A NON-alpha request on the ffmpeg engine must not be perturbed by the
    alpha guard — it falls through to the normal (mocked) ffmpeg path."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "_dispatch_engine", lambda: "ffmpeg")
    called: dict = {}

    def _fake_ffmpeg_story(*args, **kwargs):
        called["hit"] = True
        out = Path(args[3])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x" * 4096)
        return out

    with patch.object(reel_ffmpeg, "render_story_card_from_props", side_effect=_fake_ffmpeg_story):
        motion.render_story_card(
            _fake_card(), _fake_brand(), tmp_path / "story.mp4", alpha_profile=""
        )
    assert called.get("hit") is True


def test_ffmpeg_manifests_declare_alpha_unsupported():
    """Belt-and-braces honesty: both the story and reel FFmpeg manifests carry
    the fold-only-when-requested ``alpha: unsupported-on-engine`` note (guarded
    by the ``alpha_profile`` param), never a mislabeled opaque file. Source-level
    like the bit-depth encode guard, so no ffmpeg binary is required."""
    src = Path(reel_ffmpeg.__file__).read_text(encoding="utf-8")
    assert src.count('{"alpha": "unsupported-on-engine"} if alpha_profile else {}') == 2


# ---------------------------------------------------------------------------
# Cache-prune glob widening (disk-leak guard)
# ---------------------------------------------------------------------------


def test_prune_sweeps_alpha_slots_and_excludes_dotfiles(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "2")
    cache = tmp_path / "motion_cache"
    cache.mkdir(parents=True, exist_ok=True)
    import time

    # Three real entries across the three containers, ascending mtime.
    slots = [("aaa.mp4", 1000), ("bbb.mov", 2000), ("ccc.webm", 3000)]
    for name, mt in slots:
        p = cache / name
        p.write_bytes(b"x" * 4096)
        # Each entry brings a manifest + poster sidecar sharing its stem.
        (cache / (Path(name).stem + ".json")).write_text("{}")
        (cache / (Path(name).stem + ".poster.png")).write_bytes(b"p")
        import os

        os.utime(p, (mt, mt))
    # An in-flight alpha tmp dotfile must be excluded from the cap + never swept.
    tmp_dot = cache / ".ccc.123.456.tmp.webm"
    tmp_dot.write_bytes(b"x" * 4096)

    motion._prune_motion_cache(cache)

    # Cap is 2 → the oldest (aaa.mp4) is evicted with its sidecars; the alpha
    # .mov/.webm slots count toward the cap and survive as the newest two.
    assert not (cache / "aaa.mp4").exists()
    assert not (cache / "aaa.json").exists()
    assert not (cache / "aaa.poster.png").exists()
    assert (cache / "bbb.mov").exists()
    assert (cache / "ccc.webm").exists()
    # The dotfile tmp is never counted or evicted.
    assert tmp_dot.exists()
    _ = time  # silence unused import on some linters


def test_prune_default_only_mp4_unchanged(tmp_path, monkeypatch):
    """With zero alpha files present the widened glob returns the identical .mp4
    set, so DEFAULT prune behaviour is byte-identical."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_CACHE_MAX", "1")
    cache = tmp_path / "motion_cache"
    cache.mkdir(parents=True, exist_ok=True)
    import os

    for name, mt in (("old.mp4", 1000), ("new.mp4", 2000)):
        p = cache / name
        p.write_bytes(b"x" * 4096)
        os.utime(p, (mt, mt))
    motion._prune_motion_cache(cache)
    assert not (cache / "old.mp4").exists()
    assert (cache / "new.mp4").exists()


# ---------------------------------------------------------------------------
# render.js seam + no-revision-bump guard (source-level; no Node runtime needed)
# ---------------------------------------------------------------------------


def test_render_js_prores_profile_spread():
    """render.js reads --prores-profile and spreads proResProfile ONLY when
    present, mirroring the --scale / colorSpace conditional spreads, so the
    DEFAULT (no flags) renderMedia call stays byte-identical."""
    src = (motion.REMOTION_DIR / "render.js").read_text(encoding="utf-8")
    assert 'const proResProfileArg = args["prores-profile"] || null;' in src
    assert "...(proResProfileArg ? { proResProfile: proResProfileArg } : {})," in src
    # The bit-depth-gamut defaults must remain intact (byte-identical OFF path).
    assert 'const codecArg = args.codec || "h264";' in src
    assert 'const pixelFormatArg = args["pixel-format"] || "yuv420p";' in src


def test_alpha_does_not_bump_composition_revisions():
    """alpha-export adds NO new TSX component — it only gates an existing fill
    behind a false-default boolean (the footage-beat precedent, not dither's
    new-component case). renderer_generation() re-fingerprints the .tsx/.js edits
    once for everyone, so the per-composition revisions must NOT bump."""
    # The pinned values track later unrelated legit bumps — currently "9"/"12"
    # from the glyph-kern parity fix (engine-math-1/-6), not alpha-export.
    assert motion.STORY_COMPOSITION_REVISION == "9"
    assert motion.REEL_COMPOSITION_REVISION == "12"


def test_transparent_bg_prop_gates_fill_in_tsx():
    """The false-default transparentBg prop must suppress the outer ground fill
    (and full-bleed meshBg) in StoryCard, and the cover/outro fills in MeetReel,
    so the OFF-path DOM is byte-identical."""
    story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text(
        encoding="utf-8"
    )
    assert "transparentBg: z.boolean().default(false)" in story
    assert "...(card.transparentBg ? {} : { backgroundColor: roles.ground })" in story
    assert "&& !card.transparentBg" in story  # meshBg suppressed too
    reel = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text(
        encoding="utf-8"
    )
    assert "transparentBg: z.boolean().default(false)" in reel
    assert reel.count("...(transparentBg") >= 2  # cover + outro fills gated


def test_dither_mount_is_transparent_bg_gated():
    """The Dither overlay is a fully OPAQUE near-neutral tile whose
    mix-blend-mode:overlay resolves to itself over a transparent backdrop —
    unmounted, a dither-brief card's alpha export would composite its whole
    "transparent" region as solid grey. Every Dither mount (StoryCard's card
    layer, MeetReel's cover + outro bookends) must therefore be gated off under
    transparentBg; the false default keeps the OFF-path DOM byte-identical."""
    story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text(
        encoding="utf-8"
    )
    assert "{card.dither && !card.transparentBg ? <Dither /> : null}" in story
    assert "{card.dither ? <Dither /> : null}" not in story
    reel = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text(
        encoding="utf-8"
    )
    assert reel.count("{dither && !transparentBg ? <Dither /> : null}") == 2
    assert "{dither ? <Dither /> : null}" not in reel


def test_render_js_alpha_image_format_spread():
    """Remotion requires PNG video frames for the alpha pixel formats
    (validateSelectedPixelFormatAndImageFormatCombination throws for yuva* with
    the default 'jpeg', and jpeg frames carry no alpha channel anyway).
    render.js must spread imageFormat:'png' ONLY on the alpha path, mirroring
    the scale/colorSpace/proResProfile spreads, so the default renderMedia call
    stays byte-identical. The cross-validator test below executes the installed
    dist against this exact rule."""
    src = (motion.REMOTION_DIR / "render.js").read_text(encoding="utf-8")
    assert '...(pixelFormatArg.startsWith("yuva") ? { imageFormat: "png" } : {}),' in src


# ---------------------------------------------------------------------------
# Dist-level cross-validator parity (executes the INSTALLED Remotion validators)
# ---------------------------------------------------------------------------


def _renderer_dist():
    d = motion.REMOTION_DIR / "node_modules" / "@remotion" / "renderer" / "dist"
    needed = ("image-format.js", "pixel-format.js", "prores-profile.js")
    return d if all((d / n).exists() for n in needed) else None


def _effective_image_format(pixel_format: str) -> str:
    """The imageFormat renderMedia actually validates for a render.js call:
    render.js spreads imageFormat:'png' only for the alpha (yuva*) pixel
    formats; otherwise renderMedia resolves DEFAULT_VIDEO_IMAGE_FORMAT
    ('jpeg'). Kept honest by test_render_js_alpha_image_format_spread, which
    pins the render.js rule this mirrors."""
    return "png" if pixel_format.startswith("yuva") else "jpeg"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_profiles_pass_installed_remotion_cross_validators():
    """Run every shipped profile's exact codec × pixelFormat × imageFormat ×
    proResProfile combination through the INSTALLED dist's combination
    validators (pixelFormat↔imageFormat, pixelFormat↔codec, codec↔proResProfile).

    Membership checks alone missed this rule class: every individual alpha
    value was 'valid' while the combination renderMedia actually receives threw
    at render time (the imageFormat defect that shipped the alpha export dead
    on arrival). This render-free contract check fails the moment any
    profile/flag combination would throw inside renderMedia. A negative
    control proves the validators really execute."""
    dist = _renderer_dist()
    if dist is None:
        pytest.skip("Remotion dist not installed")
    combos: list[dict] = [
        {"name": "default", "codec": "h264", "pixelFormat": "yuv420p", "imageFormat": "jpeg"}
    ]
    for prof in motion.ALPHA_PROFILES.values():
        combos.append(
            {
                "name": f"alpha:{prof.key}",
                "codec": prof.codec,
                "pixelFormat": prof.pixel_format,
                "imageFormat": _effective_image_format(prof.pixel_format),
                **({"proResProfile": prof.prores_profile} if prof.prores_profile else {}),
            }
        )
    for enc in motion.MOTION_ENCODE_PROFILES.values():
        combos.append(
            {
                "name": f"encode:{enc['name']}",
                "codec": enc["codec"],
                "pixelFormat": enc["pixelFormat"],
                "imageFormat": _effective_image_format(enc["pixelFormat"]),
            }
        )
    # Negative control: the pre-fix combination (alpha pixel format + the
    # default jpeg frames) must THROW — proving the validators are really
    # executing rather than silently absent/renamed.
    combos.append(
        {
            "name": "negative:yuva444p10le+jpeg",
            "codec": "prores",
            "pixelFormat": "yuva444p10le",
            "imageFormat": "jpeg",
            "proResProfile": "4444",
            "expect_error": True,
        }
    )
    # The package exports map blocks subpath require, so require via file path.
    script = (
        "const dist = process.argv[1];"
        "const combos = JSON.parse(process.argv[2]);"
        "const im = require(dist + '/image-format.js');"
        "const pf = require(dist + '/pixel-format.js');"
        "const pp = require(dist + '/prores-profile.js');"
        "const out = combos.map((c) => {"
        "  try {"
        "    im.validateSelectedPixelFormatAndImageFormatCombination("
        "      c.pixelFormat, c.imageFormat);"
        "    pf.validateSelectedPixelFormatAndCodecCombination(c.pixelFormat, c.codec);"
        "    pp.validateSelectedCodecAndProResCombination("
        "      { codec: c.codec, proResProfile: c.proResProfile });"
        "    return { name: c.name, ok: true };"
        "  } catch (e) {"
        "    return { name: c.name, ok: false,"
        "      error: String(e && e.message ? e.message : e) };"
        "  }"
        "});"
        "console.log(JSON.stringify(out));"
    )
    res = subprocess.run(
        ["node", "-e", script, str(dist), json.dumps(combos)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, f"node failed: {res.stderr}"
    results = {r["name"]: r for r in json.loads(res.stdout.strip())}
    assert set(results) == {c["name"] for c in combos}
    for combo in combos:
        got = results[combo["name"]]
        if combo.get("expect_error"):
            assert got["ok"] is False, f"{combo['name']}: validator did not throw"
            assert "PNG" in got["error"], got["error"]
        else:
            assert got["ok"] is True, f"{combo['name']}: {got.get('error')}"


# ---------------------------------------------------------------------------
# Alpha overrides an active env encode profile (mutual exclusion, both paths)
# ---------------------------------------------------------------------------


def test_alpha_wins_over_env_encode_profile_story(tmp_path, monkeypatch):
    """The shipped contract: an alpha export OVERRIDES an active
    MEDIAHUB_MOTION_ENCODE profile (alpha needs prores/vp9 + an alpha
    pixelFormat), and exactly one of cache_payload['alpha'] /
    cache_payload['encode'] folds. An env-wins refactor would ship an opaque
    h265/yuv420p10le file under the .mov alpha slot with the suite green —
    this pins the stacked combination every other alpha test delenv's away."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10-bt2020")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_story_card(
            _fake_card(), _fake_brand(), tmp_path / "story.mov", alpha_profile="prores4444"
        )
    # The render threads the ALPHA-derived encode dict, not the env profile.
    assert sink["encode"] == motion._alpha_encode(motion.resolve_alpha_profile("prores4444"))
    payload = seen["payload"]
    assert payload["alpha"] == "prores4444"
    assert "encode" not in payload
    assert Path(sink["out_path"]).suffix == ".mov"
    manifest = _read_manifest(tmp_path)
    assert manifest["alpha"]["profile"] == "prores4444"
    assert "encode" not in manifest


def test_alpha_wins_over_env_encode_profile_reel(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.setenv("MEDIAHUB_MOTION_ENCODE", "h265-10-bt2020")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.webm", alpha_profile="vp9"
        )
    assert sink["encode"] == motion._alpha_encode(motion.resolve_alpha_profile("vp9"))
    payload = seen["payload"]
    assert payload["alpha"] == "vp9"
    assert "encode" not in payload
    assert Path(sink["out_path"]).suffix == ".webm"
    manifest = _read_manifest(tmp_path)
    assert manifest["alpha"]["profile"] == "vp9"
    assert "encode" not in manifest


def test_reel_alpha_records_suppressed_supersample(tmp_path, monkeypatch):
    """When the operator ALSO asked for the whole-composition supersample, the
    alpha reel manifest records the suppression honestly — exactly like the
    encode branch's {requested, applied: False} record."""
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    monkeypatch.delenv("MEDIAHUB_MOTION_ENCODE", raising=False)
    monkeypatch.setenv("MEDIAHUB_MOTION_SUPERSAMPLE", "2")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
    ):
        motion.render_meet_reel(
            [_fake_card()], _fake_brand(), tmp_path / "reel.webm", alpha_profile="vp9"
        )
    assert sink.get("supersample") == 1.0
    manifest = _read_manifest(tmp_path)
    ss = manifest["supersample"]
    assert ss["requested"] == 2.0
    assert ss["applied"] is False
    assert "alpha" in ss["reason"]


# ---------------------------------------------------------------------------
# Published sidecar names — alpha and opaque cuts must never collide
# ---------------------------------------------------------------------------


def test_published_sidecar_path_naming():
    p = motion.published_sidecar_path
    # Opaque .mp4 keeps the historic with_suffix names (byte-identical links).
    assert p(Path("/x/c1.mp4"), ".json") == Path("/x/c1.json")
    assert p(Path("/x/c1.mp4"), ".poster.png") == Path("/x/c1.poster.png")
    assert p(Path("/x/c1_landscape.mp4"), ".json") == Path("/x/c1_landscape.json")
    # Alpha containers fold their profile key into the stem.
    assert p(Path("/x/c1.mov"), ".json") == Path("/x/c1_prores4444.json")
    assert p(Path("/x/c1.webm"), ".poster.png") == Path("/x/c1_vp9.poster.png")


def test_publish_alpha_and_opaque_sidecars_do_not_collide(tmp_path):
    """<c>.mov (alpha) and <c>.mp4 (opaque) share a stem by design, so the
    published manifest/poster names must differ — pre-fix both cuts published
    <c>.json / <c>.poster.png and the last render (or cache-hit re-publish)
    clobbered the other cut's explainability record."""
    from mediahub.visual.audio_mux import poster_path_for

    cache = tmp_path / "cache"
    cache.mkdir()
    out_dir = tmp_path / "motion"
    out_dir.mkdir()
    mp4 = cache / "aaa111.mp4"
    mp4.write_bytes(b"o" * 2048)
    mp4.with_suffix(".json").write_text('{"cut": "opaque"}', encoding="utf-8")
    poster_path_for(mp4).write_bytes(b"opaque-poster")
    mov = cache / "bbb222.mov"
    mov.write_bytes(b"a" * 2048)
    mov.with_suffix(".json").write_text('{"cut": "alpha"}', encoding="utf-8")
    poster_path_for(mov).write_bytes(b"alpha-poster")

    motion._publish(mp4, out_dir / "c1.mp4")
    motion._publish(mov, out_dir / "c1.mov")

    assert (out_dir / "c1.json").read_text(encoding="utf-8") == '{"cut": "opaque"}'
    assert (out_dir / "c1_prores4444.json").read_text(encoding="utf-8") == '{"cut": "alpha"}'
    assert (out_dir / "c1.poster.png").read_bytes() == b"opaque-poster"
    assert (out_dir / "c1_prores4444.poster.png").read_bytes() == b"alpha-poster"


# ---------------------------------------------------------------------------
# Poster policy — alpha containers refuse the ffmpeg grab; in-render publishes
# ---------------------------------------------------------------------------


def test_alpha_container_skips_ffmpeg_poster_grab(tmp_path, monkeypatch):
    """_ensure_poster_sidecar must honour the _alpha_manifest claim: the ffmpeg
    frame grab is unavailable for alpha containers — the in-render transparent
    PNG is the only poster source, and its absence is an honest '' (no
    poster), never a grab that may bake an opaque backdrop into the thumb."""
    from mediahub.visual import audio_mux

    calls: list = []
    monkeypatch.setattr(audio_mux, "write_poster", lambda *a, **k: calls.append(1) or True)
    for name in ("c.mov", "c.webm"):
        cached = tmp_path / name
        cached.write_bytes(b"x" * 2048)
        assert motion._ensure_poster_sidecar(cached, kind="story", duration_sec=6.0) == ""
    assert calls == [], "alpha containers must never reach the ffmpeg grab"
    # An in-render poster beside the alpha slot is trusted as usual.
    cached = tmp_path / "c.mov"
    audio_mux.poster_path_for(cached).write_bytes(b"\x89PNG transparent")
    assert motion._ensure_poster_sidecar(cached, kind="story", duration_sec=6.0) == "in-render"
    assert calls == []


def test_run_remotion_publishes_in_render_poster_sidecar(tmp_path, monkeypatch):
    """render.js writes its renderStill poster beside --output — the dotfile
    temp path. _run_remotion must publish it beside the final video (R1.29 for
    every profile) instead of stranding it as an unswept dotfile; for alpha
    containers this is the ONLY poster source."""
    from mediahub.visual import audio_mux

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "node_available", lambda: True)

    class _Proc:
        returncode = 0
        stderr = ""

    def fake_run_capture(cmd, *, cwd=None, timeout=None):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"x" * 4096)
        audio_mux.poster_path_for(out).write_bytes(b"\x89PNG in-render")
        return _Proc()

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)
    out = tmp_path / "card.mov"
    motion._run_remotion(
        composition_id="StoryCard",
        props={"card": {}, "brand": {}},
        out_path=out,
        duration_sec=6.0,
        size=(1080, 1920),
        encode=motion._alpha_encode(motion.resolve_alpha_profile("prores4444")),
    )
    poster = audio_mux.poster_path_for(out)
    assert poster.exists() and poster.read_bytes() == b"\x89PNG in-render"
    dotfiles = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert dotfiles == [], f"stranded temp files: {dotfiles}"


def test_run_remotion_cleans_tmp_poster_on_failure(tmp_path, monkeypatch):
    """A failed render must take its partial in-render poster with it — the
    dotfile temp poster is invisible to the prune globs, so leaving it behind
    leaks one PNG per failure on the bounded deployment disk."""
    from mediahub.visual import audio_mux

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(motion, "node_available", lambda: True)

    class _Proc:
        returncode = 1
        stderr = "boom"

    def fake_run_capture(cmd, *, cwd=None, timeout=None):
        out = Path(cmd[cmd.index("--output") + 1])
        out.write_bytes(b"x" * 4096)
        audio_mux.poster_path_for(out).write_bytes(b"\x89PNG partial")
        return _Proc()

    monkeypatch.setattr("mediahub.visual.proc.run_capture", fake_run_capture)
    with pytest.raises(RuntimeError, match="Remotion render failed"):
        motion._run_remotion(
            composition_id="StoryCard",
            props={"card": {}, "brand": {}},
            out_path=tmp_path / "card.mp4",
            duration_sec=6.0,
            size=(1080, 1920),
            encode=None,
        )
    dotfiles = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert dotfiles == [], f"stranded temp files: {dotfiles}"


# ---------------------------------------------------------------------------
# Web routes — shared ?alpha resolver + container-aware sidecar resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def alpha_run_env(app, web_module):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alphaclub", display_name="Alpha SC"))
    run = {
        "run_id": "ar1",
        "profile_id": "alphaclub",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
            ]
        },
    }
    (web_module.RUNS_DIR / "ar1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, web_module


def test_resolve_alpha_from_request_contract(alpha_run_env):
    """One shared resolver (the _resolve_motion_canvas pattern) for all six
    motion/reel sites: absent → the byte-identical opaque default, known
    profiles resolve to the closed tuple, junk is one honest 400 payload."""
    app, wm = alpha_run_env
    with app.test_request_context("/x"):
        resolved, err = wm._resolve_alpha_from_request()
    assert err is None
    assert resolved == ("", None, "mp4", "video/mp4")
    with app.test_request_context("/x?alpha=prores4444"):
        resolved, err = wm._resolve_alpha_from_request()
    assert err is None
    alpha, prof, ext, ctype = resolved
    assert alpha == "prores4444"
    assert prof == motion.resolve_alpha_profile("prores4444")
    assert (ext, ctype) == ("mov", "video/quicktime")
    with app.test_request_context("/x?alpha=garbage"):
        resolved, err = wm._resolve_alpha_from_request()
    assert resolved is None
    resp, status = err
    assert status == 400
    body = resp.get_json()
    assert body["error"] == "bad_alpha"
    assert body["valid_alpha"] == sorted(motion.ALPHA_PROFILES)
    assert "detail" in body


def test_manifest_and_poster_routes_resolve_alpha_cut(alpha_run_env):
    """?alpha= on the manifest/poster surfaces resolves the transparent cut's
    OWN container-aware sidecars — pre-fix there was no URL that could fetch
    the alpha cut's manifest, and ?poster=1 served whichever cut published
    last."""
    app, wm = alpha_run_env
    motion_dir = wm.RUNS_DIR / "ar1" / "motion"
    motion_dir.mkdir(parents=True, exist_ok=True)
    (motion_dir / "swim-1.mp4").write_bytes(b"0" * 2048)
    (motion_dir / "swim-1.json").write_text('{"cut": "opaque"}', encoding="utf-8")
    (motion_dir / "swim-1.poster.png").write_bytes(b"op")
    (motion_dir / "swim-1.mov").write_bytes(b"0" * 2048)
    (motion_dir / "swim-1_prores4444.json").write_text('{"cut": "alpha"}', encoding="utf-8")
    (motion_dir / "swim-1_prores4444.poster.png").write_bytes(b"ap")
    (motion_dir / "reel_3.webm").write_bytes(b"0" * 2048)
    (motion_dir / "reel_3_vp9.json").write_text('{"cut": "alpha-reel"}', encoding="utf-8")
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alphaclub"})
        r = c.get("/api/runs/ar1/card/swim-1/motion/manifest")
        assert r.status_code == 200 and r.get_json() == {"cut": "opaque"}
        r = c.get("/api/runs/ar1/card/swim-1/motion/manifest?alpha=prores4444")
        assert r.status_code == 200 and r.get_json() == {"cut": "alpha"}
        bad = c.get("/api/runs/ar1/card/swim-1/motion/manifest?alpha=nope")
        assert bad.status_code == 400 and bad.get_json()["error"] == "bad_alpha"
        # The reel manifest route resolves the same way.
        r = c.get("/api/runs/ar1/reel-manifest?alpha=vp9")
        assert r.status_code == 200 and r.get_json() == {"cut": "alpha-reel"}
        # ?poster=1 serves each cut's own poster, not whichever was written last.
        p = c.get("/api/runs/ar1/card/swim-1/motion-file?poster=1")
        assert p.status_code == 200 and p.data == b"op"
        p = c.get("/api/runs/ar1/card/swim-1/motion-file?alpha=prores4444&poster=1")
        assert p.status_code == 200 and p.data == b"ap"
        # The file routes answer the SAME 400 payload shape as the resolver.
        bad = c.get("/api/runs/ar1/card/swim-1/motion-file?alpha=nope")
        assert bad.status_code == 400
        body = bad.get_json()
        assert body["error"] == "bad_alpha" and "detail" in body
