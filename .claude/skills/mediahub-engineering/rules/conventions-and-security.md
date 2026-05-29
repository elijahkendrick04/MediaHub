# Repo conventions and security

## Conventions

- **Storage:** derive every path from `DATA_DIR` — never hardcode
  `Path("data/...")`.
- **Links:** always `url_for()` — never hardcode an internal URL path.
- **Feature flags:** optional surfaces are gated by `_club_platform_ok`,
  `_v73_ok`, `_v8_ok` (in `web/web.py`). Respect the gate; don't ungate by
  default.
- **Monolith:** routes live in `web/web.py` with f-string Jinja2 templates.
- **Tests:** `python -m pytest tests/ -q`. Confirm **no new failures** vs the
  branch point (check the current baseline; don't assume a fixed count). Never
  delete / skip / weaken a test to go green.

## Removing or replacing a route / data structure

`web/web.py` is a large monolith with persisted `DATA_DIR` state and
feature-flagged surfaces. Any removal / replacement MUST follow `CLAUDE.md`'s
**15-step breakage check (before) + 15-step verification (after) + dead-code
sweep**. Prefer a clean replacement over piling on additively — but never skip
the checklists.

## Security focus

- **XSS:** all generated / user text rendered to HTML must be escaped via `_h()`
  (especially captions and athlete / club names).
- **IDOR:** run IDs and card IDs are not signed — anyone with an ID can read its
  cards. Don't widen this; deploy behind auth, and never expose a debug / admin
  route.
- **Multi-tenant isolation:** run data must not leak between profiles.
- **Uploads:** validate HY3 / ZIP / PDF (guard against zip bombs and path
  traversal).
- **Secrets:** provider keys (e.g. `ANTHROPIC_API_KEY`) must never appear in
  user-visible text or logs. `.env` only.
