"""Regression tests for deep-review batch 9 (compliance / privacy data-safety).

#103 delete_org / org_export_zip cover the analytics + assistant-memory stores
     (they used to survive deletion and be absent from the takeout).
#105 erasure / org_lifecycle _data_dir fall back to the package root (the tree
     the app actually writes to), not a cwd-relative "data".
#110 retention.run_purge tolerates a naive security-log timestamp instead of
     aborting the whole purge on the aware/naive comparison.
#112 toggle_reaction round-trips and returns the correct on/off flag.
#114 mcp_server.tools._seg percent-encodes a path id and rejects a missing one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


# ── #114 MCP path-segment encoding ──────────────────────────────────────────


def test_mcp_seg_encodes_and_requires():
    from mediahub.mcp_server.tools import McpParamError, _seg

    assert _seg({"run_id": "abc"}, "run_id") == "abc"
    # A '/' or '..' can no longer break out of the intended path segment.
    assert _seg({"run_id": "a/b/../c"}, "run_id") == "a%2Fb%2F..%2Fc"
    assert _seg({"run_id": "x?y=1"}, "run_id") == "x%3Fy%3D1"
    with pytest.raises(McpParamError):
        _seg({}, "run_id")
    with pytest.raises(McpParamError):
        _seg({"run_id": "   "}, "run_id")


# ── #105 DATA_DIR fallback = package root ───────────────────────────────────


def test_erasure_and_org_data_dir_fall_back_to_package_root(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    from mediahub.privacy import erasure, org_lifecycle

    # The app's own default (web.py _SRC_ROOT) is .../src/mediahub — both cascades
    # must scan the SAME tree, not a cwd-relative "data" the app never touches.
    assert erasure._data_dir().name == "mediahub"
    assert org_lifecycle._data_dir().name == "mediahub"


# ── #103 org deletion + takeout cover analytics + assistant memory ──────────


def test_delete_org_and_export_cover_analytics_and_assistant_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.analytics import store as analytics
    from mediahub.assistant import memory
    from mediahub.privacy import org_lifecycle

    pid = "orgZ"
    analytics.record_metric(pid, "achievement", "2026-01-01", {"likes": 4}, data_dir=tmp_path)
    memory.remember(pid, "prefers warm, understated captions")

    an_path = analytics._path(pid, tmp_path)
    mem_path = memory._path(pid)
    assert an_path.exists() and mem_path.exists()

    # Export first — both stores must appear in the takeout ZIP.
    import zipfile

    out_zip = tmp_path / "takeout.zip"
    org_lifecycle.org_export_zip(pid, out_zip)
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
    assert "analytics.json" in names
    assert "assistant_memory.json" in names

    # Then delete — both stores must be gone.
    report = org_lifecycle.delete_org(pid, delete_run=lambda rid: False)
    assert not an_path.exists()
    assert not mem_path.exists()
    assert report.get("analytics_deleted") is True
    assert report.get("assistant_memory_deleted") is True


# ── #110 retention tolerates a naive security-log timestamp ─────────────────


def test_run_purge_tolerates_naive_security_log_timestamp(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.compliance import retention

    log_dir = tmp_path / "security_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    # Naive line FIRST (recent, keep) — the old code raised on `naive < aware`
    # here and aborted the whole purge before ever reaching the aged line.
    (log_dir / "events.jsonl").write_text(
        json.dumps({"ts": "2025-06-01T00:00:00", "event": "keep-naive"})
        + "\n"
        + json.dumps({"ts": "2019-01-01T00:00:00+00:00", "event": "drop-aged"})
        + "\n"
    )

    report = retention.run_purge(now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert report["security_log_lines_dropped"] == 1
    kept = (log_dir / "events.jsonl").read_text()
    assert "keep-naive" in kept
    assert "drop-aged" not in kept


# ── #112 toggle_reaction round-trips ────────────────────────────────────────


def test_toggle_reaction_round_trips(tmp_path):
    from mediahub.collab import threads

    db = tmp_path / "collab.db"
    c = threads.add_comment("run1", "card1", "nice swim", author_email="a@x.org", db_path=db)
    # First toggle turns it on, second turns it off — no IntegrityError either way.
    assert threads.toggle_reaction(c.id, "🎉", "b@x.org", db_path=db) is True
    assert threads.toggle_reaction(c.id, "🎉", "b@x.org", db_path=db) is False
    # A reaction on a non-existent comment is a graceful False, not a crash.
    assert threads.toggle_reaction("nope", "🎉", "b@x.org", db_path=db) is False
