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

## New strategy words (the multi-sport, autonomy-first direction)

These come with the roadmap rebuild. Full detail lives in the new docs under
`docs/` (linked below); here they are in one plain line each.

- **Strategy brain** — the "what should we post?" thinking part in the middle of
  MediaHub. It decides the plan and writes drafts — instead of just turning one
  results file into posts. A person still reviews everything before it's used.
  ([`docs/ARCHITECTURE_TARGET.md`](docs/ARCHITECTURE_TARGET.md))
- **Hub and spoke** — the shape we're moving to: the strategy brain is the **hub**
  in the middle; the **spokes** are the things plugged into it.
- **Spoke** — one thing plugged into the hub: a way to bring information *in*
  (results, fixtures, news) or make a post *look good* (graphics, reels, voice).
  Results ingestion is now just one spoke.
- **Sport profile** — a simple settings sheet, one per sport, that says which kinds
  of posts that sport makes, what each one needs, how it's designed, and how its
  drafts are reviewed before use. ([`docs/SPORT_PROFILES.md`](docs/SPORT_PROFILES.md))
- **Post type** — one *kind* of post (a fixture announcement, a results recap, an
  athlete spotlight…). Most are the same for every sport. ([`docs/POST_TYPE_TAXONOMY.md`](docs/POST_TYPE_TAXONOMY.md))
- **Autonomy level** — the review disposition a single post type starts with: how
  a finished draft is handled before anyone uses it. Two settings: **draft_only**
  (just make a draft) and **approval_required** (a person approves it — the
  default). Either way a human signs off before any content is used; MediaHub
  never posts on its own.
- **Three-source intelligence** — the brain mixes three kinds of signal to make its
  plan: the team's **own** signals (past posts, brand voice), **external** signals
  (fixtures, results, news, rival clubs), and **direct** input (onboarding answers,
  goals, blackout dates).
- **Workspace** — one club's private room inside the shared MediaHub website. A
  club's profile, runs, photos and plans all live in its workspace, and other
  clubs can't see in. (Technically it's the same thing as an organisation
  profile — the workspace word stresses the privacy wall.)
- **Membership** — the note that says "this signed-in person belongs to that
  workspace" (as an **owner**, who can manage members, or a **member**, who can
  work inside it). Stored in `memberships.jsonl`, managed in
  `src/mediahub/web/tenancy.py`. ([`docs/adr/0014-org-workspace-multitenancy-schema.md`](docs/adr/0014-org-workspace-multitenancy-schema.md))
- **Bound / unbound workspace** — a workspace with at least one active member is
  **bound**: only its members (and the operator) can enter. One with no members
  yet is **unbound** (open) and behaves like the old single-club MediaHub — handy
  for pilots the founder still runs by hand.
- **Revealed willingness-to-pay (WTP)** — finding the right price by quoting real
  annual prices to real clubs and recording what they actually paid — instead of
  guessing. The public price stays "TBC" until 5 clubs have paid. The notebook
  for this lives in `src/mediahub/commercial/` and shows up on the operator-only
  `/operator/commercial` page.

## Folder names that look odd (and what they really mean)

We chose to **explain** these names rather than rename them, because renaming could
break the program. Each of these folders also has its own short `README.md`.

- **`pb_discovery`** — Finds each swimmer's personal-best times by looking them up
  on the official results website. ("PB" = Personal Best.)
- **`recognition`** — The "what's special here?" brain that works for *any* sport.
  On its own it doesn't know swimming.
- **`recognition_swim`** — The swimming-only part that plugs into `recognition`.
  (Two folders so we can add other sports later without touching the shared brain.)
- **`turn_into`** — Takes one finished meet and "turns it into" eight ready-made
  things at once: a recap, swimmer spotlights, a number thread, a parent newsletter
  (with an email subject line), a long-form club website report, a sponsor thank-you,
  a coach quote, and a next-meet preview.
- **`club_qa`** — Lets you ask a plain question about your club's own results — like
  "when did Ella last PB in 100 Free?" — and get an answer built only from the meets
  MediaHub has already processed, with the meets it used listed underneath. It never
  searches the web and never guesses.
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
- **`results_fetch`** — Reads a competition's results straight from a web link,
  the way a person with a browser would, and turns the whole site into a file the
  rest of MediaHub already understands. See
  [`docs/RESULTS_FROM_URL.md`](docs/RESULTS_FROM_URL.md).
- **`web_research`** — A helper that looks things up on the internet when MediaHub
  needs extra facts.
- **`log_sentinel`** — The app's night guard. It reads MediaHub's own server logs
  every minute, sends the operator a push message when something known goes wrong,
  and (only if you switch it on) can apply a small approved fix itself — like
  restarting the server — with strict daily limits and a written record of
  everything it did. See [`docs/LOG_SENTINEL.md`](docs/LOG_SENTINEL.md).

Want the full engineer version? See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
