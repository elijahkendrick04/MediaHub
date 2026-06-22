# `sites/` — the club microsite engine (roadmap 1.16)

Clubs need more than single posts. They need **little websites**: a club home page, a
**link-in-bio** page (one tidy list of buttons for your Instagram bio), a **meet
microsite** (all the info for one gala, plus the results as they land), and an
**event page** (details, a countdown, an RSVP form, a tickets link). This folder is
one engine that builds all of them, in your club's own colours, ready to share.

Think of it like building with LEGO:

- A **site** is made of **pages**.
- A **page** is made of **sections**.
- A **section** is made of **blocks** — a hero banner, a button, a row of result
  cards, a sponsor strip, a form, a QR code, a countdown.

You describe the site as plain data (which blocks, in which order), and the engine
turns it into a real **web page** in your brand.

Two rules matter most:

1. **The numbers are sacred.** Stat tiles and result cards only ever show real values
   the computer worked out. The AI only writes the *words around them* (and even then
   every number is double-checked). No AI switched on? It says so honestly — it never
   makes up a page.
2. **A human approves before it goes live.** A site is a private **draft** until you
   press **Publish**. Publishing takes a frozen snapshot and gives it a secret web
   address. Editing the draft afterwards changes nothing live until you publish again.
   Taking it offline deletes the address, so the old link simply stops working.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a site: pages, sections and the blocks inside them. Plain data you can save and load. Reuses the document engine's blocks and adds website ones (hero, buttons, card grids, sponsor strips, forms, widgets, QR). |
| `theme.py` | Paints the site in your brand colours (the same `--mh-*` roles the cards use) and uses MediaHub's own fonts — never Google's. Mobile-first and responsive. |
| `render.py` | The printer for the web. Turns a site shape into a real, self-contained HTML page. |
| `grounding.py` | Gathers your real club facts (name, links, sponsors, approved cards, numbers) — the only things a page is allowed to show. |
| `archetypes.py` | Builds the four real club sites (home, link-in-bio, meet microsite, event page) from those facts. |
| `draft.py` | Asks the AI to write *only the wording* around the facts (checked so it can't invent a number), plus SEO descriptions and image alt-text; says so honestly if no AI is set up. |
| `store.py` | Saves each club's sites on disk (kept separate per club), remembers what's published, and looks up a published site from its secret web address. |
| `cache.py` | Remembers finished assets (like a QR picture) so asking again is instant. |
| `README.md` | This file. |

Filled in by later builds: `forms` (the separate folder for forms → your data hub),
`widgets.py` (countdowns, medal tally, polls), `qr.py` (brand-coloured QR codes),
`seo.py` (sitemaps and meta tags) and `insights.py` (privacy-friendly view counts).

## The rules this folder follows

- **The numbers are sacred:** data blocks show real values only — no AI invents one.
- **Approval before publishing:** a site is a draft until a human presses Publish.
- **Always on-brand:** sites use your club's `--mh-*` brand roles, never invented colours.
- **First-party fonts:** the lettering is MediaHub's own self-hosted fonts — never a CDN.
- **Safe text:** every bit of text is escaped, so a title or caption can never sneak in code.
- **No surprises:** the same site shape + the same colours give the **exact same HTML**.

## Where to find it in the app

Open **Create → Sites**. Pick an archetype, let it fill from your club data, tweak it,
preview it on phone/tablet/desktop, then **Publish** to get a shareable link (and a QR
code for posters). The web routes that wire this up live in `web/web.py` (search for
"Club microsites").
