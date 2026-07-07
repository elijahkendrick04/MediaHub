"""build_content_pack — semantic caption-memory capture runs out-of-band.

The Cap-2b capture makes a blocking HTTP embed call per card when an
embedding backend is configured. It must never run on the pack-build
(render/export) path: a slow or down embed endpoint cannot stall the page.
"""

from __future__ import annotations

import json
import threading
import time
from unittest import mock


def _seed_run(runs_dir, run_id="run-1"):
    run = {
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "200m Freestyle",
                        "time": "2:08.41",
                    },
                }
            ]
        }
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run))


def test_slow_capture_does_not_block_pack_build(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _seed_run(runs_dir)

    from mediahub.memory import learning
    from mediahub.workflow.pack import build_content_pack
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(runs_dir)
    ws.set_status("run-1", "swim-1", CardStatus.APPROVED)

    captured = threading.Event()
    calls = []

    def slow_capture(profile_id, ach, cap, *, card_id, run_id=""):
        time.sleep(2.0)  # simulates the embed endpoint hanging
        calls.append((profile_id, cap, card_id, run_id))
        captured.set()
        return True

    def fake_apply_brand(card, kit, tone, kind, templates):
        out = dict(card)
        out["brand_captions"] = {"warm-club": {"headline": "Eira flies to a PB!"}}
        return out

    monkeypatch.setattr(learning, "is_enabled", lambda: True)
    monkeypatch.setattr(learning, "capture", slow_capture)
    with mock.patch(
        "mediahub.brand.store.load_brand", return_value=(object(), "warm-club", {})
    ), mock.patch("mediahub.brand.apply.apply_brand", side_effect=fake_apply_brand):
        t0 = time.monotonic()
        pack = build_content_pack("run-1", "async-club", runs_dir=runs_dir)
        elapsed = time.monotonic() - t0

    # The pack came back without waiting on the 2s capture...
    assert len(pack) == 1
    assert elapsed < 1.0, f"pack build blocked on capture ({elapsed:.2f}s)"
    assert not calls  # not yet captured at return time
    # ...and the capture still happens, out-of-band.
    assert captured.wait(timeout=10.0), "async capture never ran"
    assert calls[0][0] == "async-club"
    assert calls[0][2] == "swim-1"


def test_no_capture_thread_when_memory_unconfigured(tmp_path, monkeypatch):
    """The common (unconfigured) case queues nothing and spawns no thread."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _seed_run(runs_dir)

    from mediahub.memory import learning
    from mediahub.workflow import pack as pack_mod
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(runs_dir)
    ws.set_status("run-1", "swim-1", CardStatus.APPROVED)

    spawned = []
    monkeypatch.setattr(learning, "is_enabled", lambda: False)
    monkeypatch.setattr(
        pack_mod, "_capture_memories_async", lambda jobs: spawned.append(jobs)
    )

    def fake_apply_brand(card, kit, tone, kind, templates):
        out = dict(card)
        out["brand_captions"] = {"warm-club": {"headline": "Eira flies to a PB!"}}
        return out

    with mock.patch(
        "mediahub.brand.store.load_brand", return_value=(object(), "warm-club", {})
    ), mock.patch("mediahub.brand.apply.apply_brand", side_effect=fake_apply_brand):
        pack = pack_mod.build_content_pack("run-1", "plain-club", runs_dir=runs_dir)

    assert len(pack) == 1
    assert spawned == []
