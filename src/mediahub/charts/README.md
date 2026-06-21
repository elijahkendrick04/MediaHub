# `charts/` — turning your results into pictures (roadmap 1.11)

This folder takes the numbers MediaHub already understands — who swam, who got a
personal best, who won a medal — and draws them as a neat **picture**: a bar
chart, a line that goes up over the season, a medal table, and so on.

The most important rule lives here: **the numbers are sacred.** A computer draws
every bar and dot using the real results, exactly. The AI is *not allowed* to
draw a chart or make up a number. The AI only gets two small jobs, and they
happen in other files:

- **Pick the chart** that tells the best story (`recommend.py`, build 3).
- **Write the takeaway** in words, like *"8 of 12 swimmers got a personal best"* —
  but only using numbers the computer already worked out (`insights.py`, build 3).

Every chart comes out in **your club's own colours** automatically, and the words
on it are always checked so they're easy to read.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a chart: what kind it is, the points to plot, the axis labels. Plain data that can be saved and loaded. |
| `render.py` | The artist. Given a chart shape, it draws the actual picture (an SVG) — bars, lines, pies, tables — in your brand colours. |
| `palette.py` | Works out which of your brand colours each bar/line/slice should be, and picks a readable colour for the text. |
| `fonts.py` | Puts the club's lettering *inside* the picture so it looks right anywhere — and never loads fonts from Google (a privacy rule). |
| `README.md` | This file. |

The rest of the box: `aggregates.py` + `series.py` turn real meet data into chart
shapes; `csv_input.py` imports a spreadsheet (and flags any cell that isn't a
number instead of guessing); `recommend.py` + `insights.py` are the two small AI
jobs; and `diagrams.py` draws the picture *shapes* that aren't really charts — a
**committee org chart**, a **season timeline**, an **athlete's journey**, and a
**training flow** — from the club's roster and fixtures, in the same brand colours.

## The kinds of chart it can draw

`bar`, `hbar` (sideways bars), `line`, `progression` (a times line where *lower is
better*), `pie`, `donut`, `scatter` (dots), `table`, `medal_table`, and
`split_ladder` (the 50m splits in one race).

## The rules this folder follows

- **The numbers are sacred:** a computer plots every value from the real results.
  No AI ever draws a chart or invents a number.
- **Always on-brand:** charts only use your club's brand colours (the same `--mh-*`
  roles the cards use), never invented ones.
- **Readable text:** label colours are checked for contrast (the same APCA gate the
  cards use), so writing is never hard to read on its background.
- **No surprises:** the same chart shape + the same colours always give the
  **exact same picture**, down to the last pixel.
- **First-party fonts:** the lettering is MediaHub's own self-hosted fonts, baked
  into the picture — never fetched from a font CDN.
