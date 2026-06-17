# graphic_renderer

Draws the actual picture for each card. It takes an HTML/CSS layout and turns it
into an Instagram-ready PNG image. The drawing is exact and repeatable — the same
card always comes out the same way.

`photo_adjust.py` is the optional photo touch-up step: before a real athlete or
action photo gets baked into the card, it can sharpen it, lift the contrast,
warm up the colour, and so on — using fixed, repeatable recipes (no AI). It is
off unless asked for, and it never disturbs a cutout's see-through edges.
