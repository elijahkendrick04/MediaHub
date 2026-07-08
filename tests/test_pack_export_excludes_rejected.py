"""tests/test_pack_export_excludes_rejected.py — whole-pack exports never ship
a card a human rejected (audit finding E-2).

content_pack_zip (/pack/<id>/zip, "Download all visuals") and
_bulk_items_for_run (the Bulk export ZIP) walked every visuals subdir with no
workflow-status filter, so a card approved-then-rejected (misspelled name,
parent complaint) still shipped — only the "every format + manifest" ZIP
filtered it. Three buttons, three different rules. This pins one rule: rejected
cards are excluded everywhere.
"""
from __future__ import annotations

import importlib
import io
import json
import struct
import sys
import zlib
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _make_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = (b"\x00" + bytes([0xFF, 0, 0]) * width) * height
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _write_card(visuals_dir: Path, brief_id: str, content_item_id: str) -> None:
    bdir = visuals_dir / brief_id
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "visual.json").write_text(
        json.dumps({"id": f"v_{brief_id}", "content_item_id": content_item_id, "format": "feed_portrait"}),
        encoding="utf-8",
    )
    (bdir / "feed_portrait.png").write_bytes(_make_png(108, 135))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    import mediahub.web.web as wm

    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    run_id = "runR"
    runs = tmp_path / "runs_v4"
    (runs / f"{run_id}.json").write_text(json.dumps({"recognition_report": {"ranked_achievements": []}}))
    vdir = runs / run_id / "visuals"
    _write_card(vdir, "briefA", "cardA")
    _write_card(vdir, "briefB", "cardB")

    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.status import CardStatus

    ws = WorkflowStore(runs)
    ws.set_status(run_id, "cardA", CardStatus.APPROVED)
    ws.set_status(run_id, "cardB", CardStatus.REJECTED)
    return app, wm, run_id


def test_content_pack_zip_excludes_rejected_card(env):
    """Exercises the shared _rejected_card_ids allowlist that both
    content_pack_zip and _bulk_items_for_run now apply identically."""
    app, wm, run_id = env
    with app.test_client() as c:
        r = c.get(f"/pack/{run_id}/zip")
    assert r.status_code == 200, r.status_code
    names = zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    joined = "\n".join(names)
    assert "v_briefA" in joined, "approved card must be in the pack"
    assert "v_briefB" not in joined, "rejected card must NOT ship (E-2)"


def test_rejected_only_run_ships_no_visuals(env, tmp_path, monkeypatch):
    """A run whose only rendered card was rejected exports an empty visuals
    set — never the rejected card."""
    app, wm, run_id = env
    # Reject the approved card too, then re-export.
    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.status import CardStatus

    ws = WorkflowStore(Path(tmp_path / "runs_v4"))
    ws.set_status(run_id, "cardA", CardStatus.REJECTED)
    with app.test_client() as c:
        r = c.get(f"/pack/{run_id}/zip")
    names = "\n".join(zipfile.ZipFile(io.BytesIO(r.data)).namelist())
    assert "v_briefA" not in names and "v_briefB" not in names
