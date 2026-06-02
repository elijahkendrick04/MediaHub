"""B3 — deterministic visual-regression backbone.

``vision.py`` (the VLM judge) is great at NOVEL visual defects but has no stable
baseline, so it can't catch a *regression* and adds nondeterminism. This module is
the regression backbone: a committed, human-blessed baseline PNG per key surface
(home, review) and a pixel-diff against it every sweep — analogous to
``baseline.py``'s golden count baseline, but for pixels. A diff above the tolerance
is a DETERMINISTIC ``visual_regression`` finding (opens immediately, no confirm gate).

Baselines live under ``autotest/baseline/visual/<engine>/<surface>.png`` and are
**human-committed, never auto-written** (same anti-circularity rule as the golden
count baseline). With no baseline yet, this honest-skips (one ``info`` note telling
the operator to capture one) — it never invents a regression. Pillow is already a
runtime dependency, so there's no new package and no Playwright snapshot harness to
maintain. Toggle with ``AUTOTEST_VISUAL`` (default 1).

Dynamic regions (captions, timestamps, run ids) should be masked when a baseline is
captured (a stable surface) — see docs/autotest/AUTOTEST_CHANGES.md for the capture
recipe; per-region masking inside the diff is a documented follow-up.
"""
from __future__ import annotations

import os
from pathlib import Path

from autotest.report import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = Path(__file__).resolve().parent / "baseline" / "visual"

# A pixel counts as "changed" once its per-channel difference exceeds this (0–255),
# so JPEG-ish noise / sub-pixel AA doesn't read as a regression.
_PIXEL_DELTA = int(os.environ.get("AUTOTEST_VISUAL_PIXEL_DELTA", "24"))


def _max_diff_ratio() -> float:
    try:
        return float(os.environ.get("AUTOTEST_VISUAL_MAX_DIFF", "0.02"))
    except ValueError:
        return 0.02


def _rel(p: Path) -> str:
    """Repo-relative path for messages, falling back to the absolute path when the
    baseline dir is outside the repo (e.g. a test's tmp dir)."""
    try:
        return os.path.relpath(str(p), REPO_ROOT)
    except ValueError:
        return str(p)


def baseline_path(surface: str, engine: str = "chromium") -> Path:
    return BASELINE_DIR / engine / f"{surface}.png"


def diff_ratio(current_png: Path, baseline_png: Path) -> float:
    """Fraction of pixels that differ beyond the per-channel delta. A size mismatch
    is treated as a full (1.0) difference. Returns 0.0 on an exact match."""
    from PIL import Image, ImageChops
    with Image.open(current_png) as a_img, Image.open(baseline_png) as b_img:
        a = a_img.convert("RGB")
        b = b_img.convert("RGB")
        if a.size != b.size:
            return 1.0
        diff = ImageChops.difference(a, b).convert("L")
        mask = diff.point(lambda p: 255 if p > _PIXEL_DELTA else 0)
        changed = sum(mask.point(lambda p: 1 if p else 0).getdata())
        total = a.size[0] * a.size[1]
        return (changed / total) if total else 0.0


def check(surface: str, screenshot_path: str | None, engine: str = "chromium") -> list[Finding]:
    """Diff a captured surface screenshot against its committed baseline. Returns a
    deterministic ``visual_regression`` finding on a diff above tolerance, a single
    ``info`` honest-skip when there's no baseline / no screenshot / Pillow is missing,
    else []. Never raises, never auto-writes a baseline."""
    if os.environ.get("AUTOTEST_VISUAL", "1") == "0":
        return []
    shot = Path(screenshot_path) if screenshot_path else None
    if not shot or not shot.exists():
        return []   # nothing captured for this surface this sweep
    base = baseline_path(surface, engine)
    if not base.exists():
        return [Finding(
            category="visual_skipped", severity="info", is_bug=False,
            title=f"Visual baseline missing for {surface} ({engine})",
            route=f"({surface} screen)",
            expected=f"A committed baseline at {_rel(base)}",
            actual="No baseline yet — capture & human-review one to enable regression diffing.",
            evidence="Visual-regression check is the deterministic backbone for vision.py; "
                     "baselines are human-committed, never auto-written.")]
    try:
        ratio = diff_ratio(shot, base)
    except Exception as exc:
        return [Finding(category="visual_skipped", severity="info", is_bug=False,
                        title=f"Visual diff could not run for {surface}",
                        route=f"({surface} screen)", expected="a pixel diff",
                        actual=str(exc)[:200], evidence=str(exc)[:400])]
    tol = _max_diff_ratio()
    if ratio > tol:
        return [Finding(
            category="visual_regression", severity="medium",
            title=f"Visual regression on {surface} ({ratio:.1%} of pixels changed)",
            route=f"({surface} screen)",
            expected=f"≤ {tol:.0%} pixel change vs the committed {surface} baseline",
            actual=f"{ratio:.1%} of pixels changed vs baseline ({engine})",
            evidence=f"Pixel diff vs {_rel(base)} exceeded "
                     f"AUTOTEST_VISUAL_MAX_DIFF={tol}. Mask dynamic regions in the baseline "
                     "if this is expected churn.",
            suspect=f"visual:{surface}:{engine}",
            screenshot=os.path.relpath(str(shot), REPO_ROOT),
            repro=[f"Render the {surface} surface", f"Diff against {_rel(base)}"])]
    return []
