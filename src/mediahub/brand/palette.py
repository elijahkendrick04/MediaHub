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
from typing import Optional

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

def gather_colour_sources(
    *,
    link_palette_signals: Optional[dict] = None,
    brand_guidelines: Optional[dict] = None,
    brand_logos: Optional[list[dict]] = None,
) -> dict[str, list[str]]:
    """Build a labelled mapping of every colour signal collected.

    Returns a dict like:
        {
          "website (palette_mentions)": ["#0a2540", ...],
          "instagram (palette_mentions)": [...],
          "brand_guidelines (palette_mentions)": [...],
          "logo: navy-on-white.svg (dominant)": [...],
          ...
        }

    Order of keys is stable; values are de-duped per source. Empty
    sources are omitted.
    """
    sources: dict[str, list[str]] = {}

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
                logo.get("label")
                or logo.get("original_filename")
                or logo.get("logo_id")
                or "logo"
            )
            key = f"logo: {str(label)[:80]} (dominant)"
            if key in sources:
                key = f"logo: {logo.get('logo_id', '')} (dominant)"
            sources[key] = cleaned

    return sources


# ---------------------------------------------------------------------------
# LLM-driven palette decision
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a brand-identity expert. You receive colour samples "
    "collected from many sources for one organisation and decide which "
    "colours form the actual brand palette. Be deliberate. Reason "
    "explicitly about which signals are deliberate (brand guidelines "
    "document, logo dominant colours) and which are incidental (every "
    "CSS hex scraped off a marketing page). Pure white and pure black "
    "should only appear in the chosen palette if they are explicitly "
    "part of the brand (e.g. called out in the guidelines, or the "
    "primary logo colour). Never invent colours the inputs don't "
    "contain."
)


def _build_llm_prompt(
    *,
    org_name: str,
    voice_summary: str,
    sources: dict[str, list[str]],
    allow_fourth: bool,
) -> str:
    lines = [
        f"Organisation: {org_name or '(unnamed)'}",
        f"Voice summary: {voice_summary or '(none)'}",
        "",
        "Colour signals collected, labelled by source:",
    ]
    if sources:
        for label, hexes in sources.items():
            lines.append(f"  - {label}: " + ", ".join(hexes[:12]))
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
            '  fourth:    string "#rrggbb" OR "" — only set if the org clearly has a 4th brand colour; otherwise empty'
        )
    lines += [
        '  reasoning: short string (<=240 chars) explaining which sources informed each pick',
        "",
        "Guidance:",
        "  - Colours mentioned EXPLICITLY in the brand-guidelines document outweigh CSS hex scraped from a website.",
        "  - Colours appearing across multiple independent sources are stronger signals than one-off CSS values.",
        "  - Logo dominant colours are deliberate (the org chose them); website CSS is often incidental.",
        "  - If the same colour shows up in the guidelines AND in a logo AND on the site, it is almost certainly the primary.",
        "  - Pure white (#ffffff) and pure black (#000000) only belong in the chosen palette if the brand explicitly uses them as a key colour.",
        "  - Every chosen colour MUST come from the sources above. Do not invent new hex values.",
        "  - All hex values lower-case #rrggbb.",
        "No prose, no fences, no commentary — only the JSON object.",
    ]
    return "\n".join(lines)


def _validate_picks(raw: object, *, allow_fourth: bool,
                    universe: set[str]) -> dict:
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
        log.debug("palette: all %d candidate colours achromatic; no palette",
                  len(universe))
        return {}

    from mediahub.media_ai.llm import (
        ClaudeUnavailableError, generate_json, is_available,
    )
    if not is_available():
        raise ClaudeUnavailableError(
            "No cloud LLM provider is reachable; cannot resolve brand "
            "palette. Configure GEMINI_API_KEY or ANTHROPIC_API_KEY."
        )

    prompt = _build_llm_prompt(
        org_name=org_name,
        voice_summary=voice_summary,
        sources=sources,
        allow_fourth=allow_fourth,
    )
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM,
                            max_tokens=600, fallback={})
    except Exception as e:
        log.debug("palette resolver LLM call failed: %s", e)
        raise ClaudeUnavailableError(
            f"Palette resolver LLM call failed: {e}"
        ) from e

    picks = _validate_picks(raw, allow_fourth=allow_fourth, universe=universe)
    if not picks:
        raise ClaudeUnavailableError(
            "The LLM returned no usable palette picks."
        )
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


__all__ = [
    "SLOTS",
    "FOURTH_SLOT",
    "ALL_SLOTS",
    "gather_colour_sources",
    "resolve_palette",
    "sanitise_manual_palette",
    "effective_palette",
]
