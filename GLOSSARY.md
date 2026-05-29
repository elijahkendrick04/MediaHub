# Word list (Glossary)

Some words in MediaHub are "tech words", or short for something longer. Here they
are in plain English. If you meet a word in the code or docs you don't know, look
here first.

## Everyday words we use a lot

- **PB** — short for **Personal Best**. The fastest a swimmer has ever gone for one
  race. Beating it is a big deal, so MediaHub loves to spot these.
- **Meet** — a swimming competition. Lots of swimmers race, and we get a file with
  all the results.
- **Card** — one finished post: a picture plus a caption, ready to share online.
- **Caption** — the words under a post (like the message under an Instagram photo).
- **Content pack** — a bundle (a ZIP file) with all the cards from one meet, ready
  to download.
- **Brand kit** — a club's "look": its colours, logo and fonts. MediaHub uses it so
  every post matches the club.
- **Voice** — how the captions "sound" (proud, fun, serious...). Each club can have
  its own voice.
- **Detector** — a small checker that looks at the results and spots one kind of
  special moment (like "this was a PB!" or "this won a medal").
- **Detector bus** — the spot where all the detectors plug in, so MediaHub can run
  them together and gather what they found. (A "bus" here means a shared connector,
  like a power strip.)
- **Ranker** — after the detectors find lots of moments, the ranker puts them in
  order from most exciting to least, so the best ones become posts first.
- **Trust ledger** — a notebook where MediaHub writes down how sure it is about a
  fact (like a swimmer's PB) and where it found it. Higher trust = more sure.
- **Creative brief** — a short plan for how a card should look (colours, layout,
  wording) before it gets drawn.
- **Cutout** — cutting a person out of a photo so we can place them on a clean
  background.
- **Schema induction** — a fancy way of saying "MediaHub works out the shape of a
  results file by itself" (which columns are times, names, ages...), even for files
  it has never seen before.
- **DATA_DIR** — a setting that tells MediaHub which folder to save its working
  files in. We never hard-code a folder; we always read this setting.
- **Monolith** — when most of a program lives in one big file. MediaHub's website
  code is like this (`web/web.py` is very large). It's on purpose — but it's why we
  keep good notes.

## Folder names that look odd (and what they really mean)

We chose to **explain** these names rather than rename them, because renaming could
break the program. Each of these folders also has its own short `README.md`.

- **`pb_discovery`** — Finds each swimmer's personal-best times by looking them up
  on the official results website. ("PB" = Personal Best.)
- **`recognition`** — The "what's special here?" brain that works for *any* sport.
  On its own it doesn't know swimming.
- **`recognition_swim`** — The swimming-only part that plugs into `recognition`.
  (Two folders so we can add other sports later without touching the shared brain.)
- **`turn_into`** — Takes one finished meet and "turns it into" seven ready-made
  things at once: a recap, swimmer spotlights, a number thread, a parent newsletter,
  a sponsor thank-you, a coach quote, and a next-meet preview.
- **`content_engine`** — The single writer that makes all the captions. It first
  *plans* the set of posts, then *writes* each one.
- **`content_pack`** — Bundles the finished cards into one ZIP you can download.
  (So: `content_engine` writes; `content_pack` packages.)
- **`ai_core`** — The low-level plumbing that talks to the AI services and switches
  from one (Gemini) to a backup (Claude) if the first one fails.
- **`media_ai`** — The everyday AI helper for captions and pictures. (So: `media_ai`
  is the wrapper you use; `ai_core` is the plumbing underneath it.)
- **`creative_brief`** — Decides the look and wording direction for each card before
  it's drawn.
- **`context_engine`** — Works out who and what a meet is about (the club, the event,
  the back-story) so the posts make sense.
- **`web_research`** — A helper that looks things up on the internet when MediaHub
  needs extra facts.

Want the full engineer version? See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
