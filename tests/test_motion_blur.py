"""true-motion-blur — opt-in real multi-sample / shutter-accumulation motion blur.

Motion renders default to the single-Gaussian whip smear + un-blurred entrance.
``MEDIAHUB_MOTION_BLUR`` opts into REAL shutter accumulation: the composition
recomputes the closed-form animation (story hero/result entrance + count-up, the
reel whip flick) at N deterministic sub-frames across the shutter window and
composites the copies as a true premultiplied average (equal ``1/n`` opacity summed
with ``mix-blend-mode: plus-lighter`` inside an ``isolation: isolate`` group, so
colour AND alpha are the exact linear mean) — a frame-pure, dep-free sampler (no
``@remotion/motion-blur``). OFF by default and folded into props +
cache key only when active, so every existing cache key and rendered byte is
byte-identical. The free FFmpeg engine cannot multi-sample a shutter interval, so
it declares ``motion_blur: unsupported-on-engine`` — never a faked smear.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion
from mediahub.visual import reel_ffmpeg

STORY_TSX = (
    motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx"
)
REEL_TSX = motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx"
PACKAGE_JSON = motion.REMOTION_DIR / "package.json"


# ---------------------------------------------------------------------------
# Env resolver — off by default, canonical + clamped when on
# ---------------------------------------------------------------------------


def _clear(monkeypatch):
    for k in (
        "MEDIAHUB_MOTION_BLUR",
        "MEDIAHUB_MOTION_BLUR_SAMPLES",
        "MEDIAHUB_MOTION_BLUR_SHUTTER",
        "MEDIAHUB_REEL_ENGINE",
        "MEDIAHUB_MOTION_ENCODE",
        "MEDIAHUB_MOTION_SUPERSAMPLE",
    ):
        monkeypatch.delenv(k, raising=False)


def test_motion_blur_off_by_default(monkeypatch):
    _clear(monkeypatch)
    assert motion._motion_blur() is None
    for falsey in ("", "0", "off", "false", "no", "nope"):
        monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", falsey)
        assert motion._motion_blur() is None, falsey


def test_motion_blur_resolves_and_clamps(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "1")
    # Defaults when only the master switch is on.
    assert motion._motion_blur() == {"samples": 8, "shutter": 180.0}

    # Samples clamp to [2, 16]; shutter to [1.0, 360.0].
    for raw, expect in [("2", 2), ("16", 16), ("1", 2), ("0", 2), ("99", 16), ("6", 6)]:
        monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SAMPLES", raw)
        assert motion._motion_blur()["samples"] == expect, raw
    monkeypatch.delenv("MEDIAHUB_MOTION_BLUR_SAMPLES", raising=False)

    for raw, expect in [("90", 90.0), ("360", 360.0), ("0", 1.0), ("999", 360.0), ("1", 1.0)]:
        monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SHUTTER", raw)
        assert motion._motion_blur()["shutter"] == expect, raw
    monkeypatch.delenv("MEDIAHUB_MOTION_BLUR_SHUTTER", raising=False)


def test_motion_blur_malformed_falls_back_to_defaults(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "yes")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SAMPLES", "not-a-number")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SHUTTER", "garbage")
    # Never raises; malformed → the shipped defaults.
    assert motion._motion_blur() == {"samples": 8, "shutter": 180.0}


def test_motion_blur_canonical_types(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "on")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SAMPLES", "6.7")  # rounds to int
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SHUTTER", "144")
    mb = motion._motion_blur()
    assert isinstance(mb["samples"], int) and mb["samples"] == 7
    assert isinstance(mb["shutter"], float) and mb["shutter"] == 144.0


# ---------------------------------------------------------------------------
# Story / reel path integration (mock _run_remotion — no Node)
# ---------------------------------------------------------------------------


def _brand() -> BrandKit:
    return BrandKit(
        profile_id="mblur-test",
        display_name="Blur Club",
        primary_colour="#0A2540",
        secondary_colour="#000000",
        accent_colour="#FFFFFF",
        short_name="BC",
    )


def _card() -> dict:
    return {
        "id": "mblur_c1",
        "achievement": {
            "swimmer_name": "Blur Tester",
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
    seen: dict = {}
    real = motion._content_hash

    def _spy(payload, *, kind):
        seen["payload"] = dict(payload)
        seen["kind"] = kind
        return real(payload, kind=kind)

    return seen, _spy


def _read_manifest(tmp_path: Path) -> dict:
    cache = tmp_path / "motion_cache"
    jsons = [p for p in cache.glob("*.json") if not p.name.endswith(".audio.json")]
    assert jsons, "no render manifest written"
    return json.loads(jsons[0].read_text(encoding="utf-8"))


def test_story_props_omit_motion_blur_by_default(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_story_card(_card(), _brand(), tmp_path / "story.mp4")
    payload = seen["payload"]
    assert "motionBlur" not in payload["card"]
    assert "motionBlur" not in payload
    # The props threaded to Remotion carry no motionBlur either.
    assert "motionBlur" not in sink["props"]["card"]


def test_story_props_and_key_fold_when_on(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "1")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SAMPLES", "6")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SHUTTER", "90")
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_story_card(_card(), _brand(), tmp_path / "story.mp4")
    payload = seen["payload"]
    # The story carries motionBlur INSIDE the card dict (so it folds into the
    # story cache key automatically), not as a separate top-level payload key.
    assert payload["card"]["motionBlur"] == {"samples": 6, "shutter": 90.0}
    assert sink["props"]["card"]["motionBlur"] == {"samples": 6, "shutter": 90.0}
    manifest = _read_manifest(tmp_path)
    assert manifest["motionBlur"]["samples"] == 6
    assert manifest["motionBlur"]["shutter"] == 90.0
    assert manifest["motionBlur"]["scope"] == "entrance+count_up"


def test_story_cache_key_distinct_per_config_and_off_stable(tmp_path, monkeypatch):
    """Off-key is the historic key; different (samples, shutter) key distinctly."""
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _key_for(env: dict) -> str:
        for k in ("MEDIAHUB_MOTION_BLUR", "MEDIAHUB_MOTION_BLUR_SAMPLES", "MEDIAHUB_MOTION_BLUR_SHUTTER"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        seen, spy = _capture_cache_payload()
        with (
            patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory({})),
            patch.object(motion, "_content_hash", side_effect=spy),
        ):
            motion.render_story_card(_card(), _brand(), tmp_path / "s.mp4")
        return motion._content_hash(seen["payload"], kind="story")

    off = _key_for({})
    a = _key_for({"MEDIAHUB_MOTION_BLUR": "1", "MEDIAHUB_MOTION_BLUR_SAMPLES": "6"})
    b = _key_for({"MEDIAHUB_MOTION_BLUR": "1", "MEDIAHUB_MOTION_BLUR_SAMPLES": "12"})
    c = _key_for({"MEDIAHUB_MOTION_BLUR": "1", "MEDIAHUB_MOTION_BLUR_SHUTTER": "90"})
    assert off == _key_for({})  # stable + historic
    assert len({off, a, b, c}) == 4  # each distinct


def test_reel_props_omit_motion_blur_by_default(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_meet_reel([_card()], _brand(), tmp_path / "reel.mp4")
    payload = seen["payload"]
    assert "motionBlur" not in payload
    assert all("motionBlur" not in cp for cp in payload["cards"])
    assert "motionBlur" not in sink["props"]
    assert all("motionBlur" not in cp for cp in sink["props"]["cards"])


def test_reel_props_and_key_fold_when_on(tmp_path, monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "1")
    monkeypatch.setenv("MEDIAHUB_MOTION_BLUR_SAMPLES", "10")
    seen, spy = _capture_cache_payload()
    sink: dict = {}
    with (
        patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory(sink)),
        patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
        patch.object(motion, "_content_hash", side_effect=spy),
    ):
        motion.render_meet_reel([_card()], _brand(), tmp_path / "reel.mp4")
    payload = seen["payload"]
    # Reel-level fold (whip lives in composition chrome, not per-card).
    assert payload["motionBlur"] == {"samples": 10, "shutter": 180.0}
    # cards_props stay byte-identical: the beats NEVER carry motionBlur.
    assert all("motionBlur" not in cp for cp in payload["cards"])
    assert sink["props"]["motionBlur"] == {"samples": 10, "shutter": 180.0}
    assert all("motionBlur" not in cp for cp in sink["props"]["cards"])
    manifest = _read_manifest(tmp_path)
    assert manifest["motionBlur"]["samples"] == 10
    assert manifest["motionBlur"]["scope"] == "whip+entrance+count_up"


def test_reel_cards_props_byte_identical_on_off(tmp_path, monkeypatch):
    """The reel feature must NOT mutate cards_props — the per-beat card dicts are
    identical whether motion blur is on or off (only the reel-level prop differs)."""
    _clear(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _cards_for(on: bool):
        for k in ("MEDIAHUB_MOTION_BLUR", "MEDIAHUB_MOTION_BLUR_SAMPLES"):
            monkeypatch.delenv(k, raising=False)
        if on:
            monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", "1")
        seen, spy = _capture_cache_payload()
        with (
            patch.object(motion, "_run_remotion", side_effect=_fake_run_remotion_factory({})),
            patch.object(motion, "_render_reel_parallel_or_none", side_effect=lambda **k: None),
            patch.object(motion, "_content_hash", side_effect=spy),
        ):
            motion.render_meet_reel([_card()], _brand(), tmp_path / "reel.mp4")
        return seen["payload"]["cards"]

    assert _cards_for(False) == _cards_for(True)


# ---------------------------------------------------------------------------
# Composition revisions must NOT bump (default byte-identity guard)
# ---------------------------------------------------------------------------


def test_composition_revisions_unbumped():
    assert motion.STORY_COMPOSITION_REVISION == "8"
    assert motion.REEL_COMPOSITION_REVISION == "11"


# ---------------------------------------------------------------------------
# FFmpeg engine — honest unsupported note (never a faked smear)
# ---------------------------------------------------------------------------


def test_ffmpeg_motion_blur_requested_reads_env(monkeypatch):
    _clear(monkeypatch)
    assert reel_ffmpeg._motion_blur_requested() is False
    for on in ("1", "true", "yes", "on", "On", "TRUE"):
        monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", on)
        assert reel_ffmpeg._motion_blur_requested() is True, on
    for off in ("", "0", "off", "no"):
        monkeypatch.setenv("MEDIAHUB_MOTION_BLUR", off)
        assert reel_ffmpeg._motion_blur_requested() is False, off


def test_ffmpeg_manifests_declare_motion_blur_unsupported():
    """Both the story and the reel branches carry the honest note (emitted only
    when the operator opts in), never faking an accumulated shutter smear."""
    src = Path(reel_ffmpeg.__file__).read_text()
    assert src.count('"motion_blur": "unsupported-on-engine"') == 2


# ---------------------------------------------------------------------------
# TSX source contract (the same no-Node approach the motion suite uses)
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", no_block)


def test_dep_free_no_remotion_motion_blur_dependency():
    """The dep-free path: @remotion/motion-blur must NOT be added to deps."""
    pkg = json.loads(PACKAGE_JSON.read_text())
    assert "@remotion/motion-blur" not in pkg.get("dependencies", {})
    assert "@remotion/motion-blur" not in pkg.get("devDependencies", {})
    assert "@remotion/motion-blur" not in Path(REEL_TSX).read_text()
    assert "@remotion/motion-blur" not in Path(STORY_TSX).read_text()


def test_tsx_schema_defaults_present():
    src = STORY_TSX.read_text()
    assert "export const motionBlurSchema" in src
    assert re.search(r"samples:\s*z\.number\(\)\.default\(8\)", src)
    assert re.search(r"shutter:\s*z\.number\(\)\.default\(180\)", src)
    # Both compositions carry the opt-in optional field.
    assert "motionBlur: motionBlurSchema.optional()" in src
    assert "motionBlur: motionBlurSchema.optional()" in REEL_TSX.read_text()


def test_tsx_sampler_is_frame_pure():
    """The sub-frame sampler must be a pure function of the frame — no
    Math.random / Date.now / performance.now / new Date anywhere in the render
    code (comments stripped first)."""
    code = _strip_comments(STORY_TSX.read_text())
    assert "export function motionBlurSubFrames" in code
    assert "export const MotionBlurSampler" in code
    for forbidden in ("Math.random", "Date.now", "performance.now", "new Date"):
        assert forbidden not in code, forbidden
    # The sub-frame set is derived from the frame index.
    assert re.search(r"frame\s*\+\s*\(i", code)


def test_tsx_sampler_composites_true_premultiplied_average():
    """The accumulator composites the N sub-samples as a TRUE premultiplied average
    — equal ``1/n`` opacity summed with ``plus-lighter`` inside an ``isolation:
    isolate`` group — so colour AND alpha are the exact linear mean. An at-rest frame
    then collapses to a single draw (alpha included), preserving still<->motion parity.
    Guards against a regression to the old progressive-opacity scheme (``1/(i+1)``),
    which averaged colour but over-accumulated alpha on semi-transparent pixels."""
    code = _strip_comments(STORY_TSX.read_text())
    assert 'mixBlendMode: "plus-lighter"' in code
    assert 'isolation: "isolate"' in code
    # Equal-weight (1/n), never the progressive 1/(i+1) that over-covers alpha.
    assert "1 / subs.length" in code
    assert re.search(r"opacity:\s*1\s*/\s*\(i\s*\+\s*1\)", code) is None


def test_tsx_story_gates_wrapper_on_prop_present():
    """The wrapper is inserted ONLY when a motionBlur prop is present; the OFF
    path renders the verbatim `<Scene ctx={ctx} />` (byte-identical default)."""
    code = _strip_comments(STORY_TSX.read_text())
    # StoryCard reads card.motionBlur OR the reel-injected prop.
    assert "card.motionBlur ?? motionBlur" in code
    # Ternary gate: mb ? <MotionBlurSampler .../> : <Scene ctx={ctx} />
    assert re.search(r"mb\s*\?\s*\(\s*<MotionBlurSampler", code)
    assert "<Scene ctx={ctx} />" in code


def test_tsx_whip_keeps_default_fegaussian_and_gates_accumulation():
    """The whip's feGaussianBlur DOM stays the DEFAULT; the multi-sample
    accumulation only replaces it inside the motionBlur-on branch."""
    code = _strip_comments(REEL_TSX.read_text())
    # Default whip smear preserved on both incoming + outgoing whip branches.
    assert code.count("feGaussianBlur") == 2
    # Accumulation gated behind `if (mb)` and threaded down from the reel.
    assert "if (mb)" in code
    assert "<MotionBlurSampler" in code
    # The reel injects motionBlur into the StoryCard beats via a dedicated prop.
    assert "motionBlur={motionBlur}" in code
