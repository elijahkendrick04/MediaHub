"""Curated self-hosted font catalogue (roadmap 1.9).

The **source of truth** for the typefaces MediaHub ships first-party across its
three public surfaces — the web UI, the Playwright still renderer, and the
Remotion reel. Every face here is self-hosted ``woff2`` (NEVER the Google Fonts
CDN: the same reliability + EU/UK GDPR rule that governs ``_shared.css`` /
``fonts.css`` / ``fonts.ts``). The catalogue is *data* (:mod:`catalog.json`) plus
this thin loader / validator / query layer.

Two things consume it:

* **AI font pairing** (:mod:`mediahub.brand.type_pairing`) proposes pairings
  *only* from the catalogue, so the model can never pick a face MediaHub does
  not actually self-host.
* **The typography web surface** (1.9) browses it by mood / class / surface and
  merges an org's *uploaded* fonts (:mod:`mediahub.typography.font_intake`) into
  a per-org view via :func:`org_catalog` — without touching this built-in set.

The catalogue is deterministic, offline data: no network, no AI. Keeping it in
lock-step with the on-disk assets is :func:`verify_assets`' job (exercised by
``tests/test_font_catalog.py``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_CATALOG_JSON = _HERE / "catalog.json"
_REPO_ROOT = _HERE.parents[2]  # .../src/mediahub/typography -> repo root

# Asset locations per surface (mirrors the three fetch scripts).
_WEB_FONTS = _REPO_ROOT / "src" / "mediahub" / "web" / "static" / "fonts"
_WEB_CSS = _REPO_ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "fonts.css"
_RENDERER_FONTS = _REPO_ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts" / "fonts"
_RENDERER_CSS = _REPO_ROOT / "src" / "mediahub" / "graphic_renderer" / "layouts" / "_shared.css"
_REEL_FONTS = _REPO_ROOT / "src" / "mediahub" / "remotion" / "public" / "fonts"
_REEL_FONTS_TS = _REPO_ROOT / "src" / "mediahub" / "remotion" / "src" / "fonts.ts"

# Controlled vocabularies — a face whose JSON strays outside these is a catalogue
# bug, caught by load_catalog() at import time and by the test suite.
CLASS_VOCAB: tuple[str, ...] = ("display", "sans", "serif", "mono")
ROLE_VOCAB: tuple[str, ...] = ("display", "headline", "body", "numeric", "mono", "accent")
SURFACE_VOCAB: tuple[str, ...] = ("web", "renderer", "reel")
MOOD_VOCAB: tuple[str, ...] = (
    "bold",
    "impact",
    "heavy",
    "stadium",
    "loud",
    "athletic",
    "condensed",
    "poster",
    "chunky",
    "retro",
    "playful",
    "geometric",
    "modern",
    "technical",
    "clean",
    "precise",
    "neutral",
    "legible",
    "ui",
    "friendly",
    "data",
    "monospace",
    "editorial",
    "elegant",
    "expressive",
    "warm",
    "sporty",
    # reserved for per-org uploads surfaced through org_catalog()
    "custom",
    "brand",
)


class CatalogError(ValueError):
    """Raised when catalog.json is malformed or violates a controlled vocab."""


@dataclass(frozen=True)
class CatalogFont:
    """One self-hosted (or org-uploaded) typeface in the catalogue."""

    slug: str
    family: str
    klass: str
    mood_tags: tuple[str, ...]
    variable: bool
    axes: dict
    weights: tuple[int, ...]
    scripts: tuple[str, ...]
    licence: str
    source: str
    role_affinity: tuple[str, ...]
    numeral: bool
    pairs_well_with: tuple[str, ...]
    renderer_slug: Optional[str] = None
    web_slug: Optional[str] = None
    # Per-org uploaded faces (org_catalog) set these; built-ins leave them blank.
    custom: bool = False
    css_family: str = ""  # collision-safe @font-face family for uploads

    @property
    def surfaces(self) -> tuple[str, ...]:
        """Which public surfaces this face is hosted on."""
        if self.custom:
            # Uploads are rendered on the still/reel surfaces via font_intake's
            # file:// @font-face; they are not in the web UI's preload set.
            return ("renderer", "reel")
        out: list[str] = []
        if self.renderer_slug:
            out += ["renderer", "reel"]
        if self.web_slug:
            out.append("web")
        return tuple(out)

    @property
    def css_stack(self) -> str:
        """The CSS ``font-family`` value (family + a sane same-class fallback)."""
        fam = self.css_family or self.family
        generic = {"serif": "serif", "mono": "monospace"}.get(self.klass, "sans-serif")
        return f"'{fam}', {generic}"

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "family": self.family,
            "klass": self.klass,
            "mood_tags": list(self.mood_tags),
            "variable": self.variable,
            "axes": dict(self.axes),
            "weights": list(self.weights),
            "scripts": list(self.scripts),
            "licence": self.licence,
            "source": self.source,
            "role_affinity": list(self.role_affinity),
            "numeral": self.numeral,
            "pairs_well_with": list(self.pairs_well_with),
            "renderer_slug": self.renderer_slug,
            "web_slug": self.web_slug,
            "custom": self.custom,
            "css_family": self.css_family,
            "surfaces": list(self.surfaces),
        }


def _coerce_entry(raw: dict) -> CatalogFont:
    """Validate one catalog.json row against the controlled vocabularies."""
    try:
        slug = str(raw["slug"]).strip()
        family = str(raw["family"]).strip()
        klass = str(raw["klass"]).strip()
    except (KeyError, TypeError) as e:
        raise CatalogError(f"catalogue entry missing required field: {e}") from e
    if not slug or not family:
        raise CatalogError(f"catalogue entry has empty slug/family: {raw!r}")
    if klass not in CLASS_VOCAB:
        raise CatalogError(f"{slug}: class {klass!r} not in {CLASS_VOCAB}")
    moods = tuple(str(m).strip() for m in raw.get("mood_tags", []))
    for m in moods:
        if m not in MOOD_VOCAB:
            raise CatalogError(f"{slug}: mood {m!r} not in MOOD_VOCAB")
    roles = tuple(str(r).strip() for r in raw.get("role_affinity", []))
    for r in roles:
        if r not in ROLE_VOCAB:
            raise CatalogError(f"{slug}: role {r!r} not in {ROLE_VOCAB}")
    renderer_slug = raw.get("renderer_slug") or None
    web_slug = raw.get("web_slug") or None
    if not renderer_slug and not web_slug:
        raise CatalogError(f"{slug}: must host on at least one surface")
    return CatalogFont(
        slug=slug,
        family=family,
        klass=klass,
        mood_tags=moods,
        variable=bool(raw.get("variable", False)),
        axes=dict(raw.get("axes") or {}),
        weights=tuple(int(w) for w in raw.get("weights", []) or []),
        scripts=tuple(str(s).strip() for s in raw.get("scripts", []) or []),
        licence=str(raw.get("licence", "")).strip(),
        source=str(raw.get("source", "")).strip(),
        role_affinity=roles,
        numeral=bool(raw.get("numeral", False)),
        pairs_well_with=tuple(str(p).strip() for p in raw.get("pairs_well_with", []) or []),
        renderer_slug=renderer_slug,
        web_slug=web_slug,
    )


@lru_cache(maxsize=1)
def load_catalog() -> tuple[CatalogFont, ...]:
    """Load + validate the built-in catalogue (cached). Raises :class:`CatalogError`."""
    try:
        data = json.loads(_CATALOG_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CatalogError(f"could not read catalog.json: {e}") from e
    rows = data.get("fonts")
    if not isinstance(rows, list) or not rows:
        raise CatalogError("catalog.json has no `fonts` list")
    fonts = tuple(_coerce_entry(r) for r in rows)
    seen: set[str] = set()
    for f in fonts:
        if f.slug in seen:
            raise CatalogError(f"duplicate catalogue slug: {f.slug}")
        seen.add(f.slug)
    # pairs_well_with must reference real slugs (deterministic affinity graph).
    for f in fonts:
        for p in f.pairs_well_with:
            if p not in seen:
                raise CatalogError(f"{f.slug}: pairs_well_with unknown slug {p!r}")
    return fonts


def get(slug: str) -> Optional[CatalogFont]:
    """Return the catalogue face with ``slug``, or ``None``."""
    s = (slug or "").strip()
    for f in load_catalog():
        if f.slug == s:
            return f
    return None


def search(
    *,
    mood: Optional[str] = None,
    klass: Optional[str] = None,
    surface: Optional[str] = None,
    role: Optional[str] = None,
    numeral: Optional[bool] = None,
    catalog: Optional[tuple[CatalogFont, ...]] = None,
) -> list[CatalogFont]:
    """Filter the catalogue deterministically (stable catalogue order).

    All filters are ANDed. ``mood`` matches a face carrying that mood tag;
    ``role`` matches a face whose ``role_affinity`` lists it. An unknown filter
    value simply yields no matches (it never raises).
    """
    fonts = catalog if catalog is not None else load_catalog()
    out: list[CatalogFont] = []
    for f in fonts:
        if klass is not None and f.klass != klass:
            continue
        if surface is not None and surface not in f.surfaces:
            continue
        if mood is not None and mood not in f.mood_tags:
            continue
        if role is not None and role not in f.role_affinity:
            continue
        if numeral is not None and f.numeral != numeral:
            continue
        out.append(f)
    return out


def for_surface(surface: str) -> list[CatalogFont]:
    """All built-in faces hosted on ``surface`` (web | renderer | reel)."""
    return search(surface=surface)


def org_catalog(profile_id: str) -> list[CatalogFont]:
    """The built-in renderer faces plus this org's uploaded fonts.

    The per-org uploads come from :mod:`mediahub.typography.font_intake` and are
    surfaced as ``custom`` :class:`CatalogFont` rows so the web UI and the
    pairing layer can treat them uniformly. Tenant isolation is inherited from
    ``font_intake.list_fonts`` (scoped to ``DATA_DIR/custom_fonts/<profile>``).
    """
    builtins = list(load_catalog())
    uploads = _org_uploads(profile_id)
    return builtins + uploads


def _org_uploads(profile_id: str) -> list[CatalogFont]:
    if not (profile_id or "").strip():
        return []
    try:
        from mediahub.typography import font_intake as fi
    except Exception:  # pragma: no cover - font_intake always present in-tree
        return []
    out: list[CatalogFont] = []
    for rec in fi.list_fonts(profile_id):
        klass = _role_to_class(rec.role)
        out.append(
            CatalogFont(
                slug=f"upload:{rec.slug}",
                family=rec.family,
                klass=klass,
                mood_tags=("custom", "brand"),
                variable=False,
                axes={},
                weights=(int(rec.weight),),
                scripts=("latin", "latin-ext"),
                licence="uploaded — embedding attested by the club",
                source="org upload",
                role_affinity=(rec.role,) if rec.role in ROLE_VOCAB else (),
                numeral=rec.role in ("numeric", "mono"),
                pairs_well_with=(),
                renderer_slug=None,
                web_slug=None,
                custom=True,
                css_family=rec.css_family,
            )
        )
    return out


def _role_to_class(role: str) -> str:
    return {
        "display": "display",
        "headline": "display",
        "body": "sans",
        "numeric": "mono",
        "mono": "mono",
        "accent": "sans",
    }.get(role, "sans")


def verify_assets() -> list[str]:
    """Return a list of lock-step problems between the catalogue and disk.

    Empty list == every built-in face's woff2 and ``@font-face`` declaration are
    present on each surface it claims. Used by ``tests/test_font_catalog.py`` so
    a face can never drift out of sync with its assets (or sneak a CDN back in).
    """
    problems: list[str] = []
    web_css = _read(_WEB_CSS)
    renderer_css = _read(_RENDERER_CSS)
    reel_ts = _read(_REEL_FONTS_TS)
    for f in load_catalog():
        if f.renderer_slug:
            rp = _RENDERER_FONTS / f"{f.renderer_slug}.woff2"
            if not rp.is_file():
                problems.append(f"{f.slug}: missing renderer woff2 {rp.name}")
            ep = _REEL_FONTS / f"{f.renderer_slug}.woff2"
            if not ep.is_file():
                problems.append(f"{f.slug}: missing reel woff2 {ep.name}")
            if f"'{f.family}'" not in renderer_css:
                problems.append(f"{f.slug}: family {f.family!r} not in _shared.css")
            if f'"{f.family}"' not in reel_ts and f"'{f.family}'" not in reel_ts:
                problems.append(f"{f.slug}: family {f.family!r} not in fonts.ts")
        if f.web_slug:
            hits = list(_WEB_FONTS.glob(f"{f.web_slug}-*.woff2"))
            if not hits:
                problems.append(f"{f.slug}: no web woff2 {f.web_slug}-*.woff2")
            if f"'{f.family}'" not in web_css:
                problems.append(f"{f.slug}: family {f.family!r} not in fonts.css")
    return problems


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CatalogFont",
    "CatalogError",
    "CLASS_VOCAB",
    "ROLE_VOCAB",
    "SURFACE_VOCAB",
    "MOOD_VOCAB",
    "load_catalog",
    "get",
    "search",
    "for_surface",
    "org_catalog",
    "verify_assets",
]
