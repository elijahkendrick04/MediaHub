"""UI 1.10 — the visual template / archetype gallery.

A browse-only surface that shows the content **archetypes** the design director
draws from, *before* a user creates a pack. It renders existing data only — the
live archetype list plus each archetype's authored notes
(``graphic_renderer.archetypes``) — with a lightweight, deterministic schematic
preview per archetype and client-/server-side category filters. The gallery
lists the structural archetypes (each then varied by a deterministic style pack
— ``graphic_renderer.style_packs`` — into 1,000+ unique templates). No new API,
no external service, and (deliberately) no way to *force* an archetype: the
engine still picks the best composition per moment. It just shows the range.

Everything here is pure / Flask-free so it unit-tests without a request: the
route in ``web.py`` passes the resolved ``url_for(...)`` strings in and wraps
the returned body with ``_layout``.

Design boundary: the previews are honest **schematics** (wireframes of each
archetype's structural signature), not pixel renders of a real card — drawn
from the same "structural signature" the notes describe. They use the app's
theme CSS variables (classes defined in ``web.py``'s stylesheet), so they stay
on-theme and need no per-request brand palette.
"""

from __future__ import annotations

from markupsafe import escape

from mediahub.graphic_renderer import archetypes as _arch
from mediahub.graphic_renderer import style_packs as _sp

# ---------------------------------------------------------------------------
# Categories (presentation-only metadata — like the Create page's format chips,
# this never touches the engine). Each archetype lands in exactly one category.
# ---------------------------------------------------------------------------

# (id, label, blurb)
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    (
        "photo",
        "Photo-led",
        "The image is the hero — best when you have a strong action shot or portrait.",
    ),
    (
        "data",
        "Data-led",
        "The numbers are the hero — scorelines, grids, big results. Works with no photo.",
    ),
    (
        "editorial",
        "Editorial",
        "Type-driven and premium — the name or story leads. Works with no photo.",
    ),
)

_CATEGORY_LABELS: dict[str, str] = {cid: label for cid, label, _ in CATEGORIES}

# Which category each archetype belongs to. Derived from each archetype's own
# notes (what it is built around): a photo stage/well/ring → photo; a
# number/scoreline/grid as the structural hero → data; type/quote/narrative as
# the hero → editorial.
CATEGORY_BY_ARCHETYPE: dict[str, str] = {
    # Photo-led — the image dominates the composition.
    "split_diagonal_hero": "photo",
    "full_bleed_photo_lower_third": "photo",
    "centered_medal_spotlight": "photo",
    "duo_athlete_split": "photo",
    "relay_collage": "photo",
    "broadcast_scorebug": "photo",
    "photo_passepartout": "photo",
    "spotlight_disc": "photo",
    # Data-led — the figures are the structural hero; no photo needed.
    "big_number_dominant": "data",
    "editorial_numbers_grid": "data",
    "ticker_strip": "data",
    "stat_stack_sidebar": "data",
    "cornerstone_numeral": "data",
    "horizon_band": "data",
    "scoreline_versus": "data",
    # Editorial — type / quote / narrative leads; no photo needed.
    "magazine_cover": "editorial",
    "quote_led_recap": "editorial",
    "minimal_type_poster": "editorial",
    "triptych_progression": "editorial",
    "index_card": "editorial",
    "mega_surname_bleed": "editorial",
}

# Default for any future archetype with no explicit mapping yet (a test guards
# that every *current* archetype is mapped, so this is purely belt-and-braces).
_DEFAULT_CATEGORY = "editorial"

# Curated display order for the "All" view — interleaves the three categories so
# the unfiltered gallery reads as varied rather than three solid blocks. Any
# archetype not listed here (a future addition) is appended alphabetically.
_DISPLAY_ORDER: tuple[str, ...] = (
    "split_diagonal_hero",
    "big_number_dominant",
    "magazine_cover",
    "full_bleed_photo_lower_third",
    "editorial_numbers_grid",
    "quote_led_recap",
    "centered_medal_spotlight",
    "ticker_strip",
    "triptych_progression",
    "duo_athlete_split",
    "relay_collage",
    "stat_stack_sidebar",
    "minimal_type_poster",
    "broadcast_scorebug",
    "cornerstone_numeral",
    "index_card",
    "photo_passepartout",
    "horizon_band",
    "mega_surname_bleed",
    "spotlight_disc",
    "scoreline_versus",
)

# Friendly card titles (the snake_case slug is shown separately for
# explainability). Falls back to a title-cased slug for an unmapped archetype.
_TITLE: dict[str, str] = {
    "big_number_dominant": "Big Number",
    "centered_medal_spotlight": "Medal Spotlight",
    "duo_athlete_split": "Duo Split",
    "editorial_numbers_grid": "Numbers Grid",
    "full_bleed_photo_lower_third": "Full-Bleed Photo",
    "magazine_cover": "Magazine Cover",
    "minimal_type_poster": "Minimal Poster",
    "quote_led_recap": "Quote Recap",
    "relay_collage": "Relay Collage",
    "split_diagonal_hero": "Diagonal Hero",
    "stat_stack_sidebar": "Stat Sidebar",
    "ticker_strip": "Ticker Strip",
    "triptych_progression": "Triptych",
    "broadcast_scorebug": "Scorebug",
    "cornerstone_numeral": "Cornerstone",
    "horizon_band": "Horizon Band",
    "index_card": "Index Card",
    "mega_surname_bleed": "Mega Surname",
    "photo_passepartout": "Framed Print",
    "scoreline_versus": "Scoreline",
    "spotlight_disc": "Spotlight Disc",
}

# Short fallback "what it is" blurb, used only if an archetype's notes file is
# missing/unreadable (archetype_summary returns ""). Mirrors the AI director's
# own static fallback table so the gallery degrades to honest, accurate copy.
_FALLBACK_SUMMARY: dict[str, str] = {
    "split_diagonal_hero": "A hard diagonal splits a photo stage above a solid brand wedge of facts.",
    "big_number_dominant": "One enormous result numeral dominates a flat brand ground.",
    "full_bleed_photo_lower_third": "A full-bleed photo under a broadcast-style lower-third band.",
    "editorial_numbers_grid": "A masthead over a ruled grid of labelled stat cells.",
    "minimal_type_poster": "Huge stacked type, one accent rule, and generous space — no photo.",
    "centered_medal_spotlight": "A symmetric, centred medal/podium spotlight on one athlete.",
    "magazine_cover": "A sports-magazine cover: masthead, cover photo, headline and coverstar.",
    "quote_led_recap": "An editorial pull-quote recap on a light paper ground.",
    "stat_stack_sidebar": "A wide headline stage beside a vertical scoreboard rail.",
    "ticker_strip": "Stacked broadcast bands with a fenced event-to-result scoreline.",
    "triptych_progression": "Three vertical bays read who → result → context.",
    "duo_athlete_split": "A 50/50 photo-vs-scoreline duel crossed by one name band.",
    "relay_collage": "Two to four athlete cutouts stand balanced on one baseline above a name band and data panel.",
    "broadcast_scorebug": "A full-bleed photo with a live-TV corner scorebug and top ribbon.",
    "cornerstone_numeral": "A mega numeral cornerstoned into the bottom-left of a brand ground.",
    "horizon_band": "One full-width accent horizon carries the result; name above, meta below.",
    "index_card": "A clerical filing card: a label tab, ruled header and leader ledger.",
    "mega_surname_bleed": "The surname set huge and bled off the right edge as the artwork.",
    "photo_passepartout": "A matted, framed-print window over a gallery caption plate.",
    "scoreline_versus": "Event versus result across a bold central fence, like a scoreline.",
    "spotlight_disc": "A circular photo portal ringed by the accent, radially centred.",
}

_CARD_SUMMARY_MAX = 180
_CARD_WHEN_MAX = 150


# ---------------------------------------------------------------------------
# Schematic previews — one per archetype. Inner SVG markup (the wrapping
# <svg> + classes come from ``archetype_svg``). ViewBox is 120×150 (a 4:5
# portrait, matching the 1080×1350 feed default). Shapes use scoped classes
# defined in web.py's stylesheet (.mh-arch-svg .gd/.sf/.ac/.ik/.ik2/.ph/…),
# so the wireframes inherit the dark editorial theme + lane-yellow accent.
# ---------------------------------------------------------------------------

_VIEWBOX = "0 0 120 150"

_SVG: dict[str, str] = {
    # Data-led — single dominant numeral on a flat ground.
    "big_number_dominant": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="12" y="16" width="9" height="4" rx="1"/>'
        '<rect class="ik2" x="25" y="15" width="40" height="6" rx="1"/>'
        '<rect class="ac" x="12" y="50" width="96" height="36" rx="2"/>'
        '<rect class="ik2" x="12" y="93" width="54" height="6" rx="1"/>'
        '<rect class="ik" x="12" y="103" width="34" height="4" rx="1"/>'
        '<line class="ln" x1="12" y1="120" x2="108" y2="120"/>'
        '<rect class="ik" x="12" y="127" width="14" height="13" rx="1"/>'
        '<rect class="ik2" x="31" y="128" width="40" height="5" rx="1"/>'
        '<rect class="ik" x="31" y="136" width="28" height="3" rx="1"/>'
    ),
    # Photo-led — radial symmetry; centred ring + portrait.
    "centered_medal_spotlight": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ik" x="42" y="16" width="36" height="4" rx="1"/>'
        '<circle class="ph" cx="60" cy="58" r="22"/>'
        '<circle class="acln" cx="60" cy="58" r="26"/>'
        '<rect class="ik2" x="34" y="94" width="52" height="7" rx="1"/>'
        '<rect class="ac" x="46" y="107" width="28" height="9" rx="4"/>'
        '<rect class="ik" x="40" y="129" width="40" height="4" rx="1"/>'
    ),
    # Photo-led — 50/50 vertical bisection crossed by one name band.
    "duo_athlete_split": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ph" x="0" y="0" width="60" height="150"/>'
        '<rect class="ac" x="8" y="12" width="20" height="5" rx="1"/>'
        '<rect class="ik" x="78" y="12" width="30" height="4" rx="1"/>'
        '<rect class="ik" x="72" y="104" width="24" height="4" rx="1"/>'
        '<rect class="ac" x="72" y="112" width="34" height="8" rx="1"/>'
        '<rect class="sf" x="0" y="66" width="120" height="18"/>'
        '<rect class="ik2" x="10" y="72" width="84" height="6" rx="1"/>'
        '<line class="acln" x1="60" y1="0" x2="60" y2="150"/>'
    ),
    # Photo-led — 2-4 cutouts balanced on one baseline; name band; data panel.
    "relay_collage": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="8" y="10" width="20" height="6" rx="1"/>'
        '<rect class="ik" x="92" y="10" width="16" height="6" rx="1"/>'
        '<rect class="ph" x="13" y="36" width="17" height="50" rx="2"/>'
        '<rect class="ph" x="36" y="28" width="19" height="58" rx="2"/>'
        '<rect class="ph" x="63" y="28" width="19" height="58" rx="2"/>'
        '<rect class="ph" x="89" y="36" width="17" height="50" rx="2"/>'
        '<rect class="ac" x="0" y="88" width="120" height="16"/>'
        '<rect class="onac" x="10" y="93" width="64" height="7" rx="1"/>'
        '<rect class="sf" x="0" y="104" width="120" height="46"/>'
        '<rect class="ik" x="10" y="112" width="18" height="3" rx="1"/>'
        '<rect class="ik2" x="10" y="118" width="48" height="8" rx="1"/>'
        '<rect class="ac" x="82" y="112" width="28" height="14" rx="1"/>'
        '<line class="ln" x1="10" y1="136" x2="110" y2="136"/>'
        '<rect class="ik" x="10" y="140" width="40" height="4" rx="1"/>'
    ),
    # Data-led — masthead over a ruled grid of stat cells.
    "editorial_numbers_grid": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ik2" x="12" y="12" width="30" height="5" rx="1"/>'
        '<rect class="ik" x="84" y="12" width="24" height="4" rx="1"/>'
        '<rect class="ac" x="12" y="21" width="96" height="2"/>'
        '<rect class="ik2" x="12" y="29" width="58" height="8" rx="1"/>'
        '<rect class="ln-f" x="12" y="48" width="46" height="34" rx="1"/>'
        '<rect class="ln-f" x="62" y="48" width="46" height="34" rx="1"/>'
        '<rect class="ln-f" x="12" y="86" width="46" height="34" rx="1"/>'
        '<rect class="ln-f" x="62" y="86" width="46" height="34" rx="1"/>'
        '<rect class="ik" x="17" y="54" width="20" height="3" rx="1"/>'
        '<rect class="ik2" x="17" y="61" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="67" y="54" width="20" height="3" rx="1"/>'
        '<rect class="ik2" x="67" y="61" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="17" y="92" width="20" height="3" rx="1"/>'
        '<rect class="ik2" x="17" y="99" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="67" y="92" width="20" height="3" rx="1"/>'
        '<rect class="ik2" x="67" y="99" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="12" y="132" width="40" height="4" rx="1"/>'
    ),
    # Photo-led — full-bleed photo under a bottom band + right result chip.
    "full_bleed_photo_lower_third": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ph" x="0" y="0" width="120" height="112"/>'
        '<rect class="ac" x="8" y="10" width="22" height="6" rx="1"/>'
        '<rect class="ik" x="92" y="10" width="20" height="6" rx="1"/>'
        '<rect class="sf" x="0" y="112" width="120" height="38"/>'
        '<rect class="ik2" x="10" y="120" width="66" height="8" rx="1"/>'
        '<rect class="ik" x="10" y="132" width="40" height="4" rx="1"/>'
        '<rect class="ac" x="92" y="120" width="20" height="13" rx="1"/>'
    ),
    # Editorial — magazine cover furniture.
    "magazine_cover": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ph" x="0" y="14" width="120" height="136"/>'
        '<rect class="sf" x="0" y="0" width="120" height="14"/>'
        '<rect class="ik2" x="10" y="4" width="50" height="6" rx="1"/>'
        '<rect class="ik" x="92" y="5" width="20" height="4" rx="1"/>'
        '<rect class="ik" x="100" y="40" width="12" height="3" rx="1"/>'
        '<rect class="ik" x="100" y="48" width="12" height="3" rx="1"/>'
        '<rect class="ik" x="100" y="56" width="12" height="3" rx="1"/>'
        '<rect class="ik2" x="8" y="94" width="70" height="11" rx="1"/>'
        '<rect class="ik2" x="8" y="108" width="54" height="11" rx="1"/>'
        '<circle class="ac" cx="96" cy="116" r="16"/>'
        '<rect class="sf" x="0" y="138" width="120" height="12"/>'
        '<rect class="ik" x="10" y="142" width="2" height="5"/>'
        '<rect class="ik" x="14" y="142" width="1" height="5"/>'
        '<rect class="ik" x="17" y="142" width="2" height="5"/>'
        '<rect class="ik" x="21" y="142" width="1" height="5"/>'
        '<rect class="ik" x="24" y="142" width="2" height="5"/>'
    ),
    # Editorial — huge stacked type, one rule, generous space.
    "minimal_type_poster": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ik" x="12" y="14" width="28" height="3" rx="1"/>'
        '<rect class="ik" x="88" y="14" width="20" height="3" rx="1"/>'
        '<rect class="ac" x="12" y="44" width="24" height="5" rx="1"/>'
        '<rect class="ik2" x="12" y="54" width="92" height="14" rx="1"/>'
        '<rect class="ik2" x="12" y="72" width="72" height="14" rx="1"/>'
        '<rect class="ac" x="12" y="100" width="96" height="2"/>'
        '<rect class="ik" x="12" y="110" width="40" height="4" rx="1"/>'
        '<rect class="ik" x="12" y="118" width="28" height="4" rx="1"/>'
    ),
    # Editorial — light "paper" ground, quote bar, ragged lines.
    "quote_led_recap": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="paper" x="8" y="8" width="104" height="134" rx="2"/>'
        '<rect class="ac" x="14" y="26" width="4" height="78" rx="1"/>'
        '<rect class="ac" x="24" y="22" width="8" height="11" rx="2"/>'
        '<rect class="ac" x="35" y="22" width="8" height="11" rx="2"/>'
        '<rect class="dk" x="24" y="42" width="72" height="8" rx="1"/>'
        '<rect class="dk" x="24" y="54" width="54" height="8" rx="1"/>'
        '<rect class="dk" x="24" y="66" width="62" height="8" rx="1"/>'
        '<line class="dkln" x1="88" y1="82" x2="88" y2="104"/>'
        '<rect class="dk" x="92" y="86" width="14" height="6" rx="1"/>'
        '<line class="dkln" x1="24" y1="118" x2="104" y2="118"/>'
        '<rect class="dk" x="24" y="124" width="46" height="4" rx="1"/>'
    ),
    # Photo-led — angled seam; photo stage above a left-aligned wedge.
    "split_diagonal_hero": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<polygon class="ph" points="0,0 120,0 120,70 0,96"/>'
        '<line class="acln" x1="0" y1="96" x2="120" y2="70"/>'
        '<rect class="ac" x="12" y="104" width="18" height="4" rx="1"/>'
        '<rect class="ik2" x="12" y="112" width="64" height="9" rx="1"/>'
        '<rect class="ac" x="12" y="126" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="12" y="138" width="44" height="3" rx="1"/>'
    ),
    # Data-led — wide stage beside a full-height scoreboard rail.
    "stat_stack_sidebar": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="sf" x="86" y="0" width="34" height="150"/>'
        '<rect class="ac" x="12" y="40" width="18" height="4" rx="1"/>'
        '<rect class="ik2" x="12" y="50" width="60" height="10" rx="1"/>'
        '<rect class="ik" x="12" y="66" width="40" height="4" rx="1"/>'
        '<rect class="ac" x="12" y="74" width="30" height="6" rx="1"/>'
        '<rect class="ik" x="92" y="14" width="22" height="4" rx="1"/>'
        '<rect class="ik" x="92" y="24" width="22" height="4" rx="1"/>'
        '<rect class="ik" x="92" y="120" width="22" height="8" rx="1"/>'
        '<line class="acln" x1="86" y1="0" x2="86" y2="150"/>'
    ),
    # Data-led — stacked broadcast bands + fenced scoreline.
    "ticker_strip": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="sf" x="0" y="0" width="120" height="16"/>'
        '<rect class="ik" x="10" y="6" width="28" height="4" rx="1"/>'
        '<rect class="ik" x="86" y="6" width="24" height="4" rx="1"/>'
        '<rect class="ac" x="10" y="26" width="18" height="5" rx="1"/>'
        '<rect class="ik2" x="10" y="34" width="84" height="12" rx="1"/>'
        '<rect class="sf" x="0" y="58" width="120" height="30"/>'
        '<rect class="ac" x="0" y="58" width="120" height="2"/>'
        '<rect class="ac" x="0" y="86" width="120" height="2"/>'
        '<rect class="ik" x="10" y="68" width="36" height="6" rx="1"/>'
        '<rect class="ac" x="84" y="66" width="26" height="12" rx="1"/>'
        '<rect class="sf" x="0" y="128" width="120" height="22"/>'
        '<rect class="ik" x="10" y="135" width="30" height="6" rx="1"/>'
    ),
    # Editorial — three vertical bays; middle bay is the accent result column.
    "triptych_progression": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="40" y="0" width="40" height="150"/>'
        '<rect class="sf" x="80" y="0" width="40" height="150"/>'
        '<rect class="ac" x="8" y="18" width="16" height="4" rx="1"/>'
        '<rect class="ik2" x="8" y="28" width="26" height="7" rx="1"/>'
        '<rect class="ik2" x="8" y="38" width="22" height="7" rx="1"/>'
        '<rect class="ik" x="8" y="52" width="24" height="3" rx="1"/>'
        '<rect class="onac" x="46" y="22" width="4" height="66" rx="1"/>'
        '<rect class="onac" x="54" y="58" width="20" height="11" rx="1"/>'
        '<rect class="ik" x="88" y="18" width="24" height="4" rx="1"/>'
        '<rect class="ik" x="88" y="26" width="18" height="4" rx="1"/>'
        '<rect class="ik" x="88" y="124" width="24" height="8" rx="1"/>'
        '<line class="acln" x1="40" y1="0" x2="40" y2="150"/>'
        '<line class="acln" x1="80" y1="0" x2="80" y2="150"/>'
    ),
    # Data-led — mega numeral cornerstoned into the bottom-left.
    "cornerstone_numeral": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="12" y="16" width="9" height="4" rx="1"/>'
        '<rect class="ik2" x="25" y="15" width="38" height="6" rx="1"/>'
        '<rect class="ik" x="86" y="16" width="22" height="6" rx="1"/>'
        '<rect class="ik" x="12" y="72" width="40" height="4" rx="1"/>'
        '<rect class="ac" x="10" y="82" width="78" height="48" rx="2"/>'
        '<line class="ln" x1="12" y1="138" x2="108" y2="138"/>'
        '<rect class="ik" x="12" y="141" width="30" height="4" rx="1"/>'
    ),
    # Data-led — one full-width accent horizon carrying the result.
    "horizon_band": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="12" y="20" width="9" height="4" rx="1"/>'
        '<rect class="ik2" x="12" y="34" width="62" height="10" rx="1"/>'
        '<rect class="ac" x="0" y="64" width="120" height="24"/>'
        '<rect class="onac" x="12" y="72" width="34" height="8" rx="1"/>'
        '<rect class="onac" x="86" y="71" width="22" height="10" rx="1"/>'
        '<rect class="ik" x="12" y="104" width="40" height="4" rx="1"/>'
        '<rect class="ik" x="12" y="134" width="14" height="10" rx="1"/>'
        '<rect class="ik" x="30" y="136" width="40" height="6" rx="1"/>'
    ),
    # Data-led — two cells across a central accent fence.
    "scoreline_versus": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="12" y="16" width="9" height="4" rx="1"/>'
        '<rect class="ik2" x="25" y="15" width="50" height="7" rx="1"/>'
        '<rect class="ac" x="58" y="44" width="4" height="74"/>'
        '<rect class="ik" x="14" y="56" width="20" height="4" rx="1"/>'
        '<rect class="ik2" x="14" y="64" width="34" height="12" rx="1"/>'
        '<rect class="ik" x="86" y="56" width="20" height="4" rx="1"/>'
        '<rect class="ac" x="72" y="64" width="36" height="14" rx="1"/>'
        '<line class="ln" x1="12" y1="128" x2="108" y2="128"/>'
        '<rect class="ik" x="12" y="134" width="44" height="6" rx="1"/>'
    ),
    # Photo-led — full-bleed photo with a corner broadcast scorebug.
    "broadcast_scorebug": (
        '<rect class="ph" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="sf" x="0" y="0" width="120" height="16"/>'
        '<rect class="ik" x="8" y="6" width="30" height="4" rx="1"/>'
        '<rect class="ik" x="86" y="6" width="26" height="4" rx="1"/>'
        '<rect class="ac" x="12" y="96" width="22" height="7" rx="1"/>'
        '<rect class="ik2" x="12" y="107" width="54" height="11" rx="1"/>'
        '<rect class="ac" x="12" y="124" width="4" height="20"/>'
        '<rect class="sf" x="16" y="124" width="66" height="20" rx="1"/>'
        '<rect class="ik" x="22" y="130" width="24" height="8" rx="1"/>'
        '<rect class="ac" x="52" y="129" width="22" height="10" rx="1"/>'
    ),
    # Photo-led — matted window with a gallery caption plate.
    "photo_passepartout": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="16" y="20" width="88" height="74" rx="1"/>'
        '<rect class="ph" x="20" y="24" width="80" height="66" rx="1"/>'
        '<rect class="ik2" x="16" y="104" width="56" height="9" rx="1"/>'
        '<rect class="ik" x="16" y="118" width="40" height="4" rx="1"/>'
        '<rect class="ac" x="80" y="104" width="28" height="14" rx="1"/>'
        '<rect class="ik" x="16" y="138" width="36" height="5" rx="1"/>'
    ),
    # Photo-led — circular portal ringed by the accent, radial symmetry.
    "spotlight_disc": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="45" y="16" width="30" height="4" rx="1"/>'
        '<circle class="ac" cx="60" cy="58" r="34"/>'
        '<circle class="ph" cx="60" cy="58" r="27"/>'
        '<rect class="ik2" x="34" y="100" width="52" height="9" rx="1"/>'
        '<rect class="ac" x="42" y="114" width="36" height="12" rx="1"/>'
        '<rect class="ik" x="40" y="134" width="40" height="5" rx="1"/>'
    ),
    # Editorial — clerical filing card: tab, ruled header, leader ledger.
    "index_card": (
        '<rect class="sf" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="12" y="14" width="26" height="8" rx="1"/>'
        '<rect class="ik2" x="12" y="28" width="60" height="10" rx="1"/>'
        '<line class="ln" x1="12" y1="46" x2="108" y2="46"/>'
        '<rect class="ik" x="12" y="56" width="18" height="4" rx="1"/>'
        '<line class="ln" x1="36" y1="59" x2="92" y2="59"/>'
        '<rect class="ik" x="96" y="55" width="12" height="5" rx="1"/>'
        '<rect class="ik" x="12" y="74" width="18" height="4" rx="1"/>'
        '<line class="ln" x1="36" y1="77" x2="86" y2="77"/>'
        '<rect class="ac" x="90" y="72" width="18" height="8" rx="1"/>'
        '<rect class="ik" x="12" y="92" width="18" height="4" rx="1"/>'
        '<line class="ln" x1="36" y1="95" x2="92" y2="95"/>'
        '<rect class="ik" x="96" y="91" width="12" height="5" rx="1"/>'
        '<rect class="ik" x="12" y="128" width="40" height="6" rx="1"/>'
    ),
    # Editorial — surname set huge and bled off the right edge.
    "mega_surname_bleed": (
        '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
        '<rect class="ac" x="10" y="16" width="9" height="4" rx="1"/>'
        '<rect class="ik" x="22" y="15" width="30" height="6" rx="1"/>'
        '<rect class="ik2" x="8" y="54" width="128" height="44" rx="0"/>'
        '<rect class="ac" x="10" y="118" width="34" height="14" rx="1"/>'
        '<rect class="ik" x="10" y="138" width="40" height="4" rx="1"/>'
    ),
}

# Generic placeholder schematic for any future archetype that has no bespoke
# preview yet (a test guards that every current archetype is bespoke).
_GENERIC_SVG = (
    '<rect class="gd" x="0" y="0" width="120" height="150" rx="3"/>'
    '<rect class="ph" x="14" y="16" width="92" height="60" rx="2"/>'
    '<rect class="ik2" x="14" y="86" width="70" height="9" rx="1"/>'
    '<rect class="ik" x="14" y="100" width="48" height="5" rx="1"/>'
    '<rect class="ac" x="14" y="114" width="30" height="7" rx="1"/>'
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def humanize(name: str) -> str:
    """Friendly card title for an archetype slug (``"Diagonal Hero"``)."""
    return _TITLE.get(name) or name.replace("_", " ").title()


def category_for(name: str) -> str:
    """The category id an archetype belongs to."""
    return CATEGORY_BY_ARCHETYPE.get(name, _DEFAULT_CATEGORY)


def category_label(cid: str) -> str:
    """Human label for a category id (``"all"`` → ``"All"``)."""
    if cid == "all":
        return "All"
    return _CATEGORY_LABELS.get(cid, cid.title())


def valid_category(cid: str | None) -> str:
    """Coerce a (possibly user-supplied) category id to a known one.

    Anything not a real category id collapses to ``"all"`` — so a junk
    ``?category=`` never produces a broken/empty gallery.
    """
    cid = (cid or "").strip().lower()
    return cid if cid in _CATEGORY_LABELS else "all"


def archetype_svg(name: str) -> str:
    """The full inline ``<svg>`` schematic preview for an archetype."""
    inner = _SVG.get(name, _GENERIC_SVG)
    label = f"{humanize(name)} layout — schematic preview"
    return (
        f'<svg class="mh-arch-svg" viewBox="{_VIEWBOX}" role="img" '
        f'aria-label="{escape(label)}" preserveAspectRatio="xMidYMid meet" '
        f'focusable="false">{inner}</svg>'
    )


def _clip(text: str, limit: int) -> str:
    """Clip to ``limit`` chars at a word boundary with an ellipsis."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + " …"


def gallery_entries() -> list[dict]:
    """Build the gallery rows from the live archetype catalog.

    One dict per archetype currently registered (``archetypes.list_archetypes``),
    ordered by the curated display order with any unknown archetype appended
    alphabetically. Each row carries everything a card needs: ``name`` (slug),
    ``title``, ``summary`` (what it is), ``when`` (best for), ``category`` and
    its ``category_label``, and the inline ``svg`` schematic.
    """
    names = _arch.list_archetypes()
    order = {n: i for i, n in enumerate(_DISPLAY_ORDER)}
    ordered = sorted(names, key=lambda n: (order.get(n, len(order)), n))

    rows: list[dict] = []
    for name in ordered:
        summary = _arch.archetype_summary(name) or _FALLBACK_SUMMARY.get(name, "")
        when = _arch.director_note(name)
        cat = category_for(name)
        rows.append(
            {
                "name": name,
                "title": humanize(name),
                "summary": _clip(summary, _CARD_SUMMARY_MAX),
                "when": _clip(when, _CARD_WHEN_MAX),
                "category": cat,
                "category_label": category_label(cat),
                "svg": archetype_svg(name),
            }
        )
    return rows


def category_counts(entries: list[dict]) -> dict[str, int]:
    """Count per category id, plus ``"all"`` for the total."""
    counts: dict[str, int] = {"all": len(entries)}
    for cid, _, _ in CATEGORIES:
        counts[cid] = sum(1 for e in entries if e["category"] == cid)
    return counts


# ---------------------------------------------------------------------------
# HTML rendering (returns a body string; the route wraps it with _layout)
# ---------------------------------------------------------------------------


def _e(value) -> str:
    """Escape to a plain ``str`` (avoids Markup re-escaping on concat)."""
    return str(escape(value))


def _filter_chips(entries: list[dict], *, gallery_url: str, active: str) -> str:
    counts = category_counts(entries)
    chips = []
    rows = [("all", "All")] + [(cid, label) for cid, label, _ in CATEGORIES]
    for cid, label in rows:
        href = gallery_url if cid == "all" else f"{gallery_url}?category={cid}"
        is_active = cid == active
        cls = "mh-arch-chip is-active" if is_active else "mh-arch-chip"
        cur = ' aria-current="true"' if is_active else ""
        chips.append(
            f'<a class="{cls}" href="{_e(href)}" data-cat="{cid}"{cur}>'
            f"{_e(label)}"
            f'<span class="mh-arch-chip-n" aria-hidden="true">{counts.get(cid, 0)}</span>'
            f'<span class="mh-arch-sr"> ({counts.get(cid, 0)} templates)</span>'
            "</a>"
        )
    return (
        '<div class="mh-arch-filters" role="group" '
        'aria-label="Filter templates by category">' + "".join(chips) + "</div>"
    )


def _card(entry: dict, *, active: str) -> str:
    hidden = active != "all" and entry["category"] != active
    cls = "mh-arch-card is-hidden" if hidden else "mh-arch-card"
    when_html = ""
    if entry["when"]:
        when_html = (
            '<p class="mh-arch-when">'
            '<span class="mh-arch-when-label">Best for</span> '
            f'{_e(entry["when"])}</p>'
        )
    return (
        f'<article class="{cls}" data-category="{_e(entry["category"])}">'
        f'<div class="mh-arch-thumb">{entry["svg"]}</div>'
        '<div class="mh-arch-body">'
        '<div class="mh-arch-head">'
        f'<h3 class="mh-arch-title">{_e(entry["title"])}</h3>'
        f'<span class="mh-arch-tag" data-cat="{_e(entry["category"])}">'
        f'{_e(entry["category_label"])}</span>'
        "</div>"
        f'<code class="mh-arch-slug">{_e(entry["name"])}</code>'
        f'<p class="mh-arch-summary">{_e(entry["summary"])}</p>'
        f"{when_html}"
        "</article>"
    )


def render_gallery_body(
    *, gallery_url: str, make_url: str, active_category: str = "all", studio_url: str = ""
) -> str:
    """Render the full gallery page body (hero + filters + grid + CTA + JS).

    Pure string builder: ``gallery_url`` and ``make_url`` are pre-resolved
    ``url_for`` strings, ``active_category`` is already validated. When
    ``studio_url`` is given (the G1.26 live preview gallery), a prominent link to
    it is rendered after the intro. The returned string is handed to ``_layout``
    by the route.
    """
    active = active_category if active_category in _CATEGORY_LABELS else "all"
    entries = gallery_entries()
    n = len(entries)
    # The structural archetypes are only half the story: the renderer dresses
    # each one with a deterministic style pack (ground × texture × accent ×
    # density), so the true template space is archetypes × packs. Surface the
    # honest total so operators can see the variety the engine draws from.
    total_templates = _sp.style_pack_count() * n

    hero = (
        '<section class="mh-hero" data-lane="04" '
        'style="padding-top:var(--sp-9);padding-bottom:var(--sp-6);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Template gallery</span>'
        f'<h1>{n} ways to tell<br>the <em class="editorial">story</em>.</h1>'
        '<p class="lede">Every content pack is composed from this library of '
        f"{n} structural card templates — each then re-dressed by the style "
        f"engine into one of <strong>{total_templates:,} unique, on-brand "
        "variations</strong>, so a pack reads as a set of deliberate, distinct "
        "designs rather than one repeated look. The design director picks the "
        "best one for each moment automatically — browse the range here so you "
        "know what your cards can look like before you create a pack.</p>"
        "</section>"
    )

    intro = (
        '<p class="mh-arch-note">These are schematic previews of each '
        "template&rsquo;s structure — your real cards are rendered in your club "
        "colours, type and logo, with your athletes&rsquo; photos.</p>"
    )

    # G1.26 cross-link: from the schematic wireframes to the live, rendered
    # preview studio (every archetype × pack as a real card, with filters).
    studio_cta = ""
    if studio_url:
        studio_cta = (
            f'<a class="mh-arch-gallery-link" href="{_e(studio_url)}">'
            '<span class="mh-agl-text">'
            '<span class="mh-agl-title">See live preview thumbnails &rarr;</span>'
            "<span class=\"mh-agl-sub\">Browse every archetype &times; style pack as a "
            "real rendered card — filter by ground, texture, accent and density.</span>"
            "</span>"
            '<span class="mh-agl-cta">Open the studio</span>'
            "</a>"
        )

    # Section heading keeps the heading order valid (hero h1 → h2 → card h3);
    # visually hidden because the hero already titles the page.
    section_h2 = '<h2 class="mh-arch-sr">Template library</h2>'

    chips = _filter_chips(entries, gallery_url=gallery_url, active=active)
    cards = "".join(_card(e, active=active) for e in entries)
    grid = f'<div class="mh-arch-grid" id="mh-arch-grid">{cards}</div>'

    empty = (
        '<p class="mh-arch-empty" id="mh-arch-empty" hidden>' "No templates in this category.</p>"
    )

    cta = (
        '<div class="mh-arch-cta">'
        '<div class="mh-arch-cta-text">'
        "<strong>Ready to make something?</strong>"
        "<span>Upload results or describe a moment — the engine picks the right "
        "template for every card.</span>"
        "</div>"
        f'<a class="btn" href="{_e(make_url)}">Create a pack &rarr;</a>'
        "</div>"
    )

    script = _GALLERY_JS

    return (
        f'<section id="mh-arch-gallery" class="mh-arch-gallery" data-active="{active}">'
        f"{hero}{intro}{studio_cta}{section_h2}{chips}{grid}{empty}{cta}"
        "</section>"
        f"{script}"
    )


# Progressive enhancement: instant client-side filtering with no reload. The
# no-JS path already works (chips are real ?category= links the server honours);
# this just takes over so switching categories doesn't round-trip. All cards are
# always in the DOM, so any category is reachable without a fetch.
_GALLERY_JS = """<script>
(function(){
  var root = document.getElementById('mh-arch-gallery');
  if(!root) return;
  var grid = document.getElementById('mh-arch-grid');
  var empty = document.getElementById('mh-arch-empty');
  if(!grid) return;
  var chips = root.querySelectorAll('.mh-arch-chip');
  var cards = grid.querySelectorAll('.mh-arch-card');
  function apply(cat){
    cat = cat || 'all';
    var shown = 0;
    for(var i=0;i<cards.length;i++){
      var c = cards[i];
      var show = (cat === 'all') || (c.getAttribute('data-category') === cat);
      c.classList.toggle('is-hidden', !show);
      if(show) shown++;
    }
    for(var j=0;j<chips.length;j++){
      var ch = chips[j];
      var on = (ch.getAttribute('data-cat') === cat);
      ch.classList.toggle('is-active', on);
      if(on){ ch.setAttribute('aria-current','true'); }
      else { ch.removeAttribute('aria-current'); }
    }
    if(empty) empty.hidden = (shown !== 0);
  }
  function catFromUrl(){
    var m = /[?&]category=([^&]+)/.exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : 'all';
  }
  for(var k=0;k<chips.length;k++){
    (function(ch){
      ch.addEventListener('click', function(e){
        e.preventDefault();
        var cat = ch.getAttribute('data-cat') || 'all';
        apply(cat);
        var url = (cat === 'all')
          ? window.location.pathname
          : (window.location.pathname + '?category=' + encodeURIComponent(cat));
        try { window.history.pushState({cat:cat}, '', url); } catch(_){}
      });
    })(chips[k]);
  }
  window.addEventListener('popstate', function(){ apply(catFromUrl()); });
  apply(catFromUrl());
})();
</script>"""


__all__ = [
    "CATEGORIES",
    "CATEGORY_BY_ARCHETYPE",
    "humanize",
    "category_for",
    "category_label",
    "valid_category",
    "archetype_svg",
    "gallery_entries",
    "category_counts",
    "render_gallery_body",
]
