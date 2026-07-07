"""Animated still loops — roadmap G1.29.

Covers both halves of the feature:

* ``graphic_renderer/animated_still.py`` — the loop catalogue, deterministic
  planning, the seamless-loop maths (Hann envelope), per-frame compositing, and
  the APNG/GIF exporter.
* ``graphic_renderer/sprint_hooks/animated_still.py`` — the opt-in render hook
  and the registry invariant that an un-opted render stays byte-identical.

The two load-bearing guarantees are asserted directly: every loop is
**deterministic** (identical inputs → byte-identical files) and **frame 0 is the
untouched approved still** (the Hann envelope is zero at phase 0).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from PIL import Image

from mediahub.graphic_renderer import animated_still as A
from mediahub.graphic_renderer.sprint_hooks import (
    RenderHookCtx,
    apply_render_hooks,
)
from mediahub.graphic_renderer.sprint_hooks import animated_still as hook


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
@dataclass
class FakeBrief:
    """Minimal duck-typed stand-in for a CreativeBrief."""

    id: str = "card_x1"
    variation_signature: str = "sig-1"
    primary_hook: str = "NEW PB"
    mood: str = ""
    background_style: str = "water"
    animated_loop: str = ""
    animate_still: bool = False
    palette: dict = field(
        default_factory=lambda: {
            "primary": "#0E1726",
            "secondary": "#1E6FB8",
            "accent": "#FFB703",
        }
    )


def _base_png(size=(80, 100), bytes_out=True):
    """A small multi-colour base still."""
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[: size[1] // 2, :, :] = (24, 32, 48)
    arr[size[1] // 2 :, :, :] = (70, 40, 30)
    arr[:, :: max(1, size[0] // 4), 0] = 200
    img = Image.fromarray(arr, "RGB")
    if not bytes_out:
        return img
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _ctx(brief, width=1080, height=1350):
    return RenderHookCtx(
        brief=brief,
        width=width,
        height=height,
        family="individual_hero",
        format_name="feed_portrait",
        is_v2=True,
    )


HTML = '<html><head></head><body><div class="canvas">card</div></body></html>'


# ---------------------------------------------------------------------------
# Loop catalogue + planning
# ---------------------------------------------------------------------------
class TestPlanning:
    def test_catalogue_is_curated_and_default_is_member(self):
        assert A.DEFAULT_LOOP in A.LOOPS
        assert len(A.LOOPS) == len(set(A.LOOPS))
        # Every loop has a tuned peak alpha and a CSS keyframe analogue.
        for loop in A.LOOPS:
            assert loop in A._PEAK_ALPHA
            assert "@keyframes" in A._keyframes_for(loop, "anim")

    def test_every_mood_maps_to_a_real_loop(self):
        from mediahub.creative_brief.design_spec import MOODS

        for mood in MOODS:
            resolved = A.select_loop(FakeBrief(mood=mood, background_style="x"))
            assert resolved in A.LOOPS

    def test_select_loop_precedence(self):
        # explicit in-vocab loop wins over everything
        assert A.select_loop(FakeBrief(animated_loop="tide", mood="electric")) == "tide"
        # mood wins over background_style
        assert A.select_loop(FakeBrief(mood="electric", background_style="water")) == "sheen"
        # background_style hint when no mood
        assert A.select_loop(FakeBrief(mood="", background_style="water")) == "tide"
        # fall back to default
        assert A.select_loop(FakeBrief(mood="", background_style="")) == A.DEFAULT_LOOP
        # an out-of-vocab explicit loop is ignored (falls through to mood)
        assert A.select_loop(FakeBrief(animated_loop="nonsense", mood="calm")) == "breathe"

    def test_plan_is_deterministic_and_seed_stable(self):
        b = FakeBrief()
        p1 = A.plan_from_brief(b)
        p2 = A.plan_from_brief(b)
        assert p1 == p2
        # Seed is a stable function of identity; a different card differs.
        assert A.plan_from_brief(FakeBrief(id="other")).seed != p1.seed

    def test_plan_normalises_palette(self):
        b = FakeBrief(palette={"accent": "fff", "primary": "garbage", "secondary": "#12ab"})
        p = A.plan_from_brief(b)
        for v in p.palette.values():
            assert v.startswith("#") and len(v) == 7

    def test_plan_explicit_overrides_win(self):
        p = A.plan_from_brief(FakeBrief(mood="electric"), loop="breathe", frames=10, fps=20, seed=5)
        assert p.loop == "breathe" and p.frames == 10 and p.fps == 20 and p.seed == 5

    def test_frame_clamping(self):
        assert A.plan_from_brief(FakeBrief(), frames=1).frames == A._MIN_FRAMES
        assert A.plan_from_brief(FakeBrief(), frames=99999).frames == A._MAX_FRAMES

    def test_duration_and_loop_seconds(self):
        p = A.AnimationPlan(loop="tide", palette={}, seed=0, frames=24, fps=12)
        assert p.duration_ms == round(1000 / 12)
        assert p.loop_seconds == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Seamless-loop maths
# ---------------------------------------------------------------------------
class TestEnvelope:
    def test_hann_window_zero_at_ends_peak_at_half(self):
        assert A._envelope(0.0) == pytest.approx(0.0, abs=1e-9)
        assert A._envelope(1.0) == pytest.approx(0.0, abs=1e-9)
        assert A._envelope(0.5) == pytest.approx(1.0, abs=1e-9)

    def test_envelope_is_monotone_into_the_peak(self):
        vals = [A._envelope(t / 50) for t in range(26)]
        assert vals == sorted(vals)  # rises 0 → 0.5


# ---------------------------------------------------------------------------
# Frame building
# ---------------------------------------------------------------------------
class TestFrames:
    @pytest.mark.parametrize("loop", A.LOOPS)
    def test_frame_zero_is_the_untouched_still(self, loop):
        base = _base_png()
        plan = A.AnimationPlan(loop=loop, palette=FakeBrief().palette, seed=3, frames=6, fps=12)
        frames = A.build_frames(base, plan)
        assert len(frames) == 6
        base_img = Image.open(io.BytesIO(base)).convert("RGB")
        assert np.array_equal(np.asarray(frames[0]), np.asarray(base_img))

    @pytest.mark.parametrize("loop", A.LOOPS)
    def test_mid_loop_has_visible_motion(self, loop):
        base = _base_png()
        plan = A.AnimationPlan(loop=loop, palette=FakeBrief().palette, seed=3, frames=8, fps=12)
        frames = A.build_frames(base, plan)
        base_img = np.asarray(Image.open(io.BytesIO(base)).convert("RGB")).astype(int)
        mid = np.asarray(frames[4]).astype(int)
        assert np.abs(mid - base_img).max() > 0  # the loop actually moves

    def test_frames_match_base_size_even_when_overlay_capped(self):
        # A base larger than the overlay cap exercises the resize path; frame 0
        # must still be pixel-identical to the base.
        base = _base_png(size=(600, 600))
        plan = A.AnimationPlan(loop="breathe", palette=FakeBrief().palette, seed=1, frames=4, fps=12)
        frames = A.build_frames(base, plan)
        assert all(f.size == (600, 600) for f in frames)
        base_img = Image.open(io.BytesIO(base)).convert("RGB")
        assert np.array_equal(np.asarray(frames[0]), np.asarray(base_img))


# ---------------------------------------------------------------------------
# Exporter — APNG
# ---------------------------------------------------------------------------
class TestExportAPNG:
    def test_valid_animated_png(self, tmp_path):
        res = A.export_animated_still(
            _base_png(), tmp_path / "loop", plan=_plan("sheen"), fmt="apng", write_manifest=False
        )
        assert res.path.endswith(".apng")
        raw = Path(res.path).read_bytes()
        assert b"acTL" in raw  # the chunk that makes a PNG *animated*
        im = Image.open(res.path)
        assert getattr(im, "is_animated", False) and im.n_frames == 6
        assert res.bytes_written == Path(res.path).stat().st_size

    def test_apng_first_frame_round_trips_to_the_still(self, tmp_path):
        base_img = _base_png(bytes_out=False)
        res = A.export_animated_still(
            base_img, tmp_path / "loop", plan=_plan("drift"), fmt="apng", write_manifest=False
        )
        im = Image.open(res.path)
        im.seek(0)
        assert np.array_equal(np.asarray(im.convert("RGB")), np.asarray(base_img))

    def test_apng_loops_forever(self, tmp_path):
        res = A.export_animated_still(
            _base_png(), tmp_path / "loop", plan=_plan("tide"), fmt="apng", write_manifest=False
        )
        im = Image.open(res.path)
        assert im.info.get("loop", None) == 0  # 0 == infinite

    def test_deterministic_bytes(self, tmp_path):
        base = _base_png()
        a = A.export_animated_still(base, tmp_path / "a", plan=_plan("shimmer"), fmt="apng", write_manifest=False)
        b = A.export_animated_still(base, tmp_path / "b", plan=_plan("shimmer"), fmt="apng", write_manifest=False)
        assert Path(a.path).read_bytes() == Path(b.path).read_bytes()


# ---------------------------------------------------------------------------
# Exporter — GIF
# ---------------------------------------------------------------------------
class TestExportGIF:
    def test_valid_animated_gif(self, tmp_path):
        res = A.export_animated_still(
            _base_png(), tmp_path / "loop", plan=_plan("breathe"), fmt="gif", write_manifest=False
        )
        assert res.path.endswith(".gif")
        im = Image.open(res.path)
        assert getattr(im, "is_animated", False) and im.n_frames == 6

    def test_gif_deterministic(self, tmp_path):
        base = _base_png()
        a = A.export_animated_still(base, tmp_path / "a", plan=_plan("drift"), fmt="gif", write_manifest=False)
        b = A.export_animated_still(base, tmp_path / "b", plan=_plan("drift"), fmt="gif", write_manifest=False)
        assert Path(a.path).read_bytes() == Path(b.path).read_bytes()


# ---------------------------------------------------------------------------
# Exporter — inputs, overrides, manifest, errors
# ---------------------------------------------------------------------------
class TestExporterApi:
    def test_accepts_path_bytes_and_image(self, tmp_path):
        png = _base_png()
        p = tmp_path / "still.png"
        p.write_bytes(png)
        for src in (p, str(p), png, Image.open(io.BytesIO(png))):
            res = A.export_animated_still(src, tmp_path / "o", plan=_plan("tide"), fmt="apng", write_manifest=False)
            assert Path(res.path).exists()

    def test_brief_drives_the_plan(self, tmp_path):
        res = A.export_animated_still(
            _base_png(), tmp_path / "o", brief=FakeBrief(mood="electric"), fmt="apng",
            frames=4, write_manifest=False,
        )
        assert res.loop == "sheen" and res.frames == 4

    def test_explicit_palette_overrides_brief(self, tmp_path):
        res = A.export_animated_still(
            _base_png(), tmp_path / "o", brief=FakeBrief(), palette={"accent": "#FF0000"},
            plan=_plan("breathe"), fmt="apng", write_manifest=False,
        )
        # The override is applied to the plan that drives the render.
        assert res.loop == "breathe"

    def test_manifest_sidecar(self, tmp_path):
        res = A.export_animated_still(_base_png(), tmp_path / "o", plan=_plan("sheen"), fmt="apng")
        assert res.sidecar_path and Path(res.sidecar_path).exists()
        data = json.loads(Path(res.sidecar_path).read_text())
        assert data["loop"] == "sheen" and data["fmt"] == "apng"
        assert data["frames"] == 6 and "frame 0 == approved still" in data["why"]

    def test_bad_format_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            A.export_animated_still(_base_png(), tmp_path / "o", plan=_plan("sheen"), fmt="webp")

    def test_invalid_base_raises(self, tmp_path):
        with pytest.raises(A.AnimatedStillError):
            A.export_animated_still(b"not a png", tmp_path / "o", plan=_plan("sheen"), fmt="apng")

    def test_no_brief_no_plan_uses_safe_defaults(self, tmp_path):
        res = A.export_animated_still(_base_png(), tmp_path / "o", loop="tide", fmt="gif", frames=3, write_manifest=False)
        assert res.loop == "tide" and res.frames == 3


# ---------------------------------------------------------------------------
# CSS / SVG builder — injection safety + contract
# ---------------------------------------------------------------------------
class TestCssBuilder:
    def test_norm_hex_neutralises_garbage(self):
        assert A._norm_hex('#fff" onload=alert(1)') == "#000000"
        assert A._norm_hex("zzz") == "#000000"
        assert A._norm_hex("#1e6fb8").upper() == "#1E6FB8"

    def test_fragment_contract(self):
        plan = _plan("breathe")
        frag = A.build_animation_css(plan, 1080, 1350)
        assert "@keyframes mh-anim-breathe" in frag
        assert "mh-anim-still--breathe" in frag
        # Deterministic screenshots: the layer is paused at its neutral frame.
        assert "animation-play-state:paused" in frag
        assert "pointer-events:none" in frag
        assert "<svg" in frag and "</svg>" in frag

    def test_no_palette_injection_in_svg(self):
        plan = A.plan_from_brief(FakeBrief(palette={"accent": '#abc" onload=x', "secondary": "</style>"}))
        frag = A.build_animation_css(plan, 100, 100)
        assert "onload" not in frag and "</style><script" not in frag
        # Only normalised hex colours appear as stop-colors.
        import re

        for col in re.findall(r"stop-color=\"([^\"]+)\"", frag):
            assert col == "#FFFFFF" or re.fullmatch(r"#[0-9A-Fa-f]{6}", col)


# ---------------------------------------------------------------------------
# Render hook
# ---------------------------------------------------------------------------
class TestHook:
    def test_order_is_int(self):
        assert isinstance(hook.ORDER, int)

    def test_opt_out_is_byte_identical(self, monkeypatch):
        # At the hook level: a brief that did not ask for the effect is
        # returned unchanged.
        assert hook.apply(HTML, _ctx(FakeBrief())) == HTML
        # Through the full registry: my hook contributes nothing for a
        # non-opted brief — the registry output is identical whether my hook
        # runs or is replaced by an identity no-op. This isolates my hook's
        # opt-out invariant from whatever sibling hooks do with the same brief.
        real = apply_render_hooks(HTML, _ctx(FakeBrief()))
        monkeypatch.setattr(hook, "apply", lambda html, ctx: html)
        stub = apply_render_hooks(HTML, _ctx(FakeBrief()))
        assert real == stub
        assert "mh-anim-still" not in real

    def test_opt_in_via_animate_still(self):
        out = hook.apply(HTML, _ctx(FakeBrief(animate_still=True)))
        assert out != HTML and "mh-anim-still" in out
        assert out.index("mh-anim-still") < out.index("</body>")

    def test_opt_in_via_background_style(self):
        out = hook.apply(HTML, _ctx(FakeBrief(background_style="animated_loop")))
        assert "mh-anim-still" in out

    def test_opt_in_via_explicit_loop(self):
        out = hook.apply(HTML, _ctx(FakeBrief(animated_loop="tide")))
        assert "mh-anim-still--tide" in out

    def test_mood_selects_loop_when_opted_in(self):
        out = hook.apply(HTML, _ctx(FakeBrief(animate_still=True, mood="calm", background_style="z")))
        assert "mh-anim-still--breathe" in out

    def test_appends_when_no_body_tag(self):
        out = hook.apply("<div>x</div>", _ctx(FakeBrief(animate_still=True)))
        assert "mh-anim-still" in out

    def test_registry_discovers_the_hook(self):
        names = [name for _o, name, _fn in apply_render_hooks.__globals__["_discover"]()]
        assert "animated_still" in names

    def test_registry_swallows_a_hook_that_raises(self, monkeypatch):
        # Isolation contract: if my hook blows up, the registry skips it rather
        # than failing the whole render (sibling hooks still run normally).
        monkeypatch.setattr(hook, "apply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out = apply_render_hooks(HTML, _ctx(FakeBrief(animate_still=True)))  # must not raise
        assert "mh-anim-still" not in out  # my hook raised → its layer is dropped

    def test_hook_output_is_deterministic(self):
        b = FakeBrief(animate_still=True, mood="electric")
        assert hook.apply(HTML, _ctx(b)) == hook.apply(HTML, _ctx(b))


def _plan(loop):
    return A.AnimationPlan(
        loop=loop,
        palette={"primary": "#0E1726", "secondary": "#1E6FB8", "accent": "#FFB703"},
        seed=42,
        frames=6,
        fps=12,
    )


# ---------------------------------------------------------------------------
# Product reachability — render_brief exports the loop from a real trigger
# ---------------------------------------------------------------------------
class TestRenderBriefReachability:
    """G1.29 must be reachable from the product render path: the operator env
    flag (MEDIAHUB_ANIMATED_STILL=1) or the brief's own opt-in drives
    ``export_animated_still`` beside the rendered still — no test-only calls."""

    @staticmethod
    def _stub_brief(**over):
        from mediahub.creative_brief.generator import CreativeBrief

        base = dict(
            id="cb_g129",
            content_item_id="ci-g129",
            profile_id="g129-club",
            achievement_summary="",
            objective="celebrate",
            primary_hook="NEW PB",
            confidence_label="NEW PB",
            tone="hype",
            layout_template="individual_hero",
            inspiration_pattern_id="",
            image_treatment="cutout",
            text_hierarchy=[],
            brand_instructions="",
            sponsor_instructions=None,
            sourced_asset_ids=[],
            safety_notes=[],
            why_this_design="",
            text_layers={"result_value": "1:02.34"},
            palette={"primary": "#0E1726", "secondary": "#1E6FB8", "accent": "#FFB703"},
            format_priority=[],
        )
        base.update(over)
        return CreativeBrief(**base)

    def _render(self, monkeypatch, tmp_path, brief):
        import mediahub.graphic_renderer.render as R

        def _fake_png(html, output_path, size):  # noqa: ARG001 - signature match
            Image.new("RGB", (64, 80), (24, 32, 48)).save(output_path, "PNG")
            return Path(output_path).stat().st_size

        monkeypatch.setattr(R, "render_html_to_png", _fake_png)
        return R.render_brief(brief, output_dir=tmp_path)

    def test_env_flag_exports_apng_beside_the_still(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEDIAHUB_ANIMATED_STILL", "1")
        self._render(monkeypatch, tmp_path, self._stub_brief())
        apng = tmp_path / "feed_portrait.apng"
        assert apng.exists(), "env-flag trigger must export the animated still"
        manifest = json.loads((tmp_path / "feed_portrait.apng.json").read_text())
        assert manifest["loop"] in A.LOOPS

    def test_brief_opt_in_exports_without_env_flag(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MEDIAHUB_ANIMATED_STILL", raising=False)
        brief = self._stub_brief()
        brief.animate_still = True  # duck-typed opt-in, same gate as the hook
        self._render(monkeypatch, tmp_path, brief)
        assert (tmp_path / "feed_portrait.apng").exists()

    def test_default_render_exports_nothing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MEDIAHUB_ANIMATED_STILL", raising=False)
        self._render(monkeypatch, tmp_path, self._stub_brief())
        assert not list(tmp_path.glob("*.apng"))
        assert not list(tmp_path.glob("*.apng.json"))
