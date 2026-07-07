"""Deterministic matte-quality gate for athlete cutouts (PHOTOS-7 / M14).

A background-removed cutout is only worth shipping when the matte is sane: a
shredded matte (half a head, limbs eaten by pool-water reflections, floating
islands of background) is one of the most visible "cheap content" tells a card
can carry. Before the renderer accepts a cutout PNG, this module measures the
alpha mask with three pure image-maths checks — no AI, no network, no new
dependencies (numpy + PIL only), same file → same verdict every run:

* **alpha coverage** — the subject must occupy a sane fraction of the frame
  (``8%–85%``). Near-zero coverage means the model found nothing; near-full
  coverage means it removed nothing.
* **largest-connected-component ratio** — the biggest connected blob of the
  subject mask must carry ≥ 80% of the subject pixels. A matte whose "subject"
  is a scatter of disconnected islands is shredded.
* **border contact** — a person photographed on a pool deck touches the bottom
  edge (and maybe one side); a "cutout" whose subject wraps most of the frame
  border kept the background.

On failure the caller falls back *honestly* to the original photograph (the
scrim/full-bleed treatment path renders un-cutout photos well) and records the
reason in the visual's explainability trace — never a broken silhouette.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

__all__ = ["MatteVerdict", "assess_matte"]

# Analysis runs on a downscaled working grid — the three metrics are area
# ratios, which are scale-stable, so the small grid gives the same verdict as
# the full image for a fraction of the cost.
_WORK_MAX = 160

# Alpha (0–255) above which a pixel counts as subject; below is matting haze.
_SUBJECT_ALPHA = 25

# Gate thresholds (fractions).
_MIN_COVERAGE = 0.08
_MAX_COVERAGE = 0.85
_MIN_COMPONENT_RATIO = 0.80
_MAX_BORDER_CONTACT = 0.55


@dataclass(frozen=True)
class MatteVerdict:
    """The gate's decision for one cutout, with the measured evidence."""

    ok: bool
    reason: str = ""  # human-readable failure reason ("" when ok)
    metrics: dict = field(default_factory=dict)


def _subject_mask(path: Union[str, Path]) -> "np.ndarray | None":
    """Binary subject mask on the working grid, or None when there is no
    usable alpha channel (an opaque file is not a cutout at all)."""
    with Image.open(path) as im:
        im.load()
        has_alpha = im.mode in ("RGBA", "LA", "PA") or (
            im.mode == "P" and "transparency" in im.info
        )
        if not has_alpha:
            return None
        alpha = im.convert("RGBA").getchannel("A")
        w, h = alpha.size
        longest = max(w, h)
        if longest > _WORK_MAX:
            scale = _WORK_MAX / longest
            alpha = alpha.resize(
                (max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR
            )
    arr = np.asarray(alpha, dtype=np.uint8)
    if arr.size == 0:
        return None
    if int(arr.min()) == 255:  # fully opaque — no matte was produced
        return None
    return arr > _SUBJECT_ALPHA


def _largest_component_ratio(mask: np.ndarray) -> float:
    """Fraction of subject pixels in the largest 4-connected component.

    Iterative two-pass style labelling via BFS flood fill on the small working
    grid — pure numpy/stdlib, no scipy.
    """
    total = int(mask.sum())
    if total == 0:
        return 0.0
    labels = np.zeros(mask.shape, dtype=np.int32)
    current = 0
    best = 0
    h, w = mask.shape
    for sy, sx in zip(*np.nonzero(mask & (labels == 0))):
        if labels[sy, sx]:
            continue
        current += 1
        size = 0
        stack = [(int(sy), int(sx))]
        labels[sy, sx] = current
        while stack:
            y, x = stack.pop()
            size += 1
            if y > 0 and mask[y - 1, x] and not labels[y - 1, x]:
                labels[y - 1, x] = current
                stack.append((y - 1, x))
            if y + 1 < h and mask[y + 1, x] and not labels[y + 1, x]:
                labels[y + 1, x] = current
                stack.append((y + 1, x))
            if x > 0 and mask[y, x - 1] and not labels[y, x - 1]:
                labels[y, x - 1] = current
                stack.append((y, x - 1))
            if x + 1 < w and mask[y, x + 1] and not labels[y, x + 1]:
                labels[y, x + 1] = current
                stack.append((y, x + 1))
        best = max(best, size)
    return best / total


def _border_contact(mask: np.ndarray) -> float:
    """Fraction of frame-border pixels that are subject."""
    border = np.concatenate([mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]])
    if border.size == 0:
        return 0.0
    return float(border.mean())


def assess_matte(path: Union[str, Path]) -> MatteVerdict:
    """Judge a cutout PNG's matte. Deterministic; never raises for a readable
    file — an unreadable/mask-less file fails with an explicit reason."""
    try:
        mask = _subject_mask(path)
    except Exception as exc:
        return MatteVerdict(False, f"cutout unreadable ({exc.__class__.__name__})")
    if mask is None:
        return MatteVerdict(False, "no usable alpha matte (fully opaque output)")

    coverage = float(mask.mean())
    metrics: dict = {"coverage": round(coverage, 4)}
    if coverage < _MIN_COVERAGE:
        return MatteVerdict(
            False, f"subject covers only {coverage:.0%} of frame (min {_MIN_COVERAGE:.0%})", metrics
        )
    if coverage > _MAX_COVERAGE:
        return MatteVerdict(
            False,
            f"matte kept {coverage:.0%} of frame (max {_MAX_COVERAGE:.0%}) — background not removed",
            metrics,
        )

    component = _largest_component_ratio(mask)
    metrics["largest_component"] = round(component, 4)
    if component < _MIN_COMPONENT_RATIO:
        return MatteVerdict(
            False,
            f"shredded matte: largest piece holds {component:.0%} of subject "
            f"(min {_MIN_COMPONENT_RATIO:.0%})",
            metrics,
        )

    contact = _border_contact(mask)
    metrics["border_contact"] = round(contact, 4)
    if contact > _MAX_BORDER_CONTACT:
        return MatteVerdict(
            False,
            f"subject wraps {contact:.0%} of the frame border (max {_MAX_BORDER_CONTACT:.0%})"
            " — background likely retained",
            metrics,
        )

    return MatteVerdict(True, "", metrics)
