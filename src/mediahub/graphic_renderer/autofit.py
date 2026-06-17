"""Deterministic text auto-fit for the graphic renderer (Tier A layout intelligence).

Pure layout maths — **no network, no LLM, no judgement**. Given a string and a
box, :func:`fit_font_px` binary-searches the largest integer pixel font size at
which the text (wrapped to the box width) fits inside ``box_w x box_h``.

Why this exists
---------------
MediaHub's archetype templates must absorb wildly variable content — a 3-letter
relay tag vs. a 28-character double-barrelled surname — without overflowing or
under-filling their slots. Auto-fit is the deterministic primitive that lets a
single archetype hold any name gracefully (the "auto-fit text" item in the
generative-AI thesis, Tier A / Phase 1). This is layout *maths*, not creative
judgement, so it deliberately lives outside ``media_ai.llm`` / ``ai_core.llm``.

Measurement strategy (deterministic by construction)
----------------------------------------------------
* **Primary — char-width table.** Each glyph has an *advance width* expressed as
  a fraction of the em (the font size). The width of a line at size ``S`` is
  ``sum(em_width[c] for c in line) * S``. The base table is the Helvetica/Arial
  AFM advance-width set; per-family classes (condensed / serif / mono) scale or
  override it. This needs **no font files**, so results are identical on every
  machine — which is exactly what makes :func:`fit_font_px` reproducible and
  golden-testable.
* **Optional — Pillow.** When a caller has the real ``.ttf``/``.otf`` and passes
  ``font_path`` to :func:`measure_line_px`, Pillow's :class:`~PIL.ImageFont`
  measures the true advance width (``getlength``; ``getbbox`` width as a fallback
  on very old Pillow). Still deterministic for a given file — used for
  pixel-accurate fitting where the font ships with the deployment.

The table is an **approximation, by design**: it models advance widths plus
**kerning-pair corrections and common f-ligatures** (G1.11) but not optical
sizing or complex-script shaping. Those two corrections only ever make a
measured line *narrower* — real type sets pairs like ``VA``/``To``/``W.`` and
ligatures like ``fi``/``ffl`` tighter than the bare advance sum — and they are
kept deliberately *conservative* (smaller in magnitude than a real face's
kerning), so the estimate stays a safe upper bound on the rendered width. A
global cap (``_MAX_TIGHTEN_FRACTION``) bounds the total tightening so no
pathological all-kerning string can collapse the estimate below reality. For
Latin display/headline text in fixed-width boxes the result is accurate to
within a couple of percent — and still errs slightly *wide* (via the
unlisted-glyph default and the conservative corrections), so it prefers a
smaller, safe size over an overflowing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

__all__ = [
    "fit_font_px",
    "fit_text",
    "wrap_text",
    "measure_line_px",
    "em_width",
    "kern_ligature_em",
    # Variable-font axis optimisation (G1.9)
    "FontAxes",
    "AxisPlan",
    "font_axes_for",
    "optimise_axes",
    "axis_css",
]

# --------------------------------------------------------------------------- #
# Char-width table
# --------------------------------------------------------------------------- #
# Helvetica / Arial advance widths in 1/1000 em (the standard AFM WidthsArray).
# These are *advance* widths (pen movement), which is what governs how wide a
# run of text is — not the ink bounding box.
_AFM_1000: dict[str, int] = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 222,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    "0": 556,
    "1": 556,
    "2": 556,
    "3": 556,
    "4": 556,
    "5": 556,
    "6": 556,
    "7": 556,
    "8": 556,
    "9": 556,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 1015,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 278,
    "\\": 278,
    "]": 278,
    "^": 469,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
    "{": 334,
    "|": 260,
    "}": 334,
    "~": 584,
}

# Base profile in em units (fraction of font size).
_SANS_EM: dict[str, float] = {ch: w / 1000.0 for ch, w in _AFM_1000.items()}

# Advance for any glyph not in the table (accented Latin, punctuation we did not
# enumerate, non-Latin). Sits at the typical lowercase width so unusual names
# such as "Müller" or "Núñez" estimate sensibly; errs marginally wide for safety.
_DEFAULT_EM = 0.556

# Monospace: every glyph advances by one fixed width.
_MONO_EM = 0.600

# Per-class multipliers applied on top of the sans base table. The "mono" class
# is handled separately in _char_em (fixed advance) and so has no entry here.
#   condensed  — Bebas / Oswald are far narrower than Helvetica.
#   serif      — Lora / Georgia run a touch wider than the sans base.
_PROFILE_SCALE: dict[str, float] = {
    "sans": 1.0,
    "condensed": 0.60,
    "serif": 1.03,
}

# Measured per-family overrides on top of the class scale. Anton — the shipped
# v2 headline face — is a HEAVY display condensed: its all-caps advance widths
# run ~10–25% wider than the generic 0.60 condensed estimate (measured against
# layouts/fonts/anton.woff2: realistic caps surnames/events span 0.66–0.75 of
# the unscaled sans table). 0.76 covers the measured worst case with margin, so
# the estimate errs slightly *wide* — a fitted hero line can shrink a touch more
# than strictly needed but can never overflow its box, which is the module's
# contract. Keys are normalised first-family names.
_FAMILY_SCALE: dict[str, float] = {
    "anton": 0.76,
}

# Family-name -> profile class. Names are normalised (lowercased, de-quoted, the
# first family in a CSS stack). Anything unrecognised falls back to "sans".
_CONDENSED_FAMILIES = frozenset(
    {
        "anton",
        "bebas neue",
        "bebas",
        "oswald",
        "impact",
        "teko",
        "archivo narrow",
        "barlow condensed",
        "roboto condensed",
        "saira condensed",
        "fjalla one",
        "staatliches",
        "big shoulders",
        "boldonse",
    }
)
_MONO_FAMILIES = frozenset(
    {
        "monospace",
        "jetbrains mono",
        "ibm plex mono",
        "roboto mono",
        "space mono",
        "dm mono",
        "geist mono",
        "red hat mono",
        "courier",
        "courier new",
        "consolas",
        "menlo",
        "silkscreen",
    }
)
_SERIF_FAMILIES = frozenset(
    {
        "serif",
        "lora",
        "georgia",
        "times",
        "times new roman",
        "playfair display",
        "merriweather",
        "crimson pro",
        "crimson",
        "libre baskerville",
        "instrument serif",
        "ibm plex serif",
        "gloock",
    }
)


def _first_family(font_family: str) -> str:
    """Normalised first family of a CSS-style stack ("'Anton', sans" -> "anton")."""
    if not font_family:
        return ""
    return font_family.split(",", 1)[0].strip().strip("'\"").lower()


def _classify_family(font_family: str) -> str:
    """Map a CSS-style family name (or stack) to a width profile class."""
    first = _first_family(font_family)
    if not first:
        return "sans"
    if first in _MONO_FAMILIES:
        return "mono"
    if first in _CONDENSED_FAMILIES:
        return "condensed"
    if first in _SERIF_FAMILIES:
        return "serif"
    return "sans"


def _table_scale(font_family: str) -> float:
    """Effective sans-table multiplier for a (non-mono) family stack.

    A measured per-family override beats the generic class scale, so faces
    whose real metrics are known (Anton) fit honestly instead of optimistically.
    """
    first = _first_family(font_family)
    override = _FAMILY_SCALE.get(first)
    if override is not None:
        return override
    return _PROFILE_SCALE.get(_classify_family(font_family), 1.0)


# Weight-name -> numeric weight (CSS scale). Bolder faces advance slightly wider.
_WEIGHT_NAMES: dict[str, int] = {
    "thin": 100,
    "hairline": 100,
    "extralight": 200,
    "ultralight": 200,
    "light": 300,
    "book": 400,
    "normal": 400,
    "regular": 400,
    "medium": 500,
    "semibold": 600,
    "demibold": 600,
    "demi": 600,
    "bold": 700,
    "extrabold": 800,
    "ultrabold": 800,
    "black": 900,
    "heavy": 900,
}


def _weight_factor(weight: int | str) -> float:
    """Width multiplier for a font weight. ~+1.2% per 100 units above 400."""
    if isinstance(weight, str):
        numeric = _WEIGHT_NAMES.get(weight.strip().lower(), 400)
    else:
        numeric = int(weight)
    numeric = max(100, min(900, numeric))
    return 1.0 + (numeric - 400) / 100.0 * 0.012


def _char_em(ch: str, profile: str, scale: float) -> float:
    """Advance width of one character in em units."""
    if profile == "mono":
        return _MONO_EM
    return _SANS_EM.get(ch, _DEFAULT_EM) * scale


# --------------------------------------------------------------------------- #
# Kerning + ligature corrections (G1.11) — "truer measured fits"
# --------------------------------------------------------------------------- #
# A bare advance-sum over-states the width of real type: the face's kerning pulls
# diagonal/round/punctuation pairs (``VA``, ``To``, ``W.``) closer, and the
# default ``liga`` feature folds ``fi``/``fl``/``ff`` into a single narrower
# glyph. Both corrections only ever *narrow* the estimate, so they are applied
# in em units (scaled per family) and kept deliberately **conservative** — every
# value is smaller in magnitude than a real face's, so the corrected width stays
# a safe upper bound on the rendered advance (the never-overflow contract). The
# Helvetica/Arial metrics underpinning ``_AFM_1000`` are the source these are
# calibrated against; values are 1/1000 em, all negative (a tightening).

# Kerning pairs (left+right glyph -> 1/1000 em adjustment, always negative).
# Curated from the high-impact Helvetica/Arial pairs that actually occur in
# names, event titles and result lines — caps↔caps display pairs (the dominant
# case for MediaHub's upper-cased hero surnames), caps↔lowercase, and glyph↔
# punctuation (the largest, safest kerns). Pairs not listed contribute nothing.
_KERN_1000: dict[str, int] = {
    # A before tall / round / diagonal caps and its lowercase reflexes.
    "AC": -20,
    "AG": -20,
    "AO": -20,
    "AQ": -20,
    "AU": -20,
    "AT": -55,
    "AV": -65,
    "AW": -45,
    "AY": -65,
    "Av": -25,
    "Aw": -20,
    "Ay": -25,
    # F before A, common lowercase, and the very tight punctuation kerns.
    "FA": -65,
    "Fa": -20,
    "Fe": -10,
    "Fi": -10,
    "Fo": -20,
    "Fr": -10,
    "Fu": -10,
    "F.": -90,
    "F,": -90,
    # L before tall caps / Y and a leading apostrophe.
    "LT": -55,
    "LV": -55,
    "LW": -45,
    "LY": -55,
    "L'": -90,
    # P before A and punctuation.
    "PA": -65,
    "Pa": -10,
    "Pe": -10,
    "Po": -10,
    "P.": -100,
    "P,": -100,
    # R before tall caps.
    "RT": -20,
    "RV": -25,
    "RW": -20,
    "RY": -30,
    # T before caps, lowercase and punctuation (Taylor / Turner / Tomlin …).
    "TA": -65,
    "Ta": -65,
    "Tc": -50,
    "Te": -50,
    "Ti": -15,
    "To": -55,
    "Tr": -45,
    "Ts": -50,
    "Tu": -50,
    "Tw": -45,
    "Ty": -50,
    "T.": -65,
    "T,": -65,
    "T-": -90,
    "T:": -40,
    "T;": -40,
    # V before caps, lowercase and punctuation (Vance / Vega / Vo …).
    "VA": -65,
    "Va": -55,
    "Ve": -45,
    "Vi": -15,
    "Vo": -45,
    "Vr": -35,
    "Vu": -35,
    "Vy": -35,
    "V.": -90,
    "V,": -90,
    "V-": -65,
    "V:": -40,
    # W before caps, lowercase and punctuation (Walsh / Wong / Webb …).
    "WA": -45,
    "Wa": -35,
    "We": -25,
    "Wi": -10,
    "Wo": -35,
    "Wr": -25,
    "Wu": -25,
    "Wy": -20,
    "W.": -65,
    "W,": -65,
    "W-": -40,
    # Y before caps, lowercase and punctuation (Young / Yates / Yeo …).
    "YA": -65,
    "Ya": -65,
    "Ye": -55,
    "Yi": -15,
    "Yo": -65,
    "Yp": -55,
    "Yu": -55,
    "Yv": -55,
    "Y.": -90,
    "Y,": -90,
    "Y-": -85,
    "Y:": -45,
    # Lowercase tails before a full stop / comma (caption sign-offs).
    "r.": -25,
    "r,": -25,
    "v.": -25,
    "v,": -25,
    "w.": -25,
    "w,": -25,
    "y.": -25,
    "y,": -25,
}
_KERN_EM: dict[str, float] = {pair: v / 1000.0 for pair, v in _KERN_1000.items()}

# Common Latin ligatures the browser's default ``liga`` feature folds into one
# glyph, narrower than its parts. Width *saved* in 1/1000 em (negative). Matched
# longest-first (``ffi``/``ffl`` before ``ff``/``fi``/``fl``); lowercase only,
# since a capital ``F`` does not ligate. Savings are conservative — a real face
# usually folds at least this much, so the estimate stays a safe upper bound.
_LIGATURE_1000: dict[str, int] = {
    "ffi": -45,
    "ffl": -45,
    "ff": -25,
    "fi": -18,
    "fl": -18,
}
_LIGATURE_EM: dict[str, float] = {seq: v / 1000.0 for seq, v in _LIGATURE_1000.items()}

# Safety backstop: the net kern+ligature tightening can never remove more than
# this fraction of the raw advance width. Real Latin text tightens ~1–4% (a
# dense all-caps ``AVAW…`` run tops out near this), so on realistic input the
# cap never binds — it exists only so a synthetic worst case cannot collapse the
# estimate below the real rendered width and break the never-overflow contract.
_MAX_TIGHTEN_FRACTION = 0.10


def _kern_ligature_em(text: str, profile: str, scale: float, advance_em: float) -> float:
    """Net width correction (em, ``<= 0``) from kerning pairs + common ligatures.

    Returns ``0.0`` for monospace (fixed advance — no kerning or ligatures) and
    for text shorter than two characters. Ligatures are consumed longest-first so
    ``ffi`` is not double-counted as ``ff`` + ``fi``; kerning is summed over every
    adjacent character pair (the ligature components are absent from the kern
    table, so the two passes never overlap). The result is scaled by the family
    table scale — condensed/serif faces tighten proportionally to their advances
    — then floored at ``-_MAX_TIGHTEN_FRACTION`` of the raw advance width.
    """
    n = len(text)
    if profile == "mono" or n < 2:
        return 0.0
    # Ligatures: longest-match, non-overlapping.
    liga = 0.0
    i = 0
    while i < n - 1:
        seg3 = text[i : i + 3]
        if seg3 in _LIGATURE_EM:
            liga += _LIGATURE_EM[seg3]
            i += 3
            continue
        seg2 = text[i : i + 2]
        if seg2 in _LIGATURE_EM:
            liga += _LIGATURE_EM[seg2]
            i += 2
            continue
        i += 1
    # Kerning: every adjacent pair in the original string.
    kern = 0.0
    for j in range(n - 1):
        kern += _KERN_EM.get(text[j : j + 2], 0.0)
    correction = (liga + kern) * scale
    floor = -advance_em * _MAX_TIGHTEN_FRACTION
    return correction if correction > floor else floor


# --------------------------------------------------------------------------- #
# Public measurement primitives
# --------------------------------------------------------------------------- #
def em_width(text: str, *, font_family: str = "Inter", weight: int | str = 400) -> float:
    """Width of ``text`` in **em units** (multiply by the px size to get px).

    Deterministic and font-file-free: the char-width-table advance sum, made
    *truer* by conservative kerning-pair and common-ligature corrections (G1.11)
    that only ever narrow the line. The corrections satisfy the identity
    ``em_width(t) == raw_advance_em(t) + kern_ligature_em(t)`` and never push the
    estimate below the real rendered width.
    """
    if not text:
        return 0.0
    profile = _classify_family(font_family)
    scale = _table_scale(font_family)
    factor = _weight_factor(weight)
    advance = sum(_char_em(ch, profile, scale) for ch in text)
    correction = _kern_ligature_em(text, profile, scale, advance)
    return (advance + correction) * factor


def kern_ligature_em(text: str, *, font_family: str = "Inter", weight: int | str = 400) -> float:
    """The em width that kerning + ligature folding removes from ``text`` (``<= 0``).

    Explainability handle for the G1.11 correction: ``em_width(t)`` equals the
    bare advance sum **plus** this value (both already including the weight
    factor). ``0.0`` for monospace, empty or single-character input.
    """
    if not text:
        return 0.0
    profile = _classify_family(font_family)
    scale = _table_scale(font_family)
    factor = _weight_factor(weight)
    advance = sum(_char_em(ch, profile, scale) for ch in text)
    return _kern_ligature_em(text, profile, scale, advance) * factor


@lru_cache(maxsize=256)
def _load_truetype(font_path: str, size: int):  # pragma: no cover - thin Pillow shim
    from PIL import ImageFont

    return ImageFont.truetype(font_path, size)


def measure_line_px(
    line: str,
    font_px: float,
    *,
    font_family: str = "Inter",
    weight: int | str = 400,
    font_path: str | None = None,
) -> float:
    """Pixel width of a single (already-wrapped) line at ``font_px``.

    With ``font_path`` and Pillow available, measures the real advance width via
    :class:`~PIL.ImageFont` (``getlength``, falling back to ``getbbox``). Without
    it, uses the deterministic char-width table. ``font_path`` requires an
    integer pixel size, so it is rounded for the Pillow lookup.
    """
    if not line:
        return 0.0
    if font_path:
        font = _load_truetype(font_path, int(round(font_px)))
        get_length = getattr(font, "getlength", None)
        if get_length is not None:
            return float(get_length(line))
        # Very old Pillow: fall back to the ink bounding-box width.
        left, _, right, _ = font.getbbox(line)
        return float(right - left)
    return em_width(line, font_family=font_family, weight=weight) * font_px


# --------------------------------------------------------------------------- #
# Multi-line wrapping
# --------------------------------------------------------------------------- #
def wrap_text(
    text: str,
    box_w: float,
    font_px: float,
    *,
    font_family: str = "Inter",
    weight: int | str = 400,
    font_path: str | None = None,
) -> list[str]:
    """Greedy word-wrap ``text`` to ``box_w`` at ``font_px``.

    Hard newlines in ``text`` are honoured as line breaks. Words are never
    hyphenated: a single token wider than ``box_w`` is placed on its own line and
    will exceed the box — :func:`fit_font_px` resolves that by shrinking the
    size. Returns ``[]`` for empty / whitespace-only input.
    """

    def measure(line: str) -> float:
        return measure_line_px(
            line, font_px, font_family=font_family, weight=weight, font_path=font_path
        )

    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if measure(candidate) <= box_w + 1e-6:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


# --------------------------------------------------------------------------- #
# Auto-fit
# --------------------------------------------------------------------------- #
def fit_font_px(
    text: str,
    box_w: float,
    box_h: float,
    *,
    font_family: str = "Inter",
    weight: int | str = 400,
    min_px: int = 8,
    max_px: int = 240,
    line_height: float = 1.0,
) -> int:
    """Largest **integer** px font size at which ``text`` fits in ``box_w x box_h``.

    The text is word-wrapped to ``box_w`` at the candidate size; it fits when the
    wrapped block height (``n_lines * size * line_height``) is within ``box_h``
    *and* every wrapped line is within ``box_w``. Found by binary search over the
    monotonic fit predicate, so the cost is ``O(log(max_px - min_px))`` wraps.

    Returns ``max_px`` if even the largest size fits, and ``min_px`` (the floor)
    if nothing in range fits — at the floor the caller decides whether to truncate
    or grow the box, but the function never returns a value outside
    ``[min_px, max_px]`` and never lies about fitting.

    ``line_height`` is the CSS-style line-height **multiplier** (e.g. ``1.2``),
    not an absolute pixel value.
    """
    if box_w <= 0 or box_h <= 0:
        raise ValueError("box_w and box_h must be positive")
    if min_px < 1:
        raise ValueError("min_px must be >= 1")
    if min_px > max_px:
        raise ValueError("min_px must be <= max_px")

    if not text or not text.strip():
        return max_px

    def fits(size: int) -> bool:
        lines = wrap_text(text, box_w, size, font_family=font_family, weight=weight)
        if not lines:
            return True
        if len(lines) * size * line_height > box_h + 1e-6:
            return False
        widest = max(
            measure_line_px(ln, size, font_family=font_family, weight=weight) for ln in lines
        )
        return widest <= box_w + 1e-6

    if fits(max_px):
        return max_px
    if not fits(min_px):
        return min_px

    lo, hi, best = min_px, max_px, min_px
    while lo <= hi:
        mid = (lo + hi) // 2
        if fits(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def fit_text(
    text: str,
    box_w: float,
    box_h: float,
    *,
    font_family: str = "Inter",
    weight: int | str = 400,
    min_px: int = 8,
    max_px: int = 240,
    line_height: float = 1.0,
) -> tuple[int, list[str]]:
    """Convenience wrapper: the fitted size **and** the wrapped lines at that size.

    Templates usually need both — the size to set on the element and the line
    breaks to emit. Equivalent to calling :func:`fit_font_px` then
    :func:`wrap_text` with the result, sharing the same measurement.
    """
    size = fit_font_px(
        text,
        box_w,
        box_h,
        font_family=font_family,
        weight=weight,
        min_px=min_px,
        max_px=max_px,
        line_height=line_height,
    )
    lines = wrap_text(text, box_w, size, font_family=font_family, weight=weight)
    return size, lines


# --------------------------------------------------------------------------- #
# Variable-font axis optimisation (G1.9)
# --------------------------------------------------------------------------- #
# The self-hosted renderer fonts that ship a genuine variable woff2 expose
# continuous axes (each file's ``fvar`` table is verified by
# tests/test_variable_font_axes.py). This region turns an already-fitted text
# slot into the best axis *instance* for that slot — deterministically and
# font-file-free, the same Tier-A layout-maths contract as :func:`fit_font_px`
# above (no network, no LLM, identical output on every machine).
#
# Three axis TYPES are modelled, each applied ONLY where the active face truly
# carries the axis. A static face (or an unknown family) yields an empty plan —
# never a synthesised/faked axis, which the graphic-craft rules forbid:
#   * opsz (optical size) — reported per slot so a caller can pin the optical
#     master to the rendered size (large hero text → display master, small
#     labels → text master). The stylesheet sets ``font-optical-sizing: auto``
#     so the browser applies opsz automatically; the value is surfaced here for
#     explainability and tests.
#   * wght (weight) — the requested weight clamped to the face's range, then
#     traded DOWN toward a legibility floor to recover horizontal width before
#     the caller has to shrink ``px`` — so a long line can stay larger by going
#     a touch lighter.
#   * wdth (width) — condensed toward the face's minimum to recover any width
#     the weight trade could not. No self-hosted face exposes ``wdth`` today, so
#     this is a tested, ready capability that activates automatically for any
#     width-axis variable face added through the fonts workflow — it is never
#     faux-condensation via ``transform: scaleX`` (a visible-stroke defect).


@dataclass(frozen=True)
class FontAxes:
    """The genuine variable axes a face exposes, as inclusive ``(min, max)`` ranges.

    Mirrors the shipped ``layouts/fonts/*.woff2`` ``fvar`` tables (and the
    ``@font-face`` ranges in ``_shared.css``). ``None`` means the face does not
    carry that axis, so :func:`optimise_axes` never emits a setting for it.
    """

    wght: tuple[int, int] | None = None  # CSS weight, 100..900 scale
    opsz: tuple[float, float] | None = None  # optical size, in points
    wdth: tuple[float, float] | None = None  # width, in percent (100 = normal)


# Registry keyed by normalised first-family name. MUST stay in lock-step with
# the ``@font-face`` axis ranges in ``layouts/_shared.css`` and the shipped
# ``layouts/fonts/*.woff2`` fvar tables (tests/test_variable_font_axes.py pins
# both directions). Bebas Neue / Anton / Bowlby One have no variable cut on
# Google Fonts, so they are intentionally absent → an empty (no-op) plan.
_FONT_AXES: dict[str, FontAxes] = {
    "inter": FontAxes(wght=(100, 900), opsz=(14.0, 32.0)),
    "space grotesk": FontAxes(wght=(300, 700)),
    "jetbrains mono": FontAxes(wght=(100, 800)),
}

# How light the weight axis may be traded for fit. Lighter advances narrower,
# but a display/data line must not turn spindly, so the trade stops at this
# floor (or the face's own minimum, whichever is heavier).
_WEIGHT_FIT_FLOOR = 300


@dataclass(frozen=True)
class AxisPlan:
    """The optimised variable-axis instance for one single-line slot.

    The numeric fields are the resolved axis values (``None`` where the face
    lacks the axis). ``css`` is a ready ``font-variation-settings`` value for the
    axes deliberately controlled to make the line fit — the weight trade and any
    width condensation — e.g. ``"'wght' 612"``. It is ``""`` when the slot
    already fits at its requested weight, so a caller can emit
    ``font-variation-settings: <css or 'normal'>`` and a non-tight slot renders
    byte-identically to before. (``opsz`` is delegated to
    ``font-optical-sizing: auto`` and so is *not* folded into ``css``; build a
    full instance string with :func:`axis_css` when you need one.)
    """

    wght: float | None = None
    opsz: float | None = None
    wdth: float | None = None
    css: str = ""


def font_axes_for(font_family: str) -> FontAxes | None:
    """The variable axes the first family of a CSS stack exposes, or ``None``."""
    return _FONT_AXES.get(_first_family(font_family))


def _normalise_weight(weight: int | str) -> int:
    """A weight name or number → an int clamped to the CSS 100..900 scale."""
    if isinstance(weight, str):
        numeric = _WEIGHT_NAMES.get(weight.strip().lower(), 400)
    else:
        numeric = int(weight)
    return max(100, min(900, numeric))


def _fmt_axis(value: float) -> str:
    """Axis value as a CSS number: integral values drop the ``.0``, else 1 dp."""
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return str(int(rounded))
    return f"{value:.1f}"


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into ``[lo, hi]`` (lo wins if the range is inverted)."""
    return max(lo, min(hi, value))


def axis_css(
    *, wght: float | None = None, wdth: float | None = None, opsz: float | None = None
) -> str:
    """Format a CSS ``font-variation-settings`` value from axis values.

    Tags are emitted in the canonical ``wght, wdth, opsz`` order; ``None`` axes
    are skipped. Returns ``""`` when nothing is set, so a caller can fall back to
    ``normal``.
    """
    parts: list[str] = []
    if wght is not None:
        parts.append(f"'wght' {_fmt_axis(wght)}")
    if wdth is not None:
        parts.append(f"'wdth' {_fmt_axis(wdth)}")
    if opsz is not None:
        parts.append(f"'opsz' {_fmt_axis(opsz)}")
    return ", ".join(parts)


def _heaviest_weight_within(base: float, floor: float, target_factor: float) -> float:
    """Heaviest weight in ``[floor, base]`` whose width factor ≤ ``target_factor``.

    Width scales with :func:`_weight_factor` (``1 + (w-400)/100 * 0.012``), which
    is monotonic in ``w``. We want the *boldest* weight that still fits, so the
    line stays as heavy as possible while not overflowing. Returns ``floor`` when
    even the floor is too heavy.
    """
    # Solve _weight_factor(w) <= target_factor for w:
    #   1 + (w - 400) * 0.00012 <= target_factor
    bound = 400.0 + (target_factor - 1.0) / 0.00012
    w = min(base, bound)
    return float(max(floor, min(base, w)))


def optimise_axes(
    text: str,
    box_w: float,
    *,
    font_family: str = "Inter",
    weight: int | str = 400,
    fitted_px: float,
) -> AxisPlan:
    """Best variable-axis instance for a single-line slot — deterministic.

    Given the already-:func:`fit_font_px`-chosen ``fitted_px`` and the slot width
    ``box_w``, return the axis tuple to set on the slot:

    * ``opsz`` is matched to ``fitted_px`` (clamped to the face's optical range);
    * ``wght`` starts at the requested ``weight`` clamped to the face's range and
      — only if the line would overflow ``box_w`` — is traded down toward
      ``_WEIGHT_FIT_FLOOR`` to recover width;
    * ``wdth`` (where the face has it) is then condensed toward its minimum to
      recover any residual overflow.

    ``css`` deviates from ``""`` only when a fit-recovering move was made, so a
    slot that already fits renders unchanged. Faces with no variable axes (the
    static display faces, unknown families) return an empty plan.
    """
    axes = font_axes_for(font_family)
    if axes is None:
        return AxisPlan()

    numeric_weight = _normalise_weight(weight)

    # opsz — match the optical master to the rendered size (reported; applied by
    # font-optical-sizing: auto in the stylesheet).
    opsz: float | None = None
    if axes.opsz is not None and fitted_px > 0:
        opsz = round(_clamp(float(fitted_px), axes.opsz[0], axes.opsz[1]), 1)

    # wght — requested weight, clamped to the axis.
    wght: float | None = None
    if axes.wght is not None:
        wght = float(_clamp(float(numeric_weight), axes.wght[0], axes.wght[1]))

    wdth: float | None = None
    deviated = False
    if text and text.strip() and fitted_px > 0 and box_w > 0:
        eff_weight = int(wght) if wght is not None else numeric_weight
        measured = em_width(text, font_family=font_family, weight=eff_weight) * fitted_px
        if measured > box_w + 1e-6:
            ratio = box_w / measured  # < 1: the width factor we must reach
            # 1) trade weight down toward the floor (lighter advances narrower).
            if axes.wght is not None and wght is not None:
                floor = max(float(axes.wght[0]), float(_WEIGHT_FIT_FLOOR))
                if wght > floor:
                    target_factor = _weight_factor(eff_weight) * ratio
                    lighter = _heaviest_weight_within(wght, floor, target_factor)
                    lighter = round(lighter)
                    if lighter < wght:
                        wght = float(lighter)
                        deviated = True
                        measured = (
                            em_width(text, font_family=font_family, weight=int(wght)) * fitted_px
                        )
                        ratio = box_w / measured if measured > 0 else 1.0
            # 2) condense width toward the face minimum for any residual overflow.
            if axes.wdth is not None and ratio < 1.0 - 1e-6:
                wdth = round(_clamp(100.0 * ratio, axes.wdth[0], min(100.0, axes.wdth[1])), 1)
                deviated = True

    css = axis_css(wght=wght, wdth=wdth) if deviated else ""
    return AxisPlan(wght=wght, opsz=opsz, wdth=wdth, css=css)
