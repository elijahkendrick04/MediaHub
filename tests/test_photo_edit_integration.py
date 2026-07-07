"""Tests for media_library.photo_edit + the store migration (roadmap 1.3).

Covers the asset-integration layer that wires the pure photo_ops engine to a
stored MediaAsset: non-destructive recipe persistence, the lazy ``edit_recipe``
column migration, signature-keyed materialisation, the effective-path resolver,
the per-club enhance memory, and the derived-asset exports (profile pictures,
collages). Uses a real on-disk SQLite store in a tmp dir — no web, no network.
"""
from __future__ import annotations

import sqlite3

import numpy as np
from PIL import Image

from mediahub.media_library.models import MediaAsset
from mediahub.media_library.store import MediaLibraryStore
from mediahub.media_library import photo_edit as pe
from mediahub.media_library.photo_ops import EditRecipe


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _store(tmp_path) -> MediaLibraryStore:
    return MediaLibraryStore(db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads")


def _write_photo(tmp_path, name="p.jpg", size=(80, 60), rgb=(120, 80, 40)) -> str:
    p = tmp_path / name
    Image.new("RGB", size, rgb).save(p)
    return str(p)


def _save_asset(store, tmp_path, *, profile_id="club_a", name="p.jpg", **kw) -> MediaAsset:
    path = _write_photo(tmp_path, name=name, **kw)
    a = MediaAsset(id="", filename=name, path=path, type="athlete_action", profile_id=profile_id)
    return store.save(a)


# --------------------------------------------------------------------------- #
# Schema migration
# --------------------------------------------------------------------------- #


def test_lazy_migration_adds_edit_recipe_column(tmp_path):
    # Build an *old-shape* table without the edit_recipe column.
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE media_assets (id TEXT PRIMARY KEY, filename TEXT, path TEXT, type TEXT, "
        "profile_id TEXT, description_parsed TEXT)"
    )
    conn.execute("INSERT INTO media_assets (id, filename, path, type) VALUES ('ma_old','o.jpg','/x','other')")
    conn.commit()
    conn.close()

    # Opening the store migrates in place; the old row still loads.
    store = MediaLibraryStore(db_path=db, uploads_dir=tmp_path / "up")
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(media_assets)")}
    assert "edit_recipe" in cols
    a = store.get("ma_old")
    assert a is not None and a.edit_recipe == {}


def test_edit_recipe_persists_and_reloads(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    recipe = EditRecipe.build([("warmth", {"amount": 20}), ("contrast", {"factor": 1.1})])
    pe.save_recipe(a, recipe, store)
    reloaded = store.get(a.id)
    # Persisted recipe is canonicalised; it round-trips to the canonical form.
    assert pe.recipe_for_asset(reloaded) == recipe.canonical()
    assert pe.recipe_for_asset(reloaded).signature() == recipe.canonical().signature()
    assert pe.has_edit(reloaded)


# --------------------------------------------------------------------------- #
# Materialisation + effective path
# --------------------------------------------------------------------------- #


def test_effective_path_is_original_without_recipe(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    assert pe.effective_image_path(a, store) == a.path


def test_materialize_creates_signature_keyed_cache(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    recipe = EditRecipe.build([("crop", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8})])
    pe.save_recipe(a, recipe, store)
    a = store.get(a.id)

    out1 = pe.materialize_edit(a, store)
    assert recipe.signature() in out1
    assert out1 != a.path
    # The edited file is a real, smaller crop of the original.
    with Image.open(out1) as im:
        assert im.size == (64, 48)
    # Idempotent: same recipe → same cached path, no re-render needed.
    out2 = pe.materialize_edit(a, store)
    assert out1 == out2


def test_effective_path_uses_cache_and_reflects_recipe_change(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    pe.save_recipe(a, EditRecipe.build([("warmth", {"amount": 10})]), store)
    a = store.get(a.id)
    first = pe.effective_image_path(a, store)
    assert first != a.path

    # Change the recipe → a different signature → a different cache file.
    pe.save_recipe(a, EditRecipe.build([("warmth", {"amount": 40})]), store)
    a = store.get(a.id)
    second = pe.effective_image_path(a, store)
    assert second != first


def test_clear_recipe_removes_recipe_and_cache(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    pe.save_recipe(a, EditRecipe.build([("vignette", {"amount": 30})]), store)
    a = store.get(a.id)
    cached = pe.materialize_edit(a, store)
    from pathlib import Path

    assert Path(cached).exists()
    pe.clear_recipe(a, store)
    a = store.get(a.id)
    assert not pe.has_edit(a)
    assert not Path(cached).exists()  # stale cache swept


def test_edited_bytes_noop_returns_original(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path)
    from pathlib import Path

    data, mime = pe.edited_bytes(a)
    assert data == Path(a.path).read_bytes()


# --------------------------------------------------------------------------- #
# Per-club enhance memory
# --------------------------------------------------------------------------- #


def test_enhance_memory_defaults_and_nudges(tmp_path):
    store = _store(tmp_path)
    assert pe.remembered_enhance_strength("club_a", store) == 1.0
    pe.record_enhance_accepted("club_a", 0.0, store)
    s = pe.remembered_enhance_strength("club_a", store)
    assert 0.0 <= s < 1.0  # moved toward the accepted lower strength
    # Another club is independent.
    assert pe.remembered_enhance_strength("club_b", store) == 1.0


def test_suggest_enhance_returns_recipe(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path, rgb=(30, 40, 60))  # dim, casted
    recipe = pe.suggest_enhance(a, store)
    assert isinstance(recipe, EditRecipe)
    assert not recipe.is_noop()


# --------------------------------------------------------------------------- #
# Derived-asset exports
# --------------------------------------------------------------------------- #


def test_export_profile_picture_creates_square_draft(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path, size=(400, 300))
    new = pe.export_profile_picture(a, store, preset="avatar_circle")
    assert new.id != a.id
    assert new.profile_id == a.profile_id
    assert new.approval_status == "draft"
    assert "profile-picture" in new.tags
    with Image.open(new.path) as im:
        assert im.size == (512, 512)
        assert im.mode == "RGBA"
    # It is in the store, scoped to the club.
    assert store.get(new.id) is not None


def test_export_profile_picture_non_square_is_not_distorted(tmp_path):
    """A 4:3 source must be centre-cropped square, never squashed to 512x512."""
    store = _store(tmp_path)
    # 400x300: centre 300x300 square red, the outer flanks blue. A distorting
    # resize would drag blue into the avatar; a centred crop keeps it all red.
    img = Image.new("RGB", (400, 300), (0, 0, 255))
    img.paste(Image.new("RGB", (300, 300), (255, 0, 0)), (50, 0))
    p = tmp_path / "wide.jpg"
    img.save(p)
    a = store.save(MediaAsset(id="", filename="wide.jpg", path=str(p), type="athlete_action", profile_id="club_a"))
    new = pe.export_profile_picture(a, store, preset="avatar_circle")
    with Image.open(new.path) as im:
        assert im.size == (512, 512)
        r, g, b, alpha = im.convert("RGBA").getpixel((10, 256))
        assert alpha > 0
        assert r > 200 and b < 60  # red centre-crop content, no squashed blue


def test_avatar_ring_preset_draws_a_ring(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path, size=(300, 300), rgb=(10, 120, 10))
    ring = pe.export_profile_picture(a, store, preset="avatar_ring")
    circle = pe.export_profile_picture(a, store, preset="avatar_circle")
    with Image.open(ring.path) as im_ring, Image.open(circle.path) as im_circle:
        assert im_ring.tobytes() != im_circle.tobytes()
        # a ring pixel near the left edge of the centre row carries the ring
        # colour (neutral white here — no club profile resolves in this store),
        # while the plain circle shows the photo's green there
        rr, rg, rb, ra = im_ring.convert("RGBA").getpixel((20, 256))
        cr, cg, cb, _ = im_circle.convert("RGBA").getpixel((20, 256))
        assert ra == 255
        assert (rr, rg, rb) != (cr, cg, cb)
        assert rr > 200 and rb > 200  # white fallback ring, not the green photo


def test_apply_scaled_enhance_suggestion_teaches_memory(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path, rgb=(30, 40, 60))  # dim, casted
    scaled = pe.enhance_auto(a.path, strength=0.5)
    assert not scaled.is_noop()
    got = pe.maybe_record_enhance_accepted(a, scaled, store)
    assert got == 0.5
    assert pe.remembered_enhance_strength("club_a", store) < 1.0  # nudged


def test_unrelated_manual_edit_never_teaches_memory(tmp_path):
    store = _store(tmp_path)
    a = _save_asset(store, tmp_path, rgb=(30, 40, 60))
    manual = EditRecipe.build([("warmth", {"amount": 25}), ("crop", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8})])
    assert pe.maybe_record_enhance_accepted(a, manual, store) is None
    assert pe.remembered_enhance_strength("club_a", store) == 1.0


def test_create_collage_from_two_assets(tmp_path):
    store = _store(tmp_path)
    a1 = _save_asset(store, tmp_path, name="a1.jpg", rgb=(200, 0, 0))
    a2 = _save_asset(store, tmp_path, name="a2.jpg", rgb=(0, 200, 0))
    collage = pe.create_collage(
        [a1.id, a2.id], store, profile_id="club_a", layout="duo_v", width=200, height=100
    )
    assert collage is not None
    assert collage.approval_status == "draft"
    assert "collage" in collage.tags
    with Image.open(collage.path) as im:
        assert im.size == (200, 100)


def test_create_collage_needs_two_usable_photos(tmp_path):
    store = _store(tmp_path)
    a1 = _save_asset(store, tmp_path, name="only.jpg")
    assert pe.create_collage([a1.id], store, profile_id="club_a") is None


def test_create_collage_excludes_foreign_profiles(tmp_path):
    store = _store(tmp_path)
    mine = _save_asset(store, tmp_path, name="mine.jpg", profile_id="club_a")
    theirs = _save_asset(store, tmp_path, name="theirs.jpg", profile_id="club_b")
    # Only one belongs to club_a, so a collage can't be built → None.
    assert pe.create_collage([mine.id, theirs.id], store, profile_id="club_a") is None


def test_collage_inherits_per_photo_edits(tmp_path):
    store = _store(tmp_path)
    a1 = _save_asset(store, tmp_path, name="a1.jpg", rgb=(200, 0, 0))
    a2 = _save_asset(store, tmp_path, name="a2.jpg", rgb=(0, 200, 0))
    # Edit a1 to greyscale; the collage should read its *effective* (edited) image.
    pe.save_recipe(a1, EditRecipe.build([("grayscale", {"amount": 1.0})]), store)
    collage = pe.create_collage([a1.id, a2.id], store, profile_id="club_a", layout="duo_v", width=200, height=100)
    arr = np.asarray(Image.open(collage.path).convert("RGB"), np.float64)
    left = arr[:, :100]  # a1's cell — now near-grey, so R≈G≈B
    assert abs(left[..., 0].mean() - left[..., 1].mean()) < 30


def test_asset_dicts_for_render_applies_edits(tmp_path):
    """The render-path dicts must carry the materialised edit, not the raw
    original — a safeguarding blur that only exists in the editor preview is a
    broken promise on the rendered card."""
    store = _store(tmp_path)
    edited = _save_asset(store, tmp_path, name="edited.jpg")
    plain = _save_asset(store, tmp_path, name="plain.jpg")
    pe.save_recipe(edited, EditRecipe.build([("warmth", {"amount": 25})]), store)
    edited = store.get(edited.id)

    dicts = pe.asset_dicts_for_render([edited, plain], store)

    assert len(dicts) == 2
    edited_dict = next(d for d in dicts if d["path"] != plain.path and d["id"] == edited.id)
    assert edited_dict["path"] == pe.effective_image_path(edited, store)
    assert edited_dict["path"] != edited.path
    plain_dict = next(d for d in dicts if d["id"] == plain.id)
    assert plain_dict["path"] == plain.path
