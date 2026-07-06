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
    "## To do — build list\n\n"
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


def test_mid_line_badge_before_region_tag_is_stripped():
    # Hand-authored rows can carry a suffix after the badge (a region tag or a
    # completion annotation); the badge must still be stripped mid-line.
    line = (
        "- **U.5** · Scroll-driven progressive reveal · ❌ **NOT STARTED** · "
        "ANY ORDER (independent — not tied to the existing to-do sequence)"
    )
    core = ru._item_core(line)
    assert "❌" not in core and "NOT STARTED" not in core
    assert core == (
        "Scroll-driven progressive reveal · "
        "ANY ORDER (independent — not tied to the existing to-do sequence)"
    )
    done_line = (
        "- ✅ **UI2.8** · Codeblock raw parsed-data view · ❌ **NOT STARTED** · "
        "🟢 ISOLATED *(completed 2026-06-17)*"
    )
    core = ru._item_core(done_line)
    assert "NOT STARTED" not in core
    assert core == "Codeblock raw parsed-data view · 🟢 ISOLATED"


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
    """The real docs split: ROADMAP.md carries the two to-do blocks; the
    Completed (DONE) block lives in ROADMAP_BUILT.md (split out 2026-06-13).
    Moving an item across the two real files engages the transform."""
    import re

    text = ru.ROADMAP.read_text(encoding="utf-8")
    built = ru.ROADMAP_BUILT.read_text(encoding="utf-8")
    todo = ru._block_re("TODO").search(text)
    founder = ru._block_re("TODO_FOUNDER").search(text)
    assert todo
    assert founder
    # the forward roadmap must NOT carry the Completed list any more …
    assert not ru._block_re("DONE").search(text)
    # … it lives in the built file.
    assert ru._block_re("DONE").search(built)
    # The first live item of each to-do list is movable across the two files.
    for block in (todo, founder):
        ids = re.findall(r"^- \*\*([^*]+)\*\*", block.group(1), re.MULTILINE)
        assert ids, "each to-do block must carry at least one parseable item"
        new_text, new_built, changed = ru.set_item_status(
            text, ids[0], "done", today="2026-01-01", done_text=built
        )
        assert changed
        assert f"- ✅ **{ids[0]}**" in new_built
        origin_line = re.search(
            r"^- \*\*" + re.escape(ids[0]) + r"\*\*.*$", block.group(1), re.MULTILINE
        ).group(0)
        assert origin_line not in new_text


# --- sweep_completed (hand-marked ✅ items move to Completed) -----------------

SWEEP_DOC = (
    "<!-- ROADMAP:TODO_FOUNDER -->\n"
    "- **F.1** · Turn payments on · ❌ **NOT STARTED**\n"
    "- **F.6** · Production ops decisions · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO_FOUNDER -->\n\n"
    "<!-- ROADMAP:TODO -->\n"
    "- **PC.14** · Phase C 🥇 (sell gate) — Operational-trust remainder · ✅ "
    "**CODE HALF SHIPPED (2026-06-12)**: email seam + backups + runbook. "
    "Founder half open = F.1/F.6\n"
    "- **PC.9** · Phase C 🥇 — In-product referral engine · ✅ **BUILT (2026-06-12)**: "
    "codes, auto-granted rewards\n"
    "- **P3.1** · Phase 3 (gated) — Second-sport engine adapter · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO -->\n\n"
    "<!-- ROADMAP:DONE -->\n"
    "- ✅ **PC.1** · Phase C — Self-serve signup + auth *(completed 2026-06-09)*\n"
    "<!-- /ROADMAP:DONE -->\n"
)


def test_sweep_moves_badge_marked_items_dated_from_the_badge():
    out, moved = ru.sweep_completed(SWEEP_DOC, today="2027-01-01")
    assert moved == ["PC.14", "PC.9"]
    todo = _todo_block(out)
    assert "PC.14" not in todo and "PC.9" not in todo
    assert "- **P3.1**" in todo  # open items untouched
    done = _done_block(out)
    # badge dates win over `today`; the ship-detail tail is dropped (it lives
    # in the item's phase section), the description core is kept
    assert (
        "- ✅ **PC.9** · Phase C 🥇 — In-product referral engine "
        "*(completed 2026-06-12)*" in done
    )
    assert "2027-01-01" not in out


def test_sweep_keeps_named_founder_remainders_on_the_founder_list():
    out, _ = ru.sweep_completed(SWEEP_DOC)
    assert (
        "- ✅ **PC.14** · Phase C 🥇 (sell gate) — Operational-trust remainder "
        "*(completed 2026-06-12 — founder remainder: F.1/F.6)*" in _done_block(out)
    )
    founder = _founder_block(out)
    assert "- **F.1**" in founder and "- **F.6**" in founder
    # no new founder items invented for ids that already exist
    assert "F.7" not in founder


def test_sweep_files_free_text_remainder_as_a_new_founder_item():
    doc = SWEEP_DOC.replace(
        "Founder half open = F.1/F.6",
        "founder remainder: chase the printer for the gala banner",
    )
    out, _ = ru.sweep_completed(doc)
    founder = _founder_block(out)
    line = next(l for l in founder.splitlines() if "chase the printer" in l)
    # next free F-number after F.1/F.6 is F.7; flagged as needing its guide
    assert line.startswith("- **F.7** · chase the printer for the gala banner")
    assert "human half of PC.14" in line and "step-by-step guide" in line
    assert line.endswith("· ❌ **NOT STARTED**")
    assert "*(completed 2026-06-12 — founder remainder filed as F.7)*" in _done_block(out)


def test_sweep_warns_on_a_named_remainder_id_that_exists_nowhere(capsys):
    doc = SWEEP_DOC.replace("F.1/F.6", "F.1/F.99")
    out, moved = ru.sweep_completed(doc)
    assert "PC.14" in moved  # still swept — the warning is advisory
    assert "F.99" in capsys.readouterr().err
    assert "founder remainder: F.1/F.99" in _done_block(out)


def test_sweep_undated_badge_falls_back_to_today():
    doc = SWEEP_DOC.replace("**BUILT (2026-06-12)**", "**BUILT**")
    out, _ = ru.sweep_completed(doc, today="2026-06-13")
    assert "- ✅ **PC.9**" in _done_block(out)
    assert "*(completed 2026-06-13)*" in _done_block(out)


def test_sweep_moves_a_founder_list_item_too():
    doc = SWEEP_DOC.replace(
        "- **F.6** · Production ops decisions · ❌ **NOT STARTED**",
        "- **F.6** · Production ops decisions · ✅ **DONE (2026-06-14)**: all decided",
    )
    out, moved = ru.sweep_completed(doc)
    assert "F.6" in moved
    assert "F.6" not in _founder_block(out)
    assert (
        "- ✅ **F.6** · Production ops decisions *(completed 2026-06-14)*"
        in _done_block(out)
    )


def test_sweep_is_idempotent_and_noop_without_marked_items():
    once, moved = ru.sweep_completed(SWEEP_DOC)
    assert moved
    twice, moved_again = ru.sweep_completed(once)
    assert twice == once and moved_again == []
    bare = SWEEP_DOC.replace("✅", "🔵")
    out, moved = ru.sweep_completed(bare)
    assert out == bare and moved == []


def test_sweep_preserves_markers_and_bullet_shape():
    out, _ = ru.sweep_completed(SWEEP_DOC)
    for marker in (
        "<!-- ROADMAP:TODO -->",
        "<!-- /ROADMAP:TODO -->",
        "<!-- ROADMAP:TODO_FOUNDER -->",
        "<!-- /ROADMAP:TODO_FOUNDER -->",
        "<!-- ROADMAP:DONE -->",
        "<!-- /ROADMAP:DONE -->",
    ):
        assert out.count(marker) == 1
    for block in (_todo_block(out), _founder_block(out), _done_block(out)):
        for line in filter(None, (l.strip() for l in block.splitlines())):
            assert line.startswith("- ")


def test_live_roadmap_sweep_is_safe():
    """The sweep must run cleanly over the real two-file split: ROADMAP.md keeps
    its two to-do blocks, ROADMAP_BUILT.md keeps its DONE block, and anything it
    moves lands in the built Completed list. (Not asserted a no-op — marking an
    item ✅ in a PR and letting the bot sweep it is the supported flow.)"""
    text = ru.ROADMAP.read_text(encoding="utf-8")
    built = ru.ROADMAP_BUILT.read_text(encoding="utf-8")
    out, out_built, moved = ru.sweep_completed(text, done_text=built, today="2026-01-01")
    for name in ("TODO", "TODO_FOUNDER"):
        assert out.count(f"<!-- ROADMAP:{name} -->") == 1
        assert out.count(f"<!-- /ROADMAP:{name} -->") == 1
    assert out.count("<!-- ROADMAP:DONE -->") == 0          # never re-appears on the roadmap
    assert out_built.count("<!-- ROADMAP:DONE -->") == 1
    assert out_built.count("<!-- /ROADMAP:DONE -->") == 1
    done = _done_block(out_built)
    for ident in moved:
        assert f"- ✅ **{ident}**" in done


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


def test_md_escape_neutralises_marker_comment_injection():
    # A commit subject carrying an HTML comment must not become an early
    # block-end marker inside a bot-maintained block.
    subject = "fix: sneaky <!-- /ROADMAP:ACTIVITY --> subject"
    table = ru.render_activity([("2026-06-20", "deadbeef00", subject)])
    assert "<!--" not in table and "-->" not in table

    text = (
        "intro\n\n<!-- ROADMAP:ACTIVITY -->\n_old_\n<!-- /ROADMAP:ACTIVITY -->\n\ntail"
    )
    new, changed = ru.replace_block(text, "ACTIVITY", table)
    assert changed is True
    # The block round-trips intact: exactly one start + one end marker, the
    # escaped subject inside, no stale rows or dangling markers.
    assert new.count("<!-- ROADMAP:ACTIVITY -->") == 1
    assert new.count("<!-- /ROADMAP:ACTIVITY -->") == 1
    assert "_old_" not in new
    inner = new.split("<!-- ROADMAP:ACTIVITY -->")[1].split("<!-- /ROADMAP:ACTIVITY -->")[0]
    assert "sneaky" in inner
    # A second replace still targets the same, uncorrupted block.
    again, _ = ru.replace_block(new, "ACTIVITY", "fresh")
    assert "sneaky" not in again and "fresh" in again


# --- sentinel block (production findings) ------------------------------------

def test_render_sentinel_block_empty():
    out = ru.render_sentinel_block([])
    assert "No open production findings" in out


def test_render_sentinel_block_items_strip_prefix_and_escape():
    out = ru.render_sentinel_block(
        [
            {
                "number": 42,
                "html_url": "https://github.com/o/r/issues/42",
                "title": "[sentinel] Gunicorn worker timeout | wedged",
                "created_at": "2026-06-12T09:30:00Z",
            }
        ]
    )
    assert out == (
        "- [#42](https://github.com/o/r/issues/42) · "
        "Gunicorn worker timeout \\| wedged *(opened 2026-06-12)*"
    )


def test_sentinel_block_replace_round_trip():
    text = (
        "intro prose\n\n<!-- ROADMAP:SENTINEL -->\n_old_\n<!-- /ROADMAP:SENTINEL -->\n\ntail"
    )
    new, changed = ru.replace_block(
        text, "SENTINEL", ru.render_sentinel_block([])
    )
    assert changed is True
    assert "_old_" not in new
    assert "No open production findings" in new
    assert new.startswith("intro prose") and new.endswith("tail")


def test_fetch_sentinel_issues_inert_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert ru._fetch_sentinel_issues() is None


# --- two-file mode (to-do blocks in ROADMAP.md, DONE in ROADMAP_BUILT.md) ----

CF_TODO = (
    "<!-- ROADMAP:TODO_FOUNDER -->\n"
    "- **F.2** · Register with the ICO · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO_FOUNDER -->\n\n"
    "<!-- ROADMAP:TODO -->\n"
    "- **U.1** · Phase 1 — Core-flow polish · ❌ **NOT STARTED**\n"
    "- **P4.1** · Phase 2 — Bluesky + Mastodon · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO -->\n"
)
CF_BUILT = (
    "# Built\n\n<!-- ROADMAP:DONE -->\n"
    "- ✅ **PC.1** · Self-serve signup *(completed 2026-06-09)*\n"
    "<!-- /ROADMAP:DONE -->\n"
)


def test_cross_file_done_moves_todo_item_into_the_built_file():
    new_todo, new_built, changed = ru.set_item_status(
        CF_TODO, "P4.1", "done", today="2026-06-13", done_text=CF_BUILT
    )
    assert changed
    assert "P4.1" not in _todo_block(new_todo)        # gone from ROADMAP.md
    assert "<!-- ROADMAP:DONE -->" not in new_todo    # no DONE block leaks onto the roadmap
    assert (
        "- ✅ **P4.1** · Phase 2 — Bluesky + Mastodon *(completed 2026-06-13)*"
        in new_built
    )
    assert "PC.1" in new_built                         # the pre-existing built item is intact


def test_cross_file_demote_returns_built_item_to_the_right_todo_block():
    new_todo, new_built, changed = ru.set_item_status(
        CF_TODO, "PC.1", "wip", today="2026-06-13", done_text=CF_BUILT
    )
    assert changed
    assert "PC.1" not in _done_block(new_built)        # left the built file
    line = next(l for l in _todo_block(new_todo).splitlines() if "**PC.1**" in l)
    assert line.endswith("· \U0001F535 **IN PROGRESS**")  # back on the main build list


def test_cross_file_sweep_moves_marked_item_into_the_built_file():
    doc = CF_TODO.replace(
        "- **U.1** · Phase 1 — Core-flow polish · ❌ **NOT STARTED**",
        "- **U.1** · Phase 1 — Core-flow polish · ✅ **DONE (2026-06-13)**: shipped",
    )
    new_todo, new_built, moved = ru.sweep_completed(doc, done_text=CF_BUILT)
    assert moved == ["U.1"]
    assert "U.1" not in _todo_block(new_todo)
    assert (
        "- ✅ **U.1** · Phase 1 — Core-flow polish *(completed 2026-06-13)*"
        in new_built
    )
    assert "<!-- ROADMAP:DONE -->" not in new_todo
    assert new_built.count("<!-- ROADMAP:DONE -->") == 1


def test_cross_file_unknown_id_returns_both_unchanged():
    new_todo, new_built, changed = ru.set_item_status(
        CF_TODO, "ZZ-9", "done", done_text=CF_BUILT
    )
    assert not changed and new_todo == CF_TODO and new_built == CF_BUILT


# --- _directive_messages (self-healing directive scan) ----------------------
# Regression cover for the concurrency drop: the roadmap lands via a SHARED bot
# branch on an async auto-merge, so a later run can force-overwrite an earlier
# run's pending delta before its PR merges. Collecting directives from a bounded
# recent window (not just this push's narrow range) makes a dropped directive
# self-heal on the next push.

import subprocess as _sp  # noqa: E402


def _init_repo(tmp_path):
    def g(*args):
        _sp.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "Test")
    g("config", "commit.gpgsign", "false")

    def commit(text, message):
        (tmp_path / "f.txt").write_text(text, encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", message)
        return _sp.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return commit


def test_directive_messages_self_heals_a_dropped_directive(tmp_path, monkeypatch):
    commit = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    commit("0", "base")
    # A feature commit whose `done` directive a *later* run's narrow push range
    # never sees — the exact shape that stranded G1.2 / G1.22 / G1.30.
    dropped = commit("1", "feat G1.30\n\nroadmap: G1.30 done")
    after = commit("2", "feat G1.99\n\nroadmap: G1.99 done")

    # The bug: the narrow (dropped, after] range carries only the later directive.
    narrow = dict(ru.parse_directives(ru._commits_in_range(dropped, after)))
    assert "G1.30" not in narrow
    assert narrow == {"G1.99": "done"}

    # The fix: the backstop window re-includes the stranded directive, so this
    # push reinstates it (and still applies the new one).
    healed = dict(ru.parse_directives(ru._directive_messages(dropped, after)))
    assert healed["G1.30"] == "done"
    assert healed["G1.99"] == "done"


def test_directive_messages_newest_directive_for_an_id_wins(tmp_path, monkeypatch):
    commit = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    commit("0", "base")
    commit("1", "mark wip\n\nroadmap: P1.2 wip")
    after = commit("2", "later mark done\n\nroadmap: P1.2 done")
    # Even with the wide scan, the latest directive for an id is authoritative.
    healed = dict(ru.parse_directives(ru._directive_messages("", after)))
    assert healed["P1.2"] == "done"


def test_directive_messages_lookback_zero_is_push_range_only(tmp_path, monkeypatch):
    commit = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    base = commit("0", "base")
    commit("1", "old\n\nroadmap: G1.30 done")
    after = commit("2", "new\n\nroadmap: G1.99 done")
    # lookback=0 disables the backstop → behaviour collapses to the explicit range.
    got = dict(ru.parse_directives(ru._directive_messages(base, after, lookback=0)))
    assert got == {"G1.30": "done", "G1.99": "done"}


# --- in-depth phase plan (badges + auto-move when complete) ------------------
# The forward roadmap's per-phase status used to be hand-maintained and rotted
# (a phase whose every item shipped still read "NOT STARTED"). These cover the
# bot deriving each phase's badge from the live lists and moving a complete
# phase off the forward plan into ROADMAP_BUILT.md.

PHASE_FWD = (
    "# Roadmap\n\n"
    "<!-- ROADMAP:TODO -->\n"
    "- **P4.1** · Phase 2 — Bluesky · ❌ **NOT STARTED**\n"
    "- **P6.1** · Phase 3 — Format catalogue · 🔵 **IN PROGRESS**\n"
    "<!-- /ROADMAP:TODO -->\n\n"
    "<!-- ROADMAP:TODO_FOUNDER -->\n"
    "- **F.9** · Choose the name · ❌ **NOT STARTED**\n"
    "<!-- /ROADMAP:TODO_FOUNDER -->\n\n"
    "## The plan in depth\n\n"
    "<!-- ROADMAP:PHASES\n"
    "1 = U., G1.\n"
    "2 = P4.\n"
    "3 = P6.\n"
    "9 = ZZ.\n"
    "-->\n\n"
    "<!-- ROADMAP:PHASE 1 -->\n"
    "### Phase 1 — Product polish · U · ❌ **NOT STARTED**\n\n"
    "Phase one prose.\n"
    "<!-- /ROADMAP:PHASE 1 -->\n\n"
    "<!-- ROADMAP:PHASE 2 -->\n"
    "### Phase 2 — Direct publishing · P4 · ❌ **NOT STARTED**\n\n"
    "Phase two prose.\n"
    "<!-- /ROADMAP:PHASE 2 -->\n\n"
    "<!-- ROADMAP:PHASE 3 -->\n"
    "### Phase 3 — Creative suite · P6 · 🔒 gated · ❌ **NOT STARTED**\n\n"
    "Phase three prose.\n"
    "<!-- /ROADMAP:PHASE 3 -->\n"
)

PHASE_BUILT = (
    "# Built\n\n"
    "## Finished phases (newest first)\n\n"
    "<!-- ROADMAP:BUILT_PHASES -->\n"
    "<!-- /ROADMAP:BUILT_PHASES -->\n\n"
    "<!-- ROADMAP:DONE -->\n"
    "- ✅ **U.1** · Phase 1 — Core-flow polish *(completed 2026-06-13)*\n"
    "- ✅ **G1.1** · Sprint — archetypes *(completed 2026-06-16)*\n"
    "<!-- /ROADMAP:DONE -->\n"
)


def test_parse_phase_registry():
    reg = ru.parse_phase_registry(PHASE_FWD)
    assert reg == {
        "1": ["U.", "G1."],
        "2": ["P4."],
        "3": ["P6."],
        "9": ["ZZ."],
    }
    assert ru.parse_phase_registry("no markers here") == {}


def test_id_matches_glob_and_exact():
    assert ru._id_matches("P4.1", "P4.")  # prefix glob
    assert not ru._id_matches("PC.4", "P4.")  # PC.* must not match P4.
    assert ru._id_matches("PC.15", "PC.15")  # exact
    assert not ru._id_matches("PC.150", "PC.15")  # exact is not a prefix
    assert ru._id_matches("UI 1.3", "UI 1.")
    assert not ru._id_matches("UI 1.3", "U.")  # "U." must not swallow "UI …"


def test_compute_phase_status_all_outcomes():
    reg = ru.parse_phase_registry(PHASE_FWD)
    st = ru.compute_phase_status(PHASE_FWD, reg, done_text=PHASE_BUILT)
    assert st["1"] == "complete"  # U.1 + G1.1 done, none open
    assert st["2"] == "not_started"  # P4.1 open, nothing done, not wip
    assert st["3"] == "in_progress"  # P6.1 carries a 🔵 badge
    assert st["9"] == "unknown"  # ZZ.* matches nothing → never guessed


def test_update_phases_relocates_complete_and_sets_badges():
    new_fwd, new_built, moved = ru.update_phases(
        PHASE_FWD, PHASE_BUILT, ru.parse_phase_registry(PHASE_FWD), today="2026-06-17"
    )
    assert moved == ["1"]
    # Phase 1 is gone from the forward plan entirely …
    assert "<!-- ROADMAP:PHASE 1 -->" not in new_fwd
    assert "Phase 1 — Product polish" not in new_fwd
    # … and now lives in the BUILT_PHASES block, badge rewritten + dated.
    assert "Phase 1 — Product polish · U · ✅ **COMPLETE (auto-moved 2026-06-17)**" in new_built
    assert "Phase one prose." in new_built
    # Phase 3 flipped to IN PROGRESS in place, gating prose preserved.
    assert "### Phase 3 — Creative suite · P6 · 🔒 gated · 🔵 **IN PROGRESS**" in new_fwd
    # Phase 2 unchanged (already NOT STARTED) and still on the forward plan.
    assert "### Phase 2 — Direct publishing · P4 · ❌ **NOT STARTED**" in new_fwd


def test_update_phases_is_idempotent():
    once = ru.update_phases(
        PHASE_FWD, PHASE_BUILT, ru.parse_phase_registry(PHASE_FWD), today="2026-06-17"
    )
    twice = ru.update_phases(
        once[0], once[1], ru.parse_phase_registry(once[0]), today="2026-06-18"
    )
    assert twice[2] == []  # nothing left to move
    assert twice[0] == once[0]  # forward plan unchanged on the second pass
    assert twice[1] == once[1]  # built record unchanged on the second pass


def test_update_phases_no_built_target_keeps_section_in_place():
    # Without a BUILT_PHASES block, a complete phase must NOT be dropped on the
    # floor — its badge is corrected in place instead.
    built_no_target = PHASE_BUILT.replace(
        "<!-- ROADMAP:BUILT_PHASES -->\n<!-- /ROADMAP:BUILT_PHASES -->\n\n", ""
    )
    new_fwd, _new_built, moved = ru.update_phases(
        PHASE_FWD, built_no_target, ru.parse_phase_registry(PHASE_FWD)
    )
    assert moved == []
    assert "### Phase 1 — Product polish · U · ✅ **COMPLETE**" in new_fwd
