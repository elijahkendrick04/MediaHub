---
name: repo-tidy
description: Keeps the MediaHub repo tidy and beginner-readable. Use whenever you add a new folder or package, add or change docs, notice runtime junk getting committed, or the user asks to "clean up" / "keep it tidy" / "make it understandable". Encodes where the plain-English docs live, the README-per-folder rule, the 10-year-old readability standard, the hygiene tooling, and the hands-off rule for legacy/ and the vendored toolkits (vendor/).
metadata:
  tags: mediahub, repo-hygiene, docs, tooling, cleanup, onboarding
---

## When to use

Load this when you change repo structure or documentation, or when asked to keep
things clean and readable. It is about tidiness and onboarding, not product logic —
for engine/pipeline work use the `mediahub-engineering` skill.

## The plain-English layer (keep it readable for a 10-year-old)

A non-coder must be able to understand this repo. These files are the front door:

- **`START_HERE.md`** (root) — the no-coding tour: a "map of the rooms" table, a
  "where do I change X?" table, and an onboarding checklist.
- **`GLOSSARY.md`** (root) — plain-English meanings for jargon (PB, detector bus,
  ranker, trust ledger…) and for the deliberately-not-renamed folder names
  (`pb_discovery`, `turn_into`, `content_engine`, `ai_core` vs `media_ai`,
  `recognition` vs `recognition_swim`, `creative_brief`, `context_engine`,
  `web_research`).
- **A `README.md` in every product folder** — 1–3 plain sentences, sourced from
  `docs/ARCHITECTURE.md`'s responsibility table.
- **A plain "In plain words" intro** at the top of the key engineer docs
  (`README.md`, `docs/ARCHITECTURE.md`) and a kid-readable plan section at the top
  of `docs/ROADMAP.md`.

**Readability standard for all of the above:** short sentences; no jargon (and if a
term is unavoidable, define it in the same line); second person, present tense; a
plain analogy where it helps. Test: a bright 10-year-old can read it aloud and
explain it back. These docs **link to** the engineer docs — they never duplicate them.

## Rules that keep it tidy

1. **Add a package → add its README + a row in `START_HERE.md`'s room table.** If
   the new name is cryptic, add a `GLOSSARY.md` entry rather than renaming code.
2. **Never edit, lint, reformat, rename or delete `legacy/` or anything under
   `vendor/`.** `legacy/` is on `sys.path` (`src/mediahub/__init__.py`). `vendor/`
   holds downloaded Claude skill "marketplaces" kept for reference — NOT MediaHub
   product. Never commit a *new* downloaded marketplace/ZIP into the product tree;
   reference material belongs under `vendor/`.
3. **When editing `docs/ROADMAP.md`, keep the hand-written plain-English section
   above the `<!-- ROADMAP:... -->` marker blocks.** A GitHub Action rewrites only
   the marker blocks and heading status badges; prose outside them is safe.
4. **Run the hygiene tools, don't fight them.** `make tidy` (or
   `pre-commit run --all-files`) handles whitespace, end-of-file, the large-file
   guard and ruff. Ruff is scoped to `src/mediahub/` with a small rule set — don't
   broaden it onto `legacy/` or `vendor/`, and don't reformat the deterministic
   engine for style alone (see `mediahub-engineering`).
5. **Keep runtime junk out of git.** Caches, `node_modules`, `*.egg-info`,
   `runs_v4/`, `uploads_v4/`, `motion_cache`, `*.db` are gitignored. If something
   runtime-generated shows up in `git status`, add a `.gitignore` rule — never an
   ignore for `vendor/` (it stays tracked on purpose).
6. **Respect the bloat guard.** `.github/workflows/repo-hygiene.yml` fails a PR that
   adds an oversized file or a huge batch of new files. For an intentional big add,
   raise the limit in that workflow — don't delete the guard.

## After a structure or docs change

Re-list `src/mediahub/*`, make sure each package still has a `README.md`, update the
`START_HERE.md` room table and any new `GLOSSARY.md` term, and confirm
`python -m pytest tests/ -q` still passes with no new failures (docs/config changes
must not move the test result).
