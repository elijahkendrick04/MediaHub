"""Image-side measurement at ingest: dimensions, orientation, dominant colours,
and deterministic technical-quality metrics (sharpness, clipping, entropy, dHash).

Pure Pillow/numpy maths — same file in, same numbers out, no AI, no network.
EXIF orientation is honoured everywhere: :func:`bake_exif_orientation` rewrites
a fresh upload upright once (so Pillow and Chromium see the same pixel grid),
and :func:`measure_image` applies the transpose in memory so legacy files that
were stored before baking still measure at their display orientation.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# EXIF tag 0x0112 = Orientation; values 2..8 mean "the pixel grid needs a
# transpose to display upright" (1 / absent = already upright).
_EXIF_ORIENTATION_TAG = 0x0112

# Quality metrics are computed on a fixed-size working grid so sharpness /
# clipping numbers are comparable across assets regardless of megapixels.
_QUALITY_WORK_MAX = 512

_EMPTY_MEASUREMENT = {
    "width": 0,
    "height": 0,
    "orientation": "unknown",
    "dominant_colours": [],
    "quality": None,
}


def bake_exif_orientation(path) -> bool:
    """Rewrite ``path`` upright when it carries an EXIF orientation transpose.

    Returns True iff the file was rewritten. Files without a 2..8 orientation
    tag are left byte-identical (no pointless JPEG re-encode). Never raises —
    a photo that can't be baked is simply measured exif-aware downstream.
    """
    try:
        p = Path(path)
        with Image.open(p) as im:
            orientation = im.getexif().get(_EXIF_ORIENTATION_TAG)
            if orientation is None or int(orientation) == 1:
                return False
            upright = ImageOps.exif_transpose(im)
            fmt = im.format
            icc = im.info.get("icc_profile")
        save_kwargs: dict = {}
        if icc:
            save_kwargs["icc_profile"] = icc
        if fmt == "JPEG":
            save_kwargs["quality"] = 92
            if upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")
        # exif_transpose already dropped the orientation tag from the copy's
        # EXIF, so the re-saved file reads as upright everywhere. Write to a
        # sibling temp file + atomic replace so a mid-save failure can never
        # corrupt the only copy of the user's photo.
        tmp = p.with_name(p.name + ".baking")
        upright.save(tmp, format=fmt, **save_kwargs)
        tmp.replace(p)
        return True
    except Exception as e:
        log.debug("bake_exif_orientation failed for %s: %s", path, e)
        try:
            Path(path).with_name(Path(path).name + ".baking").unlink(missing_ok=True)
        except OSError:
            pass
        return False


def measure_image(path: str) -> dict:
    """Return {width, height, orientation, dominant_colours[], quality{...}}.

    EXIF-aware: the transpose is applied in memory first, so a legacy phone
    photo that was stored un-baked still reports its display width/height and
    orientation. ``quality`` is the deterministic technical-quality dict (see
    :func:`_quality_metrics`) or None when the file couldn't be read.
    """
    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as e:
        log.debug("measure_image open failed for %s: %s", path, e)
        return dict(_EMPTY_MEASUREMENT)
    w, h = img.size
    orientation = "square"
    if w > h * 1.05:
        orientation = "landscape"
    elif h > w * 1.05:
        orientation = "portrait"
    return {
        "width": w,
        "height": h,
        "orientation": orientation,
        "dominant_colours": _dominant_colours(img, n=4),
        "quality": _quality_metrics(img),
    }


def measure_asset(asset) -> bool:
    """Measure ``asset.path`` and write the results onto the MediaAsset.

    Sets width / height / orientation / dominant_colours and
    ``media_meta["quality"]``. Returns True iff a real measurement landed;
    an unreadable file leaves the asset untouched (never zeroes out data a
    previous measurement already stored). ``has_face`` is deliberately NOT
    set here — there is no real face signal at ingest; it stays None until
    one exists (a fake aspect-ratio guess is worse than honest absence).
    """
    m = measure_image(asset.path)
    if not m["width"] or not m["height"]:
        return False
    asset.width = m["width"]
    asset.height = m["height"]
    asset.orientation = m["orientation"]
    asset.dominant_colours = m["dominant_colours"]
    if not isinstance(asset.media_meta, dict):
        asset.media_meta = {}
    asset.media_meta["quality"] = m["quality"]
    return True


def dhash_hamming(a: str, b: str) -> int:
    """Hamming distance between two 64-bit dHash hex strings (0..64).

    Invalid / empty hashes count as maximally distant so they can never form
    a burst family with anything.
    """
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except (TypeError, ValueError):
        return 64


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _dominant_colours(img: Image.Image, n: int = 4) -> list[str]:
    """Quick palette via downsample + quantise. Returns hex list."""
    try:
        small = img.resize((120, 120))
        # Quantise to a small palette and pick top
        pal = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
        pal_rgb = pal.convert("RGB")
        # Count pixels by colour
        pixels = list(pal_rgb.getdata())
        counts = Counter(pixels)
        most = counts.most_common(n * 2)
        out: list[str] = []
        for (r, g, b), _ in most:
            # Skip near-pure-white/black to keep palette useful
            if (r > 245 and g > 245 and b > 245) or (r < 12 and g < 12 and b < 12):
                continue
            out.append(f"#{r:02X}{g:02X}{b:02X}")
            if len(out) >= n:
                break
        return out
    except Exception as e:
        log.debug("dominant_colours failed: %s", e)
        return []


def _quality_metrics(img: Image.Image) -> dict:
    """Deterministic technical-quality numbers for one upright RGB image.

    * ``sharpness`` — variance of the 4-neighbour Laplacian on a fixed-size
      luma grid (blur kills high-frequency energy, so blurry ≪ sharp).
    * ``clip_highlights`` / ``clip_shadows`` — fraction of luma pixels at the
      blown (≥250) / crushed (≤5) ends.
    * ``entropy`` — Shannon entropy of the luma histogram in bits (0..8);
      near-flat frames (lens cap, blank wall) score close to 0.
    * ``dhash`` — 64-bit difference hash as a 16-char hex string, for burst /
      near-duplicate grouping in the selector.
    """
    grey = img.convert("L")
    w, h = grey.size
    longest = max(w, h)
    if longest > _QUALITY_WORK_MAX:
        scale = _QUALITY_WORK_MAX / longest
        grey = grey.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)
    arr = np.asarray(grey, dtype=np.float32)

    sharpness = 0.0
    if arr.shape[0] >= 3 and arr.shape[1] >= 3:
        lap = (
            4.0 * arr[1:-1, 1:-1] - arr[:-2, 1:-1] - arr[2:, 1:-1] - arr[1:-1, :-2] - arr[1:-1, 2:]
        )
        sharpness = float(lap.var())

    clip_highlights = float(np.mean(arr >= 250.0))
    clip_shadows = float(np.mean(arr <= 5.0))

    hist, _ = np.histogram(arr, bins=256, range=(0.0, 256.0))
    total = float(hist.sum())
    entropy = 0.0
    if total > 0:
        p = hist[hist > 0] / total
        entropy = float(-(p * np.log2(p)).sum())

    return {
        "sharpness": round(sharpness, 2),
        "clip_highlights": round(clip_highlights, 4),
        "clip_shadows": round(clip_shadows, 4),
        "entropy": round(entropy, 3),
        "dhash": _dhash(grey),
    }


def _dhash(grey: Image.Image) -> str:
    """64-bit difference hash (9×8 grid, adjacent-column compare) as hex."""
    small = np.asarray(grey.resize((9, 8), Image.BILINEAR), dtype=np.float32)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


__all__ = [
    "bake_exif_orientation",
    "measure_image",
    "measure_asset",
    "dhash_hamming",
]
