"""The canonical post-type vocabulary (P1.2) — slugs first, enum as badge.

This module realises ``docs/POST_TYPE_TAXONOMY.md`` in code, per ADR-0013:

* The **canonical identity** of a post type is its taxonomy **slug**
  (``event_preview``, ``pb_spotlight``, ``full_time_score`` …). Universal
  slugs are declared here; sport-specific slugs live in the sport-profile
  YAML (``data/sport_profiles/*.yaml``, loaded via ``mediahub.sport_profiles``).
* ``club_platform.content_types.ContentType`` is the **implemented-surface
  badge**: a small enum naming the slugs that have a real, clickable product
  surface today. Every enum value IS a canonical slug (subset invariant,
  pinned by ``tests/test_post_types.py``); the enum never grows a member for
  a merely-planned type.
* Two **legacy aliases** map the pre-ADR-0013 enum strings that persist in
  old ``DATA_DIR`` data (per-org autonomy policy keys, saved stub packs) to
  their canonical slugs. Persistence boundaries call :func:`canonical_slug`
  on read so old data keeps working and operator-set autonomy levels are
  never silently reset.

The P1.3 planner enumerates a sport's post types through
:func:`post_types_for` and bridges to product surfaces via
:func:`implemented_content_type`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mediahub.club_platform.content_types import REGISTRY, ContentType
from mediahub.sport_profiles import SportProfile
from mediahub.sport_profiles.schema import PostTypeConfig

# ---------------------------------------------------------------------------
# Legacy aliases — the pre-ADR-0013 enum strings still present in persisted
# DATA_DIR data. Read boundaries normalise through canonical_slug(); writes
# always use the canonical slug. Permanent but tiny, and test-pinned.
# ---------------------------------------------------------------------------

LEGACY_ALIASES: dict[str, str] = {
    "weekend_preview": "event_preview",
    "sponsor_post": "sponsor_activation",
}

# ---------------------------------------------------------------------------
# Universal post types — taxonomy §3, verbatim slugs. These are meaningful
# for any team in any sport; a sport profile chooses which ones it enables.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniversalPostType:
    slug: str
    title: str
    description: str


UNIVERSAL_POST_TYPES: tuple[UniversalPostType, ...] = (
    UniversalPostType(
        "fixture_announcement",
        "Fixture Announcement",
        "Upcoming game/meet/race announcement.",
    ),
    UniversalPostType(
        "result_recap",
        "Result Recap",
        "Score/result summary after an event.",
    ),
    UniversalPostType(
        "athlete_spotlight",
        "Athlete Spotlight",
        "One athlete's story or achievement.",
    ),
    UniversalPostType(
        "event_preview",
        "Event Preview",
        "Tease athletes and story angles before an event.",
    ),
    UniversalPostType(
        "milestone_celebration",
        "Milestone Celebration",
        "Caps, records, anniversaries, first-evers.",
    ),
    UniversalPostType(
        "birthday",
        "Birthday",
        "Athlete or club birthday.",
    ),
    UniversalPostType(
        "signings_recruitment",
        "Signings & Recruitment",
        "New member or signing announcement.",
    ),
    UniversalPostType(
        "sponsor_activation",
        "Sponsor Activation",
        "Sponsor thank-you / activation post.",
    ),
    UniversalPostType(
        "ticket_merch_promo",
        "Tickets & Merch",
        "Tickets, merch or fundraiser push.",
    ),
    UniversalPostType(
        "behind_the_scenes",
        "Behind the Scenes",
        "Training, travel and community moments.",
    ),
    UniversalPostType(
        "season_recap",
        "Season Recap",
        "End-of-season or mid-season wrap.",
    ),
    UniversalPostType(
        "this_day_in_history",
        "This Day in History",
        "“On this day…” archive post.",
    ),
    UniversalPostType(
        "session_update",
        "Session Update",
        "Live, mid-event Stories update.",
    ),
    UniversalPostType(
        "free_text",
        "Free Text",
        "Any described moment turned into drafted cards.",
    ),
)

_UNIVERSAL_BY_SLUG: dict[str, UniversalPostType] = {u.slug: u for u in UNIVERSAL_POST_TYPES}


def universal_slugs() -> tuple[str, ...]:
    """The taxonomy's universal post-type slugs, in doc order."""
    return tuple(u.slug for u in UNIVERSAL_POST_TYPES)


def is_universal(slug: str) -> bool:
    return canonical_slug(slug) in _UNIVERSAL_BY_SLUG


# ---------------------------------------------------------------------------
# Canonicalisation + the implemented-surface bridge
# ---------------------------------------------------------------------------


def canonical_slug(value: object) -> str:
    """Normalise any post-type string to its canonical taxonomy slug.

    Lower-cases, trims, converts spaces/hyphens to underscores, and maps the
    pre-ADR-0013 legacy enum strings to their canonical slugs. Unknown values
    are returned normalised (not invented, not dropped) — callers that need
    membership use :func:`is_universal` / profile lookups.
    """
    s = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return LEGACY_ALIASES.get(s, s)


def implemented_content_type(slug: object) -> Optional[ContentType]:
    """The implemented-surface badge for ``slug``, or None when the type is
    planning vocabulary only (no clickable product surface yet)."""
    try:
        return ContentType(canonical_slug(slug))
    except ValueError:
        return None


def is_implemented(slug: object) -> bool:
    return implemented_content_type(slug) is not None


def implemented_slugs() -> tuple[str, ...]:
    """Canonical slugs that have a product surface today (the enum values)."""
    return tuple(ct.value for ct in ContentType)


def title_for(slug: str) -> str:
    """Human title for a slug: registry title for implemented surfaces,
    taxonomy title for universal types, titleised slug otherwise."""
    c = canonical_slug(slug)
    ct = implemented_content_type(c)
    if ct is not None:
        return REGISTRY[ct].title
    uni = _UNIVERSAL_BY_SLUG.get(c)
    if uni is not None:
        return uni.title
    return c.replace("_", " ").title()


# ---------------------------------------------------------------------------
# The per-sport merged view the planner consumes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SportPostType:
    """One post type as a sport profile declares it, bridged to the product.

    ``content_type`` is the implemented-surface badge (None for
    planning-vocabulary-only types); ``config`` carries the profile's four
    axes (enabled / data_inputs / template_namespace / default_autonomy).
    """

    slug: str
    title: str
    sport: str
    universal: bool
    config: PostTypeConfig
    content_type: Optional[ContentType]


def post_types_for(profile: SportProfile, *, enabled_only: bool = True) -> list[SportPostType]:
    """The sport's post types as canonical, bridged records, in slug order."""
    out: list[SportPostType] = []
    for raw_slug, cfg in sorted(profile.post_types.items()):
        if enabled_only and not cfg.enabled:
            continue
        slug = canonical_slug(raw_slug)
        out.append(
            SportPostType(
                slug=slug,
                title=title_for(slug),
                sport=profile.sport,
                universal=is_universal(slug),
                config=cfg,
                content_type=implemented_content_type(slug),
            )
        )
    return out


__all__ = [
    "LEGACY_ALIASES",
    "UNIVERSAL_POST_TYPES",
    "UniversalPostType",
    "SportPostType",
    "canonical_slug",
    "implemented_content_type",
    "implemented_slugs",
    "is_implemented",
    "is_universal",
    "post_types_for",
    "title_for",
    "universal_slugs",
]
