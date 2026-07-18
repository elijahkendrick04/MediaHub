"""F6 (systemic floor) — measured layout scoring over K candidate style packs.

Canva's quality floor comes from *scoring and curation*: every published
template inherits a reviewed layout, and the auto-layout literature
(O'Donovan / Agarwala / Hertzmann) shows that a handful of interpretable
energy terms — alignment, whitespace band, importance-weighted balance,
overlap penalty, saliency coverage — reproduce novice-designer-grade layouts
by optimisation alone. MediaHub historically picked a style pack by a blind
seed-modulo walk (``style_packs.pick_style_pack_avoiding``) and never measured
whether the *composed* result was balanced, breathing, or collision-free.

F6 closes that gap with a **deterministic layout-energy scorer** that runs over
the seeded candidate walk before the final screenshot: for each candidate pack
the card's real HTML is composed and measured once in the warm browser (a
single ``getBoundingClientRect`` sweep — see :data:`MEASURE_JS`), scored on the
terms below, and the argmax is shipped. Same brief + seed → same candidates →
same measured geometry → same argmax, so the whole thing respects the
deterministic-engine boundary: it is *mathematical scoring*, never an LLM.

House rules this module keeps, matching every other opt-in render lever:

* **Deterministic.** Pure float arithmetic over the measured geometry; the
  candidate order is the deterministic pack walk; ties resolve to the lowest
  candidate index (which is always the director's current pack), so the outcome
  is reproducible to the byte.
* **Opt-in & byte-identical when off.** Gated on ``MEDIAHUB_LAYOUT_SCORE`` (a
  default-OFF flag). When the flag is unset :func:`enabled` is ``False`` and the
  render path never calls in here, so every legacy / flag-off render is
  byte-identical to before.
* **Humble.** The director's chosen pack is always candidate #0 and wins every
  tie; F6 only overrides it when a sibling pack beats it by more than
  :data:`_IMPROVEMENT_EPS`, so a card only changes when there is a *measurable*
  layout win. A pack whose text collides is hard-rejected, but if every
  candidate collides the scorer degrades to the current pack — never worse than
  today.
* **Brand-safe by construction.** Every candidate is a real member of
  ``style_packs.list_style_packs()`` (or the mood bundle), so it is already
  in-catalog, under the coherence weight cap and APCA-legible. F6 only *reorders
  the choice among* brand-safe packs; it never invents colour, geometry or type.

This module is pure and importable without a browser: the measurement (running
:data:`MEASURE_JS` in Playwright) lives in :mod:`graphic_renderer.render`, which
imports :func:`choose` / :func:`score_geometry` and feeds them the geometry
dicts. That keeps the energy maths unit-testable on synthetic geometry with no
Chromium, exactly like ``archetypes.score_archetype`` (F4).
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

__all__ = [
    "enabled",
    "candidate_count",
    "candidate_pack_ids",
    "DECISION_SIZE",
    "MEASURE_JS",
    "score_geometry",
    "choose",
]

# The canonical decision geometry: the v2 archetype certification anchor
# (1080×1350 feed_portrait — the primary cut every archetype must read well at).
# Candidates are always composed and measured at THIS geometry, whatever cut is
# being rendered, so every format of a card computes the identical winner — a
# card stays one design across its cuts, and parallel per-format renders can
# only benign-race to the same deterministic value.
DECISION_SIZE = (1080, 1350)


# --------------------------------------------------------------------------- #
# Opt-in gate (default OFF — mirrors render._derived_accent_enabled idiom)
# --------------------------------------------------------------------------- #

# The number of candidate packs to measure per card, counting the director's
# current pack. Small by default: the win is picking the cleanest of a few
# neighbours, not an exhaustive catalog sweep (which would cost K browser
# passes). Clamped to a sane range so a stray env value can't explode the cost.
_DEFAULT_K = 4
_MIN_K = 2
_MAX_K = 8


def enabled() -> bool:
    """True only when the operator opts in with ``MEDIAHUB_LAYOUT_SCORE``.

    Default OFF: an unset / falsey flag means the render path never scores, so
    the pack the director chose ships unchanged and the render is byte-identical
    to the pre-F6 output.
    """
    return os.environ.get("MEDIAHUB_LAYOUT_SCORE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def candidate_count() -> int:
    """How many candidate packs to consider (including the current one)."""
    raw = os.environ.get("MEDIAHUB_LAYOUT_SCORE_K", "").strip()
    if not raw:
        return _DEFAULT_K
    try:
        k = int(raw)
    except ValueError:
        return _DEFAULT_K
    return max(_MIN_K, min(_MAX_K, k))


# --------------------------------------------------------------------------- #
# Candidate enumeration — the seeded pack walk, current pack first
# --------------------------------------------------------------------------- #


def candidate_pack_ids(
    brief: Any, k: Optional[int] = None, recent: Iterable[str] = ()
) -> list[str]:
    """The candidate pack ids to score, the director's current pack first.

    F6 must respect *whichever picker chose the card*: a mood card walks its
    small curated mood bundle (so a geometrically-tidy but off-mood pack can
    never override the director's feeling), and every other card samples the
    full deterministic catalog order. In both cases the current pack is
    candidate #0 (so it wins ties and a no-improvement card stays
    byte-identical), and later candidates skip ``recent`` ids exactly like
    ``style_packs.pick_style_pack_avoiding``.

    **Strided sampling.** The catalog is sorted quiet → busy, so the packs
    *adjacent* to the current one are near-duplicates (same ground, trailing
    density/texture variants) — measuring those would choose among visually
    identical candidates and learn nothing. The walk therefore samples the pool
    at ``n/k`` strides from the current pack's position: candidates span the
    ground/texture space (a genuinely different treatment can rescue a card
    whose current ground buries its focus), while staying fully deterministic —
    same current pack + same pool → same candidate list. A small pool (a mood
    bundle) degrades naturally to the plain forward walk.

    An empty / unknown ``brief.style_pack`` yields ``[]`` — a legacy / bare card
    has no pack to score, so F6 no-ops and the render is unchanged.
    """
    current = (getattr(brief, "style_pack", "") or "").strip().lower()
    if not current:
        return []
    if k is None:
        k = candidate_count()

    from mediahub.graphic_renderer import style_packs as _sp

    pool_ids: list[str]
    mood = (getattr(brief, "mood", "") or "").strip()
    mood_ids = [m.strip().lower() for m in _sp.mood_preset_ids(mood)] if mood else []
    if mood_ids:
        pool_ids = mood_ids
    else:
        pool_ids = [p.id for p in _sp.list_style_packs()]

    # The current pack must anchor the walk at index 0 even if (unusually) it is
    # not a member of the chosen pool — so it always wins ties and the no-change
    # path is byte-identical.
    if current not in pool_ids:
        pool_ids = [current] + [pid for pid in pool_ids if pid != current]

    start = pool_ids.index(current)
    avoid = {str(r).strip().lower() for r in recent if r}
    out: list[str] = [current]
    seen: set[str] = {current}
    n = len(pool_ids)
    # Deterministic strided sample: the j-th candidate sits j·n/k past the
    # current pack (wrapping), stepping forward past duplicates / recent ids.
    for j in range(1, k):
        base = (start + (j * n) // k) % n
        for probe in range(n):
            cid = pool_ids[(base + probe) % n]
            if cid in seen or cid in avoid:
                continue
            seen.add(cid)
            out.append(cid)
            break
    return out


# --------------------------------------------------------------------------- #
# The in-page measurement sweep (run by render.py in Playwright)
# --------------------------------------------------------------------------- #

# One getBoundingClientRect sweep per candidate, modelled on render._RENDER_FLOOR_JS
# and tests/test_archetype_lint._SWEEP_JS. Returns, for every painted leaf, its
# box + a coarse kind:
#   * 'text'  — an element with its own (non-empty) text and no element children;
#               carries text, fontPx, weight, its own chip fill flag, effective alpha.
#   * 'photo' — an <img> or any element whose background paints a url() image;
#               carries the object-position focus as (ox, oy) fractions.
#   * 'mark'  — a painted, text-less mark: a solid chip fill, a gradient/SVG
#               decoration, or a bordered rule. Badges, accent geometry, rules.
# All coordinates are CSS px in the viewport; deterministic given the fixed
# Chromium build + self-hosted fonts the render already pins.
MEASURE_JS = r"""
() => {
  const W = window.innerWidth, H = window.innerHeight;
  const boxes = [];
  const pctOf = (s, d) => {
    if (!s) return d;
    s = s.trim().toLowerCase();
    if (s.endsWith('%')) { const v = parseFloat(s); return isNaN(v) ? d : Math.max(0, Math.min(1, v / 100)); }
    if (s === 'left' || s === 'top') return 0;
    if (s === 'right' || s === 'bottom') return 1;
    if (s === 'center') return 0.5;
    const px = parseFloat(s);
    return isNaN(px) ? d : px;  // raw px object-position is rare; kept as-is
  };
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const tag = el.tagName.toLowerCase();
    const bg = cs.backgroundImage || 'none';
    const isImg = tag === 'img' || /url\(/i.test(bg);
    const isGradient = /gradient\(/i.test(bg);
    const bgFill = !!(cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && bg === 'none');
    // effective alpha = element opacity × text-colour alpha (a faint watermark
    // is low and drops out of collision detection, matching the F3 lint).
    let colorA = 1;
    const cm = (cs.color || '').match(/rgba?\(([^)]+)\)/);
    if (cm) { const p = cm[1].split(','); if (p.length === 4) colorA = parseFloat(p[3]); }
    const eff = parseFloat(cs.opacity) * colorA;

    // An <svg> root is a single decorative mark (its <path> children carry no
    // background fill so they are skipped below); capture it and move on.
    if (tag === 'svg') {
      boxes.push({ kind: 'mark', x: r.x, y: r.y, w: r.width, h: r.height, gradient: true, fill: false });
      continue;
    }

    // A url()-image element is a photo well; record the crop focus.
    if (isImg) {
      const op = (cs.objectPosition || '').split(/\s+/).filter(Boolean);
      const ox = pctOf(op[0], 0.5);
      const oy = pctOf(op[1], 0.5);
      boxes.push({ kind: 'photo', x: r.x, y: r.y, w: r.width, h: r.height, ox: ox, oy: oy });
      continue;
    }

    let direct = '';
    for (const n of el.childNodes) if (n.nodeType === 3) direct += n.textContent;
    direct = direct.replace(/\s+/g, ' ').trim();
    const hasChild = el.children.length > 0;

    if (direct && !hasChild) {
      boxes.push({
        kind: 'text', x: r.x, y: r.y, w: r.width, h: r.height,
        text: direct, fontPx: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight) || 400,
        bgFill: bgFill, eff: eff,
      });
      continue;
    }

    // A painted, text-less leaf: solid chip, gradient/border decoration, rule.
    const hasBorder = cs.borderStyle && cs.borderStyle !== 'none' && parseFloat(cs.borderTopWidth || '0') > 0;
    if (!direct && !hasChild && (bgFill || isGradient || hasBorder)) {
      if (r.width >= 6 && r.height >= 6) {
        boxes.push({ kind: 'mark', x: r.x, y: r.y, w: r.width, h: r.height, gradient: isGradient, fill: bgFill });
      }
    }
  }
  return { W: W, H: H, boxes: boxes };
}
"""


# --------------------------------------------------------------------------- #
# The energy terms (pure maths over a measured geometry dict)
# --------------------------------------------------------------------------- #

# Weights for the soft terms (the hard text-text overlap gate is separate). Hand
# tuned so no single term dominates; whitespace + balance carry the most weight
# because breathing room and a settled centre are what read as "designed".
_WEIGHTS = {
    "whitespace": 0.28,
    "balance": 0.26,
    "alignment": 0.20,
    "clearance": 0.16,  # small badges/marks off the words
    "saliency": 0.10,  # photo focus in frame & unoccluded
}

# Per-archetype macro-whitespace band (fraction of canvas NOT covered by text +
# marks — the photo well is excluded, since a full-bleed photo is not clutter).
# A card wants to breathe: too dense reads busy, too empty reads unfinished. The
# default band suits most portrait cards; dense/quiet archetypes can override.
_DEFAULT_WHITESPACE_BAND = (0.45, 0.78)
_WHITESPACE_BANDS: dict[str, tuple[float, float]] = {
    # A stat-dense recap legitimately fills more of the canvas.
    "stat_stack_recap": (0.35, 0.70),
    "data_grid_recap": (0.35, 0.70),
    # A quiet spotlight wants generous negative space.
    "centered_medal_spotlight": (0.55, 0.85),
    "spotlight_disc": (0.55, 0.85),
    "quote_led_recap": (0.52, 0.84),
}

# Two boxes "gross-overlap" when the intersection covers more than this fraction
# of the smaller box — the same threshold the F3 archetype lint uses, so F6 and
# the lint agree on what a real collision is.
_OVERLAP_FRAC = 0.55

# A word is substantial, opaque, non-chip text — a real content word, not a
# faint watermark, a badge pill, or a punctuation / numeral fragment.
_WORD_RE = re.compile(r"[A-Za-z0-9]")
_MIN_WORD_CHARS = 3
_MIN_WORD_ALPHA = 0.4

# Edges align when within this many CSS px — a soft grid tolerance.
_ALIGN_EPS = 6.0

# A "small" mark (badge / chip) that must stay off the words, as a fraction of
# canvas area; larger marks are background motifs that legitimately underlap.
_SMALL_MARK_FRAC = 0.14

# Only switch away from the director's pack when a sibling beats it by more than
# this, so noise never causes churn and a no-improvement card is byte-identical.
_IMPROVEMENT_EPS = 1e-3


def _is_word(b: dict) -> bool:
    if b.get("kind") != "text":
        return False
    if b.get("bgFill"):
        return False
    if float(b.get("eff", 1.0)) < _MIN_WORD_ALPHA:
        return False
    text = str(b.get("text", ""))
    return len(re.sub(r"\s", "", text)) >= _MIN_WORD_CHARS and bool(_WORD_RE.search(text))


def _overlap_area(a: dict, b: dict) -> float:
    ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy


def _gross_overlap(a: dict, b: dict, frac: float = _OVERLAP_FRAC) -> bool:
    inter = _overlap_area(a, b)
    if inter <= 0:
        return False
    smaller = max(1.0, min(a["w"] * a["h"], b["w"] * b["h"]))
    return inter / smaller > frac


def _has_text_collision(boxes: list[dict]) -> bool:
    """True when two substantial words gross-overlap — an unambiguous break."""
    words = [b for b in boxes if _is_word(b)]
    for i in range(len(words)):
        for j in range(i + 1, len(words)):
            if _gross_overlap(words[i], words[j]):
                return True
    return False


def _coverage_fraction(boxes: list[dict], W: float, H: float) -> float:
    """Fraction of the canvas covered by the given boxes (rasterised union).

    A coarse fixed grid (canvas / 12 per axis) makes this a deterministic union
    area — no double counting where boxes overlap — cheap for the < ~40 boxes a
    card carries.
    """
    if W < 1 or H < 1 or not boxes:
        return 0.0
    gw = max(1, int(round(W / 12)))
    gh = max(1, int(round(H / 12)))
    cell_w = W / gw
    cell_h = H / gh
    covered = bytearray(gw * gh)
    for b in boxes:
        x0 = max(0, int((b["x"]) / cell_w))
        y0 = max(0, int((b["y"]) / cell_h))
        x1 = min(gw - 1, int((b["x"] + b["w"] - 1e-6) / cell_w))
        y1 = min(gh - 1, int((b["y"] + b["h"] - 1e-6) / cell_h))
        if x1 < 0 or y1 < 0 or x0 >= gw or y0 >= gh:
            continue
        for gy in range(y0, y1 + 1):
            row = gy * gw
            for gx in range(x0, x1 + 1):
                covered[row + gx] = 1
    return sum(covered) / float(gw * gh)


def _whitespace_score(boxes: list[dict], W: float, H: float, archetype: Optional[str]) -> float:
    """Reward macro whitespace inside the archetype's band (text + marks only)."""
    content = [b for b in boxes if b.get("kind") in ("text", "mark")]
    coverage = _coverage_fraction(content, W, H)
    whitespace = 1.0 - coverage
    lo, hi = _WHITESPACE_BANDS.get(str(archetype or ""), _DEFAULT_WHITESPACE_BAND)
    if lo <= whitespace <= hi:
        return 1.0
    # Linear falloff outside the band, normalised by a 0.30-wide runway so a
    # small miss barely dents the score and a wild miss zeroes it.
    dist = (lo - whitespace) if whitespace < lo else (whitespace - hi)
    return max(0.0, 1.0 - dist / 0.30)


def _weighted_centroid(boxes: list[dict], W: float, H: float) -> Optional[tuple[float, float]]:
    """Importance-weighted centroid of the text, as canvas fractions in [0,1].

    Importance = box area × font size × (1.0 for a real word else 0.4), so the
    headline and result pull the centre far harder than a meta label — the same
    "important elements dominate balance" intuition as the saliency centroid.
    """
    num_x = num_y = denom = 0.0
    for b in boxes:
        if b.get("kind") != "text":
            continue
        area = float(b["w"]) * float(b["h"])
        font = float(b.get("fontPx", 10.0)) or 10.0
        w = area * font * (1.0 if _is_word(b) else 0.4)
        if w <= 0:
            continue
        cx = float(b["x"]) + float(b["w"]) / 2.0
        cy = float(b["y"]) + float(b["h"]) / 2.0
        num_x += w * cx
        num_y += w * cy
        denom += w
    if denom <= 0:
        return None
    return (num_x / denom / W, num_y / denom / H)


def _balance_score(boxes: list[dict], W: float, H: float) -> float:
    """Reward the text centroid sitting near the centre OR a rule-of-thirds line.

    A settled composition is either centred or intentionally thirds-placed; the
    worst place is drifting between the two. Distance is the min of "to centre"
    and "to the nearest thirds intersection", normalised by the half-diagonal.
    """
    c = _weighted_centroid(boxes, W, H)
    if c is None:
        return 0.5  # no text to balance — neutral
    cx, cy = c
    thirds = (1.0 / 3.0, 2.0 / 3.0)
    targets = [(0.5, 0.5)] + [(tx, ty) for tx in thirds for ty in thirds]
    best = min(((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5 for tx, ty in targets)
    # Half-diagonal of the unit square ≈ 0.707 is the worst reachable distance.
    return max(0.0, 1.0 - best / 0.5)


def _alignment_score(boxes: list[dict], W: float) -> float:
    """Reward shared vertical edges among text boxes (a grid-aligned feel).

    Counts left / right / centre-x edges shared within a few px across text
    boxes; more shared edges → a tidier column structure. Normalised so a
    handful of alignments saturates the term.
    """
    texts = [b for b in boxes if b.get("kind") == "text"]
    if len(texts) < 2:
        return 0.5
    edges: list[float] = []
    for b in texts:
        edges.append(float(b["x"]))
        edges.append(float(b["x"]) + float(b["w"]))
        edges.append(float(b["x"]) + float(b["w"]) / 2.0)
    edges.sort()
    shared = 0
    for i in range(len(edges) - 1):
        if edges[i + 1] - edges[i] <= _ALIGN_EPS:
            shared += 1
    # Saturate at ~ len(texts) shared edges: a clean layout aligns most boxes.
    return min(1.0, shared / float(max(1, len(texts))))


def _clearance_score(boxes: list[dict], W: float, H: float) -> float:
    """Penalise small badges / chips landing on the words (soft, not a gate).

    A large background motif under a headline is fine (text on top); a small
    opaque chip covering a word is not. Sums the (word ∩ small-mark) area and
    maps it to [0,1] — clean → 1.0.
    """
    words = [b for b in boxes if _is_word(b)]
    if not words:
        return 1.0
    canvas = max(1.0, W * H)
    small_marks = [
        m
        for m in boxes
        if m.get("kind") == "mark" and (float(m["w"]) * float(m["h"])) <= _SMALL_MARK_FRAC * canvas
    ]
    if not small_marks:
        return 1.0
    bad = 0.0
    for w in words:
        for m in small_marks:
            bad += _overlap_area(w, m)
    # 5% of the canvas worth of word-on-badge overlap zeroes the term.
    return max(0.0, 1.0 - (bad / canvas) / 0.05)


def _saliency_score(boxes: list[dict], W: float, H: float) -> float:
    """Reward the photo's focal point being in frame and clear of the words.

    The crop focus was chosen deterministically upstream (saliency →
    object-position) and is read straight back off the rendered photo box. A
    focus that sits inside the frame and is not covered by a substantial word
    scores 1.0; a focus pushed to the edge or buried under a headline is
    penalised. Neutral (0.5) when the card carries no photo.
    """
    photos = [b for b in boxes if b.get("kind") == "photo"]
    if not photos:
        return 0.5
    words = [b for b in boxes if _is_word(b)]
    best = 0.0
    for p in photos:
        fx = float(p["x"]) + float(p.get("ox", 0.5)) * float(p["w"])
        fy = float(p["y"]) + float(p.get("oy", 0.5)) * float(p["h"])
        # In-frame margin: reward a focus comfortably inside the canvas.
        mx = min(fx, W - fx) / (W / 2.0) if W > 0 else 0.0
        my = min(fy, H - fy) / (H / 2.0) if H > 0 else 0.0
        in_frame = max(0.0, min(1.0, min(mx, my)))
        # Occlusion: is the focus point under a substantial word?
        occluded = any(
            (w["x"] <= fx <= w["x"] + w["w"] and w["y"] <= fy <= w["y"] + w["h"]) for w in words
        )
        s = in_frame * (0.4 if occluded else 1.0)
        best = max(best, s)
    return best


def score_geometry(geom: dict, *, archetype: Optional[str] = None) -> dict:
    """Score one candidate's measured geometry. Higher total = better layout.

    Returns a JSON-serialisable record: the per-term scores, the weighted
    ``total`` in [0,1], and ``disqualified`` / ``reason`` when a hard gate
    (text-on-text collision) fires. A disqualified candidate carries
    ``total = 0.0`` and is never chosen unless *every* candidate is disqualified.
    """
    boxes = list(geom.get("boxes") or [])
    W = float(geom.get("W") or 0.0)
    H = float(geom.get("H") or 0.0)

    # A degenerate / malformed geometry (no canvas) can't be scored — disqualify
    # it so a single bad candidate is skipped rather than raising and killing the
    # whole scoring pass (which would silently degrade every card to its current
    # pack). Defensive: real measurements always carry the viewport size.
    if W < 1 or H < 1:
        return {"disqualified": True, "reason": "degenerate canvas", "total": 0.0, "terms": {}}

    if _has_text_collision(boxes):
        return {
            "disqualified": True,
            "reason": "text-text overlap",
            "total": 0.0,
            "terms": {},
        }

    terms = {
        "whitespace": _whitespace_score(boxes, W, H, archetype),
        "balance": _balance_score(boxes, W, H),
        "alignment": _alignment_score(boxes, W),
        "clearance": _clearance_score(boxes, W, H),
        "saliency": _saliency_score(boxes, W, H),
    }
    total = sum(_WEIGHTS[k] * terms[k] for k in _WEIGHTS)
    return {
        "disqualified": False,
        "reason": "",
        "total": round(total, 6),
        "terms": {k: round(v, 6) for k, v in terms.items()},
    }


def choose(
    candidates: list[tuple[str, Optional[dict]]],
    *,
    archetype: Optional[str] = None,
    current_id: Optional[str] = None,
) -> dict:
    """Pick the best pack among measured candidates. Candidate #0 is the current.

    ``candidates`` is an ordered list of ``(pack_id, geometry-or-None)`` — the
    director's current pack first, then the seeded walk. A ``None`` geometry (a
    candidate whose measurement failed) is scored as disqualified and skipped.

    Returns a record: ``winner`` (a pack id — always one of the candidates, and
    the current pack unless a sibling beats it by > _IMPROVEMENT_EPS),
    ``changed`` (whether it differs from the current), ``current`` id, and the
    per-candidate score breakdown for the explainability sidecar. Degrades to
    the current pack when the input is empty or every candidate collides, so the
    result is never worse than the pre-F6 pick.
    """
    if not candidates:
        return {
            "winner": current_id or "",
            "current": current_id or "",
            "changed": False,
            "candidates": [],
        }
    if current_id is None:
        current_id = candidates[0][0]

    scored: list[dict] = []
    for pack_id, geom in candidates:
        if geom is None:
            rec = {"disqualified": True, "reason": "measure failed", "total": 0.0, "terms": {}}
        else:
            rec = score_geometry(geom, archetype=archetype)
        scored.append({"pack": pack_id, **rec})

    # The current pack's score (candidate #0). It anchors the "only switch on a
    # real improvement" rule and wins every tie.
    current_score = scored[0]["total"] if not scored[0].get("disqualified") else -1.0

    winner = current_id
    winner_total = current_score
    for cand in scored[1:]:
        if cand.get("disqualified"):
            continue
        if cand["total"] > winner_total + _IMPROVEMENT_EPS:
            winner = cand["pack"]
            winner_total = cand["total"]

    # If the current pack was itself disqualified, fall back to the best
    # non-disqualified sibling (a collision beats no collision), else keep it.
    if current_score < 0:
        for cand in scored:
            if not cand.get("disqualified") and cand["total"] > winner_total:
                winner = cand["pack"]
                winner_total = cand["total"]

    return {
        "winner": winner,
        "current": current_id,
        "changed": winner != current_id,
        "winner_total": round(winner_total, 6) if winner_total >= 0 else None,
        "candidates": scored,
    }
