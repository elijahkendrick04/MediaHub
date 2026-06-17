# Sprint render hooks (graphic generator)

Post-render HTML transforms for the still-graphic generator, auto-discovered at
import time (`pkgutil`). This is the graphic-side analogue of the motion
`remotion/src/compositions/sprint/` registries: a generator-sprint capability
(roadmap `G1.*`) that works by injecting CSS or an overlay into the finished card
HTML lands as its **own module here**, with **no edits to `render.py`**, so
parallel sessions never touch the same file.

## Contract

```python
# sprint_hooks/gradient_mesh_bg.py   (roadmap G1.8)
from . import RenderHookCtx

ORDER = 20  # lower runs earlier; ties break on module name

def apply(html: str, ctx: RenderHookCtx) -> str:
    if (getattr(ctx.brief, "background_style", "") or "") != "gradient_mesh":
        return html  # opt out unless this brief asked for the effect
    svg = _build_mesh(ctx.brief.palette, ctx.width, ctx.height)
    return html.replace("</body>", f'<div class="mh-mesh-bg">{svg}</div></body>', 1)
```

`apply` must be **deterministic** and should opt out (return `html` unchanged)
unless `ctx.brief` requests the effect. A hook that raises is skipped, never fatal.
A hook that no brief opts into is a no-op, so renders stay byte-identical.

## Implemented hooks

- `depth_of_field.py` (**G1.21**, `ORDER = 40`) — depth-of-field photo
  treatment. When a brief sets `photo_treatment` (or `background_style`) to a
  depth-of-field token (`depth_of_field` / `dof` / `background_blur` / …), it
  blurs the photographic background layers (`.bg-photo`, `.bg-ai`) and keeps the
  athlete cutout (`.athlete-cutout`) sharp. Pure CSS-filter transform, opt-in,
  byte-identical for every other brief.
- `animated_still.py` (**G1.29**, `ORDER = 20`) — animated still loops. When a
  brief opts in (`animate_still` truthy, `background_style == "animated_loop"`,
  or an explicit `animated_loop` name), it injects a subtle, seamlessly-looping
  animated SVG layer so a live preview of the card breathes. The matching APNG/
  GIF exporter and the loop maths live in `graphic_renderer/animated_still.py`.
  Opt-in, byte-identical for every other brief.
- `photo_tint.py` (**G1.7**, `ORDER = 40`) — photo-derived ground tinting. When
  `MEDIAHUB_PHOTO_TINT` is set, nudges a v2 card's derived `--mh-surface` (and the
  no-brand fallback ground only) toward the dominant colour of the card's photo —
  extracted by deterministic PIL k-means (`graphic_renderer.photo_palette`) —
  APCA-gated and never overriding a confirmed brand hex. Opt-in, byte-identical
  when the flag is off.
- `mono_mode.py` (**G1.19**, `ORDER = 90`) — grayscale / mono accessibility
  render. Deterministic B/W with a colour-**role remap**: the painted `--mh-*`
  tokens are rewritten to a contrast-preserving neutral-grey ramp (accent ↔ ground
  at opposite extremes, so the inverted chip and hero still pop and every APCA pair
  clears its gate), then a page-level `filter: grayscale(1)` flattens photos /
  logos / overlays / v1 grounds too. Opt in per card via `brief.render_mode` /
  `background_style` (`mono` / `monochrome` / `grayscale` / `b&w` …) or a mono
  phrase in `brief.mood` / `style_pack`, or operator-wide via the
  `MEDIAHUB_MONO_MODE` env flag (`MEDIAHUB_MONO_CONTRAST` optionally trims the B/W
  photo pass; default `1.0`). Runs last, so it desaturates earlier hooks' output too.

Capabilities that also fit this seam include **G1.8** (gradient-mesh
backgrounds), **G1.22** (icon/badge overlays) and **G1.30** (inspection
overlay). Capabilities that change formats, encoding, fonts, palettes or
text-fitting edit their own dedicated module/region instead.
