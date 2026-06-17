"""Multi-athlete collage / relay layout engine (roadmap G1.2).

Composites **2–4 athlete cutouts** into one *balanced* frame with **deterministic
multi-subject placement** — the still-graphic side of "the relay team / the
medley squad / the two PBs in one race" moment that a single-photo archetype
cannot tell honestly.

This module is the intelligence; the ``layouts/v2/relay_collage.html`` archetype
is the stage it paints onto, and ``sprint_hooks/relay_collage.py`` is the
auto-discovered seam that drops the composited block into that stage at render
time (no ``render.py`` edit). Splitting it this way keeps the engine a **pure,
deterministic, browser-free unit** that unit-tests on its own.

Design rules it lives by (consistent with the deterministic-engine boundary —
this is layout maths, never an LLM call):

* **Deterministic.** ``plan_collage(n, …, seed=s)`` is a pure function of its
  arguments — same inputs always yield the identical plan (and the identical
  HTML), so a re-render of the same card never reshuffles the squad.
* **Balanced by construction.** Whatever per-subject size profile a variant
  uses, the placement is recentred so the *weighted* visual centroid (area ∝
  height², the eye's weighting) sits on the frame's vertical midline. A collage
  never lists to one side — see :meth:`CollagePlan.centroid`.
* **In-bounds and legible.** Subjects stand on a shared baseline (a believable
  group photo, not floating heads), kept inside the frame, front-to-back
  z-ordered so overlaps read naturally, and the outermost subjects face inward.
* **Honest.** Only real provided cutouts are placed — never a synthesised
  person. With fewer than two people-photos the engine yields nothing and the
  archetype falls back to its single-photo / painted treatment.

Public API::

    plan_collage(count, *, width, height, seed)      -> CollagePlan
    render_collage(images, *, width, height, seed)   -> str   (HTML block)
    collage_images_for_brief(brief, …)               -> list[str] (data URIs)
    collage_seed_for_brief(brief)                    -> int
    collage_block_for_brief(brief, *, width, height) -> str   ("" if < 2 photos)

No LLM, no network.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass
from typing import Any, Optional, Sequence

# People-photo asset types the collage will pull from a brief (a relay/squad is
# made of athletes, never the venue or a logo). Mirrors media_library.models.
_PERSON_ASSET_TYPES = frozenset({"athlete_headshot", "athlete_action", "team_photo"})

# The most cutouts one frame can carry before it stops reading as a composition
# and starts reading as a contact sheet. The roadmap scopes G1.2 at 2–4.
MAX_SUBJECTS = 4

# Each subject sits in a bounding box; the cutout is ``object-fit: contain``-ed
# into it, bottom-anchored. The box is taller than wide (people are vertical),
# so box width is this fraction of the box height. The cutout never clips — a
# wider box just leaves transparent margin — so box height (``scale``) is the
# real apparent-size knob and this only governs horizontal breathing room.
BOX_W_OVER_H = 0.70

# Horizontal safe band for subject centres, so even the outermost subject keeps
# its body inside the frame rather than bleeding a limb off the edge.
_CX_MIN, _CX_MAX = 0.085, 0.915


@dataclass(frozen=True)
class Subject:
    """One placed cutout, in *fractions of the container* (resolution-free).

    ``cx`` is the horizontal centre; ``scale`` the box height; ``bottom`` the
    gap from the container floor to the subject's feet (the shared baseline plus
    a little per-subject lift). ``z`` is the paint order (higher = nearer the
    viewer), ``flip`` mirrors the cutout to face inward, and ``rotate`` is a
    subtle tilt in degrees.
    """

    cx: float
    scale: float
    bottom: float
    z: int
    flip: bool
    rotate: float

    @property
    def top(self) -> float:
        """Fraction of container height from the floor to the subject's head."""
        return self.bottom + self.scale

    @property
    def weight(self) -> float:
        """Visual weight ∝ painted area ∝ height² (the eye's size weighting)."""
        return self.scale * self.scale


@dataclass(frozen=True)
class CollagePlan:
    """A deterministic arrangement of 1–4 subjects in one frame."""

    count: int
    width: int
    height: int
    layout: str
    subjects: tuple[Subject, ...]

    def centroid(self) -> float:
        """Weight-balanced horizontal centroid of the placement (target 0.5).

        ``Σ wᵢ·cxᵢ / Σ wᵢ`` with ``wᵢ`` the subject's visual weight. The planner
        recentres every arrangement so this lands on the midline — the numeric
        definition of "balanced frame".
        """
        total = sum(s.weight for s in self.subjects)
        if total <= 0:
            return 0.5
        return sum(s.weight * s.cx for s in self.subjects) / total

    def spread(self) -> float:
        """Horizontal extent of the subject centres (0 for a lone subject)."""
        if len(self.subjects) < 2:
            return 0.0
        xs = [s.cx for s in self.subjects]
        return max(xs) - min(xs)


# --------------------------------------------------------------------------- #
# Arrangement vocabulary
# --------------------------------------------------------------------------- #
#
# One entry per subject-count. Each variant is a deterministic recipe; the seed
# picks the variant (``seed % len(variants)``). ``profile`` is the per-slot
# height multiplier (normalised so the tallest subject uses ``base``); a
# palindromic profile is balanced before correction, an asymmetric one exercises
# the recentring. ``spread`` is how wide the centres fan across the frame,
# ``tilt`` the max alternating tilt, ``lift`` the alternating baseline stagger,
# and ``face_in`` mirrors the outer subjects to look toward the middle.

_VARIANTS: dict[int, tuple[dict, ...]] = {
    1: (
        {
            "name": "solo_centre",
            "spread": 0.0,
            "profile": (1.0,),
            "base": 0.94,
            "tilt": 0.0,
            "lift": 0.0,
            "face_in": False,
        },
        {
            "name": "solo_raised",
            "spread": 0.0,
            "profile": (1.0,),
            "base": 0.88,
            "tilt": 0.0,
            "lift": 0.0,
            "face_in": False,
        },
    ),
    2: (
        {
            "name": "duo_face_off",
            "spread": 0.50,
            "profile": (1.0, 1.0),
            "base": 0.90,
            "tilt": 4.0,
            "lift": 0.018,
            "face_in": True,
        },
        {
            "name": "duo_lead",
            "spread": 0.46,
            "profile": (1.0, 0.90),
            "base": 0.92,
            "tilt": 3.0,
            "lift": 0.030,
            "face_in": True,
        },
        {
            "name": "duo_wide",
            "spread": 0.58,
            "profile": (0.96, 0.96),
            "base": 0.86,
            "tilt": 2.0,
            "lift": 0.010,
            "face_in": True,
        },
    ),
    3: (
        {
            "name": "trio_pyramid",
            "spread": 0.62,
            "profile": (0.86, 1.0, 0.86),
            "base": 0.86,
            "tilt": 3.0,
            "lift": 0.022,
            "face_in": True,
        },
        {
            "name": "trio_arc",
            "spread": 0.68,
            "profile": (1.0, 1.0, 1.0),
            "base": 0.80,
            "tilt": 2.0,
            "lift": 0.040,
            "face_in": True,
        },
        {
            "name": "trio_lead_left",
            "spread": 0.60,
            "profile": (1.0, 0.90, 0.82),
            "base": 0.86,
            "tilt": 2.5,
            "lift": 0.020,
            "face_in": True,
        },
    ),
    4: (
        {
            "name": "quad_lineup",
            "spread": 0.74,
            "profile": (1.0, 1.0, 1.0, 1.0),
            "base": 0.78,
            "tilt": 2.0,
            "lift": 0.020,
            "face_in": False,
        },
        {
            "name": "quad_centre_weight",
            "spread": 0.72,
            "profile": (0.86, 1.0, 1.0, 0.86),
            "base": 0.80,
            "tilt": 2.0,
            "lift": 0.016,
            "face_in": True,
        },
        {
            "name": "quad_wave",
            "spread": 0.76,
            "profile": (0.92, 1.0, 0.92, 0.84),
            "base": 0.80,
            "tilt": 2.5,
            "lift": 0.030,
            "face_in": True,
        },
    ),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def plan_collage(
    count: int,
    *,
    width: int = 1080,
    height: int = 1350,
    seed: int = 0,
) -> CollagePlan:
    """Deterministically place ``count`` subjects into a balanced frame.

    ``count`` is clamped to 1–:data:`MAX_SUBJECTS`. ``seed`` selects one of the
    arrangement variants for that count (stable per card). ``width``/``height``
    only nudge the overall scale (a wider-than-tall frame stands the squad a
    little shorter); the geometry is otherwise container-relative so the same
    plan paints correctly into any stage box.

    The arrangement is recentred so :meth:`CollagePlan.centroid` is 0.5 — the
    placement carries equal visual weight either side of the midline regardless
    of the per-subject size profile.
    """
    n = int(_clamp(float(count), 1, MAX_SUBJECTS))
    variants = _VARIANTS[n]
    spec = variants[int(seed) % len(variants)]

    profile = spec["profile"]
    peak = max(profile)
    base = float(spec["base"])
    # Landscape frames get a slightly shorter squad so heads don't crowd the top.
    if width > height:
        base *= 0.88
    scales = [base * (p / peak) for p in profile]

    # Even horizontal slots across the variant's spread, midline-centred.
    spread = float(spec["spread"])
    if n == 1:
        xs = [0.5]
    else:
        left = 0.5 - spread / 2.0
        xs = [left + spread * i / (n - 1) for i in range(n)]

    # Balance: shift every centre so the weighted centroid sits on 0.5. A no-op
    # for the palindromic profiles; a real correction for the asymmetric ones.
    weights = [s * s for s in scales]
    wsum = sum(weights) or 1.0
    centroid = sum(w * x for w, x in zip(weights, xs)) / wsum
    shift = 0.5 - centroid
    xs = [_clamp(x + shift, _CX_MIN, _CX_MAX) for x in xs]

    # Shared baseline + a gentle alternating lift so the row isn't a flat cut-out
    # line; outer subjects sit a touch lower (read as nearer the camera).
    lift = float(spec["lift"])
    tilt = float(spec["tilt"])
    centre = (n - 1) / 2.0

    subjects: list[Subject] = []
    for i in range(n):
        dist = abs(i - centre)  # 0 at the middle, grows toward the ends
        bottom = round(lift * (centre - dist), 4)  # middle lifted, ends grounded
        # Nearer the centre paints in front, so a central subject overlaps inward.
        z = 100 - int(round(dist * 10))
        # Outer subjects face the middle; the left half mirrors to look right.
        flip = bool(spec["face_in"]) and (i < centre)
        # Alternating, sign-stable tilt scaled by how far out the subject is.
        direction = -1.0 if i < centre else (1.0 if i > centre else 0.0)
        rotate = round(direction * tilt * (dist / max(centre, 1.0)), 3)
        subjects.append(
            Subject(
                cx=round(xs[i], 4),
                scale=round(scales[i], 4),
                bottom=bottom,
                z=z,
                flip=flip,
                rotate=rotate,
            )
        )

    return CollagePlan(
        count=n,
        width=int(width),
        height=int(height),
        layout=str(spec["name"]),
        subjects=tuple(subjects),
    )


# --------------------------------------------------------------------------- #
# HTML compositor
# --------------------------------------------------------------------------- #


def _safe_src(src: Any) -> Optional[str]:
    """Accept a usable image source, reject anything that could break the tag.

    Cutouts arrive as ``data:`` URIs (base64 — quote-free) or vetted paths.
    Defence-in-depth: anything carrying a quote / angle bracket is dropped
    rather than injected verbatim into ``src="…"``.
    """
    if not isinstance(src, str):
        return None
    s = src.strip()
    if not s or '"' in s or "<" in s or ">" in s:
        return None
    return s


def render_collage(
    images: Sequence[str],
    *,
    width: int = 1080,
    height: int = 1350,
    seed: int = 0,
    names: Optional[Sequence[str]] = None,
) -> str:
    """Composite ``images`` (2–:data:`MAX_SUBJECTS` cutouts) into one HTML block.

    Returns a self-contained ``<div class="rc-collage">`` whose children are the
    bottom-anchored, balanced subject figures from :func:`plan_collage` —
    positioned with inline percentages so it fills whatever stage container the
    archetype drops it into. It paints no brand colour of its own (only neutral
    rgba contact shadows), so the cutouts read against the archetype's resolved
    brand ground rather than competing with it.

    Sources that fail :func:`_safe_src` are skipped; with fewer than two usable
    cutouts the block is empty (``""``) and the caller keeps the single-photo
    fallback. Output is byte-stable for a given ``(images, width, height,
    seed)``.
    """
    srcs = [s for s in (_safe_src(i) for i in images) if s][:MAX_SUBJECTS]
    if len(srcs) < 2:
        return ""

    plan = plan_collage(len(srcs), width=width, height=height, seed=seed)
    name_list = list(names or [])

    # Paint back-to-front so nearer (higher-z) subjects overlap correctly.
    order = sorted(range(len(plan.subjects)), key=lambda i: plan.subjects[i].z)

    figures: list[str] = []
    for i in order:
        s = plan.subjects[i]
        src = srcs[i]
        alt = html.escape(name_list[i]) if i < len(name_list) and name_list[i] else ""
        box_w = round(s.scale * BOX_W_OVER_H * 100, 3)
        box_h = round(s.scale * 100, 3)
        left = round(s.cx * 100, 3)
        bottom = round(s.bottom * 100, 3)
        sx = -1 if s.flip else 1
        # A soft contact shadow grounds the subject on the shared baseline.
        shadow = (
            f'<span class="rc-collage__shadow" style="bottom:{max(bottom - 1.2, 0):.3f}%;'
            f'left:{left:.3f}%;width:{box_w * 0.62:.3f}%"></span>'
        )
        figures.append(
            shadow + f'<figure class="rc-collage__subject" style="'
            f"left:{left:.3f}%;bottom:{bottom:.3f}%;width:{box_w:.3f}%;height:{box_h:.3f}%;"
            f"z-index:{s.z};transform:translateX(-50%) rotate({s.rotate:.3f}deg) scaleX({sx});"
            f'transform-origin:bottom center">'
            f'<img src="{src}" alt="{alt}" />'
            f"</figure>"
        )

    style = (
        ".rc-collage{position:absolute;inset:0;overflow:hidden}"
        ".rc-collage__subject{position:absolute;margin:0;padding:0}"
        ".rc-collage__subject img{width:100%;height:100%;object-fit:contain;"
        "object-position:bottom center;display:block;"
        "filter:drop-shadow(0 18px 30px rgba(0,0,0,0.34))}"
        ".rc-collage__shadow{position:absolute;height:3.2%;transform:translateX(-50%);"
        "border-radius:50%;background:radial-gradient(ellipse at center,"
        "rgba(0,0,0,0.40) 0%,rgba(0,0,0,0) 70%);z-index:1;pointer-events:none}"
    )
    return (
        f'<div class="rc-collage" data-collage-layout="{plan.layout}" '
        f'data-collage-count="{plan.count}">'
        f"<style>{style}</style>" + "".join(figures) + "</div>"
    )


# --------------------------------------------------------------------------- #
# Brief integration (resolve a card's people-photos → composited block)
# --------------------------------------------------------------------------- #


def collage_seed_for_brief(brief: Any) -> int:
    """A stable non-negative placement seed for ``brief``.

    Prefers the brief's own ``variation_seed`` (so the collage moves in lock-step
    with the rest of the card's deterministic variation); otherwise hashes the
    content-item / brief id. Same card → same squad arrangement, every render.
    """
    seed = getattr(brief, "variation_seed", 0)
    try:
        seed = int(seed or 0)
    except (TypeError, ValueError):
        seed = 0
    if seed:
        return abs(seed)
    key = str(getattr(brief, "content_item_id", "") or getattr(brief, "id", "") or "relay")
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)


def _resolve_people_paths(brief: Any, store: Any, max_subjects: int) -> list[str]:
    """Ordered, de-duplicated people-photo file paths for ``brief``.

    Honours an explicit ``brief.collage_image_paths`` override first (a
    forward-compatible hook for a pipeline that already resolved the squad);
    otherwise walks ``brief.sourced_asset_ids`` through the media-library store
    and keeps the athlete/team photos, preferring a pre-computed cutout. Always
    best-effort — a missing store or unreadable row simply yields fewer (or no)
    subjects.
    """
    override = getattr(brief, "collage_image_paths", None)
    if override:
        out: list[str] = []
        for p in override:
            sp = str(p).strip()
            if sp and sp not in out:
                out.append(sp)
            if len(out) >= max_subjects:
                break
        return out

    asset_ids = list(getattr(brief, "sourced_asset_ids", None) or [])
    if not asset_ids:
        return []
    if store is None:
        try:
            from mediahub.media_library.store import get_store

            store = get_store()
        except Exception:
            return []

    paths: list[str] = []
    for asset_id in asset_ids:
        try:
            asset = store.get(asset_id)
        except Exception:
            asset = None
        if asset is None or getattr(asset, "type", "") not in _PERSON_ASSET_TYPES:
            continue
        cutout = getattr(asset, "cutout_path", None)
        path = cutout or getattr(asset, "path", None)
        if not path:
            continue
        path = str(path)
        if path not in paths:
            paths.append(path)
        if len(paths) >= max_subjects:
            break
    return paths


def collage_images_for_brief(
    brief: Any,
    *,
    max_subjects: int = MAX_SUBJECTS,
    store: Any = None,
) -> list[str]:
    """Resolve a card's people-photos to ``data:`` URIs ready for the collage.

    Returns up to ``max_subjects`` cutout data URIs (or ``[]``). Each source is
    cut out if it isn't already and embedded as a data URI via the renderer's
    own helpers — so the collage subjects match the single-photo path's
    treatment exactly. Best-effort and isolating: any one photo that fails to
    resolve is skipped, never fatal.
    """
    paths = _resolve_people_paths(brief, store, max_subjects)
    if not paths:
        return []

    # Lazy import: avoids any import-time cycle with the (large) render module,
    # which pulls in this package's sprint-hook seam.
    try:
        from mediahub.graphic_renderer.render import (
            _img_to_data_uri,
            _maybe_cut_out_athlete,
        )
    except Exception:
        return []

    profile_id = str(getattr(brief, "profile_id", "") or "default")
    uris: list[str] = []
    for path in paths:
        try:
            cut = _maybe_cut_out_athlete(path, profile_id=profile_id)
            uris.append(_img_to_data_uri(cut))
        except Exception:
            continue
        if len(uris) >= max_subjects:
            break
    return uris


def collage_block_for_brief(
    brief: Any,
    *,
    width: int = 1080,
    height: int = 1350,
    store: Any = None,
) -> str:
    """End-to-end: resolve ``brief``'s squad and composite it, or ``""``.

    The one call the render hook makes. Returns ``""`` whenever fewer than two
    people-photos resolve, so the ``relay_collage`` archetype keeps its
    single-photo / painted fallback instead of showing a one-person "collage".
    """
    uris = collage_images_for_brief(brief, store=store)
    if len(uris) < 2:
        return ""
    return render_collage(uris, width=width, height=height, seed=collage_seed_for_brief(brief))


__all__ = [
    "MAX_SUBJECTS",
    "BOX_W_OVER_H",
    "Subject",
    "CollagePlan",
    "plan_collage",
    "render_collage",
    "collage_seed_for_brief",
    "collage_images_for_brief",
    "collage_block_for_brief",
]
