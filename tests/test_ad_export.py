"""Roadmap 1.14 — sponsor A/B ad-variant export sets (prepare, never place).

Pins the ad-platform specs, the deterministic A/B set builder + manifest, and
the web surfaces (the set page + the manifest export), including the standing
"prepares, never spends" guarantee, org-gating and tenant isolation.
"""

from __future__ import annotations

import pytest

from mediahub.ad_export import (
    ad_platform,
    all_ad_platforms,
    build_variant_set,
    manifest_text,
)


# ---------------------------------------------------------------------------
# Specs + builder
# ---------------------------------------------------------------------------


def test_ad_platform_lookup_and_aliases():
    assert ad_platform("meta").slug == "meta"
    assert ad_platform("facebook").slug == "meta"  # alias
    assert ad_platform("instagram").slug == "meta"
    assert ad_platform("google").slug == "google_display"
    assert ad_platform("nope") is None
    slugs = {p.slug for p in all_ad_platforms()}
    assert {"meta", "google_display", "linkedin", "tiktok"} <= slugs
    # Every platform ships at least one concrete size with an aspect label.
    for p in all_ad_platforms():
        assert p.sizes and all(s.width > 0 and s.height > 0 for s in p.sizes)
        assert p.sizes[0].aspect_label()


def test_build_variant_set_labels_and_skips_empty():
    cards = [
        {"caption": "Proudly backed by AquaCorp.", "hashtags": ["AquaCorp"]},
        {"caption": "AquaCorp powers our swimmers!", "hashtags": ["swim"]},
        {"caption": "   "},  # empty → skipped
    ]
    vs = build_variant_set(cards, "AquaCorp", "meta")
    assert vs is not None
    assert [v.label for v in vs.variants] == ["A", "B"]  # labelled, empty skipped
    assert vs.sponsor == "AquaCorp"
    assert vs.platform.slug == "meta"
    # Unknown platform → None (honest).
    assert build_variant_set(cards, "AquaCorp", "myspace") is None
    # No usable copy → an empty set, not an error.
    assert build_variant_set([{"caption": ""}], "X", "meta").variants == []


def test_build_variant_set_is_deterministic_and_capped():
    cards = [{"caption": f"Angle {i}"} for i in range(20)]
    a = build_variant_set(cards, "Sp", "meta")
    b = build_variant_set(cards, "Sp", "meta")
    assert a.to_dict()["variants"] == b.to_dict()["variants"]
    from mediahub.ad_export.variants import MAX_VARIANTS

    assert len(a.variants) == MAX_VARIANTS  # capped


def test_manifest_states_sizes_and_no_spend_guarantee():
    vs = build_variant_set(
        [{"caption": "Backed by AquaCorp", "hashtags": ["AquaCorp"]}], "AquaCorp", "meta"
    )
    text = manifest_text(vs)
    assert "AquaCorp" in text
    assert "Variant A" in text
    assert "1080x1080" in text  # a Meta size is spelled out
    # The standing rule is stated in the export itself.
    assert "does NOT buy or place ads" in text
    # A set with no sponsor is honest, not blank-tagged.
    no_sponsor = manifest_text(build_variant_set([{"caption": "x"}], "", "meta"))
    assert "(sponsor not set)" in no_sponsor


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club",
                             sponsor_name="AquaCorp"))
    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _with_org(client, org_id: str):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


def _seed_sponsor_pack(profile_id="org-test"):
    from mediahub.club_platform import stub_pack_store as sps

    rec = sps.save_pack(
        "sponsor_activation",
        {"sponsor_name": "AquaCorp", "meet_name": "County"},
        [
            {"caption": "Proudly backed by AquaCorp.", "hashtags": ["AquaCorp"]},
            {"caption": "AquaCorp powers our swimmers!", "hashtags": ["swim"]},
        ],
        profile_id=profile_id,
    )
    return rec["pack_id"]


def test_ad_variants_page_and_export(app_with_org):
    with app_with_org.test_client() as client:
        _with_org(client, "org-test")
        pid = _seed_sponsor_pack()

        page = client.get(f"/plan/ad-variants/{pid}")
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "AquaCorp" in html
        assert "never buys or places ads" in html  # the no-spend guarantee, on-page
        assert "Variant" in html and "Meta Ads" in html

        # Platform switch works.
        assert client.get(f"/plan/ad-variants/{pid}?platform=google_display").status_code == 200

        # Export is a downloadable text manifest with the no-spend disclaimer.
        exp = client.get(f"/api/plan/ad-variants/{pid}/export?platform=meta")
        assert exp.status_code == 200
        assert exp.headers["Content-Type"].startswith("text/plain")
        assert "attachment" in exp.headers["Content-Disposition"]
        assert "does NOT buy or place ads" in exp.get_data(as_text=True)
        # Unknown platform on export → 400.
        assert client.get(
            f"/api/plan/ad-variants/{pid}/export?platform=myspace"
        ).status_code == 400


def test_ad_variants_require_org_and_isolate_tenants(app_with_org):
    with app_with_org.test_client() as client:
        # No org → page redirects, export 403.
        assert client.get("/plan/ad-variants/whatever").status_code == 302
        assert client.get("/api/plan/ad-variants/whatever/export").status_code == 403

    pid = _seed_sponsor_pack(profile_id="org-test")
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-other", display_name="Other"))
    with app_with_org.test_client() as client:
        _with_org(client, "org-other")  # different org
        assert client.get(f"/plan/ad-variants/{pid}").status_code == 404
        assert client.get(f"/api/plan/ad-variants/{pid}/export").status_code == 404
