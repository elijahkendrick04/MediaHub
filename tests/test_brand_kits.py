"""Roadmap 1.12 build 1 — multi-kit brand platform data model.

Covers the back-compat guarantee (an un-migrated profile resolves to one
synthesised primary kit that round-trips byte-identically to
``get_brand_kit()``), kit CRUD, resolution, sponsor pairing rules, and JSON
persistence through ``save_profile`` / ``load_profile``.
"""

from __future__ import annotations

import pytest

from mediahub.brand.kits import (
    BrandKitRef,
    SponsorPairingRules,
    brand_kit_from_ref,
    default_kit_id,
    delete_kit,
    get_kit,
    list_kits,
    new_kit_id,
    normalise_kit,
    primary_kit,
    resolve_kit_for,
    set_default_kit,
    upsert_kit,
)
from mediahub.web.club_profile import ClubProfile, load_profile, save_profile


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _profile(**kwargs) -> ClubProfile:
    base = dict(
        profile_id="testclub",
        display_name="Test Club",
        brand_primary="#0E2A47",
        brand_secondary="#C9A227",
    )
    base.update(kwargs)
    return ClubProfile(**base)


# ---- back-compat: the synthesised primary kit --------------------------


def test_empty_profile_yields_one_synthesised_primary():
    p = _profile()
    kits = list_kits(p)
    assert len(kits) == 1
    assert kits[0].role == "primary"
    assert kits[0].kit_id == "primary"
    # palette mirrors the resolved brand kit
    assert kits[0].palette["primary"] == "#0e2a47"


def test_primary_kit_round_trips_to_get_brand_kit_byte_identical():
    p = _profile()
    base = p.get_brand_kit()
    derived = brand_kit_from_ref(p, primary_kit(p))
    # The bridge must resolve byte-identically to get_brand_kit() for an
    # un-migrated profile — no palette/logo drift, no recomputed theme.
    assert derived.to_dict() == base.to_dict()


def test_default_kit_id_is_primary_for_unmigrated_profile():
    p = _profile()
    assert default_kit_id(p) == "primary"
    assert resolve_kit_for(p).role == "primary"


# ---- normalise_kit -----------------------------------------------------


def test_normalise_kit_requires_a_name():
    assert normalise_kit({"kit_id": "k1"}) is None
    assert normalise_kit({"name": "  "}) is None
    assert normalise_kit("not a dict") is None


def test_normalise_kit_assigns_id_and_defaults_bad_role():
    k = normalise_kit({"name": "Gala 2026", "role": "nonsense"})
    assert k is not None
    assert k.kit_id  # auto-assigned
    assert k.role == "primary"  # unknown role falls back


def test_normalise_kit_cleans_palette_and_locks():
    k = normalise_kit(
        {
            "name": "Sponsor kit",
            "role": "sponsor",
            "palette": {"primary": "abc", "secondary": "not-a-hex", "accent": "#FF0000"},
            "locks": ["palette", "bogus", "fonts"],
        }
    )
    assert k.palette == {"primary": "#aabbcc", "accent": "#ff0000"}
    assert k.locks == ["palette", "fonts"]  # bogus dropped


def test_brandkitref_round_trip():
    k = BrandKitRef(
        kit_id="k1",
        name="Section kit",
        role="section",
        palette={"primary": "#123456"},
        locks=["palette"],
    )
    again = BrandKitRef.from_dict(k.to_dict())
    assert again == k


# ---- sponsor pairing rules ---------------------------------------------


def test_sponsor_pairing_rules_coerce_bad_values():
    r = SponsorPairingRules.from_dict(
        {"placement": "across-the-face", "lockup": "weird", "clear_space": "x", "min_logo_px": -5}
    )
    assert r.placement == "footer"
    assert r.lockup == "side_by_side"
    assert r.clear_space == 1.0
    assert r.min_logo_px == 64


def test_sponsor_kit_carries_pairing_rules():
    k = normalise_kit(
        {
            "name": "Acme co-brand",
            "role": "sponsor",
            "pairing_rules": {"placement": "corner", "lockup": "club_lead", "clear_space": 2.0},
        }
    )
    pairing = k.pairing()
    assert pairing.placement == "corner"
    assert pairing.lockup == "club_lead"
    assert pairing.clear_space == 2.0


# ---- upsert / delete / default -----------------------------------------


def test_upsert_first_kit_materialises_primary():
    p = _profile()
    gala = BrandKitRef(kit_id=new_kit_id(), name="Gala 2026", role="event")
    upsert_kit(p, gala)
    kits = list_kits(p)
    roles = sorted(k.role for k in kits)
    assert roles == ["event", "primary"]  # primary materialised alongside the new kit
    prim = primary_kit(p)
    assert prim.created_at  # timestamp stamped


def test_upsert_updates_existing_kit_in_place():
    p = _profile()
    k = BrandKitRef(kit_id="k1", name="Squad", role="section", palette={"primary": "#111111"})
    upsert_kit(p, k)
    created = get_kit(p, "k1").created_at
    k2 = BrandKitRef(kit_id="k1", name="Masters squad", role="section")
    upsert_kit(p, k2)
    fetched = get_kit(p, "k1")
    assert fetched.name == "Masters squad"
    assert fetched.created_at == created  # preserved across update


def test_delete_kit_refuses_primary_and_last():
    p = _profile()
    upsert_kit(p, BrandKitRef(kit_id="k1", name="Event", role="event"))
    # cannot delete the primary
    prim_id = primary_kit(p).kit_id
    assert delete_kit(p, prim_id) is False
    # can delete the event kit
    assert delete_kit(p, "k1") is True
    assert get_kit(p, "k1") is None
    # primary remains and cannot be removed (would leave zero)
    assert delete_kit(p, prim_id) is False


def test_delete_kit_clears_dangling_default():
    p = _profile()
    upsert_kit(p, BrandKitRef(kit_id="k1", name="Event", role="event"))
    assert set_default_kit(p, "k1") is True
    assert default_kit_id(p) == "k1"
    delete_kit(p, "k1")
    assert p.default_kit_id == ""
    assert default_kit_id(p) == primary_kit(p).kit_id  # falls back


def test_set_default_kit_rejects_unknown():
    p = _profile()
    assert set_default_kit(p, "does-not-exist") is False


def test_resolve_kit_for_prefers_explicit_then_default():
    p = _profile()
    upsert_kit(p, BrandKitRef(kit_id="k1", name="Event", role="event"))
    set_default_kit(p, "k1")
    assert resolve_kit_for(p, kit_id="k1").kit_id == "k1"
    # unknown id falls back to the default kit, never errors
    assert resolve_kit_for(p, kit_id="ghost").kit_id == "k1"


# ---- bridge to BrandKit ------------------------------------------------


def test_brand_kit_from_ref_overlays_custom_palette():
    p = _profile()
    sponsor = BrandKitRef(
        kit_id="s1",
        name="Sponsor livery",
        role="sponsor",
        palette={"primary": "#ff0000", "secondary": "#00ff00"},
    )
    bk = brand_kit_from_ref(p, sponsor)
    assert bk.primary_colour == "#ff0000"
    assert bk.secondary_colour == "#00ff00"
    # a custom palette must not reuse the org's cached derived theme
    assert bk.derived_palette is None


def test_brand_kit_from_ref_inherits_blank_slots():
    p = _profile()
    # only override the accent; primary/secondary inherit from the org base
    k = BrandKitRef(kit_id="k1", name="Tweak", role="event", palette={"accent": "#abcdef"})
    bk = brand_kit_from_ref(p, k)
    base = p.get_brand_kit()
    assert bk.primary_colour == base.primary_colour
    assert bk.secondary_colour == base.secondary_colour
    assert bk.accent_colour == "#abcdef"


# ---- persistence -------------------------------------------------------


def test_brand_kits_persist_through_save_load():
    p = _profile()
    upsert_kit(p, BrandKitRef(kit_id="k1", name="Gala 2026", role="event", locks=["palette"]))
    set_default_kit(p, "k1")
    save_profile(p)

    loaded = load_profile("testclub")
    assert loaded is not None
    assert loaded.default_kit_id == "k1"
    kits = {k.kit_id: k for k in list_kits(loaded)}
    assert "k1" in kits
    assert kits["k1"].role == "event"
    assert kits["k1"].locks == ["palette"]


def test_legacy_profile_json_without_kits_field_loads():
    # A profile JSON predating 1.12 has no brand_kits key at all.
    raw = {"profile_id": "old", "display_name": "Old Club", "brand_primary": "#102030"}
    p = ClubProfile.from_dict(raw)
    assert p.brand_kits == []
    assert p.default_kit_id == ""
    assert len(list_kits(p)) == 1  # synthesised primary
