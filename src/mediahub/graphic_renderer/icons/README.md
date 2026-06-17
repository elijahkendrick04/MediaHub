# Card icon / badge assets (G1.22)

Small SVG emblems the **icon/badge overlay** stamps into the corner of a finished
card — a deterministic, brand-aware way to flag *what kind of moment* a card
celebrates at a glance.

| File         | Badge        | When it shows                                  |
|--------------|--------------|-----------------------------------------------|
| `medal.svg`  | Medal disc   | A gold / silver / bronze finish                |
| `record.svg` | Honour shield| A club / county / national **record**          |
| `ribbon.svg` | PB rosette   | A personal best (`NEW PB` / `LIKELY PB`)       |
| `flag.svg`   | Nation chip  | When the card carries an athlete nationality   |

These are **template** SVGs: each one contains upper-case placeholder tokens
(`__TINT__`, `__TINT_DEEP__`, `__TEXT__`, `__BAND1..3__`, `__CODE__`,
`__UID__`, `__LABEL__`) that the overlay substitutes deterministically before it
inlines the markup. `__UID__` is replaced with a per-badge suffix so two inlined
copies on the same card never collide on a gradient/clip `id`.

The placement logic — which badges a card earns, their tints, sizes and corner
stack — lives next door in
[`../sprint_hooks/icon_overlay.py`](../sprint_hooks/icon_overlay.py). Nothing
here is AI-generated or random: same brief → same badges → same pixels.

### Flags are honest, not fabricated

`flag.svg` shows a nation's **colours plus its ISO/NOC code chip** rather than
claiming pixel-exact vexillology. Real flags vary in geometry (vertical vs
horizontal stripes, crests, unions) and a wrong flag is worse than none — so the
code chip is always visible and an unknown code falls back to a neutral cloth.
Add or correct a nation in `icon_overlay._NATIONS`.
