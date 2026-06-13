# Data on graphics

Result cards are data products: a time, a place, a delta, a label. The
craft is making verified numbers feel *tangible* without ever bending
them. Adapted from HyperFrames' data-in-motion (Apache-2.0,
`vendor/hyperframes-skills-main/`), hardened for MediaHub's exactness
rules.

## Exactness first (the rules that outrank style)

- **The time is the time.** Display the verified value exactly as the
  canonical data formats it. Never round a swim time for layout reasons —
  53.21 is not "53.2"; the hundredths are the sport.
- **Deltas are computed, not styled.** A "−1.30s PB" chip must show the
  detector's computed delta. If the delta isn't in the card payload, the
  chip doesn't exist — no recomputing in a template, no "about a second".
- **Proportions must be true.** Any bar, ring, or fill whose size encodes
  a value must be mathematically proportional to the real values on the
  card. A decorative bar that *looks* like data but encodes nothing is a
  lie waiting to be read — make decoration visibly abstract, or make it
  true.
- **No invented comparisons.** "Fastest in the county" comes from a
  detector with a confidence score, or it doesn't appear. The card's
  explainability trace ("why this card") must cover every claim rendered.

## The hero stat carries the card

The brief's `heroStat` (from `STAT_KEYS`: `final_time`, `pb_delta`,
`placing`, `relay_split`, `split_time`, `season_best`, `age_group`,
`points`, `event`) is the editorial decision about *which number is the
story*. Execute it:

- The hero gets the scale (60–80% frame width — `big_number_dominant`
  exists for exactly this), the accent role, and the strongest treatment.
- Everything else steps down visibly. A card where the PB delta, the
  final time, and the placing all shout equally tells no story.
- Vary the hero across a pack: three cards all heroing `final_time` when
  one swim's story is the placing and another's is the delta is a missed
  edit, and a samey pack. `hero_stat_options` exists so the director can
  choose per card.

## Numbers need visual weight

A number floating in space reads as text, not achievement. Pair every
hero metric with one element that gives it presence — honestly:

- **A true proportional element** — a PB-delta bar whose length is the
  real before/after ratio; split bars scaled to real split times.
- **A containment treatment** — badge, ribbon, bracket, frame (the
  brief's `accent_style`) that frames the number as an *award*, encoding
  nothing.
- **A contextual label** — "NEW PB", the medal tint, the event name in
  mono. Labels are verified card facts, set in the label register.
- **Marker emphasis** — an accent sweep/underline behind the key figure
  (the still-side analogue of motion's marker-sweep effect; keep the
  accent-treatment vocabulary in sync across surfaces).

One weight-giving element per number. A badge in a frame on a bar is
costume jewellery.

## Visual continuity across a pack

When several stats belong to one concept, keep the visual system
constant and let only the values change:

- Splits within one swim: same chip geometry, same register, same scale —
  a viewer should compare values, not decode three designs.
- Across a content pack: recurring stat-chip geometry and label register
  are part of the club's system; vary archetype, background, hero — keep
  the data grammar stable. An aesthetic change should signal a *new
  concept* (new swimmer, new event), not a new number.
- The reel's cover chips (label-derived counts) follow the same grammar
  as the stills — that parity is what makes the pack feel like one
  campaign.

## Patterns to refuse

- **Pie charts** — never. Incomparable at a glance; PowerPoint energy.
- **Gridlines, axes, tick marks, legends** — chart-library furniture. A
  card shows 1–4 numbers; furniture outweighs the data.
- **Multi-series charts / 6-panel dashboards** — a feed card gets ~2
  seconds; 2–3 related values side-by-side is the ceiling.
- **Chart-library output pasted as an image** — everything renders from
  the layout templates with the `--mh-*` roles, or it's off-brand by
  construction.
- **Sparkline-shaped decoration** — wavy lines that imply a trend that
  was never computed. If a trend detector someday emits real series data,
  it arrives through the brief with provenance, not through CSS.
