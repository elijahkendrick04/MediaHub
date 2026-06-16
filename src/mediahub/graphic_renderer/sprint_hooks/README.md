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
unless `ctx.brief` (or an explicit operator toggle) requests the effect. A hook
that raises is skipped, never fatal. A hook that opts out leaves the render
byte-identical, so the modules here are safe to ship in the always-loaded
registry.

## Shipped hooks

- **`inspect_overlay.py`** — **G1.30** render debug / inspection overlay +
  design-explainability sidecar (`graphic_renderer/inspect.py`). Off by default;
  opt in with `MEDIAHUB_INSPECT_OVERLAY=1` or a truthy `inspect_overlay` brief
  attribute. When off it returns `html` unchanged (byte-identical render).

Capabilities that also fit this seam include **G1.8** (gradient-mesh
backgrounds), **G1.19** (mono mode), **G1.21** (depth-of-field blur) and
**G1.22** (icon/badge overlays). Capabilities that change formats, encoding,
fonts, palettes or text-fitting edit their own dedicated module/region instead.
