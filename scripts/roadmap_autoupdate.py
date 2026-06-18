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
     the founder list, everything else to the main (build) list.
  5. **In-depth phase plan** — the forward roadmap's "plan in depth" carries one
     section per open phase, each wrapped in ``<!-- ROADMAP:PHASE <key> -->``
     markers, with a machine-readable ``<!-- ROADMAP:PHASES -->`` registry
     mapping each phase key to the item ids that compose it. On every push the
     bot recomputes each phase's status **from the same lists above** (so the
     phase badge can never drift out of sync with its items) and, when a phase's
     every item has shipped, **moves the whole phase section into
     ``ROADMAP_BUILT.md``** (the ``BUILT_PHASES`` block) — so nothing
     already-built lingers on the forward plan.

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

  ``<!-- ROADMAP:TODO -->`` is the main list (things a build session can build);
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
                        "written (ask in any build session) · ❌ **NOT STARTED**",
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
# In-depth phase plan: bot-maintained status badges + auto-move when complete
# ---------------------------------------------------------------------------
#
# The forward roadmap's "plan in depth" used to hand-maintain a status badge per
# phase, which silently rotted: a phase whose every item had shipped still read
# "NOT STARTED". These helpers make the bot-maintained to-do / Completed lists
# the single source of truth for phase status too. Each phase section is wrapped:
#
#     <!-- ROADMAP:PHASE 2 -->
#     ### Phase 2 — Direct publishing · P4 · ❌ **NOT STARTED**
#     …prose…
#     <!-- /ROADMAP:PHASE 2 -->
#
# and a registry block maps each phase key to the item ids that compose it:
#
#     <!-- ROADMAP:PHASES
#     2 = P4.
#     5 = F.9, F.10, F.11, PC.15
#     -->
#
# A token ending in "." is a prefix glob (``P4.`` → ``P4.1``/``P4.2``/…);
# anything else is an exact id (``PC.15``, ``F.9``). On every push each phase's
# status is recomputed from its items across the two to-do lists + the Completed
# list: every item done -> **complete** (the whole section is moved to
# ROADMAP_BUILT.md's ``BUILT_PHASES`` block, date-stamped); some done / some
# in-progress -> in progress; none -> not started; no items found at all ->
# left untouched (never guess a status away).

_PHASE_STATUS = {
    "complete": ("✅", "COMPLETE"),
    "in_progress": ("\U0001F535", "IN PROGRESS"),
    "not_started": ("❌", "NOT STARTED"),
}

# Any "- **id** …" / "- ✅ **id** …" list line, with the remainder captured so a
# 🔵 in-progress badge can be spotted.
_LIST_ITEM_RE = re.compile(r"^- (?:✅\s+)?\*\*([^*]+)\*\*(.*)$", re.MULTILINE)

# The phase registry is a single hidden HTML comment (`<!-- ROADMAP:PHASES … -->`)
# so it never renders; `\b` keeps it from matching the per-phase `ROADMAP:PHASE N`
# section markers.
_PHASES_RE = re.compile(r"<!--\s*ROADMAP:PHASES\b(.*?)-->", re.DOTALL)


def parse_phase_registry(text):
    """Parse ``<!-- ROADMAP:PHASES … -->`` into ``{key: [tokens]}`` (or ``{}``).

    Each non-blank ``<key> = <tok>, <tok>, …`` line is one phase. Order is
    preserved (insertion order) so the forward plan is processed top-to-bottom.
    """
    m = _PHASES_RE.search(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, rhs = line.split("=", 1)
        toks = [t.strip() for t in rhs.split(",") if t.strip()]
        if key.strip() and toks:
            out[key.strip()] = toks
    return out


def _id_matches(ident: str, token: str) -> bool:
    """An id matches a token: prefix glob (token ends ``.``) or exact match."""
    return ident.startswith(token) if token.endswith(".") else ident == token


def _ids_in_block(body: str):
    """``[(id, is_wip)]`` for every list line in a block body."""
    return [(m.group(1), "\U0001F535" in m.group(2)) for m in _LIST_ITEM_RE.finditer(body)]


def compute_phase_status(text, registry, *, done_text=None):
    """``{key: status}`` for each phase key, read from the live lists.

    To-do items come from the two to-do blocks (in ``text``); done items from
    the DONE block (in ``done_text`` if given, else ``text``). Status values:
    ``complete`` · ``in_progress`` · ``not_started`` · ``unknown`` (no items
    matched — the section is then left untouched).
    """
    done_src = text if done_text is None else done_text
    todo_ids = []
    for name in _TODO_BLOCKS:
        m = _block_re(name).search(text)
        if m:
            todo_ids += _ids_in_block(m.group(1))
    m = _block_re("DONE").search(done_src)
    done_ids = [i for i, _ in _ids_in_block(m.group(1))] if m else []

    out = {}
    for key, tokens in registry.items():
        def hit(ident, _tokens=tokens):
            return any(_id_matches(ident, t) for t in _tokens)

        open_here = [(i, w) for (i, w) in todo_ids if hit(i)]
        done_here = [i for i in done_ids if hit(i)]
        if not open_here and not done_here:
            out[key] = "unknown"
        elif not open_here:
            out[key] = "complete"
        elif done_here or any(w for _, w in open_here):
            out[key] = "in_progress"
        else:
            out[key] = "not_started"
    return out


def _phase_block_re(key: str) -> re.Pattern:
    return re.compile(
        re.escape(f"<!-- ROADMAP:PHASE {key} -->")
        + r"(.*?)"
        + re.escape(f"<!-- /ROADMAP:PHASE {key} -->"),
        re.DOTALL,
    )


def _rewrite_phase_header(body: str, badge_md: str) -> str:
    """Replace the trailing ``· <emoji> **LABEL**`` on the block's first
    ``### …`` heading line with ``· {badge_md}`` (gating prose before it kept)."""
    return re.sub(
        r"^### .*$",
        lambda m: f"{_BADGE_RE.sub('', m.group(0))} · {badge_md}",
        body,
        count=1,
        flags=re.MULTILINE,
    )


def _prepend_built_phase(built_text: str, entry: str):
    """Prepend a finished-phase ``entry`` inside the ``BUILT_PHASES`` block
    (newest first). Returns the new text, or ``None`` if the block is absent."""
    if not _block_re("BUILT_PHASES").search(built_text):
        return None
    body = _block_re("BUILT_PHASES").search(built_text).group(1)
    new_body = "\n" + entry.strip("\n") + "\n" + body.lstrip("\n")
    return _block_re("BUILT_PHASES").sub(
        lambda _m: f"<!-- ROADMAP:BUILT_PHASES -->{new_body}<!-- /ROADMAP:BUILT_PHASES -->",
        built_text,
        count=1,
    )


def update_phases(text, built_text, registry, *, today=None):
    """Maintain phase badges and move completed phases to ``built_text``.

    For each phase in ``registry`` that has a ``ROADMAP:PHASE`` block in
    ``text``: set its header badge to the computed status, and — when complete —
    cut the whole section out of ``text`` and prepend it to ``built_text``'s
    ``BUILT_PHASES`` block (badge → ``COMPLETE (auto-moved <date>)``). Idempotent
    (a moved phase has no block left to act on). Returns
    ``(new_text, new_built, moved_keys)``.
    """
    today = today or date.today().isoformat()
    status = compute_phase_status(text, registry, done_text=built_text)
    has_target = _block_re("BUILT_PHASES").search(built_text) is not None
    out, built, moved = text, built_text, []
    for key in registry:
        m = _phase_block_re(key).search(out)
        if not m:
            continue
        body, st = m.group(1), status.get(key, "unknown")
        if st == "unknown":
            continue
        if st == "complete":
            entry = _rewrite_phase_header(
                body, f"✅ **COMPLETE (auto-moved {today})**"
            ).strip("\n")
            relocated = _prepend_built_phase(built, entry) if has_target else None
            if relocated is not None:
                out = _phase_block_re(key).sub("", out, count=1)
                built = relocated
                moved.append(key)
            else:
                # No relocation target — at least keep the in-place badge honest
                # rather than dropping a finished section on the floor.
                out = _replace_phase_body(out, key, _rewrite_phase_header(body, "✅ **COMPLETE**"))
        else:
            emoji, label = _PHASE_STATUS[st]
            new_body = _rewrite_phase_header(body, f"{emoji} **{label}**")
            if new_body != body:
                out = _replace_phase_body(out, key, new_body)
    return out, built, moved


def _replace_phase_body(text: str, key: str, new_body: str) -> str:
    return _phase_block_re(key).sub(
        lambda _m: f"<!-- ROADMAP:PHASE {key} -->{new_body}<!-- /ROADMAP:PHASE {key} -->",
        text,
        count=1,
    )


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


# How many recent non-merge commits to re-scan for `roadmap:` directives on
# every run, on top of this push's own range. The narrow push range alone is
# not enough: `main` is updated by a SHARED bot branch landed via async
# auto-merge, and under concurrent feature merges a later run rebuilds that
# branch from the freshest main — which still lacks an earlier run's *un-merged*
# roadmap delta — and force-overwrites it, applying only its own range's
# directives. Any directive whose commit sat solely in the overwritten run's
# range is then silently lost (this is how G1.2 / G1.22 / G1.30 stalled at
# NOT-STARTED despite shipping). Re-applying the directives found in a bounded
# recent window every run makes the apply self-healing: a `done` is idempotent
# (re-applying it to an already-moved item is a no-op), so a re-scan can only
# converge the lists toward the directives' intent, never corrupt them — the
# next push to land reinstates anything a force-overwrite dropped.
_DIRECTIVE_LOOKBACK = int(os.environ.get("ROADMAP_DIRECTIVE_LOOKBACK", "400"))


def _directive_messages(before: str, after: str, lookback: int | None = None):
    """Commit bodies to scan for directives, ordered oldest->newest.

    The union of this push's explicit range ``(before, after]`` and a bounded
    recent backstop (the last ``lookback`` non-merge commits ending at
    ``after``). The backstop is the self-heal; the explicit range guarantees a
    directive is never *less* likely to apply than before. Returned oldest-first
    so that — via :func:`parse_directives`' last-write-wins — the **newest**
    directive for any id is the one that takes effect.
    """
    if lookback is None:
        lookback = _DIRECTIVE_LOOKBACK
    bodies = list(_commits_in_range(before, after))  # newest-first
    if lookback > 0:
        try:
            out = _git("log", "--no-merges", f"-{int(lookback)}", "--format=%B%x1e", after)
            bodies += [c.strip() for c in out.split("\x1e") if c.strip()]
        except subprocess.CalledProcessError:
            pass
    # De-dup identical bodies (the range is a subset of the backstop), keeping
    # the first — newest — occurrence, then reverse to hand parse_directives an
    # oldest->newest stream so the latest directive for an id wins.
    seen = set()
    uniq = []
    for body in bodies:
        if body not in seen:
            seen.add(body)
            uniq.append(body)
    uniq.reverse()
    return uniq


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

    # 2. status directives → update/move list items (after the sweep, so an
    #    explicit directive wins over it). Scanned from this push's range PLUS a
    #    bounded recent backstop so a directive force-dropped by the concurrent
    #    bot-branch race (see _DIRECTIVE_LOOKBACK) self-heals on the next push.
    directives = parse_directives(_directive_messages(before, after))
    for ident, status_kw in directives:
        text, built, changed = set_item_status(text, ident, status_kw, done_text=built)
        if changed:
            applied.append(f"{ident}={status_kw}")
        else:
            print(f"note: no list item matched directive id {ident!r}", file=sys.stderr)

    # 2b. in-depth phase plan: recompute each phase's status badge from the now
    #     up-to-date lists, and MOVE any fully-complete phase section out of the
    #     forward roadmap into ROADMAP_BUILT.md — so nothing already-built ever
    #     lingers on the plan. Runs after the sweep + directives so it sees the
    #     final list state.
    registry = parse_phase_registry(text)
    if registry:
        text, built, moved_phases = update_phases(text, built, registry)
        applied += [f"phase {k}=moved" for k in moved_phases]

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
