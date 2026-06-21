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
- **The calendar** (`calendar.py`, `key_dates.py`) gives the plan a *month
  view*: planned drafts, club-aware key dates (the curated, provenance-stamped
  packs in `../../../data/key_dates/`), your events, blackout dates, meet
  anniversaries and what you've already posted, all on one grid. Drag a draft
  onto a day to plan when to post it (a planning intention — MediaHub never
  posts for you; you still post by hand on the day). Page: **Plan → Open
  calendar**. It is a read model over the same stores the planner reads, so the
  calendar and the ranked plan can never disagree.
- **The board** (`board.py`) is the committee whiteboard: a per-org Kanban of
  free-form idea cards in four columns (idea → drafted → approved → scheduled).
  Drag a card as it progresses, and **promote** a good idea into a real
  free-text draft with one click (seeded from the idea text verbatim — no AI, so
  it works with no provider) which then flows into the previews and the
  calendar. Page: **Plan → Board**.
- **The performance loop** feeds the plan back from real results: the club logs
  how a posted card did, and `signals.gather_performance_signals` turns the
  deterministic attribution (`../analytics/`) into a bounded, explained ranking
  nudge — "your spotlights beat your average, rank more". Page: **Plan →
  Performance**. The ranker stays deterministic; the analytics index is just
  another source-grounded signal.
- **The writer** (`engine.py`, `director.py`) makes all the captions. It first
  *plans* the set of posts (which angle, which platform), then *writes* each
  caption. Every content type goes through here, so there isn't a separate
  writer for each.

Plain-English words: see ../../../GLOSSARY.md
