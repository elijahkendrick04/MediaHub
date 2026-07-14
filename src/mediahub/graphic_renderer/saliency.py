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
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple, Union

import numpy as np
from PIL import Image

Crop = Tuple[int, int, int, int]
RatioSpec = Union[str, float, int, Tuple[int, int]]


class SmartCrop(NamedTuple):
    """A smartcrop-style crop: the window ``(x, y, w, h)`` plus the CSS ``zoom``.

    ``zoom`` (≥ 1.0) is how much the still/motion photo layer must scale the
    ``object-fit: cover`` image to present this crop — 1.0 is the largest crop
    (today's answer, no punch-in). ``x, y, w, h`` are original-image pixels.
    """

    x: int
    y: int
    w: int
    h: int
    zoom: float


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


# --------------------------------------------------------------------------- #
# Smart crop (E2, Canva gap analysis / photo-imagery) — multi-scale candidate
# scoring, rule-of-thirds placement, headroom, subject punch-in.
#
# smartcrop.js (MIT) slides candidate crops from maxScale 1.0 down to minScale
# in 0.1 steps over edge/skin/saturation feature maps with a rule-of-thirds
# importance bump and an edge penalty; a distant subject earns a punch-in, a
# subject that fills the frame keeps full context. This is a deterministic
# integer-maths port that runs on the same working grid as ``best_crop``, so
# it stays on the engine's deterministic side (no LLM, no randomness). It is
# additive: ``best_crop`` / ``focus_position`` are unchanged, and when the
# scorer's winner equals today's largest-crop answer the emitted vars are
# byte-identical, so a card only changes when the scorer genuinely reframes it.
# --------------------------------------------------------------------------- #

# Candidate zoom levels, largest (most context) first so ties prefer less
# punch-in — a tighter crop must strictly out-score full context to win.
_SMART_SCALES: Tuple[float, ...] = (1.0, 0.9, 0.8, 0.7, 0.6)
# CSS-zoom ceiling: never punch past this (matches the tight_portrait cap, so a
# crop never degrades resolution more than ~1.3x).
_SMART_MAX_ZOOM = 1.30
# The scorer runs on a coarse grid — subject placement is a low-frequency
# decision, so a small grid gives the same argmax far cheaper.
_SCORE_MAX = 96
# Importance-function weights (smartcrop.js lineage).
_EDGE_WEIGHT = 3.0  # penalty for saliency pushed into the crop edges
_THIRDS_WEIGHT = 1.1  # reward for saliency on the rule-of-thirds power lines
_ZOOM_COST = 0.08  # a punch-in must beat full context by this margin per unit
_HEADROOM_BAND = 0.06  # keep ~6% of frame height above the subject's head
# Subject-size punch-in floor (Canva gap: "punch in when the subject bbox
# occupies < ~20% of frame"). A subject smaller than the trigger is enlarged
# toward the target fill, snapped to the 0.1 scale grid and bounded by the zoom
# cap. A subject that already fills the frame is never punched in.
_PUNCH_TRIGGER = 0.50  # subject max-extent below this is a candidate for punch-in
_PUNCH_TARGET = 0.66  # enlarge the subject toward this fraction of the crop


def _score_saliency(
    image_path: Union[str, Path], mask_path: Union[str, Path, None] = None
) -> Tuple[int, int, np.ndarray, bool]:
    """The scorer's saliency grid: alpha subject when present, else edge+skin+sat.

    Returns ``(width, height, sal, is_alpha)`` where ``sal`` is a non-negative
    float grid on the ≤``_SCORE_MAX`` working size. The alpha path IS the
    subject silhouette; the gradient path blends edge energy with a skin-tone
    and a saturation map so the athlete (not the lane ropes) reads as salient.
    """
    with Image.open(image_path) as im:
        im.load()
        width, height = im.size
        # An external cutout's alpha steers the original's crop (parity with
        # focus_position_with_mask); otherwise read the image's own alpha.
        mask_im = None
        if mask_path and str(mask_path) != str(image_path):
            try:
                with Image.open(mask_path) as mim:
                    mim.load()
                    mask_im = _alpha_mask(mim)
            except Exception:
                mask_im = None
        alpha = mask_im if mask_im is not None else _alpha_mask(im)
        sw, sh = _score_work_size(width, height)
        if alpha is not None:
            sal = np.asarray(alpha.resize((sw, sh), Image.BILINEAR), dtype=np.float32)
            return width, height, sal, True
        rgb = im.convert("RGB").resize((sw, sh), Image.BILINEAR)
    arr = np.asarray(rgb, dtype=np.float32)
    lum = arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    edges = _gradient_energy(lum)
    edges = edges / (float(edges.max()) or 1.0)
    skin = _skin_map(arr)
    sat = _saturation_map(arr)
    sal = edges + 0.6 * skin + 0.3 * sat
    return width, height, sal, False


def _score_work_size(width: int, height: int) -> Tuple[int, int]:
    longest = max(width, height)
    if longest <= _SCORE_MAX:
        return max(1, width), max(1, height)
    scale = _SCORE_MAX / longest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _skin_map(rgb: np.ndarray) -> np.ndarray:
    """A 0–1 skin-likeness map (deterministic RGB heuristic).

    Not face detection — a cheap prior that a warm, moderately-bright,
    R>G>B pixel is more likely the athlete than blue water or a dark wall, so
    the crop biases toward people. Pure elementwise maths.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    like = (
        (r > 95) & (g > 40) & (b > 20) & ((mx - mn) > 15) & (np.abs(r - g) > 15) & (r > g) & (r > b)
    )
    return like.astype(np.float32)


def _saturation_map(rgb: np.ndarray) -> np.ndarray:
    """A 0–1 saturation map — vivid pixels (kit, medals) carry more interest."""
    mx = np.maximum(np.maximum(rgb[..., 0], rgb[..., 1]), rgb[..., 2])
    mn = np.minimum(np.minimum(rgb[..., 0], rgb[..., 1]), rgb[..., 2])
    return np.where(mx > 0, (mx - mn) / mx, 0.0).astype(np.float32)


def _importance_kernel(cw: int, ch: int, thirds: bool) -> np.ndarray:
    """The per-pixel importance weighting for a ``cw×ch`` crop (smartcrop.js).

    Positive toward the centre (``1.41 − radial``), penalised toward the edges,
    and — unless ``thirds`` is off (a symmetric composition) — bumped on the
    rule-of-thirds power lines so saliency there is rewarded.
    """
    xs = (np.arange(cw, dtype=np.float32) + 0.5) / cw
    ys = (np.arange(ch, dtype=np.float32) + 0.5) / ch
    px = np.abs(0.5 - xs) * 2.0  # 0 at centre → 1 at the crop edge
    py = np.abs(0.5 - ys) * 2.0
    PX, PY = np.meshgrid(px, py)
    centre = 1.41 - np.sqrt(PX * PX + PY * PY)
    edge = -(np.maximum(PX - 0.8, 0.0) ** 2 + np.maximum(PY - 0.8, 0.0) ** 2) * _EDGE_WEIGHT
    imp = centre + edge
    if thirds:
        imp = imp + (_thirds_bump(PX) + _thirds_bump(PY)) * _THIRDS_WEIGHT
    return imp.astype(np.float32)


def _thirds_bump(p: np.ndarray) -> np.ndarray:
    """A triangular bump peaking on the thirds power line (centre-distance 1/3)."""
    return np.maximum(0.0, 1.0 - np.abs(p - (1.0 / 3.0)) / 0.18)


def _crop_dims(sw: int, sh: int, ratio: float, scale: float) -> Tuple[int, int]:
    """Grid crop dims of ``ratio`` at ``scale`` of the largest fitting crop."""
    if ratio >= sw / sh:
        base_w = sw
        base_h = min(sh, max(1, round(sw / ratio)))
    else:
        base_h = sh
        base_w = min(sw, max(1, round(sh * ratio)))
    cw = max(1, min(sw, round(base_w * scale)))
    ch = max(1, min(sh, round(base_h * scale)))
    return cw, ch


def _positions(free: int, count: int = 12) -> List[int]:
    """Up to ``count+1`` evenly-spaced slide positions across ``[0, free]``."""
    if free <= 0:
        return [0]
    step = max(1, free // count)
    xs = list(range(0, free + 1, step))
    if xs[-1] != free:
        xs.append(free)
    return xs


def _best_position_at_scale(
    sal: np.ndarray, ratio: float, scale: float, thirds: bool
) -> Tuple[float, float, float]:
    """Argmax ``(score, cx, cy)`` for one scale — the best placement of a crop
    of this size over the saliency grid (centre fractions in [0, 1])."""
    sh, sw = sal.shape
    cw, ch = _crop_dims(sw, sh, ratio, scale)
    kernel = _importance_kernel(cw, ch, thirds)
    best_score = -np.inf
    best_cx, best_cy = 0.5, 0.5
    for y0 in _positions(sh - ch):
        for x0 in _positions(sw - cw):
            window = sal[y0 : y0 + ch, x0 : x0 + cw]
            score = float((window * kernel).sum())
            if score > best_score:
                best_score = score
                best_cx = (x0 + cw / 2.0) / sw
                best_cy = (y0 + ch / 2.0) / sh
    return best_score, best_cx, best_cy


def _smart_search(sal: np.ndarray, ratio: float, symmetric: bool) -> Tuple[float, float, float]:
    """Argmax ``(scale, cx, cy)`` over the candidate crops (fractions in [0,1]).

    Scores every crop at scales 1.0→0.6 with the rule-of-thirds importance
    kernel; ties prefer the largest scale (least punch-in), so a tighter crop
    must strictly out-score full context. Deterministic.
    """
    thirds = not symmetric
    best_score = -np.inf
    best = (1.0, 0.5, 0.5)
    for scale in _SMART_SCALES:
        bias = 1.0 - _ZOOM_COST * (1.0 - scale)
        score, cx, cy = _best_position_at_scale(sal, ratio, scale, thirds)
        score *= bias
        if score > best_score:
            best_score = score
            best = (scale, cx, cy)
    return best


def _snap_scale(scale: float) -> float:
    """Snap a continuous scale to the nearest candidate in the 0.1 grid, bounded
    below by the zoom cap (so a crop never zooms past ``_SMART_MAX_ZOOM``)."""
    floor = 1.0 / _SMART_MAX_ZOOM
    candidates = [s for s in _SMART_SCALES if s >= floor - 1e-6]
    return min(candidates, key=lambda s: abs(s - scale))


def _punch_floor_scale(band: Optional[Tuple[float, float, float, float]]) -> float:
    """The deepest crop scale a small subject earns (1.0 = no punch-in).

    Implements the Canva-gap rule: a subject whose larger extent is below
    ``_PUNCH_TRIGGER`` of the frame is enlarged toward ``_PUNCH_TARGET`` fill,
    snapped to the scale grid and bounded by the zoom cap. A subject that
    already fills the frame returns 1.0 (no punch-in).
    """
    if band is None:
        return 1.0
    extent = max(band[2], band[3])
    if extent <= 0 or extent >= _PUNCH_TRIGGER:
        return 1.0
    return _snap_scale(max(1.0 / _SMART_MAX_ZOOM, min(1.0, extent / _PUNCH_TARGET)))


def _subject_band(sal: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    """Subject bbox ``(left, top, w, h)`` fractions from the saliency grid."""
    sh, sw = sal.shape
    thresh = float(sal.max()) * 0.35
    if thresh <= 0:
        return None
    mask = sal > thresh
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    return (
        cols[0] / sw,
        rows[0] / sh,
        (cols[-1] - cols[0] + 1) / sw,
        (rows[-1] - rows[0] + 1) / sh,
    )


def smart_crop(
    image_path: Union[str, Path],
    ratio: RatioSpec = "4:5",
    *,
    symmetric: bool = False,
    mask_path: Union[str, Path, None] = None,
) -> SmartCrop:
    """Multi-scale, thirds-aware, headroom-constrained crop for ``ratio``.

    The scorer decides zoom + placement; a symmetric composition keeps the
    subject centred (thirds bump off) and pins placement to today's centroid
    crop so a scale-1.0 symmetric card stays byte-identical. On any failure the
    result degrades to :func:`best_crop` at zoom 1.0.
    """
    try:
        r = _parse_ratio(ratio)
        width, height, sal, is_alpha = _score_saliency(image_path, mask_path)
        # Today's answer (centroid / head-biased largest crop) — the byte-identity
        # anchor and the symmetric placement.
        bx, by, bw, bh = _base_crop_for_ratio(image_path, r, mask_path)
        base_cx = (bx + bw / 2.0) / width
        base_cy = (by + bh / 2.0) / height

        scale, cx, cy = _smart_search(sal, r, symmetric)
        # Subject-size punch-in floor (dossier rule): a small/distant subject
        # earns a bounded zoom even when full context scores well. Take the
        # deeper of the scorer's scale and the size floor, then re-place at it.
        band = _subject_band(sal)
        floor = _punch_floor_scale(band)
        if floor < scale:
            scale = floor
            _, cx, cy = _best_position_at_scale(sal, r, scale, not symmetric)
        if symmetric:
            cx, cy = base_cx, base_cy  # centred composition: keep today's focus
        cx, cy = _apply_headroom(sal, r, scale, cx, cy, is_alpha)

        crop = _place_crop_scaled(width, height, r, scale, cx, cy)
        zoom = round(min(_SMART_MAX_ZOOM, max(1.0, 1.0 / scale)), 2)
        # Snap to the byte-identity anchor when the winner is today's largest crop.
        if (crop.x, crop.y, crop.w, crop.h) == (bx, by, bw, bh):
            return SmartCrop(bx, by, bw, bh, 1.0)
        return SmartCrop(crop.x, crop.y, crop.w, crop.h, zoom)
    except Exception:
        try:
            x, y, w, h = best_crop(image_path, ratio)
            return SmartCrop(x, y, w, h, 1.0)
        except Exception:
            return SmartCrop(0, 0, 1, 1, 1.0)


def _base_crop_for_ratio(
    image_path: Union[str, Path], ratio: float, mask_path: Union[str, Path, None]
) -> Crop:
    """Today's largest-crop answer for ``ratio`` — mask-steered when a cutout
    exists, exactly like :func:`_v2_photo_position` resolves it."""
    if mask_path and str(mask_path) != str(image_path):
        with Image.open(image_path) as im:
            im.load()
            width, height = im.size
        with Image.open(mask_path) as mim:
            mim.load()
            alpha = _alpha_mask(mim)
        if alpha is not None and width > 0 and height > 0:
            sw, sh = _work_size(width, height)
            energy = np.asarray(alpha.resize((sw, sh), Image.BILINEAR), dtype=np.float32)
            cx, cy = _focus_centroids(energy, True, ratio)
            return _place_crop(width, height, ratio, cx, cy)
    return best_crop(image_path, ratio)


def _apply_headroom(
    sal: np.ndarray, ratio: float, scale: float, cx: float, cy: float, is_alpha: bool
) -> Tuple[float, float]:
    """Nudge a portrait-ish crop down so the subject keeps head-room.

    Only for subject silhouettes (alpha) on portrait-ish targets, where cutting
    the crop's top edge into the head band reads as a decapitated portrait.
    Deterministic; a no-op when there is no measurable subject.
    """
    if not is_alpha or ratio >= 1.0:
        return cx, cy
    band = _subject_band(sal)
    if band is None:
        return cx, cy
    _, subj_top, _, _ = band
    sh, sw = sal.shape
    _, crop_h = _crop_dims(sw, sh, ratio, scale)
    crop_h_frac = crop_h / sh
    crop_top = cy - crop_h_frac / 2.0
    # Want the crop's top edge to sit at least _HEADROOM_BAND above the subject
    # top; if it cuts below, slide the crop up (smaller crop_top → smaller cy).
    max_crop_top = subj_top - _HEADROOM_BAND
    if crop_top > max_crop_top:
        cy = max(crop_h_frac / 2.0, max_crop_top + crop_h_frac / 2.0)
    return cx, cy


def _place_crop_scaled(
    width: int, height: int, ratio: float, scale: float, cx: float, cy: float
) -> SmartCrop:
    """Place a crop of ``ratio`` at ``scale`` of the max crop, centred on
    ``(cx, cy)`` fractions, clamped within bounds (pixels)."""
    if ratio >= width / height:
        base_w = width
        base_h = min(height, max(1, round(width / ratio)))
    else:
        base_h = height
        base_w = min(width, max(1, round(height * ratio)))
    cw = max(1, min(width, round(base_w * scale)))
    ch = max(1, min(height, round(base_h * scale)))
    x = _slide(cx * width - cw / 2.0, width - cw)
    y = _slide(cy * height - ch / 2.0, height - ch)
    return SmartCrop(int(x), int(y), int(cw), int(ch), round(1.0 / scale, 4))


def smart_focus(
    image_path: Union[str, Path],
    ratio: RatioSpec = "4:5",
    *,
    symmetric: bool = False,
    mask_path: Union[str, Path, None] = None,
) -> Dict[str, str]:
    """The ``--mh-photo-*`` CSS vars for a smart crop of ``image_path``.

    Returns ``{"--mh-photo-pos": "x% y%"}`` and, only when a punch-in applies,
    ``"--mh-photo-scale": "1.NN"``. When the winner equals today's largest-crop
    answer the position string is exactly :func:`focus_position`'s and no scale
    is emitted, so the render is byte-identical. Safe default on any failure.
    """
    base_pos = (
        focus_position_with_mask(image_path, mask_path, ratio)
        if mask_path and str(mask_path) != str(image_path)
        else focus_position(image_path, ratio)
    )
    try:
        crop = smart_crop(image_path, ratio, symmetric=symmetric, mask_path=mask_path)
        with Image.open(image_path) as im:
            iw, ih = im.size
        if iw <= 0 or ih <= 0:
            return {"--mh-photo-pos": base_pos}
        cx = max(0.0, min(1.0, (crop.x + crop.w / 2.0) / iw)) * 100.0
        cy = max(0.0, min(1.0, (crop.y + crop.h / 2.0) / ih)) * 100.0
        pos = f"{cx:.0f}% {cy:.0f}%"
        out = {"--mh-photo-pos": pos}
        if crop.zoom > 1.0:
            out["--mh-photo-scale"] = f"{crop.zoom:.2f}"
        # Byte-identity: no punch-in and the position matches today's answer.
        if "--mh-photo-scale" not in out and pos == base_pos:
            return {"--mh-photo-pos": base_pos}
        return out
    except Exception:
        return {"--mh-photo-pos": base_pos}


def smart_focus_for_format(
    image_path: Union[str, Path],
    format_name: str = "story",
    *,
    symmetric: bool = False,
    mask_path: Union[str, Path, None] = None,
) -> Dict[str, str]:
    """:func:`smart_focus` resolved for a named output cut (story/portrait/…)."""
    return smart_focus(
        image_path, ratio_for_format(format_name), symmetric=symmetric, mask_path=mask_path
    )


__all__ = [
    "crops_for",
    "best_crop",
    "focus_position",
    "focus_position_for_format",
    "focus_position_with_mask",
    "ratio_for_format",
    "smart_crop",
    "smart_focus",
    "smart_focus_for_format",
    "FORMAT_RATIOS",
    "Crop",
    "SmartCrop",
    "RatioSpec",
]
