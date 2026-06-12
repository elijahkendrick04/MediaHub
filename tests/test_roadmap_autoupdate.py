"""Unit tests for scripts/roadmap_autoupdate.py (the pure transforms)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import roadmap_autoupdate as ru  # noqa: E402


# --- parse_directives -------------------------------------------------------

def test_parse_directives_basic():
    msg = (
        "Implement multi-tenancy\n\n"
        "roadmap: PC.3 done\n"
        "roadmap: p1.2 wip\n"
        "roadmap: f.2 done\n"
        "roadmap: w.3 wip\n"
        "roadmap: par-3 wip\n"
        "roadmap: Step 8 blocked\n"
        "not a directive: roadmap stuff in prose\n"
    )
    got = dict(ru.parse_directives(msg))
    assert got == {
        "PC.3": "done",
        "P1.2": "wip",
        "F.2": "done",
        "W.3": "wip",
        "PAR-3": "wip",
        "Step 8": "blocked",
    }


def test_parse_directives_last_wins_and_ignores_garbage():
    got = dict(ru.parse_directives(["roadmap: PC.4 todo", "roadmap: PC.4 done", "roadmap: PC.4 banana"]))
    assert got == {"PC.4": "done"}  # invalid status 'banana' ignored, last valid wins


# --- set_item_status (the to-do / Completed list contract) -------------------

DOC = (
    "# Roadmap\n\n"
    "## To do — founder\n\n"
    "<!-- ROADMAP:TODO_FOUNDER -->\n"
    "- **F.2** · Register with the ICO and fill in the business identity · ❌ **NOT STARTED**\n"
    "- **PC.6** · Phase C 🥇 — Win the first ~10 paying clubs · 🔵 **IN PROGRESS**\n"
    "<!-- /ROADMAP:TODO_FOUNDER -->\n\n"
    "## To do — Fable 5\n\n"
    "<!-- ROADMAP:TODO -->\n"
    "- **PC.3** · Phase C 🥇 — True multi-tenancy: org → workspace · ⚠️ **BLOCKED**\n"
    "- **PC.4** · Phase C 🥇 — Pricing by revealed WTP · ❌ **NOT STARTED**\n"
    "- **P1.40** · Phase 1 — A decoy id for boundary tests · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO -->\n\n"
    "## Completed\n\n"
    "<!-- ROADMAP:DONE -->\n"
    "- ✅ **PC.1** · Phase C — Self-serve signup + auth *(completed 2026-06-09, PR #267)*\n"
    "- ✅ **F.9** · A completed founder action *(completed 2026-06-10)*\n"
    "<!-- /ROADMAP:DONE -->\n"
)


def _todo_block(text: str) -> str:
    return text.split("<!-- ROADMAP:TODO -->")[1].split("<!-- /ROADMAP:TODO -->")[0]


def _founder_block(text: str) -> str:
    return text.split("<!-- ROADMAP:TODO_FOUNDER -->")[1].split(
        "<!-- /ROADMAP:TODO_FOUNDER -->"
    )[0]


def _done_block(text: str) -> str:
    return text.split("<!-- ROADMAP:DONE -->")[1].split("<!-- /ROADMAP:DONE -->")[0]


def test_done_moves_item_from_todo_to_completed_with_date():
    out, changed = ru.set_item_status(DOC, "PC.4", "done", today="2026-06-11")
    assert changed
    assert "PC.4" not in _todo_block(out)
    assert (
        "- ✅ **PC.4** · Phase C 🥇 — Pricing by revealed WTP *(completed 2026-06-11)*"
        in _done_block(out)
    )
    # the badge is gone from the moved line; the untouched items survive intact
    assert "Pricing by revealed WTP · ❌" not in out
    assert "- **PC.3**" in _todo_block(out)
    assert "PR #267" in _done_block(out)


def test_badge_update_in_place_within_todo():
    out, changed = ru.set_item_status(DOC, "PC.3", "wip")
    assert changed
    line = next(l for l in _todo_block(out).splitlines() if "**PC.3**" in l)
    assert line.endswith("· \U0001F535 **IN PROGRESS**")
    assert "⚠️" not in line
    assert "PC.3" not in _done_block(out)


def test_demotion_moves_completed_item_back_to_todo():
    out, changed = ru.set_item_status(DOC, "PC.1", "wip")
    assert changed
    assert "PC.1" not in _done_block(out)
    line = next(l for l in _todo_block(out).splitlines() if "**PC.1**" in l)
    assert line == (
        "- **PC.1** · Phase C — Self-serve signup + auth · \U0001F535 **IN PROGRESS**"
    )
    # the completion annotation is stripped on the way back
    assert "completed 2026-06-09" not in line


def test_redone_completed_item_keeps_original_annotation():
    out, changed = ru.set_item_status(DOC, "PC.1", "done", today="2026-06-12")
    # re-affirming an already-completed item must not rewrite its history
    assert "*(completed 2026-06-09, PR #267)*" in _done_block(out)
    assert "2026-06-12" not in out
    assert not changed  # nothing material changed


def test_founder_item_done_moves_to_completed():
    out, changed = ru.set_item_status(DOC, "F.2", "done", today="2026-06-13")
    assert changed
    assert "F.2" not in _founder_block(out)
    assert (
        "- ✅ **F.2** · Register with the ICO and fill in the business identity "
        "*(completed 2026-06-13)*" in _done_block(out)
    )
    # the other founder item and the main list are untouched
    assert "- **PC.6**" in _founder_block(out)
    assert "- **PC.4**" in _todo_block(out)


def test_founder_badge_update_stays_in_founder_block():
    out, changed = ru.set_item_status(DOC, "PC.6", "blocked")
    assert changed
    line = next(l for l in _founder_block(out).splitlines() if "**PC.6**" in l)
    assert line.endswith("· ⚠️ **BLOCKED**")
    assert "PC.6" not in _todo_block(out) and "PC.6" not in _done_block(out)


def test_demoted_f_id_returns_to_the_founder_block():
    out, changed = ru.set_item_status(DOC, "F.9", "todo")
    assert changed
    assert "F.9" not in _done_block(out)
    line = next(l for l in _founder_block(out).splitlines() if "**F.9**" in l)
    assert line == "- **F.9** · A completed founder action · ❌ **NOT STARTED**"
    assert "F.9" not in _todo_block(out)


def test_demoted_non_f_id_returns_to_the_main_block():
    out, changed = ru.set_item_status(DOC, "PC.1", "wip")
    assert changed
    assert "PC.1" not in _done_block(out) and "PC.1" not in _founder_block(out)
    line = next(l for l in _todo_block(out).splitlines() if "**PC.1**" in l)
    assert line == (
        "- **PC.1** · Phase C — Self-serve signup + auth · \U0001F535 **IN PROGRESS**"
    )


def test_doc_without_founder_block_still_works():
    """A document carrying only TODO/DONE keeps the original behaviour."""
    single = (
        "<!-- ROADMAP:TODO -->\n"
        "- **PC.4** · Pricing by revealed WTP · ❌ **NOT STARTED**\n"
        "<!-- /ROADMAP:TODO -->\n"
        "<!-- ROADMAP:DONE -->\n"
        "- ✅ **F.9** · A completed founder action *(completed 2026-06-10)*\n"
        "<!-- /ROADMAP:DONE -->\n"
    )
    out, changed = ru.set_item_status(single, "PC.4", "done", today="2026-06-13")
    assert changed and "- ✅ **PC.4**" in _done_block(out)
    # demoting an F.* id falls back to the main block when no founder block exists
    out, changed = ru.set_item_status(single, "F.9", "todo")
    assert changed and "- **F.9**" in _todo_block(out)


def test_token_boundary_no_false_match():
    # 'P1.4' must not touch the decoy 'P1.40'
    out, changed = ru.set_item_status(DOC, "P1.4", "done", today="2026-06-11")
    assert not changed and out == DOC


def test_unknown_id_is_noop():
    out, changed = ru.set_item_status(DOC, "ZZ-9", "done")
    assert not changed and out == DOC


def test_unknown_status_is_noop():
    out, changed = ru.set_item_status(DOC, "PC.4", "banana")
    assert not changed and out == DOC


def test_missing_marker_blocks_is_noop():
    out, changed = ru.set_item_status("# no lists here\n", "PC.4", "done")
    assert not changed


def test_done_then_demote_round_trips_the_core_text():
    once, _ = ru.set_item_status(DOC, "PC.4", "done", today="2026-06-11")
    back, changed = ru.set_item_status(once, "PC.4", "todo")
    assert changed
    line = next(l for l in _todo_block(back).splitlines() if "**PC.4**" in l)
    assert line == "- **PC.4** · Phase C 🥇 — Pricing by revealed WTP · ❌ **NOT STARTED**"


def test_markers_and_structure_survive_every_move():
    out, _ = ru.set_item_status(DOC, "PC.4", "done", today="2026-06-11")
    out, _ = ru.set_item_status(out, "PC.1", "blocked")
    out, _ = ru.set_item_status(out, "F.2", "done", today="2026-06-11")
    out, _ = ru.set_item_status(out, "F.9", "wip")
    for marker in (
        "<!-- ROADMAP:TODO -->",
        "<!-- /ROADMAP:TODO -->",
        "<!-- ROADMAP:TODO_FOUNDER -->",
        "<!-- /ROADMAP:TODO_FOUNDER -->",
        "<!-- ROADMAP:DONE -->",
        "<!-- /ROADMAP:DONE -->",
    ):
        assert out.count(marker) == 1
    # every list line is still a well-formed bullet
    for block in (_todo_block(out), _founder_block(out), _done_block(out)):
        for line in filter(None, (l.strip() for l in block.splitlines())):
            assert line.startswith("- ")


def test_live_roadmap_file_satisfies_the_list_contract():
    """The real docs/ROADMAP.md must carry all three blocks with parseable items."""
    import re

    text = ru.ROADMAP.read_text(encoding="utf-8")
    todo = ru._block_re("TODO").search(text)
    founder = ru._block_re("TODO_FOUNDER").search(text)
    assert todo
    assert founder
    assert ru._block_re("DONE").search(text)
    # The first live item of each to-do list is movable: the transform engages
    # on the real file. Resolved dynamically so this test doesn't go stale
    # every time an item ships (a hardcoded id rotted the moment P0.1
    # completed).
    for block in (todo, founder):
        ids = re.findall(r"^- \*\*([^*]+)\*\*", block.group(1), re.MULTILINE)
        assert ids, "each to-do block must carry at least one parseable item"
        moved, changed = ru.set_item_status(text, ids[0], "done", today="2026-01-01")
        assert changed and f"- ✅ **{ids[0]}**" in moved


# --- replace_block ----------------------------------------------------------

def test_replace_block_replaces_between_markers():
    text = "intro\n<!-- ROADMAP:LAST_UPDATED -->\nOLD\n<!-- /ROADMAP:LAST_UPDATED -->\noutro\n"
    out, changed = ru.replace_block(text, "LAST_UPDATED", "NEW LINE")
    assert changed
    assert "NEW LINE" in out and "OLD" not in out
    assert out.startswith("intro") and out.rstrip().endswith("outro")


def test_replace_block_missing_markers_is_noop():
    text = "no markers here\n"
    out, changed = ru.replace_block(text, "ACTIVITY", "X")
    assert not changed and out == text


def test_replace_block_idempotent():
    text = "<!-- ROADMAP:ACTIVITY -->\nA\n<!-- /ROADMAP:ACTIVITY -->\n"
    once, _ = ru.replace_block(text, "ACTIVITY", "B")
    twice, _ = ru.replace_block(once, "ACTIVITY", "B")
    assert once == twice


# --- renderers --------------------------------------------------------------

def test_render_stamp_format():
    s = ru.render_stamp("2026-05-21", "c338ab4abc123", "Consolidate roadmap")
    assert s.startswith("**Last updated:** 2026-05-21 · `c338ab4ab`")
    assert "Consolidate roadmap" in s


def test_render_activity_escapes_pipes_and_handles_empty():
    rows = ru.render_activity([("2026-05-21", "deadbeef00", "feat: a|b table break")])
    assert "feat: a\\|b table break" in rows
    assert "| Date | Commit | Summary |" in rows
    empty = ru.render_activity([])
    assert "no recent activity" in empty
