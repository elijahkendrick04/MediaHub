"""UI2.1 — Cut-out before/after compare slider.

Wires the design-system kit's `.mh-compare` slider onto a *real*
original-photo ↔ background-removed cut-out preview in the media flow, so a
user can drag to see exactly what rembg knocked out.

These tests pin the whole surface:

  * the `_v8_ensure_cutout` resolver — cached / generated / honest-unavailable
    / failed / no-source, and the honest-error rule (never a fake pass-through
    cut-out when no real remover is available);
  * the cut-out file route (`/api/media-library/cutout/<id>`) — serves a PNG,
    is profile-scoped (IDOR), and 503s honestly when unavailable;
  * the before/after preview page (`/media-library/<id>/cutout`) — renders the
    reused `.mh-compare` markup (handle + checkerboard after-layer), is
    pixel-perfect sized to the photo, escapes subject metadata, links back,
    explains the provider, and falls back honestly with no fake slider;
  * the media-library row exposing the preview link;
  * the kit CSS/JS contract (reuse, not duplication; checkerboard is
    token-driven and static).

The background remover is mocked everywhere so tests never download the
~170 MB rembg model or hit the network.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

THEME_MOTION_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-motion.css"
UI_KIT_JS = _ROOT / "src" / "mediahub" / "web" / "static" / "js" / "ui-kit.js"


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_ctx(app, web_module, tmp_path):
    """Fresh Flask app with two saved orgs and DATA_DIR pinned to tmp."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))

    return app, tmp_path, web_module


def _png_bytes(w: int = 200, h: int = 250) -> bytes:
    """A non-uniform PNG so it compresses to a realistic size (>1000 bytes),
    matching the cache-validity guard that real photos always satisfy."""
    import os

    from PIL import Image

    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _seed_asset(
    tmp_path: Path,
    profile_id: str,
    *,
    filename: str = "athlete.png",
    w: int = 200,
    h: int = 250,
    athlete_names=None,
) -> str:
    """Save a real PNG file + a media_library row for a given profile."""
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    asset_path = tmp_path / f"{profile_id}_{filename}"
    asset_path.write_bytes(_png_bytes(w, h))
    store = get_store()
    asset = MediaAsset(
        id="",
        filename=filename,
        path=str(asset_path),
        type="athlete_photo",
        profile_id=profile_id,
        permission_status="approved_by_club",
        approval_status="approved",
        linked_athlete_names=athlete_names if athlete_names is not None else ["Eira Hughes"],
    )
    return store.save(asset).id


class _FakeRemover:
    """A bg remover that writes a believable transparent cut-out PNG."""

    name = "rembg_local"

    def __init__(self, available=True):
        self._available = available
        self.remove_calls = 0

    def is_available(self) -> bool:
        return self._available

    def remove(self, src_path, dst_path) -> str:
        # If something asks an *unavailable* remover to run, that's a bug:
        # the honest-error rule says we must not fake a cut-out.
        assert self._available, "remove() must never be called when unavailable"
        self.remove_calls += 1
        from PIL import Image, ImageDraw

        img = Image.open(src_path).convert("RGBA")
        # A believable person matte: one bottom-anchored opaque silhouette on
        # a transparent field, so the M14 matte-quality gate (coverage bounds,
        # single component, limited border contact) accepts it like a real cut.
        w, h = img.size
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        # head + torso: covers roughly a third of the frame, touching only
        # part of the bottom edge — the shape rembg gives for a swimmer.
        draw.ellipse((w * 0.38, h * 0.10, w * 0.62, h * 0.32), fill=255)
        draw.polygon(
            [(w * 0.30, h * 0.30), (w * 0.70, h * 0.30), (w * 0.62, h - 1), (w * 0.38, h - 1)],
            fill=255,
        )
        img.putalpha(mask)
        Path(dst_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(dst_path, "PNG")
        return str(dst_path)


@pytest.fixture
def patch_remover(monkeypatch):
    """Install a fake remover; return it so tests can flip availability."""

    def _install(available=True):
        fake = _FakeRemover(available=available)
        import mediahub.media_ai.providers as prov

        monkeypatch.setattr(prov, "get_bg_remover", lambda: fake)
        return fake

    return _install


def _pin(client, profile_id="alpha"):
    client.post("/api/organisation/active", data={"profile_id": profile_id})


# --------------------------------------------------------------------------- #
# 1. The resolver: _v8_ensure_cutout
# --------------------------------------------------------------------------- #
class TestEnsureCutoutResolver:
    def test_generated_then_persisted(self, app_ctx, patch_remover):
        app, tmp_path, wm = app_ctx
        fake = patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            from mediahub.media_library.store import get_store

            asset = get_store().get(aid)
            path, status = wm._v8_ensure_cutout(asset)
        assert status == "generated", status
        assert path is not None and path.exists()
        assert fake.remove_calls == 1
        # cutout_path is persisted onto the asset for next time
        again = get_store().get(aid)
        assert again.cutout_path and Path(again.cutout_path).exists()

    def test_cached_skips_regeneration(self, app_ctx, patch_remover):
        app, tmp_path, wm = app_ctx
        fake = patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            from mediahub.media_library.store import get_store

            asset = get_store().get(aid)
            wm._v8_ensure_cutout(asset)  # generate + persist
            asset2 = get_store().get(aid)
            calls_before = fake.remove_calls
            path, status = wm._v8_ensure_cutout(asset2)  # should hit cache
        assert status == "cached", status
        assert path is not None and path.exists()
        assert fake.remove_calls == calls_before, "cache hit must not re-run rembg"

    def test_unavailable_is_honest_and_never_fakes(self, app_ctx, patch_remover):
        """No working remover ⇒ honest 'unavailable', and remove() is never
        called (so we never serve a pass-through that looks like the original)."""
        app, tmp_path, wm = app_ctx
        fake = patch_remover(available=False)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            from mediahub.media_library.store import get_store

            asset = get_store().get(aid)
            path, status = wm._v8_ensure_cutout(asset)
        assert path is None
        assert status == "unavailable", status
        assert fake.remove_calls == 0

    def test_no_source_when_file_missing(self, app_ctx, patch_remover):
        app, tmp_path, wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            from mediahub.media_library.store import get_store

            asset = get_store().get(aid)
            Path(asset.path).unlink()  # original vanished
            path, status = wm._v8_ensure_cutout(asset)
        assert path is None
        assert status == "no_source", status

    def test_none_asset_is_no_source(self, app_ctx):
        _app, _tmp, wm = app_ctx
        assert wm._v8_ensure_cutout(None) == (None, "no_source")


# --------------------------------------------------------------------------- #
# 2. The cut-out file route
# --------------------------------------------------------------------------- #
class TestCutoutFileRoute:
    def test_serves_png_when_available(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            resp = c.get(f"/api/media-library/cutout/{aid}")
        assert resp.status_code == 200, resp.status_code
        assert resp.content_type.startswith("image/png"), resp.content_type
        assert resp.data[:8] == b"\x89PNG\r\n\x1a\n", "must be a real PNG"

    def test_foreign_profile_forbidden(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c, "alpha")
            beta_id = _seed_asset(tmp_path, "beta")
            resp = c.get(f"/api/media-library/cutout/{beta_id}")
        assert resp.status_code == 403, resp.status_code

    def test_missing_asset_404(self, app_ctx, patch_remover):
        app, _tmp, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            resp = c.get("/api/media-library/cutout/ma_does_not_exist")
        assert resp.status_code == 404, resp.status_code

    def test_503_when_remover_unavailable(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=False)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            resp = c.get(f"/api/media-library/cutout/{aid}")
        assert resp.status_code == 503, f"honest 503 when no remover; got {resp.status_code}"

    def test_run_scoped_profile_allowed(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c, "alpha")
            run_id = _seed_asset(tmp_path, "_run_abc123")
            resp = c.get(f"/api/media-library/cutout/{run_id}")
        assert resp.status_code == 200, resp.status_code


# --------------------------------------------------------------------------- #
# 3. The before/after preview page
# --------------------------------------------------------------------------- #
class TestCutoutPreviewPage:
    def _page(self, client, asset_id):
        resp = client.get(f"/media-library/{asset_id}/cutout")
        return resp

    def test_renders_reused_compare_markup(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            resp = self._page(c, aid)
        assert resp.status_code == 200, resp.status_code
        body = resp.get_data(as_text=True)
        # reuses the kit's compare component (not a bespoke slider)
        assert 'class="mh-compare"' in body
        assert "mh-compare__after--checker" in body
        assert "mh-compare__handle" in body
        assert 'data-mh-pos="50"' in body
        # before = original-file route, after = cut-out route
        assert f"/api/media-library/file/{aid}" in body
        assert f"/api/media-library/cutout/{aid}" in body

    def test_sized_to_photo_aspect_ratio(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha", w=300, h=400)
            body = self._page(c, aid).get_data(as_text=True)
        assert "aspect-ratio:300 / 400" in body, "slider must match the photo shape"

    def test_explains_the_provider(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            body = self._page(c, aid).get_data(as_text=True)
        assert "rembg" in body.lower(), "preview should name what cut the image out"

    def test_back_link_to_library(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            body = self._page(c, aid).get_data(as_text=True)
        assert "/media-library" in body
        assert "Back to library" in body

    def test_images_have_descriptive_alt(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha", athlete_names=["Eira Hughes"])
            body = self._page(c, aid).get_data(as_text=True)
        assert 'alt="Original photo of Eira Hughes, background intact"' in body
        assert 'alt="Eira Hughes with the background removed"' in body

    def test_subject_metadata_is_escaped(self, app_ctx, patch_remover):
        """Athlete names are user/AI supplied — must be HTML-escaped (no XSS)."""
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha", athlete_names=["<script>alert(1)</script>"])
            body = self._page(c, aid).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_honest_fallback_when_unavailable_no_fake_slider(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=False)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            resp = self._page(c, aid)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "No cut-out to show" in body
        # honest: the original is still shown, but NO compare slider is faked.
        # (Check markup-only tokens — the kit CSS naming the classes is always
        # inlined in the shell, so assert on the figure markup, not class names.)
        assert f"/api/media-library/file/{aid}" in body
        assert 'class="mh-compare"' not in body
        assert "data-mh-pos" not in body
        assert f"/api/media-library/cutout/{aid}" not in body

    def test_foreign_profile_403(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c, "alpha")
            beta_id = _seed_asset(tmp_path, "beta")
            resp = self._page(c, beta_id)
        assert resp.status_code == 403, resp.status_code

    def test_missing_asset_404(self, app_ctx, patch_remover):
        app, _tmp, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            resp = self._page(c, "ma_missing")
        assert resp.status_code == 404, resp.status_code


# --------------------------------------------------------------------------- #
# 4. The media-library row link
# --------------------------------------------------------------------------- #
class TestLibraryRowLink:
    def test_row_links_to_cutout_preview(self, app_ctx, patch_remover):
        app, tmp_path, _wm = app_ctx
        patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            aid = _seed_asset(tmp_path, "alpha")
            resp = c.get("/media-library")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert f"/media-library/{aid}/cutout" in body
        assert ">Cut-out<" in body

    def test_listing_does_not_eagerly_generate(self, app_ctx, patch_remover):
        """Browsing the library must not run rembg on every asset — the
        cut-out is generated lazily only when the preview is opened."""
        app, tmp_path, _wm = app_ctx
        fake = patch_remover(available=True)
        with app.test_client() as c:
            _pin(c)
            _seed_asset(tmp_path, "alpha", filename="a.png")
            _seed_asset(tmp_path, "alpha", filename="b.png")
            c.get("/media-library")
        assert fake.remove_calls == 0, "library listing must not generate cut-outs"


# --------------------------------------------------------------------------- #
# 5. The kit CSS / JS contract (reuse, token-driven, static)
# --------------------------------------------------------------------------- #
class TestKitContract:
    CSS = THEME_MOTION_CSS.read_text(encoding="utf-8")
    JS = UI_KIT_JS.read_text(encoding="utf-8")

    def test_checker_rule_exists(self):
        assert ".mh-compare__after--checker" in self.CSS

    def test_reuses_existing_compare_component(self):
        # We build on the already-shipped slider rather than duplicating it.
        for sel in (".mh-compare", ".mh-compare__after", ".mh-compare__handle"):
            assert sel in self.CSS, f"missing reused kit rule {sel}"

    def test_checker_is_token_driven(self):
        block = self.CSS[self.CSS.find(".mh-compare__after--checker") :]
        block = block[: block.find("}") + 1]
        assert "var(--mh-surface)" in block
        assert "var(--mh-outline-variant)" in block

    def test_checker_is_static_no_motion(self):
        block = self.CSS[self.CSS.find(".mh-compare__after--checker") :]
        block = block[: block.find("}") + 1]
        # A transparency backdrop must not animate (reduced-motion / no-JS safe).
        assert "animation" not in block
        assert "transition" not in block

    def test_kit_js_binds_compare(self):
        # The behaviour layer that drags the slider already ships in the kit.
        assert "mh-compare" in self.JS
        assert "bindCompare" in self.JS
