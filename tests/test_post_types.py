"""P1.2 / ADR-0013 — the slug-canonical post-type layer.

Pins the data-model decision:
  * every ContentType value IS a canonical taxonomy slug (subset invariant);
  * the legacy enum strings persisted before the rename keep working at every
    persistence boundary (policy store, stub-pack store, publish gate) and
    operator-set autonomy levels survive the rename;
  * sport profiles bridge to implemented surfaces via post_types.
"""

from __future__ import annotations

import json

import pytest

from mediahub.club_platform import post_types as pt
from mediahub.club_platform.content_types import REGISTRY, ContentType
from mediahub.sport_profiles import list_sport_profiles, load_sport_profile


# ---------------------------------------------------------------------------
# The subset invariant + vocabulary
# ---------------------------------------------------------------------------


def _known_slugs() -> set[str]:
    known = set(pt.universal_slugs())
    for prof in list_sport_profiles():
        known.update(pt.canonical_slug(s) for s in prof.post_types)
    return known


def test_every_content_type_value_is_a_canonical_slug():
    """The enum is a BADGE over the taxonomy — never a parallel vocabulary."""
    known = _known_slugs()
    for ct in ContentType:
        assert ct.value == pt.canonical_slug(ct.value), ct
        assert ct.value in known, f"{ct.value} is not a taxonomy slug"


def test_no_legacy_alias_is_an_enum_value():
    values = {ct.value for ct in ContentType}
    for legacy in pt.LEGACY_ALIASES:
        assert legacy not in values


def test_universal_slugs_match_taxonomy_doc():
    assert pt.universal_slugs() == (
        "fixture_announcement",
        "result_recap",
        "athlete_spotlight",
        "event_preview",
        "milestone_celebration",
        "birthday",
        "signings_recruitment",
        "sponsor_activation",
        "ticket_merch_promo",
        "behind_the_scenes",
        "season_recap",
        "this_day_in_history",
        "session_update",
        "free_text",
    )


def test_canonical_slug_normalises_and_maps_aliases():
    assert pt.canonical_slug("weekend_preview") == "event_preview"
    assert pt.canonical_slug("sponsor_post") == "sponsor_activation"
    assert pt.canonical_slug(" Event Preview ") == "event_preview"
    assert pt.canonical_slug("Sponsor-Post") == "sponsor_activation"
    assert pt.canonical_slug("pb_spotlight") == "pb_spotlight"
    assert pt.canonical_slug(None) == ""
    # Unknown values pass through normalised — never invented, never dropped.
    assert pt.canonical_slug("mystery_type") == "mystery_type"


def test_implemented_bridge():
    assert pt.implemented_content_type("event_preview") is ContentType.EVENT_PREVIEW
    assert pt.implemented_content_type("weekend_preview") is ContentType.EVENT_PREVIEW
    assert pt.implemented_content_type("sponsor_post") is ContentType.SPONSOR_ACTIVATION
    assert pt.implemented_content_type("pb_spotlight") is None
    assert pt.is_implemented("free_text")
    assert not pt.is_implemented("this_day_in_history")
    assert set(pt.implemented_slugs()) == {ct.value for ct in ContentType}


def test_title_for_prefers_registry_then_taxonomy():
    assert pt.title_for("event_preview") == REGISTRY[ContentType.EVENT_PREVIEW].title
    assert pt.title_for("weekend_preview") == REGISTRY[ContentType.EVENT_PREVIEW].title
    assert pt.title_for("this_day_in_history") == "This Day in History"
    assert pt.title_for("pb_spotlight") == "Pb Spotlight"


# ---------------------------------------------------------------------------
# Sport-profile bridging (the planner's view)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sport", ["swimming", "football"])
def test_post_types_for_bridges_profile_to_surfaces(sport):
    prof = load_sport_profile(sport)
    rows = pt.post_types_for(prof)
    assert rows, sport
    by_slug = {r.slug for r in rows}
    # Every implemented universal surface is enabled in the shipped profiles.
    for slug in ("event_preview", "session_update", "free_text", "sponsor_activation"):
        assert slug in by_slug, f"{sport} profile missing {slug}"
    for r in rows:
        assert r.slug == pt.canonical_slug(r.slug)
        assert r.title
        assert r.sport == sport
        assert r.config.enabled
        if r.content_type is not None:
            assert r.content_type.value == r.slug


def test_post_types_for_swimming_specifics():
    rows = {r.slug: r for r in pt.post_types_for(load_sport_profile("swimming"))}
    assert rows["meet_recap"].content_type is ContentType.MEET_RECAP
    assert not rows["meet_recap"].universal
    assert rows["pb_spotlight"].content_type is None  # planning vocabulary only
    assert rows["athlete_spotlight"].universal
    assert rows["sponsor_activation"].config.default_autonomy.value == "draft_only"


def test_post_types_for_respects_enabled_flag():
    prof = load_sport_profile("swimming")
    prof.post_types["meet_recap"].enabled = False
    enabled = {r.slug for r in pt.post_types_for(prof)}
    assert "meet_recap" not in enabled
    everything = {r.slug for r in pt.post_types_for(prof, enabled_only=False)}
    assert "meet_recap" in everything


# ---------------------------------------------------------------------------
# Persistence boundaries — legacy data must keep working (ADR-0013 §4)
# ---------------------------------------------------------------------------


def test_stub_pack_store_normalises_legacy_packs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.club_platform import stub_pack_store as sps

    # New saves canonicalise whatever the caller passes.
    rec = sps.save_pack("weekend_preview", {"meet_name": "County Champs"}, [])
    assert rec["stub_type"] == "event_preview"
    assert rec["title"] == "Preview — County Champs"

    # Packs persisted before the rename normalise on load and in listings.
    legacy = {
        "pack_id": "legacy00x1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "stub_type": "sponsor_post",
        "title": "Sponsor post — Acme",
        "form_data": {},
        "cards": [{"platform": "Instagram", "caption": "Thanks Acme"}],
    }
    (tmp_path / "stub_packs" / "legacy00x1.json").write_text(json.dumps(legacy), encoding="utf-8")
    loaded = sps.load_pack("legacy00x1")
    assert loaded["stub_type"] == "sponsor_activation"
    listed = {r["pack_id"]: r for r in sps.list_packs()}
    assert listed["legacy00x1"]["stub_type"] == "sponsor_activation"


def test_stub_lookup_accepts_both_vocabularies():
    from mediahub.club_platform.stubs import (
        SponsorPostStub,
        WeekendPreviewStub,
        requirements_for,
        stub_for_type,
    )

    assert isinstance(stub_for_type("event_preview"), WeekendPreviewStub)
    assert isinstance(stub_for_type("weekend_preview"), WeekendPreviewStub)
    assert isinstance(stub_for_type("sponsor_post"), SponsorPostStub)
    assert stub_for_type("pb_spotlight") is None
    assert requirements_for("weekend_preview") == requirements_for("event_preview") != ""
    assert requirements_for("sponsor_post") == requirements_for("sponsor_activation") != ""
