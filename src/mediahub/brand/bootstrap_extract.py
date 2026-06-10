"""brand/bootstrap_extract.py — URL → *draft* DesignTokens, for onboarding.

Given a club's website URL, return a best-effort **draft** token set
shaped like the `DesignTokens` contract sketched in the generative-AI
thesis (§5.3): semantic colour roles, logo URLs grouped by inferred
form, and font guesses. The draft is meant to *pre-fill* an onboarding
form a human then confirms — it is never auto-applied and never trusted.

Two deliberate splits, both following MediaHub's standing rules:

  * **Deterministic extraction vs. LLM judgement.** Scraping the page,
    scanning hex codes, classifying a logo asset by aspect-ratio/filename,
    and reading font-family declarations are mechanical facts, done here
    without AI. Deciding *which* extracted colour is the brand vs. accent
    (and which font is the heading vs. body) is a judgement call — and per
    `brand/palette.py`'s established doctrine ("the palette pick is a
    judgement call with no honest non-AI substitute; no regex
    frequency-ranking fallback"), that judgement goes through
    `media_ai.llm`. When no provider is configured we do **not** fabricate
    a guess: the semantic roles stay null and the draft says so honestly.

  * **Honest about uncertainty.** Small-club extraction is unreliable
    (the thesis flags this explicitly), so every value carries a
    confidence flag, auto-extracted confidence never claims more than
    "medium", and *every* token field is marked ``"confirmed": false``.

Fetching reuses ``brand/link_handlers`` (read-only) so the UA / timeout /
size-cap config and any future scraping strategy are shared rather than
re-implemented. This module adds no route, edits no web.py, and persists
nothing.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

from mediahub.brand.link_learners.content_extractor import _scan_hex_candidates
from mediahub.theming.contrast import _hex_to_rgb, _srgb_to_relative_luminance

log = logging.getLogger(__name__)

DRAFT_VERSION = "draft-1"

# Confidence vocabulary. Auto-extraction never reaches "high" for a
# brand-identity judgement (colour role / font role) — the most an
# unconfirmed scrape earns is "medium". "high" is reserved for asset
# facts we are genuinely sure of (e.g. a declared <link rel=icon>).
_CONF_NONE = "none"
_CONF_LOW = "low"
_CONF_MEDIUM = "medium"
_CONF_HIGH = "high"

# Static role descriptions from the DesignTokens contract (thesis §5.3).
# These describe the *role*, not the club — constant regardless of what
# colour ends up filling the slot, so the renderer/director can read
# "when_to_use" as a contract regardless of confirmation state.
_WHEN_TO_USE = {
    "brand": "dominant ground / large fills",
    "accent": "highlights, chips, rules — never body text on light",
    "surface": "panels behind text on photos",
    "on_surface": "text on brand/surface",
}
_COLOUR_ROLES = ("brand", "accent", "surface", "on_surface")

_MAX_CANDIDATES = 12
_MAX_LOGOS = 12
_MAX_FONTS = 8


# ---------------------------------------------------------------------------
# Fetch — delegated to link_handlers so we don't re-implement the fetcher.
# This is the single network seam tests mock.
# ---------------------------------------------------------------------------


def _fetch_html(url: str) -> tuple[str, int]:
    """Fetch a page's raw HTML, reusing ``link_handlers``' shared fetcher.

    Returns ``(body, status_code)``; ``status_code == 0`` means the
    request never connected. Never raises.
    """
    try:
        from mediahub.brand import link_handlers
        from mediahub.brand.link_learners import strategy as strategy_learner
    except Exception:  # pragma: no cover - core modules always import
        return "", 0
    strat = strategy_learner.default_strategy(url)
    try:
        body, code, _headers = link_handlers._fetch_with_strategy(url, strat)
    except Exception as e:  # pragma: no cover - fetcher is already no-raise
        log.debug("bootstrap fetch failed for %s: %s", url, e)
        return "", 0
    return body or "", code


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")


def _norm_hex(value: object) -> Optional[str]:
    """Lower-case #rrggbb or None. Candidates are already normalised, so
    this mostly guards the LLM echo against stray casing / shorthand."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if not v.startswith("#"):
        v = "#" + v
    if len(v) == 4:
        v = "#" + "".join(ch * 2 for ch in v[1:])
    return v if _HEX_RE.match(v) else None


def _brightness(hex_value: str) -> Optional[float]:
    """WCAG relative luminance (0=black … 1=white) for a #rrggbb colour,
    sourced from the existing colour-science module (read-only). This is
    the ``brightness`` field the DesignTokens contract expects so the
    director/compliance check can reason about legibility."""
    try:
        return round(_srgb_to_relative_luminance(_hex_to_rgb(hex_value)), 3)
    except Exception:
        return None


def normalise_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s">]+))""")


def _parse_attrs(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(tag):
        name = m.group(1).lower()
        val = m.group(3)
        if val is None:
            val = m.group(4)
        if val is None:
            val = m.group(5) or ""
        out[name] = html.unescape(val)
    return out


def _find_tags(body: str, tag: str) -> list[dict[str, str]]:
    pattern = re.compile(rf"<{tag}\b[^>]*?>", re.IGNORECASE)
    return [_parse_attrs(m.group(0)) for m in pattern.finditer(body)]


# ---------------------------------------------------------------------------
# Palette candidates (deterministic facts)
# ---------------------------------------------------------------------------


def _palette_candidates(body: str) -> list[dict]:
    """Every distinct chromatic #rrggbb on the page, annotated with
    brightness. Pure white/black/near-grey are dropped by the shared
    scanner (they are UI chrome, not brand identity)."""
    out: list[dict] = []
    for hex_value in _scan_hex_candidates(body, limit=_MAX_CANDIDATES):
        out.append(
            {
                "hex": hex_value,
                "brightness": _brightness(hex_value),
                "confidence": _CONF_LOW,
                "confirmed": False,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Logos by inferred form (deterministic facts)
# ---------------------------------------------------------------------------

# Form names use the canonical DesignTokens lockup vocabulary
# (brand/design_tokens.py: icon / full_horizontal / full_stacked / mono) so a
# confirmed draft maps 1:1 onto resolve_design_tokens' ``logos`` records.
_FORM_KEYWORDS = (
    ("mono", "mono"),
    ("favicon", "icon"),
    ("icon", "icon"),
    ("mark", "icon"),
    ("badge", "icon"),
    ("emblem", "icon"),
    ("crest", "icon"),
    ("horizontal", "full_horizontal"),
    ("landscape", "full_horizontal"),
    ("lockup", "full_horizontal"),
    ("banner", "full_horizontal"),
    ("wide", "full_horizontal"),
    ("stacked", "full_stacked"),
    ("vertical", "full_stacked"),
    ("portrait", "full_stacked"),
)

_THEME_LIGHT_KEYWORDS = (
    "white",
    "light",
    "reverse",
    "reversed",
    "knockout",
    "inverse",
    "inverted",
    "on-black",
    "on_black",
    "onblack",
    "on-dark",
    "on_dark",
)
_THEME_DARK_KEYWORDS = (
    "black",
    "dark",
    "on-white",
    "on_white",
    "onwhite",
    "on-light",
    "on_light",
)


def _form_from_name(name: str) -> Optional[str]:
    low = name.lower()
    for needle, form in _FORM_KEYWORDS:
        if needle in low:
            return form
    return None


def _form_from_dims(attrs: dict) -> Optional[str]:
    try:
        w = float(re.sub(r"[^\d.]", "", attrs.get("width", "")) or 0)
        h = float(re.sub(r"[^\d.]", "", attrs.get("height", "")) or 0)
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    ar = w / h
    if ar >= 1.8:
        return "full_horizontal"
    if ar <= 0.7:
        return "full_stacked"
    return "icon"


def _theme_from_name(name: str) -> str:
    low = name.lower()
    if any(k in low for k in _THEME_LIGHT_KEYWORDS):
        return "light"
    if any(k in low for k in _THEME_DARK_KEYWORDS):
        return "dark"
    return "any"


def _logo_record(*, url: str, form: str, theme: str, source: str, confidence: str) -> dict:
    return {
        "url": url,
        "form": form,
        "theme": theme,
        "source": source,
        "confidence": confidence,
        "confirmed": False,
    }


def _logos(body: str, base_url: str) -> list[dict]:
    """Logo URLs grouped by inferred form/theme. Sources are tried in
    descending certainty (declared icon link → in-page <img> tagged
    'logo' → social-share image) and de-duplicated by resolved URL so the
    most reliable classification of each asset wins."""
    found: list[dict] = []
    seen: set[str] = set()

    def _add(rec: dict) -> None:
        if not rec["url"] or rec["url"] in seen:
            return
        seen.add(rec["url"])
        found.append(rec)

    # 1) Declared icon links — definitively the site's icon mark.
    for attrs in _find_tags(body, "link"):
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "")
        if not href or "icon" not in rel:
            continue
        _add(
            _logo_record(
                url=urljoin(base_url, href),
                form="icon",
                theme=_theme_from_name(href),
                source="link-icon",
                confidence=_CONF_HIGH,
            )
        )

    # 2) In-page images tagged as a logo by src/alt/class/id.
    for attrs in _find_tags(body, "img"):
        src = attrs.get("src") or attrs.get("data-src", "")
        if not src:
            continue
        haystack = " ".join(
            (
                src,
                attrs.get("alt", ""),
                attrs.get("class", ""),
                attrs.get("id", ""),
            )
        ).lower()
        if "logo" not in haystack:
            continue
        form = _form_from_name(src) or _form_from_dims(attrs) or "unknown"
        _add(
            _logo_record(
                url=urljoin(base_url, src),
                form=form,
                theme=_theme_from_name(src),
                source="img",
                confidence=_CONF_MEDIUM,
            )
        )

    # 3) Social-share images — may be a logo or a hero photo, so low
    #    confidence and form left unknown.
    for attrs in _find_tags(body, "meta"):
        prop = (attrs.get("property") or attrs.get("name") or "").lower()
        if prop not in ("og:image", "og:image:url", "twitter:image"):
            continue
        content = attrs.get("content", "")
        if not content:
            continue
        _add(
            _logo_record(
                url=urljoin(base_url, content),
                form="unknown",
                theme="any",
                source="og:image",
                confidence=_CONF_LOW,
            )
        )

    return found[:_MAX_LOGOS]


# ---------------------------------------------------------------------------
# Fonts (deterministic facts)
# ---------------------------------------------------------------------------

_GENERIC_FONTS = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
    "ui-rounded",
    "-apple-system",
    "blinkmacsystemfont",
    "inherit",
    "initial",
    "unset",
    "revert",
    "math",
    "emoji",
    # Classic web-safe fallbacks — almost never the distinctive brand font.
    "arial",
    "helvetica",
    "helvetica neue",
    "segoe ui",
    "times",
    "times new roman",
    "georgia",
    "courier",
    "courier new",
    "verdana",
    "tahoma",
    "trebuchet ms",
    "sans",
    "serif",
}

_FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;}{<]+)", re.IGNORECASE)


def _google_font_families(href: str) -> list[str]:
    """Family names from a Google Fonts <link>. Handles both the v1
    ``family=Open+Sans:400,700|Roboto`` (pipe-joined) and the css2
    ``family=Anton&family=Inter:wght@400;700`` (repeated key) forms."""
    fams: list[str] = []
    for raw in parse_qs(urlparse(href).query).get("family", []):
        for part in raw.split("|"):
            name = part.split(":")[0].replace("+", " ").strip()
            if name:
                fams.append(name)
    return fams


def _fonts_found(body: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        clean = name.strip().strip("\"'").strip()
        if not clean:
            return
        if clean.lower() in _GENERIC_FONTS:
            return
        if clean.lower() in seen:
            return
        seen.add(clean.lower())
        names.append(clean)

    for attrs in _find_tags(body, "link"):
        href = attrs.get("href", "")
        if "fonts.googleapis.com" in href.lower():
            for fam in _google_font_families(href):
                _add(fam)

    for m in _FONT_FAMILY_RE.finditer(body):
        first = m.group(1).split(",")[0]
        _add(first)

    return names[:_MAX_FONTS]


# ---------------------------------------------------------------------------
# Semantic interpretation — the one judgement step, through media_ai.llm.
# ---------------------------------------------------------------------------

_INTERPRET_SYSTEM = (
    "You are a brand-identity expert pre-filling a DRAFT brand-token set "
    "for one organisation from signals scraped off its website. A human "
    "will review and confirm every value, so your job is a conservative "
    "first guess, never a final answer. Only assign a role when a "
    "candidate clearly fits; return null when unsure. NEVER invent a hex "
    "or font that is not in the supplied lists."
)


def _build_interpret_prompt(org_name: str, candidates: list[dict], fonts: list[str]) -> str:
    lines = [
        f"Organisation: {org_name or '(unknown)'}",
        "",
        "Candidate colours scraped from the site (hex — brightness, where " "0=black and 1=white):",
    ]
    if candidates:
        for c in candidates:
            lines.append(f"  - {c['hex']} — {c['brightness']}")
    else:
        lines.append("  (none found)")
    lines += [
        "",
        "Font families referenced on the site:",
        ("  " + ", ".join(fonts)) if fonts else "  (none found)",
        "",
        "Return a SINGLE JSON object with EXACTLY these keys:",
        "  brand:      a hex from the list, or null — the main identity colour (usually the most prominent/saturated)",
        "  accent:     a hex from the list, or null — a secondary highlight colour",
        "  surface:    a hex from the list, or null — a dark colour usable as a panel behind text (low brightness)",
        "  on_surface: a hex from the list, or null — a light colour for text on dark grounds (high brightness)",
        "  title_font: a font from the list, or null — the display/heading face",
        "  body_font:  a font from the list, or null — the readable body face",
        "  reasoning:  short string (<=240 chars) on which signals informed the picks",
        "",
        "Every chosen value MUST appear verbatim in the lists above. If a "
        "role has no good candidate, use null rather than guessing.",
    ]
    return "\n".join(lines)


def _validate_interpretation(
    raw: object, *, hex_universe: set[str], font_universe: dict[str, str]
) -> dict:
    """Coerce the LLM response, dropping any colour/font it invented —
    the same anti-hallucination guard ``palette.resolve_palette`` uses."""
    picks = {
        "brand": None,
        "accent": None,
        "surface": None,
        "on_surface": None,
        "title_font": None,
        "body_font": None,
        "reasoning": "",
    }
    if not isinstance(raw, dict):
        return picks
    for role in _COLOUR_ROLES:
        n = _norm_hex(raw.get(role))
        if n and n in hex_universe:
            picks[role] = n
    for key in ("title_font", "body_font"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip().lower() in font_universe:
            picks[key] = font_universe[v.strip().lower()]
    reasoning = raw.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        picks["reasoning"] = reasoning.strip()[:240]
    return picks


def _interpret_signals(*, org_name: str, candidates: list[dict], fonts: list[str]) -> dict:
    """Best-effort semantic mapping of extracted facts → token roles.

    Returns ``{"available": bool, "picks": {...}, "reasoning": str}``.
    When no provider is configured (or the call fails) ``available`` is
    False and the picks are all null — we never fabricate a role.
    """
    empty = _validate_interpretation({}, hex_universe=set(), font_universe={})
    if not candidates and not fonts:
        return {"available": False, "picks": empty, "reasoning": ""}
    try:
        from mediahub.media_ai import llm as _llm
    except Exception:
        return {"available": False, "picks": empty, "reasoning": ""}
    if not _llm.is_available():
        return {"available": False, "picks": empty, "reasoning": ""}

    hex_universe = {c["hex"] for c in candidates}
    font_universe = {f.lower(): f for f in fonts}
    prompt = _build_interpret_prompt(org_name, candidates, fonts)
    try:
        raw = _llm.generate_json(
            prompt,
            system=_INTERPRET_SYSTEM,
            max_tokens=600,
            fallback={},
        )
    except Exception as e:
        log.debug("bootstrap interpretation LLM call failed: %s", e)
        return {"available": False, "picks": empty, "reasoning": ""}

    picks = _validate_interpretation(
        raw,
        hex_universe=hex_universe,
        font_universe=font_universe,
    )
    return {
        "available": True,
        "picks": picks,
        "reasoning": picks.get("reasoning", ""),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _org_name(body: str) -> str:
    m = re.search(r"<title\b[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return html.unescape(m.group(1)).strip()[:120]


def _fetch_status(body: str, code: int) -> str:
    if code == 0:
        return "unreachable"
    if code >= 400:
        return "http_error"
    if not body.strip():
        return "empty"
    return "ok"


def _colour_role(role: str, hex_value: Optional[str]) -> dict:
    return {
        "hex": hex_value,
        "brightness": _brightness(hex_value) if hex_value else None,
        "when_to_use": _WHEN_TO_USE[role],
        "confidence": _CONF_MEDIUM if hex_value else _CONF_NONE,
        "confirmed": False,
    }


def _font_role(family: Optional[str]) -> dict:
    return {
        "family": family,
        "confidence": _CONF_MEDIUM if family else _CONF_NONE,
        "confirmed": False,
    }


def extract_brand_draft(url: str) -> dict:
    """Return a *draft* DesignTokens set extracted from ``url``.

    The draft pre-fills onboarding for human confirmation. Every field is
    ``confirmed: false`` and carries a confidence flag; semantic colour /
    font roles are filled by the LLM (and left null when no provider is
    configured — never guessed). Adds no route and persists nothing.
    Never raises.
    """
    source_url = normalise_url(url)
    notes: list[str] = [
        "Draft only — every field is unconfirmed and must be reviewed by a " "human before use.",
        "Automated brand extraction is unreliable for small clubs; treat "
        "low/medium-confidence values as starting points, not facts.",
    ]

    body, code = ("", 0)
    if source_url:
        body, code = _fetch_html(source_url)
    else:
        notes.append("No URL supplied.")
    status = _fetch_status(body, code)

    if status != "ok":
        notes.append(f"Page could not be read ({status}); no signals extracted.")
        candidates: list[dict] = []
        logos: list[dict] = []
        fonts: list[str] = []
        org_name = ""
    else:
        org_name = _org_name(body)
        candidates = _palette_candidates(body)
        logos = _logos(body, source_url)
        fonts = _fonts_found(body)

    interp = _interpret_signals(
        org_name=org_name,
        candidates=candidates,
        fonts=fonts,
    )
    picks = interp["picks"]
    if not interp["available"] and (candidates or fonts):
        notes.append(
            "AI provider not configured — colour and font roles were left "
            "unresolved rather than guessed. Confirm them manually."
        )

    return {
        "version": DRAFT_VERSION,
        "source_url": source_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "org_name": org_name,
        "reliability": "low",
        "confirmed": False,
        "fetch": {"status": status, "http_status": code},
        "interpretation": {
            "available": interp["available"],
            "reasoning": interp["reasoning"],
        },
        "tokens": {
            "colours": {role: _colour_role(role, picks.get(role)) for role in _COLOUR_ROLES},
            "palette_candidates": candidates,
            "logos": logos,
            "type": {
                "title": _font_role(picks.get("title_font")),
                "body": _font_role(picks.get("body_font")),
                "fonts_found": fonts,
                "confirmed": False,
            },
        },
        "notes": notes,
    }


__all__ = ["extract_brand_draft", "normalise_url", "DRAFT_VERSION"]
