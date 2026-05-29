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
| `skills-main/`, `ui-ux-pro-max-skill-main/`, `agent-skills-main/`, `bencium-marketplace-main/`, `taste-skill-main/`, `claude-marketplace-main/` | **Downloaded toolkits — NOT part of MediaHub.** They're reference kits kept for ideas. You can ignore them. |

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

## If you're joining the team

1. Read this page (you're here! ✅).
2. Read the plan in plain English: the top of **[`docs/ROADMAP.md`](docs/ROADMAP.md)**
   — it says where we are now and what's next.
3. Hit a word you don't know? Look it up in **[`GLOSSARY.md`](GLOSSARY.md)**.
4. Want the deep technical version? See **[`README.md`](README.md)** and
   **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

Welcome aboard! 🏊
