# timeline_progression — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** A connected vertical timeline: one accent
spine runs top-to-bottom down the left margin, threaded through circular
milestone nodes read as a progression of beats — **START** (the achievement
kicker) → **ATHLETE** (first name + an oversized surname) → **RESULT** (the
dominant node, an accent disc carrying the headline time/mark and the event) →
**CONTEXT** (the meet + an optional measured highlight chip). The club lockup
anchors the foot.

The distinctiveness comes from the **spine geometry** — a single connected line
you can follow with marker dots — not a recolour, so it reads as a new
structure at a glance even on an all-dark brand kit. Distinct from the three
separate edge-to-edge bays of `triptych_progression`, the vertical right rail of
`stat_stack_sidebar`, the 2×2 cells of `editorial_numbers_grid` and the centred
numeral of `big_number_dominant`.

**When the director should pick it.** Good when the story is a clean
beat-by-beat journey — who → result → context — and there is one strong result
to anchor the dominant middle node. It carries a measured highlight (a PB drop,
a placing) in the final node when one exists, and reads as a deliberate
progression rather than a flat stack. Works with or without a portrait (the
photo is a quiet wash behind the ground, never the focal element), so it is a
safe pick when no usable cutout exists.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The result node fills with `--mh-accent` and sets its text to
`var(--mh-primary)` — accent is the one role the resolver guarantees contrasts
the primary (APCA gate), so primary-on-accent is a gate-checked legible pair.

**Overflow safety (the important bit).** The rail eats the left ~190px, so the
name and result live in a ~2/3-width column, narrower than the full-canvas
single-line boxes the autofit vars assume (surname fit ≈ 86% of canvas, result
≈ 52%). So the surname is scaled via `calc(var(--mh-fit-surname-px) * 0.5)`
**and** allowed to wrap (`overflow-wrap: anywhere; word-break: break-word`), and
the result is scaled via `calc(var(--mh-fit-result-px) * 0.62)` and also breaks.
Holds at both **1080×1350** and **1080×1920**: the spine simply grows taller and
the `tl__foot` club lockup stays bottom-anchored via `margin-top: auto`.

**Optional-slot collapse.** `.tl__hero:has(.tl__hero-val:empty)` hides the
highlight chip entirely when no measured hero stat is supplied, so an empty slot
never leaves a dangling label on the spine.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library and pack
archetype-diversity rises.
