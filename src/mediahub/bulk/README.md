# `bulk/` — make many at once, but a human still says yes (roadmap 1.13)

This folder does the big jobs: *"make a certificate for all 47 swimmers who got
a personal best"*, or *"a spotlight for every leaver"*. You click once, and it
makes one piece of content for each person.

The golden rule is the same as everywhere else in MediaHub: **nothing is posted
on its own.** Every item it makes is dropped into the **review queue**, where a
person looks at it and approves it (or not) before it goes anywhere. Bulk just
does the boring repetition — it never skips the human.

It also picks *who* gets one using plain, fixed rules (e.g. "everyone with a
personal best"), not a guess. And it has a safety limit so a job can't run away.

## What's in here

| File | What it does (in plain words) |
|------|-------------------------------|
| `models.py` | The shape of a big job and each item in it, plus how far it's got (10 of 47 done…). |
| `store.py` | Saves the job so you can check its progress later. Kept separate per club. |
| `generate.py` | The worker: finds who to make content for, queues each one for review, and tries to draw the actual file (e.g. a certificate). If it can't draw one, it says so for that item — it never makes a fake. |
| `README.md` | This file. |

## The rules this folder follows

- **Always review first.** Every item is queued for a person to approve. Bulk
  never approves or posts anything by itself.
- **Don't disturb decisions.** If someone already approved (or posted) a card,
  bulk leaves it alone.
- **Pick by fixed rules, not guesses.** Who gets a certificate is decided by
  deterministic filters (post type, personal-best, a named list) — never by AI.
- **Honest about failures.** If one item can't be drawn (a missing tool, say),
  that item is marked failed with the reason — the rest still go through.
- **There's a limit.** A single job is capped for safety; full per-club quotas
  arrive with the AI-governance work (roadmap 1.23).
