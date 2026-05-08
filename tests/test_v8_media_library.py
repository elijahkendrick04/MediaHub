"""V8 media_library tests.

Verifies CRUD round-trip + describe heuristics + selector ranking.
"""
import sys
import tempfile
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.media_library.models import MediaAsset
from mediahub.media_library.store import MediaLibraryStore
from mediahub.media_library.describe import parse_description
from mediahub.media_library import selector as sel


def _tmp_store():
    tmp = Path(tempfile.mkdtemp())
    return MediaLibraryStore(db_path=tmp / "media.db", uploads_dir=tmp / "uploads")


def test_save_get_list_round_trip():
    store = _tmp_store()
    a = MediaAsset(
        id="",
        filename="eira.jpg",
        path="/tmp/eira.jpg",
        type="athlete_photo",
        description_raw="Eira Hughes at Wales National Pool",
        profile_id="swansea",
        linked_athlete_names=["Eira Hughes"],
        linked_venue="Wales National Pool",
    )
    saved = store.save(a)
    assert saved.id, "id auto-assigned"
    fetched = store.get(saved.id)
    assert fetched is not None
    assert fetched.filename == "eira.jpg"
    assert "Eira Hughes" in fetched.linked_athlete_names

    rows = store.list(profile_id="swansea")
    assert any(r.id == saved.id for r in rows)


def test_describe_heuristic_extracts_athlete_and_venue():
    out = parse_description("Eira Hughes swimming 200m Freestyle at Wales National Pool")
    # Heuristic fallback should populate the standard schema.
    assert isinstance(out, dict)
    for key in ("athletes", "venue", "event", "tags"):
        assert key in out
    # Specific extractions:
    assert any("Eira" in n for n in out.get("athletes") or [])
    assert "Wales" in (out.get("venue") or "")


def test_score_asset_returns_float():
    asset = MediaAsset(
        id="ma_1",
        filename="x.jpg",
        path="/tmp/x.jpg",
        type="athlete_photo",
        profile_id="swansea",
        linked_athlete_names=["Eira Hughes"],
        permission_status="cleared",
        approval_status="approved",
        orientation="portrait",
        width=2000, height=3000,
    )
    score = sel.score_asset(asset, role="hero_athlete",
                            athlete_name="Eira Hughes",
                            preferred_orientation="portrait")
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_select_picks_athlete_match():
    store = _tmp_store()
    a1 = MediaAsset(id="", filename="other.jpg", path="/tmp/o.jpg", type="athlete_photo",
                    profile_id="p", linked_athlete_names=["Sam Powell"],
                    permission_status="cleared", approval_status="approved")
    a2 = MediaAsset(id="", filename="eira.jpg", path="/tmp/e.jpg", type="athlete_photo",
                    profile_id="p", linked_athlete_names=["Eira Hughes"],
                    permission_status="cleared", approval_status="approved")
    a1 = store.save(a1)
    a2 = store.save(a2)
    candidates = store.list(profile_id="p")
    ranked = sel.select_assets(candidates, role="hero_athlete",
                               athlete_name="Eira Hughes")
    assert ranked
    assert ranked[0]["asset_id"] == a2.id
