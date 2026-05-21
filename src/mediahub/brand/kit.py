"""
BrandKit dataclass — everything visual about a club's identity.

Stored inside the club profile JSON under the key "brand_kit".
Fields are all optional with sensible defaults so old profiles load cleanly.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class BrandKit:
    profile_id: str
    display_name: str
    primary_colour: str = "#A30D2D"      # CSS hex colour
    secondary_colour: str = "#000000"
    accent_colour: Optional[str] = None
    logo_svg: Optional[str] = None       # inline SVG string (uploaded or pasted)
    governing_body: Optional[str] = None
    short_name: Optional[str] = None

    # Phase 1.6 Stage B — Adaptive Theming Engine.
    # DTCG-format theme JSON cached at brand-kit save time. Shape is
    # documented as ``mediahub.theming.ThemeJSON``. Optional + None
    # default so old serialised profiles load cleanly through
    # ``from_dict`` (which already ignores unknown keys, but the
    # field is added here so ``to_dict`` round-trips it).
    derived_palette: Optional[dict] = None

    # ---- factory ----

    @classmethod
    def generic_default(cls) -> "BrandKit":
        """Generic, club-agnostic default brand kit.

        Used as a fallback when no profile-specific kit is configured.
        Colours are deliberately neutral so they don't masquerade as any
        real club's livery.
        """
        return cls(
            profile_id="default",
            display_name="Your Club",
            primary_colour="#0E2A47",   # neutral navy
            secondary_colour="#C9A227",  # neutral gold
            accent_colour=None,
            logo_svg=None,
            governing_body=None,
            short_name="Your Club",
        )

    @classmethod
    def from_dict(cls, d: dict) -> "BrandKit":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- helpers ----

    def safe_primary(self) -> str:
        """Return primary_colour if it looks like a CSS hex colour, else fallback."""
        import re
        if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", self.primary_colour or ""):
            return self.primary_colour
        return "#A30D2D"

    def safe_secondary(self) -> str:
        import re
        if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", self.secondary_colour or ""):
            return self.secondary_colour
        return "#000000"

    # ---- Adaptive Theming Engine ----

    def ensure_derived_palette(self, *, force: bool = False,
                                source: Optional[str] = None) -> dict:
        """Compute (or re-compute) the Adaptive Theming Engine palette.

        Cached on ``self.derived_palette`` as a DTCG-format dict. Safe
        to call repeatedly; idempotent unless ``force=True``. Seed
        defaults to ``self.logo_svg`` if present, otherwise
        ``self.safe_primary()``.

        Computation pipeline (see docs/THEMING.md):
          seed → HCT → 5 tonal palettes × 13 tones → MD3 role mapping
          (light + dark) → APCA + WCAG2 + ΔE + CVD gates → repair loop.

        Returns the cached dict. Never raises — the fallback palette
        is always available.
        """
        if self.derived_palette is not None and not force:
            return self.derived_palette
        # Local import to avoid circular dep (theming → kit would loop).
        from mediahub.theming import derive_theme
        seed_source = source if source is not None else (
            self.logo_svg if self.logo_svg else self.safe_primary()
        )
        theme = derive_theme(seed_source)
        self.derived_palette = theme.to_json()
        # Phase 1.6 Stage G — mirror the palette to the on-disk theme
        # store at DATA_DIR/themes/<profile_id>.json so the motion,
        # email, and static-graphic renderers can read from the same
        # source of truth as the web cascade. Best-effort: a failed
        # disk write keeps the in-memory palette authoritative.
        try:
            from mediahub.theming.theme_store import write_theme
            write_theme(self.profile_id, self.derived_palette)
        except Exception:
            pass
        return self.derived_palette
