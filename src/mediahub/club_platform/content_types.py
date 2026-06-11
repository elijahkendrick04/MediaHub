"""
ContentType enum + ContentTypeMeta dataclass + REGISTRY dict.

REGISTRY is the single source of truth for every content type the platform
knows about.  is_implemented=True → the route generates real output.
is_implemented=False → the route renders a stub page with the input_contract
so the user knows what is coming.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContentType(str, Enum):
    """The implemented-surface badge (ADR-0013).

    Every value IS a canonical taxonomy slug from docs/POST_TYPE_TAXONOMY.md
    (subset invariant, pinned by tests/test_post_types.py). The full planning
    vocabulary lives in club_platform.post_types + the sport-profile YAML;
    this enum only names the slugs with a real product surface, so it never
    grows a member for a merely-planned type. Legacy persisted strings
    ("weekend_preview", "sponsor_post") are normalised at read boundaries via
    post_types.canonical_slug().
    """

    MEET_RECAP = "meet_recap"
    ATHLETE_SPOTLIGHT = "athlete_spotlight"
    EVENT_PREVIEW = "event_preview"
    SPONSOR_ACTIVATION = "sponsor_activation"
    SESSION_UPDATE = "session_update"
    FREE_TEXT = "free_text"


@dataclass
class ContentTypeMeta:
    type: ContentType
    title: str  # e.g. "Meet Recap"
    description: str  # short — what it produces
    input_contract: str  # what input is required (long-form)
    is_implemented: bool  # if False, route renders a stub page
    icon_svg: str  # tiny inline SVG for navigation cards
    primary_route_endpoint: str  # url_for endpoint name


# --- Icon SVGs (inline, 24×24 viewBox) ---

_WAVES_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<path d="M2 12c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>'
    '<path d="M2 17c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>'
    '<path d="M2 7c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>'
    "</svg>"
)

_PERSON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<circle cx="12" cy="8" r="4"/>'
    '<path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>'
    "</svg>"
)

_CALENDAR_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
    '<line x1="16" y1="2" x2="16" y2="6"/>'
    '<line x1="8" y1="2" x2="8" y2="6"/>'
    '<line x1="3" y1="10" x2="21" y2="10"/>'
    "</svg>"
)

_STAR_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>'
    "</svg>"
)

_SESSION_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<polyline points="14 2 14 8 20 8"/>'
    '<line x1="16" y1="13" x2="8" y2="13"/>'
    '<line x1="16" y1="17" x2="8" y2="17"/>'
    '<polyline points="10 9 9 9 8 9"/>'
    "</svg>"
)


_PENCIL_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
    '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
    '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>'
    "</svg>"
)


REGISTRY: dict[ContentType, ContentTypeMeta] = {
    ContentType.MEET_RECAP: ContentTypeMeta(
        type=ContentType.MEET_RECAP,
        title="Meet Recap",
        description="Turn a meet results file into ranked, source-grounded content cards.",
        input_contract=(
            "Upload a Hytek Meet Manager file (.hy3) or a zip containing one. "
            "Optional: a pre-meet PB snapshot will be fetched from a public PB "
            "source (chosen automatically) for accurate PB claims. Requires a "
            "configured club profile so the pipeline knows which swimmers are yours."
        ),
        is_implemented=True,
        icon_svg=_WAVES_SVG,
        primary_route_endpoint="upload",
    ),
    ContentType.ATHLETE_SPOTLIGHT: ContentTypeMeta(
        type=ContentType.ATHLETE_SPOTLIGHT,
        title="Athlete Spotlight",
        description="One swimmer's story from the meet — every achievement, ranked.",
        input_contract=(
            "Pick a swimmer from any processed meet. We'll generate a single-athlete "
            "recognition view with every achievement they earned, ranked by impact. "
            "Ideal for a post-meet 'swimmer of the weekend' feature."
        ),
        is_implemented=True,
        icon_svg=_PERSON_SVG,
        primary_route_endpoint="spotlight_landing",
    ),
    ContentType.EVENT_PREVIEW: ContentTypeMeta(
        type=ContentType.EVENT_PREVIEW,
        title="Event Preview",
        description="Tease upcoming athletes and story angles before an event.",
        input_contract=(
            "Tell us the event name, date / venue, athletes to watch, and any story angles. "
            "We generate Instagram, Stories and Twitter preview captions ready to edit and post. "
            "Full entry-list parsing is coming next — this form already produces usable cards."
        ),
        is_implemented=True,
        icon_svg=_CALENDAR_SVG,
        primary_route_endpoint="stub_weekend_preview",
    ),
    ContentType.SPONSOR_ACTIVATION: ContentTypeMeta(
        type=ContentType.SPONSOR_ACTIVATION,
        title="Sponsor Post",
        description="Brand-safe highlight posts for sponsor activation.",
        input_contract=(
            "Tell us the sponsor, the event, the key achievement, and any brand rules. "
            "We generate sponsor-friendly captions that lead with the moment and make the partnership feel natural. "
            "Pipeline integration with processed meets comes next."
        ),
        is_implemented=True,
        icon_svg=_STAR_SVG,
        primary_route_endpoint="stub_sponsor_post",
    ),
    ContentType.SESSION_UPDATE: ContentTypeMeta(
        type=ContentType.SESSION_UPDATE,
        title="Session Update",
        description="Quick in-session updates for Stories and live coverage.",
        input_contract=(
            "Type the event, what's happened so far, and the current session. "
            "We generate short Stories + Twitter cards ready to share mid-event. "
            "Live partial-results parsing is on the roadmap."
        ),
        is_implemented=True,
        icon_svg=_SESSION_SVG,
        primary_route_endpoint="stub_session_update",
    ),
    ContentType.FREE_TEXT: ContentTypeMeta(
        type=ContentType.FREE_TEXT,
        title="Free Text",
        description="Describe any moment and get content suggestions.",
        input_contract=(
            "Type or paste a description of anything — a result, an event, a milestone, "
            "a training session. We identify the strongest social angles and draft platform-ready cards."
        ),
        is_implemented=True,
        icon_svg=_PENCIL_SVG,
        primary_route_endpoint="free_text_chat_page",
    ),
}
