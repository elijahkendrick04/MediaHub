"""Asset integration for the non-destructive photo editor (roadmap **1.3**).

:mod:`mediahub.media_library.photo_ops` is the pure, browser-free engine. This
module is the thin layer that wires it to a stored :class:`MediaAsset`:

* read / save an asset's :class:`~mediahub.media_library.photo_ops.EditRecipe`
  (persisted in the ``edit_recipe`` column — non-destructive: the original file
  on disk is never rewritten);
* **materialise** the edited image into a signature-keyed cache file beside the
  original, so cards / exports re-use the same bytes without re-rendering;
* resolve the **effective image path** any consumer should read (the cached edit
  when a recipe is set, otherwise the untouched original);
* a tiny per-club **enhance memory** so one-click Enhance learns a club's
  preferred strength over time (still deterministic per image + strength);
* derived-asset exports — **profile pictures** and **photo collages** — saved
  back as new draft assets for review (approval-first, like every output).

Everything here is best-effort and isolating: a missing engine, unreadable file
or absent store degrades to "return the original", never an exception into a
render path.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, List, Optional, Sequence

from .models import MediaAsset
from .photo_ops import (
    PROFILE_PRESETS,
    EditRecipe,
    compose_grid,
    enhance_auto,
    encode_image,
    load_image,
    profile_picture_recipe,
)

log = logging.getLogger(__name__)

_EXT_BY_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


# --------------------------------------------------------------------------- #
# Recipe read / save
# --------------------------------------------------------------------------- #


def recipe_for_asset(asset: MediaAsset) -> EditRecipe:
    """The asset's stored :class:`EditRecipe` (empty if none / malformed)."""
    return EditRecipe.from_dict(getattr(asset, "edit_recipe", None) or {})


def has_edit(asset: MediaAsset) -> bool:
    return not recipe_for_asset(asset).is_noop()


def save_recipe(asset: MediaAsset, recipe: EditRecipe, store: Any) -> Optional[MediaAsset]:
    """Persist ``recipe`` on the asset (canonicalised). Clears stale edit caches."""
    canon = recipe.canonical()
    _purge_edit_cache(
        asset, store, keep_signature=canon.signature() if not canon.is_noop() else None
    )
    updated = store.update_fields(asset.id, {"edit_recipe": canon.to_dict()})
    return updated


def clear_recipe(asset: MediaAsset, store: Any) -> Optional[MediaAsset]:
    """Drop the asset's edit recipe and remove its materialised caches."""
    _purge_edit_cache(asset, store, keep_signature=None)
    return store.update_fields(asset.id, {"edit_recipe": {}})


# --------------------------------------------------------------------------- #
# Materialisation + effective path
# --------------------------------------------------------------------------- #


def _edits_dir(asset: MediaAsset, store: Any) -> Path:
    base = Path(getattr(store, "uploads_dir", "."))
    d = base / (asset.profile_id or "_shared") / "edits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _purge_edit_cache(asset: MediaAsset, store: Any, *, keep_signature: Optional[str]) -> None:
    """Best-effort: remove cached edits for this asset except ``keep_signature``."""
    try:
        d = Path(getattr(store, "uploads_dir", ".")) / (asset.profile_id or "_shared") / "edits"
        if not d.exists():
            return
        for p in d.glob(f"{asset.id}_*"):
            if keep_signature and f"_{keep_signature}." in p.name:
                continue
            p.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - cache cleanup never blocks a save
        pass


def materialize_edit(asset: MediaAsset, store: Any, *, recipe: Optional[EditRecipe] = None) -> str:
    """Apply the asset's recipe to a *copy* of the original and cache the result.

    Returns the path to the cached edited file, or the original ``asset.path``
    when there is no recipe (or anything fails). The cache file is named
    ``<asset_id>_<signature>.<ext>`` so it is content-addressed: change the
    recipe and the path changes; the same recipe re-uses the same bytes.
    """
    rec = recipe if recipe is not None else recipe_for_asset(asset)
    if rec.is_noop():
        return asset.path
    try:
        img = load_image(asset.path)
        src_format = (img.format or Path(asset.path).suffix.lstrip(".")).upper()
        edited = rec.apply(img)
        data, mime = encode_image(edited, src_format)
        ext = _EXT_BY_MIME.get(mime, ".png")
        out = _edits_dir(asset, store) / f"{asset.id}_{rec.signature()}{ext}"
        if not out.exists():
            out.write_bytes(data)
        return str(out)
    except Exception as exc:  # pragma: no cover - degrade to the original
        log.warning("materialize_edit failed for %s: %s", getattr(asset, "id", "?"), exc)
        return asset.path


def edited_bytes(asset: MediaAsset, *, recipe: Optional[EditRecipe] = None) -> tuple[bytes, str]:
    """The edited image bytes + MIME for ``asset`` (original bytes if no recipe)."""
    rec = recipe if recipe is not None else recipe_for_asset(asset)
    img = load_image(asset.path)
    src_format = (img.format or Path(asset.path).suffix.lstrip(".")).upper()
    if rec.is_noop():
        data = Path(asset.path).read_bytes()
        mime = _EXT_BY_MIME_INV(src_format)
        return data, mime
    out = rec.apply(img)
    return encode_image(out, src_format)


def _EXT_BY_MIME_INV(fmt: str) -> str:
    fmt = (fmt or "").upper()
    if fmt in ("JPEG", "JPG", "MPO"):
        return "image/jpeg"
    if fmt == "WEBP":
        return "image/webp"
    return "image/png"


def effective_image_path(asset: MediaAsset, store: Any = None) -> str:
    """The path a card / export should read: the cached edit, else the original.

    This is the single call the rest of the pipeline makes — it never has to
    know whether a photo was edited.
    """
    if not has_edit(asset):
        return asset.path
    if store is None:
        try:
            from .store import get_store

            store = get_store()
        except Exception:
            return asset.path
    return materialize_edit(asset, store)


def asset_dicts_for_render(assets: Sequence[Any], store: Any = None) -> List[dict]:
    """Asset dicts for the visual pipeline, with edits applied.

    The render path reads each dict's ``path`` — so a stored edit recipe
    (enhance, crop, safeguarding blur) must be materialised here or a card
    silently renders the untouched original. Best-effort per asset: any
    failure falls back to the plain ``to_dict()``.
    """
    out: List[dict] = []
    for a in assets:
        d = a.to_dict() if hasattr(a, "to_dict") else a
        try:
            if isinstance(d, dict) and hasattr(a, "path") and has_edit(a):
                d = dict(d)
                d["path"] = effective_image_path(a, store)
        except Exception:  # pragma: no cover - render path must never raise
            pass
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Per-club enhance memory — light, deterministic, opt-in
# --------------------------------------------------------------------------- #


def _prefs_path(store: Any) -> Path:
    base = Path(getattr(store, "db_path", "data.db")).parent
    return base / "media_edit_prefs.json"


def _load_prefs(store: Any) -> dict:
    try:
        p = _prefs_path(store)
        if p.exists():
            return json.loads(p.read_text() or "{}")
    except Exception:
        pass
    return {}


def remembered_enhance_strength(profile_id: str, store: Any) -> float:
    """The club's learned Enhance strength (0..1), defaulting to 1.0."""
    prefs = _load_prefs(store).get(profile_id or "_shared", {})
    try:
        return max(0.0, min(1.0, float(prefs.get("enhance_strength", 1.0))))
    except Exception:
        return 1.0


def record_enhance_accepted(profile_id: str, strength: float, store: Any) -> None:
    """Nudge the remembered Enhance strength toward an accepted ``strength``."""
    try:
        prefs = _load_prefs(store)
        key = profile_id or "_shared"
        cur = float(prefs.get(key, {}).get("enhance_strength", strength))
        # Exponential move toward the accepted value — stable, no surprises.
        new = round(cur * 0.7 + float(strength) * 0.3, 4)
        prefs.setdefault(key, {})["enhance_strength"] = max(0.0, min(1.0, new))
        _prefs_path(store).write_text(json.dumps(prefs, sort_keys=True))
    except Exception:  # pragma: no cover - memory is best-effort
        pass


def suggest_enhance(asset: MediaAsset, store: Any) -> EditRecipe:
    """The deterministic one-click Enhance recipe for ``asset`` (club-tuned)."""
    strength = remembered_enhance_strength(asset.profile_id or "", store)
    return enhance_auto(asset.path, strength=strength)


# The op family enhance_auto emits — the only steps the learning matcher looks at.
_ENHANCE_OP_NAMES = (
    "white_balance",
    "auto_contrast",
    "brightness",
    "shadows",
    "clarity",
    "warmth",
    "saturation",
)


def derive_enhance_strength(asset: MediaAsset, recipe: EditRecipe) -> Optional[float]:
    """The Enhance strength ``recipe`` embeds for this image, or ``None``.

    Deterministic and conservative: the recipe's enhance-family steps (other
    edits — crop, brush, filters — are ignored) must EXACTLY reproduce
    ``enhance_auto`` for this image at the estimated strength, so an unrelated
    manual edit can never teach the memory anything. The strength estimate
    inverts the linear ``clarity``/``warmth`` scaling and is then verified by
    signature against a fresh suggestion.
    """
    try:
        kept = tuple(s for s in recipe.canonical().steps if s.op in _ENHANCE_OP_NAMES)
        if not kept:
            return None
        params = {s.op: s.params for s in kept}
        if "clarity" in params:  # enhance_auto: amount = 14 * strength
            est = float(params["clarity"].get("amount", 0.0)) / 14.0
        elif "warmth" in params:  # enhance_auto: amount = 6 * strength
            est = float(params["warmth"].get("amount", 0.0)) / 6.0
        else:
            return None
        strength = max(0.0, min(1.0, est))
        if strength <= 0.0:
            return None
        cand = enhance_auto(asset.path, strength=strength)
        if cand.is_noop() or cand.signature() != EditRecipe(steps=kept).signature():
            return None
        return strength
    except Exception:
        return None


def maybe_record_enhance_accepted(asset: MediaAsset, recipe: EditRecipe, store: Any) -> Optional[float]:
    """After a recipe save: learn the club's preferred Enhance strength when the
    saved recipe embeds a (possibly scaled) Enhance suggestion. Best-effort —
    returns the recorded strength, or ``None`` when the recipe is unrelated."""
    strength = derive_enhance_strength(asset, recipe)
    if strength is None:
        return None
    record_enhance_accepted(asset.profile_id or "", strength, store)
    return strength


# --------------------------------------------------------------------------- #
# Derived-asset exports (saved as new draft assets — approval-first)
# --------------------------------------------------------------------------- #


def _new_blob_path(store: Any, profile_id: str, stem: str, ext: str) -> Path:
    base = Path(getattr(store, "uploads_dir", "uploads")) / (profile_id or "_shared")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{stem}_{uuid.uuid4().hex[:10]}{ext}"


def _ring_colour_for(profile_id: str) -> str:
    """The club's resolved brand primary for the avatar ring. When no profile
    resolves, fall back to neutral white — never an invented brand colour."""
    try:
        from mediahub.web.club_profile import load_profile

        prof = load_profile(profile_id) if profile_id else None
        if prof is not None:
            kit = prof.get_brand_kit()
            colour = str(getattr(kit, "primary_colour", "") or "").strip()
            if colour:
                return colour
    except Exception:
        pass
    return "#ffffff"


def _draw_brand_ring(img: Any, colour: str) -> Any:
    """Draw a circular ring in ``colour`` around the (already shape-cropped)
    avatar. Best-effort: an unparseable colour leaves the image unchanged."""
    from PIL import ImageDraw

    rgba = img.convert("RGBA")
    w, h = rgba.size
    stroke = max(4, round(min(w, h) * 0.045))
    inset = stroke // 2 + 1
    try:
        d = ImageDraw.Draw(rgba)
        d.ellipse((inset, inset, w - 1 - inset, h - 1 - inset), outline=colour, width=stroke)
    except (ValueError, TypeError):
        return img
    return rgba


def export_profile_picture(
    asset: MediaAsset, store: Any, *, preset: str = "avatar_circle"
) -> MediaAsset:
    """Render a profile-picture crop of ``asset`` and save it as a new draft asset."""
    recipe = profile_picture_recipe(preset)
    img = load_image(effective_image_path(asset, store))
    # The preset's exact square resize would distort a non-square source, so
    # prepend a centred square crop (with_op sorts it before the resize).
    w, h = img.size
    if w != h and w > 0 and h > 0:
        side = min(w, h)
        recipe = recipe.with_op(
            "crop",
            {"x": (w - side) / (2 * w), "y": (h - side) / (2 * h), "w": side / w, "h": side / h},
        )
    out_img = recipe.apply(img)
    if PROFILE_PRESETS.get(preset, {}).get("ring"):
        out_img = _draw_brand_ring(out_img, _ring_colour_for(asset.profile_id or ""))
    data, mime = encode_image(out_img, "PNG")  # shape crop carries alpha → PNG
    path = _new_blob_path(store, asset.profile_id or "", "profilepic", ".png")
    path.write_bytes(data)
    new = MediaAsset(
        id="",
        filename=path.name,
        path=str(path),
        type=asset.type if asset.type in ("athlete_headshot", "team_photo") else "other",
        description_raw=f"Profile picture ({preset}) from {asset.filename}",
        profile_id=asset.profile_id,
        width=out_img.width,
        height=out_img.height,
        orientation="square",
        permission_status=asset.permission_status,
        approval_status="draft",
        safe_for_minors=asset.safe_for_minors,
        tags=["profile-picture", preset],
    )
    return store.save(new)


def create_collage(
    asset_ids: Sequence[str],
    store: Any,
    *,
    profile_id: str,
    layout: str = "grid_2x2",
    width: int = 1080,
    height: int = 1080,
    gap: int = 12,
    background: str = "#0b0d12",
    corner: int = 0,
) -> Optional[MediaAsset]:
    """Compose the given assets into a photo collage saved as a new draft asset.

    Reads each source's *effective* (edited) image, so a collage inherits any
    per-photo edits. Returns ``None`` when fewer than two usable photos resolve.
    """
    paths: List[str] = []
    safe = True
    for aid in asset_ids:
        a = store.get(aid)
        if not a or a.profile_id != profile_id:
            continue
        paths.append(effective_image_path(a, store))
        safe = safe and bool(getattr(a, "safe_for_minors", True))
        if len(paths) >= 9:
            break
    if len(paths) < 2:
        return None
    collage = compose_grid(
        paths,
        layout=layout,
        width=width,
        height=height,
        gap=gap,
        background=background,
        corner=corner,
    )
    data, _mime = encode_image(collage, "JPEG")
    path = _new_blob_path(store, profile_id, "collage", ".jpg")
    path.write_bytes(data)
    new = MediaAsset(
        id="",
        filename=path.name,
        path=str(path),
        type="other",
        description_raw=f"Photo collage ({layout}) of {len(paths)} photos",
        profile_id=profile_id,
        width=collage.width,
        height=collage.height,
        orientation="square"
        if collage.width == collage.height
        else ("portrait" if collage.height > collage.width else "landscape"),
        permission_status="internal_only",
        approval_status="draft",
        safe_for_minors=safe,
        tags=["collage", layout],
    )
    return store.save(new)


__all__ = [
    "recipe_for_asset",
    "has_edit",
    "save_recipe",
    "clear_recipe",
    "materialize_edit",
    "edited_bytes",
    "effective_image_path",
    "remembered_enhance_strength",
    "record_enhance_accepted",
    "suggest_enhance",
    "derive_enhance_strength",
    "maybe_record_enhance_accepted",
    "export_profile_picture",
    "create_collage",
]
