# content_engine

MediaHub's strategy brain and its single caption writer.

- **The planner** (`planner.py`, `signals.py`, `inputs.py`) works out *what to
  post next*: it gathers three kinds of evidence — your own results and
  drafts, outside context like the calendar and discovered meets, and things
  you typed in (upcoming events, goals, blackout dates) — and fuses them into
  a ranked list of post types, showing the reasoning for every line. It only
  recommends; a human still approves everything. Page: **Plan** in the nav.
  Full story: ../../../docs/CONTENT_PLANNER.md
- **The writer** (`engine.py`, `director.py`) makes all the captions. It first
  *plans* the set of posts (which angle, which platform), then *writes* each
  caption. Every content type goes through here, so there isn't a separate
  writer for each.

Plain-English words: see ../../../GLOSSARY.md
