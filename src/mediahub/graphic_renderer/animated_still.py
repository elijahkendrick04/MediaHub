"""Animated still loops (roadmap G1.29) — subtle living motion for static posts.

A finished card is a single PNG. This module turns it into a *static-but-living*
post: the picture stays exactly as approved, with a subtle, seamlessly-looping
atmosphere drifting over it — a soft light sweep, a gentle breath of accent glow,
slow-drifting motes — exported as an **APNG** (lossless, the default) or a **GIF**
(universally embeddable fallback).

Two surfaces consume this module, mirroring the still ↔ motion parity rule:

* The **render hook** (``sprint_hooks/animated_still.py``) injects the matching
  animated SVG layer into the card HTML so a live preview of the card breathes.
  It calls :func:`build_animation_css`.
* The **exporter** (:func:`export_animated_still`) renders the loop to an APNG/GIF
  from the finished still PNG, with no browser — pure numpy + Pillow.

Everything here is **deterministic** (the deterministic-render rule): the loop,
seed, palette and frame maths are pure functions of the brief, so the same card
always yields byte-identical output. Two invariants make the loop safe:

* a Hann-window opacity envelope ``0.5 - 0.5*cos(2*pi*phase)`` means every loop
  fades in from nothing and back to nothing each cycle — so the wrap from the
  last frame to the first is seamless *and* **frame 0 is pixel-identical to the
  base still** (the canonical, approved frame is never altered);
* peak overlay opacity is held low (≤ ~0.22) so on-card text stays legible.

Colours are always re-emitted as normalised ``#RRGGBB`` before they touch CSS or
SVG, so a malformed palette value can never break out of the markup context.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

try:  # Pillow is the encoder; required for the exporter, not for the CSS builder.
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover - Pillow is a hard dep of the renderer
    Image = None  # type: ignore

try:  # numpy drives the per-frame overlay maths; CSS builder needs none of it.
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover
    _np = None  # type: ignore


class AnimatedStillError(RuntimeError):
    """Raised when an animated-still loop cannot be produced."""


# ---------------------------------------------------------------------------
# Loop catalogue
# ---------------------------------------------------------------------------
# Each loop is a subtle, periodic atmosphere. Keep this list small and curated;
# the design-quality rule is "alive, not busy". Adding a loop = a new branch in
# ``_overlay_rgba`` plus a CSS analogue in ``_keyframes_for`` — nothing else.
LOOPS: tuple[str, ...] = (
    "sheen",  # soft diagonal light band sweeps across once per loop
    "breathe",  # gentle radial accent glow pulses in and out
    "drift",  # slow-rising soft motes, twinkling as they go
    "tide",  # slow horizontal palette bands drift vertically
    "shimmer",  # faint seeded sparkle that twinkles in place
)
DEFAULT_LOOP = "breathe"

# Mood → loop. Moods come from ``creative_brief.design_spec.MOODS``; anything
# outside this map (or an absent mood) falls back to DEFAULT_LOOP. Deterministic.
_MOOD_TO_LOOP: dict[str, str] = {
    "explosive": "sheen",
    "electric": "sheen",
    "fierce": "sheen",
    "bold": "sheen",
    "calm": "breathe",
    "stoic": "breathe",
    "minimal": "breathe",
    "precise": "breathe",
    "celebratory": "drift",
    "triumphant": "drift",
    "warm": "drift",
    "neutral": "tide",
}
# A few background-style hints map to a loop when no mood resolves one.
_BG_TO_LOOP: dict[str, str] = {
    "water": "tide",
    "waves": "tide",
    "gradient_mesh": "breathe",
    "particles": "drift",
}

# Frame defaults: a 2.0s single-breath loop reads as "living" without distracting.
DEFAULT_FRAMES = 24
DEFAULT_FPS = 12
_MIN_FRAMES = 2
_MAX_FRAMES = 120

# The overlay maths run on a capped canvas then upscale — the effects are smooth
# and low-frequency, so this is visually lossless and keeps cold renders cheap.
_OVERLAY_MAX_DIM = 540

# Per-loop peak opacity (the Hann envelope scales each down to 0 at the ends).
_PEAK_ALPHA: dict[str, float] = {
    "sheen": 0.22,
    "breathe": 0.18,
    "drift": 0.45,  # per-mote; the motes themselves are tiny
    "tide": 0.12,
    "shimmer": 0.14,
}


# ---------------------------------------------------------------------------
# Colour helpers (self-contained so the hook needn't import the heavy renderer)
# ---------------------------------------------------------------------------
def _hex_to_rgb(c: str) -> tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 0, 0, 0


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _norm_hex(c: str) -> str:
    """Normalise any palette value to a safe ``#RRGGBB`` literal.

    Round-tripping through the parser guarantees the result is six hex digits —
    no stray characters can survive into a CSS/SVG context (injection guard).
    """
    return _rgb_to_hex(_hex_to_rgb(c))


def _lighten(c: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(c)
    return _rgb_to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


# ---------------------------------------------------------------------------
# Planning — derive a deterministic loop spec from a CreativeBrief
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AnimationPlan:
    """Deterministic description of the loop for one card.

    Shared by both surfaces so the injected CSS and the exported frames describe
    the *same* motion. Pure function of the brief (see :func:`plan_from_brief`).
    """

    loop: str
    palette: dict[str, str]
    seed: int
    frames: int = DEFAULT_FRAMES
    fps: int = DEFAULT_FPS

    @property
    def duration_ms(self) -> int:
        """Milliseconds per frame (each frame held equally)."""
        return max(1, round(1000 / max(1, self.fps)))

    @property
    def loop_seconds(self) -> float:
        return self.frames / max(1, self.fps)

    def to_dict(self) -> dict:
        return asdict(self)


def _coerce_loop(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip().lower() in LOOPS:
        return value.strip().lower()
    return None


def select_loop(brief: Any) -> str:
    """Pick a loop id for ``brief`` deterministically.

    Precedence: an explicit, in-vocabulary ``brief.animated_loop`` →
    ``brief.mood`` → ``brief.background_style`` hint → :data:`DEFAULT_LOOP`.
    """
    explicit = _coerce_loop(getattr(brief, "animated_loop", None))
    if explicit:
        return explicit
    mood = str(getattr(brief, "mood", "") or "").strip().lower()
    if mood in _MOOD_TO_LOOP:
        return _MOOD_TO_LOOP[mood]
    bg = str(getattr(brief, "background_style", "") or "").strip().lower()
    if bg in _BG_TO_LOOP:
        return _BG_TO_LOOP[bg]
    return DEFAULT_LOOP


def _seed_from(brief: Any) -> int:
    """Stable 32-bit seed from the brief's identity (id + variation signature)."""
    key = "|".join(
        str(getattr(brief, attr, "") or "")
        for attr in ("id", "variation_signature", "primary_hook")
    )
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def _palette_from(brief: Any) -> dict[str, str]:
    pal = getattr(brief, "palette", None)
    if not isinstance(pal, dict):
        pal = {}
    primary = _norm_hex(pal.get("primary") or pal.get("ground") or "#101317")
    secondary = _norm_hex(pal.get("secondary") or primary)
    accent = _norm_hex(pal.get("accent") or pal.get("highlight") or secondary)
    return {"primary": primary, "secondary": secondary, "accent": accent}


def plan_from_brief(
    brief: Any,
    *,
    loop: str = "",
    frames: int = DEFAULT_FRAMES,
    fps: int = DEFAULT_FPS,
    seed: Optional[int] = None,
) -> AnimationPlan:
    """Build the :class:`AnimationPlan` for ``brief``; explicit args win."""
    chosen = _coerce_loop(loop) or select_loop(brief)
    return AnimationPlan(
        loop=chosen,
        palette=_palette_from(brief),
        seed=int(seed) if seed is not None else _seed_from(brief),
        frames=_clamp_frames(frames),
        fps=max(1, int(fps)),
    )


def _clamp_frames(frames: int) -> int:
    try:
        n = int(frames)
    except Exception:
        n = DEFAULT_FRAMES
    return max(_MIN_FRAMES, min(_MAX_FRAMES, n))


# ---------------------------------------------------------------------------
# Phase maths — shared by every loop
# ---------------------------------------------------------------------------
def _envelope(phase: float) -> float:
    """Hann window: 0 at phase 0, 1 at phase 0.5, 0 at phase 1.

    Both value *and* slope are zero at the ends, so the loop wraps seamlessly and
    frame 0 carries no overlay (the base still is preserved untouched).
    """
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)


# ---------------------------------------------------------------------------
# Overlay maths (numpy) — one RGBA layer per frame
# ---------------------------------------------------------------------------
def _overlay_rgba(loop: str, phase: float, plan: AnimationPlan, w: int, h: int):
    """Return an (h, w, 4) uint8 RGBA overlay for ``loop`` at ``phase``.

    The alpha channel already folds in the Hann envelope, so frame 0 (phase 0)
    is fully transparent for every loop.
    """
    if _np is None:  # pragma: no cover - numpy is present wherever we render
        raise AnimatedStillError("numpy is required to render animated stills")

    env = _envelope(phase)
    rgb = _np.zeros((h, w, 3), dtype=_np.float64)
    alpha = _np.zeros((h, w), dtype=_np.float64)

    xs = (_np.arange(w, dtype=_np.float64) + 0.5) / w  # column centres in [0,1)
    ys = (_np.arange(h, dtype=_np.float64) + 0.5) / h  # row centres in [0,1)
    u = xs[_np.newaxis, :]  # (1, w)
    v = ys[:, _np.newaxis]  # (h, 1)
    aspect = w / h
    accent = _hex_to_rgb(plan.palette["accent"])
    secondary = _hex_to_rgb(plan.palette["secondary"])

    if loop == "sheen":
        # Diagonal light band sweeping off-left → off-right; white brightening.
        skew = 0.35
        center = -0.3 + 1.6 * phase
        band_center = center + skew * (v - 0.5)  # (h,1) broadcast over u
        d = u - band_center
        g = _np.exp(-((d / 0.16) ** 2))
        rgb[:] = (255.0, 255.0, 255.0)
        alpha = g * env * _PEAK_ALPHA["sheen"]

    elif loop == "breathe":
        # Radial accent glow, slightly above centre, pulsing with the envelope.
        cx, cy = 0.5, 0.42
        radius = 0.34 * (1.0 + 0.06 * env)
        dist = _np.sqrt(((u - cx) * aspect) ** 2 + (v - cy) ** 2)
        falloff = _np.clip(1.0 - dist / radius, 0.0, 1.0) ** 2
        rgb[:] = accent
        alpha = falloff * env * _PEAK_ALPHA["breathe"]

    elif loop == "drift":
        # Slow-rising soft motes; each twinkles on its own phase offset.
        rng = _np.random.default_rng(plan.seed)
        n_motes = 14
        mx = rng.uniform(0.05, 0.95, n_motes)
        my0 = rng.uniform(0.0, 1.0, n_motes)
        msize = rng.uniform(0.018, 0.05, n_motes)  # radius in v-units
        mtwk = rng.uniform(0.0, 1.0, n_motes)  # twinkle phase offset
        mote_rgb = _hex_to_rgb(_lighten(plan.palette["accent"], 0.55))
        acc = _np.zeros((h, w), dtype=_np.float64)
        for i in range(n_motes):
            my = (my0[i] - 0.22 * phase) % 1.08 - 0.04  # drift up, wrap
            twk = 0.5 + 0.5 * math.sin(2.0 * math.pi * (phase + mtwk[i]))
            dist = _np.sqrt(((u - mx[i]) * aspect) ** 2 + (v - my) ** 2)
            blob = _np.exp(-((dist / msize[i]) ** 2))
            acc += blob * twk
        rgb[:] = mote_rgb
        alpha = _np.clip(acc, 0.0, 1.0) * env * _PEAK_ALPHA["drift"]

    elif loop == "tide":
        # Horizontal palette bands drifting downward; seamless (sin period = 1).
        freq = 3.0
        bands = _np.sin(2.0 * math.pi * (v * freq - phase))  # (h,1) → broadcast
        band_a = (0.5 + 0.5 * bands) * _np.ones_like(u)
        rgb[:] = secondary
        alpha = band_a * env * _PEAK_ALPHA["tide"]

    elif loop == "shimmer":
        # Faint seeded sparkle twinkling in place (coarse field, upscaled smooth).
        rng = _np.random.default_rng(plan.seed ^ 0x5EED)
        cells = 16
        mask = rng.uniform(0.0, 1.0, (cells, cells))
        nphase = rng.uniform(0.0, 1.0, (cells, cells))
        twk = 0.5 + 0.5 * _np.sin(2.0 * math.pi * (phase + nphase))
        noise_field = (mask**3) * twk  # bias toward darkness; a few bright cells
        # Nearest-neighbour upscale to (h,w) — deterministic, cheap.
        yi = _np.minimum((ys * cells).astype(int), cells - 1)
        xi = _np.minimum((xs * cells).astype(int), cells - 1)
        up = noise_field[_np.ix_(yi, xi)]
        rgb[:] = (255.0, 255.0, 255.0)
        alpha = up * env * _PEAK_ALPHA["shimmer"]

    else:  # unknown loop → inert (frame stays the base still)
        return _stack_rgba(rgb, alpha)

    return _stack_rgba(rgb, alpha)


def _stack_rgba(rgb, alpha):
    a = (_np.clip(alpha, 0.0, 1.0) * 255.0).astype(_np.uint8)
    rgb_u = _np.clip(rgb, 0.0, 255.0).astype(_np.uint8)
    return _np.dstack([rgb_u, a])


def _overlay_dims(w: int, h: int) -> tuple[int, int]:
    """Cap the overlay-compute canvas to keep cold renders cheap."""
    longest = max(w, h)
    if longest <= _OVERLAY_MAX_DIM:
        return w, h
    scale = _OVERLAY_MAX_DIM / longest
    return max(1, round(w * scale)), max(1, round(h * scale))


# ---------------------------------------------------------------------------
# Frame building + encoding
# ---------------------------------------------------------------------------
def _load_base(base_png: Any):
    if Image is None:  # pragma: no cover
        raise AnimatedStillError("Pillow is required to render animated stills")
    try:
        if isinstance(base_png, Image.Image):
            img = base_png
        elif isinstance(base_png, (bytes, bytearray)):
            img = Image.open(BytesIO(bytes(base_png)))
        else:
            img = Image.open(Path(base_png))
        return img.convert("RGBA")
    except AnimatedStillError:
        raise
    except Exception as e:
        raise AnimatedStillError(f"could not read base still: {e}") from e


def build_frames(base_png: Any, plan: AnimationPlan) -> list:
    """Render the loop to a list of ``plan.frames`` RGB PIL frames.

    Frame 0 is pixel-identical to ``base_png`` (the Hann envelope is 0 there).
    """
    if Image is None or _np is None:  # pragma: no cover
        raise AnimatedStillError("Pillow and numpy are required for animated stills")
    base = _load_base(base_png)
    w, h = base.size
    ow, oh = _overlay_dims(w, h)
    frames = []
    for i in range(plan.frames):
        phase = i / plan.frames
        over_arr = _overlay_rgba(plan.loop, phase, plan, ow, oh)
        over = Image.fromarray(over_arr, mode="RGBA")
        if (ow, oh) != (w, h):
            over = over.resize((w, h), Image.BILINEAR)
        frame = Image.alpha_composite(base, over).convert("RGB")
        frames.append(frame)
    return frames


def _encode_apng(frames: list, out: Path, duration_ms: int) -> int:
    frames[0].save(
        out,
        format="PNG",
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,  # loop forever
        disposal=1,  # restore to background before each frame
        default_image=False,
    )
    return out.stat().st_size


def _encode_gif(frames: list, out: Path, duration_ms: int) -> int:
    # Adaptive per-frame quantisation is deterministic (median cut). GIF is the
    # universally-embeddable fallback; APNG is the lossless default.
    pal_frames = [f.convert("P", palette=Image.ADAPTIVE, colors=256) for f in frames]
    pal_frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=pal_frames[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    return out.stat().st_size


@dataclass(frozen=True)
class AnimatedStillResult:
    """Explainability manifest for one exported loop."""

    path: str
    fmt: str
    loop: str
    frames: int
    fps: int
    duration_ms: int
    width: int
    height: int
    seed: int
    bytes_written: int
    why: str
    sidecar_path: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_EXT = {"apng": ".apng", "gif": ".gif"}


def export_animated_still(
    base_png: Any,
    out_path: str | Path,
    *,
    brief: Any = None,
    plan: Optional[AnimationPlan] = None,
    loop: str = "",
    fmt: str = "apng",
    frames: int = DEFAULT_FRAMES,
    fps: int = DEFAULT_FPS,
    seed: Optional[int] = None,
    palette: Optional[dict[str, str]] = None,
    write_manifest: bool = True,
) -> AnimatedStillResult:
    """Render a finished still into a looping APNG/GIF.

    ``base_png`` may be a path, raw PNG bytes, or a PIL image. The loop is taken
    from ``plan`` if given, else derived from ``brief`` (with explicit ``loop`` /
    ``frames`` / ``fps`` / ``seed`` / ``palette`` overriding the brief). Output is
    deterministic: identical inputs always produce byte-identical files.

    Returns an :class:`AnimatedStillResult`; writes a ``<out>.json`` manifest
    sidecar alongside the file unless ``write_manifest`` is False.
    """
    fmt = (fmt or "apng").strip().lower()
    if fmt not in _EXT:
        raise ValueError(f"unsupported animated-still format: {fmt!r} (use apng|gif)")

    if plan is None:
        if brief is not None:
            plan = plan_from_brief(brief, loop=loop, frames=frames, fps=fps, seed=seed)
        else:
            chosen = _coerce_loop(loop) or DEFAULT_LOOP
            pal = {k: _norm_hex(v) for k, v in (palette or {}).items()}
            for slot, dflt in (
                ("primary", "#101317"),
                ("secondary", "#101317"),
                ("accent", "#3DA9FC"),
            ):
                pal.setdefault(slot, dflt)
            plan = AnimationPlan(
                loop=chosen,
                palette=pal,
                seed=int(seed) if seed is not None else 0,
                frames=_clamp_frames(frames),
                fps=max(1, int(fps)),
            )
    if palette:  # explicit palette overrides whatever the plan carried
        merged = dict(plan.palette)
        merged.update({k: _norm_hex(v) for k, v in palette.items()})
        plan = AnimationPlan(
            loop=plan.loop, palette=merged, seed=plan.seed, frames=plan.frames, fps=plan.fps
        )

    out_path = Path(out_path).with_suffix(_EXT[fmt])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frames_imgs = build_frames(base_png, plan)
    w, h = frames_imgs[0].size
    if fmt == "apng":
        nbytes = _encode_apng(frames_imgs, out_path, plan.duration_ms)
    else:
        nbytes = _encode_gif(frames_imgs, out_path, plan.duration_ms)

    why = (
        f"{plan.loop} loop · {plan.frames} frames @ {plan.fps}fps "
        f"({plan.loop_seconds:.1f}s) · {fmt.upper()} · seamless Hann loop, "
        f"frame 0 == approved still"
    )
    sidecar = ""
    result = AnimatedStillResult(
        path=str(out_path),
        fmt=fmt,
        loop=plan.loop,
        frames=plan.frames,
        fps=plan.fps,
        duration_ms=plan.duration_ms,
        width=w,
        height=h,
        seed=plan.seed,
        bytes_written=nbytes,
        why=why,
    )
    if write_manifest:
        import json

        sidecar = str(out_path) + ".json"
        Path(sidecar).write_text(
            json.dumps(result.to_dict() | {"sidecar_path": sidecar}, indent=2), encoding="utf-8"
        )
        result = AnimatedStillResult(**(result.to_dict() | {"sidecar_path": sidecar}))
    return result


# ---------------------------------------------------------------------------
# CSS / SVG builder — consumed by the render hook for live HTML preview
# ---------------------------------------------------------------------------
# Live-preview peak opacity per loop — held low so the on-card text stays
# legible (the screen-blended layer brightens; it never blacks anything out).
# This mirrors the exporter's restraint, so the breathing preview reads at the
# same gentle intensity as the exported APNG/GIF.
_CSS_PEAK: dict[str, float] = {
    "sheen": 0.55,
    "breathe": 0.45,
    "drift": 0.6,
    "tide": 0.4,
    "shimmer": 0.4,
}


def _keyframes_for(loop: str, anim: str) -> str:
    """CSS @keyframes (a browser analogue of the PIL motion) for ``loop``.

    Opacity always runs 0 → peak → 0 (a subtle Hann-like bump) so the still
    screenshot (paused at 0%) is neutral and the live loop is seamless — the
    same contract as the exporter. The travel/scale gestures echo the per-loop
    motion the PIL frames draw.
    """
    peak = _CSS_PEAK.get(loop, 0.4)
    if loop == "sheen":
        body = (
            "0%{opacity:0;transform:translateX(-30%)}"
            f"50%{{opacity:{peak}}}"
            "100%{opacity:0;transform:translateX(30%)}"
        )
    elif loop == "breathe":
        body = (
            "0%{opacity:0;transform:scale(1.0)}"
            f"50%{{opacity:{peak};transform:scale(1.04)}}"
            "100%{opacity:0;transform:scale(1.0)}"
        )
    elif loop == "drift":
        body = (
            "0%{opacity:0;transform:translateY(6%)}"
            f"50%{{opacity:{peak}}}"
            "100%{opacity:0;transform:translateY(-6%)}"
        )
    elif loop == "tide":
        body = (
            "0%{opacity:0;transform:translateY(0)}"
            f"50%{{opacity:{peak}}}"
            "100%{opacity:0;transform:translateY(4%)}"
        )
    else:  # shimmer / unknown
        body = f"0%{{opacity:0}}50%{{opacity:{peak}}}100%{{opacity:0}}"
    return f"@keyframes {anim}{{{body}}}"


def _svg_layer(loop: str, plan: AnimationPlan, width: int, height: int) -> str:
    """A small inline SVG carrying the loop's colour field (normalised hex)."""
    accent = _norm_hex(plan.palette["accent"])
    secondary = _norm_hex(plan.palette["secondary"])
    vb = f"0 0 {width} {height}"
    if loop == "sheen" or loop == "shimmer":
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" preserveAspectRatio="none" '
            f'width="100%" height="100%"><defs><linearGradient id="mhasg" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0%" stop-color="#FFFFFF" stop-opacity="0"/>'
            f'<stop offset="50%" stop-color="#FFFFFF" stop-opacity="0.9"/>'
            f'<stop offset="100%" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient></defs>'
            f'<rect width="100%" height="100%" fill="url(#mhasg)"/></svg>'
        )
    if loop == "breathe":
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" preserveAspectRatio="none" '
            f'width="100%" height="100%"><defs><radialGradient id="mhasg" cx="50%" cy="42%" r="55%">'
            f'<stop offset="0%" stop-color="{accent}" stop-opacity="0.9"/>'
            f'<stop offset="100%" stop-color="{accent}" stop-opacity="0"/></radialGradient></defs>'
            f'<rect width="100%" height="100%" fill="url(#mhasg)"/></svg>'
        )
    # drift / tide — soft palette wash
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" preserveAspectRatio="none" '
        f'width="100%" height="100%"><defs><linearGradient id="mhasg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{secondary}" stop-opacity="0"/>'
        f'<stop offset="50%" stop-color="{secondary}" stop-opacity="0.85"/>'
        f'<stop offset="100%" stop-color="{secondary}" stop-opacity="0"/></linearGradient></defs>'
        f'<rect width="100%" height="100%" fill="url(#mhasg)"/></svg>'
    )


def build_animation_css(plan: AnimationPlan, width: int, height: int) -> str:
    """Return a self-contained ``<style>…</style><div…>`` fragment for the hook.

    The layer is full-bleed, ``pointer-events:none`` and screen-blended at low
    opacity (text stays legible). It is **paused at 0%** by default so a static
    screenshot is deterministic and neutral; a live preview can play it by
    setting ``animation-play-state: running`` on ``.mh-anim-still``.
    """
    loop = plan.loop if plan.loop in LOOPS else DEFAULT_LOOP
    anim = f"mh-anim-{loop}"
    # The @keyframes own the opacity envelope (0 → subtle peak → 0); the layer
    # itself sits at full opacity and is paused at 0% so the screenshot is
    # neutral. A live preview plays it via ``animation-play-state: running``.
    css = (
        f"<style>{_keyframes_for(loop, anim)}"
        f".mh-anim-still{{position:fixed;inset:0;z-index:60;pointer-events:none;"
        f"mix-blend-mode:screen;opacity:0;will-change:opacity,transform;"
        f"animation:{anim} {plan.loop_seconds:.2f}s ease-in-out infinite;"
        f"animation-play-state:paused}}"
        f".mh-anim-still svg{{width:100%;height:100%;display:block}}</style>"
    )
    layer = f'<div class="mh-anim-still mh-anim-still--{loop}" aria-hidden="true">{_svg_layer(loop, plan, width, height)}</div>'
    return css + layer


__all__ = [
    "LOOPS",
    "DEFAULT_LOOP",
    "DEFAULT_FRAMES",
    "DEFAULT_FPS",
    "AnimationPlan",
    "AnimatedStillResult",
    "AnimatedStillError",
    "select_loop",
    "plan_from_brief",
    "build_frames",
    "export_animated_still",
    "build_animation_css",
]
