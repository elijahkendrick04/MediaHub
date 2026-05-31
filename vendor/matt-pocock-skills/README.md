# matt-pocock-skills (vendored, reference only)

A small, hand-picked subset of [Matt Pocock's "Skills for Real Engineers"](https://github.com/mattpocock/skills)
(MIT licensed). These are Claude Code *skills* — folders of plain-English
instructions an AI assistant can load to do a task in a repeatable way.

**This folder is reference material, not active behaviour.** Like the other
collections under `vendor/`, these skills are copied here to read and learn
from. They are deliberately **not** placed in `.claude/skills/`, so they do
**not** auto-trigger. MediaHub's own first-party skills
(`.claude/skills/mediahub-engineering`, `.claude/skills/repo-tidy`) plus the
`code-review` skill remain the active set. Keeping these passive avoids
polluting the skill-trigger namespace — which matters for a project that
values predictable, deterministic behaviour.

## Why only six?

The upstream repo has ~30 skills across several categories. Copying all of them
would bloat a repo whose whole point is to stay tidy and readable. So we kept
only the skills that are (a) genuinely useful for a solo developer working on a
large Python Flask monolith, (b) language-agnostic, and (c) standalone — no
dependency on Matt's wider setup (a configured issue tracker, `CONTEXT.md`, or
Architecture Decision Records).

### Kept

| Skill | What it does |
| --- | --- |
| `diagnose` | A disciplined debugging loop: reproduce → minimise → hypothesise → instrument → fix → regression-test. |
| `zoom-out` | Step back and explain how a piece of code fits the bigger picture — handy for a 5000-line `web.py`. |
| `handoff` | Compact a long conversation into a handoff document another agent (or future you) can pick up. |
| `grill-me` | Relentlessly interrogate a plan or design until every branch of the decision is resolved. |
| `write-a-skill` | Scaffold a new, well-structured skill — useful because MediaHub authors its own skills. |
| `tdd` | Red-green-refactor test-first loop, with notes on mocking, interface design and refactoring. |

### Dropped (and why)

- **TypeScript / JavaScript-specific** — `migrate-to-shoehorn`, `setup-pre-commit`
  (Husky/lint-staged), `scaffold-exercises`. MediaHub is Python; these don't apply.
- **Needs Matt's ecosystem wired up** — `to-prd`, `to-issues`, `triage` (require a
  configured issue tracker), `grill-with-docs`, `improve-codebase-architecture`
  (require `CONTEXT.md` + ADRs MediaHub doesn't keep). Broken on arrival here.
- **The installer** — `setup-matt-pocock-skills` exists to bootstrap the npx
  install flow and edit `CLAUDE.md`/`AGENTS.md`. We copied by hand instead, so
  it's unnecessary and would only invite scope creep.
- **`prototype`, `caveman`, and the `personal/`, `in-progress/`, `deprecated/`
  sets** — niche, gimmicky, or unfinished; not worth the surface area.

## Provenance

- Source: <https://github.com/mattpocock/skills>
- Upstream commit: `e3b90b5238f38cdea5996e16861dcae28ef52eda`
- License: MIT (see `LICENSE`). Copyright © 2026 Matt Pocock.
- Copied verbatim; no modifications to the skill files.

To refresh, re-copy the listed folders from the upstream repo at a newer commit
and update the SHA above.
