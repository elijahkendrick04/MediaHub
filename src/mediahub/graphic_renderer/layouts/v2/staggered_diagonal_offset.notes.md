# staggered_diagonal_offset — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** Type blocks stepped down a descending
diagonal: the kicker, the athlete name, the result chip and the event each sit
further to the right and lower than the last, so the eye travels a diagonal
staircase. A single thin accent guide rule runs the diagonal behind the type,
with a small accent tick marking each step. The club lockup anchors the foot.

The structural signature is **staggered text blocks on a diagonal axis** — there
is no photo stage, no wedge, no seam. That sets it apart from
`split_diagonal_hero`, where a hard diagonal seam cuts a photo stage above a
solid wedge of facts: here the diagonal is expressed purely by the offset rhythm
of the type, for an editorial, kinetic feel. The distinctiveness comes from the
offset geometry, not a recolour, so it reads as a new structure on any kit.

**When the director should pick it.** Pick it for an energetic, type-led card —
a strong swim with a punchy result and a short, bold name — where movement and
attitude matter more than a photo. The diagonal staircase gives a pack a jolt of
dynamism between calmer stacked layouts, lifting archetype diversity. Skip it
when the athlete portrait is the point, or for a sombre / DQ context where the
kinetic feel would read wrong.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The result chip fills with `--mh-accent` and sets its text to
`var(--mh-primary)` — accent is the role the resolver guarantees contrasts the
primary (APCA gate), so primary-on-accent is a gate-checked legible pair.

**Overflow safety (the important bit).** The steps push content right
(`margin-left` up to ~200px), so each block is narrower than the full canvas.
The surname is scaled via `calc(var(--mh-fit-surname-px) * 0.62)` **and** wraps
(`overflow-wrap: anywhere; word-break: break-word`); the result chip via
`calc(var(--mh-fit-result-px) * 0.7)` **and** wraps; the kicker and event break
too. Holds at both **1080×1350** and **1080×1920**: the steps are vertically
centred (`justify-content: center`) so the staircase spreads down the taller
canvas while the absolutely-pinned `so__foot` lockup stays anchored.

**Optional-slot collapse.** `.so__hero:empty` hides the highlight line when no
measured hero stat is supplied (the slot renders empty), so an empty slot never
leaves a gap under the result.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
