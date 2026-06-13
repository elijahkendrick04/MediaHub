"""Auto-update ``docs/ROADMAP.md`` on each push to ``main``.

Driven by ``.github/workflows/roadmap-autoupdate.yml``. Given the commits in
a push it does four things, all idempotent and confined to marker blocks so
hand-written prose is never touched:

  1. **Completed-item sweep** — any to-do item already carrying a ✅ badge
     (a session marked it shipped in place instead of issuing a directive)
     is **moved off its to-do list into the Completed list**, date-stamped
     from the badge. If the item's line declares a human remainder
     (``Founder half open = F.1/F.6`` or ``founder remainder: <text>``),
     the named ``F.*`` items are kept on the founder list and referenced
     from the completion annotation; a free-text remainder is filed as a
     **new** ``F.*`` founder item flagged as needing its step-by-step guide.
  2. **Last-updated stamp** — date + short SHA + subject of the pushed tip.
  3. **Recent-activity feed** — the last N non-bot commits as a small table.
  4. **Status directives** — any ``roadmap: <ID> <status>`` line found in the
     pushed commit messages updates the matching item in the roadmap's three
     lists: ``done`` **moves the item from its to-do list to the Completed
     list** (date-stamped); ``wip``/``blocked``/``todo`` set the badge in
     place, or move the item back out of Completed — ``F.*`` ids return to
     the founder list, everything else to the main (Fable 5) list.

Directive convention (put one per line in any commit message)::

    roadmap: PC.3 wip
    roadmap: P1.2 done
    roadmap: F.2 done
    roadmap: P4.1 blocked

IDs are the item IDs in the lists (``PC.3``, ``F.1``, ``P0.1`` …). Statuses:
``done | wip | blocked | todo``.

The roadmap's list contract (kept by this script):

* To-do items live in two blocks, one item per line, same shape in both::

      - **<ID>** · <description> · <emoji> **<LABEL>**

  ``<!-- ROADMAP:TODO -->`` is the main list (things Fable 5 can build);
  ``<!-- ROADMAP:TODO_FOUNDER -->`` is the founder list (things only the
  maintainer can do — ``F.*`` ids plus the founder-owned ``PC.*`` items).
  Both are searched for directive ids; an id must be unique across them.

* Completed items live between ``<!-- ROADMAP:DONE -->`` markers, in
  ``docs/ROADMAP_BUILT.md`` (split out 2026-06-13 so the forward roadmap stays
  clean — the two to-do blocks above stay in ``docs/ROADMAP.md``)::

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
# The Completed/Done list lives in its own file (split out 2026-06-13 so the
# forward roadmap stays a clean to-do plan); this script maintains the DONE
# block there. ``main`` reads both files and writes whichever changed.
ROADMAP_BUILT = Path(__file__).resolve().parents[1] / "docs" / "ROADMAP_BUILT.md"

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
    """Normalise a directive id: 'pc.3'->'PC.3', 'f.2'->'F.2', 'par-1'->'PAR-1',
    'step 8'->'Step 8'. Every letter-prefixed id family in the lists (P*, PC.*,
    F.*, W.*) is uppercase, so uppercase them all — the old p-only rule made
    lowercase 'f.2'/'w.3' directives silently miss."""
    s = raw.strip().replace("–", "-")
    m = re.match(r"^(par|seq)[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m = re.match(r"^step[-\s]?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"Step {m.group(1)}"
    return s.upper() if re.match(r"^[a-z]", s, re.IGNORECASE) else s


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

# The two to-do blocks, in search order. TODO_FOUNDER is optional in a
# document (set_item_status degrades to single-list behaviour without it).
_TODO_BLOCKS = ("TODO", "TODO_FOUNDER")


def _demote_target(ident: str) -> str:
    """Which to-do block an item demoted out of Completed lands in.

    ``F.*`` ids are founder actions by construction; everything else defaults
    to the main list (a founder-owned ``PC.*`` item demoted here is moved by
    hand — demotion is rare and the main list is the safe default).
    """
    return "TODO_FOUNDER" if re.match(r"^F\.", ident, re.IGNORECASE) else "TODO"


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


def _apply_block_updates(text, originals, new_bodies, names):
    """Substitute the changed blocks in ``names`` back into ``text``.

    Only blocks whose body actually changed are rewritten. This lets the to-do
    blocks (in ROADMAP.md) and the DONE block (in ROADMAP_BUILT.md) be written
    back into *different* source texts from one ``new_bodies`` dict.
    """
    out = text
    for name in names:
        if name in new_bodies and new_bodies[name] != originals.get(name):
            out = _block_re(name).sub(
                lambda _m, n=name, b=new_bodies[name]: f"<!-- ROADMAP:{n} -->{b}<!-- /ROADMAP:{n} -->",
                out,
                count=1,
            )
    return out


def set_item_status(text, ident, status_kw, *, today=None, done_text=None):
    """Apply a directive to the to-do / Completed lists.

    ``done`` moves the item (from whichever to-do block holds it) into the
    Completed block with a ``*(completed <date>)*`` stamp (an
    already-completed item keeps its original annotation). Any other status
    sets the badge in place, or — for a Completed item — demotes it back to a
    to-do block (``F.*`` → the founder block, else the main block).

    The to-do blocks are read from ``text``; the DONE block is read from
    ``done_text`` when given, else from ``text``. With ``done_text=None``
    (single-document mode — used by the unit tests) it returns
    ``(new_text, changed)``; with a ``done_text`` (the two-file ROADMAP.md /
    ROADMAP_BUILT.md split) it returns ``(new_text, new_done_text, changed)``.
    Unknown ids are a no-op.
    """
    if status_kw not in STATUS:
        return (text, False) if done_text is None else (text, done_text, False)
    done_src = text if done_text is None else done_text
    bodies = {}
    for name in _TODO_BLOCKS:
        m = _block_re(name).search(text)
        if m:
            bodies[name] = m.group(1)
    m = _block_re("DONE").search(done_src)
    if m:
        bodies["DONE"] = m.group(1)
    if "TODO" not in bodies or "DONE" not in bodies:
        print("warning: TODO/DONE marker blocks not found", file=sys.stderr)
        return (text, False) if done_text is None else (text, done_text, False)

    found_in, item = None, None
    for name in (*_TODO_BLOCKS, "DONE"):
        if name in bodies:
            item = _find_item(bodies[name], ident)
            if item:
                found_in = name
                break
    if not item:
        return (text, False) if done_text is None else (text, done_text, False)
    old_line = item.group(0)
    core = _item_core(old_line)

    new_bodies = dict(bodies)
    if status_kw == "done":
        kept = _COMPLETED_RE.search(old_line) if found_in == "DONE" else None
        annotation = kept.group(0).strip() if kept else (
            f"*(completed {today or date.today().isoformat()})*"
        )
        new_line = f"- ✅ **{ident}** · {core} {annotation}"
        if found_in == "DONE":
            new_bodies["DONE"] = bodies["DONE"].replace(old_line, new_line, 1)
        else:
            new_bodies[found_in] = _remove_line(bodies[found_in], old_line)
            new_bodies["DONE"] = _append_line(bodies["DONE"], new_line)
    else:
        emoji, label = STATUS[status_kw]
        new_line = f"- **{ident}** · {core} · {emoji} **{label}**"
        if found_in == "DONE":
            target = _demote_target(ident)
            if target not in bodies:
                target = "TODO"
            new_bodies["DONE"] = _remove_line(bodies["DONE"], old_line)
            new_bodies[target] = _append_line(new_bodies[target], new_line)
        else:
            new_bodies[found_in] = bodies[found_in].replace(old_line, new_line, 1)

    if done_text is None:
        new_text = _apply_block_updates(text, bodies, new_bodies, (*_TODO_BLOCKS, "DONE"))
        return new_text, new_text != text
    new_text = _apply_block_updates(text, bodies, new_bodies, _TODO_BLOCKS)
    new_done = _apply_block_updates(done_text, bodies, new_bodies, ("DONE",))
    return new_text, new_done, (new_text != text) or (new_done != done_text)


# A ✅ badge wherever it sits on a to-do line (`· ✅ **LABEL**`). Open items
# carry ❌/🔵/⚠️ badges; a ✅ on a to-do line means a session marked the work
# shipped in place without moving the item — the sweep finishes the move.
_DONE_BADGE_ANYWHERE_RE = re.compile(r"\s*·\s*✅\s*\*\*([^*]+)\*\*")

# A `(YYYY-MM-DD)` stamp inside a badge label, e.g. `**BUILT (2026-06-12)**`.
_BADGE_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")

# A declared human remainder on a completed item's line, e.g.
# "Founder half open = F.1/F.6" or "founder remainder: chase the printer".
_REMAINDER_RE = re.compile(
    r"(?:founder|human)\s+(?:half(?:\s+open)?|remainder|part)\s*[:=]\s*([^·\n]+)",
    re.IGNORECASE,
)

_F_ID_RE = re.compile(r"^F\.\d+$", re.IGNORECASE)


def _next_f_number(bodies) -> int:
    """The next free ``F.<n>`` id across every list body given."""
    nums = [0]
    for body in bodies:
        nums.extend(int(n) for n in re.findall(r"\*\*F\.(\d+)\*\*", body))
    return max(nums) + 1


def sweep_completed(text, *, done_text=None, today=None):
    """Move every to-do item already hand-marked ✅ into the Completed list.

    The to-do blocks are read from ``text``; the DONE block from ``done_text``
    when given, else from ``text``. With ``done_text=None`` returns
    ``(new_text, moved_ids)``; with a ``done_text`` (the two-file split)
    returns ``(new_text, new_done_text, moved_ids)``.

    Sessions sometimes record a ship by editing the badge in place
    (``· ✅ **BUILT (2026-06-12)**: …``) instead of issuing a
    ``roadmap: <ID> done`` directive — the finished item then squats on its
    to-do list forever. This sweep moves each such item to Completed, dated
    from the badge's ``(YYYY-MM-DD)`` stamp when it carries one (else
    ``today``/today's date). A human remainder declared on the line
    (``Founder half open = F.1/F.6``) keeps its named ``F.*`` items on the
    founder list and is referenced from the completion annotation — a named
    id that exists nowhere is warned about; a free-text remainder
    (``founder remainder: <text>``) is filed as a new ``F.*`` founder item
    flagged as needing its step-by-step guide. Returns
    ``(new_text, moved_ids)``; idempotent — a second run is a no-op.
    """
    done_src = text if done_text is None else done_text
    bodies = {}
    for name in _TODO_BLOCKS:
        m = _block_re(name).search(text)
        if m:
            bodies[name] = m.group(1)
    m = _block_re("DONE").search(done_src)
    if m:
        bodies["DONE"] = m.group(1)
    if "TODO" not in bodies or "DONE" not in bodies:
        return (text, []) if done_text is None else (text, done_text, [])

    moved = []
    new_bodies = dict(bodies)
    for name in _TODO_BLOCKS:
        if name not in bodies:
            continue
        for item in re.finditer(r"^- \*\*([^*]+)\*\*.*$", bodies[name], re.MULTILINE):
            line, ident = item.group(0), item.group(1)
            badge = _DONE_BADGE_ANYWHERE_RE.search(line)
            if not badge:
                continue
            core = _item_core(line[: badge.start()])
            stamp = _BADGE_DATE_RE.search(badge.group(1))
            done_date = stamp.group(1) if stamp else (today or date.today().isoformat())

            suffix = ""
            remainder = _REMAINDER_RE.search(line)
            if remainder:
                rem_text = remainder.group(1).strip().rstrip(".")
                tokens = [t for t in re.split(r"[\s/,+&]+", rem_text) if t]
                if tokens and all(_F_ID_RE.match(t) for t in tokens):
                    ids = [t.upper() for t in tokens]
                    for fid in ids:
                        if not any(
                            _find_item(new_bodies[b], fid)
                            for b in ("TODO_FOUNDER", "DONE", "TODO")
                            if b in new_bodies
                        ):
                            print(
                                f"warning: {ident} names remainder {fid} "
                                "but no such list item exists",
                                file=sys.stderr,
                            )
                    suffix = f" — founder remainder: {'/'.join(ids)}"
                else:
                    target = "TODO_FOUNDER" if "TODO_FOUNDER" in new_bodies else "TODO"
                    fid = f"F.{_next_f_number(new_bodies.values())}"
                    new_bodies[target] = _append_line(
                        new_bodies[target],
                        f"- **{fid}** · {rem_text} — filed by the roadmap sweep as "
                        f"the human half of {ident}; needs its step-by-step guide "
                        "written (ask in any Fable 5 session) · ❌ **NOT STARTED**",
                    )
                    suffix = f" — founder remainder filed as {fid}"

            new_bodies[name] = _remove_line(new_bodies[name], line)
            new_bodies["DONE"] = _append_line(
                new_bodies["DONE"],
                f"- ✅ **{ident}** · {core} *(completed {done_date}{suffix})*",
            )
            moved.append(ident)

    if not moved:
        return (text, []) if done_text is None else (text, done_text, [])
    if done_text is None:
        new_text = _apply_block_updates(text, bodies, new_bodies, (*_TODO_BLOCKS, "DONE"))
        return new_text, moved
    new_text = _apply_block_updates(text, bodies, new_bodies, _TODO_BLOCKS)
    new_done = _apply_block_updates(done_text, bodies, new_bodies, ("DONE",))
    return new_text, new_done, moved


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


def render_sentinel_block(issues) -> str:
    """Render the "Production findings" list from open ``sentinel`` issues.

    ``issues`` is a list of dicts with ``number``, ``html_url``, ``title`` and
    ``created_at`` (the GitHub issues API shape). Closing an issue removes it
    here on the next refresh — the issue tracker is the source of truth."""
    if not issues:
        return "_No open production findings — the log sentinel has nothing filed._"
    rows = []
    for it in issues:
        title = _md_escape(str(it.get("title") or "").removeprefix("[sentinel]").strip())
        opened = str(it.get("created_at") or "")[:10]
        number = it.get("number")
        url = str(it.get("html_url") or "")
        rows.append(f"- [#{number}]({url}) · {title} *(opened {opened or 'unknown'})*")
    return "\n".join(rows)


def _fetch_sentinel_issues():
    """Open issues labelled ``sentinel`` via the GitHub API, or None on ANY
    failure — the caller then leaves the block untouched rather than blanking
    real findings over a transient API error. Stdlib-only (the workflow's
    runner installs nothing)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if not repo or not token:
        return None
    import json
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues?labels=sentinel&state=open&per_page=50",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"warning: sentinel issue fetch failed: {e}", file=sys.stderr)
        return None
    if not isinstance(data, list):
        return None
    # The issues API also returns PRs; a PR carries a "pull_request" key.
    return [it for it in data if isinstance(it, dict) and "pull_request" not in it]


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
    built = ROADMAP_BUILT.read_text(encoding="utf-8") if ROADMAP_BUILT.exists() else ""
    original, original_built = text, built

    # 1. completed-item sweep: anything hand-marked ✅ on a to-do list moves
    #    to the Completed list in ROADMAP_BUILT.md (no directive needed);
    #    declared human remainders are kept on / filed into the founder list.
    text, built, swept = sweep_completed(text, done_text=built)
    applied = [f"{ident}=done(sweep)" for ident in swept]

    # 2. status directives from this push → update/move list items (after the
    #    sweep, so an explicit directive in this push wins over it)
    directives = parse_directives(_commits_in_range(before, after))
    for ident, status_kw in directives:
        text, built, changed = set_item_status(text, ident, status_kw, done_text=built)
        if changed:
            applied.append(f"{ident}={status_kw}")
        else:
            print(f"note: no list item matched directive id {ident!r}", file=sys.stderr)

    # 3. last-updated stamp
    tip = _git("show", "-s", "--format=%cs\x1f%H\x1f%s", after).strip().split("\x1f")
    date, sha, subject = (tip + ["", "", ""])[:3]
    text, _ = replace_block(text, "LAST_UPDATED", render_stamp(date, sha, subject))

    # 4. recent-activity feed
    text, _ = replace_block(text, "ACTIVITY", render_activity(_recent_commits()))

    # 5. production findings — open `sentinel` issues (docs/LOG_SENTINEL.md).
    # None => API unavailable; keep the existing block rather than blank it.
    sentinel_issues = _fetch_sentinel_issues()
    if sentinel_issues is not None:
        text, _ = replace_block(text, "SENTINEL", render_sentinel_block(sentinel_issues))

    wrote = False
    if text != original:
        ROADMAP.write_text(text, encoding="utf-8")
        wrote = True
    if built != original_built:
        ROADMAP_BUILT.write_text(built, encoding="utf-8")
        wrote = True
    if wrote:
        print("roadmap updated" + (f" (status: {', '.join(applied)})" if applied else ""))
        return 0
    print("roadmap unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
