"""Phase A photo-foundation seams in `content_pack_visual.integration`.

Covers the STILLS-9 identity note (unverified face on a named card), the
PHOTOS-5 used_in persistence after a render, and the PHOTOS-4 burst-family
index used to thread recently-used photo dHashes through a pack build.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mediahub.content_pack_visual.integration import (
    _dhash_by_asset_id,
    _photo_identity_note,
    _record_asset_usage,
)
from mediahub.media_library.models import MediaAsset
from mediahub.media_library.store import MediaLibraryStore
from mediahub.media_requirements.evaluator import EvaluationResult


def _eval_with_hero(asset_dict) -> EvaluationResult:
    return EvaluationResult(
        content_item_id="ci_1",
        content_type="confirmed_official_pb",
        status="ready",
        suggested_layout="individual_hero",
        matched={
            "hero_athlete": [
                {"asset_id": asset_dict["id"], "score": 0.7, "asset": asset_dict}
            ]
        },
        missing_required=[],
        missing_optional=[],
        recommended_action="Ready to render.",
    )


def _item(swimmer="Eira Hughes", **extra):
    d = {"id": "ci_1", "swimmer_name": swimmer, "achievement": {"swimmer_name": swimmer}}
    d.update(extra)
    return d


def _asset_dict(aid="ma_1", **overrides) -> dict:
    base = MediaAsset(id=aid, filename="p.jpg", path="/tmp/p.jpg", type="athlete_action")
    d = base.to_dict()
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# STILLS-9 — photo identity note
# ---------------------------------------------------------------------------


class TestPhotoIdentityNote:
    def test_unlinked_hero_on_named_card_gets_note(self) -> None:
        hero = _asset_dict(linked_athlete_ids=[], linked_athlete_names=[])
        note = _photo_identity_note(_item(), _eval_with_hero(hero), [hero])
        assert note == "photo identity unverified — check it's really Eira Hughes"

    def test_verified_name_link_no_note(self) -> None:
        hero = _asset_dict(linked_athlete_names=["Eira Hughes"])
        assert _photo_identity_note(_item(), _eval_with_hero(hero), [hero]) is None

    def test_verified_id_link_no_note(self) -> None:
        hero = _asset_dict(linked_athlete_ids=["ath-9"], linked_athlete_names=[])
        item = _item(swimmer_id="ath-9")
        assert _photo_identity_note(item, _eval_with_hero(hero), [hero]) is None

    def test_wrong_athlete_link_gets_note(self) -> None:
        hero = _asset_dict(linked_athlete_names=["Sam Powell"])
        note = _photo_identity_note(_item(), _eval_with_hero(hero), [hero])
        assert note is not None and "Eira Hughes" in note

    def test_description_mention_is_not_verification(self) -> None:
        hero = _asset_dict(
            linked_athlete_names=[], description_raw="Eira Hughes at the gala"
        )
        assert _photo_identity_note(_item(), _eval_with_hero(hero), [hero]) is not None

    def test_forced_hero_resolved_from_media_assets(self) -> None:
        matched = _asset_dict("ma_matched", linked_athlete_names=["Eira Hughes"])
        forced = _asset_dict("ma_forced", linked_athlete_names=[])
        note = _photo_identity_note(
            _item(), _eval_with_hero(matched), [matched, forced], forced_hero_asset_id="ma_forced"
        )
        # The user-forced (unlinked) photo is the one rendering — note applies.
        assert note is not None

    def test_unnamed_card_no_note(self) -> None:
        hero = _asset_dict(linked_athlete_names=[])
        assert _photo_identity_note(_item(swimmer=""), _eval_with_hero(hero), [hero]) is None

    def test_no_hero_photo_no_note(self) -> None:
        ev = EvaluationResult(
            content_item_id="ci_1",
            content_type="x",
            status="needs_media",
            suggested_layout="individual_hero",
            matched={},
            missing_required=["hero_athlete"],
            missing_optional=[],
            recommended_action="",
        )
        assert _photo_identity_note(_item(), ev, []) is None

    def test_case_insensitive_name_verification(self) -> None:
        hero = _asset_dict(linked_athlete_names=["eira hughes"])
        assert _photo_identity_note(_item(), _eval_with_hero(hero), [hero]) is None


# ---------------------------------------------------------------------------
# PHOTOS-5 — used_in persistence
# ---------------------------------------------------------------------------


def _tmp_store() -> MediaLibraryStore:
    tmp = Path(tempfile.mkdtemp())
    return MediaLibraryStore(db_path=tmp / "media.db", uploads_dir=tmp / "uploads")


class TestRecordAssetUsage:
    def _seed(self, store, aid="ma_1", profile_id="alpha", used_in=None):
        return store.save(
            MediaAsset(
                id=aid,
                filename="p.jpg",
                path="/tmp/p.jpg",
                type="athlete_action",
                profile_id=profile_id,
                used_in=used_in or [],
            )
        )

    def test_appends_visual_ids(self) -> None:
        store = _tmp_store()
        self._seed(store)
        visuals = [
            {"id": "vis_a", "sourced_asset_ids": ["ma_1"]},
            {"id": "vis_b", "sourced_asset_ids": ["ma_1"]},
        ]
        assert _record_asset_usage(visuals, profile_id="alpha", store=store) == 1
        assert store.get("ma_1").used_in == ["vis_a", "vis_b"]

    def test_idempotent_on_rerender(self) -> None:
        store = _tmp_store()
        self._seed(store, used_in=["vis_a"])
        visuals = [{"id": "vis_a", "sourced_asset_ids": ["ma_1"]}]
        assert _record_asset_usage(visuals, profile_id="alpha", store=store) == 0
        assert store.get("ma_1").used_in == ["vis_a"]

    def test_other_profiles_assets_untouched(self) -> None:
        store = _tmp_store()
        self._seed(store, profile_id="beta")
        visuals = [{"id": "vis_a", "sourced_asset_ids": ["ma_1"]}]
        assert _record_asset_usage(visuals, profile_id="alpha", store=store) == 0
        assert store.get("ma_1").used_in == []

    def test_brand_logo_placeholder_ignored(self) -> None:
        store = _tmp_store()
        self._seed(store)
        visuals = [{"id": "vis_a", "sourced_asset_ids": ["_brand_logo_", "ma_1"]}]
        _record_asset_usage(visuals, profile_id="alpha", store=store)
        assert store.get("ma_1").used_in == ["vis_a"]

    def test_unknown_assets_and_empty_visuals_are_safe(self) -> None:
        store = _tmp_store()
        assert _record_asset_usage([], profile_id="alpha", store=store) == 0
        assert (
            _record_asset_usage(
                [{"id": "vis_a", "sourced_asset_ids": ["ma_ghost"]}],
                profile_id="alpha",
                store=store,
            )
            == 0
        )


# ---------------------------------------------------------------------------
# PHOTOS-4 — burst-family index for pack threading
# ---------------------------------------------------------------------------


class TestDhashIndex:
    def test_maps_measured_assets_only(self) -> None:
        measured = _asset_dict(
            "ma_m", media_meta={"quality": {"sharpness": 100.0, "dhash": "ab" * 8}}
        )
        legacy = _asset_dict("ma_l")
        broken = _asset_dict("ma_b", media_meta={"quality": None})
        idx = _dhash_by_asset_id([measured, legacy, broken])
        assert idx == {"ma_m": "ab" * 8}

    def test_accepts_media_asset_objects(self) -> None:
        obj = MediaAsset(
            id="ma_o",
            filename="p.jpg",
            path="/p",
            media_meta={"quality": {"sharpness": 1.0, "dhash": "cd" * 8}},
        )
        assert _dhash_by_asset_id([obj]) == {"ma_o": "cd" * 8}

    def test_empty_input(self) -> None:
        assert _dhash_by_asset_id(None) == {}
        assert _dhash_by_asset_id([]) == {}
