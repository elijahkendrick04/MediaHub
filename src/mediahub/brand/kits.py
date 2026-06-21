"""brand/kits.py — multi-kit brand platform (roadmap 1.12).

MediaHub's brand layer started single: one ``BrandKit`` per club, resolved by
``ClubProfile.get_brand_kit()``. Real clubs need more than one identity:

  - the **primary** club kit (the default livery),
  - **sponsor** co-branding kits (a sponsor lockup pairs with the club's, with
    clear-space and placement rules so the sponsor is presented safely),
  - **event** sub-brands (an annual gala identity),
  - **section** / team kits (the masters squad, the junior development squad),
  - **personal** kits (a coach's own side projects).

This module adds that **without** changing how anything renders today. A
``BrandKitRef`` is a lightweight descriptor stored as a dict in
``ClubProfile.brand_kits``; ``brand_kit_from_ref`` turns one back into the
existing :class:`~mediahub.brand.kit.BrandKit` that every renderer already
consumes. The hard back-compat guarantee:

  * a profile that has never touched the multi-kit surface
    (``brand_kits == []``) still resolves to exactly one synthesised
    **primary** kit, and ``brand_kit_from_ref(profile, primary_kit(profile))``
    is byte-identical to ``profile.get_brand_kit()``.

Governance fields (``locks``, ``approver_rule``) ride the schema here so the
shape is stable, but their *enforcement* lives in the workflow/approval layer
(roadmap 1.12 build 4) — storing them costs nothing for clubs that don't use
them.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

# Closed vocabularies ------------------------------------------------------

# Kit roles. ``primary`` is special: exactly one kit is the club's default
# livery, and an un-migrated profile synthesises one from its legacy fields.
KIT_ROLES: tuple[str, ...] = ("primary", "sponsor", "event", "section", "personal")

# Tokens a kit can lock. A locked token means the brand owner has frozen that
# aspect of the identity; the approval gate (build 4) refuses to ship a card
# that drifts off a locked token. Enforcement is additive — listing a token
# here only does anything once the governance layer reads it.
LOCKABLE_TOKENS: tuple[str, ...] = ("palette", "fonts", "logo")

# Where a sponsor lockup may sit on a co-branded graphic. Deliberately a small,
# safe set — sponsors get presented predictably, never splashed over a face.
SPONSOR_PLACEMENTS: tuple[str, ...] = ("footer", "corner", "banner", "sidebar")

# How the sponsor lockup pairs with the club's mark.
SPONSOR_LOCKUPS: tuple[str, ...] = (
    "side_by_side",
    "stacked",
    "club_lead",
    "sponsor_lead",
)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Palette slot names mirror brand.palette.ALL_SLOTS without importing it at
# module load (palette pulls in the LLM stack); kept in sync by the test suite.
_PALETTE_SLOTS: tuple[str, ...] = ("primary", "secondary", "accent", "fourth")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_kit_id() -> str:
    """A short, collision-resistant kit id."""
    return "kit_" + uuid.uuid4().hex[:12]


def _norm_hex(value) -> Optional[str]:
    """Normalise to lowercase ``#rrggbb`` (expanding ``#rgb``); else ``None``."""
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


def _clean_palette(raw) -> dict:
    """Keep only known slots holding valid hex colours."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for slot in _PALETTE_SLOTS:
        h = _norm_hex(raw.get(slot))
        if h:
            out[slot] = h
    return out


def _clean_str_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Data model ---------------------------------------------------------------


@dataclass
class SponsorPairingRules:
    """How a sponsor lockup is presented next to the club's mark.

    Deterministic, geometric rules — never an AI judgement. ``clear_space``
    is expressed in multiples of the sponsor logo's own height (the usual way
    brand guidelines state it). Consumed by the sponsor_activation content
    type and the co-branding composition.
    """

    clear_space: float = 1.0  # min clear space = N × sponsor-logo height
    placement: str = "footer"
    lockup: str = "side_by_side"
    min_logo_px: int = 64  # never render the sponsor mark smaller than this
    notes: str = ""

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "SponsorPairingRules":
        d = d or {}
        placement = str(d.get("placement", "footer")).strip().lower()
        if placement not in SPONSOR_PLACEMENTS:
            placement = "footer"
        lockup = str(d.get("lockup", "side_by_side")).strip().lower()
        if lockup not in SPONSOR_LOCKUPS:
            lockup = "side_by_side"
        try:
            clear_space = max(0.0, float(d.get("clear_space", 1.0)))
        except (TypeError, ValueError):
            clear_space = 1.0
        try:
            v = int(d.get("min_logo_px", 64))
            # A sponsor mark below a floor stops being legible; a negative
            # value is invalid input, so fall back to the default rather than
            # clamp to a meaningless zero. (0 is allowed = "no floor".)
            min_logo_px = v if v >= 0 else 64
        except (TypeError, ValueError):
            min_logo_px = 64
        return cls(
            clear_space=clear_space,
            placement=placement,
            lockup=lockup,
            min_logo_px=min_logo_px,
            notes=str(d.get("notes", "")).strip(),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BrandKitRef:
    """A named brand identity belonging to one org.

    Stored as a dict in ``ClubProfile.brand_kits``. Every visual field is
    optional and *inherits from the org's resolved brand* when blank, so a
    kit can be a light overlay (just a swapped accent) or a full identity.
    """

    kit_id: str
    name: str
    role: str = "primary"
    palette: dict = field(default_factory=dict)  # {primary, secondary, accent, fourth?}
    logo_ids: list[str] = field(default_factory=list)  # refs into ClubProfile.brand_logos
    font_pairing: str = ""  # graphic_renderer type-pairing id; "" → inherit
    tone: str = ""  # "" → inherit the org tone
    locks: list[str] = field(default_factory=list)  # subset of LOCKABLE_TOKENS
    pairing_rules: dict = field(default_factory=dict)  # SponsorPairingRules (sponsor kits)
    sponsor_id: str = ""  # link to a ClubProfile.sponsors entry (sponsor kits)
    shared_with: list[str] = field(default_factory=list)  # section/workspace ids
    approver_rule: dict = field(default_factory=dict)  # group-approver rule (build 4)
    created_at: str = ""
    updated_at: str = ""

    # ---- (de)serialisation ----

    @classmethod
    def from_dict(cls, d: dict) -> Optional["BrandKitRef"]:
        return normalise_kit(d)

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- helpers ----

    def is_locked(self, token: str) -> bool:
        return token in (self.locks or [])

    def pairing(self) -> SponsorPairingRules:
        return SponsorPairingRules.from_dict(self.pairing_rules)


def normalise_kit(entry) -> Optional[BrandKitRef]:
    """Coerce a raw dict into a valid :class:`BrandKitRef` (or ``None``).

    Mirrors ``club_platform.sponsors.normalise_sponsor``: invalid entries are
    dropped rather than raised so one bad row never breaks a profile load.
    """
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name", "")).strip()
    kit_id = str(entry.get("kit_id", "")).strip()
    if not kit_id:
        kit_id = new_kit_id()
    if not name:
        return None
    role = str(entry.get("role", "primary")).strip().lower()
    if role not in KIT_ROLES:
        role = "primary"
    locks = [t for t in _clean_str_list(entry.get("locks")) if t in LOCKABLE_TOKENS]
    return BrandKitRef(
        kit_id=kit_id,
        name=name,
        role=role,
        palette=_clean_palette(entry.get("palette")),
        logo_ids=_clean_str_list(entry.get("logo_ids")),
        font_pairing=str(entry.get("font_pairing", "")).strip(),
        tone=str(entry.get("tone", "")).strip(),
        locks=locks,
        pairing_rules=(
            SponsorPairingRules.from_dict(entry.get("pairing_rules")).to_dict()
            if entry.get("pairing_rules")
            else {}
        ),
        sponsor_id=str(entry.get("sponsor_id", "")).strip(),
        shared_with=_clean_str_list(entry.get("shared_with")),
        approver_rule=(
            dict(entry.get("approver_rule")) if isinstance(entry.get("approver_rule"), dict) else {}
        ),
        created_at=str(entry.get("created_at", "")).strip(),
        updated_at=str(entry.get("updated_at", "")).strip(),
    )


# Profile-level registry ----------------------------------------------------


def _synthesised_primary(profile) -> BrandKitRef:
    """The implicit primary kit for a profile that has no explicit kits.

    Derived from the profile's resolved brand so the multi-kit surface has
    something to show, and so ``brand_kit_from_ref`` round-trips to exactly
    ``profile.get_brand_kit()``.
    """
    bk = profile.get_brand_kit()
    palette: dict = {}
    p = _norm_hex(bk.primary_colour)
    s = _norm_hex(bk.secondary_colour)
    a = _norm_hex(bk.accent_colour)
    if p:
        palette["primary"] = p
    if s:
        palette["secondary"] = s
    if a:
        palette["accent"] = a
    return BrandKitRef(
        kit_id="primary",
        name=(bk.display_name or profile.display_name or "Primary brand"),
        role="primary",
        palette=palette,
    )


def list_kits(profile) -> list[BrandKitRef]:
    """Every kit on a profile, primary first.

    When the profile carries no explicit kits, returns a single synthesised
    primary kit so callers never special-case the empty state.
    """
    raw = profile.brand_kits or []
    kits: list[BrandKitRef] = []
    for entry in raw:
        k = normalise_kit(entry)
        if k is not None:
            kits.append(k)
    if not kits:
        return [_synthesised_primary(profile)]
    # Primary kit(s) first, then by name for stable ordering.
    kits.sort(key=lambda k: (k.role != "primary", k.name.lower()))
    return kits


def get_kit(profile, kit_id: str) -> Optional[BrandKitRef]:
    if not kit_id:
        return None
    for k in list_kits(profile):
        if k.kit_id == kit_id:
            return k
    return None


def primary_kit(profile) -> BrandKitRef:
    """The club's default livery kit (always present)."""
    kits = list_kits(profile)
    for k in kits:
        if k.role == "primary":
            return k
    return kits[0]


def default_kit_id(profile) -> str:
    """Which kit the pipeline applies by default ("" → the primary kit)."""
    wanted = (getattr(profile, "default_kit_id", "") or "").strip()
    if wanted and get_kit(profile, wanted) is not None:
        return wanted
    return primary_kit(profile).kit_id


def resolve_kit_for(profile, *, kit_id: Optional[str] = None) -> BrandKitRef:
    """Pick the kit to apply: an explicit id wins, else the profile default.

    Per roadmap 1.12 the pipeline can pin a kit id per pack/format; this is
    the single resolver those call sites use. An unknown id falls back to the
    default kit rather than erroring, so a deleted kit never breaks a render.
    """
    if kit_id:
        k = get_kit(profile, kit_id)
        if k is not None:
            return k
    return get_kit(profile, default_kit_id(profile)) or primary_kit(profile)


# Mutation (persistence is the caller's job via save_profile) ---------------


def upsert_kit(profile, kit: BrandKitRef) -> BrandKitRef:
    """Insert or replace a kit on the profile's ``brand_kits`` list.

    Materialises the synthesised primary first time the list is touched so the
    club's existing livery is preserved as an explicit, editable kit. Stamps
    ``created_at`` / ``updated_at``. Mutates ``profile.brand_kits`` in place;
    the caller persists with ``save_profile``.
    """
    existing = list(profile.brand_kits or [])
    if not existing:
        # First explicit kit: seed the list with the materialised primary so
        # the club's current brand survives as a real, editable entry.
        prim = _synthesised_primary(profile)
        if kit.kit_id != prim.kit_id:
            prim.created_at = prim.updated_at = _now_iso()
            existing.append(prim.to_dict())

    now = _now_iso()
    out: list[dict] = []
    found = False
    for entry in existing:
        cur = normalise_kit(entry)
        if cur is not None and cur.kit_id == kit.kit_id:
            kit.created_at = cur.created_at or now
            kit.updated_at = now
            out.append(kit.to_dict())
            found = True
        else:
            out.append(entry)
    if not found:
        kit.created_at = kit.created_at or now
        kit.updated_at = now
        out.append(kit.to_dict())
    profile.brand_kits = out
    return kit


def delete_kit(profile, kit_id: str) -> bool:
    """Remove a kit. Refuses to delete the primary kit or the last remaining
    kit (a club always has at least its primary livery). Returns True on
    removal. Clears ``default_kit_id`` if it pointed at the removed kit.
    """
    existing = [normalise_kit(e) for e in (profile.brand_kits or [])]
    existing = [k for k in existing if k is not None]
    if not existing:
        return False  # nothing explicit to delete (synthesised primary only)
    target = next((k for k in existing if k.kit_id == kit_id), None)
    if target is None or target.role == "primary":
        return False
    remaining = [k for k in existing if k.kit_id != kit_id]
    if not remaining:
        return False
    profile.brand_kits = [k.to_dict() for k in remaining]
    if (getattr(profile, "default_kit_id", "") or "") == kit_id:
        profile.default_kit_id = ""
    return True


def set_default_kit(profile, kit_id: str) -> bool:
    """Pin which kit the pipeline applies by default. Returns False for an
    unknown id."""
    if get_kit(profile, kit_id) is None:
        return False
    profile.default_kit_id = kit_id
    return True


# Bridge back to the renderer's BrandKit -----------------------------------


def _logo_svg_for(profile, logo_id: str) -> Optional[str]:
    """Inline SVG for a pinned logo id, when it is an SVG we can embed.

    Best-effort: returns None for raster logos (the BrandKit's logo_svg slot
    only carries inline SVG) so the caller falls back to the base kit's logo.
    """
    if not logo_id:
        return None
    for entry in profile.brand_logos or []:
        if not isinstance(entry, dict) or entry.get("logo_id") != logo_id:
            continue
        if (entry.get("mime") or "") != "image/svg+xml":
            return None
        stored = entry.get("stored_path") or ""
        if not stored:
            return None
        try:
            import os
            from pathlib import Path

            base = os.environ.get("DATA_DIR")
            path = Path(base) / stored if base else Path(stored)
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
    return None


def brand_kit_from_ref(profile, ref: BrandKitRef):
    """Produce the renderer-facing :class:`BrandKit` for a kit ref.

    This is the bridge that lets every existing renderer consume a multi-kit
    selection unchanged. For the **primary** kit with no palette override the
    result is byte-identical to ``profile.get_brand_kit()`` (the back-compat
    guarantee); other kits overlay their own palette/logo on the org base and
    leave ``derived_palette`` for lazy recomputation.
    """
    from mediahub.brand.kit import BrandKit

    base = profile.get_brand_kit()
    pal = ref.palette or {}

    primary = _norm_hex(pal.get("primary")) or base.primary_colour
    secondary = _norm_hex(pal.get("secondary")) or base.secondary_colour
    accent = _norm_hex(pal.get("accent")) or base.accent_colour

    # Compare case-insensitively: the synthesised primary lowercases its hex
    # while the org base keeps the user's original casing, and a hex render is
    # case-insensitive — so an unchanged palette must still hit the fast path.
    def _eq_hex(a, b) -> bool:
        na, nb = _norm_hex(a), _norm_hex(b)
        if na is not None or nb is not None:
            return na == nb
        return (a or None) == (b or None)

    same_palette = (
        _eq_hex(primary, base.primary_colour)
        and _eq_hex(secondary, base.secondary_colour)
        and _eq_hex(accent, base.accent_colour)
    )

    logo_svg = base.logo_svg
    if ref.logo_ids:
        pinned = _logo_svg_for(profile, ref.logo_ids[0])
        if pinned:
            logo_svg = pinned

    # Fast path: the primary kit with no overrides is exactly the org kit.
    if ref.role == "primary" and same_palette and logo_svg == base.logo_svg:
        return base

    merged = {
        "profile_id": profile.profile_id,
        "display_name": ref.name or base.display_name,
        "primary_colour": primary,
        "secondary_colour": secondary,
        "accent_colour": accent,
        "logo_svg": logo_svg,
        "governing_body": base.governing_body,
        "short_name": base.short_name,
        # Reuse the cached theme only when the palette is unchanged; a custom
        # palette must derive its own (lazily, via ensure_derived_palette).
        "derived_palette": base.derived_palette if same_palette else None,
    }
    return BrandKit.from_dict(merged)


__all__ = [
    "KIT_ROLES",
    "LOCKABLE_TOKENS",
    "SPONSOR_PLACEMENTS",
    "SPONSOR_LOCKUPS",
    "SponsorPairingRules",
    "BrandKitRef",
    "normalise_kit",
    "new_kit_id",
    "list_kits",
    "get_kit",
    "primary_kit",
    "default_kit_id",
    "resolve_kit_for",
    "upsert_kit",
    "delete_kit",
    "set_default_kit",
    "brand_kit_from_ref",
]
