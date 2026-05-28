"""MediaHub autonomous website tester.

Two halves, deliberately decoupled (see autotest/README.md):

* ``run``      — the *finder*. Boots the Flask app, drives the real user
                 flows in a headless browser, detects defects, and writes a
                 deduplicated, fix-ready report (reports/BUGS.md + ledger.json).
                 It never edits code.
* ``fix_loop`` — the *fixer*. Reads the ledger, prompts Claude Code
                 (``claude -p``) to fix each new bug on its own branch, opens a
                 draft PR, and — only when explicitly enabled — auto-merges to
                 the integration branch on green CI. It never touches ``main``.

The split keeps the low-risk autonomous half (finding bugs) free to run
unattended in CI every few hours, while the higher-risk half (writing code and
merging it) stays gated and runs where Claude Code is authenticated.
"""

__all__ = ["report", "run", "fix_loop"]
