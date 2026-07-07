# graphic_renderer

Draws the actual picture for each card. It takes an HTML/CSS layout and turns it
into an Instagram-ready PNG image. The drawing is exact and repeatable — the same
card always comes out the same way.

`photo_adjust.py` is the photo touch-up step: before a real athlete or action
photo gets baked into the card, it sharpens it, lifts the contrast, warms up
the colour, and so on — using fixed, repeatable recipes (no AI). Every card's
recipe is keyed to its mood (a celebratory card gets a punchier look than a
calm one), and it never disturbs a cutout's see-through edges.

`matte.py` is the cutout quality gate: before a background-removed athlete
picture is allowed onto a card, it measures the see-through mask with plain
image maths (how much of the frame the subject fills, whether it is one solid
shape or shredded pieces, whether the background was really removed). A bad
cutout is rejected and the card honestly uses the original photograph instead,
with the reason recorded on the card's trace.

## SVG vector export (`svg_export.py`, roadmap G1.13)

Alongside the PNG you can ask for an **editable, outlined-font SVG** of the same
card. Text becomes vector outlines (no font needed to open it, no `<text>`),
backgrounds and shapes become vector paths, and only a real photo stays as an
embedded picture — it is never a screenshot wrapped in an SVG.

How it works: Chromium renders the card to a vector PDF (the same self-hosted
fonts and brand colours as the PNG), then PDFium reads it back and we re-emit
every glyph, shape and photo as SVG, reading colours from the rendered pixels so
gradients and tints come out the colour they actually show.

```python
from mediahub.graphic_renderer import html_to_svg, render_html_to_svg

svg = html_to_svg(card_html, (1080, 1350))            # → SVG string
render_html_to_svg(card_html, "card.svg", (1080, 1350))  # → writes the file
```

Set `MEDIAHUB_SVG_SIDECAR=1` and every `render_brief` drops a `<name>.svg` next
to its `<name>.png`. It is off by default because the SVG needs a second render
pass. Pass `embed_images=False` for a strictly raster-free export (photos become
labelled placeholder boxes).
