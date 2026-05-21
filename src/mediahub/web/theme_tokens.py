"""Three-tier DTCG-format design-token vocabulary for MediaHub.

This module is the loader for Phase 1.6 Stage C's static CSS files:

  src/mediahub/web/static/theme/theme-base.css       — framework + @property
  src/mediahub/web/static/theme/theme-fallback.css   — Safari ≤ 16.3 fallback
  src/mediahub/web/static/theme/theme-derive.css     — modern oklch(from …) derivations

The three files are concatenated at import time into THEME_TOKENS_CSS in
the order documented below. ``web.py`` prepends THEME_TOKENS_CSS to
BASE_CSS as before — Stage C is the source migration, not the delivery
mechanism switch (Stage D handles the network-level switch from inline
<style> to <link rel="stylesheet">).

# Tier hierarchy (per W3C Design Tokens Community Group format)

1. **Primitives (``--mh-prim-*``)** — raw colour values, no semantics.
   In Stage C, MOST primitives are derived at runtime from seven seed
   variables via ``oklch(from var(--mh-…-seed) …)`` expressions
   (modern browsers) or fall back to hand-coded values byte-identical
   to Stage A (Safari ≤ 16.3, other engines without relative-colour
   syntax). The neutral ramp stays hand-coded in both branches because
   its hue shift mid-ramp isn't a clean tonal palette.

2. **Semantic role tokens (``--mh-*``)** — ~25 Material-3-style tokens
   referencing primitives. Each declared via ``light-dark(…, …)`` so
   the same role adapts to ``prefers-color-scheme`` automatically.
   For Stage C, both arguments are identical (dark-only design today);
   Stage D introduces real light-mode values.

3. **Component tokens** — deliberately not introduced in Stage A or C
   (Nathan Curtis's "promote across 3+ component reuses" rule).

# Cascade order

    THEME_BASE_CSS  →  THEME_FALLBACK_CSS  →  THEME_DERIVE_CSS

theme-base.css declares the seed variables, the tier-2 role tokens
(via light-dark wrappers), and the @property registrations.
theme-fallback.css declares the tier-1 primitives inside
@supports not (...). theme-derive.css declares them again inside
@supports (color: oklch(from red l c h)) — the modern branch.

Modern browsers parse all three; the derive block sits last and wins.
Safari ≤ 16.3 ignores the derive block (parser rejects relative-
colour syntax) and the fallback declarations apply. Either way every
variable is set; the cascade is fully specified for every engine.

# Backward compatibility

The module-level ``THEME_TOKENS_CSS`` constant still exists — every
existing import (e.g. ``from mediahub.web.theme_tokens import
THEME_TOKENS_CSS`` in web.py) keeps working unchanged. The value is
now loaded from disk instead of being a Python r-string, but it's the
same shape and the same content (with the new tier-1 derivation
strategy baked in).

# References

- W3C Design Tokens Format Module (DTCG)
- Material Design 3 — Color Roles
- CSS Color Module Level 5 — Relative colour syntax + color-mix
- W3C CSS Properties and Values API Level 1 — @property
- docs/THEMING.md
"""
from __future__ import annotations

from pathlib import Path


__all__ = [
    "THEME_TOKENS_CSS",
    "THEME_BASE_CSS",
    "THEME_FALLBACK_CSS",
    "THEME_DERIVE_CSS",
    "THEME_CASCADE_CSS",
    "STATIC_THEME_DIR",
]


STATIC_THEME_DIR: Path = Path(__file__).resolve().parent / "static" / "theme"


def _load(filename: str) -> str:
    """Read a CSS file under static/theme/.

    Raises ``FileNotFoundError`` with a useful message if the file is
    missing — this is a hard requirement; the loader is the single
    source of truth for what gets concatenated into BASE_CSS at
    import time.
    """
    path = STATIC_THEME_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Theme CSS file missing: {path}. "
            f"Expected file in src/mediahub/web/static/theme/."
        )
    return path.read_text(encoding="utf-8")


# Loaded once at import time. The files are tiny (~5KB each); read-on-
# import keeps the loader synchronous and predictable, with no first-
# request latency penalty.
THEME_BASE_CSS: str = _load("theme-base.css")
THEME_FALLBACK_CSS: str = _load("theme-fallback.css")
THEME_DERIVE_CSS: str = _load("theme-derive.css")
# Stage E — cascade-animation layer (@view-transition + :root seed
# transition + reduced-motion override).
THEME_CASCADE_CSS: str = _load("theme-cascade.css")
# Polish layer — additive component primitives (drag-drop, modals,
# mobile nav, type/easing scales, focus rings on non-button controls,
# WCAG-safe brand-link lift). Exported separately because it must
# load AFTER BASE_CSS in web.py so it can override legacy component
# rules with the same specificity.
THEME_COMPONENTS_CSS: str = _load("theme-components.css")


# The single module-level constant every other module consumes.
# Order matters:
#   1. base       — seeds + role tokens + @property registrations
#   2. fallback   — Safari ≤ 16.3 primitive values inside @supports not
#   3. derive     — modern oklch(from …) values inside @supports
#   4. cascade    — Stage E animation rules (last so they apply
#                   regardless of @supports branch)
THEME_TOKENS_CSS: str = (
    THEME_BASE_CSS
    + "\n"
    + THEME_FALLBACK_CSS
    + "\n"
    + THEME_DERIVE_CSS
    + "\n"
    + THEME_CASCADE_CSS
)
