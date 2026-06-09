# triptych_progression — authoring notes (PAR-7 v2 archetype)

**Family / structural signature.** A three-panel composition: the canvas is
split into THREE equal full-height vertical bays separated by accent seams,
read left-to-right as a progression — **WHO** (brand-ground panel: kicker +
first name + oversized surname + event) → **RESULT** (dominant accent panel: a
vertical "RESULT" spine and the headline time/mark, centred) → **CONTEXT**
(surface panel: meet + optional highlight chip + club lockup at the foot).

The distinctiveness comes from **column geometry**, not a recolour, so it reads
as a new structure at a glance even on an all-dark brand kit where the ground
and surface luminance are close — distinct from the centred numeral
(`big_number_dominant`), the angled wedge (`split_diagonal_hero`), the vertical
right rail (`stat_stack_sidebar`) and the horizontal broadcast bands
(`ticker_strip`).

**Why the director should pick it.** Good when the story is a clean
who → result → context beat and there is a strong single result to anchor the
middle bay; works with or without a portrait (the photo is a quiet wash behind
panel 1, never the focal element), so it is a safe pick when no usable cutout
exists.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*`
roles (no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders
from the allow-list only. The middle bay fills with `--mh-accent` and sets text
to `var(--mh-primary)` — accent is the one role the resolver guarantees
contrasts the primary (APCA gate), so primary-on-accent is a gate-checked
legible pair.

**Overflow safety (the important bit).** Each bay is ~1/3 of the canvas
(~328px content after padding), much narrower than the full-canvas single-line
boxes the renderer's autofit vars assume (surname fit ≈ 86% of canvas, result
fit ≈ 52%). So:

- the surname is scaled to the bay via `calc(var(--mh-fit-surname-px) * 0.34)`
  **and** allowed to wrap (`overflow-wrap: anywhere; word-break: break-word`),
  so a long or space-less single-token name flows onto extra lines instead of
  clipping into the seam;
- the middle result is scaled via `calc(var(--mh-fit-result-px) * 0.52)` and
  also breaks;
- the first-name line, event and chip values break too.

Holds at both **1080×1350** and **1080×1920**: the three columns simply grow
taller, the `tp__ctx-foot` club lockup stays bottom-anchored via `margin-top:
auto`.

**Optional-slot collapse.** `.tp__hero:has(.tp__hero-val:empty)` hides the
highlight chip entirely when no hero stat is supplied, so an empty slot never
leaves a dangling label on the context column.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in
the Tier-A picker automatically (`archetypes._scan()` globs the directory), so
a representative seeds-0..9 pack spreads across the larger library and pack
archetype-diversity rises.
