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
