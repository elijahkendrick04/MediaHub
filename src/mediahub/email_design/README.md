# `email_design/` — the email & newsletter composer (roadmap 1.17)

Clubs already send emails — they have a mailing-list tool. What they don't have is an
easy way to turn **this month's good news** (the personal bests, the medals, the
spotlights, the next few fixtures, a thank-you to the sponsor) into a smart, branded
newsletter without rebuilding it by hand. This folder is that composer.

Think of it like building with LEGO (the same way the cards, documents and microsites
work):

- A **newsletter** is made of **sections**.
- A **section** is made of **blocks** — a heading, some words, a button, a result
  card, a row of big numbers, a list of upcoming fixtures, a sponsor slot.

You describe the newsletter as plain data (which blocks, in which order) and the engine
prints it as **email-safe HTML**: the kind of HTML that still looks right in Outlook,
Gmail and Apple Mail — table-based, with the styles written onto every element, a tidy
dark-mode version, buttons that stay buttons, and sensible fallback text when a picture
is blocked.

Three things you can do with a finished newsletter:

1. **Download the HTML** and paste it into your existing mailing-list tool.
2. **Copy it to the clipboard** to drop straight into an email.
3. **Publish a hosted web version** — a shareable "view in your browser" link.

We **don't** send it for you (yet). MediaHub is not a mailing list — it makes the
newsletter; you send it from your own tool. (A send button can come later, and when it
does it will ask a human to approve first, like everything else here.)

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a newsletter: sections and the blocks inside them, plus the handful of email "formats". Plain data you can save and load. |
| `theme.py` | Works out your brand colours as plain colour codes the email can use directly (email can't use the website's colour variables), and uses the device's own fonts (no web-font downloads). |
| `render.py` | The printer for email. Turns a newsletter shape into email-safe HTML — and a plain-text version too. |
| `store.py` | Saves each club's newsletters on disk (kept separate per club), remembers which one is published, and looks up a published newsletter from its secret web address. |
| `README.md` | This file. |

Filled in by later builds: `grounding.py` (gathers the period's approved cards, the
planner's fixtures and the sponsor), `assemble.py` (lays them out into a newsletter),
`draft.py` (asks the AI to write *only the wording* in your club's voice — checked so it
can't invent a number — and says so honestly if no AI is set up) and `formats.py` (the
ready-made newsletter layouts).

## The rules this folder follows

- **The numbers are sacred:** result cards and stat tiles show real values only — no AI
  invents one. The AI only writes the words around them.
- **Approval before publishing:** the hosted version is a draft until a human presses
  Publish; taking it offline makes the old link stop working.
- **Always on-brand:** newsletters use your club's resolved brand colours, never
  invented ones.
- **Email-safe by construction:** tables not flexbox, styles inlined on every element,
  a dark-mode version, bulletproof buttons, and `alt` text on every image.
- **Safe text:** every bit of text is escaped, so a title or caption can never sneak in
  code.
- **No surprises:** the same newsletter shape + the same colours give the **exact same
  HTML** every time (which is how we snapshot-test it against email-client quirks).

## Where to find it in the app

Open **Create → Newsletters**, pick a format and a date range, and let it fill from your
approved content. Tweak it, preview it, then **Download / Copy** the HTML or **Publish**
the hosted version. The web routes that wire this up live in `web/web.py` (search for
"Email & newsletter composer").
