# vertical_stat_tower — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** The whole canvas is one vertical tower of
full-width stacked tiers, like a totem of facts: a header (kicker + athlete
first name + oversized surname), then full-bleed horizontal tiers of varying
height — **EVENT** (a surface tier) → **RESULT** (the dominant accent tier,
tallest, the tower's peak, carrying the headline time/mark) → **THE MOVE** (an
optional measured-highlight tier that collapses when empty). The club lockup
and meet anchor the foot.

The structural signature is **full-width tiers stacked vertically with one
tall dominant accent tier**. That is a different geometry from the vertical
right rail of `stat_stack_sidebar` (a side scoreboard beside a stage), the 2×2
cells of `editorial_numbers_grid`, and the stacked broadcast bands of
`ticker_strip` (which fence and crawl horizontally). The distinctiveness comes
from the dominant-tier rhythm, not a recolour, so it reads as a new structure
even on an all-dark brand kit.

**When the director should pick it.** Pick it for a data-forward card where the
result deserves a full-bleed tier of its own and there is a clean event label to
stack above it — strong with or without a photo. It carries a measured highlight
("the move") in its own tier when one exists and drops the tier cleanly when
none does, so the tower never shows an empty shelf. A good change of pace from
the left-anchored stacks in a pack.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The result tier fills with `--mh-accent` and sets its text to
`var(--mh-primary)` — accent is the role the resolver guarantees contrasts the
primary (APCA gate), so primary-on-accent is a gate-checked legible pair, medal
tints included.

**Overflow safety (the important bit).** The tiers are full-width, so the result
tier matches the full-canvas result box closely; it still uses
`calc(var(--mh-fit-result-px) * 0.92)` **and** wraps
(`overflow-wrap: anywhere; word-break: break-word`), and the header surname uses
`calc(var(--mh-fit-surname-px) * 0.78)` and wraps too. Holds at both
**1080×1350** and **1080×1920**: the result tier is `flex: 1 1 auto`, so it
absorbs the extra height while the `vt__foot` lockup stays bottom-anchored.

**Optional-slot collapse.** `.vt__move-tier:has(.vt__move-val:empty)` hides the
highlight tier entirely when no measured hero stat is supplied, so an empty slot
never leaves a dangling shelf in the tower.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
