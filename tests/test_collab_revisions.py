"""Roadmap 1.18 build 3 — design-spec version history (collab.revisions)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.collab import revisions as rv


def _write_brief(runs_dir, run_id, brief_id, card_id, headline, layout="hero", created="2026-01-01T00:00:00Z"):
    bdir = runs_dir / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"{brief_id}.json").write_text(
        json.dumps(
            {
                "id": brief_id,
                "content_item_id": card_id,
                "text_layers": {"headline_line1": headline},
                "layout_template": layout,
                "tone": "data_led",
                "created_at": created,
            }
        )
    )


@pytest.fixture
def runs(tmp_path):
    return tmp_path / "runs_v4"


def test_list_revisions_orders_and_flags_current(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "FIRST")
    time.sleep(0.02)
    _write_brief(runs, "run1", "cb_b", "card1", "SECOND")
    revs = rv.list_revisions("run1", "card1", runs_dir=runs)
    assert [r["brief_id"] for r in revs] == ["cb_a", "cb_b"]
    assert revs[-1]["is_current"] is True
    assert revs[0]["is_current"] is False
    assert "FIRST" in revs[0]["label"]


def test_revisions_isolated_per_card(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "A")
    _write_brief(runs, "run1", "cb_b", "card2", "B")
    revs = rv.list_revisions("run1", "card1", runs_dir=runs)
    assert [r["brief_id"] for r in revs] == ["cb_a"]
    # a brief from another card can't be fetched under card1
    assert rv.get_brief("run1", "card1", "cb_b", runs_dir=runs) is None


def test_diff_revisions(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "OLD", layout="hero")
    _write_brief(runs, "run1", "cb_b", "card1", "NEW", layout="split")
    diff = rv.diff_revisions("run1", "card1", "cb_a", "cb_b", runs_dir=runs)
    fields = {d["field"]: (d["before"], d["after"]) for d in diff}
    assert fields["text_layers.headline_line1"] == ("OLD", "NEW")
    assert fields["layout_template"] == ("hero", "split")


def test_diff_missing_revision_returns_none(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "OLD")
    assert rv.diff_revisions("run1", "card1", "cb_a", "cb_missing", runs_dir=runs) is None


def test_restore_reissues_as_new_current(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "FIRST")
    time.sleep(0.02)
    _write_brief(runs, "run1", "cb_b", "card1", "SECOND")
    restored = rv.restore_revision("run1", "card1", "cb_a", runs_dir=runs)
    assert restored is not None
    assert restored["id"] != "cb_a"  # fresh id
    assert restored["restored_from"] == "cb_a"
    revs = rv.list_revisions("run1", "card1", runs_dir=runs)
    # three versions now; the restored one is current and carries FIRST's design
    assert len(revs) == 3
    assert revs[-1]["is_current"] is True
    assert "FIRST" in revs[-1]["label"]


def test_restore_missing_returns_none(runs):
    _write_brief(runs, "run1", "cb_a", "card1", "X")
    assert rv.restore_revision("run1", "card1", "cb_missing", runs_dir=runs) is None


def test_count_revisions(runs):
    assert rv.count_revisions("run1", "card1", runs_dir=runs) == 0
    _write_brief(runs, "run1", "cb_a", "card1", "X")
    assert rv.count_revisions("run1", "card1", runs_dir=runs) == 1
