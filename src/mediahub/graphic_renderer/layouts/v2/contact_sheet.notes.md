# contact_sheet — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** A photographer's contact sheet: sprocket-hole
film strips bracket a grid of six small frames of the same real athlete shot,
each framed differently (varied `object-position`), with one frame as the
"keeper" — ringed in the accent role and carrying the headline result. A caption
plate at the foot carries the achievement kicker, the name, the event and an
optional measured highlight.

The structural signature is a **sprocket-bracketed grid of film frames with one
highlighted keeper**. Nothing else in the library reads this way — it is not the
matted single window of `photo_passepartout`, nor the full-bleed photo of
`broadcast_scorebug` / `full_bleed_photo_lower_third`. The sprocket strips are
pure CSS (a `repeating-linear-gradient` in the outline role), so the motif is
deterministic and uses only role tokens.

**When the director should pick it.** Pick it when there is one strong action
shot worth showing off and the brief wants a behind-the-scenes, editorial,
photo-led treatment — a "best of the shoot" feel that still lands one clear
result on the keeper frame. It is a deliberately distinctive pick that lifts a
pack's archetype diversity. When no usable cutout exists the frames become a
clean brand-surface grid, but a data/editorial archetype is the better choice
with no photo.

**Honest repetition.** `{{ATHLETE_IMG_BLOCK}}` is the one real cutout the
renderer inlines; it is substituted into each frame (the renderer's global
slot-replace fills every occurrence) and re-cropped purely via CSS
`object-position` — exactly like a real contact sheet of a single shoot. No new
or invented imagery is fabricated, in keeping with the renderer's exact-evidence
rule.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The keeper ring and accents paint in `var(--mh-accent)`, the
keeper's result scrim mixes `var(--mh-primary)` with `transparent` via
`color-mix` (no invented colour), and the caption plate is the surface role.

**Overflow safety (the important bit).** The keeper frame is small, so its
result is scaled via `calc(var(--mh-fit-result-px) * 0.42)` **and** wraps
(`overflow-wrap: anywhere; word-break: break-word`); the caption surname is
scaled via `calc(var(--mh-fit-surname-px) * 0.6)` **and** wraps; the event and
hero break too. Holds at both **1080×1350** and **1080×1920**: the grid
(`flex: 1 1 auto`) absorbs the spare height while the caption plate stays
bottom-anchored.

**Optional-slot collapse.** `.cs__hero:has(.cs__hero-val:empty)` hides the
highlight line in the caption when no measured hero stat is supplied, so an empty
slot never leaves a dangling line.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
