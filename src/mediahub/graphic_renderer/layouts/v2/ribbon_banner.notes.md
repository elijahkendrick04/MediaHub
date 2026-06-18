# ribbon_banner — authoring notes (PAR-7 v2 archetype, G1.1)

**Family / structural signature.** An award-ribbon motif: a centred banner sash
with notched, double-pointed (chevron) ends carries the achievement label across
the upper third, with two ribbon tails descending from behind it. Beneath the
ribbon the athlete first name + oversized surname, the headline result and the
event read down the centre; the club lockup anchors the foot.

The structural signature is a **shaped ribbon / pennant** — clip-path chevron
ends plus hanging tails — used as the centrepiece, for a prize / award feel.
That sets it apart from `horizon_band` (a flat full-width rectangular band
carrying the result) and from `ticker_strip` (stacked broadcast bands that fence
and crawl). Here the band is a shaped object, not a rule. The ribbon and tails
paint in the accent role, so the motif is brand-coloured and deterministic — no
asset, no hex.

**When the director should pick it.** Reach for it for a genuine accolade — a
medal, a club record, a champion, a season award — where the achievement label
("Club Record", "Gold", "Champion") deserves to be celebrated as the headline,
not just tagged. The ribbon makes the honour the centrepiece. Keep the overshoot
of celebration to real wins; skip it for a routine swim or a sombre context,
where the award framing would overclaim.

**Slot convention.** `{{BASE_CSS}}` first; brand colour only via `--mh-*` roles
(no hex literal anywhere — CI greps `#[0-9a-fA-F]{3,6}`); placeholders from the
allow-list only. The ribbon fills with `--mh-accent` and sets its label to
`var(--mh-primary)` — accent is the role the resolver guarantees contrasts the
primary (APCA gate), so primary-on-accent is a gate-checked legible pair, and a
medal card's gated metal tint flows straight into the ribbon.

**Overflow safety (the important bit).** The label rides the ribbon and is
allowed to wrap (`overflow-wrap: anywhere; word-break: break-word`), so the
ribbon grows taller rather than clipping a long label. The surname is scaled via
`calc(var(--mh-fit-surname-px) * 0.66)` **and** wraps; the result via
`calc(var(--mh-fit-result-px) * 0.78)` **and** wraps; the first name and event
break too. Holds at both **1080×1350** and **1080×1920**: the centred stack
breathes into the taller canvas while the `rb__foot` lockup stays bottom-anchored
via `margin-top: auto`.

**Optional-slot collapse.** `.rb__hero:has(.rb__hero-val:empty)` hides the
highlight line when no measured hero stat is supplied, so an empty slot never
leaves a gap under the event.

**Auto-registration.** Dropping this file into `layouts/v2/` registers it in the
Tier-A picker automatically (`archetypes._scan()` globs the directory), so a
representative seeds-0..9 pack spreads across the larger library.
