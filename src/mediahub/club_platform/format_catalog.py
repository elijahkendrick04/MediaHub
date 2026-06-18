"""The smart format catalogue (P6.1) — every club design type as data.

MediaHub already renders feed/story/reel cards from run data + a ``BrandKit``.
This module generalises that into a **format catalogue**: one registry of the
off-feed and per-channel design formats a club actually needs — certificates,
posters, coach contact cards, season calendars, phone wallpapers, plus a
per-platform size preset for every social channel — each declared as a typed,
deterministic :class:`FormatSpec`.

Design rules this module obeys:

* **Pure data, no AI, no I/O.** A :class:`FormatSpec` is canvas size + safe
  zones + which archetypes suit it + which run data it needs. Building the
  registry touches no network and no provider. The *judgement* half of P6.1 —
  "which archetype re-lays-out this design for a square canvas" — lives in
  :mod:`mediahub.turn_into.transform`, behind the design-spec director with the
  deterministic archetype picker as the honest no-LLM floor.
* **The renderer is untouched.** ``graphic_renderer.render_brief`` already
  accepts an explicit ``size=(w, h)`` and adapts the composition to the aspect
  (``_format_aspect``). A :class:`FormatSpec` is therefore just the ``(w, h)``
  (plus metadata) the transformer threads into the existing render path — no
  new rendering engine, no per-format template.
* **Per-sport availability comes from the sport profile.** A format that needs
  a particular kind of run data declares it in ``requires_post_types``;
  :func:`formats_for_sport` keeps a format only when the sport profile enables
  at least one of those post types. Universal formats (every social size, a
  poster, a wallpaper) declare nothing and are always available.

Multi-page formats (programmes, yearbooks, prospectuses) are deliberately NOT
registered here — they compose existing single renders into a paged PDF via the
P6.12 document engine, and print-ready CMYK output is P6.19. The ``bleed_mm`` /
``dpi`` fields are carried now so those packages have the geometry waiting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from mediahub.club_platform.post_types import canonical_slug

# ---------------------------------------------------------------------------
# Aspect classification — mirrors graphic_renderer.render._format_aspect so the
# catalogue and the renderer agree on what a canvas "is". Kept as an
# independent public function (the renderer's is private) and cross-checked by
# tests/test_format_catalog.py so the two can never silently drift.
# ---------------------------------------------------------------------------

ASPECT_CLASSES: tuple[str, ...] = (
    "square",
    "portrait",
    "story",
    "landscape_43",
    "landscape_32",
    "landscape_169",
)


def aspect_class(width: int, height: int) -> str:
    """Classify a canvas into the renderer's composition family.

    Thresholds are identical to ``graphic_renderer.render._format_aspect``:
    a tall canvas is ``story`` at ≥1.7:1 else ``portrait``; a wide canvas snaps
    to the nearest of 4:3 / 3:2 / 16:9 at the midpoints between them.
    """
    if width <= 0 or height <= 0:
        raise ValueError("format dimensions must be positive")
    if width == height:
        return "square"
    if height > width:
        return "story" if (height / width) >= 1.7 else "portrait"
    ratio = width / height
    if ratio >= 1.64:
        return "landscape_169"
    if ratio >= 1.42:
        return "landscape_32"
    return "landscape_43"


# Coarse orientation bucket the transformer keys its archetype sets on.
_ASPECT_BUCKET: dict[str, str] = {
    "square": "square",
    "portrait": "tall",
    "story": "tall",
    "landscape_43": "wide",
    "landscape_32": "wide",
    "landscape_169": "wide",
}


def orientation_of(width: int, height: int) -> str:
    """``portrait`` | ``square`` | ``landscape`` — the plain human orientation."""
    if width == height:
        return "square"
    return "portrait" if height > width else "landscape"


# ---------------------------------------------------------------------------
# Preferred archetypes per orientation bucket. These are the v2 archetype slugs
# whose composition reads well at that aspect. The transformer intersects them
# with the *live* archetype library (``graphic_renderer.archetypes``) at call
# time, so a missing archetype is skipped rather than crashing a re-layout.
# ---------------------------------------------------------------------------

ARCHETYPES_BY_BUCKET: dict[str, tuple[str, ...]] = {
    "tall": (
        "split_diagonal_hero",
        "big_number_dominant",
        "full_height_portrait_split",
        "mega_surname_bleed",
        "minimal_type_poster",
        "vertical_stat_tower",
        "magazine_cover",
    ),
    "square": (
        "centered_medal_spotlight",
        "big_number_dominant",
        "editorial_numbers_grid",
        "spotlight_disc",
        "index_card",
        "cornerstone_numeral",
        "photo_passepartout",
    ),
    "wide": (
        "full_bleed_photo_lower_third",
        "editorial_numbers_grid",
        "broadcast_scorebug",
        "horizon_band",
        "ticker_strip",
        "three_card_editorial_grid",
        "scoreline_versus",
        "stat_stack_sidebar",
    ),
}


# Catalogue categories, in the order the UI groups them.
CATEGORIES: tuple[str, ...] = (
    "social_size",
    "carousel",
    "poster",
    "certificate",
    "card",
    "document",
    "calendar",
    "wallpaper",
    "custom",
)


@dataclass(frozen=True)
class FormatSpec:
    """One club design format — a named canvas with everything a re-layout needs.

    ``width``/``height`` are pixels (the renderer's native unit). ``render_name``
    is the ``format_name`` the renderer files the PNG under; it defaults to the
    slug but reuses an existing renderer format name when the size matches one,
    so well-known sizes keep consistent filenames. ``archetypes`` is an optional
    override of the per-aspect preferred set; empty means "use the aspect
    default". ``requires_post_types`` are canonical taxonomy slugs whose run
    data this format needs — empty means universal.
    """

    slug: str
    title: str
    category: str
    width: int
    height: int
    render_format: str = ""
    description: str = ""
    safe_top: int = 0
    safe_bottom: int = 0
    safe_left: int = 0
    safe_right: int = 0
    bleed_mm: float = 0.0
    dpi: int = 0  # 0 = screen-native (no physical print intent)
    archetypes: tuple[str, ...] = ()
    caption_style: str = ""
    requires_post_types: tuple[str, ...] = ()
    sports: tuple[str, ...] = ()  # () = every sport
    custom: bool = False

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def render_name(self) -> str:
        """The renderer ``format_name`` to file this format under."""
        return self.render_format or self.slug

    @property
    def aspect(self) -> str:
        return aspect_class(self.width, self.height)

    @property
    def bucket(self) -> str:
        return _ASPECT_BUCKET[self.aspect]

    @property
    def orientation(self) -> str:
        return orientation_of(self.width, self.height)

    @property
    def is_print(self) -> bool:
        """True when this format carries physical print intent (bleed or dpi)."""
        return self.bleed_mm > 0 or self.dpi > 0

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "category": self.category,
            "width": self.width,
            "height": self.height,
            "render_name": self.render_name,
            "description": self.description,
            "aspect": self.aspect,
            "orientation": self.orientation,
            "safe": {
                "top": self.safe_top,
                "bottom": self.safe_bottom,
                "left": self.safe_left,
                "right": self.safe_right,
            },
            "bleed_mm": self.bleed_mm,
            "dpi": self.dpi,
            "caption_style": self.caption_style,
            "requires_post_types": list(self.requires_post_types),
            "sports": list(self.sports),
            "is_print": self.is_print,
            "custom": self.custom,
        }


# ---------------------------------------------------------------------------
# The registry. Sizes follow widely-cited 2026 platform specs; off-feed club
# formats use sensible screen-native pixel canvases (print readiness ↗ P6.19).
# ---------------------------------------------------------------------------

# Run data that means "this club produces achievement/result content" — the
# trigger for certificates, athlete one-pagers and the like. Any one enabled
# post type from this set is enough (sport-agnostic: swimming's pb_spotlight,
# football's full_time_score, athletics' podium_recap all qualify).
_ACHIEVEMENT_INPUTS: tuple[str, ...] = (
    "result_recap",
    "meet_recap",
    "athlete_spotlight",
    "pb_spotlight",
    "final_box_score",
    "player_of_the_game",
    "podium_recap",
    "finish_time_spotlight",
)

_CATALOG: tuple[FormatSpec, ...] = (
    # --- Per-channel social size presets (universal) ----------------------
    FormatSpec(
        "ig_post",
        "Instagram post",
        "social_size",
        1080,
        1350,
        render_format="feed_portrait",
        description="Portrait 4:5 in-feed post — the highest-reach feed size.",
        caption_style="feed",
    ),
    FormatSpec(
        "ig_square",
        "Instagram square",
        "social_size",
        1080,
        1080,
        render_format="feed_square",
        description="Classic 1:1 feed post.",
        caption_style="feed",
    ),
    FormatSpec(
        "ig_story",
        "Instagram / Reel story",
        "social_size",
        1080,
        1920,
        render_format="story",
        description="Full-screen 9:16 story or reel cover.",
        safe_top=250,
        safe_bottom=250,
        caption_style="story",
    ),
    FormatSpec(
        "ig_reel_cover",
        "Reel cover",
        "social_size",
        1080,
        1920,
        render_format="reel_cover",
        description="9:16 cover frame for a reel, designed for the grid crop.",
        safe_top=250,
        safe_bottom=420,
        caption_style="story",
    ),
    FormatSpec(
        "fb_post",
        "Facebook post",
        "social_size",
        1080,
        1080,
        render_format="feed_square",
        description="Square Facebook feed post.",
        caption_style="feed",
    ),
    FormatSpec(
        "fb_cover",
        "Facebook cover",
        "social_size",
        1640,
        624,
        description="Facebook Page cover banner (16:6-ish).",
        caption_style="banner",
    ),
    FormatSpec(
        "fb_event_cover",
        "Facebook event cover",
        "social_size",
        1920,
        1005,
        description="Facebook event header.",
        caption_style="banner",
    ),
    FormatSpec(
        "x_post",
        "X / Twitter post",
        "social_size",
        1600,
        900,
        description="16:9 in-feed image for X / Twitter.",
        caption_style="feed",
    ),
    FormatSpec(
        "x_header",
        "X / Twitter header",
        "social_size",
        1500,
        500,
        description="X / Twitter profile header (3:1).",
        caption_style="banner",
    ),
    FormatSpec(
        "linkedin_post",
        "LinkedIn post",
        "social_size",
        1200,
        1200,
        description="Square LinkedIn feed post.",
        caption_style="feed",
    ),
    FormatSpec(
        "linkedin_banner",
        "LinkedIn banner",
        "social_size",
        1584,
        396,
        description="LinkedIn Page / profile cover (4:1).",
        caption_style="banner",
    ),
    FormatSpec(
        "pinterest_pin",
        "Pinterest pin",
        "social_size",
        1000,
        1500,
        description="Tall 2:3 Pinterest pin.",
        caption_style="feed",
    ),
    FormatSpec(
        "tiktok_video",
        "TikTok cover",
        "social_size",
        1080,
        1920,
        render_format="story",
        description="9:16 TikTok cover / first frame.",
        safe_top=250,
        safe_bottom=250,
        caption_style="story",
    ),
    FormatSpec(
        "youtube_thumbnail",
        "YouTube thumbnail",
        "social_size",
        1280,
        720,
        description="16:9 YouTube thumbnail.",
        caption_style="banner",
    ),
    FormatSpec(
        "youtube_banner",
        "YouTube banner",
        "social_size",
        2560,
        1440,
        description="YouTube channel art; key content sits in the 1546×423 safe area.",
        safe_top=508,
        safe_bottom=509,
        safe_left=507,
        safe_right=507,
        caption_style="banner",
    ),
    # --- Carousel ----------------------------------------------------------
    FormatSpec(
        "carousel_slide",
        "Carousel slide",
        "carousel",
        1080,
        1080,
        render_format="carousel_slide",
        description="One 1:1 slide in a multi-image carousel.",
        caption_style="feed",
    ),
    # --- Posters & flyers (universal) -------------------------------------
    FormatSpec(
        "poster",
        "Poster",
        "poster",
        1080,
        1350,
        archetypes=("magazine_cover", "minimal_type_poster", "split_diagonal_hero"),
        description="Portrait club poster — fixtures, galas, open days.",
        caption_style="poster",
    ),
    FormatSpec(
        "flyer",
        "Flyer",
        "poster",
        874,
        1240,
        archetypes=("minimal_type_poster", "magazine_cover", "editorial_numbers_grid"),
        description="A5-proportion handout flyer.",
        bleed_mm=3.0,
        dpi=150,
        caption_style="poster",
    ),
    FormatSpec(
        "event_poster",
        "Event banner",
        "poster",
        1920,
        1080,
        archetypes=("horizon_band", "full_bleed_photo_lower_third", "broadcast_scorebug"),
        description="Wide event / fixture announcement banner.",
        caption_style="banner",
    ),
    # --- Certificates (need achievement data) -----------------------------
    FormatSpec(
        "certificate",
        "Certificate",
        "certificate",
        1754,
        1240,
        archetypes=("centered_medal_spotlight", "minimal_type_poster", "ribbon_banner"),
        description=(
            "A4-landscape achievement certificate (PB / medal / participation). "
            "Re-targets a card's design to a framed certificate canvas; the bulk "
            "per-achievement certificate export ships separately on the pack."
        ),
        bleed_mm=3.0,
        dpi=150,
        requires_post_types=_ACHIEVEMENT_INPUTS,
        caption_style="formal",
    ),
    # --- Cards (universal) -------------------------------------------------
    FormatSpec(
        "coach_card",
        "Coach contact card",
        "card",
        1050,
        600,
        archetypes=("index_card", "horizon_band", "stat_stack_sidebar"),
        description="Business-card-proportion coach / committee contact card.",
        bleed_mm=3.0,
        dpi=300,
        caption_style="formal",
    ),
    FormatSpec(
        "quote_card",
        "Quote card",
        "card",
        1080,
        1080,
        archetypes=("quote_led_recap", "minimal_type_poster", "index_card"),
        description="Square coach / athlete quote card.",
        caption_style="feed",
    ),
    # --- Documents (need achievement data) --------------------------------
    FormatSpec(
        "athlete_one_pager",
        "Athlete one-pager",
        "document",
        1240,
        1754,
        archetypes=("stat_stack_sidebar", "editorial_numbers_grid", "timeline_progression"),
        description="A4-portrait athlete CV / recruitment sheet from PBs + spotlight data.",
        bleed_mm=3.0,
        dpi=150,
        requires_post_types=_ACHIEVEMENT_INPUTS,
        caption_style="formal",
    ),
    # --- Calendars (need fixtures) ----------------------------------------
    FormatSpec(
        "season_calendar",
        "Season calendar",
        "calendar",
        1080,
        1350,
        archetypes=("editorial_numbers_grid", "stat_stack_sidebar", "minimal_type_poster"),
        description="Portrait season fixture calendar from key dates.",
        requires_post_types=("fixture_announcement",),
        caption_style="feed",
    ),
    # --- Wallpapers (universal) -------------------------------------------
    FormatSpec(
        "club_wallpaper_phone",
        "Phone wallpaper",
        "wallpaper",
        1080,
        1920,
        render_format="story",
        archetypes=("mega_surname_bleed", "minimal_type_poster", "full_height_portrait_split"),
        description="9:16 phone wallpaper for fans / parents from brand tokens.",
        caption_style="none",
    ),
    FormatSpec(
        "club_wallpaper_desktop",
        "Desktop wallpaper",
        "wallpaper",
        1920,
        1080,
        render_format="landscape",
        archetypes=("horizon_band", "full_bleed_photo_lower_third", "minimal_type_poster"),
        description="16:9 desktop wallpaper from brand tokens.",
        caption_style="none",
    ),
)

# Fast lookups, validated for slug-uniqueness at import.
_BY_SLUG: dict[str, FormatSpec] = {}
for _spec in _CATALOG:
    if _spec.slug in _BY_SLUG:  # pragma: no cover - guards a developer typo
        raise ValueError(f"duplicate FormatSpec slug: {_spec.slug}")
    _BY_SLUG[_spec.slug] = _spec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def all_formats() -> tuple[FormatSpec, ...]:
    """Every registered format, in catalogue (category) order."""
    return _CATALOG


def format_for(slug: object) -> Optional[FormatSpec]:
    """The :class:`FormatSpec` for ``slug`` (canonicalised), or ``None``."""
    return _BY_SLUG.get(canonical_slug(slug))


def is_known(slug: object) -> bool:
    return canonical_slug(slug) in _BY_SLUG


def formats_in_category(category: str) -> list[FormatSpec]:
    """Formats in one category, in registry order."""
    return [f for f in _CATALOG if f.category == category]


def categories() -> tuple[str, ...]:
    """Catalogue categories that actually carry at least one format, in order."""
    present = {f.category for f in _CATALOG}
    return tuple(c for c in CATEGORIES if c in present)


def _enabled_post_type_slugs(profile) -> set[str]:
    """Canonical enabled post-type slugs for a sport profile (tolerant)."""
    try:
        return {canonical_slug(s) for s in profile.enabled_post_types()}
    except Exception:
        return set()


def formats_for_sport(sport: Union[str, "object", None]) -> list[FormatSpec]:
    """The formats available to one sport, sourced from its sport profile.

    ``sport`` may be a sport slug (loaded via ``sport_profiles``), an already
    loaded ``SportProfile``, or ``None`` (returns every universal format only —
    nothing that needs sport-specific run data). A format is kept when it is
    universal (no ``requires_post_types``, no ``sports`` restriction) or when
    the profile both allows the sport and enables at least one required post
    type.
    """
    profile = None
    sport_name = ""
    if sport is None:
        sport_name = ""
    elif isinstance(sport, str):
        sport_name = canonical_slug(sport)
        try:
            from mediahub.sport_profiles import load_sport_profile

            profile = load_sport_profile(sport)
        except Exception:
            profile = None
    else:
        profile = sport
        sport_name = canonical_slug(getattr(profile, "sport", "") or "")

    enabled = _enabled_post_type_slugs(profile) if profile is not None else set()

    out: list[FormatSpec] = []
    for f in _CATALOG:
        if f.sports and sport_name not in {canonical_slug(s) for s in f.sports}:
            continue
        if f.requires_post_types:
            needed = {canonical_slug(s) for s in f.requires_post_types}
            if not (needed & enabled):
                continue
        out.append(f)
    return out


def preferred_archetypes(spec: FormatSpec, *, available: Optional[list[str]] = None) -> list[str]:
    """The archetype slugs that suit ``spec``, intersected with what's live.

    Returns the format's explicit ``archetypes`` override when set, else the
    per-orientation default set. When ``available`` (the live archetype library)
    is given, the result is filtered to it and order-preserved; an empty result
    means the caller should fall back to the global archetype picker.
    """
    wanted = list(spec.archetypes) if spec.archetypes else list(ARCHETYPES_BY_BUCKET[spec.bucket])
    if available is None:
        return wanted
    live = set(available)
    return [a for a in wanted if a in live]


# Bounds for custom canvases: small enough to render fast, large enough for
# print at sensible dpi; rejects absurd / resource-abusive sizes.
_MIN_PX = 200
_MAX_PX = 10000
_UNIT_PER_INCH = {"in": 1.0, "inch": 1.0, "mm": 25.4, "cm": 2.54, "px": 0.0}


def custom_format(
    width: float,
    height: float,
    *,
    unit: str = "px",
    dpi: int = 300,
    slug: str = "custom",
    title: str = "",
    category: str = "custom",
) -> FormatSpec:
    """Build a one-off :class:`FormatSpec` for a custom size (px / mm / cm / in).

    Physical units are converted to pixels at ``dpi``. The result is validated
    to a sane pixel range so a custom size can never request a resource-abusive
    canvas. Raises ``ValueError`` on an unknown unit or out-of-range result.
    """
    u = (unit or "px").strip().lower()
    if u not in _UNIT_PER_INCH:
        raise ValueError(f"unknown unit: {unit!r} (use px, mm, cm or in)")
    if width <= 0 or height <= 0:
        raise ValueError("custom dimensions must be positive")
    if u == "px":
        w_px, h_px = int(round(width)), int(round(height))
        carries_print = False
    else:
        if dpi <= 0:
            raise ValueError("dpi must be positive for physical units")
        per_inch = _UNIT_PER_INCH[u]
        w_px = int(round(width / per_inch * dpi))
        h_px = int(round(height / per_inch * dpi))
        carries_print = True
    for v in (w_px, h_px):
        if v < _MIN_PX or v > _MAX_PX:
            raise ValueError(
                f"custom size {w_px}×{h_px}px out of range ({_MIN_PX}–{_MAX_PX}px per side)"
            )
    return FormatSpec(
        slug=canonical_slug(slug) or "custom",
        title=title or f"Custom {w_px}×{h_px}",
        category=category if category in CATEGORIES else "custom",
        width=w_px,
        height=h_px,
        description=f"Custom {width:g}{u} × {height:g}{u} canvas.",
        dpi=dpi if carries_print else 0,
        caption_style="feed",
        custom=True,
    )


__all__ = [
    "FormatSpec",
    "ASPECT_CLASSES",
    "ARCHETYPES_BY_BUCKET",
    "CATEGORIES",
    "aspect_class",
    "orientation_of",
    "all_formats",
    "format_for",
    "is_known",
    "formats_in_category",
    "categories",
    "formats_for_sport",
    "preferred_archetypes",
    "custom_format",
]
