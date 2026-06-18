# three_card_editorial_grid — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** A magazine "three-up": a full-width masthead
row, then three self-contained, inset, rounded editorial cards in a row, then a
full-width foot row. Each card is a complete unit — **A · WHO** (surface card:
an "Athlete" label + first name + surname) → **B · RESULT** (the dominant accent
card, lifted, carrying the headline mark) → **C · CONTEXT** (surface card: the
event, the meet, and an optional measured highlight that collapses when empty).

The structural signature is **three discrete inset cards** — gutters, rounded
corners, their own labels — framed by a shared masthead and foot. That reads
differently from the three edge-to-edge full-height bays of
`triptych_progression` (column geometry, no gutters, no masthead/foot rows) and
from the 2×2 stat cells of `editorial_numbers_grid`. The distinctiveness is the
card-grid geometry, not a recolour, so it holds on an all-dark kit.

**When the director should pick it.** Pick it for an editorial, premium feel
when the story splits cleanly into who / result / context and you want each
beat to read as its own framed card — strong with no photo, and a deliberate
change of pace from the full-bleed layouts in a pack. The lifted middle card
makes the result the obvious focal point. Skip it when a single dominant photo
should lead.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The middle card fills with `--mh-accent` and sets its text to
`var(--mh-primary)` — accent is the role the resolver guarantees contrasts the
primary (APCA gate), so primary-on-accent is a gate-checked legible pair.

**Overflow safety (the important bit).** Each card is ~1/3 width (~300px
content after padding), much narrower than the full-canvas single-line boxes
the autofit vars assume. So the surname is scaled via
`calc(var(--mh-fit-surname-px) * 0.32)` **and** wraps
(`overflow-wrap: anywhere; word-break: break-word`), the result via
`calc(var(--mh-fit-result-px) * 0.5)` **and** wraps, and every value line
breaks. Holds at both **1080×1350** and **1080×1920**: the cards (`flex: 1 1 0`)
grow taller while the masthead and foot rows stay pinned.

**Optional-slot collapse.** `.tg__hero:has(.tg__hero-val:empty)` hides the
highlight block in the context card when no measured hero stat is supplied, so
an empty slot never leaves a dangling label.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
