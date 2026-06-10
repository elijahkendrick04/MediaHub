"""Auto-update ``docs/ROADMAP.md`` on each push to ``main``.

Driven by ``.github/workflows/roadmap-autoupdate.yml``. Given the commits in
a push it does three things, all idempotent and confined to marker blocks so
hand-written prose is never touched:

  1. **Last-updated stamp** — date + short SHA + subject of the pushed tip.
  2. **Recent-activity feed** — the last N non-bot commits as a small table.
  3. **Status directives** — any ``roadmap: <ID> <status>`` line found in the
     pushed commit messages updates the matching item in the roadmap's two
     lists: ``done`` **moves the item from the To-do list to the Completed
     list** (date-stamped); ``wip``/``blocked``/``todo`` set the badge and
     move the item back to To do if it had been completed.

Directive convention (put one per line in any commit message)::

    roadmap: PC.3 wip
    roadmap: P1.2 done
    roadmap: P4.1 blocked

IDs are the item IDs in the lists (``PC.3``, ``P0.1`` …). Statuses:
``done | wip | blocked | todo``.

The roadmap's list contract (kept by this script):

* To-do items live between ``<!-- ROADMAP:TODO -->`` markers, one per line::

      - **<ID>** · <description> · <emoji> **<LABEL>**

* Completed items live between ``<!-- ROADMAP:DONE -->`` markers::

      - ✅ **<ID>** · <description> *(completed <date>[, refs])*

The pure transformation helpers (``parse_directives``, ``set_item_status``,
``replace_block``, ``render_stamp``, ``render_activity``) take no git/IO and
are unit-tested in ``tests/test_roadmap_autoupdate.py``. ``main()`` wires them
to ``git`` and the file on disk.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "docs" / "ROADMAP.md"

# Status keyword -> (emoji, label) rendered into an item badge.
STATUS = {
    "done": ("✅", "DONE"),
    "wip": ("\U0001F535", "IN PROGRESS"),
    "blocked": ("⚠️", "BLOCKED"),
    "todo": ("❌", "NOT STARTED"),
}

# Commits the bot itself makes — excluded from the activity feed.
_BOT_SUBJECT = "docs: auto-update roadmap"

# A trailing status badge on an item line: " · <emoji> **LABEL**".
_BADGE_RE = re.compile(
    r"\s*·\s*(?:✅|\U0001F535|⚠️|❌)\s*\*\*[^*]+\*\*\s*$"
)

# The completion annotation a Completed item carries.
_COMPLETED_RE = re.compile(r"\s*\*\(completed [^)]*\)\*\s*$")

# Id grammar: `P1.4` / `PC.3` (letters, optional . - or space, digits, optional
# .digits), bare `1.6`, `SEQ-1`/`PAR-3`, `Step 8`. The previous pattern's
# separator class lacked `.`, so `PC.x` directives silently never parsed.
_DIRECTIVE_RE = re.compile(
    r"^\s*roadmap:\s*([A-Za-z]+[-.\s]?\d+(?:\.\d+)?|\d+\.\d+)\s+"
    r"(done|wip|blocked|todo)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _norm_id(raw: str) -> str:
    """Normalise a directive id: 'pc.3'->'PC.3', 'par-1'->'PAR-1', 'step 8'->'Step 8'."""
    s = raw.strip().replace("–", "-")
    m = re.match(r"^(par|seq)[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m = re.match(r"^step[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"Step {m.group(1)}"
    return s.upper() if re.match(r"^p", s, re.IGNORECASE) else s


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


# ---------------------------------------------------------------------------
# List-item status + movement (the To-do / Completed contract)
# ---------------------------------------------------------------------------


def _block_re(name: str) -> re.Pattern:
    return re.compile(
        re.escape(f"<!-- ROADMAP:{name} -->")
        + r"(.*?)"
        + re.escape(f"<!-- /ROADMAP:{name} -->"),
        re.DOTALL,
    )


def _find_item(block_body: str, ident: str):
    """The item line for ``ident`` inside one block body, or None.

    The id must be the entire first bold token (``**PC.3**``), so ``P1.4``
    can never match ``P1.40``.
    """
    pat = re.compile(
        r"^- (?:✅\s+)?\*\*" + re.escape(ident) + r"\*\*.*$", re.MULTILINE
    )
    return pat.search(block_body)


def _item_core(line: str) -> str:
    """The item's descriptive text: everything between the id token and the
    trailing badge / completion annotation."""
    s = line.lstrip("- ").strip()
    if s.startswith("✅"):
        s = s[1:].strip()
    m = re.match(r"\*\*[^*]+\*\*\s*(?:·\s*)?(.*)$", s, re.DOTALL)
    core = m.group(1) if m else s
    core = _BADGE_RE.sub("", core)
    core = _COMPLETED_RE.sub("", core)
    return core.strip()


def _remove_line(body: str, line: str) -> str:
    return body.replace("\n" + line, "", 1)


def _append_line(body: str, line: str) -> str:
    return body.rstrip("\n") + "\n" + line + "\n"


def set_item_status(text: str, ident: str, status_kw: str, *, today: str | None = None):
    """Apply a directive to the To-do / Completed lists.

    ``done`` moves the item into the Completed block with a
    ``*(completed <date>)*`` stamp (an already-completed item keeps its
    original annotation). Any other status puts the item in the To-do block
    with the matching badge — including demoting a Completed item back to
    To do. Returns ``(new_text, changed)``; unknown ids are a no-op.
    """
    if status_kw not in STATUS:
        return text, False
    todo_m = _block_re("TODO").search(text)
    done_m = _block_re("DONE").search(text)
    if not todo_m or not done_m:
        print("warning: TODO/DONE marker blocks not found in ROADMAP.md", file=sys.stderr)
        return text, False
    todo_body, done_body = todo_m.group(1), done_m.group(1)

    in_todo = _find_item(todo_body, ident)
    in_done = None if in_todo else _find_item(done_body, ident)
    if not in_todo and not in_done:
        return text, False
    old_line = (in_todo or in_done).group(0)
    core = _item_core(old_line)

    if status_kw == "done":
        kept = _COMPLETED_RE.search(old_line) if in_done else None
        annotation = kept.group(0).strip() if kept else (
            f"*(completed {today or date.today().isoformat()})*"
        )
        new_line = f"- ✅ **{ident}** · {core} {annotation}"
        if in_done:
            new_done = done_body.replace(old_line, new_line, 1)
            new_todo = todo_body
        else:
            new_todo = _remove_line(todo_body, old_line)
            new_done = _append_line(done_body, new_line)
    else:
        emoji, label = STATUS[status_kw]
        new_line = f"- **{ident}** · {core} · {emoji} **{label}**"
        if in_todo:
            new_todo = todo_body.replace(old_line, new_line, 1)
            new_done = done_body
        else:
            new_done = _remove_line(done_body, old_line)
            new_todo = _append_line(todo_body, new_line)

    new_text = _block_re("TODO").sub(
        lambda _m: f"<!-- ROADMAP:TODO -->{new_todo}<!-- /ROADMAP:TODO -->", text, count=1
    )
    new_text = _block_re("DONE").sub(
        lambda _m: f"<!-- ROADMAP:DONE -->{new_done}<!-- /ROADMAP:DONE -->", new_text, count=1
    )
    return new_text, new_text != text


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

    # 1. status directives from this push → update/move list items
    directives = parse_directives(_commits_in_range(before, after))
    applied = []
    for ident, status_kw in directives:
        text, changed = set_item_status(text, ident, status_kw)
        if changed:
            applied.append(f"{ident}={status_kw}")
        else:
            print(f"note: no list item matched directive id {ident!r}", file=sys.stderr)

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
