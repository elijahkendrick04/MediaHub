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


@dataclass(frozen=True)
class HowItWorks:
    """Per-content-type "how it works" first-slide content (UI only).

    Drives the Create → heading intro slide (``/make/<type>``): a homepage-style
    ``you give → the engine → you get`` diagram plus a few numbered steps. Pure
    presentation copy + icon *keys* (resolved to glyphs by the web renderer);
    it touches no engine, AI or data surface.

    Optional on :class:`ContentTypeMeta`. When a content type omits it, the
    intro renderer derives a sensible default from the existing ``description``
    and ``title`` — so a half-built tile never renders broken. That default is
    a **safety net only**: every tile surfaced under Create MUST author its own
    tile-specific ``HowItWorks``. Adding a new tile therefore means authoring a
    new "how it works" for it — a contract enforced by
    ``tests/test_content_intro.py`` (the suite fails until the new tile has its
    own non-empty, distinct slide).
    """

    tagline: str  # one-line promise shown under the title
    inputs: tuple[tuple[str, str], ...]  # (label, icon_key) — "what you give"
    steps: tuple[str, ...]  # 2–4 numbered steps describing the flow
    # The engine node's process line — the centre of the graphic, e.g.
    # "detect · rank · brand · generate". Authored per tile so each graphic
    # depicts THAT tile's actual functionality, not a generic pipeline. Empty
    # falls back to the canonical phrase (safety net); the per-tile guard test
    # requires every surfaced tile to author its own distinct line.
    engine_process: str = ""


@dataclass
class ContentTypeMeta:
    type: ContentType
    title: str  # e.g. "Meet Recap"
    description: str  # short — what it produces
    input_contract: str  # what input is required (long-form)
    is_implemented: bool  # if False, route renders a stub page
    icon_svg: str  # tiny inline SVG for navigation cards
    primary_route_endpoint: str  # url_for endpoint name
    # Optional first-slide "how it works" content. None → the intro renderer
    # derives a graceful default, so adding a heading never requires authoring
    # this to get a working slide.
    how_it_works: "HowItWorks | None" = None


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
        how_it_works=HowItWorks(
            tagline="From a raw results file to ranked, branded, ready-to-post content.",
            inputs=(
                ("Results file", "file"),
                ("PB history", "pb"),
                ("Your brand kit", "brand"),
            ),
            steps=(
                "Upload your Hytek results file (.hy3) or a zip — we read every swim.",
                "The engine detects PBs, medals, finals and first-times, then ranks "
                "them by how content-worthy they are.",
                "You get branded cards, captions and a reel to review, approve and export.",
            ),
            engine_process="detect · rank · brand · generate",
        ),
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
        how_it_works=HowItWorks(
            tagline="One swimmer's meet, told as a single ranked story.",
            inputs=(
                ("A processed meet", "meet"),
                ("Pick a swimmer", "swimmer"),
            ),
            steps=(
                "Choose any meet you've already processed, then pick the swimmer.",
                "The engine gathers every achievement they earned and ranks it by impact.",
                "You get a single-athlete spotlight card, caption and story to approve.",
            ),
            engine_process="gather · rank · brand · generate",
        ),
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
        how_it_works=HowItWorks(
            tagline="Build the hype before the first whistle.",
            inputs=(
                ("Event details", "event"),
                ("Athletes to watch", "swimmer"),
                ("Photo (optional)", "photo"),
            ),
            steps=(
                "Tell us the event, the date and venue, and who to watch.",
                "The engine shapes the story angles and writes preview copy in your voice.",
                "You get feed and story captions plus a branded graphic to approve.",
            ),
            engine_process="angle · write · brand",
        ),
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
        how_it_works=HowItWorks(
            tagline="Brand-safe posts that lead with the moment, not the logo.",
            inputs=(
                ("Sponsor + event", "sponsor"),
                ("Key achievement", "trophy"),
                ("Brand rules", "brand"),
            ),
            steps=(
                "Tell us the sponsor, the event and the moment to celebrate.",
                "The engine writes a sponsor-friendly caption that keeps the "
                "partnership feeling natural.",
                "You get a brand-safe graphic and caption to approve and export.",
            ),
            engine_process="feature · write · brand-check",
        ),
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
        how_it_works=HowItWorks(
            tagline="Quick mid-meet updates while the action is still live.",
            inputs=(
                ("What's happened", "note"),
                ("Current session", "meet"),
            ),
            steps=(
                "Type the event, the latest, and which session you're in.",
                "The engine writes short, shareable Stories and feed cards in your voice.",
                "You get quick captions and a graphic to post between sessions.",
            ),
            engine_process="summarise · write · brand",
        ),
    ),
    ContentType.FREE_TEXT: ContentTypeMeta(
        type=ContentType.FREE_TEXT,
        title="Free Text",
        description="Describe any post in a single prompt — and add photos — to get a branded graphic.",
        input_contract=(
            "Type what you want — a shout-out, a sponsor thank-you, a session update, a "
            "milestone, anything. MediaHub interprets the prompt, writes the caption, and "
            "builds a branded graphic from it; attach your own photos and it places them in. "
            "Lands on a draft you can edit, approve and export."
        ),
        is_implemented=True,
        icon_svg=_PENCIL_SVG,
        primary_route_endpoint="free_text_chat_page",
        how_it_works=HowItWorks(
            tagline="Describe any post in plain words — get a branded graphic back.",
            inputs=(
                ("Your words", "words"),
                ("Photos (optional)", "photo"),
            ),
            steps=(
                "Type what you want — a shout-out, a thank-you, a milestone, anything.",
                "MediaHub interprets it, writes the caption and places your photos in.",
                "You get a branded graphic draft to edit, approve and export.",
            ),
            engine_process="interpret · write · place",
        ),
    ),
}
