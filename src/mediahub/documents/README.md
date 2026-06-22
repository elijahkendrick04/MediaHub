# `documents/` — the document engine (roadmap 1.15)

Clubs don't only post single pictures. They also hand out **multi-page documents**:
a **meet programme** for gala night, a **season report** for the committee, a
**sponsor proposal** to win money, and an **AGM slide deck** to present. This folder
is one engine that builds all of them, in your club's own colours, ready to print or
present.

Think of it like building with LEGO:

- A **document** is made of **sections**.
- A **section** is made of **blocks** — a heading, a paragraph, a table, a chart, a
  big number, a photo, a quote.

You describe the document as plain data (which blocks, in which order), and the engine
turns it into a real **PDF** (or a picture preview of any page).

The most important rule is the same one the charts follow: **the numbers are sacred.**
Tables, big-number tiles and embedded charts only ever show real values that the
computer worked out. The AI (added in a later build) is only allowed to *write the
words around them*, and even then every number it writes is double-checked. If no AI
is switched on, the engine says so honestly — it never makes up a report.

## What's in here (build 1 — the core)

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a document: sections, and the blocks inside them. Plain data you can save and load. |
| `theme.py` | Paints the document in your brand colours (the same `--mh-*` roles the cards use) and uses MediaHub's own fonts — never Google's. |
| `render.py` | The printer. Turns a document shape into a real web page, then into a **PDF**, or a **PNG** picture of one page. |
| `cache.py` | Remembers a finished document so asking for the exact same one again is instant. |
| `README.md` | This file. |

## Two looks from one set of colours

- **Documents** (programme / report / proposal) print on white paper: dark, easy-to-read
  text with your brand colour as the headings, lines and number tiles. Kind to the printer.
- **Decks** (the AGM) look like the social cards: the deep brand background, light text,
  bright accents — so a slideshow on the projector matches what's on Instagram.

## The rules this folder follows

- **The numbers are sacred:** data blocks show real values only — no AI ever invents one.
- **Always on-brand:** documents use your club's `--mh-*` brand roles, never invented colours.
- **First-party fonts:** the lettering is MediaHub's own self-hosted fonts, baked in — never
  fetched from a font CDN.
- **Safe text:** every bit of text is escaped, so a caption or title can never sneak in code.
- **No surprises:** the same document shape + the same colours give the **exact same PDF**.

## What comes next (later builds)

The four real club formats + AI-drafted wording (build 2); exporting to PowerPoint / Word and
turning a deck into a video, plus PDF tools like merge and reorder (build 3); the **presenter**
mode with speaker notes, a timer and your phone as a remote (build 4); and the buttons in the
app to make all of it (build 5).
