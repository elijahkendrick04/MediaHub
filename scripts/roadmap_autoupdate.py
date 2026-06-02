"""Auto-update ``docs/ROADMAP.md`` on each push to ``main``.

Driven by ``.github/workflows/roadmap-autoupdate.yml``. Given the commits in
a push it does three things, all idempotent and confined to marker blocks /
heading badges so hand-written prose is never touched:

  1. **Last-updated stamp** — date + short SHA + subject of the pushed tip.
  2. **Recent-activity feed** — the last N non-bot commits as a small table.
  3. **Status directives** — any ``roadmap: <ID> <status>`` line found in the
     pushed commit messages flips the status badge on the matching roadmap
     heading. (These directives are now **human-authored**: the autonomous
     roadmap builder/acceptance loop that used to emit them has been removed;
     this script still applies any you write by hand in a commit message.)

Directive convention (put one per line in any commit message)::

    roadmap: SEQ-1 done
    roadmap: PAR-3 wip
    roadmap: 1.7 wip
    roadmap: Step 8 blocked

IDs: a phase id (``1.6``, ``2.1`` …), or ``PAR-N`` / ``SEQ-N`` / ``Step N``
(Appendix A/B). Statuses: ``done | wip | blocked | todo``.

The pure transformation helpers (``parse_directives``, ``set_status``,
``replace_block``, ``render_stamp``, ``render_activity``) take no git/IO and
are unit-tested in ``tests/test_roadmap_autoupdate.py``. ``main()`` wires them
to ``git`` and the file on disk.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "docs" / "ROADMAP.md"

# Status keyword -> (emoji, label) rendered into a heading badge.
STATUS = {
    "done": ("✅", "DONE"),
    "wip": ("\U0001F535", "IN PROGRESS"),
    "blocked": ("⚠️", "BLOCKED"),
    "todo": ("❌", "NOT STARTED"),
}

# Commits the bot itself makes — excluded from the activity feed.
_BOT_SUBJECT = "docs: auto-update roadmap"

# A trailing status badge on a heading line: " · <emoji> **LABEL**".
_BADGE_RE = re.compile(
    r"\s*·\s*(?:✅|\U0001F535|⚠️|❌)\s*\*\*[^*]+\*\*\s*$"
)

_DIRECTIVE_RE = re.compile(
    r"^\s*roadmap:\s*([A-Za-z]+[-\s]?\d+(?:\.\d+)?|\d+\.\d+)\s+"
    r"(done|wip|blocked|todo)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _norm_id(raw: str) -> str:
    """Normalise a directive id: 'par-1'->'PAR-1', 'step 8'->'Step 8', '1.7'->'1.7'."""
    s = raw.strip().replace("–", "-")
    m = re.match(r"^(par|seq)[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m = re.match(r"^step[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"Step {m.group(1)}"
    return s  # phase id like 1.6 / 2.1


def parse_directives(messages):
    """Extract ``[(id, status_keyword)]`` from commit-message text(s).

    Later directives for the same id win (last write wins).
    """
    if isinstance(messages, str):
        messages = [messages]
    out = {}
    for msg in messages:
        for m in _DIRECTIVE_RE.finditer(msg or ""):
            out[_norm_id(m.group(1))] = m.group(2).lower()
    return list(out.items())


def _heading_pattern(ident: str) -> re.Pattern:
    """Regex matching the roadmap heading whose title carries ``ident`` as a token."""
    esc = re.escape(ident)
    # id followed by a non-alphanumeric boundary (space, ·, dot-not-digit, EOL)
    return re.compile(
        r"^(#{2,6})\s+(.*?\b" + esc + r")(?![\w.])(.*)$",
        re.MULTILINE,
    )


def set_status(text: str, ident: str, status_kw: str):
    """Set/replace the status badge on the heading for ``ident``.

    Returns ``(new_text, changed)``. If no matching heading exists the text is
    returned unchanged.
    """
    if status_kw not in STATUS:
        return text, False
    emoji, label = STATUS[status_kw]
    badge = f" · {emoji} **{label}**"
    pat = _heading_pattern(ident)

    def _repl(m):
        line = m.group(0)
        line = _BADGE_RE.sub("", line)  # drop any existing badge
        return line.rstrip() + badge

    new_text, n = pat.subn(_repl, text, count=1)
    return new_text, bool(n)


def replace_block(text: str, name: str, content: str):
    """Replace text between ``<!-- ROADMAP:NAME -->`` and ``<!-- /ROADMAP:NAME -->``.

    Returns ``(new_text, changed)``. No-op (with a warning) if markers absent.
    """
    start = f"<!-- ROADMAP:{name} -->"
    end = f"<!-- /ROADMAP:{name} -->"
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    block = f"{start}\n{content}\n{end}"
    if not pat.search(text):
        print(f"warning: marker block {name} not found in ROADMAP.md", file=sys.stderr)
        return text, False
    new_text = pat.sub(lambda _m: block, text, count=1)
    return new_text, new_text != text


def render_stamp(date: str, sha: str, subject: str) -> str:
    return f"**Last updated:** {date} · `{sha[:9]}` · {_md_escape(subject)}"


def render_activity(commits) -> str:
    """``commits`` is a list of ``(date, sha, subject)``; render a small table."""
    rows = ["| Date | Commit | Summary |", "|---|---|---|"]
    for date, sha, subject in commits:
        rows.append(f"| {date} | `{sha[:9]}` | {_md_escape(subject)} |")
    if len(rows) == 2:
        rows.append("| — | — | _(no recent activity)_ |")
    return "\n".join(rows)


def _md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").strip()[:100]


# ---------------------------------------------------------------------------
# git glue (not unit-tested; exercised by the workflow)
# ---------------------------------------------------------------------------

def _git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def _commits_in_range(before: str, after: str):
    """Return commit message bodies in (before, after]; fall back to the tip."""
    rng = None
    if before and not re.fullmatch(r"0+", before):
        rng = f"{before}..{after}"
    spec = [rng] if rng else ["-1", after]
    try:
        out = _git("log", "--no-merges", "--format=%B%x1e", *spec)
    except subprocess.CalledProcessError:
        out = _git("log", "--no-merges", "--format=%B%x1e", "-1", after)
    return [c.strip() for c in out.split("\x1e") if c.strip()]


def _recent_commits(n: int = 12):
    out = _git("log", "--no-merges", f"-{n + 5}", "--format=%cs%x1f%H%x1f%s%x1e")
    items = []
    for rec in out.split("\x1e"):
        rec = rec.strip()
        if not rec:
            continue
        date, sha, subject = (rec.split("\x1f") + ["", "", ""])[:3]
        if subject.startswith(_BOT_SUBJECT):
            continue
        items.append((date, sha, subject))
        if len(items) >= n:
            break
    return items


def main() -> int:
    after = os.environ.get("ROADMAP_AFTER") or "HEAD"
    before = os.environ.get("ROADMAP_BEFORE") or ""

    text = ROADMAP.read_text(encoding="utf-8")
    original = text

    # 1. status directives from this push
    directives = parse_directives(_commits_in_range(before, after))
    applied = []
    for ident, status_kw in directives:
        text, changed = set_status(text, ident, status_kw)
        if changed:
            applied.append(f"{ident}={status_kw}")
        else:
            print(f"note: no heading matched directive id {ident!r}", file=sys.stderr)

    # 2. last-updated stamp
    tip = _git("show", "-s", "--format=%cs\x1f%H\x1f%s", after).strip().split("\x1f")
    date, sha, subject = (tip + ["", "", ""])[:3]
    text, _ = replace_block(text, "LAST_UPDATED", render_stamp(date, sha, subject))

    # 3. recent-activity feed
    text, _ = replace_block(text, "ACTIVITY", render_activity(_recent_commits()))

    if text != original:
        ROADMAP.write_text(text, encoding="utf-8")
        print("roadmap updated" + (f" (status: {', '.join(applied)})" if applied else ""))
        return 0
    print("roadmap unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
