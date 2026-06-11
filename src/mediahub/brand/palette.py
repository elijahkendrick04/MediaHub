"""brand/palette.py — Unified palette resolver across every org input.

The first-run org setup collects colour signals from many places:

  - Website + each social link        (palette_mentions in merged DNA)
  - Brand guidelines document         (palette_mentions in guidelines)
  - Each uploaded logo                (ai_dominant_colours per logo)

Historically only the website's palette mentions made it into the
ClubProfile.brand_palette_extracted dict — colours mentioned in the
brand guidelines doc or sitting in the uploaded logos were silently
ignored. This module fixes that by:

  1. ``gather_colour_sources(...)``  — collect every colour signal,
     labelled by source so the AI can weight them differently.
  2. ``resolve_palette(...)``        — ask the cloud LLM (Gemini /
     Anthropic) to pick the actual brand primary / secondary / accent
     (and optionally a fourth) from ALL signals. Raises
     ``ClaudeUnavailableError`` when no provider is configured — the
     palette pick is a judgement call with no honest non-AI substitute.
  3. ``apply_manual_override(...)``  — if the user supplied a manual
     override on the confirmation form, that wins; the AI only runs
     when the manual override is empty or invalid.

No hardcoded "first 3 hex codes" logic, no regex frequency-ranking
fallback. The LLM reasons about which sources are deliberate
(guidelines doc, logo dominant colours) vs incidental (every CSS hex
on a website) and picks accordingly.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence

log = logging.getLogger(__name__)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Canonical slot names. The first three are mandatory; the fourth is
# opt-in via the confirmation form's tickbox. Code that walks slots
# should iterate ``SLOTS`` rather than reaching for the bare tuple
# literal — a typo like ``"prmary"`` otherwise silently drops a colour.
SLOTS: tuple[str, ...] = ("primary", "secondary", "accent")
FOURTH_SLOT: str = "fourth"
ALL_SLOTS: tuple[str, ...] = SLOTS + (FOURTH_SLOT,)


# ---------------------------------------------------------------------------
# Hex normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_hex(value: str) -> Optional[str]:
    """Normalise a hex string to lowercase #rrggbb. Returns None if invalid."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    if _HEX_RE.match(v):
        return v
    return None


def _is_chromatic(hex_value: str, *, min_chroma: int = 18) -> bool:
    """True if a #rrggbb colour carries real hue (not white/black/grey).

    Chroma here is the spread between the max and min RGB channel — a
    cheap saturation proxy. Pure white (#ffffff), pure black (#000000)
    and any near-grey collapse to ~0 and are rejected; a club's navy,
    gold, red, etc. all clear the threshold comfortably.
    """
    n = _normalise_hex(hex_value)
    if not n:
        return False
    r, g, b = int(n[1:3], 16), int(n[3:5], 16), int(n[5:7], 16)
    return (max(r, g, b) - min(r, g, b)) >= min_chroma


def _clean_hex_list(items) -> list[str]:
    """Coerce a list-like to a clean ordered de-duplicated list of #rrggbb."""
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for h in items:
        v = _normalise_hex(h) if isinstance(h, str) else None
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Source aggregation
# ---------------------------------------------------------------------------


class _SourcesWithUsage(dict):
    """A plain ``dict[str, list[str]]`` of labelled colour sources that
    also carries the raw frequency-ranked usage evidence.

    The visible mapping keeps the historical ``{label: [hex, ...]}`` shape
    so the resolver's colour ``universe`` and every existing caller keep
    working untouched. ``.colour_usage`` holds ``{label: [(hex, count), ...]}``
    for the usage source lines, letting ``_build_llm_prompt`` show the AI
    each colour WITH its usage count — the decisive brand signal.
    """

    # Accept the same call signatures as ``dict`` so the object survives
    # being copied / round-tripped by ``dataclasses.asdict`` (which does
    # ``type(obj)(iterable)``) without ``colour_usage`` being a required
    # arg. When reconstructed that way the usage evidence simply resets
    # to empty — harmless, since the resolver reads it via getattr.
    def __init__(self, *args, usage: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.colour_usage: dict[str, list[tuple[str, int]]] = usage or {}


_USAGE_SUFFIX = " colours by CSS usage"


def _clean_usage_pairs(items) -> list[tuple[str, int]]:
    """Coerce a ``[(hex, count), ...]``-like into clean, ordered pairs.

    Accepts the raw colour-usage evidence (list of ``(hex, count)`` or
    ``[hex, count]``), normalises each hex to ``#rrggbb``, drops invalid
    entries, de-dupes (keeping the first/highest), and preserves the
    incoming order (the evidence map is already frequency-sorted desc).
    """
    if not isinstance(items, (list, tuple)):
        return []
    seen: set[str] = set()
    out: list[tuple[str, int]] = []
    for pair in items:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        hexv = _normalise_hex(pair[0]) if isinstance(pair[0], str) else None
        if not hexv or hexv in seen:
            continue
        try:
            count = int(pair[1])
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        seen.add(hexv)
        out.append((hexv, count))
    return out


def gather_colour_sources(
    *,
    link_palette_signals: Optional[dict] = None,
    brand_guidelines: Optional[dict] = None,
    brand_logos: Optional[list[dict]] = None,
    colour_usage: Optional[dict] = None,
) -> dict[str, list[str]]:
    """Build a labelled mapping of every colour signal collected.

    Returns a dict like:
        {
          "website colours by CSS usage": ["#1f336c", "#2ea3f2", ...],
          "instagram (palette_mentions)": [...],
          "brand_guidelines (palette_mentions)": [...],
          "logo: navy-on-white.svg (dominant)": [...],
          ...
        }

    Order of keys is stable; values are de-duped per source. Empty
    sources are omitted.

    ``colour_usage`` carries the frequency-ranked colour-USAGE evidence
    per platform (``{platform: [(hex, count), ...]}`` from
    ``dna_capture.build_colour_usage_map``). This is the decisive signal:
    colours used MANY times across the full site CSS are far more likely
    to be brand than colours declared once. The raw counts are stashed on
    the returned dict's ``.colour_usage`` attribute so ``_build_llm_prompt``
    can show each colour WITH its count; the visible source lists keep the
    plain ``[hex, ...]`` shape so the universe / existing callers are
    unaffected.
    """
    sources: dict[str, list[str]] = {}
    usage_counts: dict[str, list[tuple[str, int]]] = {}

    if isinstance(colour_usage, dict):
        for platform, pairs in colour_usage.items():
            cleaned = _clean_usage_pairs(pairs)
            if cleaned:
                key = f"{platform}{_USAGE_SUFFIX}"
                sources[key] = [h for h, _ in cleaned]
                usage_counts[key] = cleaned

    if isinstance(link_palette_signals, dict):
        for platform, hexes in link_palette_signals.items():
            cleaned = _clean_hex_list(hexes)
            if cleaned:
                sources[f"{platform} (palette_mentions)"] = cleaned

    if isinstance(brand_guidelines, dict):
        mentioned = _clean_hex_list(brand_guidelines.get("palette_mentions"))
        if mentioned:
            sources["brand_guidelines (palette_mentions)"] = mentioned

    if isinstance(brand_logos, list):
        for logo in brand_logos:
            if not isinstance(logo, dict):
                continue
            cleaned = _clean_hex_list(logo.get("ai_dominant_colours"))
            if not cleaned:
                continue
            label = (
                logo.get("label") or logo.get("original_filename") or logo.get("logo_id") or "logo"
            )
            key = f"logo: {str(label)[:80]} (dominant)"
            if key in sources:
                key = f"logo: {logo.get('logo_id', '')} (dominant)"
            sources[key] = cleaned

    return _SourcesWithUsage(sources, usage=usage_counts)


# ---------------------------------------------------------------------------
# LLM-driven palette decision
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a brand-identity expert. You are given the colour evidence "
    "collected for ONE organisation and you decide which colours form its "
    "actual brand palette (primary, secondary, accent, optionally a "
    "fourth).\n"
    "\n"
    "THE DECISIVE SIGNAL IS USAGE FREQUENCY. Website colours arrive WITH a "
    "usage count, written as `#rrggbb\u00d7N`, where N is how many times that "
    "colour appears across the site's full CSS. A colour used MANY times "
    "(navy used 21 times, a blue used 52 times) is almost certainly a brand "
    "colour. A colour declared only once or twice is almost certainly "
    "incidental and should be ignored.\n"
    "\n"
    "RECOGNISE AND IGNORE GENERIC CMS / PAGE-BUILDER DEFAULT PALETTES. Club "
    "sites are built on WordPress/Gutenberg, Divi, Elementor, Material and "
    "Bootstrap, which inline their stock swatches on every page whether or "
    "not the club uses them. Treat the following as DEFAULTS to ignore "
    "UNLESS the colour is clearly DOMINANT in usage (a high count), in which "
    "case it may genuinely be the brand:\n"
    "  - WordPress/Gutenberg: #cf2e2e #ff6900 #fcb900 #7bdcb5 #00d084 "
    "#8ed1fc #0693e3 #abb8c3 #eb144c #f78da7 #9900ef\n"
    "  - Material: #f44336 #e91e63 #9c27b0 #673ab7 #3f51b5 #2196f3 #03a9f4 "
    "#00bcd4 #009688 #4caf50 #8bc34a #cddc39 #ffeb3b #ffc107 #ff9800 "
    "#ff5722\n"
    "  - Divi: #2ea3f2 #7a00df #4721fb #e02b20 #e09900\n"
    "  - Elementor: #6ec1e4 #61ce70 #f54040 #6c757d\n"
    "  - Bootstrap: #0d6efd #6610f2 #6f42c1 #d63384 #dc3545 #fd7e14 #198754 "
    "#20c997 #0dcaf0\n"
    "\n"
    "OTHER SOURCES. Colours in the brand-guidelines document and the logo "
    "dominant colours are DELIBERATE choices; a colour that appears in BOTH "
    "the high-usage site CSS AND the logo/guidelines is almost certainly the "
    "primary. Prefer picks that are corroborated across sources.\n"
    "\n"
    "RULES. Pick ONLY from the colours supplied below \u2014 never invent a hex "
    "value. Pure white (#ffffff) and pure black (#000000) belong in the "
    "palette only when the brand explicitly uses them as a key colour. "
    "Output lower-case #rrggbb. Return JSON only."
)


def _build_llm_prompt(
    *,
    org_name: str,
    voice_summary: str,
    sources: dict[str, list[str]],
    allow_fourth: bool,
    usage_counts: Optional[dict[str, list[tuple[str, int]]]] = None,
) -> str:
    usage_counts = usage_counts or {}
    lines = [
        f"Organisation: {org_name or '(unnamed)'}",
        f"Voice summary: {voice_summary or '(none)'}",
        "",
        "Colour evidence collected, labelled by source. Website colours are "
        "shown WITH their usage count across the full site CSS as "
        "`#rrggbb\u00d7N` (N = times used) \u2014 higher N means more likely to be "
        "a real brand colour:",
    ]
    if sources:
        for label, hexes in sources.items():
            pairs = usage_counts.get(label)
            if pairs:
                rendered = ", ".join(f"{h}\u00d7{c}" for h, c in pairs[:24])
            else:
                rendered = ", ".join(hexes[:12])
            lines.append(f"  - {label}: " + rendered)
    else:
        lines.append("  (no colour signals collected)")

    lines += [
        "",
        "Return a SINGLE JSON object with EXACTLY these keys:",
        '  primary:   string "#rrggbb" — the organisation\'s main brand colour',
        '  secondary: string "#rrggbb" — their second key brand colour',
        '  accent:    string "#rrggbb" — a complementary brand accent',
    ]
    if allow_fourth:
        lines.append(
            '  fourth:    string "#rrggbb" OR "" — DEFAULT IS "". Most '
            "organisations have two or three brand colours; a genuine "
            "fourth is the exception, not the rule. Set it ONLY when the "
            "evidence is unambiguous — the brand-guidelines document "
            "names a fourth colour, or the same extra colour recurs "
            "across logo + heavy site usage. NEVER fill the slot just "
            "because it exists; a wrong fourth colour is worse than none."
        )
    lines += [
        "  reasoning: short string (<=240 chars) explaining which sources informed each pick",
        "",
        "Guidance:",
        "  - USAGE COUNT IS DECISIVE: colours used MANY times across the site CSS are far more likely to be brand than colours declared only once or twice.",
        "  - RECOGNISE AND IGNORE generic CMS / page-builder DEFAULT palettes (WordPress/Gutenberg, Material, Divi, Elementor, Bootstrap) UNLESS such a colour is clearly DOMINANT in usage here \u2014 then it may genuinely be the brand.",
        "  - Examples of default swatches to ignore unless dominant: WordPress #cf2e2e #ff6900 #fcb900 #00d084 #0693e3 #9900ef; Material #f44336 #e91e63 #9c27b0 #2196f3 #ffeb3b #ff9800; Divi #2ea3f2 #7a00df #4721fb; Elementor #6ec1e4 #61ce70 #f54040; Bootstrap #0d6efd #6610f2 #d63384 #dc3545.",
        "  - Colours mentioned EXPLICITLY in the brand-guidelines document and the logo dominant colours are deliberate; prefer picks corroborated there.",
        "  - If the same colour shows high usage AND appears in the guidelines/logo, it is almost certainly the primary.",
        "  - Pure white (#ffffff) and pure black (#000000) only belong in the chosen palette if the brand explicitly uses them as a key colour.",
        "  - The fourth slot defaults to empty: leave it \"\" unless the evidence for a real fourth brand colour is unambiguous. When in doubt, omit it.",
        "  - Every chosen colour MUST come from the colours above. Do not invent new hex values.",
        "  - All hex values lower-case #rrggbb.",
        "No prose, no fences, no commentary — only the JSON object.",
    ]
    return "\n".join(lines)


def _validate_picks(raw: object, *, allow_fourth: bool, universe: set[str]) -> dict:
    """Coerce the LLM response into a clean palette dict.

    The LLM is instructed not to invent colours; we enforce that here by
    discarding any pick that isn't in the universe of supplied colours.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key in SLOTS:
        v = raw.get(key)
        norm = _normalise_hex(v) if isinstance(v, str) else None
        if not norm:
            continue
        if universe and norm not in universe:
            # The LLM hallucinated a colour. Drop it.
            log.debug("palette: dropping hallucinated %s=%s", key, norm)
            continue
        out[key] = norm
    if allow_fourth:
        v = raw.get(FOURTH_SLOT)
        norm = _normalise_hex(v) if isinstance(v, str) else None
        if norm and (not universe or norm in universe):
            out[FOURTH_SLOT] = norm
    reasoning = raw.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        out["reasoning"] = reasoning.strip()[:240]
    return out


def resolve_palette(
    *,
    org_name: str,
    voice_summary: str,
    sources: dict[str, list[str]],
    allow_fourth: bool = True,
) -> dict:
    """Decide the brand palette from all gathered colour signals.

    Returns a dict with keys ``primary``, ``secondary``, ``accent``, an
    optional ``fourth``, and a ``reasoning`` string. Returns an empty
    dict when no usable colour signals are supplied.

    Raises:
        ClaudeUnavailableError: when colour signals exist but the
        configured cloud LLM is unreachable. The palette decision is a
        judgement call about which of the org's signals are the actual
        brand colours — there is no honest non-AI substitute, so we
        surface the error to the caller (web.py wraps the call in
        try/except and leaves the existing palette untouched).
    """
    sources = sources or {}
    if not sources:
        return {}
    universe: set[str] = set()
    for hexes in sources.values():
        universe.update(hexes)

    # Safety net: if EVERY candidate colour is achromatic (pure white,
    # pure black, or near-grey), there's no real brand identity to
    # resolve — returning a palette here just paints the whole UI
    # white/grey, which looks broken and is worse than no palette.
    # Bail with {} so the caller leaves the palette empty (the user
    # picks manually and the chrome stays MediaHub default). When at
    # least one chromatic colour exists, white/grey stay in the
    # universe and remain valid as an accent.
    if not any(_is_chromatic(h) for h in universe):
        log.debug("palette: all %d candidate colours achromatic; no palette", len(universe))
        return {}

    from mediahub.media_ai.llm import (
        ClaudeUnavailableError,
        generate_json,
        is_available,
    )

    if not is_available():
        raise ClaudeUnavailableError(
            "No cloud LLM provider is reachable; cannot resolve brand "
            "palette. Configure GEMINI_API_KEY or ANTHROPIC_API_KEY."
        )

    # The colour-usage counts ride on the sources object (when it came
    # from gather_colour_sources). Surface them so the prompt can show
    # each website colour WITH its CSS-usage frequency.
    usage_counts = getattr(sources, "colour_usage", None) or {}
    prompt = _build_llm_prompt(
        org_name=org_name,
        voice_summary=voice_summary,
        sources=sources,
        allow_fourth=allow_fourth,
        usage_counts=usage_counts,
    )
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=600, fallback={})
    except Exception as e:
        log.debug("palette resolver LLM call failed: %s", e)
        raise ClaudeUnavailableError(f"Palette resolver LLM call failed: {e}") from e

    picks = _validate_picks(raw, allow_fourth=allow_fourth, universe=universe)
    if not picks:
        raise ClaudeUnavailableError("The LLM returned no usable palette picks.")
    return picks


# ---------------------------------------------------------------------------
# Manual override handling
# ---------------------------------------------------------------------------


def sanitise_manual_palette(
    *,
    primary: str = "",
    secondary: str = "",
    accent: str = "",
    fourth: str = "",
    include_fourth: bool = False,
) -> dict:
    """Validate and normalise the four manual colour inputs.

    Any slot whose value is not a valid hex is dropped. The returned
    dict only contains the slots the user actually supplied; callers
    decide whether to fall back to AI-detected values for the missing
    ones. ``include_fourth`` mirrors the form tickbox — when False, the
    fourth value is ignored even if a string was posted.
    """
    raw_inputs = dict(zip(SLOTS, (primary, secondary, accent)))
    out: dict = {}
    for key, raw in raw_inputs.items():
        v = _normalise_hex(raw)
        if v:
            out[key] = v
    if include_fourth:
        v = _normalise_hex(fourth)
        if v:
            out[FOURTH_SLOT] = v
    return out


def effective_palette(
    *,
    manual: Optional[dict],
    extracted: Optional[dict],
) -> dict:
    """Return the palette that should actually drive rendering.

    Manual entries win per-slot; missing slots fall back to the
    AI-extracted palette. ``fourth`` is only present when one of the
    two dicts explicitly carries it.
    """
    manual = manual or {}
    extracted = extracted or {}
    out: dict = {}
    for key in SLOTS:
        v = _normalise_hex(manual.get(key)) if manual.get(key) else None
        if not v:
            v = _normalise_hex(extracted.get(key)) if extracted.get(key) else None
        if v:
            out[key] = v
    # Fourth: manual wins; only persist when explicitly set.
    if manual.get(FOURTH_SLOT):
        v = _normalise_hex(manual.get(FOURTH_SLOT))
        if v:
            out[FOURTH_SLOT] = v
    elif extracted.get(FOURTH_SLOT):
        v = _normalise_hex(extracted.get(FOURTH_SLOT))
        if v:
            out[FOURTH_SLOT] = v
    return out


# ---------------------------------------------------------------------------
# Slot reordering — let the user swap colours between roles
# ---------------------------------------------------------------------------


def present_slots(palette: Optional[dict]) -> list[str]:
    """Return the slots that carry a valid hex, in canonical order.

    Canonical order is ``ALL_SLOTS`` (primary, secondary, accent, fourth)
    so a reorder always works against a stable, predictable sequence
    regardless of dict insertion order. Slots whose value isn't a valid
    ``#rrggbb`` hex are omitted — there's nothing to move.
    """
    palette = palette or {}
    return [s for s in ALL_SLOTS if _normalise_hex(palette.get(s))]


def reorder_palette(palette: Optional[dict], order: Sequence[str]) -> dict:
    """Reassign colour values to slots according to a new ordering.

    ``palette`` is keyed by slot names (a subset of ``ALL_SLOTS``).
    ``order`` is a permutation of the slots actually present in
    ``palette``: the colour currently sitting in ``order[i]`` moves into
    the i-th present slot (present slots taken in ``ALL_SLOTS`` order).

    The result always carries exactly the same set of slot keys it
    started with — only the hex values are shuffled between them, so no
    downstream consumer ever sees a slot vanish or a brand-new colour
    appear. Every value is normalised to ``#rrggbb`` so the output is
    render-safe.

    If ``order`` is not a permutation of the present slots (a stale or
    hand-crafted POST), the palette is returned unchanged (slots only,
    normalised) rather than corrupted.
    """
    present = present_slots(palette)
    palette = palette or {}
    clean_order = [s for s in (order or []) if isinstance(s, str)]
    identity = {s: _normalise_hex(palette[s]) for s in present}
    if sorted(clean_order) != sorted(present):
        return identity
    return {present[i]: _normalise_hex(palette[clean_order[i]]) for i in range(len(present))}


def rotate_palette(palette: Optional[dict], steps: int = 1) -> dict:
    """Rotate the colours across the present slots by ``steps``.

    A positive step moves each colour *forward* one role — the primary
    colour becomes the secondary, the secondary becomes the third, and
    the last wraps back to primary. This is the "swap the colours
    around" cycle: repeatedly rotating walks through every arrangement
    and returns to the start. Negative steps rotate the other way.

    Slots with fewer than two colours are returned unchanged.
    """
    present = present_slots(palette)
    n = len(present)
    if n < 2:
        return {s: _normalise_hex((palette or {})[s]) for s in present}
    steps %= n
    # Slot i receives the colour that was `steps` positions earlier, so
    # the colour in slot i ends up `steps` positions later (forward).
    order = [present[(i - steps) % n] for i in range(n)]
    return reorder_palette(palette, order)


__all__ = [
    "SLOTS",
    "FOURTH_SLOT",
    "ALL_SLOTS",
    "gather_colour_sources",
    "resolve_palette",
    "sanitise_manual_palette",
    "effective_palette",
    "present_slots",
    "reorder_palette",
    "rotate_palette",
]
