"""Deterministic photo-derived palette extraction for the graphic renderer.

Given a photo (the athlete cutout / action shot a card carries) this module
extracts a small, representative colour palette via **k-means** clustering of
the image's pixels — the dominant colours and how much of the frame each one
occupies. The renderer's G1.7 ground-tint hook uses it to nudge a card's
*derived* ground toward the photo's own colour story, so a card feels colour-
connected to the swimmer in it rather than floating on a generic brand slab.

Like :mod:`graphic_renderer.saliency`, this is deliberately **not** AI-driven:
it is colour-science maths, and the engine's exact, reproducible decisions stay
deterministic (the same image bytes always yield the same palette). That matters
because the palette feeds a *rendered* surface — a non-deterministic palette
would make the same card render two different ways. Determinism is guaranteed by

  * a fixed downscale to a small working grid (placement-independent, fast),
  * a fixed pixel-iteration order, and
  * a fixed-seed k-means++ initialisation with a fixed iteration cap —

so there is no hidden randomness anywhere in the path.

Public API:
    extract_palette(source, *, k=5, ...) -> PhotoPalette
    tint_toward(base_hex, target_hex, amount) -> str   # bounded sRGB mix

No LLM, no network. Pure functions; safe (empty) result on any failure so a
render can never break on an odd or unreadable image.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
from PIL import Image

# A photo's colour story is resolution-independent: the proportions of each hue
# are the same on a 96px working grid as on the full frame, for a fraction of
# the cost. 96 keeps k-means comfortably fast (≤ ~9k pixels) and deterministic.
_WORK_MAX = 96

# Pixels dimmer than this in the alpha channel are treated as "not the subject"
# (the transparent void around a rembg cutout). Dropping them makes the palette
# reflect the swimmer, not the empty background a cutout leaves behind.
_ALPHA_FLOOR = 128

# Below this many usable pixels there is no honest palette to extract.
_MIN_PIXELS = 16

PaletteSource = Union[str, Path, bytes, bytearray, "Image.Image"]


# --------------------------------------------------------------------------- #
# Hex / colour helpers (self-contained so this module imports nothing from the
# big render.py — it is imported *by* the render path, not the other way round)
# --------------------------------------------------------------------------- #


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = (value or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) < 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(float(v))))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Swatch:
    """One extracted colour cluster.

    ``weight`` is the fraction of usable pixels (0..1) assigned to this cluster —
    i.e. how much of the frame the colour occupies.
    """

    hex: str
    weight: float
    rgb: tuple[int, int, int]

    @property
    def chroma(self) -> int:
        """Crude saturation proxy: ``max(r,g,b) - min(r,g,b)`` on 0..255.

        The same near-neutral test the logo-dominant picker uses, so "is this a
        real colour or just a grey?" is judged one consistent way across the
        renderer.
        """
        r, g, b = self.rgb
        return max(r, g, b) - min(r, g, b)

    @property
    def luminance(self) -> float:
        """Perceptual luminance in 0..1 (Rec.709 weights)."""
        r, g, b = self.rgb
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


@dataclass(frozen=True)
class PhotoPalette:
    """An ordered set of :class:`Swatch` (most-prominent first)."""

    swatches: tuple[Swatch, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.swatches

    @property
    def dominant(self) -> Optional[Swatch]:
        """The colour that occupies the most of the frame, or ``None``."""
        return self.swatches[0] if self.swatches else None

    @property
    def average_hex(self) -> Optional[str]:
        """Weighted mean of every swatch — the photo's overall cast."""
        if not self.swatches:
            return None
        total = sum(s.weight for s in self.swatches) or 1.0
        r = sum(s.rgb[0] * s.weight for s in self.swatches) / total
        g = sum(s.rgb[1] * s.weight for s in self.swatches) / total
        b = sum(s.rgb[2] * s.weight for s in self.swatches) / total
        return _rgb_to_hex((r, g, b))

    def vibrant(self, *, min_chroma: int = 28) -> Optional[Swatch]:
        """The most colourful *prominent* swatch, or ``None`` if the photo is
        essentially neutral.

        Scored as ``chroma × sqrt(weight)`` so a vivid splash that fills a
        meaningful share of the frame beats both a muddy dominant and a saturated
        speck. ``min_chroma`` gates out greys masquerading as colour.
        """
        candidates = [s for s in self.swatches if s.chroma >= min_chroma]
        if not candidates:
            return None
        return max(candidates, key=lambda s: (s.chroma * (s.weight**0.5), s.hex))

    def tint_target(self, *, min_chroma: int = 28) -> Optional[str]:
        """The hex a ground should be tinted *toward* — the vibrant swatch when
        the photo has real colour, else the dominant one, else ``None``."""
        vib = self.vibrant(min_chroma=min_chroma)
        if vib is not None:
            return vib.hex
        return self.dominant.hex if self.dominant else None

    def to_list(self) -> list[dict]:
        """Plain-data form (for explainability sidecars / tests)."""
        return [
            {"hex": s.hex, "weight": round(s.weight, 4), "chroma": s.chroma} for s in self.swatches
        ]


# --------------------------------------------------------------------------- #
# Image loading
# --------------------------------------------------------------------------- #


def _load_rgba(source: PaletteSource) -> Optional[Image.Image]:
    """Open any supported source as an RGBA :class:`PIL.Image.Image`, or None."""
    try:
        if isinstance(source, Image.Image):
            return source.convert("RGBA")
        if isinstance(source, (bytes, bytearray)):
            with Image.open(io.BytesIO(bytes(source))) as im:
                im.load()
                return im.convert("RGBA")
        with Image.open(source) as im:  # str | Path
            im.load()
            return im.convert("RGBA")
    except Exception:
        return None


def _usable_pixels(im: Image.Image) -> np.ndarray:
    """Downscaled RGB pixels worth clustering — the opaque subject when the
    image is a cutout, else the whole frame. Shape ``(n, 3)`` float64."""
    longest = max(im.size)
    if longest > _WORK_MAX:
        scale = _WORK_MAX / longest
        small = im.resize(
            (max(1, round(im.size[0] * scale)), max(1, round(im.size[1] * scale))),
            Image.BILINEAR,
        )
    else:
        small = im

    arr = np.asarray(small, dtype=np.float64)  # (h, w, 4)
    flat = arr.reshape(-1, 4)
    alpha = flat[:, 3]
    opaque = flat[alpha >= _ALPHA_FLOOR][:, :3]
    if opaque.shape[0] >= _MIN_PIXELS:
        return opaque
    # No usable alpha subject (a flat JPEG, or an all-but-transparent cutout):
    # fall back to every pixel that carries any opacity at all.
    any_visible = flat[alpha > 0][:, :3]
    return any_visible if any_visible.shape[0] >= _MIN_PIXELS else opaque


# --------------------------------------------------------------------------- #
# Deterministic k-means (Lloyd's algorithm, fixed-seed k-means++ init)
# --------------------------------------------------------------------------- #


def _kmeanspp_init(pixels: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++ seeding — spread initial centroids by squared distance.

    Deterministic given a fixed ``rng`` and a fixed pixel order, so the whole
    clustering is reproducible.
    """
    n = pixels.shape[0]
    first = int(rng.integers(0, n))
    centers = [pixels[first]]
    closest = np.full(n, np.inf)
    for _ in range(1, k):
        diff = pixels - centers[-1]
        d2 = np.einsum("ij,ij->i", diff, diff)
        closest = np.minimum(closest, d2)
        total = float(closest.sum())
        if total <= 0.0:
            # Every remaining point coincides with a chosen centroid; the data
            # has < k distinct colours. Pick the farthest (deterministic) — it
            # will collapse to an empty cluster and be dropped later.
            idx = int(np.argmax(closest))
        else:
            idx = int(rng.choice(n, p=closest / total))
        centers.append(pixels[idx])
    return np.asarray(centers, dtype=np.float64)


def _kmeans(pixels: np.ndarray, k: int, *, iters: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Cluster ``pixels`` into ``k`` colours. Returns ``(centroids, weights)``
    with empty clusters dropped; weights are population fractions summing to 1."""
    n = pixels.shape[0]
    k = max(1, min(k, n))
    rng = np.random.default_rng(0)  # fixed seed → reproducible clustering
    centers = _kmeanspp_init(pixels, k, rng)

    labels = np.zeros(n, dtype=np.int64)
    for _ in range(iters):
        # (n, k) squared distances → nearest centroid per pixel.
        dists = ((pixels[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = dists.argmin(axis=1)
        new_centers = centers.copy()
        for j in range(centers.shape[0]):
            mask = new_labels == j
            if mask.any():
                new_centers[j] = pixels[mask].mean(axis=0)
        moved = not np.allclose(new_centers, centers)
        centers, labels = new_centers, new_labels
        if not moved:
            break

    counts = np.bincount(labels, minlength=centers.shape[0]).astype(np.float64)
    keep = counts > 0
    centers, counts = centers[keep], counts[keep]
    weights = counts / counts.sum()
    return centers, weights


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def extract_palette(
    source: PaletteSource,
    *,
    k: int = 5,
) -> PhotoPalette:
    """Extract up to ``k`` representative colours from a photo.

    ``source`` is a file path, raw image ``bytes``, or a PIL ``Image``. The
    returned :class:`PhotoPalette` lists swatches most-prominent-first, each with
    the share of the frame it occupies. Identical-hex clusters are merged. Any
    failure (unreadable image, too few pixels) yields an **empty** palette rather
    than raising — the ground-tint hook then simply leaves the card untouched.
    """
    im = _load_rgba(source)
    if im is None:
        return PhotoPalette(())
    try:
        pixels = _usable_pixels(im)
        if pixels.shape[0] < _MIN_PIXELS:
            return PhotoPalette(())
        centers, weights = _kmeans(pixels, k)
    except Exception:
        return PhotoPalette(())

    # Merge clusters that round to the same hex (a near-flat photo can land two
    # centroids on the same colour); sum their weights so prominence stays honest.
    merged: dict[str, list] = {}
    for center, weight in zip(centers, weights):
        hex_value = _rgb_to_hex(center)
        if hex_value in merged:
            entry = merged[hex_value]
            entry[0] += float(weight)
        else:
            merged[hex_value] = [float(weight), _hex_to_rgb(hex_value)]

    swatches = [Swatch(hex=hx, weight=w, rgb=tuple(rgb)) for hx, (w, rgb) in merged.items()]
    # Most-prominent first; hex tiebreak keeps the order fully deterministic.
    swatches.sort(key=lambda s: (-s.weight, s.hex))
    return PhotoPalette(tuple(swatches))


# --------------------------------------------------------------------------- #
# C4 (Canva gap analysis) — Android-Palette semantic swatch classification
# --------------------------------------------------------------------------- #
# The six Material/Vibrant.js target roles. Each entry is
# ((sat_target, sat_min, sat_max), (light_target, light_min, light_max)) in the
# HSL space AOSP uses. Weights and target constants are the public AOSP
# ``androidx.palette.graphics.Target`` values — reproduced verbatim so the same
# photo always yields the same role assignment (deterministic, no tuning).
_TARGET_WEIGHT_SAT = 0.24
_TARGET_WEIGHT_LUMA = 0.52
_TARGET_WEIGHT_POP = 0.24

# Iteration order matters: a swatch that wins a role is not reused for a later
# one, exactly like AOSP's ``mUsedColors`` exclusion. This is AOSP's default
# target insertion order.
_PALETTE_TARGETS: tuple[tuple[str, tuple[float, float, float], tuple[float, float, float]], ...] = (
    ("light_vibrant", (1.0, 0.35, 1.0), (0.74, 0.55, 1.0)),
    ("vibrant", (1.0, 0.35, 1.0), (0.50, 0.30, 0.70)),
    ("dark_vibrant", (1.0, 0.35, 1.0), (0.26, 0.00, 0.45)),
    ("light_muted", (0.30, 0.00, 0.40), (0.74, 0.55, 1.0)),
    ("muted", (0.30, 0.00, 0.40), (0.50, 0.30, 0.70)),
    ("dark_muted", (0.30, 0.00, 0.40), (0.26, 0.00, 0.45)),
)

SEMANTIC_ROLES: tuple[str, ...] = tuple(name for name, _s, _l in _PALETTE_TARGETS)


def _hsl(rgb: tuple[int, int, int]) -> tuple[float, float]:
    """(saturation, lightness) in 0..1 — the HSL axes AOSP scores against."""
    import colorsys

    r, g, b = rgb
    _h, light, sat = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return sat, light


def classify_swatches(palette: PhotoPalette) -> dict[str, Optional[Swatch]]:
    """Assign the extracted swatches to Android-Palette semantic roles (C4).

    Returns ``{role: Swatch | None}`` for every role in :data:`SEMANTIC_ROLES`
    (``vibrant`` / ``muted`` / ``dark_vibrant`` / ``dark_muted`` /
    ``light_vibrant`` / ``light_muted``). Scoring is the verbatim AOSP
    ``Target`` formula — a weighted blend of saturation-distance, lightness-
    distance and population, with each swatch eligible only inside its target's
    HSL window and never reused across roles. Deterministic: the same palette
    always yields the same assignment; an empty palette yields all-``None``.
    """
    result: dict[str, Optional[Swatch]] = {name: None for name in SEMANTIC_ROLES}
    swatches = list(palette.swatches)
    if not swatches:
        return result
    max_pop = max((s.weight for s in swatches), default=0.0) or 1.0
    hsl = {id(s): _hsl(s.rgb) for s in swatches}
    used: set[int] = set()

    for role, (sat_t, sat_lo, sat_hi), (lum_t, lum_lo, lum_hi) in _PALETTE_TARGETS:
        best: Optional[Swatch] = None
        best_score = -1.0
        for s in swatches:
            if id(s) in used:
                continue
            sat, lum = hsl[id(s)]
            if not (sat_lo <= sat <= sat_hi and lum_lo <= lum <= lum_hi):
                continue
            score = (
                _TARGET_WEIGHT_SAT * (1.0 - abs(sat - sat_t))
                + _TARGET_WEIGHT_LUMA * (1.0 - abs(lum - lum_t))
                + _TARGET_WEIGHT_POP * (s.weight / max_pop)
            )
            # Hex tiebreak keeps the pick fully deterministic across equal scores.
            if score > best_score or (
                score == best_score and best is not None and s.hex < best.hex
            ):
                best, best_score = s, score
        if best is not None:
            result[role] = best
            used.add(id(best))
    return result


def tint_toward(base_hex: str, target_hex: str, amount: float) -> str:
    """Mix ``base_hex`` toward ``target_hex`` by ``amount`` (0..1) in sRGB.

    ``amount=0`` returns ``base`` unchanged; ``1`` returns ``target``. Used to
    nudge a ground a *small* way toward a photo colour — never to replace it.
    Pure and deterministic; returns an uppercase ``#RRGGBB`` hex.
    """
    a = _clamp01(float(amount))
    br, bg, bb = _hex_to_rgb(base_hex)
    tr, tg, tb = _hex_to_rgb(target_hex)
    return _rgb_to_hex((br + (tr - br) * a, bg + (tg - bg) * a, bb + (tb - bb) * a))


__all__ = [
    "Swatch",
    "PhotoPalette",
    "extract_palette",
    "tint_toward",
    "classify_swatches",
    "SEMANTIC_ROLES",
]
