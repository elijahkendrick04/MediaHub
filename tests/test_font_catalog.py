"""Curated self-hosted font catalogue (roadmap 1.9).

Guards the catalogue itself (controlled vocabularies, unique slugs, a valid
affinity graph) and — the important part — keeps it in **lock-step with the
on-disk assets** across all three surfaces, so a catalogue face can never drift
away from its woff2 / ``@font-face`` declaration (nor sneak the Google Fonts CDN
back in). The per-org upload merge (``org_catalog``) needs the woff2 toolchain
and skips cleanly where it is absent.
"""
from __future__ import annotations

import pytest

from mediahub.typography import catalog as cat
from mediahub.typography import font_intake as fi


# --------------------------------------------------------------------------- #
# Catalogue integrity
# --------------------------------------------------------------------------- #
class TestCatalogueIntegrity:
    def test_loads_and_has_curated_set(self):
        fonts = cat.load_catalog()
        assert len(fonts) >= 9
        assert all(isinstance(f, cat.CatalogFont) for f in fonts)

    def test_slugs_unique(self):
        slugs = [f.slug for f in cat.load_catalog()]
        assert len(slugs) == len(set(slugs))

    def test_controlled_vocabularies(self):
        for f in cat.load_catalog():
            assert f.klass in cat.CLASS_VOCAB
            for m in f.mood_tags:
                assert m in cat.MOOD_VOCAB, f"{f.slug}: bad mood {m}"
            for r in f.role_affinity:
                assert r in cat.ROLE_VOCAB, f"{f.slug}: bad role {r}"

    def test_affinity_graph_resolves(self):
        slugs = {f.slug for f in cat.load_catalog()}
        for f in cat.load_catalog():
            for p in f.pairs_well_with:
                assert p in slugs, f"{f.slug}: dangling pair {p}"

    def test_every_face_hosts_somewhere(self):
        for f in cat.load_catalog():
            assert f.surfaces, f"{f.slug}: hosted on no surface"

    def test_licence_is_self_hostable(self):
        # Curated built-ins are OFL; no proprietary/CDN-only licence sneaks in.
        for f in cat.load_catalog():
            assert "OFL" in f.licence or "Apache" in f.licence, f"{f.slug}: {f.licence}"

    def test_bad_entry_rejected(self):
        with pytest.raises(cat.CatalogError):
            cat._coerce_entry({"slug": "x", "family": "X", "klass": "blackletter"})
        with pytest.raises(cat.CatalogError):
            cat._coerce_entry(
                {"slug": "x", "family": "X", "klass": "sans", "mood_tags": ["smelly"]}
            )
        with pytest.raises(cat.CatalogError):
            # hosts on no surface
            cat._coerce_entry({"slug": "x", "family": "X", "klass": "sans"})


# --------------------------------------------------------------------------- #
# Lock-step with disk (the guard that matters)
# --------------------------------------------------------------------------- #
class TestAssetLockStep:
    def test_verify_assets_clean(self):
        problems = cat.verify_assets()
        assert problems == [], f"catalogue drifted from disk: {problems}"

    def test_renderer_faces_present_on_renderer_and_reel(self):
        for f in cat.for_surface("renderer"):
            assert (cat._RENDERER_FONTS / f"{f.renderer_slug}.woff2").is_file()
            assert (cat._REEL_FONTS / f"{f.renderer_slug}.woff2").is_file()

    def test_web_faces_present(self):
        for f in cat.for_surface("web"):
            assert list(cat._WEB_FONTS.glob(f"{f.web_slug}-*.woff2"))

    def test_no_cdn_in_catalogue_source(self):
        raw = cat._CATALOG_JSON.read_text(encoding="utf-8")
        assert "googleapis" not in raw and "gstatic" not in raw


# --------------------------------------------------------------------------- #
# Query surface
# --------------------------------------------------------------------------- #
class TestQuery:
    def test_get(self):
        anton = cat.get("anton")
        assert anton is not None and anton.family == "Anton"
        assert cat.get("does-not-exist") is None

    def test_search_by_class(self):
        displays = cat.search(klass="display")
        assert displays and all(f.klass == "display" for f in displays)

    def test_search_by_mood(self):
        loud = cat.search(mood="loud")
        assert loud and all("loud" in f.mood_tags for f in loud)

    def test_search_by_surface(self):
        web = cat.search(surface="web")
        assert web and all("web" in f.surfaces for f in web)

    def test_search_by_role_and_numeral(self):
        numerals = cat.search(numeral=True)
        assert numerals and all(f.numeral for f in numerals)
        bodies = cat.search(role="body")
        assert bodies and all("body" in f.role_affinity for f in bodies)

    def test_search_ands_filters(self):
        # A display face that is also a numeral hero (Anton).
        hits = cat.search(klass="display", numeral=True)
        assert any(f.slug == "anton" for f in hits)

    def test_jetbrains_spans_all_surfaces(self):
        jb = cat.get("jetbrains-mono")
        assert jb is not None
        assert set(jb.surfaces) == {"web", "renderer", "reel"}

    def test_css_stack_and_dict(self):
        f = cat.get("fraunces")
        assert f is not None
        assert f.css_stack == "'Fraunces', serif"
        d = f.to_dict()
        assert d["slug"] == "fraunces" and "surfaces" in d


# --------------------------------------------------------------------------- #
# Per-org catalogue (built-ins + uploads)
# --------------------------------------------------------------------------- #
class TestOrgCatalogue:
    def test_org_catalog_without_uploads_is_builtins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        merged = cat.org_catalog("club-empty")
        assert len(merged) == len(cat.load_catalog())
        assert all(not f.custom for f in merged)

    @pytest.mark.skipif(
        not fi.is_font_tooling_available(), reason="fontTools + brotli (woff2) not installed"
    )
    def test_org_catalog_merges_uploads(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from tests.test_font_intake import build_ttf

        fi.intake_font(build_ttf("Club Brand", weight=700), profile_id="club-x", role="display")
        merged = cat.org_catalog("club-x")
        customs = [f for f in merged if f.custom]
        assert len(customs) == 1
        c = customs[0]
        assert c.family == "Club Brand"
        assert c.custom and c.css_family.startswith("club-")
        assert set(c.surfaces) == {"renderer", "reel"}
        assert "'" + c.css_family + "'" in c.css_stack
        # tenant isolation — another club sees no custom faces
        assert not [f for f in cat.org_catalog("club-y") if f.custom]
