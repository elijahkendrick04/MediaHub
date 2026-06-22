"""email_design.theme — resolve a club's brand into an *email-safe* palette.

Email is not the web: there is no ``var(--token)``, no external stylesheet, no
reliable web-font. So instead of CSS custom properties this module resolves a
club's brand to a flat dict of **literal hex strings** the renderer inlines on
every element. The colours are the same ones the existing
:mod:`brand.newsletter_renderer` settled on — the **light** MD3 scheme (emails
sit on a white body, where the light-primary is the darker, more contrasting
brand tone) — so a newsletter matches the club's still cards and motion.

Resolution cascade for the brand colours (manual override always wins), mirrored
from the shipped email renderer so brand parity holds:

  1. ``brand_palette_manual``    — the operator's confirmed pick
  2. ``brand_palette_extracted`` — the AI's unified pick
  3. theme-store light scheme    — HCT-derived from the seed
  4. legacy ``brand_primary`` / ``brand_secondary`` fields
  5. house defaults

Legible on-colours (button/label text) come from the deterministic
:func:`theming.contrast.brand_on_color`; the section-band tint is a plain blend
toward white (presentation tinting, not colour-science). Pure and deterministic
— no I/O beyond the optional theme-store read.
"""

from __future__ import annotations

from typing import Any, Optional

# House defaults — the Stage-A navy + neutral slate the email renderer falls back
# to when a club has no resolved brand yet. Lowercase to match the normalised hex
# the cascade emits everywhere else (so the palette is consistently cased).
_DEFAULT_PRIMARY = "#0a2540"
_DEFAULT_SECONDARY = "#475569"
_DEFAULT_ACCENT = "#0a2540"

# Fixed email canvas colours (the chrome the brand colours sit inside).
_BG = "#f3f4f6"  # page canvas behind the card
_PANEL = "#ffffff"  # the email card surface
_INK = "#1f2937"  # body text
_MUTED = "#6b7280"  # secondary / footer text
_BORDER = "#e5e7eb"  # hairline rules

# An email-safe system font stack. Web-fonts are unreliable in mail clients, so
# (unlike the web UI / renderer, which self-host woff2 — never the Google CDN)
# email uses the device system stack. There is no webfont link or @import here,
# so the self-hosted-fonts rule is honoured by *not loading a remote font at
# all*.
EMAIL_FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a ClubProfile-like object or a dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _safe_hex(value: Any, fallback: str) -> str:
    """Validate/normalise a hex string; expand 3-char; default on garbage."""
    if not isinstance(value, str):
        return fallback
    v = value.strip()
    if not v:
        return fallback
    if not v.startswith("#"):
        v = "#" + v
    body = v[1:]
    if len(body) == 3:
        body = "".join(c * 2 for c in body)
    if len(body) != 6:
        return fallback
    try:
        int(body, 16)
    except ValueError:
        return fallback
    return "#" + body.lower()


def _to_rgb(hex_colour: str) -> tuple[int, int, int]:
    s = _safe_hex(hex_colour, "#000000").lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def mix_hex(a: str, b: str, t: float) -> str:
    """Linear blend of two hex colours; t=0 → ``a``, t=1 → ``b``. Pure."""
    ar, ag, ab = _to_rgb(a)
    br, bg, bb = _to_rgb(b)
    t = max(0.0, min(1.0, t))
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def _mix_to_white(hex_colour: str, t: float) -> str:
    """Blend ``hex_colour`` toward white; t=0 → colour, t=1 → white."""
    return mix_hex(hex_colour, "#ffffff", t)


def _from_palette_slot(profile: Any, slot: str) -> Optional[str]:
    """The manual-then-extracted palette slot value, if a valid hex."""
    for key in ("brand_palette_manual", "brand_palette_extracted"):
        src = _get(profile, key) or {}
        if isinstance(src, dict):
            v = src.get(slot)
            if isinstance(v, str) and v.strip():
                return _safe_hex(v, "")  # "" means "present but invalid → skip"
    return None


def _from_theme_store(profile: Any, slot: str) -> Optional[str]:
    """The theme-store *light*-scheme value for ``slot`` (primary/secondary/
    tertiary), if the club has a stored theme."""
    pid = _get(profile, "profile_id")
    if not pid:
        return None
    try:
        from mediahub.theming.theme_store import palette_for_email, read_theme

        theme_json = read_theme(pid)
        if theme_json:
            p = palette_for_email(theme_json)
            v = p.get(slot)
            if isinstance(v, str) and v.startswith("#"):
                return _safe_hex(v, "")
    except Exception:
        return None
    return None


def _resolve(profile: Any, brand_kit: Any, *, slot: str, theme_slot: str, legacy: str,
            kit_attr: str, default: str) -> str:
    """Run the full cascade for one brand colour slot."""
    # 1 + 2: manual / extracted palette slot
    v = _from_palette_slot(profile, slot)
    if v:
        return v
    # brand_kit explicit colour (already resolved by ClubProfile.get_brand_kit)
    if brand_kit is not None:
        kv = _get(brand_kit, kit_attr)
        if isinstance(kv, str) and kv.strip():
            cand = _safe_hex(kv, "")
            if cand:
                return cand
    # 3: theme-store light scheme
    v = _from_theme_store(profile, theme_slot)
    if v:
        return v
    # 4: legacy field
    lv = _get(profile, legacy)
    if isinstance(lv, str) and lv.strip():
        cand = _safe_hex(lv, "")
        if cand:
            return cand
    # 5: house default
    return default


def email_palette(profile: Any = None, brand_kit: Any = None) -> dict[str, str]:
    """Resolve a club's brand into the flat hex palette the renderer inlines.

    Returns keys: ``bg, panel, ink, muted, border, brand, on_brand, accent,
    on_accent, surface``. Every value is a literal ``#rrggbb`` string safe to
    drop straight into an inline ``style=""``.
    """
    brand = _resolve(
        profile, brand_kit, slot="primary", theme_slot="primary",
        legacy="brand_primary", kit_attr="primary_colour", default=_DEFAULT_PRIMARY,
    )
    accent = _resolve(
        profile, brand_kit, slot="secondary", theme_slot="secondary",
        legacy="brand_secondary", kit_attr="secondary_colour", default=_DEFAULT_SECONDARY,
    )
    # Accent slot may also be carried explicitly; prefer a confirmed accent.
    explicit_accent = _from_palette_slot(profile, "accent")
    if explicit_accent:
        accent = explicit_accent

    on_brand = _on_color(brand)
    on_accent = _on_color(accent)
    return {
        "bg": _BG,
        "panel": _PANEL,
        "ink": _INK,
        "muted": _MUTED,
        "border": _BORDER,
        "brand": brand,
        "on_brand": on_brand,
        "accent": accent,
        "on_accent": on_accent,
        # a very light brand tint for "surface" section bands (12% brand / 88% white)
        "surface": _mix_to_white(brand, 0.90),
    }


def _on_color(bg_hex: str) -> str:
    """Legible ink for a brand-coloured fill, via the deterministic contrast
    primitive. Falls back to white/near-black if the helper is unavailable."""
    try:
        from mediahub.theming.contrast import brand_on_color

        return _safe_hex(brand_on_color(bg_hex), "#ffffff")
    except Exception:
        r, g, b = _to_rgb(bg_hex)
        # Rec. 601 luma — dark fills get white ink, light fills get near-black.
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        return "#0b0b0b" if luma > 150 else "#ffffff"


__all__ = ["EMAIL_FONT_STACK", "email_palette", "mix_hex"]
