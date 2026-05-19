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
  2. ``resolve_palette(...)``        — ask the LLM to pick the actual
     brand primary / secondary / accent (and optionally a fourth) from
     ALL signals. Falls back to a frequency-based heuristic when no
     LLM is reachable.
  3. ``apply_manual_override(...)``  — if the user supplied a manual
     override on the confirmation form, that wins; the AI only runs
     when the manual override is empty or invalid.

No hardcoded "first 3 hex codes" logic. The LLM reasons about which
sources are deliberate (guidelines doc, logo dominant colours) vs
incidental (every CSS hex on a website) and picks accordingly.
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


def _heuristic_pick(sources: dict[str, list[str]], *, allow_fourth: bool) -> dict:
    """Frequency-weighted heuristic when no LLM is reachable.

    Source weights mirror the LLM guidance:
      guidelines = 4, logo = 3, social = 2, website = 1, other = 1
    Pure white/black are demoted heavily so they only appear when they
    dominate the explicit sources.
    """
    if not sources:
        return {}

    scores: dict[str, float] = {}
    for label, hexes in sources.items():
        ll = label.lower()
        if "guidelines" in ll:
            weight = 4.0
        elif ll.startswith("logo:") or " logo " in ll:
            weight = 3.0
        elif ll.startswith("website "):
            weight = 1.0
        else:
            weight = 2.0
        for i, h in enumerate(hexes):
            rank_bonus = max(0.0, 1.0 - i * 0.1)
            base = weight + rank_bonus
            if h in ("#ffffff", "#000000"):
                base *= 0.15
            scores[h] = scores.get(h, 0.0) + base

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    picks = [h for h, _ in ranked]
    out: dict = {}
    for slot, h in zip(SLOTS, picks):
        out[slot] = h
    if allow_fourth and len(picks) >= 4:
        out[FOURTH_SLOT] = picks[3]
    if out:
        out["reasoning"] = "Heuristic frequency ranking (no LLM available)."
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
    optional ``fourth`` (only present when the AI / heuristic actually
    surfaced a fourth colour), and a ``reasoning`` string. Always
    returns; never raises. An empty dict is returned only when there
    are zero usable colour signals AND no LLM is available.
    """
    sources = sources or {}
    universe: set[str] = set()
    for hexes in sources.values():
        universe.update(hexes)

    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return _heuristic_pick(sources, allow_fourth=allow_fourth)
    if not is_available() or not sources:
        return _heuristic_pick(sources, allow_fourth=allow_fourth)

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
        return _heuristic_pick(sources, allow_fourth=allow_fourth)

    picks = _validate_picks(raw, allow_fourth=allow_fourth, universe=universe)
    # If the LLM only returned a partial palette, top up from the heuristic
    # so the org always gets three slots when sources are available.
    needed = [k for k in SLOTS if k not in picks]
    if needed:
        fallback = _heuristic_pick(sources, allow_fourth=allow_fourth)
        for k in needed:
            v = fallback.get(k)
            if v and v not in picks.values():
                picks[k] = v
    if not picks:
        return _heuristic_pick(sources, allow_fourth=allow_fourth)
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
