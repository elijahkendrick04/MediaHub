# `data_hub/` — your club's data, as tables you can browse and edit (roadmap 1.13)

MediaHub already understands your results — who swam, who got a personal best,
who holds a club record. This folder shows you all of that as plain **tables**,
like a tidy spreadsheet, and lets you keep your own tables too (a roster, your
sponsors, a sign-up list).

The most important idea here is **provenance** — a fancy word for *where each
number came from*. Every cell carries a little badge:

- **From results file** — the computer read it out of a meet's results.
- **Imported** — you brought it in from a spreadsheet.
- **Typed in** — a person wrote it.
- **Calculated** — a formula worked it out from other columns.
- **Synced** — it was pulled in from another source.

And here is the rule that keeps everyone honest: if a cell doesn't make sense —
a word where a time should be, a swim that didn't finish — it gets **flagged**
for a human to look at. It is *never* silently changed or hidden. The numbers
the computer is sure about are kept exactly.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a table: its columns, its rows, and each cell with its "where did this come from?" badge. Plain data that saves and loads. |
| `tables.py` | The **read-only** views. Turns the club's real data (athletes, results, records, swimmers, clubs, meets) into tables you can read but not change. |
| `store.py` | Your **own** tables (roster, sponsors, anything). These you *can* edit. Kept safely separate per club. |
| `portability.py` | Bring a spreadsheet in (CSV or Excel) and take one back out — a clean round-trip. Flags any cell it can't read instead of guessing. |
| `derive.py` | "Calculated" columns — e.g. work out an age group from a birth year. The maths is real code; the AI is only allowed to *suggest* a formula for a person to approve. |
| `scaffold.py` | "Make me a table for X" — the AI suggests the columns; you fill it in. If no AI is set up, it says so honestly. |
| `connectors/` | Keep a table fresh from another source on a schedule (e.g. ranking sites), always written down as "where it came from". |
| `README.md` | This file. |

## The rules this folder follows

- **Provenance on every cell.** You can always see where a value came from.
- **Flag, never guess.** A cell that doesn't fit is flagged for review — the
  "flag ambiguous rows" rule, made visible.
- **Read views are read-only.** The engine's data (results, records) is a mirror
  you can't accidentally change here; only your *own* tables are editable.
- **Facts are code; the AI only suggests.** Importing, calculating and exporting
  are deterministic. The AI may *suggest* a formula or a set of columns, but a
  person confirms it — the AI never quietly fills in a number.
- **One club can't see another's tables.** Every table is scoped to your club
  (the same tenant rule the rest of MediaHub uses).
- **Bulk generation still needs a human.** Making "a certificate for all 47 PB
  swimmers" queues them for review — nothing is posted automatically.
