"""Deterministic saliency-aware cropping for the graphic renderer.

Given an image path and one or more target aspect ratios, this module
proposes crop rectangles that keep the *interesting* part of the photo
(the swimmer, the medal, the action) inside the frame for each format —
9:16 story, 1:1 feed, 4:5 portrait, etc.

It is deliberately **not** AI-driven: this is layout-intelligence maths
(consistent with the colour-science / ranker rule that the engine's
exact, reproducible decisions stay deterministic). The "what's
interesting" signal is one of:

* the **cutout alpha mask** when the image already carries transparency
  (a rembg/PhotoRoom cutout) — the subject is exactly where alpha > 0; or
* a **gradient-magnitude energy map** otherwise — edges and detail are
  where the content lives, uniform sky/wall is not.

The crop for a ratio is the *largest* rectangle of that aspect ratio that
fits inside the image, slid along its single free axis so its centre sits
on the energy centroid. That guarantees the crop always stays within
bounds and always tracks the subject.

Public API:
    crops_for(image_path, ratios) -> dict[ratio_spec, (x, y, w, h)]
    best_crop(image_path, ratio)  -> (x, y, w, h)
    focus_position(image_path, ratio) -> "x% y%" object-position
    focus_position_with_mask(image_path, mask_path, ratio) -> "x% y%"
        (an external cutout's alpha steers the ORIGINAL photo's crop)

Alpha-mask energy additionally gets a deterministic head bias for
portrait-ish target ratios (< 1): the whole-mass centroid of a person
cutout sits on the torso, so it is blended with the centroid of the top
~30% of the subject's bounding box — fixed weights, no randomness.
Non-alpha images are byte-identical to the pre-head-bias behaviour.

No LLM, no network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Union

import numpy as np
from PIL import Image

Crop = Tuple[int, int, int, int]
RatioSpec = Union[str, float, int, Tuple[int, int]]

# Energy is computed on a downscaled working copy — the chosen crop offset is
# resolution-independent (a fraction of the free axis), so the small map gives
# the same placement as the full image for a fraction of the cost.
_WORK_MAX = 256


def crops_for(image_path: Union[str, Path], ratios: Iterable[RatioSpec]) -> Dict[RatioSpec, Crop]:
    """Return one saliency-aware crop per target aspect ratio.

    ``ratios`` is an iterable of ratio specs, each either ``"W:H"`` /
    ``"W/H"`` / ``"WxH"`` (string), ``(W, H)`` (tuple), or a bare
    ``width / height`` float. The returned dict is keyed by the spec exactly
    as supplied, so callers can look a crop up by what they asked for.

    Each crop is ``(x, y, w, h)`` in original-image pixel coordinates,
    guaranteed to lie within the image bounds.
    """
    specs = _as_spec_list(ratios)
    # Validate every ratio up front so a bad spec fails before any file I/O.
    parsed = [(spec, _parse_ratio(spec)) for spec in specs]

    width, height, energy, is_alpha = _energy_map(image_path)
    out: Dict[RatioSpec, Crop] = {}
    for spec, ratio in parsed:
        cx, cy = _focus_centroids(energy, is_alpha, ratio)
        out[spec] = _place_crop(width, height, ratio, cx, cy)
    return out


def best_crop(image_path: Union[str, Path], ratio: RatioSpec) -> Crop:
    """Return the single best saliency-aware crop for ``ratio``.

    ``ratio`` accepts the same forms as the elements of ``crops_for``'s
    ``ratios``. The result is ``(x, y, w, h)`` in original-image pixels,
    guaranteed within bounds.
    """
    r = _parse_ratio(ratio)
    width, height, energy, is_alpha = _energy_map(image_path)
    cx, cy = _focus_centroids(energy, is_alpha, r)
    return _place_crop(width, height, r, cx, cy)


def focus_position(image_path: Union[str, Path], ratio: RatioSpec = "4:5") -> str:
    """CSS ``object-position`` keeping the saliency focus in frame.

    The :func:`best_crop` centroid for ``ratio``, converted to percentages —
    the one string both the still renderer (``--mh-photo-pos``) and the motion
    compositions (``photoPos``) feed to ``object-position`` so a full-bleed
    photo is steered the same way on every surface. Safe default on any
    failure so a render never breaks on a missing or odd image.
    """
    if not image_path:
        return "center 28%"
    try:
        x, y, w, h = best_crop(image_path, ratio)
        with Image.open(image_path) as im:
            iw, ih = im.size
        if iw <= 0 or ih <= 0:
            return "center 28%"
        cx = max(0.0, min(1.0, (x + w / 2.0) / iw)) * 100.0
        cy = max(0.0, min(1.0, (y + h / 2.0) / ih)) * 100.0
        return f"{cx:.0f}% {cy:.0f}%"
    except Exception:
        return "center 28%"


# --------------------------------------------------------------------------- #
# Format-aware focus (R1.7)
# --------------------------------------------------------------------------- #

# Canonical social-output cut → its aspect ratio. A caller that knows only the
# *cut name* (the motion renderer's story / portrait / square / landscape) gets
# the crop steered for that frame's real shape: a face kept in a 9:16 story can
# fall out of frame in a 16:9 landscape, because the two crops slide along
# different axes. Resolving the ratio per format fixes the focus to each cut.
# Pixel sizes live with the renderer (``visual.motion.MOTION_FORMATS``); this is
# the ratio-only view, kept in lockstep by ``tests/test_motion_format_focus.py``.
FORMAT_RATIOS: Dict[str, str] = {
    "story": "9:16",
    "portrait": "4:5",
    "square": "1:1",
    "landscape": "16:9",
}

_DEFAULT_FORMAT_RATIO = "9:16"


def ratio_for_format(format_name: str) -> str:
    """Aspect-ratio spec for a named output cut.

    Case-insensitive; unknown or empty names fall back to the 9:16 story
    ratio (the default cut), so a caller can pass a format straight through
    without first validating it.
    """
    if not format_name:
        return _DEFAULT_FORMAT_RATIO
    return FORMAT_RATIOS.get(str(format_name).strip().lower(), _DEFAULT_FORMAT_RATIO)


def focus_position_for_format(image_path: Union[str, Path], format_name: str = "story") -> str:
    """CSS ``object-position`` keeping the saliency focus in frame for a *cut*.

    A per-format wrapper over :func:`focus_position`: the 9:16 story, 4:5
    portrait, 1:1 square and 16:9 landscape crops of the same photo slide
    along different axes, so each cut needs its centroid resolved for its own
    aspect ratio. Unknown format names fall back to the 9:16 story ratio, and
    the same safe-default-on-failure contract as :func:`focus_position` holds.
    """
    return focus_position(image_path, ratio_for_format(format_name))


def focus_position_with_mask(
    image_path: Union[str, Path],
    mask_path: Union[str, Path],
    ratio: RatioSpec = "4:5",
) -> str:
    """CSS ``object-position`` for the ORIGINAL photo, steered by a cutout's alpha.

    Most originals carry no transparency, so :func:`focus_position` falls back
    to gradient energy — which tracks edges, not the subject. When a rembg /
    PhotoRoom cutout of the same photo exists, its alpha channel IS the
    subject mask: this helper reads the mask's alpha as the energy map (head
    bias included for portrait-ish ratios) and places the crop in the
    original photo's pixel grid, so face-accurate focus works for non-alpha
    originals too.

    Deterministic; on any failure (missing/opaque/unreadable mask) it falls
    back to ``focus_position(image_path, ratio)`` — exactly what the caller
    would have used without a mask.
    """
    if not image_path or not mask_path:
        return focus_position(image_path, ratio)
    try:
        r = _parse_ratio(ratio)
        with Image.open(image_path) as im:
            im.load()
            width, height = im.size
        if width <= 0 or height <= 0:
            return focus_position(image_path, ratio)
        with Image.open(mask_path) as mim:
            mim.load()
            alpha = _alpha_mask(mim)
            if alpha is None:
                return focus_position(image_path, ratio)
            # Resample the mask onto the ORIGINAL's working grid so the
            # centroid lands in the original's coordinate space even when the
            # cutout was produced at a different resolution.
            sw, sh = _work_size(width, height)
            energy = np.asarray(alpha.resize((sw, sh), Image.BILINEAR), dtype=np.float32)
        cx, cy = _focus_centroids(energy, True, r)
        x, y, w, h = _place_crop(width, height, r, cx, cy)
        px = max(0.0, min(1.0, (x + w / 2.0) / width)) * 100.0
        py = max(0.0, min(1.0, (y + h / 2.0) / height)) * 100.0
        return f"{px:.0f}% {py:.0f}%"
    except Exception:
        return focus_position(image_path, ratio)


# --------------------------------------------------------------------------- #
# Ratio parsing
# --------------------------------------------------------------------------- #


def _as_spec_list(ratios: Iterable[RatioSpec]) -> List[RatioSpec]:
    # A lone string is iterable over characters — wrap it so ``"9:16"`` is one
    # spec, not three.
    if isinstance(ratios, (str, bytes)):
        return [ratios]  # type: ignore[list-item]
    return list(ratios)


def _parse_ratio(spec: RatioSpec) -> float:
    """Normalise a ratio spec to a positive ``width / height`` float."""
    if isinstance(spec, bool):  # bool is an int subclass — reject it explicitly
        raise ValueError(f"invalid aspect ratio: {spec!r}")
    if isinstance(spec, (int, float)):
        value = float(spec)
    elif isinstance(spec, (tuple, list)):
        if len(spec) != 2:
            raise ValueError(f"ratio tuple must be (width, height): {spec!r}")
        w, h = float(spec[0]), float(spec[1])
        if h == 0:
            raise ValueError(f"ratio height must be non-zero: {spec!r}")
        value = w / h
    elif isinstance(spec, str):
        parts = [p for p in re.split(r"[:/x×X]", spec.strip()) if p != ""]
        try:
            if len(parts) == 2:
                w, h = float(parts[0]), float(parts[1])
                if h == 0:
                    raise ValueError
                value = w / h
            elif len(parts) == 1:
                value = float(parts[0])
            else:
                raise ValueError
        except ValueError:
            raise ValueError(f"could not parse aspect ratio: {spec!r}") from None
    else:
        raise ValueError(f"unsupported ratio spec type: {type(spec).__name__}")

    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"aspect ratio must be a positive number: {spec!r}")
    return value


# --------------------------------------------------------------------------- #
# Energy / saliency map
# --------------------------------------------------------------------------- #


def _energy_map(image_path: Union[str, Path]) -> Tuple[int, int, np.ndarray, bool]:
    """Load the image and return ``(width, height, energy, is_alpha)``.

    ``energy`` is a non-negative 2-D float array on a downscaled working
    grid: the cutout alpha mask if the image carries usable transparency
    (``is_alpha=True``), otherwise a gradient-magnitude edge map
    (``is_alpha=False``). Only the alpha path carries a subject silhouette,
    so only it is eligible for the head-bias blend.
    """
    with Image.open(image_path) as im:
        im.load()
        width, height = im.size
        sw, sh = _work_size(width, height)

        mask = _alpha_mask(im)
        if mask is not None:
            small = mask.resize((sw, sh), Image.BILINEAR)
            energy = np.asarray(small, dtype=np.float32)
            is_alpha = True
        else:
            small = im.convert("L").resize((sw, sh), Image.BILINEAR)
            energy = _gradient_energy(np.asarray(small, dtype=np.float32))
            is_alpha = False

    return width, height, energy, is_alpha


def _work_size(width: int, height: int) -> Tuple[int, int]:
    longest = max(width, height)
    if longest <= _WORK_MAX:
        return max(1, width), max(1, height)
    scale = _WORK_MAX / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _alpha_mask(im: Image.Image) -> Union[Image.Image, None]:
    """Return the alpha channel as an 'L' image iff it usefully marks a subject.

    A fully-opaque or fully-transparent alpha carries no positional signal,
    so those fall through to the gradient path.
    """
    has_alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    if not has_alpha:
        return None
    alpha = im.convert("RGBA").getchannel("A")
    arr = np.asarray(alpha)
    if arr.size and int(arr.min()) < 255 and int(arr.max()) > 0:
        return alpha
    return None


def _gradient_energy(lum: np.ndarray) -> np.ndarray:
    """Gradient-magnitude edge map of a luminance array (same shape, >= 0)."""
    gx = np.zeros_like(lum)
    gy = np.zeros_like(lum)
    if lum.shape[1] > 1:
        gx[:, 1:] = np.abs(np.diff(lum, axis=1))
    if lum.shape[0] > 1:
        gy[1:, :] = np.abs(np.diff(lum, axis=0))
    return np.hypot(gx, gy)


# --------------------------------------------------------------------------- #
# Head bias (PHOTOS-8) — alpha-mask energy only, portrait-ish targets only
# --------------------------------------------------------------------------- #

# A person cutout's whole-mass centroid sits on the torso; for portrait-ish
# crops (ratio < 1) the head is what must stay in frame. The head lives in the
# top band of the subject's bounding box, so we blend the centroid of that
# band with the full centroid using fixed weights. Alpha values below the
# threshold (0..255 grid) are matting noise, not subject.
_HEAD_BAND_FRACTION = 0.30
_HEAD_BLEND = 0.6  # weight on the head-band centroid; 1-this on the full one
_ALPHA_SUBJECT_THRESHOLD = 25.0


def _focus_centroids(energy: np.ndarray, is_alpha: bool, ratio: float) -> Tuple[float, float]:
    """The centroid the crop should centre on, head-biased where it applies.

    Gradient-energy images (no mask) keep the plain centroid — byte-identical
    behaviour for every non-alpha photo. Alpha-mask energy gets the head-bias
    blend for portrait-ish target ratios (ratio < 1); wider targets keep the
    whole-mass centroid, which frames torso-level action correctly.
    """
    cx, cy = _centroids(energy)
    if not is_alpha or ratio >= 1.0:
        return cx, cy
    head = _head_centroid(energy)
    if head is None:
        return cx, cy
    hx, hy = head
    return (
        _HEAD_BLEND * hx + (1.0 - _HEAD_BLEND) * cx,
        _HEAD_BLEND * hy + (1.0 - _HEAD_BLEND) * cy,
    )


def _head_centroid(energy: np.ndarray) -> Union[Tuple[float, float], None]:
    """Centroid of the top ``_HEAD_BAND_FRACTION`` of the subject's bbox.

    Returns fractions in ``[0, 1]`` like :func:`_centroids`, or None when the
    mask carries no subject above the threshold (fall back to the full
    centroid — never guess).
    """
    subject = energy > _ALPHA_SUBJECT_THRESHOLD
    rows = np.flatnonzero(subject.any(axis=1))
    if rows.size == 0:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    band_h = max(1, int(round((bottom - top + 1) * _HEAD_BAND_FRACTION)))
    band = np.zeros_like(energy)
    band[top : top + band_h, :] = energy[top : top + band_h, :]
    # Only subject pixels contribute — matting haze outside the silhouette
    # must not drag the head point sideways.
    band[~subject] = 0.0
    if float(band.sum()) <= 1e-9:
        return None
    return _centroids(band)


def _centroids(energy: np.ndarray) -> Tuple[float, float]:
    """Energy centre of mass as ``(x_fraction, y_fraction)`` in ``[0, 1]``.

    A flat map (no edges / no subject) has no signal, so we fall back to the
    image centre — the least-bad default for a featureless photo.
    """
    sh, sw = energy.shape
    total = float(energy.sum())
    if total <= 1e-9:
        return 0.5, 0.5
    col = energy.sum(axis=0)
    row = energy.sum(axis=1)
    xs = (np.arange(sw, dtype=np.float64) + 0.5) / sw
    ys = (np.arange(sh, dtype=np.float64) + 0.5) / sh
    cx = float((col * xs).sum() / total)
    cy = float((row * ys).sum() / total)
    return cx, cy


# --------------------------------------------------------------------------- #
# Crop geometry
# --------------------------------------------------------------------------- #


def _place_crop(width: int, height: int, ratio: float, cx: float, cy: float) -> Crop:
    """Largest crop of ``ratio`` fitting in the image, centred on the centroid.

    One axis is pinned to the full image extent (so the crop is maximal); the
    crop slides along the other axis to put its centre on the energy centroid,
    clamped to stay within bounds.
    """
    img_ratio = width / height
    if ratio >= img_ratio:
        # Wider-or-equal target than the image: full width, slide vertically.
        crop_w = width
        crop_h = min(height, max(1, round(width / ratio)))
        x = 0
        y = _slide(cy * height - crop_h / 2.0, height - crop_h)
    else:
        # Taller target than the image: full height, slide horizontally.
        crop_h = height
        crop_w = min(width, max(1, round(height * ratio)))
        y = 0
        x = _slide(cx * width - crop_w / 2.0, width - crop_w)
    return int(x), int(y), int(crop_w), int(crop_h)


def _slide(value: float, hi: int) -> int:
    """Round ``value`` and clamp it to ``[0, hi]`` (``hi`` may be 0)."""
    pos = int(round(value))
    if pos < 0:
        return 0
    if pos > hi:
        return hi
    return pos


__all__ = [
    "crops_for",
    "best_crop",
    "focus_position",
    "focus_position_for_format",
    "focus_position_with_mask",
    "ratio_for_format",
    "FORMAT_RATIOS",
    "Crop",
    "RatioSpec",
]
