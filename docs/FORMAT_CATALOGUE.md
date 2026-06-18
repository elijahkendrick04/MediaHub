# Format Catalogue & "Turn this into that" (P6.1)

> **In plain words.** Once you've made and approved a design for a card, you
> often want the *same* design in a different shape — a tall Story, a square
> post, a wide YouTube thumbnail, a printable certificate, a poster for the
> noticeboard. The **format catalogue** is the master list of those shapes, and
> the **format transformer** re-makes your approved design in whichever one you
> pick — laying it out properly for the new shape instead of just stretching it.
> New here? Read [`START_HERE.md`](START_HERE.md) first.

This realises roadmap item **P6.1**. Design record:
[`adr/0021-format-catalogue-transformer.md`](adr/0021-format-catalogue-transformer.md).
Feature-by-feature map vs Canva/Adobe:
[`CREATIVE_SUITE_PARITY.md`](CREATIVE_SUITE_PARITY.md) §P6.1.

## What's in the catalogue

Every format is one entry (`FormatSpec`) in
`src/mediahub/club_platform/format_catalog.py`. Two kinds:

- **Per-channel social sizes** — the right pixels for each platform: Instagram
  post/square/story/reel cover, Facebook post/cover/event, X post/header,
  LinkedIn post/banner, Pinterest pin, TikTok, YouTube thumbnail/banner, and a
  carousel slide.
- **Off-feed club formats** — things clubs print or share that aren't a feed
  post: poster, flyer, certificate, coach contact card, quote card, athlete
  one-pager, season calendar, phone & desktop wallpapers.

Each entry knows its canvas size, its safe margins, which layouts suit its shape,
and — for the data-driven ones — what club data it needs. It's plain data: the
catalogue never calls the AI; it just tells the renderer what size to paint.

## Which formats a sport sees

A format that needs particular data says so (a **certificate** needs results; a
**season calendar** needs fixtures). The catalogue checks the sport's profile
(`data/sport_profiles/*.yaml`) and only offers a format when the sport actually
produces the data it needs. Sizes and posters are universal — every sport gets
them. (`formats_for_sport()`.)

## Custom sizes

Need something not in the list? `custom_format(width, height, unit=…)` makes a
one-off canvas in pixels, millimetres, centimetres or inches (physical units are
converted at a print dpi). Sensible bounds stop a runaway request.

## Turning a design into a format

`turn_into/transform.py` does the re-make:

- It starts from the design you **already approved** (its saved brief).
- It **keeps** the approved palette, headline, stats and photo.
- It **re-chooses the layout** to suit the new shape — a layout that looks great
  tall is wrong when wide. The AI art director picks the new layout when one is
  configured; a fixed, repeatable per-shape picker does it when the AI isn't
  available. It never invents a layout, and it never just stretches the old one.
- **Blank start:** `blank_brief_for_format()` makes a clean on-brand canvas from
  your club colours if you'd rather start from nothing.

## Using it in the app

- On the **content builder**, each approved card has a **Reformat…** button.
  Open it, pick a format (or type a custom size), and the re-made design appears
  with a download link. Tick "AI re-layout" to let the art director choose.
- Behind the scenes: `GET /api/formats` lists the catalogue;
  `POST /api/runs/<run_id>/card/<card_id>/reformat?format=<slug>` returns the
  re-rendered PNG.

## What's deliberately *not* here yet

These live in later packages so this one stays focused:

- Multi-page things (match programmes, yearbooks) → **P6.12** document engine.
- Print-ready CMYK files with bleed and crop marks → **P6.19** print pipeline.
- Dragging elements around by hand → **P6.24** pro editor.
- Saving an approved design as a reusable club template, and making hundreds at
  once → **P6.11 / P6.15**.
