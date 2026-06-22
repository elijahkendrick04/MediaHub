# `forms/` — public club forms (roadmap 1.16)

Clubs need to **collect answers from people**: trial sign-ups, volunteer rotas, kit
orders, event RSVPs. This folder builds those forms, shows them on a microsite page,
and files every answer tidily.

Where do the answers go? Into the **data hub** (the club's spreadsheet of its own
data). Each time someone fills the form in, one **new row** appears — already typed
(emails as emails, numbers as numbers), exportable to CSV/Excel, and easy to delete
if someone asks (GDPR).

Two things this folder is careful about:

1. **No rubbish gets in.** Every field is checked (is the email a real email? is a
   required box ticked?). If something's wrong, the person is told exactly what —
   nothing is silently guessed. A hidden "honeypot" box catches spam bots.
2. **Children's details are handled with care.** If a form asks for a young person's
   details, the form is marked, every sensitive answer is noted, and the stricter
   safeguarding rules apply to where it's stored.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a form: its fields and their types (text, email, phone, number, choice, tickbox, consent, date). Plain data you can save and load. |
| `store.py` | Saves each club's form designs on disk (kept separate per club). The *answers* don't live here — they go to the data hub. |
| `submit.py` | Checks a submitted form, blocks spam, and writes one tidy row into the data hub; pings the club's notifications. |
| `render.py` | Turns a form design into a real, accessible HTML form with a small built-in "send" button — no outside form service. |
| `README.md` | This file. |

## The rules this folder follows

- **Answers go to one place:** the data hub, as typed rows — exportable and deletable.
- **Honest validation:** invalid answers are reported, never quietly fixed or dropped.
- **Spam-resistant:** a hidden honeypot field plus per-visitor rate-limiting (web layer).
- **Minors first:** forms that collect a child's details are flagged and handled per policy.
- **In-house:** no third-party form provider — MediaHub renders, validates and stores it all.
- **Safe text:** every label and message is escaped, so a form can never sneak in code.

## Where to find it in the app

Forms live inside the **Sites** editor (Create → Sites): add a *form* block to a page,
design the fields, and publish. Responses show up in your **Data hub**. The web routes
that accept submissions live in `web/web.py` (search for "Club microsites").
