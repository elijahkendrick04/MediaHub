# Start Here 👋

**New to MediaHub? Read this first. No coding needed.**

## What is MediaHub?

MediaHub is a robot helper for sports clubs. You give it a file of swimming race
results, and it makes ready-to-post pictures and captions for Instagram, Facebook
and TikTok — the kind a club shares to celebrate its swimmers.

It works in steps: **read the results → spot what's special** (like a personal best
or a medal) **→ put the best moments first → make a nice picture and caption for
each one → let a human check them → download them.**

## A map of the rooms

Think of the project as a building. Here's what's in each room (folder):

| Folder | What's inside (plain English) |
|---|---|
| **`src/`** | **The actual MediaHub program. This is the important room** — almost everything lives in `src/mediahub/`. |
| `legacy/` | Older versions of the program. Newer parts still borrow bits from here, so **don't touch or delete it.** |
| `tests/` | Automatic checks that make sure the program still works after a change. |
| `docs/` | The detailed manual, written for engineers. |
| `data/` | Lookup tables the program reads (like lists of swim strokes), plus example clubs and voices. |
| `samples/`, `sample_data/` | Example results files used for trying things out and for the tests. |
| `scripts/` | Small helper programs the team runs by hand (build steps, reports). |
| `autotest/` | A robot that tests the whole app by itself in the cloud and reports bugs. |
| `.github/`, `.claude/` | Settings for the automatic cloud checks and for the AI assistant. |
| `vendor/` | **Downloaded toolkits — NOT part of MediaHub.** Reference kits (Claude skill "marketplaces") kept for ideas, tucked away in one folder. You can ignore this whole folder. |

> Each important folder has its own `README.md` with one or two plain sentences.
> Open it to learn what that folder does.

## Where do I look if I want to change…?

Open that folder's `README.md` first — it explains the folder in plain English.

| I want to change… | Look in… |
|---|---|
| How the captions **sound** | `src/mediahub/voice/` and `src/mediahub/media_ai/` |
| How the picture / **card looks** | `src/mediahub/graphic_renderer/` |
| What counts as a **"special moment"** | `src/mediahub/recognition_swim/` |
| The club **colours, logo, fonts** | `src/mediahub/brand/` and `src/mediahub/theming/` |
| The **website** and its buttons | `src/mediahub/web/` |
| Who can **sign in to which club** (workspaces) | `src/mediahub/web/tenancy.py` |
| Who each **swimmer is** across meets (and their milestones) | `src/mediahub/athletes/` |
| **Asking a question** about your own results ("when did Ella last PB?") | `src/mediahub/club_qa/` |
| **Photo / name permission** per athlete (consent) | `src/mediahub/safeguarding/` |
| The **club records** book | `src/mediahub/club_records/` |
| Your data as **browsable tables** (and "make a certificate for everyone") | `src/mediahub/data_hub/` |
| **Qualifying times** ("made Counties!") | `src/mediahub/standards/` + `data/standards/` |
| Watching a **live meet** during a gala | `src/mediahub/results_fetch/live_watch.py` |
| Watching the **server's own logs** for trouble (and safe auto-fixes) | `src/mediahub/log_sentinel/` |
| **Month / season recap** numbers | `src/mediahub/season_wrap/` |
| The founder's **selling notebook** (quotes, leads) | `src/mediahub/commercial/` |
| **Consent, "delete me", privacy rules** | `src/mediahub/compliance/` (the law paperwork: `docs/compliance/`) |

## If you're joining the team

1. Read this page (you're here! ✅).
2. Read the plan in plain English: the top of **[`docs/ROADMAP.md`](docs/ROADMAP.md)**
   — it says where we are now and what's next. Everything already shipped is
   recorded in **[`docs/ROADMAP_BUILT.md`](docs/ROADMAP_BUILT.md)**.
3. Hit a word you don't know? Look it up in **[`GLOSSARY.md`](GLOSSARY.md)**.
4. Want the deep technical version? See **[`README.md`](README.md)** and
   **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

Welcome aboard! 🏊
