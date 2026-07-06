"""Deterministic, non-destructive photo-edit engine (roadmap **1.3**).

The volunteer shoots on a phone in bad pool light; the wedge feature is *make
this photo usable on a card in 10 seconds*. This module is the intelligence
behind that: a serialisable :class:`EditRecipe` of bounded pixel operations that
is **applied at render time** to a *copy* of the original, so the source asset
is never mutated and the same photo can carry a different recipe per card.

Like :mod:`graphic_renderer.photo_adjust` (whose six tone primitives this module
reuses) and :mod:`graphic_renderer.saliency`, the engine lives on the
**deterministic side of the engine boundary** — the same colour-science rule
that keeps the ranker reproducible. Every operation is pure Pillow/numpy pixel
maths: *same image + same recipe → byte-identical output*, every run, with **no
LLM and no network** (one-click :func:`enhance_auto` is allowed to *suggest* a
recipe via ``media_ai`` elsewhere, but the maths here never calls a model).

Design rules
------------
* **Non-destructive.** A recipe is data; :meth:`EditRecipe.apply` returns a new
  image and never touches the source bytes on disk. The asset integration layer
  (:mod:`mediahub.media_library.photo_edit`) caches the materialised result by
  the recipe's :meth:`~EditRecipe.signature`.
* **Alpha is sacred.** Tone/colour/effect ops run on the visible RGB only and
  re-attach the original alpha untouched, so a cutout's mask never shifts. The
  ops that *make* alpha (shape crop, eraser) do so deliberately and explicitly.
* **Bounded + clamped.** Every parameter is clamped to a sane range, so a
  fat-fingered slider can dull or punch a photo but can never corrupt it.
* **Canonical order.** Geometry happens before tone before effects before masks,
  regardless of the order the UI added the steps, so the result is predictable.
  :meth:`EditRecipe.canonical` enforces it; :meth:`EditRecipe.with_op` keeps a
  recipe canonical as the editor mutates it.

Public API
----------
* :class:`EditOp` / :class:`EditRecipe` — the serialisable recipe model.
* :func:`enhance_auto` — the one-click deterministic auto-fix recipe.
* :func:`compose_grid` — the photo-collage / grid composer.
* The op primitives (``brightness``/``crop``/``duotone``/``blur_brush`` …) are
  exposed for direct use and unit testing.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

# Reuse the proven, test-guarded tone primitives rather than re-implementing
# them — single source of truth for the maths shared with the render-time stack.
from mediahub.graphic_renderer.photo_adjust import (
    auto_contrast as _auto_contrast,
    brightness as _brightness,
    contrast as _contrast,
    levels as _levels,
    saturation as _saturation,
    sharpen as _sharpen,
)

ImageLike = Union[str, bytes, Image.Image]

# A hard ceiling so a resize/expand can never allocate an absurd buffer.
_MAX_DIM = 8000

# Posted recipes are untrusted JSON (up to the request-body cap), so bound the
# work a single recipe can demand: at most this many steps per recipe and this
# many brush stamps per op. Legit UI recipes are single-instance per op (~15
# op kinds) and a dense manual brush pass is a few hundred stamps.
_MAX_STEPS = 40
_MAX_STAMPS = 2000


# --------------------------------------------------------------------------- #
# Clamps
# --------------------------------------------------------------------------- #

_BOUNDS: Dict[str, Tuple[float, float]] = {
    "factor": (0.0, 3.0),
    "unit": (-100.0, 100.0),  # symmetric slider amounts (warmth/tint/…)
    "amount01": (0.0, 1.0),  # 0..1 strength
    "amount100": (0.0, 100.0),  # 0..100 strength
    "degrees": (-360.0, 360.0),
    "perspective": (-1.0, 1.0),
    "frac": (0.0, 1.0),
    "blur_radius": (0.0, 60.0),
    "pixelate": (1.0, 256.0),
    "seed": (0.0, 9999.0),
}


def _clamp(value: Any, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    if v != v:  # NaN
        return lo
    return lo if v < lo else hi if v > hi else v


# --------------------------------------------------------------------------- #
# Alpha-preserving split / merge + numpy bridges
# --------------------------------------------------------------------------- #


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _split_alpha(img: Image.Image) -> Tuple[Image.Image, Optional[Image.Image]]:
    """``(rgb, alpha_or_None)`` — RGBA→RGB drops alpha without compositing."""
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        return rgba.convert("RGB"), rgba.getchannel("A")
    if img.mode == "RGB":
        return img, None
    return img.convert("RGB"), None


def _merge_alpha(rgb: Image.Image, alpha: Optional[Image.Image]) -> Image.Image:
    if alpha is None:
        return rgb
    out = rgb.convert("RGBA")
    if alpha.size != out.size:
        alpha = alpha.resize(out.size, Image.LANCZOS)
    out.putalpha(alpha)
    return out


def _rgb_array(img: Image.Image) -> Tuple[np.ndarray, Optional[Image.Image]]:
    """Float32 HxWx3 in 0..255 of the visible RGB, plus the split-off alpha."""
    rgb, alpha = _split_alpha(img)
    return np.asarray(rgb, dtype=np.float32), alpha


def _from_rgb_array(arr: np.ndarray, alpha: Optional[Image.Image]) -> Image.Image:
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return _merge_alpha(out, alpha)


def _luma(arr: np.ndarray) -> np.ndarray:
    """Rec.601 luminance of an HxWx3 array, shape HxW."""
    return arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114


# --------------------------------------------------------------------------- #
# Tone / colour adjustments (the broad slider set)
# --------------------------------------------------------------------------- #


def warmth(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """Temperature: ``+`` warms (red up / blue down), ``-`` cools. amount -100..100."""
    a = _clamp(amount, *_BOUNDS["unit"])
    if a == 0.0:
        return img
    arr, alpha = _rgb_array(img)
    shift = (a / 100.0) * 40.0  # up to ±40 levels at the extremes
    arr[..., 0] += shift
    arr[..., 2] -= shift
    return _from_rgb_array(arr, alpha)


def tint(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """Green↔magenta tint. ``+`` adds magenta (R/B up, G down), ``-`` adds green."""
    a = _clamp(amount, *_BOUNDS["unit"])
    if a == 0.0:
        return img
    arr, alpha = _rgb_array(img)
    shift = (a / 100.0) * 30.0
    arr[..., 0] += shift * 0.5
    arr[..., 2] += shift * 0.5
    arr[..., 1] -= shift
    return _from_rgb_array(arr, alpha)


def highlights(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """Recover/boost the bright tones only. amount -100 (recover) .. 100 (boost)."""
    a = _clamp(amount, *_BOUNDS["unit"])
    if a == 0.0:
        return img
    arr, alpha = _rgb_array(img)
    y = _luma(arr) / 255.0
    mask = np.clip((y - 0.5) * 2.0, 0.0, 1.0) ** 1.5  # 0 in shadows → 1 in highlights
    arr += (a / 100.0) * 70.0 * mask[..., None]
    return _from_rgb_array(arr, alpha)


def shadows(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """Lift/deepen the dark tones only. amount -100 (deepen) .. 100 (lift)."""
    a = _clamp(amount, *_BOUNDS["unit"])
    if a == 0.0:
        return img
    arr, alpha = _rgb_array(img)
    y = _luma(arr) / 255.0
    mask = np.clip((0.5 - y) * 2.0, 0.0, 1.0) ** 1.5  # 1 in shadows → 0 in highlights
    arr += (a / 100.0) * 70.0 * mask[..., None]
    return _from_rgb_array(arr, alpha)


def white_balance(img: Image.Image, amount: float = 1.0) -> Image.Image:
    """Gray-world auto white balance — neutralise a colour cast (e.g. pool cyan).

    ``amount`` (0..1) is the strength of the correction toward a neutral grey;
    1.0 is a full gray-world balance, 0.0 a no-op. Deterministic per image.
    """
    a = _clamp(amount, *_BOUNDS["amount01"])
    if a == 0.0:
        return img
    arr, alpha = _rgb_array(img)
    means = arr.reshape(-1, 3).mean(axis=0)
    grey = float(means.mean())
    if grey <= 0:
        return img
    gains = grey / np.clip(means, 1.0, None)
    gains = 1.0 + (gains - 1.0) * a  # blend the gain toward identity by `amount`
    arr = arr * gains[None, None, :]
    return _from_rgb_array(arr, alpha)


def clarity(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """Local-contrast 'texture' punch via a wide-radius unsharp. amount 0..100."""
    a = _clamp(amount, *_BOUNDS["amount100"])
    if a <= 0.0:
        return img
    rgb, alpha = _split_alpha(img)
    radius = max(2.0, min(rgb.size) / 50.0)
    percent = int(round(a * 1.6))
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))
    return _merge_alpha(rgb, alpha)


# --------------------------------------------------------------------------- #
# Effects
# --------------------------------------------------------------------------- #


def grayscale(img: Image.Image, amount: float = 1.0) -> Image.Image:
    """Desaturate by ``amount`` (0..1). 1.0 = full mono, alpha preserved."""
    return _saturation(img, 1.0 - _clamp(amount, *_BOUNDS["amount01"]))


def sepia(img: Image.Image, amount: float = 1.0) -> Image.Image:
    """Classic sepia tone, blended in by ``amount`` (0..1)."""
    a = _clamp(amount, *_BOUNDS["amount01"])
    if a <= 0.0:
        return img
    arr, alpha = _rgb_array(img)
    y = _luma(arr)
    toned = np.stack([y * 1.07, y * 0.82, y * 0.63], axis=-1)
    out = arr * (1.0 - a) + toned * a
    return _from_rgb_array(out, alpha)


def duotone(
    img: Image.Image,
    shadow: str = "#0b1020",
    highlight: str = "#f5f7ff",
    amount: float = 1.0,
) -> Image.Image:
    """Map luminance onto a two-colour gradient (``shadow``→``highlight``).

    Honours a brand palette when the caller passes brand colours. ``amount``
    (0..1) blends the duotone back toward the original.
    """
    a = _clamp(amount, *_BOUNDS["amount01"])
    if a <= 0.0:
        return img
    lo = np.array(_hex_rgb(shadow), dtype=np.float32)
    hi = np.array(_hex_rgb(highlight), dtype=np.float32)
    arr, alpha = _rgb_array(img)
    t = (_luma(arr) / 255.0)[..., None]
    mapped = lo[None, None, :] * (1.0 - t) + hi[None, None, :] * t
    out = arr * (1.0 - a) + mapped * a
    return _from_rgb_array(out, alpha)


def golden_hour(img: Image.Image, amount: float = 1.0) -> Image.Image:
    """Warm, glowing late-afternoon grade. ``amount`` 0..1."""
    a = _clamp(amount, *_BOUNDS["amount01"])
    if a <= 0.0:
        return img
    out = warmth(img, 35.0 * a)
    out = _saturation(out, 1.0 + 0.12 * a)
    out = _contrast(out, 1.0 + 0.06 * a)
    return out


def colour_punch(img: Image.Image, amount: float = 0.0) -> Image.Image:
    """The 'make it pop' combo — saturation + contrast together. amount 0..100."""
    a = _clamp(amount, *_BOUNDS["amount100"]) / 100.0
    if a <= 0.0:
        return img
    out = _saturation(img, 1.0 + 0.45 * a)
    out = _contrast(out, 1.0 + 0.20 * a)
    return out


def blur(img: Image.Image, radius: float = 0.0) -> Image.Image:
    """Whole-image Gaussian blur. ``radius`` 0..60 px."""
    r = _clamp(radius, *_BOUNDS["blur_radius"])
    if r <= 0.0:
        return img
    rgb, alpha = _split_alpha(img)
    rgb = rgb.filter(ImageFilter.GaussianBlur(radius=r))
    return _merge_alpha(rgb, alpha)


def pixelate(img: Image.Image, size: float = 1.0) -> Image.Image:
    """Mosaic/pixelate to ``size``-px blocks (also a face-anonymising tool)."""
    block = int(_clamp(size, *_BOUNDS["pixelate"]))
    if block <= 1:
        return img
    rgb, alpha = _split_alpha(img)
    w, h = rgb.size
    small = rgb.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
    rgb = small.resize((w, h), Image.NEAREST)
    return _merge_alpha(rgb, alpha)


def glitch(img: Image.Image, amount: float = 0.0, seed: int = 0) -> Image.Image:
    """Deterministic RGB channel-shift glitch. ``amount`` 0..100, ``seed`` stable."""
    a = _clamp(amount, *_BOUNDS["amount100"])
    if a <= 0.0:
        return img
    s = int(_clamp(seed, *_BOUNDS["seed"]))
    arr, alpha = _rgb_array(img)
    w = arr.shape[1]
    mag = int(round((a / 100.0) * w * 0.05)) or 1
    # Stable per-channel offsets derived from the seed — no RNG state.
    dr = ((s * 7 + 3) % (2 * mag + 1)) - mag
    db = ((s * 13 + 5) % (2 * mag + 1)) - mag
    arr[..., 0] = np.roll(arr[..., 0], dr, axis=1)
    arr[..., 2] = np.roll(arr[..., 2], db, axis=1)
    return _from_rgb_array(arr, alpha)


def vignette(img: Image.Image, amount: float = 0.0, feather: float = 0.5) -> Image.Image:
    """Darken the corners. ``amount`` 0..100 strength, ``feather`` 0..1 softness."""
    a = _clamp(amount, *_BOUNDS["amount100"]) / 100.0
    if a <= 0.0:
        return img
    f = _clamp(feather, *_BOUNDS["amount01"])
    arr, alpha = _rgb_array(img)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    dist = np.sqrt(((xx - cx) / (w / 2.0)) ** 2 + ((yy - cy) / (h / 2.0)) ** 2)
    inner = 0.45 + 0.5 * f
    mask = np.clip((dist - inner) / max(1e-3, (1.45 - inner)), 0.0, 1.0)
    factor = 1.0 - a * mask
    arr *= factor[..., None]
    return _from_rgb_array(arr, alpha)


def opacity(img: Image.Image, alpha: float = 1.0) -> Image.Image:
    """Scale the overall alpha by ``alpha`` (0..1); always returns RGBA."""
    a = _clamp(alpha, *_BOUNDS["amount01"])
    rgba = img.convert("RGBA")
    if a >= 1.0:
        return rgba
    band = rgba.getchannel("A").point(lambda v: int(v * a))
    rgba.putalpha(band)
    return rgba


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #


def crop(
    img: Image.Image, x: float = 0.0, y: float = 0.0, w: float = 1.0, h: float = 1.0
) -> Image.Image:
    """Crop to a rectangle in **fractions of the current image** (0..1).

    Resolution-independent: ``(x, y)`` is the top-left, ``(w, h)`` the size, all
    as fractions, so the same recipe crops a thumbnail and a full-res export
    identically. A degenerate box returns the image unchanged.
    """
    iw, ih = img.size
    fx = _clamp(x, *_BOUNDS["frac"])
    fy = _clamp(y, *_BOUNDS["frac"])
    fw = _clamp(w, *_BOUNDS["frac"])
    fh = _clamp(h, *_BOUNDS["frac"])
    left = int(round(fx * iw))
    top = int(round(fy * ih))
    right = int(round(min(1.0, fx + fw) * iw))
    bottom = int(round(min(1.0, fy + fh) * ih))
    if right - left < 1 or bottom - top < 1:
        return img
    if (left, top, right, bottom) == (0, 0, iw, ih):
        return img
    return img.crop((left, top, right, bottom))


def flip(img: Image.Image, axis: str = "h") -> Image.Image:
    """Mirror horizontally (``"h"``) or vertically (``"v"``)."""
    if str(axis).lower().startswith("v"):
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.transpose(Image.FLIP_LEFT_RIGHT)


def rotate(img: Image.Image, degrees: float = 0.0, expand: bool = True) -> Image.Image:
    """Rotate counter-clockwise by ``degrees``; right-angles are lossless.

    Arbitrary angles ``expand`` the canvas and fill the new corners with
    transparency (so no content is cropped and the fill never invents pixels).
    """
    d = _clamp(degrees, *_BOUNDS["degrees"]) % 360.0
    if d == 0.0:
        return img
    if d == 90.0:
        return img.transpose(Image.ROTATE_90)
    if d == 180.0:
        return img.transpose(Image.ROTATE_180)
    if d == 270.0:
        return img.transpose(Image.ROTATE_270)
    base = img.convert("RGBA")
    out = base.rotate(d, resample=Image.BICUBIC, expand=bool(expand))
    if not _has_alpha(img):
        # Composite onto white so a non-transparent source stays non-transparent
        # except where the rotation genuinely exposed new corners.
        bg = Image.new("RGBA", out.size, (255, 255, 255, 0))
        bg.alpha_composite(out)
        return bg
    return out


def resize(img: Image.Image, width: int = 0, height: int = 0, scale: float = 0.0) -> Image.Image:
    """Resize by explicit ``width``/``height`` or a ``scale`` factor.

    A zero ``width`` *or* ``height`` is inferred from the other to preserve the
    aspect ratio. All dimensions are clamped to a sane ceiling.
    """
    iw, ih = img.size
    if scale and scale > 0:
        tw = int(round(iw * scale))
        th = int(round(ih * scale))
    else:
        tw = int(width or 0)
        th = int(height or 0)
        if not tw and not th:
            return img  # no target specified → no-op (never collapse to 1×1)
        if tw and not th:
            th = int(round(ih * (tw / iw)))
        elif th and not tw:
            tw = int(round(iw * (th / ih)))
    tw = max(1, min(_MAX_DIM, tw))
    th = max(1, min(_MAX_DIM, th))
    if (tw, th) == (iw, ih):
        return img
    return img.resize((tw, th), Image.LANCZOS)


def _perspective_coeffs(
    src: Sequence[Tuple[float, float]], dst: Sequence[Tuple[float, float]]
) -> Tuple[float, ...]:
    """Solve the 8 PIL PERSPECTIVE coefficients mapping ``dst`` → ``src``."""
    matrix = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        matrix.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        matrix.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    a = np.array(matrix, dtype=np.float64)
    b = np.array([c for pt in src for c in pt], dtype=np.float64)
    res = np.linalg.solve(a, b)
    return tuple(float(v) for v in res)


def perspective(img: Image.Image, h: float = 0.0, v: float = 0.0) -> Image.Image:
    """Keystone-correct perspective. ``h``/``v`` in -1..1 (horizontal/vertical)."""
    hh = _clamp(h, *_BOUNDS["perspective"])
    vv = _clamp(v, *_BOUNDS["perspective"])
    if hh == 0.0 and vv == 0.0:
        return img
    w, ht = img.size
    kx = abs(hh) * 0.25 * w  # horizontal keystone inset (px)
    ky = abs(vv) * 0.25 * ht  # vertical keystone inset (px)
    # Destination quad corners, clockwise from top-left.
    tl = [0.0, 0.0]
    tr = [float(w), 0.0]
    br = [float(w), float(ht)]
    bl = [0.0, float(ht)]
    # Vertical keystone: narrow the top edge (v>0) or the bottom edge (v<0).
    if vv > 0:
        tl[0] += ky
        tr[0] -= ky
    elif vv < 0:
        bl[0] += ky
        br[0] -= ky
    # Horizontal keystone: narrow the left edge (h>0) or the right edge (h<0).
    if hh > 0:
        tl[1] += kx
        bl[1] -= kx
    elif hh < 0:
        tr[1] += kx
        br[1] -= kx
    dst = [tuple(tl), tuple(tr), tuple(br), tuple(bl)]
    src = [(0, 0), (w, 0), (w, ht), (0, ht)]
    coeffs = _perspective_coeffs(src, dst)
    base = img.convert("RGBA")
    return base.transform((w, ht), Image.PERSPECTIVE, coeffs, Image.BICUBIC)


# --------------------------------------------------------------------------- #
# Masks — crop-to-shape, frames, and the local brush ops
# --------------------------------------------------------------------------- #

SHAPES: Tuple[str, ...] = ("circle", "oval", "square", "rounded", "triangle", "star", "heart")


def _shape_mask(shape: str, size: Tuple[int, int]) -> Image.Image:
    """An 'L' mask (255 inside the shape) for ``shape`` at ``size``."""
    w, h = size
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    shape = (shape or "circle").lower()
    if shape in ("circle", "oval"):
        if shape == "circle":
            r = min(w, h)
            box = ((w - r) // 2, (h - r) // 2, (w - r) // 2 + r, (h - r) // 2 + r)
        else:
            box = (0, 0, w, h)
        d.ellipse(box, fill=255)
    elif shape == "rounded":
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(min(w, h) * 0.12), fill=255)
    elif shape == "square":
        s = min(w, h)
        d.rectangle(
            ((w - s) // 2, (h - s) // 2, (w - s) // 2 + s - 1, (h - s) // 2 + s - 1), fill=255
        )
    elif shape == "triangle":
        d.polygon([(w / 2, 0), (w, h), (0, h)], fill=255)
    elif shape == "star":
        d.polygon(_star_points(w, h), fill=255)
    elif shape == "heart":
        d.polygon(_heart_points(w, h), fill=255)
    else:
        d.ellipse((0, 0, w, h), fill=255)
    return mask


def _star_points(w: int, h: int, points: int = 5) -> List[Tuple[float, float]]:
    cx, cy = w / 2.0, h / 2.0
    rad_o = min(w, h) / 2.0
    rad_i = rad_o * 0.42
    pts: List[Tuple[float, float]] = []
    for i in range(points * 2):
        ang = math.pi / points * i - math.pi / 2.0
        r = rad_o if i % 2 == 0 else rad_i
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _heart_points(w: int, h: int, n: int = 60) -> List[Tuple[float, float]]:
    pts: List[Tuple[float, float]] = []
    for i in range(n + 1):
        t = math.pi * 2 * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x, -y))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    sx = w / (maxx - minx)
    sy = h / (maxy - miny)
    s = min(sx, sy)
    ox = (w - (maxx - minx) * s) / 2.0
    oy = (h - (maxy - miny) * s) / 2.0
    return [((x - minx) * s + ox, (y - miny) * s + oy) for x, y in pts]


def shape_crop(img: Image.Image, shape: str = "circle", feather: float = 0.0) -> Image.Image:
    """Crop the photo into ``shape``, leaving transparency outside it.

    The canvas size is unchanged (the shape sits on a transparent field), so a
    downstream composite places it exactly where the rectangle was. ``feather``
    (0..1) softens the mask edge.
    """
    if shape not in SHAPES:
        return img
    rgba = img.convert("RGBA")
    mask = _shape_mask(shape, rgba.size)
    f = _clamp(feather, *_BOUNDS["amount01"])
    if f > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, f * min(rgba.size) * 0.06)))
    base = rgba.getchannel("A")
    combined = Image.composite(base, Image.new("L", rgba.size, 0), mask)
    rgba.putalpha(combined)
    return rgba


def frame(
    img: Image.Image, style: str = "solid", colour: str = "#ffffff", width: float = 0.04
) -> Image.Image:
    """Draw a border *inside* the image edges. ``width`` is a fraction of the short side."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    bw = max(1, int(_clamp(width, *_BOUNDS["frac"]) * min(w, h)))
    if bw <= 0:
        return rgba
    rgb = tuple(_hex_rgb(colour)) + (255,)
    d = ImageDraw.Draw(rgba)
    if style == "polaroid":
        # Even border on three sides, a deeper sill at the bottom.
        d.rectangle((0, 0, w - 1, bw), fill=rgb)
        d.rectangle((0, 0, bw, h - 1), fill=rgb)
        d.rectangle((w - bw, 0, w - 1, h - 1), fill=rgb)
        d.rectangle((0, h - bw * 3, w - 1, h - 1), fill=rgb)
    else:
        for i in range(bw):
            d.rectangle((i, i, w - 1 - i, h - 1 - i), outline=rgb)
    return rgba


def _stamp_regions(params: Dict[str, Any]) -> List[Tuple[float, float, float, float]]:
    """Normalise a brush/eraser param dict to ``[(cx, cy, r, strength), …]``.

    Each stamp's ``cx``/``cy``/``r`` are fractions of the image (resolution-free),
    ``strength`` an optional 0..1 (defaults to 1). Junk stamps are dropped.
    """
    out: List[Tuple[float, float, float, float]] = []
    for s in params.get("stamps", []) or []:
        if len(out) >= _MAX_STAMPS:
            break
        if not isinstance(s, dict):
            continue
        cx = _clamp(s.get("cx", 0.5), *_BOUNDS["frac"])
        cy = _clamp(s.get("cy", 0.5), *_BOUNDS["frac"])
        r = _clamp(s.get("r", 0.05), 0.0, 1.0)
        st = _clamp(s.get("strength", 1.0), *_BOUNDS["amount01"])
        if r <= 0:
            continue
        out.append((cx, cy, r, st))
    return out


def _stamp_mask(
    size: Tuple[int, int], stamps: Sequence[Tuple[float, float, float, float]]
) -> Image.Image:
    """An 'L' mask painted from circular stamps (max strength wins on overlap).

    All discs are drawn into ONE shared mask, weakest first, so a stronger disc
    overwrites any overlap — max-wins for uniform-value discs — without
    allocating a full-size image per stamp (recipes are untrusted input).
    """
    w, h = size
    mask = Image.new("L", size, 0)
    short = min(w, h)
    dd = ImageDraw.Draw(mask)
    for cx, cy, r, st in sorted(stamps, key=lambda s: s[3]):
        px, py = cx * w, cy * h
        rad = r * short
        val = int(round(st * 255))
        dd.ellipse((px - rad, py - rad, px + rad, py + rad), fill=val)
    return mask


def blur_brush(
    img: Image.Image, stamps: Optional[list] = None, radius: float = 12.0, feather: float = 0.4
) -> Image.Image:
    """Locally blur the painted regions — the safeguarding tool (blur a face).

    ``stamps`` is a list of ``{cx, cy, r, strength}`` discs in image fractions;
    ``radius`` is the blur strength in px. Pixels outside every stamp are
    untouched, so the rest of the photo stays sharp.
    """
    regions = _stamp_regions({"stamps": stamps or []})
    if not regions:
        return img
    r = _clamp(radius, *_BOUNDS["blur_radius"]) or 12.0
    rgba = img.convert("RGBA")
    blurred = rgba.filter(ImageFilter.GaussianBlur(radius=r))
    mask = _stamp_mask(rgba.size, regions)
    f = _clamp(feather, *_BOUNDS["amount01"])
    if f > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, f * r)))
    out = Image.composite(blurred, rgba, mask)
    if not _has_alpha(img):
        return out.convert("RGB") if out.getchannel("A").getextrema() == (255, 255) else out
    return out


def eraser(img: Image.Image, stamps: Optional[list] = None, feather: float = 0.3) -> Image.Image:
    """Manually erase (make transparent) the painted regions. Always RGBA out."""
    regions = _stamp_regions({"stamps": stamps or []})
    rgba = img.convert("RGBA")
    if not regions:
        return rgba
    mask = _stamp_mask(rgba.size, regions)
    f = _clamp(feather, *_BOUNDS["amount01"])
    if f > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, f * min(rgba.size) * 0.03)))
    base = rgba.getchannel("A")
    # Erase = subtract the stamp coverage from the existing alpha.
    new_alpha = ImageChops.subtract(base, mask)
    rgba.putalpha(new_alpha)
    return rgba


# --------------------------------------------------------------------------- #
# Named filter strip — a look applied at an intensity
# --------------------------------------------------------------------------- #

# Each filter is a small ordered op stack (op-name → params). The strip applies
# it at full strength, then blends back toward the original by (1 - intensity),
# so the same filter at 0.0 is the identity and at 1.0 the full look.
FILTERS: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
    "mono": [("grayscale", {"amount": 1.0}), ("contrast", {"factor": 1.06})],
    "noir": [
        ("grayscale", {"amount": 1.0}),
        ("contrast", {"factor": 1.28}),
        ("vignette", {"amount": 30}),
    ],
    "sepia": [("sepia", {"amount": 1.0})],
    "natural": [("auto_contrast", {"cutoff": 0.5}), ("sharpen", {"amount": 0.5})],
    "crisp": [("sharpen", {"amount": 0.9}), ("contrast", {"factor": 1.05})],
    "punchy": [
        ("contrast", {"factor": 1.12}),
        ("saturation", {"factor": 1.15}),
        ("sharpen", {"amount": 0.8}),
    ],
    "vivid": [("saturation", {"factor": 1.28}), ("contrast", {"factor": 1.08})],
    "editorial": [
        ("contrast", {"factor": 1.06}),
        ("saturation", {"factor": 0.92}),
        ("levels", {"black": 6, "white": 250, "gamma": 0.98}),
    ],
    "soft": [
        ("contrast", {"factor": 0.94}),
        ("brightness", {"factor": 1.04}),
        ("saturation", {"factor": 0.96}),
    ],
    "golden": [("golden_hour", {"amount": 1.0})],
    "poolside": [
        ("white_balance", {"amount": 0.8}),
        ("auto_contrast", {"cutoff": 0.5}),
        ("saturation", {"factor": 1.08}),
    ],
}

FILTER_NAMES: Tuple[str, ...] = tuple(FILTERS.keys())


def apply_filter(img: Image.Image, name: str, intensity: float = 1.0) -> Image.Image:
    """Apply named filter ``name`` at ``intensity`` (0..1) by blending."""
    spec = FILTERS.get((name or "").lower())
    if not spec:
        return img
    inten = _clamp(intensity, *_BOUNDS["amount01"])
    if inten <= 0.0:
        return img
    looked = img
    for op_name, params in spec:
        fn = _OPS.get(op_name)
        if fn is not None:
            looked = fn(looked, **params)
    if inten >= 1.0:
        return looked
    base = img.convert(looked.mode)
    if base.size != looked.size:
        base = base.resize(looked.size, Image.LANCZOS)
    return Image.blend(base, looked, inten)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _hex_rgb(value: str) -> Tuple[int, int, int]:
    s = str(value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return (0, 0, 0)
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return (0, 0, 0)


# --------------------------------------------------------------------------- #
# Op dispatch table + param coercion
# --------------------------------------------------------------------------- #

# op name → callable(img, **params). The render-time tone primitives are reused
# from photo_adjust; everything else is defined above.
_OPS: Dict[str, Callable[..., Image.Image]] = {
    # geometry
    "crop": crop,
    "perspective": perspective,
    "rotate": rotate,
    "flip": flip,
    "resize": resize,
    # tone / colour
    "white_balance": white_balance,
    "auto_contrast": _auto_contrast,
    "levels": _levels,
    "brightness": _brightness,
    "contrast": _contrast,
    "highlights": highlights,
    "shadows": shadows,
    "warmth": warmth,
    "tint": tint,
    "saturation": _saturation,
    "clarity": clarity,
    "sharpen": _sharpen,
    # filter strip
    "filter": apply_filter,
    # effects
    "grayscale": grayscale,
    "sepia": sepia,
    "duotone": duotone,
    "golden_hour": golden_hour,
    "colour_punch": colour_punch,
    "vignette": vignette,
    "blur": blur,
    "pixelate": pixelate,
    "glitch": glitch,
    # local
    "blur_brush": blur_brush,
    "eraser": eraser,
    # masks / output
    "shape_crop": shape_crop,
    "frame": frame,
    "opacity": opacity,
}

# Canonical pipeline order: geometry → tone → filter → effects → local → mask.
_OP_RANK: Dict[str, int] = {
    "crop": 10,
    "perspective": 20,
    "rotate": 30,
    "flip": 40,
    "resize": 50,
    "white_balance": 90,
    "auto_contrast": 95,
    "levels": 100,
    "brightness": 110,
    "contrast": 120,
    "highlights": 130,
    "shadows": 140,
    "warmth": 150,
    "tint": 160,
    "saturation": 170,
    "clarity": 180,
    "sharpen": 190,
    "filter": 300,
    "grayscale": 400,
    "sepia": 410,
    "duotone": 420,
    "golden_hour": 430,
    "colour_punch": 440,
    "vignette": 500,
    "blur": 510,
    "pixelate": 520,
    "glitch": 530,
    "blur_brush": 600,
    "eraser": 610,
    "shape_crop": 700,
    "frame": 710,
    "opacity": 800,
}


def _coerce_params(op: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + clamp the params for ``op`` into a canonical, JSON-safe dict."""
    p = dict(params or {})
    if op in ("brightness", "contrast", "saturation"):
        return {"factor": round(_clamp(p.get("factor", 1.0), *_BOUNDS["factor"]), 4)}
    if op == "sharpen":
        return {
            "amount": round(_clamp(p.get("amount", 1.0), 0.0, 4.0), 4),
            "radius": round(_clamp(p.get("radius", 2.0), 0.1, 8.0), 4),
            "threshold": int(_clamp(p.get("threshold", 3), 0.0, 255.0)),
        }
    if op == "levels":
        return {
            "black": int(_clamp(p.get("black", 0), 0.0, 255.0)),
            "white": int(_clamp(p.get("white", 255), 0.0, 255.0)),
            "gamma": round(_clamp(p.get("gamma", 1.0), 0.2, 5.0), 4),
        }
    if op == "auto_contrast":
        return {"cutoff": round(_clamp(p.get("cutoff", 0.0), 0.0, 49.0), 4)}
    if op in ("warmth", "tint", "highlights", "shadows"):
        return {"amount": round(_clamp(p.get("amount", 0.0), *_BOUNDS["unit"]), 4)}
    if op in ("clarity", "colour_punch", "vignette", "glitch"):
        out = {"amount": round(_clamp(p.get("amount", 0.0), *_BOUNDS["amount100"]), 4)}
        if op == "vignette":
            out["feather"] = round(_clamp(p.get("feather", 0.5), *_BOUNDS["amount01"]), 4)
        if op == "glitch":
            out["seed"] = int(_clamp(p.get("seed", 0), *_BOUNDS["seed"]))
        return out
    if op == "white_balance":
        return {"amount": round(_clamp(p.get("amount", 1.0), *_BOUNDS["amount01"]), 4)}
    if op in ("grayscale", "sepia", "golden_hour"):
        return {"amount": round(_clamp(p.get("amount", 1.0), *_BOUNDS["amount01"]), 4)}
    if op == "opacity":
        return {"alpha": round(_clamp(p.get("alpha", 1.0), *_BOUNDS["amount01"]), 4)}
    if op == "duotone":
        return {
            "shadow": _hex_str(p.get("shadow", "#0b1020")),
            "highlight": _hex_str(p.get("highlight", "#f5f7ff")),
            "amount": round(_clamp(p.get("amount", 1.0), *_BOUNDS["amount01"]), 4),
        }
    if op == "blur":
        return {"radius": round(_clamp(p.get("radius", 0.0), *_BOUNDS["blur_radius"]), 4)}
    if op == "pixelate":
        return {"size": int(_clamp(p.get("size", 1), *_BOUNDS["pixelate"]))}
    if op == "crop":
        return {
            "x": round(_clamp(p.get("x", 0.0), *_BOUNDS["frac"]), 5),
            "y": round(_clamp(p.get("y", 0.0), *_BOUNDS["frac"]), 5),
            "w": round(_clamp(p.get("w", 1.0), *_BOUNDS["frac"]), 5),
            "h": round(_clamp(p.get("h", 1.0), *_BOUNDS["frac"]), 5),
        }
    if op == "flip":
        return {"axis": "v" if str(p.get("axis", "h")).lower().startswith("v") else "h"}
    if op == "rotate":
        return {
            "degrees": round(_clamp(p.get("degrees", 0.0), *_BOUNDS["degrees"]), 3),
            "expand": bool(p.get("expand", True)),
        }
    if op == "resize":
        return {
            "width": int(max(0, min(_MAX_DIM, int(p.get("width", 0) or 0)))),
            "height": int(max(0, min(_MAX_DIM, int(p.get("height", 0) or 0)))),
            "scale": round(_clamp(p.get("scale", 0.0), 0.0, 16.0), 4),
        }
    if op == "perspective":
        return {
            "h": round(_clamp(p.get("h", 0.0), *_BOUNDS["perspective"]), 4),
            "v": round(_clamp(p.get("v", 0.0), *_BOUNDS["perspective"]), 4),
        }
    if op == "shape_crop":
        shape = str(p.get("shape", "circle")).lower()
        return {
            "shape": shape if shape in SHAPES else "circle",
            "feather": round(_clamp(p.get("feather", 0.0), *_BOUNDS["amount01"]), 4),
        }
    if op == "frame":
        return {
            "style": str(p.get("style", "solid")).lower(),
            "colour": _hex_str(p.get("colour", "#ffffff")),
            "width": round(_clamp(p.get("width", 0.04), *_BOUNDS["frac"]), 4),
        }
    if op == "filter":
        name = str(p.get("name", "")).lower()
        return {
            "name": name if name in FILTERS else "",
            "intensity": round(_clamp(p.get("intensity", 1.0), *_BOUNDS["amount01"]), 4),
        }
    if op in ("blur_brush", "eraser"):
        out = {"stamps": _canon_stamps(p.get("stamps", []))}
        if op == "blur_brush":
            out["radius"] = round(_clamp(p.get("radius", 12.0), *_BOUNDS["blur_radius"]), 3)
            out["feather"] = round(_clamp(p.get("feather", 0.4), *_BOUNDS["amount01"]), 4)
        else:
            out["feather"] = round(_clamp(p.get("feather", 0.3), *_BOUNDS["amount01"]), 4)
        return out
    return {}


def _hex_str(value: Any) -> str:
    r, g, b = _hex_rgb(str(value))
    return f"#{r:02x}{g:02x}{b:02x}"


def _canon_stamps(stamps: Any) -> List[Dict[str, float]]:
    out: List[Dict[str, float]] = []
    for s in stamps or []:
        if len(out) >= _MAX_STAMPS:
            break
        if not isinstance(s, dict):
            continue
        out.append(
            {
                "cx": round(_clamp(s.get("cx", 0.5), *_BOUNDS["frac"]), 5),
                "cy": round(_clamp(s.get("cy", 0.5), *_BOUNDS["frac"]), 5),
                "r": round(_clamp(s.get("r", 0.05), 0.0, 1.0), 5),
                "strength": round(_clamp(s.get("strength", 1.0), *_BOUNDS["amount01"]), 4),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Recipe model
# --------------------------------------------------------------------------- #


@dataclass
class EditOp:
    """One validated edit operation: an op name + clamped, JSON-safe params."""

    op: str
    params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.op = str(self.op)
        self.params = _coerce_params(self.op, self.params)

    @property
    def valid(self) -> bool:
        return self.op in _OPS

    @property
    def rank(self) -> int:
        return _OP_RANK.get(self.op, 999)

    def apply(self, img: Image.Image) -> Image.Image:
        fn = _OPS.get(self.op)
        if fn is None:
            return img
        return fn(img, **self.params)

    def to_dict(self) -> Dict[str, Any]:
        return {"op": self.op, "params": dict(self.params)}


@dataclass
class EditRecipe:
    """An ordered, validated, serialisable, non-destructive edit recipe.

    Invalid steps are dropped on construction so a recipe is always runnable.
    Use :meth:`with_op` to add/replace an op and keep the recipe in canonical
    pipeline order; :meth:`apply` runs the steps in their stored order.
    """

    steps: Tuple[EditOp, ...] = ()

    def __post_init__(self) -> None:
        # Cap the step count too — recipes arrive as untrusted posted JSON.
        self.steps = tuple(s for s in self.steps if isinstance(s, EditOp) and s.valid)[
            :_MAX_STEPS
        ]

    # --- construction --------------------------------------------------- #

    @classmethod
    def build(
        cls, spec: Sequence[Union[Tuple[str, Dict[str, Any]], Tuple[str], str]]
    ) -> "EditRecipe":
        steps: List[EditOp] = []
        for item in spec:
            if isinstance(item, str):
                op, params = item, {}
            elif len(item) == 1:
                op, params = item[0], {}
            else:
                op, params = item[0], item[1]
            steps.append(EditOp(op, params))
        return cls(steps=tuple(steps))

    @classmethod
    def from_dict(cls, data: Any) -> "EditRecipe":
        """Rebuild a recipe from :meth:`to_dict`. Tolerant: bad shapes → empty."""
        if not isinstance(data, dict):
            return cls()
        try:
            steps = tuple(
                EditOp(s.get("op", ""), s.get("params", {}))
                for s in data.get("steps", [])
                if isinstance(s, dict)
            )
            return cls(steps=steps)
        except Exception:
            return cls()

    # --- mutation (returns a new recipe; recipes are values) ------------ #

    def with_op(self, op: str, params: Optional[Dict[str, Any]] = None) -> "EditRecipe":
        """Return a new recipe with ``op`` set (single-instance ops replace; the
        brush/eraser ops are also single-instance — the UI accumulates stamps
        into one op). Result is sorted into canonical pipeline order.
        """
        new = EditOp(op, params or {})
        if not new.valid:
            return self
        kept = [s for s in self.steps if s.op != new.op]
        kept.append(new)
        kept.sort(key=lambda s: s.rank)
        return EditRecipe(steps=tuple(kept))

    def without_op(self, op: str) -> "EditRecipe":
        return EditRecipe(steps=tuple(s for s in self.steps if s.op != op))

    def canonical(self) -> "EditRecipe":
        return EditRecipe(steps=tuple(sorted(self.steps, key=lambda s: s.rank)))

    # --- properties ----------------------------------------------------- #

    def is_noop(self) -> bool:
        return len(self.steps) == 0

    def op_names(self) -> List[str]:
        return [s.op for s in self.steps]

    def to_dict(self) -> Dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    def signature(self) -> str:
        """Stable 12-hex digest of the recipe's effect (a content-cache seed)."""
        payload = json.dumps([s.to_dict() for s in self.steps], sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def describe(self) -> List[str]:
        """Plain-English step list for the why-this-edit explainability sidecar."""
        return [_describe_step(s) for s in self.steps]

    # --- apply ---------------------------------------------------------- #

    def apply(self, img: Image.Image) -> Image.Image:
        if self.is_noop():
            return img
        out = img
        for step in self.steps:
            out = step.apply(out)
        return out

    def apply_bytes(self, data: bytes, *, fmt: Optional[str] = None) -> bytes:
        """Decode ``data``, apply the recipe, re-encode. No-op → byte-identical."""
        if self.is_noop():
            return data
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            src_format = (im.format or "").upper()
            out = self.apply(im)
        encoded, _mime = encode_image(out, fmt or src_format)
        return encoded

    def __hash__(self) -> int:
        return hash(self.signature())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EditRecipe):
            return NotImplemented
        return self.to_dict() == other.to_dict()


def _describe_step(step: EditOp) -> str:
    op, p = step.op, step.params
    if op in ("brightness", "contrast", "saturation"):
        return f"{op} ×{p['factor']:g}"
    if op in ("warmth", "tint", "highlights", "shadows"):
        return f"{op} {p['amount']:+g}"
    if op == "crop":
        return f"crop {p['w']:.0%}×{p['h']:.0%}"
    if op == "rotate":
        return f"rotate {p['degrees']:g}°"
    if op == "flip":
        return f"flip {p['axis']}"
    if op == "resize":
        return (
            f"resize {p['width']}×{p['height']}"
            if p.get("width")
            else f"resize ×{p.get('scale', 0):g}"
        )
    if op == "perspective":
        return f"perspective h{p['h']:+g} v{p['v']:+g}"
    if op == "shape_crop":
        return f"{p['shape']} crop"
    if op == "filter":
        return f"{p['name']} filter {p['intensity']:.0%}" if p.get("name") else "filter (none)"
    if op == "duotone":
        return f"duotone {p['shadow']}→{p['highlight']}"
    if op in ("blur_brush", "eraser"):
        return f"{op.replace('_', ' ')} ×{len(p.get('stamps', []))}"
    if "amount" in p:
        return f"{op} {p['amount']:g}"
    return op


# --------------------------------------------------------------------------- #
# Encoding
# --------------------------------------------------------------------------- #

_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def encode_image(img: Image.Image, src_format: str = "") -> Tuple[bytes, str]:
    """Encode an edited image to bytes + MIME. Alpha forces PNG."""
    buf = io.BytesIO()
    fmt = (src_format or "").upper()
    if not _has_alpha(img) and fmt in ("JPEG", "JPG", "MPO"):
        img.convert("RGB").save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    img.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def load_image(source: ImageLike) -> Image.Image:
    """Open ``source`` (path / bytes / PIL) into a loaded PIL image."""
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, (bytes, bytearray)):
        im = Image.open(io.BytesIO(bytes(source)))
    else:
        im = Image.open(source)
    im.load()
    return im


# --------------------------------------------------------------------------- #
# One-click Enhance — deterministic auto-fix tuned for indoor pool light
# --------------------------------------------------------------------------- #


def enhance_auto(source: ImageLike, *, strength: float = 1.0) -> EditRecipe:
    """Analyse ``source`` and return a deterministic auto-fix :class:`EditRecipe`.

    Pool halls are dim, low-contrast and cyan/green cast; phone JPEGs come out
    flat. This inspects the histogram + colour means and builds a restrained
    recipe — white-balance the cast out, stretch the contrast, lift crushed
    shadows, add a little clarity and warmth — scaled by ``strength`` (0..1).
    No model call: same pixels in → same recipe out.
    """
    s = _clamp(strength, *_BOUNDS["amount01"])
    img = load_image(source)
    arr, _ = _rgb_array(img)
    flat = arr.reshape(-1, 3)
    means = flat.mean(axis=0)
    y = _luma(arr)
    y_mean = float(y.mean())
    y_std = float(y.std())

    ops: List[Tuple[str, Dict[str, Any]]] = []

    # Colour cast: how far the channel means spread from neutral.
    cast = float(means.max() - means.min())
    if cast > 10.0:
        ops.append(("white_balance", {"amount": round(min(1.0, cast / 60.0) * s, 4)}))

    # Contrast: a flat histogram (low std) gets an auto-contrast stretch.
    if y_std < 60.0:
        ops.append(("auto_contrast", {"cutoff": 0.5}))

    # Brightness: a dim frame (low mean luma) gets a gentle lift.
    if y_mean < 110.0:
        lift = 1.0 + min(0.22, (110.0 - y_mean) / 110.0 * 0.4) * s
        ops.append(("brightness", {"factor": round(lift, 4)}))

    # Crushed shadows in a dim hall → a small shadow lift.
    dark_frac = float((y < 40).mean())
    if dark_frac > 0.12:
        ops.append(("shadows", {"amount": round(min(40.0, dark_frac * 120.0) * s, 2)}))

    # A touch of texture + warmth + saturation to undo phone flatness.
    if s > 0:
        ops.append(("clarity", {"amount": round(14.0 * s, 2)}))
        ops.append(("warmth", {"amount": round(6.0 * s, 2)}))
        ops.append(("saturation", {"factor": round(1.0 + 0.08 * s, 4)}))

    return EditRecipe.build(ops).canonical()


# --------------------------------------------------------------------------- #
# Photo-grid collage composer (reuses frames; distinct from the cutout collage)
# --------------------------------------------------------------------------- #

# layout slug → list of (x, y, w, h) cell rectangles in 0..1 fractions.
GRID_LAYOUTS: Dict[str, List[Tuple[float, float, float, float]]] = {
    "duo_v": [(0, 0, 0.5, 1), (0.5, 0, 0.5, 1)],
    "duo_h": [(0, 0, 1, 0.5), (0, 0.5, 1, 0.5)],
    "trio_strip": [(0, 0, 1 / 3, 1), (1 / 3, 0, 1 / 3, 1), (2 / 3, 0, 1 / 3, 1)],
    "trio_feature": [(0, 0, 0.62, 1), (0.62, 0, 0.38, 0.5), (0.62, 0.5, 0.38, 0.5)],
    "grid_2x2": [(0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)],
    "grid_3x3": [(c / 3, r / 3, 1 / 3, 1 / 3) for r in range(3) for c in range(3)],
}

GRID_NAMES: Tuple[str, ...] = tuple(GRID_LAYOUTS.keys())


def grid_capacity(layout: str) -> int:
    return len(GRID_LAYOUTS.get(layout, []))


def compose_grid(
    images: Sequence[ImageLike],
    *,
    layout: str = "grid_2x2",
    width: int = 1080,
    height: int = 1080,
    gap: int = 12,
    background: str = "#0b0d12",
    corner: int = 0,
) -> Image.Image:
    """Composite ``images`` into a balanced photo grid — the collage composer.

    Each cell is centre-cropped (``cover``) to fill its rectangle, so portraits
    and landscapes sit together cleanly. Deterministic: same inputs → identical
    pixels. Cells beyond the layout's capacity are ignored; empty cells stay the
    background colour. ``corner`` rounds each cell; ``gap`` insets them.
    """
    cells = GRID_LAYOUTS.get(layout) or GRID_LAYOUTS["grid_2x2"]
    W = max(1, min(_MAX_DIM, int(width)))
    H = max(1, min(_MAX_DIM, int(height)))
    g = max(0, int(gap))
    canvas = Image.new("RGB", (W, H), _hex_rgb(background))
    for cell, src in zip(cells, images):
        cx, cy, cw, ch = cell
        x0 = int(round(cx * W)) + g // 2
        y0 = int(round(cy * H)) + g // 2
        x1 = int(round((cx + cw) * W)) - (g - g // 2)
        y1 = int(round((cy + ch) * H)) - (g - g // 2)
        bw, bh = max(1, x1 - x0), max(1, y1 - y0)
        try:
            tile = load_image(src).convert("RGB")
        except Exception:
            continue
        tile = ImageOps.fit(tile, (bw, bh), method=Image.LANCZOS, centering=(0.5, 0.5))
        if corner > 0:
            mask = Image.new("L", (bw, bh), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, bw - 1, bh - 1), radius=int(corner), fill=255
            )
            canvas.paste(tile, (x0, y0), mask)
        else:
            canvas.paste(tile, (x0, y0))
    return canvas


# --------------------------------------------------------------------------- #
# Profile-picture export presets
# --------------------------------------------------------------------------- #

PROFILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "avatar_circle": {"shape": "circle", "size": 512, "title": "Circle avatar"},
    "avatar_square": {"shape": "rounded", "size": 512, "title": "Rounded square avatar"},
    "avatar_ring": {
        "shape": "circle",
        "size": 512,
        "ring": True,
        "title": "Avatar with brand ring",
    },
}


def profile_picture_recipe(preset: str = "avatar_circle") -> EditRecipe:
    """Build the crop+resize recipe for a named profile-picture ``preset``."""
    cfg = PROFILE_PRESETS.get(preset, PROFILE_PRESETS["avatar_circle"])
    size = int(cfg["size"])
    return EditRecipe.build(
        [
            ("resize", {"width": size, "height": size}),
            ("shape_crop", {"shape": cfg["shape"], "feather": 0.02}),
        ]
    ).canonical()


__all__ = [
    "EditOp",
    "EditRecipe",
    "enhance_auto",
    "compose_grid",
    "GRID_LAYOUTS",
    "GRID_NAMES",
    "grid_capacity",
    "SHAPES",
    "FILTERS",
    "FILTER_NAMES",
    "PROFILE_PRESETS",
    "profile_picture_recipe",
    "encode_image",
    "load_image",
    # primitives (exported for direct use / tests)
    "warmth",
    "tint",
    "highlights",
    "shadows",
    "white_balance",
    "clarity",
    "grayscale",
    "sepia",
    "duotone",
    "golden_hour",
    "colour_punch",
    "blur",
    "pixelate",
    "glitch",
    "vignette",
    "opacity",
    "crop",
    "flip",
    "rotate",
    "resize",
    "perspective",
    "shape_crop",
    "frame",
    "blur_brush",
    "eraser",
    "apply_filter",
]
