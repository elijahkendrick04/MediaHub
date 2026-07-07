# Composition

A 1080-px social graphic is a *frame*, not a web page. Web instincts —
sparse padding, centred stacks, 1px hairlines, 5% tints — produce cards
that read as empty or unfinished at feed size. Adapted from HyperFrames'
video-composition rules (Apache-2.0, `vendor/hyperframes-skills-main/`) for
MediaHub's still archetypes.

## Brand is sacred; application is yours

The BrandKit defines what the club looks like: the resolved `--mh-*` roles,
the logo, the fonts. It does NOT define how to compose a frame. Use the
brand at graphic-appropriate intensity:

- **Strict from the brand:** every colour value (via roles, never raw hex),
  the logo artwork (chip decision comes from `theming/logo_chip.py`, not
  taste), the type families.
- **Yours to design:** sizes, spacing, decorative opacity, border weights,
  treatments. A web-UI card style (1px border, 6% shadow) is invisible in
  a feed thumbnail — scale the *application* up without touching the brand
  values.

## Three depth layers, always

Every archetype slot, whatever its geometry, wants three layers:

1. **Background treatment** — the brief's `background_style` (dots,
   diagonal, stripes, geometric, halftone, grain, water, radial, duotone,
   clean). "Clean" is a treatment too — a tinted ground with deliberate
   negative space, not a forgotten flat fill. Pure untinted `#000`/`#fff`
   reads as "nothing loaded"; tint grounds toward the brand hue via the
   role palette.
2. **Midground facts** — name, event, time, place, photo. The message.
3. **Foreground accents** — the brief's `accent_style` (brackets, stripe,
   badge, frame, ribbon, arrow, underline, diagonal_underline, minimal),
   plus the R1.5 sizing/style variants (thick/thin/double stripe, side_rail,
   large/small brackets, bracket_frame, corner_tabs, offset_badge — the
   full closed list is `design_spec.ACCENT_TREATMENTS`, executed identically
   by the still engine and the motion accents registry),
   plus structural rules/dividers and the logo. These are what make a card
   feel *produced*: registration-mark details, a hairline scale, a label in
   mono.

Density target: 8–10 distinct visual elements per card, two of which are
decorative details nobody asked for. Three floating elements on a flat
ground is the signature of a template, not a design. (`minimal_type_poster`
earns low density through deliberate type scale — minimalism is a choice
made *visible*, not elements missing.)

## Focal points and eye travel

- **Two focal points minimum** — the hero stat and one counterweight (the
  athlete photo, the medal, the club mark). The eye needs a path; a single
  centred block reads as unfinished.
- **Anchor to edges.** Pin content to left/top or right/bottom per the
  brief's `composition` (left/right/center). Centred-and-floating
  everything is the web habit the archetypes exist to break.
- **Split frames beat centred stacks** — `stat_stack_sidebar`,
  `split_diagonal_hero`, `duo_athlete_split` and `magazine_cover` are
  zone-based for a reason; respect their zones instead of recentring
  content inside them.
- **Fill the frame.** Hero text wants 60–80% of frame width. If the time
  fits in a quarter of the canvas, it isn't the hero yet.
- **Structural elements create paths** — rules, dividers, border panels.
  Cheap to render, strong hierarchy.

## Colour presence at graphic scale

Muted is fine; flat is not. Every card needs at least one element that
pulls the eye, within the APCA-gated roles:

- The accent role should be *visible*: decorative tints at 12–25% opacity
  (a 5% web tint disappears in feed compression), full saturation for the
  focal accent.
- Light grounds work differently from dark: on light, use bolder structural
  elements (2px+ rules, solid panels) and full-strength accent hits; subtle
  glows vanish. Don't switch a light-brand club to dark — make light feel
  produced.
- Medal cards: the gated medal tints (gold/silver/bronze via
  `resolved_role_vars_for_brief`) are the accent — don't stack a second
  competing accent on top.

## Scale calibration (1080-px canvases)

| Element | Web habit | Card reality |
| --- | --- | --- |
| Hero stat / headline | 32–48px | 90–220px (fitted via `fit_font_px`) |
| Secondary line | 16–20px | 32–48px |
| Labels / metadata | 12px | 18–28px |
| Decorative opacity | 3–8% | 12–25% |
| Rules / borders | 1px | 2–6px |
| Outer padding | 16–32px | 48–96px |

If a font-size under 24px or a decorative under 10% opacity appears in a
layout, justify it.

## Photos

- Crop by `saliency.focus_position`, never by geometric centre — the
  athlete, not the pool, is the subject.
- Every photo gets a treatment (duotone, panel inset, cutout with shadow,
  lower-third scrim) so it sits *in* the design rather than pasted on. The
  treatment must not distort the subject or fabricate content.
- Text never covers the saliency focus; scrims protect legibility where
  text overlaps photo (`full_bleed_photo_lower_third` exists for this).
