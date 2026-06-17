# content_engine

MediaHub's strategy brain and its single caption writer.

- **The planner** (`planner.py`, `signals.py`, `inputs.py`) works out *what to
  post next*: it gathers three kinds of evidence — your own results and
  drafts, outside context like the calendar and discovered meets, and things
  you typed in (upcoming events, goals, blackout dates) — and fuses them into
  a ranked list of post types, showing the reasoning for every line. It only
  recommends; a human still approves everything. Page: **Plan**, reached from
  the **Create** tab. Full story: ../../../docs/CONTENT_PLANNER.md
- **Plain-language inputs** (`nl_inputs.py`) let you *describe* what's coming
  up in your own words instead of filling in fields one by one — "County
  Champs at Ponds Forge on the 12th, we're shut the bank holiday weekend" —
  and an AI (optionally checking the web for an event's date) turns it into
  the same structured events / blackout dates / goals for you to review and
  save. The AI only proposes the inputs; the planner above still does the
  ranking.
- **The writer** (`engine.py`, `director.py`) makes all the captions. It first
  *plans* the set of posts (which angle, which platform), then *writes* each
  caption. Every content type goes through here, so there isn't a separate
  writer for each.

Plain-English words: see ../../../GLOSSARY.md
