# `elements/` — the sticker box for cards (roadmap 1.10)

Think of this folder as a **box of stickers and stamps** you can put on a card —
little drawings like a swimmer, a stopwatch, a trophy, a "PB" tag, a wavy line,
or a frame.

The clever part: every sticker is drawn in **black-and-blank**, with the colours
left empty. When you stick one on a card, MediaHub fills in the empty colours
with **your club's own brand colours**. So the swimmer comes out in your club
blue and gold automatically — you never get an off-brand sticker that clashes.

We keep the box **small and good** on purpose. Canva has a million clip-art
pictures; most of them look generic. MediaHub ships a tight, sporty set that
actually fits a swim-club card, and the smart bit is helping you pick the *right*
one for the moment (that's the search, added in build 2).

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of one sticker (its name, kind, tags) and where it sits on a card. |
| `catalog.py` | Opens the box and lists the stickers — both the ones we ship and any a club adds. |
| `catalog.json` | The list of shipped stickers and their labels. |
| `recolour.py` | Fills a sticker's empty colours with the club's brand colours, and checks any text is still readable. |
| `render.py` | Turns a sticker into ready-to-paste picture code (SVG). |
| `gradients.py` | Pre-made colour fades built from the club palette (no off-brand colours). |
| `assets/svg/` | The actual sticker drawings. Each one has `__SLOT__` blanks for colours. |

## How a sticker gets onto a card

1. A card "brief" lists which stickers to use and where (`elements` field).
2. At render time, `graphic_renderer/sprint_hooks/elements.py` reads that list.
3. For each one it calls `recolour` (fill in brand colours) + `render` (make the
   picture), then drops it on the card.
4. If the list is empty, the card looks **exactly** the same as before — stickers
   are always optional.

## Adding a new shipped sticker

1. Draw it as an SVG and save it in `assets/svg/`. Use the colour blanks
   `__ACCENT__`, `__GROUND__`, `__SURFACE__`, `__ON_GROUND__`, `__ON_SURFACE__`,
   `__SECONDARY__`, `__OUTLINE__` instead of real colours. Put `__UID__` on any
   `id` you use for a gradient or pattern so two copies never clash.
2. Add an entry to `catalog.json` (give it an id, name, kind, tags, keywords).
3. That's it — the tests in `tests/test_elements_*.py` check it loads and
   recolours cleanly.

## The rules this folder follows

- **Always on-brand:** stickers only ever use the club's brand colours, never
  invented ones (the same `--mh-*` roles the rest of the card uses).
- **Readable text:** if a sticker has words on it, the colour fill is checked for
  contrast (the same APCA gate the cards use).
- **No surprises:** a card with no stickers renders byte-for-byte the same as
  before. Same stickers + same colours always give the same result.
- **First-party:** the shipped stickers are MediaHub's own drawings (CC0), not
  borrowed clip-art.
