# full_height_portrait_split — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** A clean vertical split: a full-height
portrait fills the left ~56% of the canvas, edge to edge and top to bottom; a
full-height info column on the right ~44% carries the kicker, the first name +
oversized surname, the event, the result and the meta, stacked. A thin accent
seam runs the full height of the split line, and a brand-tinted scrim sits over
the photo's seam edge so the column copy reads cleanly without distorting the
subject.

The structural signature is **one full-height portrait beside a full-height
info column, split by a straight vertical seam**. That is distinct from
`duo_athlete_split` (a 50/50 split crossed by a single name band, built for two
subjects) and from `split_diagonal_hero` (an angled photo stage above a wedge).
Here the portrait is uninterrupted and the type lives entirely in its own
column — a poised, gallery-portrait feel.

**When the director should pick it.** The go-to when there is one strong, tall
portrait or action cutout of a single athlete and you want the image to carry
the card while the facts read calmly alongside — premium and uncluttered. When
no usable cutout exists it degrades gracefully (the photo panel becomes a brand
surface with a faint surname watermark), but a photo-led archetype is wasted
without a photo, so prefer a data/editorial archetype in that case.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The photo uses `object-position: var(--mh-photo-pos)` so the
saliency crop keeps the athlete's face in frame, and the scrim mixes
`var(--mh-primary)` with `transparent` via `color-mix` — no invented colour. The
seam and accents paint in `var(--mh-accent)`, the APCA-gated contrast role.

**Overflow safety (the important bit).** The info column is ~44% width (~347px
content after padding), much narrower than the full-canvas single-line boxes the
autofit vars assume. So the surname is scaled via
`calc(var(--mh-fit-surname-px) * 0.5)` **and** wraps
(`overflow-wrap: anywhere; word-break: break-word`), and the result via
`calc(var(--mh-fit-result-px) * 0.62)` **and** wraps; first name and event break
too. Holds at both **1080×1350** and **1080×1920**: the portrait and column both
grow taller, and the `ps__foot` meta + lockup stay bottom-anchored via
`margin-top: auto`.

**Optional-slot collapse.** `.ps__hero:has(.ps__hero-val:empty)` hides the
highlight line when no measured hero stat is supplied, so an empty slot never
leaves a gap under the result.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
