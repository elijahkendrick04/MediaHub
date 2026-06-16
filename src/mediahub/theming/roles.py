"""Material 3 role-token mapping for the Adaptive Theming Engine.

Given a ``DerivedPalette``, return a ``ThemeRoles`` containing the
light-mode and dark-mode ``RoleScheme`` instances. Each scheme has
~30 named roles: primary, on_primary, primary_container,
on_primary_container, surface, surface_container, outline, …

The tone selections come straight from the published MD3 tables
(documented in ``concepts/dynamic_color_scheme.md`` of
``material-color-utilities``). The MD3 contrast guarantees are baked
into the geometry — a tone delta ≥ 50 between any role and its "on"
pair gives WCAG AA (4.5:1) automatically. We rely on that here; the
extra APCA/CVD QA gates run in ``quality.py``.

Per-role tone lookup:

    Light       | Dark
    --------    | --------
    primary               40       | 80
    on_primary           100       | 20
    primary_container     90       | 30
    on_primary_container  10       | 90
    (same pattern for secondary, tertiary, error)

    background            99       | 10
    on_background         10       | 90
    surface               99       | 10
    on_surface            10       | 90
    surface_variant       90       | 30   (neutral_variant palette)
    on_surface_variant    30       | 80   (neutral_variant palette)
    surface_container_lowest  100  | 4
    surface_container_low     96   | 10
    surface_container         94   | 12
    surface_container_high    92   | 17
    surface_container_highest 90   | 22

    outline               50       | 60   (neutral_variant palette)
    outline_variant       80       | 30   (neutral_variant palette)

    inverse_surface       20       | 90
    inverse_on_surface    95       | 20
    inverse_primary       80       | 40

References:
  - m3.material.io/styles/color/roles
  - material-color-utilities/concepts/dynamic_color_scheme.md
  - flutter.dev/ColorScheme (canonical list of ~30 roles)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

from coloraide import Color
from materialyoucolor.hct import Hct

from .palette import DerivedPalette, TonalRamp
from .contrast import apca, brand_on_color


__all__ = [
    "RoleScheme",
    "ThemeRoles",
    "derive_roles",
    "ROLE_TONE_MAP",
    # G1.20 — APCA-gated automatic role assignment across N custom colours.
    "ColourRole",
    "BrandRoleAssignment",
    "assign_brand_roles",
    "BRAND_ROLE_SLOTS",
]


# ---------------------------------------------------------------------------
# Per-role (palette, light_tone, dark_tone) table
# ---------------------------------------------------------------------------
# Tuple shape: (palette_name, light_tone, dark_tone)
# Palette names: "primary" / "secondary" / "tertiary" / "neutral" /
#                "neutral_variant" / "error"

ROLE_TONE_MAP: dict[str, tuple[str, int, int]] = {
    # Primary
    "primary": ("primary", 40, 80),
    "on_primary": ("primary", 100, 20),
    "primary_container": ("primary", 90, 30),
    "on_primary_container": ("primary", 10, 90),
    # Secondary
    "secondary": ("secondary", 40, 80),
    "on_secondary": ("secondary", 100, 20),
    "secondary_container": ("secondary", 90, 30),
    "on_secondary_container": ("secondary", 10, 90),
    # Tertiary
    "tertiary": ("tertiary", 40, 80),
    "on_tertiary": ("tertiary", 100, 20),
    "tertiary_container": ("tertiary", 90, 30),
    "on_tertiary_container": ("tertiary", 10, 90),
    # Error
    "error": ("error", 40, 80),
    "on_error": ("error", 100, 20),
    "error_container": ("error", 90, 30),
    "on_error_container": ("error", 10, 90),
    # Background + Surface
    "background": ("neutral", 99, 10),
    "on_background": ("neutral", 10, 90),
    "surface": ("neutral", 99, 10),
    "on_surface": ("neutral", 10, 90),
    # Surface containers (M3 elevation tints)
    "surface_container_lowest": ("neutral", 100, 0),
    "surface_container_low": ("neutral", 95, 10),
    "surface_container": ("neutral", 90, 20),
    "surface_container_high": ("neutral", 90, 30),
    "surface_container_highest": ("neutral", 90, 30),
    # Surface-variant (neutral_variant palette)
    "surface_variant": ("neutral_variant", 90, 30),
    "on_surface_variant": ("neutral_variant", 30, 80),
    # Outline
    "outline": ("neutral_variant", 50, 60),
    "outline_variant": ("neutral_variant", 80, 30),
    # Inverse
    "inverse_surface": ("neutral", 20, 90),
    "inverse_on_surface": ("neutral", 95, 20),
    "inverse_primary": ("primary", 80, 40),
}


@dataclass
class RoleScheme:
    """~30 MD3 role tokens for a single scheme (light or dark)."""

    primary: str
    on_primary: str
    primary_container: str
    on_primary_container: str

    secondary: str
    on_secondary: str
    secondary_container: str
    on_secondary_container: str

    tertiary: str
    on_tertiary: str
    tertiary_container: str
    on_tertiary_container: str

    error: str
    on_error: str
    error_container: str
    on_error_container: str

    background: str
    on_background: str
    surface: str
    on_surface: str

    surface_container_lowest: str
    surface_container_low: str
    surface_container: str
    surface_container_high: str
    surface_container_highest: str

    surface_variant: str
    on_surface_variant: str

    outline: str
    outline_variant: str

    inverse_surface: str
    inverse_on_surface: str
    inverse_primary: str

    # MediaHub addition — `focus` is the colour of the focus ring;
    # aliased to primary so every theme has a consistent accent.
    focus: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ThemeRoles:
    light: RoleScheme
    dark: RoleScheme


def _build_scheme(palette: DerivedPalette, *, is_dark: bool) -> RoleScheme:
    values: dict[str, str] = {}
    for role_name, (palette_name, light_t, dark_t) in ROLE_TONE_MAP.items():
        ramp: TonalRamp = palette.ramp_by_name(palette_name)
        tone = dark_t if is_dark else light_t
        values[role_name] = ramp.tone(tone)
    # Focus aliases to primary.
    values["focus"] = values["primary"]
    return RoleScheme(**values)


def derive_roles(palette: DerivedPalette) -> ThemeRoles:
    """Build light + dark RoleScheme from a DerivedPalette."""
    return ThemeRoles(
        light=_build_scheme(palette, is_dark=False),
        dark=_build_scheme(palette, is_dark=True),
    )


# ===========================================================================
# G1.20 — Brand-palette expansion: APCA-gated automatic role assignment
# ===========================================================================
#
# The base engine derives the whole palette from a SINGLE seed, so a club's
# real secondary / accent colours were decoration the engine ignored. G1.20
# lets a club hand the engine *N* of their own colours and have them placed
# into the brand role slots (primary / secondary / tertiary) automatically.
#
# "Automatic role assignment" is the decision of which colour fills which
# slot. It is **APCA-gated**: a colour only earns the dominant `primary`
# slot (the CTA/fill that carries text) if its best ink clears a perceptual-
# contrast floor — so the colour the engine paints buttons with always has a
# legible label. A colour that fails the ink gate is *demoted* to an accent
# slot rather than being made the primary fill. Slots are also kept visually
# distinct via a CIEDE2000 floor, so a club that lists two near-identical
# blues doesn't get two indistinguishable brand roles.
#
# The whole thing is deterministic and order-aware: a club's first colour is
# their primary unless accessibility forces a demotion, and every decision is
# written to a plain-English trace for the explainability panel.
#
# This module decides the *mapping*; `palette.derive_palette_multi` consumes
# the mapping to build the expanded palette, and the existing
# `quality.audit_palette` + `repair` pipeline validates the materialised
# result exactly as it does for a single-seed palette.


# Brandability — mirrors `seed_extract._is_brandable`: a near-grey or near-
# black/near-white colour is a neutral, not a brand colour, so it never
# competes for a brand role slot (it falls through to the derived neutral).
BRANDABLE_CHROMA_MIN = 5.0
BRANDABLE_TONE_MIN = 8.0
BRANDABLE_TONE_MAX = 95.0

# APCA ink gate. A brand role's fill carries text (button labels, chips), so
# its best ink must clear the APCA "Bronze" non-text / large-text floor
# (|Lc| ≥ 45) to earn the dominant `primary` slot. Below this the colour is
# a weak text-bearing fill and is demoted to an accent role.
ROLE_INK_FLOOR_APCA = 45.0

# Distinctness gate. Two assigned brand roles must differ by at least this
# CIEDE2000 ΔE (the ColorBrewer categorical-legibility floor, the same value
# the CVD gate uses) or the second colour is redundant — folded into the
# already-assigned role rather than given a slot of its own.
ROLE_DISTINCT_DELTA_E = 10.0

# The brand role slots G1.20 fills, in priority order. Status roles
# (error/success/warning/info) and neutrals are never brand-assigned — they
# stay locked / derived per the existing engine.
BRAND_ROLE_SLOTS: tuple[str, ...] = ("primary", "secondary", "tertiary")


@dataclass
class ColourRole:
    """One club colour, analysed and assigned a brand role.

    ``role`` is one of the :data:`BRAND_ROLE_SLOTS` values, or:
      - ``"neutral"``    — not brandable (near-grey / extreme tone); folds
                            into the derived neutral family.
      - ``"redundant"``  — brandable but ΔE-indistinct from an already
                            assigned role; not given its own slot.
      - ``"extra"``      — a brandable, distinct colour beyond the three
                            brand slots (kept for explainability / future
                            expansion, not painted into a core role).
    """

    hex: str
    hct: tuple[float, float, float]  # (hue, chroma, tone)
    chroma: float
    tone: float
    brandable: bool
    best_ink: str  # the legible ink the contrast engine picks for this fill
    ink_apca: float  # signed APCA Lc of best_ink against this colour
    passes_ink_gate: bool  # |ink_apca| >= ROLE_INK_FLOOR_APCA
    role: str = ""  # filled by assign_brand_roles


@dataclass
class BrandRoleAssignment:
    """The result of mapping N club colours onto the brand role slots."""

    primary: str | None
    secondary: str | None
    tertiary: str | None
    colours: list[ColourRole] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    n_input: int = 0
    n_brandable: int = 0

    def slots(self) -> dict[str, str]:
        """Return ``{role: hex}`` for the assigned brand slots only."""
        out: dict[str, str] = {}
        for name in BRAND_ROLE_SLOTS:
            value = getattr(self, name)
            if value:
                out[name] = value
        return out

    def to_dict(self) -> dict:
        """Serialisable form for the explainability panel / audit trail."""
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "tertiary": self.tertiary,
            "n_input": self.n_input,
            "n_brandable": self.n_brandable,
            "colours": [asdict(c) for c in self.colours],
            "trace": list(self.trace),
        }


def _normalise_unique(colours: list[str]) -> list[str]:
    """Return canonical ``#RRGGBB`` strings, de-duplicated, order-preserving.

    Accepts ``#RGB`` and ``#RRGGBB`` (any case); silently drops anything that
    is not a parseable hex colour so a stray empty string / ``None`` / logo
    blob never reaches the assignment maths.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in colours or []:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if len(s) == 4 and s[0] == "#":
            try:
                int(s[1:], 16)
            except ValueError:
                continue
            s = "#" + "".join(ch + ch for ch in s[1:])
        if len(s) != 7 or s[0] != "#":
            continue
        try:
            int(s[1:], 16)
        except ValueError:
            continue
        key = s.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _analyse_one(hex_str: str) -> ColourRole:
    """Compute HCT, the legible ink, its APCA, and the brandability flag."""
    argb = 0xFF000000 | int(hex_str.lstrip("#"), 16)
    h = Hct.from_int(argb)
    hct = (h.hue, h.chroma, h.tone)
    ink = brand_on_color(hex_str)
    lc = apca(ink, hex_str)
    brandable = (
        h.chroma >= BRANDABLE_CHROMA_MIN and BRANDABLE_TONE_MIN <= h.tone <= BRANDABLE_TONE_MAX
    )
    return ColourRole(
        hex=hex_str,
        hct=hct,
        chroma=round(h.chroma, 1),
        tone=round(h.tone, 1),
        brandable=brandable,
        best_ink=ink,
        ink_apca=lc,
        passes_ink_gate=abs(lc) >= ROLE_INK_FLOOR_APCA,
        role="",
    )


def _delta_e(a_hex: str, b_hex: str) -> float:
    """CIEDE2000 ΔE between two hex colours (same maths as quality.py)."""
    return Color(a_hex).delta_e(Color(b_hex), method="2000")


def _distinct_from(cand: ColourRole, refs: list[ColourRole]) -> bool:
    return all(_delta_e(cand.hex, r.hex) >= ROLE_DISTINCT_DELTA_E for r in refs)


def assign_brand_roles(colours: list[str]) -> BrandRoleAssignment:
    """Map N custom club colours onto the brand role slots, APCA-gated.

    Parameters
    ----------
    colours : list[str]
        The club's own colours, in priority order (primary first). Hex
        strings; non-hex / duplicate entries are ignored.

    Returns
    -------
    BrandRoleAssignment
        The chosen ``primary`` / ``secondary`` / ``tertiary`` (any may be
        ``None`` when fewer distinct brand colours are supplied), the full
        per-colour analysis, and a plain-English decision trace.

    The algorithm (deterministic, order-aware):

      1. **Primary** — the first brandable colour whose best ink clears the
         APCA gate (so the dominant fill carries legible text). If none
         clear it, the first brandable colour is used with a warning; if
         nothing is brandable at all, the first colour is used as a
         near-neutral seed (the base engine handles grey seeds fine).
      2. **Secondary** — the next brandable colour that is ΔE-distinct from
         the primary. A brandable-but-indistinct colour is marked redundant.
      3. **Tertiary** — the next brandable colour distinct from *both* the
         primary and secondary.
      4. Remaining brandable colours become ``extra``; non-brandable ones
         become ``neutral``. Neither is painted into a core role.
    """
    norm = _normalise_unique(colours)
    analyses = [_analyse_one(h) for h in norm]
    n_input = len(norm)
    trace: list[str] = []

    if not analyses:
        trace.append("assign: no valid colours supplied; nothing to assign")
        return BrandRoleAssignment(None, None, None, [], trace, 0, 0)

    brandable = [a for a in analyses if a.brandable]
    n_brandable = len(brandable)
    trace.append(
        f"assign: {n_input} unique colour(s), {n_brandable} brandable "
        f"(chroma ≥ {BRANDABLE_CHROMA_MIN}, tone {BRANDABLE_TONE_MIN:.0f}–{BRANDABLE_TONE_MAX:.0f})"
    )

    # 1 — primary: first brandable clearing the APCA ink gate.
    primary_a: ColourRole | None = next((a for a in brandable if a.passes_ink_gate), None)
    if primary_a is None and brandable:
        primary_a = brandable[0]
        trace.append(
            f"primary: no brandable colour cleared the APCA ink gate "
            f"(|Lc| ≥ {ROLE_INK_FLOOR_APCA}); using first brandable {primary_a.hex} "
            f"(ink {primary_a.best_ink}, Lc {primary_a.ink_apca}) — text contrast is marginal"
        )
    if primary_a is None:
        primary_a = analyses[0]
        trace.append(
            f"primary: no brandable colour at all; using {primary_a.hex} "
            f"as a near-neutral seed (chroma {primary_a.chroma}, tone {primary_a.tone})"
        )
    primary_a.role = "primary"
    h, c, t = primary_a.hct
    trace.append(
        f"primary ← {primary_a.hex} (H={h:.0f} C={c:.0f} T={t:.0f}; "
        f"ink {primary_a.best_ink} |Lc|={abs(primary_a.ink_apca):.0f}, "
        f"gate {'pass' if primary_a.passes_ink_gate else 'WARN'})"
    )

    assigned: list[ColourRole] = [primary_a]

    # 2 + 3 — secondary then tertiary: next distinct brandable colours.
    for slot in ("secondary", "tertiary"):
        chosen: ColourRole | None = None
        for a in brandable:
            if a.role:  # already primary / secondary / redundant
                continue
            if not _distinct_from(a, assigned):
                a.role = "redundant"
                near = min(assigned, key=lambda r: _delta_e(a.hex, r.hex))
                trace.append(
                    f"  {a.hex}: ΔE2000 {_delta_e(a.hex, near.hex):.1f} vs "
                    f"{near.hex} (< {ROLE_DISTINCT_DELTA_E}) → redundant, folded into {near.role}"
                )
                continue
            chosen = a
            break
        if chosen is not None:
            chosen.role = slot
            assigned.append(chosen)
            trace.append(
                f"{slot} ← {chosen.hex} (C={chosen.chroma:.0f} T={chosen.tone:.0f}; "
                f"ink gate {'pass' if chosen.passes_ink_gate else 'warn'})"
            )
        else:
            trace.append(f"{slot}: no further distinct brandable colour available")

    # 4 — classify the leftovers for the explainability panel.
    for a in analyses:
        if a.role:
            continue
        a.role = "extra" if a.brandable else "neutral"

    return BrandRoleAssignment(
        primary=primary_a.hex,
        secondary=next((a.hex for a in analyses if a.role == "secondary"), None),
        tertiary=next((a.hex for a in analyses if a.role == "tertiary"), None),
        colours=analyses,
        trace=trace,
        n_input=n_input,
        n_brandable=n_brandable,
    )
