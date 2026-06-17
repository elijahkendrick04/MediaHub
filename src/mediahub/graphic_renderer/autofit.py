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

from functools import lru_cache

__all__ = [
    "fit_font_px",
    "fit_text",
    "wrap_text",
    "measure_line_px",
    "em_width",
    "kern_ligature_em",
    "balance_lines",
    "fit_balanced",
    "fit_balanced_px",
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
# Balanced multi-line fitting (G1.12)
# --------------------------------------------------------------------------- #
# The fitters above shrink a long *atomic* headline — a double-barrelled surname
# ("WOLAJIMI-ABUBAKARI") or a split-time result ("1:45.23 / 50.12") — until the
# whole run fits a single forced line, which can drive a hero name/numeral down
# to a thin strip. Balanced fitting instead BREAKS such a value at its natural
# seams (spaces, hyphens, the split slash) into a small number of lines whose
# widths are as even as possible, then sizes to the widest of those lines.
#
# Fewer-but-wider vs more-but-shorter lines is a real trade-off — more lines
# relax the width bound but tighten the height bound — so the fitter evaluates
# each line count and keeps whichever yields the LARGEST size, ties preferring
# fewer lines. One line is always a candidate, so the result is never smaller
# than (and for an unbreakable token, identical to) the single-line fit. Line
# widths reuse :func:`em_width`, so the G1.11 kerning/ligature correction flows
# through for free. Like the rest of this module it is pure, deterministic
# layout maths — no judgement.

import re as _re

# A zero-width break *after* a hyphen: "SMITH-JOHNSON" -> "SMITH-", "JOHNSON".
# The hyphen stays on the left piece, the way real hyphenation signals that the
# word continues on the next line.
_HYPHEN_BREAK_RE = _re.compile(r"(?<=-)(?=.)")
# A slash optionally padded by spaces — the separator between split / relay
# times ("1:45.23 / 50.12", "49.81/50.12/51.04").
_SLASH_SEP_RE = _re.compile(r"\s*/\s*")


def _hero_units(text: str, mode: str) -> list[tuple[str, str]]:
    """Tokenise ``text`` into ordered ``(glyphs, glue)`` break units.

    ``glue`` is what renders *before* a unit when it shares a line with its
    predecessor, and is dropped when a line break falls before it — so a space
    or slash separator vanishes cleanly at a wrap while a hyphen (part of the
    glyphs, never the glue) stays visible at the line end. The first unit always
    carries glue ``""``: it can only begin a line.

    * ``mode="name"`` breaks at whitespace (glue ``" "``) and after hyphens
      (glue ``""``) — compound and double-barrelled surnames.
    * ``mode="split"`` breaks at the time-split slash (glue ``" / "``).
    """
    text = (text or "").strip()
    if not text:
        return []
    if mode == "split":
        parts = [p for p in _SLASH_SEP_RE.split(text) if p]
        return [(p, "" if i == 0 else " / ") for i, p in enumerate(parts)]
    units: list[tuple[str, str]] = []
    for word in text.split():
        pieces = [p for p in _HYPHEN_BREAK_RE.split(word) if p]
        for j, piece in enumerate(pieces):
            units.append((piece, " " if (units and j == 0) else ""))
    return units


def _join_units(units: list[tuple[str, str]]) -> str:
    """Reconstruct the line a slice of units renders as (its first glue drops)."""
    if not units:
        return ""
    out = units[0][0]
    for glyphs, glue in units[1:]:
        out += glue + glyphs
    return out


def _balanced_spans(units, n_lines, measure) -> list[tuple[int, int]]:
    """``[(start, end), …]`` splitting ``units`` into ``n_lines`` contiguous
    groups whose widest line (per ``measure(a, b)``) is minimal — the balanced
    wrap. Exhaustive over the ``C(len-1, n_lines-1)`` cut placements; ``units``
    is a handful of name parts / splits, so this is a few dozen evaluations.
    """
    import itertools

    n = len(units)
    n_lines = max(1, min(n_lines, n))
    if n_lines == 1:
        return [(0, n)]
    best_bounds: tuple[int, ...] | None = None
    best_width: float | None = None
    for cuts in itertools.combinations(range(1, n), n_lines - 1):
        bounds = (0, *cuts, n)
        width = max(measure(bounds[i], bounds[i + 1]) for i in range(n_lines))
        if best_width is None or width < best_width:
            best_width, best_bounds = width, bounds
    assert best_bounds is not None
    return [(best_bounds[i], best_bounds[i + 1]) for i in range(n_lines)]


def balance_lines(
    text: str,
    *,
    n_lines: int = 2,
    font_family: str = "Inter",
    weight: int | str = 400,
    mode: str = "name",
) -> list[str]:
    """Split ``text`` into up to ``n_lines`` width-balanced lines.

    Breaks only at the seams ``mode`` allows (see :func:`_hero_units`) and
    returns the grouping whose lines are as even as possible. Yields at most
    ``min(n_lines, break-units)`` lines (so an unbreakable token stays one
    line), and ``[]`` for empty / whitespace-only input. The lines always
    re-join to the original text.
    """
    units = _hero_units(text, mode)
    if not units:
        return []

    def measure(a: int, b: int) -> float:
        return em_width(_join_units(units[a:b]), font_family=font_family, weight=weight)

    return [_join_units(units[a:b]) for a, b in _balanced_spans(units, n_lines, measure)]


def fit_balanced(
    text: str,
    box_w: float,
    box_h: float,
    *,
    max_lines: int = 2,
    font_family: str = "Inter",
    weight: int | str = 400,
    min_px: int = 8,
    max_px: int = 240,
    line_height: float = 1.0,
    mode: str = "name",
) -> tuple[int, list[str]]:
    """Largest **integer** px — and the line layout — at which ``text`` fits in
    ``box_w x box_h`` when balanced across ``1..max_lines`` lines.

    For each candidate line count the value is balanced (:func:`balance_lines`)
    and sized to the tighter of its width bound (widest line ≤ ``box_w``) and
    height bound (``n * size * line_height`` ≤ ``box_h``); the count giving the
    biggest size wins, ties preferring fewer lines. Because one line is always
    a candidate, the size is never smaller than the single-line
    :func:`fit_font_px` result, and for an unbreakable token it is identical.

    Returns ``(size, lines)`` — the size to set and the balanced lines to emit
    (joined with ``<br>`` by the caller). ``line_height`` is the CSS multiplier,
    as in :func:`fit_font_px`. Geometry/bounds errors raise like
    :func:`fit_font_px`.
    """
    if box_w <= 0 or box_h <= 0:
        raise ValueError("box_w and box_h must be positive")
    if min_px < 1:
        raise ValueError("min_px must be >= 1")
    if min_px > max_px:
        raise ValueError("min_px must be <= max_px")

    units = _hero_units(text, mode)
    if not units:
        return max_px, []

    def measure(a: int, b: int) -> float:
        return em_width(_join_units(units[a:b]), font_family=font_family, weight=weight)

    best_size, best_lines = -1, [_join_units(units)]
    for k in range(1, min(max_lines, len(units)) + 1):
        spans = _balanced_spans(units, k, measure)
        widest = max((measure(a, b) for a, b in spans), default=0.0)
        if widest <= 0:
            continue
        # Clamp to [min_px, max_px] BEFORE comparing line counts, so once two
        # layouts both reach the cap the earlier (fewer-line) one wins — a name
        # that already fits one line at the cap is never split needlessly.
        size = max(min_px, min(max_px, int(min(box_w / widest, box_h / (k * line_height)))))
        if size > best_size:
            best_size = size
            best_lines = [_join_units(units[a:b]) for a, b in spans]
    if best_size < 0:  # no measurable unit (defensive; non-empty units always size)
        return max_px, [_join_units(units)]
    return best_size, best_lines


def fit_balanced_px(text: str, box_w: float, box_h: float, **kwargs) -> int:
    """The fitted size from :func:`fit_balanced`, dropping the line layout."""
    return fit_balanced(text, box_w, box_h, **kwargs)[0]
