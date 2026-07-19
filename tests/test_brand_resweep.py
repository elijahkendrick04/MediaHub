"""Roadmap 1.12 build 5 — kit-edit -> re-render sweep over persisted briefs.

The deterministic preview/diff is the headline (no rendering needed); apply is
orchestration over an injected renderer, capped and approval-gated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediahub.brand.kits import BrandKitRef
from mediahub.brand.resweep import (
    apply_kit_change,
    iter_profile_briefs,
    preview_kit_change,
)
from mediahub.creative_brief.generator import CreativeBrief
from mediahub.web.club_profile import ClubProfile

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _profile(pid="sweepclub"):
    return ClubProfile(
        profile_id=pid,
        display_name="Sweep Club",
        brand_primary="#0E2A47",
        brand_secondary="#C9A227",
    )


def _write_brief(runs_dir: Path, run_id: str, card_id: str, brief_id: str, palette: dict, pid):
    (runs_dir / run_id / "briefs").mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "profile_id": pid}), encoding="utf-8"
    )
    brief = CreativeBrief(
        id=brief_id,
        content_item_id=card_id,
        profile_id=pid,
        achievement_summary="",
        objective="",
        primary_hook="PB",
        confidence_label="NEW PB",
        tone="data-led",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="",
        text_layers={"headline_line1": "PB"},
        palette=palette,
        format_priority=["story"],
    )
    (runs_dir / run_id / "briefs" / f"{brief_id}.json").write_text(
        json.dumps(brief.to_dict()), encoding="utf-8"
    )


# ---- enumeration -------------------------------------------------------


def test_iter_profile_briefs_scopes_and_skips_sidecars(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    pid = "sweepclub"
    _write_brief(runs, "run1", "s1", "cb_1", {"primary": "#0E5BFF"}, pid)
    _write_brief(runs, "run2", "s2", "cb_2", {"primary": "#0E5BFF"}, pid)
    # a run owned by another profile must not be enumerated
    _write_brief(runs, "run3", "s3", "cb_3", {"primary": "#0E5BFF"}, "otherclub")
    # a workflow sidecar must be ignored as a "run"
    (runs / "run1__workflow.json").write_text("{}", encoding="utf-8")
    got = sorted((r, c) for r, c, _ in iter_profile_briefs(pid, runs_dir=runs))
    assert got == [("run1", "s1"), ("run2", "s2")]


def test_iter_profile_briefs_latest_per_card(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    pid = "sweepclub"
    _write_brief(runs, "run1", "s1", "cb_old", {"primary": "#111111"}, pid)
    import os
    import time

    # make cb_new newer
    _write_brief(runs, "run1", "s1", "cb_new", {"primary": "#222222"}, pid)
    newp = runs / "run1" / "briefs" / "cb_new.json"
    os.utime(newp, (time.time() + 10, time.time() + 10))
    briefs = [b for _, _, b in iter_profile_briefs(pid, runs_dir=runs)]
    assert len(briefs) == 1
    assert briefs[0]["palette"]["primary"] == "#222222"


# ---- preview (deterministic diff) --------------------------------------


def test_preview_flags_cards_a_new_kit_would_change(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    prof = _profile()
    _write_brief(
        runs, "run1", "s1", "cb_1", {"primary": "#0E5BFF", "secondary": "#101820"}, prof.profile_id
    )
    # a kit with a wholly different palette
    kit = BrandKitRef(
        kit_id="k1",
        name="Loud",
        role="event",
        palette={"primary": "#FF0000", "secondary": "#00AA00"},
    )
    preview = preview_kit_change(prof, kit, runs_dir=runs)
    assert preview.n_affected if hasattr(preview, "n_affected") else preview.to_dict()["n_affected"]
    d = preview.to_dict()
    assert d["n_affected"] == 1
    assert d["affected"][0]["run_id"] == "run1"
    assert "--mh-primary" in d["affected"][0]["changed_roles"]


def test_preview_same_palette_no_change(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    prof = _profile()
    # brief uses exactly the profile's own palette → the synthesised primary kit
    # resolves identically → no change.
    _write_brief(
        runs, "run1", "s1", "cb_1", {"primary": "#0E2A47", "secondary": "#C9A227"}, prof.profile_id
    )
    from mediahub.brand.kits import primary_kit

    preview = preview_kit_change(prof, primary_kit(prof), runs_dir=runs)
    assert preview.to_dict()["n_affected"] == 0


# ---- apply (injected renderer) -----------------------------------------


def _seed_three_affected(runs, pid):
    _write_brief(runs, "run1", "s1", "cb_1", {"primary": "#0E5BFF"}, pid)
    _write_brief(runs, "run1", "s2", "cb_2", {"primary": "#0E5BFF"}, pid)
    _write_brief(runs, "run2", "s3", "cb_3", {"primary": "#0E5BFF"}, pid)


def test_apply_renders_all_affected(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    prof = _profile()
    _seed_three_affected(runs, prof.profile_id)
    kit = BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    calls = []
    res = apply_kit_change(
        prof, kit, runs_dir=runs, render_card=lambda r, c, b: calls.append((r, c)) or True
    )
    d = res.to_dict()
    assert d["n_rendered"] == 3
    assert d["remaining"] == 0
    assert len(calls) == 3


def test_apply_respects_limit(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    prof = _profile()
    _seed_three_affected(runs, prof.profile_id)
    kit = BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    res = apply_kit_change(prof, kit, runs_dir=runs, render_card=lambda r, c, b: True, limit=2)
    d = res.to_dict()
    assert d["n_rendered"] == 2
    assert d["remaining"] == 1


def test_apply_counts_skips(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    prof = _profile()
    _seed_three_affected(runs, prof.profile_id)
    kit = BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    res = apply_kit_change(prof, kit, runs_dir=runs, render_card=lambda r, c, b: False)
    d = res.to_dict()
    assert d["n_rendered"] == 0
    assert d["n_skipped"] == 3


# ---- web routes --------------------------------------------------------


@pytest.fixture
def app_client(client, web_module, tmp_path):
    import mediahub.web.club_profile as cp

    yield client, cp, web_module, tmp_path


def test_resweep_preview_route(app_client):
    client, cp, _wm, tmp_path = app_client
    prof = cp.ClubProfile(profile_id="sweepclub", display_name="Sweep Club")
    cp.save_profile(prof)
    from mediahub.brand.kits import BrandKitRef, upsert_kit

    prof = cp.load_profile("sweepclub")
    upsert_kit(
        prof, BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    )
    cp.save_profile(prof)
    _write_brief(tmp_path / "runs_v4", "run1", "s1", "cb_1", {"primary": "#0E5BFF"}, "sweepclub")
    with client.session_transaction() as s:
        s["active_profile_id"] = "sweepclub"
    r = client.post("/api/brand/kits/k1/resweep/preview")
    assert r.status_code == 200
    assert r.get_json()["n_affected"] == 1


def test_resweep_apply_route_requeues_for_review(app_client, monkeypatch):
    client, cp, wm, tmp_path = app_client
    prof = cp.ClubProfile(profile_id="sweepclub", display_name="Sweep Club")
    cp.save_profile(prof)
    from mediahub.brand.kits import BrandKitRef, upsert_kit

    prof = cp.load_profile("sweepclub")
    upsert_kit(
        prof, BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    )
    cp.save_profile(prof)
    _write_brief(tmp_path / "runs_v4", "run1", "s1", "cb_1", {"primary": "#0E5BFF"}, "sweepclub")

    # stub the heavy render + persist so the route is testable without Chromium
    monkeypatch.setattr(
        "mediahub.graphic_renderer.render.render_brief",
        lambda *a, **k: SimpleNamespace(visual=SimpleNamespace(id="v1")),
    )
    monkeypatch.setattr(
        "mediahub.content_pack_visual.integration.persist_visual", lambda *a, **k: None
    )

    with client.session_transaction() as s:
        s["active_profile_id"] = "sweepclub"
    r = client.post("/api/brand/kits/k1/resweep/apply")
    assert r.status_code == 200
    assert r.get_json()["n_rendered"] == 1
    # the card was re-queued for human re-review (EDITED), never auto-published
    from mediahub.workflow.status import CardStatus

    ws = wm._get_wf_store()
    state = ws.load("run1").get("s1")
    assert state is not None and state.status == CardStatus.EDITED


def test_resweep_apply_route_chunks_drain_the_backlog(app_client, monkeypatch):
    """A re-render never rewrites the stored brief, so the affected list is
    identical on every call — the offset cursor must make successive chunked
    calls cover DIFFERENT cards with remaining decreasing to zero."""
    client, cp, wm, tmp_path = app_client
    prof = cp.ClubProfile(profile_id="sweepclub", display_name="Sweep Club")
    cp.save_profile(prof)
    from mediahub.brand.kits import BrandKitRef, upsert_kit

    prof = cp.load_profile("sweepclub")
    upsert_kit(
        prof, BrandKitRef(kit_id="k1", name="Loud", role="event", palette={"primary": "#FF0000"})
    )
    cp.save_profile(prof)
    for i in range(3):
        _write_brief(
            tmp_path / "runs_v4", "run1", f"s{i}", f"cb_{i}", {"primary": "#0E5BFF"}, "sweepclub"
        )

    rendered_tags: list[str] = []

    def fake_render(brief, *a, **k):
        return SimpleNamespace(visual=SimpleNamespace(id="v1", brief_id=brief.id))

    monkeypatch.setattr("mediahub.graphic_renderer.render.render_brief", fake_render)
    monkeypatch.setattr(
        "mediahub.content_pack_visual.integration.persist_visual", lambda *a, **k: None
    )

    with client.session_transaction() as s:
        s["active_profile_id"] = "sweepclub"

    remainings = []
    offset = 0
    for _ in range(3):
        r = client.post(f"/api/brand/kits/k1/resweep/apply?limit=1&offset={offset}")
        assert r.status_code == 200
        d = r.get_json()
        assert d["n_rendered"] == 1
        assert d["n_skipped"] == 0  # cursor skips are not reported as skips
        rendered_tags.extend(d["rendered"])
        remainings.append(d["remaining"])
        offset = d["next_offset"]
    assert remainings == [2, 1, 0]
    # Three different cards were rendered — the cursor made real progress.
    assert len(set(rendered_tags)) == 3
