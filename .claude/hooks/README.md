# `.claude/hooks/` — Claude Code hooks for MediaHub

These are small scripts the Claude Code harness runs automatically at certain
moments. They are **developer tooling only** — they are not part of the
MediaHub product and never ship to customers. They're wired up in
[`.claude/settings.json`](../settings.json).

## What's here

### `session-start.sh` — runs once when a web session boots
Installs everything a fresh remote container needs to render graphics and
motion (Python deps, MediaHub in editable mode, the matching Playwright
Chromium, and the Remotion `node_modules`). It only does work in the Claude
Code on the web container and is safe to re-run — each step skips if it's
already done.

### `guard-edits.py` — runs before every Edit / Write / MultiEdit
A safety net that turns two written-down rules in `CLAUDE.md` into something
the harness checks automatically, so a reviewer doesn't have to catch them by
eye:

1. **Secret leak → blocks the edit.** If an edit would hard-code a real
   provider API key (an `sk-ant-…` or `AIza…` token, or
   `GEMINI_API_KEY = "<literal>"`), the edit is refused. Keys belong in the
   gitignored `.env`, read at runtime via `os.environ` / `getenv` — never
   written into a source file, test, or comment. Editing `.env` itself is
   allowed (that's where a real key is meant to live).
2. **Banned CDN on a UI surface → warns (does not block).** If a change to a
   `.css` / template / `web.py` UI surface reintroduces the Google Fonts or
   Tailwind Play CDN, you get an early note. (Fonts are self-hosted on every
   surface; `tests/test_self_hosted_fonts.py` will hard-fail the font CDNs
   anyway — this just catches it sooner.)

The guard fails open: any unexpected or malformed input is allowed through, so
it can never wedge your editing.

## Attribution

`guard-edits.py` adapts two ideas from the
[ECC](https://github.com/affaan-m/ECC) agent-harness project (MIT-licensed):
its secrets-detection pre-tool hook and its "generic SaaS template"
design-quality hook. ECC's originals are Node/JS for a generic stack; this is a
dependency-free Python rewrite tied to MediaHub's own `CLAUDE.md` rules.
