"""PHOTOS-6 — meet-scoped photo candidates on the media-requirements evaluator.

When hero matching fails but the library holds photos linked to this run (or
uploaded within the meet window), evaluate() surfaces them as ``candidates``
with a "Pick from N photos uploaded for this meet" action — for a human to
pick from, never auto-placed on a named card. Deterministic throughout.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mediahub.media_library.models import MediaAsset
from mediahub.media_requirements.evaluator import NEEDS_MEDIA, evaluate


def _item(angle="confirmed_official_pb", *, conf=0.9, swimmer="Eira Hughes", **extra):
    d = {
        "id": "ci_1",
        "post_angle": angle,
        "confidence": conf,
        "swimmer_name": swimmer,
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "post_angle": angle,
            "confidence": conf,
        },
        "safe_to_post": {"level": "safe"},
    }
    d.update(extra)
    return d


def _meet_photo(i=0, *, run_ids=("r1",), uploaded_at=None, **overrides):
    """A realistic quick/bulk phone upload: untyped ("other"), unlinked,
    unmeasured, permission unknown — scores ~0.34, just under the hero
    matcher's 0.35 floor. Exactly the photos the candidates surface exists
    for."""
    defaults = dict(
        id=f"ma_meet_{i}",
        filename=f"m{i}.jpg",
        path=f"/tmp/m{i}.jpg",
        type="other",
        profile_id="p",
        linked_meet_ids=list(run_ids),
        permission_status="unknown",
        approval_status="draft",
        width=0,
        height=0,
        orientation="unknown",
    )
    if uploaded_at:
        defaults["uploaded_at"] = uploaded_at
    defaults.update(overrides)
    return MediaAsset(**defaults)


class TestMeetScopedCandidates:
    def test_candidates_surface_when_hero_missing(self) -> None:
        photos = [_meet_photo(i) for i in range(3)]
        res = evaluate(_item(), library_assets=photos, run_id="r1")
        assert res.status == NEEDS_MEDIA
        assert "hero_athlete" in res.missing_required
        assert len(res.candidates) == 3
        assert res.recommended_action == "Pick from 3 photos uploaded for this meet."
        # Candidates are surfaced, never auto-matched onto the card.
        assert "hero_athlete" not in res.matched
        # Same scored shape as matched entries so the picker can reuse it.
        entry = res.candidates[0]
        assert {"asset_id", "score", "reason_summary", "asset"} <= set(entry.keys())

    def test_no_run_context_keeps_the_upload_nag(self) -> None:
        photos = [_meet_photo(i) for i in range(3)]
        res = evaluate(_item(), library_assets=photos)  # no run_id
        assert res.candidates == []
        assert res.recommended_action == (
            "Upload a real photo of Eira Hughes to render this post."
        )

    def test_other_meets_photos_not_offered(self) -> None:
        photos = [_meet_photo(i, run_ids=("some_other_run",)) for i in range(2)]
        res = evaluate(_item(), library_assets=photos, run_id="r1")
        assert res.candidates == []
        assert "Upload a real photo" in res.recommended_action

    def test_top_k_capped_but_action_counts_all(self) -> None:
        photos = [_meet_photo(i) for i in range(8)]
        res = evaluate(_item(), library_assets=photos, run_id="r1")
        assert len(res.candidates) == 5
        assert res.recommended_action == "Pick from 8 photos uploaded for this meet."

    def test_meet_window_scopes_by_upload_time(self) -> None:
        now = datetime.now(timezone.utc)
        inside = _meet_photo(0, run_ids=(), uploaded_at=now.isoformat())
        outside = _meet_photo(
            1, run_ids=(), uploaded_at=(now - timedelta(days=30)).isoformat()
        )
        window = ((now - timedelta(days=1)).isoformat(), (now + timedelta(days=1)).isoformat())
        res = evaluate(
            _item(), library_assets=[inside, outside], run_id="r_unmatched", meet_window=window
        )
        assert [c["asset_id"] for c in res.candidates] == ["ma_meet_0"]

    def test_unusable_photos_excluded(self) -> None:
        blocked = _meet_photo(0, permission_status="do_not_use")
        rejected = _meet_photo(1, approval_status="rejected")
        res = evaluate(_item(), library_assets=[blocked, rejected], run_id="r1")
        assert res.candidates == []

    def test_non_person_types_excluded(self) -> None:
        venue = _meet_photo(0, type="venue_photo")
        logo = _meet_photo(1, type="logo")
        res = evaluate(_item(), library_assets=[venue, logo], run_id="r1")
        assert res.candidates == []

    def test_consent_block_suppresses_candidates(self) -> None:
        # W.2: photo consent withheld → no photo may be offered for this card.
        photos = [_meet_photo(i) for i in range(2)]
        item = _item(consent={"level": "full", "photo_ok": False})
        res = evaluate(item, library_assets=photos, run_id="r1")
        assert res.candidates == []
        assert "Pick from" not in res.recommended_action

    def test_candidates_ranked_deterministically(self) -> None:
        photos = [_meet_photo(i) for i in range(4)]
        a = evaluate(_item(), library_assets=photos, run_id="r1")
        b = evaluate(_item(), library_assets=photos, run_id="r1")
        assert [c["asset_id"] for c in a.candidates] == [c["asset_id"] for c in b.candidates]

    def test_well_tagged_photo_matches_instead_of_candidates(self) -> None:
        # A properly typed, measured, subject-linked photo clears the hero
        # matcher — no candidates path, the card is READY.
        named = _meet_photo(
            1,
            type="athlete_action",
            linked_athlete_names=["Eira Hughes"],
            permission_status="user_owned",
            approval_status="approved",
            width=1600,
            height=2000,
            orientation="portrait",
        )
        res = evaluate(_item(), library_assets=[named], run_id="r1")
        assert res.status != NEEDS_MEDIA
        assert res.matched.get("hero_athlete")
        assert res.candidates == []

    def test_candidates_serialised_in_to_dict(self) -> None:
        photos = [_meet_photo(0)]
        res = evaluate(_item(), library_assets=photos, run_id="r1")
        d = res.to_dict()
        assert "candidates" in d
        assert d["candidates"] == res.candidates

    def test_wrong_athlete_photos_rank_last_among_candidates(self) -> None:
        generic = _meet_photo(0)
        wrong = _meet_photo(1, linked_athlete_names=["Sam Powell"])
        res = evaluate(_item(), library_assets=[generic, wrong], run_id="r1")
        assert res.status == NEEDS_MEDIA
        ids = [c["asset_id"] for c in res.candidates]
        assert ids == ["ma_meet_0", "ma_meet_1"]
