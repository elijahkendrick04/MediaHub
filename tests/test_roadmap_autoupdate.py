"""Unit tests for scripts/roadmap_autoupdate.py (the pure transforms)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import roadmap_autoupdate as ru  # noqa: E402


# --- parse_directives -------------------------------------------------------

def test_parse_directives_basic():
    msg = (
        "Implement Tier A\n\n"
        "roadmap: SEQ-1 done\n"
        "roadmap: par-3 wip\n"
        "roadmap: 1.7 wip\n"
        "roadmap: Step 8 blocked\n"
        "not a directive: roadmap stuff in prose\n"
    )
    got = dict(ru.parse_directives(msg))
    assert got == {
        "SEQ-1": "done",
        "PAR-3": "wip",
        "1.7": "wip",
        "Step 8": "blocked",
    }


def test_parse_directives_last_wins_and_ignores_garbage():
    got = dict(ru.parse_directives(["roadmap: PAR-1 todo", "roadmap: PAR-1 done", "roadmap: PAR-1 banana"]))
    assert got == {"PAR-1": "done"}  # invalid status 'banana' ignored, last valid wins


# --- set_status -------------------------------------------------------------

def test_set_status_adds_badge_when_absent():
    text = "#### PAR-1 · Caption quality pack\nbody\n"
    out, changed = ru.set_status(text, "PAR-1", "done")
    assert changed
    assert "#### PAR-1 · Caption quality pack · ✅ **DONE**" in out


def test_set_status_replaces_existing_badge():
    text = "### 1.6 Adaptive Theming Engine · \U0001F535 **NEW — IN FLIGHT**\n"
    out, changed = ru.set_status(text, "1.6", "done")
    assert changed
    # exactly one badge, the old one gone
    assert out.count("**") == 2
    assert "✅ **DONE**" in out
    assert "IN FLIGHT" not in out


def test_set_status_token_boundary_no_false_match():
    # 'PAR-1' must not touch 'PAR-10'; '1.6' must not touch '1.60'
    text = "#### PAR-10 · Something\n### 1.60 Other\n"
    out1, c1 = ru.set_status(text, "PAR-1", "done")
    out2, c2 = ru.set_status(text, "1.6", "done")
    assert not c1 and out1 == text
    assert not c2 and out2 == text


def test_set_status_step_and_seq():
    text = "#### Step 7: Commercial Layer — Stripe\n#### SEQ-0 · DesignTokens contract\n"
    out, _ = ru.set_status(text, "Step 7", "blocked")
    out, _ = ru.set_status(out, "SEQ-0", "wip")
    assert "Step 7: Commercial Layer — Stripe · ⚠️ **BLOCKED**" in out
    assert "SEQ-0 · DesignTokens contract · \U0001F535 **IN PROGRESS**" in out


def test_set_status_unknown_id_is_noop():
    text = "### 1.6 X\n"
    out, changed = ru.set_status(text, "ZZ-9", "done")
    assert not changed and out == text


def test_set_status_idempotent():
    text = "#### PAR-2 · Auto-fit\n"
    once, _ = ru.set_status(text, "PAR-2", "done")
    twice, changed = ru.set_status(once, "PAR-2", "done")
    assert once == twice  # re-applying the same status changes nothing material
    assert "· ✅ **DONE**" in twice and twice.count("✅") == 1


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
