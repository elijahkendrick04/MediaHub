# Accent decorations (sprint registry)

Roadmap **R1.5**. Add a new accent decoration as its **own file** here — never edit
`StoryCard.tsx`'s `accentDecoration` switch.

```tsx
// accents/hexframe.tsx
import type { AccentDecoration } from "../registry";
const decoration: AccentDecoration = (roles, opacity, width, height) => (
  <div style={{ /* margin-safe accent geometry in roles.accent */ }} />
);
export default { name: "hexframe", decoration };
```

`name` is the `accent_style` brief token. Draw in the accent role only, in the
margins, at the supplied opacity. Keep it frame-pure (no `Math.random` /
`Date.now` / CSS animation) and `pointer-events: none`.

Shipped pack (R1.5 — sizing + style variants of the built-in accents):
`thick_stripe`, `thin_stripe`, `double_stripe`, `side_rail`, `large_brackets`,
`small_brackets`, `bracket_frame`, `corner_tabs`, `offset_badge`, plus
`diagonal_underline` (the motion twin of that long-standing vocabulary token).
Every token here is also in `creative_brief/design_spec.ACCENT_TREATMENTS` and
implemented by the still engine (`render._accent_decoration_html`), so the
design-spec director and the card copilot can actually emit it. The built-in
`accentDecoration` switch in `StoryCard.tsx` owns the base set (`stripe`,
`brackets`, `badge`, `frame`, `ribbon`, `arrow`, `underline`, `minimal`) — pick
a name here that does NOT collide with those, or the inline case wins and your
file never runs.
