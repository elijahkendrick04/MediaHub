"""tests/test_card_download_uses_edited_caption.py — the per-card ZIP exports
the caption the volunteer wrote, not the internal headline (audit finding E-3).

api_card_download read `caption` from a ?caption= query param no caller ever
passes, so it fell straight through to the achievement headline. The ZIP's
README claims the .txt is "the ready-to-post caption", so a volunteer posted
the raw internal headline and their edit was silently lost — and the run-level
export.zip (which uses the real caption) contradicted it.

The fix resolves the caption from the same approved/active source as the
run-level export, with the persisted human edit as an approval-independent
fallback, and the headline only as a last resort.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def env(app, web_module, tmp_path):
    return app, web_module, tmp_path


def _seed_run(runs_dir: Path, run_id: str, headline: str) -> None:
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(
            {
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "id": "c1",
                            "achievement": {
                                "swim_id": "c1",
                                "swimmer_name": "Maya Smith",
                                "event": "200m Free",
                                "headline": headline,
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def _caption_from_zip(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        name = next(n for n in zf.namelist() if n.endswith("caption.txt"))
        return zf.read(name).decode("utf-8")


def test_edited_caption_wins_over_headline(env):
    app, wm, tmp_path = env
    runs_dir = tmp_path / "runs_v4"
    _seed_run(runs_dir, "runE", headline="INTERNAL HEADLINE — do not post")

    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(runs_dir)
    ws.set_edits("runE", "c1", {"warm-club_headline": "Maya smashed her PB — 200m Free 🏊"})

    with app.test_client() as c:
        r = c.get("/api/runs/runE/card/c1/download")
    assert r.status_code == 200, r.status_code
    caption = _caption_from_zip(r.data)
    assert "Maya smashed her PB" in caption, caption
    assert "INTERNAL HEADLINE" not in caption


def test_falls_back_to_headline_when_no_caption(env):
    """With no edit and no approved pack caption, the headline is still used
    (behaviour preserved for cards the user never touched)."""
    app, wm, tmp_path = env
    runs_dir = tmp_path / "runs_v4"
    _seed_run(runs_dir, "runF", headline="Maya Smith — new PB")

    with app.test_client() as c:
        r = c.get("/api/runs/runF/card/c1/download")
    assert r.status_code == 200
    assert "Maya Smith — new PB" in _caption_from_zip(r.data)


def test_explicit_caption_override_still_wins(env):
    app, wm, tmp_path = env
    runs_dir = tmp_path / "runs_v4"
    _seed_run(runs_dir, "runG", headline="headline")
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(runs_dir).set_edits("runG", "c1", {"warm-club_headline": "edited"})

    with app.test_client() as c:
        r = c.get("/api/runs/runG/card/c1/download?caption=explicit+override")
    assert "explicit override" in _caption_from_zip(r.data)
