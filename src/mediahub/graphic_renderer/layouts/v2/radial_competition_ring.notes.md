# radial_competition_ring — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** A radial data dial: the headline result sits
at the centre of a concentric ring assembly — an outer ring of clock-style tick
marks, a thick accent ring, and a punched-out core that frames the time/mark in
the accent role. A kicker pill caps the dial; the athlete first name + oversized
surname + event sit beneath it, and the meet + club lockup anchor the foot.

The structural signature is **concentric rings with a radial tick rhythm and a
centred numeral** — a competition dial / gauge. The hero is *data*, not a photo,
which sets it apart from the photo portal of `spotlight_disc` and the centred
medal/portrait of `centered_medal_spotlight`; the radial symmetry sets it apart
from every left- or column-anchored layout. The ticks are pure CSS (a
`repeating-conic-gradient` in the outline role, masked to a thin band), so the
dial is deterministic and uses only the injected role tokens.

**When the director should pick it.** Reach for it when the time or mark itself
is the whole story and you want it to read like a scoreboard / lap clock —
strong on a clean PB or a final time with no photo. The radial composition is a
deliberate change of pace in a pack otherwise full of left-anchored stacks, so
it lifts a pack's archetype diversity. Skip it when the athlete portrait is the
point — pick a photo-led archetype instead.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The core result paints in `var(--mh-accent)` over the primary
ground — accent is the role the resolver guarantees contrasts the primary (APCA
gate), so it is a gate-checked legible focal hit, medal tints included.

**Overflow safety (the important bit).** The core is a fixed disc (~388px),
far narrower than the full-canvas result box the autofit var assumes (result
fit ≈ 52% of canvas). So the centre result is scaled via
`calc(var(--mh-fit-result-px) * 0.5)` **and** allowed to wrap
(`overflow-wrap: anywhere; word-break: break-word`); the surname below the dial
(full width) uses `calc(var(--mh-fit-surname-px) * 0.62)` and also breaks. Holds
at both **1080×1350** and **1080×1920**: the dial stays centred and the foot
stays bottom-anchored via `margin-top: auto`.

**Optional-slot collapse.** `.rr__hero:has(.rr__hero-val:empty)` hides the
highlight line when no measured hero stat is supplied, so an empty slot never
leaves a gap below the event.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
