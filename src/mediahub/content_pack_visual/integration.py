"""Glue between content_pack output and graphic_renderer.

Public API
----------
- ``visuals_dir_for_run(run_id) -> Path``
- ``persist_visual(visual: GeneratedVisual, run_id, brief) -> Path`` — writes
   ``runs_v4/<run_id>/visuals/<visual_id>.json`` next to the PNG so we have a
   round-trippable record.
- ``create_visual_for_item(item, brand_kit, *, profile_id, run_id, formats=None)
   -> dict`` — runs the full pipeline (evaluate → brief → render) for one item
   and returns ``{ visuals: [...], brief: {...}, evaluation: {...} }``.
- ``attach_visuals_to_pack(pack, brand_kit, run_id, profile_id, *, only_buckets,
   only_safe=True) -> pack`` — mutates the pack in place; only items in
   ``only_buckets`` are processed.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path
from typing import Any, Iterable, Optional

_HEX_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def _sanitise_hex(value) -> str:
    """Return ``value`` if it is a 3/6-digit CSS hex colour, else ``""``.

    Guards the UI 1.18 accent override: only a real hex colour reaches the
    BrandKit / brief palette, so a junk value can never slip a ``;``/``}`` into
    the injected ``:root{}`` CSS or bypass the brand-locked swatch contract.
    """
    s = str(value or "").strip()
    return s if _HEX_RE.match(s) else ""


# ---------------------------------------------------------------------------
# Disk layout helpers
# ---------------------------------------------------------------------------


def _runs_dir() -> Path:
    """Resolve RUNS_DIR. Must match `web.web.RUNS_DIR` exactly, otherwise the
    /api/visual/<id>/png endpoint can't find PNGs written by this module.

    Resolution order (matches src/mediahub/web/web.py):
      1. RUNS_DIR env var (production / persistent disk)
      2. DATA_DIR env var → DATA_DIR/runs_v4
      3. Local dev default: src/mediahub/runs_v4 (same as DATA_DIR=src/mediahub)
    """
    env = os.environ.get("RUNS_DIR")
    if env:
        return Path(env)
    data_env = os.environ.get("DATA_DIR")
    if data_env:
        return Path(data_env) / "runs_v4"
    # Local-dev default — same _SRC_ROOT logic as web.py:
    # this file is at src/mediahub/content_pack_visual/integration.py
    # so parents[1] = src/mediahub/.
    return Path(__file__).resolve().parents[1] / "runs_v4"


def visuals_dir_for_run(run_id: str) -> Path:
    p = _runs_dir() / run_id / "visuals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def briefs_dir_for_run(run_id: str) -> Path:
    p = _runs_dir() / run_id / "briefs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def persist_visual(visual, *, run_id: str, brief=None) -> Path:
    """Write a JSON sidecar next to the PNG so we can list/edit later.

    The PNGs for a brief are written by ``render_all_formats`` into a single
    directory keyed by ``brief.id``. We persist *one* sidecar in that same
    directory so the sidecar + PNG live side-by-side. The sidecar payload
    enumerates every per-format visual id in ``visual_ids`` so the API can
    locate the right PNG by visual id.
    """
    brief_id = getattr(brief, "id", None) or getattr(visual, "brief_id", None) or visual.id
    vdir = visuals_dir_for_run(run_id) / brief_id
    vdir.mkdir(parents=True, exist_ok=True)
    sidecar = vdir / "visual.json"
    payload = visual.to_dict() if hasattr(visual, "to_dict") else dict(visual)
    if brief is not None and hasattr(brief, "to_dict"):
        payload["brief"] = brief.to_dict()
    # If a sidecar already exists (multi-format render), merge id + format mapping.
    if sidecar.exists():
        try:
            existing = json.loads(sidecar.read_text())
            ids_map = existing.get("visual_ids") or {}
        except Exception:
            ids_map = {}
    else:
        ids_map = {}
    fmt_name = payload.get("format_name") or payload.get("format") or "feed_portrait"
    ids_map[payload.get("id", visual.id)] = fmt_name
    payload["visual_ids"] = ids_map
    sidecar.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Governance (1.23): stamp an honest provenance manifest beside the PNG —
    # what made this card, from what, when. A result card is a deterministic
    # composite of real photography (not an AI image); only the caption and
    # creative direction may be AI-assisted, and the manifest says so. Strictly
    # best-effort: a provenance hiccup never sinks the persist.
    try:
        from mediahub.governance import provenance as _prov

        fp = getattr(visual, "file_path", None)
        if fp:
            _prov.write_sidecar(fp, _prov.build_card_manifest(visual, brief=brief))
    except Exception:
        pass

    return sidecar


# ---------------------------------------------------------------------------
# Per-item pipeline
# ---------------------------------------------------------------------------


def _flat_post_angle(item: dict) -> str:
    return (
        item.get("post_angle")
        or (item.get("achievement") or {}).get("post_angle")
        or "recap_mention"
    )


def _meet_name(item: dict, run_data: Optional[dict] = None) -> str:
    if item.get("meet_name"):
        return item["meet_name"]
    if run_data:
        m = run_data.get("meet") or {}
        return m.get("name") or m.get("title") or run_data.get("meet_name") or ""
    return ""


def _safe_for_post(item: dict) -> bool:
    s2p = item.get("safe_to_post") or {}
    if isinstance(s2p, dict):
        return s2p.get("level") == "safe"
    return False


def _resolve_asset_paths(
    evaluation,
    media_assets,
    brand_kit,
    *,
    forced_hero_asset_id=None,
    forced_bg_asset_id=None,
) -> tuple:
    """Resolve (athlete, venue, logo, bg_photo) paths for a render.

    Shared by the single-render pipeline and the Tier B candidate pool so a
    pool candidate uses exactly the photos the single path would. The
    automatic scorer's matches are the default; a user-forced hero/background
    asset id always wins; the brand-kit logo is the logo fallback.
    """
    athlete_path = None
    venue_path = None
    logo_path = None
    if hasattr(evaluation, "matched") and evaluation.matched:
        for role, scored in evaluation.matched.items():
            if not scored:
                continue
            top = scored[0]
            asset = (top.get("asset") if isinstance(top, dict) else None) or {}
            fp = asset.get("path") or asset.get("file_path")
            if not fp:
                continue
            if role.startswith("hero") and not athlete_path:
                athlete_path = fp
            elif role == "venue" and not venue_path:
                venue_path = fp
            elif role == "logo" and not logo_path and asset.get("id") != "_brand_logo_":
                logo_path = fp

    # User-chosen hero photo: when the caller forces a specific asset id, it
    # wins over the automatic scorer so the user controls exactly which photo
    # lands on this graphic.
    if forced_hero_asset_id:
        for a in media_assets or []:
            ad = a if isinstance(a, dict) else (a.to_dict() if hasattr(a, "to_dict") else {})
            if str(ad.get("id")) == str(forced_hero_asset_id):
                fp = ad.get("path") or ad.get("file_path")
                if fp:
                    athlete_path = fp
                break

    # User-chosen BACKGROUND photo (caption-led graphics): the photo fills the
    # canvas behind the text rather than being cut out as a hero.
    bg_photo_path = None
    if forced_bg_asset_id:
        for a in media_assets or []:
            ad = a if isinstance(a, dict) else (a.to_dict() if hasattr(a, "to_dict") else {})
            if str(ad.get("id")) == str(forced_bg_asset_id):
                bg_photo_path = ad.get("path") or ad.get("file_path")
                break

    # Fallback: pull the logo straight from the brand kit if the media-library
    # match didn't supply one. This is the path saved by the upload flow at
    # /upload/configure (brand_kit_upload.save_logo_bytes).
    if not logo_path:
        bk_logo = getattr(brand_kit, "logo_path", None)
        if bk_logo:
            try:
                if Path(bk_logo).exists():
                    logo_path = str(bk_logo)
            except Exception:
                pass
    return athlete_path, venue_path, logo_path, bg_photo_path


def _item_athlete_name(item: dict) -> str:
    ach = item.get("achievement") or {}
    return str(
        item.get("swimmer_name")
        or ach.get("swimmer_name")
        or item.get("athlete_name")
        or ach.get("athlete_name")
        or ""
    ).strip()


def _asset_as_dict(a) -> dict:
    if isinstance(a, dict):
        return a
    return a.to_dict() if hasattr(a, "to_dict") else {}


def _photo_identity_note(
    item: dict,
    evaluation,
    media_assets,
    forced_hero_asset_id=None,
) -> Optional[str]:
    """STILLS-9: flag an unverified face landing on a named card.

    When the card names an athlete and the hero photo about to render carries
    no verified link to that athlete (no matching ``linked_athlete_ids`` /
    ``linked_athlete_names``), return a reviewer-facing note for the visual's
    safety_notes. A description mention is NOT verification — only an explicit
    athlete link is. Returns None when there's no named subject, no hero
    photo, or the link checks out.
    """
    name = _item_athlete_name(item)
    if not name:
        return None
    ach = item.get("achievement") or {}
    subject_id = str(
        item.get("swimmer_id") or ach.get("swimmer_id") or item.get("athlete_id") or ""
    ).strip()

    hero: Optional[dict] = None
    if forced_hero_asset_id:
        for a in media_assets or []:
            ad = _asset_as_dict(a)
            if str(ad.get("id")) == str(forced_hero_asset_id):
                hero = ad
                break
    elif hasattr(evaluation, "matched") and evaluation.matched:
        for role, scored in evaluation.matched.items():
            if role.startswith("hero") and scored:
                top = scored[0]
                hero = (top.get("asset") if isinstance(top, dict) else None) or None
                break
    if not hero:
        return None

    ids = [str(x) for x in (hero.get("linked_athlete_ids") or [])]
    names = [str(n).lower() for n in (hero.get("linked_athlete_names") or [])]
    needle = name.lower()
    verified = bool(subject_id and subject_id in ids) or (
        needle in names or any(needle in n or n in needle for n in names)
    )
    if verified:
        return None
    return f"photo identity unverified — check it's really {name}"


def _record_asset_usage(visuals: list[dict], *, profile_id: str, store=None) -> int:
    """PHOTOS-5: persist which visuals each source asset ended up in.

    Appends every rendered visual id onto its source assets' ``used_in`` so
    the selector's reuse-penalty axis finally has data — the same photo stops
    landing on every card of a multi-PB weekend. Profile-scoped: an asset
    belonging to a different organisation is never touched, even if its id
    leaked into a brief. Returns the number of assets updated.
    """
    usage: dict[str, list[str]] = {}
    for v in visuals or []:
        vid = str(v.get("id") or "")
        if not vid:
            continue
        for aid in v.get("sourced_asset_ids") or []:
            if aid and aid != "_brand_logo_":
                usage.setdefault(str(aid), []).append(vid)
    if not usage:
        return 0
    if store is None:
        from mediahub.media_library.store import get_store

        store = get_store()
    updated = 0
    for aid, vids in usage.items():
        try:
            asset = store.get(aid)
            if asset is None:
                continue
            if profile_id and asset.profile_id and asset.profile_id != profile_id:
                continue
            merged = list(asset.used_in or [])
            fresh = [v for v in vids if v not in merged]
            if not fresh:
                continue
            store.update_fields(aid, {"used_in": merged + fresh})
            updated += 1
        except Exception:
            continue
    return updated


def _dhash_by_asset_id(media_assets) -> dict[str, str]:
    """Index asset id → ingest dHash (burst-family key) for pack threading."""
    out: dict[str, str] = {}
    for a in media_assets or []:
        ad = _asset_as_dict(a)
        aid = str(ad.get("id") or "")
        meta = ad.get("media_meta")
        q = meta.get("quality") if isinstance(meta, dict) else None
        dh = str(q.get("dhash") or "") if isinstance(q, dict) else ""
        if aid and dh:
            out[aid] = dh
    return out


def create_visual_for_item(
    item: dict,
    brand_kit,
    *,
    profile_id: str,
    run_id: str,
    voice_profile=None,
    formats: Optional[list[str]] = None,
    media_assets: Optional[list[dict]] = None,
    sponsor_name: str = "",
    sponsor_logo_path: Optional[str] = None,
    watermark_text: str = "",
    variation_seed: Optional[int] = None,
    variation_profile=None,
    use_ai_director: bool = False,
    recent_signatures: Optional[list[str]] = None,
    recent_hooks: Optional[list[str]] = None,
    allowed_families: Optional[list[str]] = None,
    forced_hero_asset_id: Optional[str] = None,
    forced_bg_asset_id: Optional[str] = None,
    design_spec=None,
    user_overrides: Optional[dict] = None,
    recent_asset_families: Optional[list[str]] = None,
) -> dict:
    """Full pipeline for one content item. Returns a dict of:
        { brief, evaluation, visuals (list of dicts with file_path), errors }

    The caller normally writes the returned ``visuals`` list back onto the item.

    ``recent_asset_families``: dHash hex strings of photos already used earlier
    in this pack (threaded by ``attach_visuals_to_pack`` the same way
    ``recent_signatures`` is) — the selector drops near-frames of them so one
    pack never features two shots from the same burst.

    ``design_spec``: a validated ``DesignSpec`` to apply onto the brief (the
    regenerate-variants worker pre-computes distinct specs in one batch call
    and pins one per variant). Applied via ``generator.apply_design_spec`` —
    the same mapping the candidate pool uses.

    ``user_overrides`` (UI 1.18 inspector): explicit human tweaks layered on top
    of the AI-directed brief, never AI-chosen and applied deterministically:
      * ``accent``       — a brand-kit hex used as the card's accent colour
                           (rendered via a BrandKit copy so the existing
                           APCA legibility gate still runs);
      * ``photo_pos``    — a CSS ``object-position`` manual crop;
      * ``hide_sponsor`` — drop the sponsor strip for this render.
    Omitted / empty keys leave the automatic behaviour byte-identical.
    """
    out: dict[str, Any] = {"errors": []}
    overrides = user_overrides or {}

    # 1. Requirements evaluation
    try:
        from mediahub.media_requirements.evaluator import evaluate
        from mediahub.media_library.models import MediaAsset

        # Accept either a list of MediaAsset objects or list of dicts
        library = []
        for a in media_assets or []:
            if isinstance(a, MediaAsset):
                library.append(a)
            elif isinstance(a, dict):
                try:
                    library.append(MediaAsset.from_dict(a))
                except Exception:
                    pass
        _exclude_photos = False
        try:
            from mediahub.compliance.child_policy import exclude_athlete_photos_for_item
            from mediahub.web.club_profile import load_profile as _cp_load_profile

            _exclude_photos = exclude_athlete_photos_for_item(
                _cp_load_profile(profile_id) if profile_id else None, item
            )
        except Exception:
            pass
        evaluation = evaluate(
            item,
            library_assets=library,
            profile_logo_present=bool(getattr(brand_kit, "logo_svg", None)),
            exclude_athlete_photos=_exclude_photos,
            run_id=run_id,
            exclude_asset_families=recent_asset_families,
        )
        out["evaluation"] = (
            evaluation.to_dict() if hasattr(evaluation, "to_dict") else dict(evaluation.__dict__)
        )
    except Exception as e:
        out["errors"].append(f"evaluation_failed: {e}")
        traceback.print_exc()
        return out

    if str(getattr(evaluation, "status", "")).lower() == "skip_low_confidence":
        out["skipped"] = "low_confidence"
        return out

    # 2. Creative brief
    try:
        from mediahub.creative_brief.generator import generate as gen_brief

        brief = gen_brief(
            item,
            evaluation,
            brand_kit,
            voice_profile=voice_profile,
            profile_id=profile_id,
            meet_name=_meet_name(item),
            venue_name=item.get("venue_name") or "",
            sponsor={"name": sponsor_name} if sponsor_name else None,
            variation_seed=variation_seed,
            variation_profile=variation_profile,
            use_ai_director=use_ai_director,
            recent_signatures=recent_signatures,
            recent_hooks=recent_hooks,
            allowed_families=allowed_families,
        )
        if design_spec is not None:
            from mediahub.creative_brief.generator import apply_design_spec

            apply_design_spec(brief, design_spec)
        # UI 1.18 — manual accent swatch. Re-point the card's accent at the
        # chosen BRAND colour. Done on a BrandKit copy (not the shared object)
        # and on the brief palette so the render's role resolver still applies
        # the APCA legibility gate — an off-brand or illegible pick is repaired,
        # never blindly painted.
        _accent_override = _sanitise_hex(overrides.get("accent"))
        if _accent_override:
            try:
                import dataclasses as _dc

                brand_kit = _dc.replace(brand_kit, accent_colour=_accent_override)
            except Exception:
                pass
            try:
                brief.palette = {**(brief.palette or {}), "accent": _accent_override}
            except Exception:
                pass
        out["brief"] = brief.to_dict()
    except Exception as e:
        out["errors"].append(f"brief_failed: {e}")
        traceback.print_exc()
        return out

    # Persist brief
    try:
        bdir = briefs_dir_for_run(run_id)
        (bdir / f"{brief.id}.json").write_text(
            json.dumps(brief.to_dict(), indent=2, default=str), encoding="utf-8"
        )
    except Exception as e:
        out["errors"].append(f"brief_persist_failed: {e}")

    # 3. Resolve photo/logo paths from matched assets + user choices
    athlete_path, venue_path, logo_path, bg_photo_path = _resolve_asset_paths(
        evaluation,
        media_assets,
        brand_kit,
        forced_hero_asset_id=forced_hero_asset_id,
        forced_bg_asset_id=forced_bg_asset_id,
    )

    # 4. Render variants
    try:
        from mediahub.graphic_renderer.variants import render_all_formats

        out_root = visuals_dir_for_run(run_id)
        # Each visual gets its own dir so multi-format files stay grouped
        # We'll let render_all_formats place files inside out_root/<brief.id>/
        per_brief_dir = out_root / brief.id
        per_brief_dir.mkdir(parents=True, exist_ok=True)

        # Honour the seed-3 "text-led / no photo" treatment by skipping the
        # athlete cutout entirely. Same treatment for any brief whose
        # photo_treatment is "no-photo" (set by the AI director or a
        # random variation profile).
        skip_cutout_for_render = variation_seed == 3 or (
            getattr(brief, "photo_treatment", "") == "no-photo"
        )
        # A user-chosen photo always renders — never let a no-photo treatment
        # silently drop the photo they explicitly picked for this graphic.
        if forced_hero_asset_id and athlete_path:
            skip_cutout_for_render = False
        athlete_for_render = None if skip_cutout_for_render else athlete_path

        # STILLS-9: an unverified face about to render beside the subject's
        # name gets a reviewer-facing safety note (rides brief.safety_notes →
        # GeneratedVisual.safety_notes → the review panel's trace).
        if athlete_for_render:
            _identity_note = _photo_identity_note(
                item, evaluation, media_assets, forced_hero_asset_id
            )
            if _identity_note:
                try:
                    brief.safety_notes = list(brief.safety_notes or []) + [_identity_note]
                except Exception:
                    pass

        # UI 1.18 — element toggle: drop the sponsor strip for this render.
        _hide_sponsor = bool(overrides.get("hide_sponsor"))
        _render_sponsor_name = "" if _hide_sponsor else sponsor_name
        _render_sponsor_logo = None if _hide_sponsor else sponsor_logo_path
        # UI 1.18 — manual crop (validated to a safe object-position downstream).
        _photo_pos = str(overrides.get("photo_pos") or "")

        results = render_all_formats(
            brief,
            output_dir=per_brief_dir,
            formats=formats,
            athlete_path=athlete_for_render,
            venue_path=venue_path,
            logo_path=logo_path,
            bg_photo_path=bg_photo_path,
            brand_kit=brand_kit,
            sponsor_name=_render_sponsor_name,
            sponsor_logo_path=_render_sponsor_logo,
            watermark_text=watermark_text,
            photo_pos_override=_photo_pos,
        )
    except Exception as e:
        out["errors"].append(f"render_failed: {e}")
        traceback.print_exc()
        return out

    # Persist each visual + collect summary
    visuals_summary: list[dict] = []
    for r in results:
        try:
            persist_visual(r.visual, run_id=run_id, brief=brief)
        except Exception as e:
            out["errors"].append(f"persist_failed_{r.visual.id}: {e}")
        visuals_summary.append(
            {
                "id": r.visual.id,
                "format_name": r.visual.format_name,
                "width": r.visual.width,
                "height": r.visual.height,
                "file_path": r.visual.file_path,
                "layout_template": r.visual.layout_template,
                "confidence_label": r.visual.confidence_label,
                "why_this_design": r.visual.why_this_design,
                "safety_notes": r.visual.safety_notes,
                "sourced_asset_ids": r.visual.sourced_asset_ids,
            }
        )

    # PHOTOS-5: remember where each source photo landed so the reuse-penalty
    # axis works across the pack and across weeks. Best-effort — a bookkeeping
    # hiccup never sinks a successful render.
    try:
        _record_asset_usage(visuals_summary, profile_id=profile_id)
    except Exception:
        pass

    out["visuals"] = visuals_summary
    return out


# ---------------------------------------------------------------------------
# Tier B — candidate pool: emit N specs, render, compliance-check, rank
# ---------------------------------------------------------------------------

POOL_DEFAULT_N = 5
POOL_MAX_N = 6
# One cheap format per candidate keeps the pool render ~the cost of the
# existing 3-variant fan-out; the chosen candidate re-renders all formats
# through the normal path.
POOL_FORMATS = ("feed_portrait",)


def _archetype_sponsor_slot(name: str) -> bool:
    """True when the archetype template carries a ``{{SPONSOR_BLOCK}}`` slot."""
    try:
        from mediahub.graphic_renderer.archetypes import V2_DIR

        return "{{SPONSOR_BLOCK}}" in (V2_DIR / f"{name}.html").read_text(encoding="utf-8")
    except Exception:
        return False


def _candidate_compliance(brief, brand_kit, spec, *, lockups, sponsor_name: str) -> dict:
    """The deterministic, explainable brand-compliance verdict for one candidate.

    APCA legibility over the exact ``--mh-*`` set the render paints
    (``resolved_role_vars_for_brief`` — including the gated colour-role
    assignment and medal tint), plus the logo-lockup fit for the resolved
    ground and, when a sponsor is in play, whether this archetype actually has
    a sponsor slot. Everything here is evidence, never a guess.
    """
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief
    from mediahub.quality.compliance import check_roles

    roles = resolved_role_vars_for_brief(brief, brand_kit)
    report = check_roles(roles)
    out: dict[str, Any] = {
        "score": report.score,
        "passes": report.passes,
        "explain": report.explain(),
        "pairs": {k: round(v, 1) for k, v in report.pairs.items()},
    }
    if lockups:
        try:
            from mediahub.theming.logo_chip import select_logo_lockup

            choice = select_logo_lockup(
                lockups, roles.get("--mh-primary", ""), prefer_form=spec.logo_lockup
            )
            if choice is not None:
                out["logo"] = {
                    "form": choice.lockup.get("form"),
                    "mode": choice.mode,
                    "reasoning": choice.reasoning,
                }
        except Exception:
            pass
    if sponsor_name:
        out["sponsor_slot_present"] = _archetype_sponsor_slot(brief.layout_template)
    return out


def create_candidate_pool_for_item(
    item: dict,
    brand_kit,
    *,
    profile_id: str,
    run_id: str,
    n: int = POOL_DEFAULT_N,
    voice_profile=None,
    formats: Optional[list[str]] = None,
    media_assets: Optional[list[dict]] = None,
    sponsor_name: str = "",
    sponsor_logo_path: Optional[str] = None,
    recent_signatures: Optional[list[str]] = None,
    forced_hero_asset_id: Optional[str] = None,
) -> dict:
    """Tier B §5.5: emit N candidate DesignSpecs, render the pool, score each
    with the deterministic brand-compliance gate, and return a ranked shortlist.

    The specs come from ONE batch director call (``ai_design_specs``) when a
    provider is configured; the deterministic Tier A archetype walk fills any
    gap (and the whole pool when no provider exists — the honest floor, never
    a fabricated card). All candidates share the card's stable variation seed,
    so they differ by *direction* (archetype, hook, emphasis, colour roles),
    not by accidental noise.

    Returns::

        { "candidates": [ {rank, archetype, ai_directed, spec, brief,
                           visuals, compliance}, ... ],   # rank 1 = best
          "pool_metrics": {archetype_diversity, perceptual_spread, n},
          "evaluation": {...}, "errors": [...] }
    """
    out: dict[str, Any] = {"errors": [], "candidates": []}

    from mediahub.graphic_renderer import archetypes as _arch

    names = _arch.list_archetypes() if _arch.is_enabled() else []
    if not names:
        out["errors"].append("gen_v2_disabled_or_no_archetypes")
        return out
    n = max(2, min(int(n or POOL_DEFAULT_N), POOL_MAX_N, len(names)))

    # 1. Requirements evaluation (once for the whole pool)
    try:
        from mediahub.media_requirements.evaluator import evaluate
        from mediahub.media_library.models import MediaAsset

        library = []
        for a in media_assets or []:
            if isinstance(a, MediaAsset):
                library.append(a)
            elif isinstance(a, dict):
                try:
                    library.append(MediaAsset.from_dict(a))
                except Exception:
                    pass
        _exclude_photos = False
        try:
            from mediahub.compliance.child_policy import exclude_athlete_photos_for_item
            from mediahub.web.club_profile import load_profile as _cp_load_profile

            _exclude_photos = exclude_athlete_photos_for_item(
                _cp_load_profile(profile_id) if profile_id else None, item
            )
        except Exception:
            pass
        evaluation = evaluate(
            item,
            library_assets=library,
            profile_logo_present=bool(getattr(brand_kit, "logo_svg", None)),
            exclude_athlete_photos=_exclude_photos,
            run_id=run_id,
        )
        out["evaluation"] = (
            evaluation.to_dict() if hasattr(evaluation, "to_dict") else dict(evaluation.__dict__)
        )
    except Exception as e:
        out["errors"].append(f"evaluation_failed: {e}")
        traceback.print_exc()
        return out
    if str(getattr(evaluation, "status", "")).lower() == "skip_low_confidence":
        out["skipped"] = "low_confidence"
        return out

    # 2. N candidate specs: one batch director call + the deterministic floor
    from mediahub.creative_brief.design_spec import normalise
    from mediahub.creative_brief.generator import (
        apply_design_spec,
        auto_variation_seed_for,
        generate as gen_brief,
    )

    angle = _flat_post_angle(item)
    recent_archetypes = [s.split("|", 1)[0] for s in (recent_signatures or []) if s]
    token_roles = list(_arch.TOKEN_ROLES)

    ai_specs = None
    try:
        from mediahub.creative_brief.ai_director import ai_design_specs

        ai_specs = ai_design_specs(
            content_item=item,
            brand_kit=brand_kit,
            archetypes=names,
            token_roles=token_roles,
            angle=angle,
            recent_archetypes=recent_archetypes,
            count=n,
        )
    except Exception as e:
        out["errors"].append(f"director_failed: {e}")
        ai_specs = None

    specs: list[tuple[Any, bool]] = [(s, True) for s in (ai_specs or [])[:n]]
    card_key = str(item.get("id") or item.get("swim_id") or "")
    base_seed = auto_variation_seed_for(card_key or None)
    used = [s.archetype for s, _ in specs]
    while len(specs) < n:
        arch_name = _arch.pick_archetype_avoiding(base_seed, used + recent_archetypes)
        if arch_name is None:
            break
        specs.append(
            (normalise({"archetype": arch_name}, archetypes=names, token_roles=token_roles), False)
        )
        used.append(arch_name)

    # Logo lockups resolve once per pool (they depend on brand, not candidate).
    lockups: list[dict] = []
    try:
        from mediahub.brand.design_tokens import resolve_design_tokens

        lockups = resolve_design_tokens(profile_id, brand_kit=brand_kit).get("logo_lockups", [])
    except Exception:
        lockups = []

    # 3. Brief + render + compliance per candidate
    from mediahub.graphic_renderer.variants import render_all_formats
    from mediahub.graphic_renderer.render import render_pool_session

    athlete_path, venue_path, logo_path, bg_photo_path = _resolve_asset_paths(
        evaluation, media_assets, brand_kit, forced_hero_asset_id=forced_hero_asset_id
    )
    pool_formats = list(formats) if formats else list(POOL_FORMATS)
    candidates: list[dict] = []
    png_paths: list[str] = []
    # Render the whole candidate pool against ONE warm Chromium pool (G1.23):
    # every candidate × format reuses warm browsers instead of relaunching
    # Chromium per render, which dominates the wall-clock of a batch render.
    with render_pool_session():
        for idx, (spec, ai_directed) in enumerate(specs):
            try:
                # variation_seed=0 keeps the identity palette: Tier B candidates
                # differ by DIRECTION (the spec's archetype / colour roles / hook),
                # never by the v1 seed-permutation, which can rotate the brand
                # primary into the accent slot and fail the compliance gate.
                brief = gen_brief(
                    item,
                    evaluation,
                    brand_kit,
                    voice_profile=voice_profile,
                    profile_id=profile_id,
                    meet_name=_meet_name(item),
                    venue_name=item.get("venue_name") or "",
                    sponsor={"name": sponsor_name} if sponsor_name else None,
                    variation_seed=0,
                    use_ai_director=False,
                )
                apply_design_spec(brief, spec)
                if not ai_directed:
                    brief.ai_directed = False
                try:
                    (briefs_dir_for_run(run_id) / f"{brief.id}.json").write_text(
                        json.dumps(brief.to_dict(), indent=2, default=str), encoding="utf-8"
                    )
                except Exception as e:
                    out["errors"].append(f"brief_persist_failed_{idx}: {e}")

                per_brief_dir = visuals_dir_for_run(run_id) / brief.id
                per_brief_dir.mkdir(parents=True, exist_ok=True)
                skip_photo = brief.photo_treatment == "no-photo" and not forced_hero_asset_id
                results = render_all_formats(
                    brief,
                    output_dir=per_brief_dir,
                    formats=pool_formats,
                    athlete_path=None if skip_photo else athlete_path,
                    venue_path=venue_path,
                    logo_path=logo_path,
                    bg_photo_path=bg_photo_path,
                    brand_kit=brand_kit,
                    sponsor_name=sponsor_name,
                    sponsor_logo_path=sponsor_logo_path,
                )
                visuals_summary: list[dict] = []
                for r in results:
                    try:
                        persist_visual(r.visual, run_id=run_id, brief=brief)
                    except Exception as e:
                        out["errors"].append(f"persist_failed_{r.visual.id}: {e}")
                    visuals_summary.append(
                        {
                            "id": r.visual.id,
                            "format_name": r.visual.format_name,
                            "width": r.visual.width,
                            "height": r.visual.height,
                            "file_path": r.visual.file_path,
                            "layout_template": r.visual.layout_template,
                            "confidence_label": r.visual.confidence_label,
                            "why_this_design": r.visual.why_this_design,
                            "safety_notes": r.visual.safety_notes,
                            "sourced_asset_ids": r.visual.sourced_asset_ids,
                        }
                    )
                    if r.visual.file_path:
                        png_paths.append(r.visual.file_path)
                candidates.append(
                    {
                        "archetype": spec.archetype,
                        "ai_directed": ai_directed,
                        "spec": spec.to_dict(),
                        "brief": brief.to_dict(),
                        "visuals": visuals_summary,
                        "compliance": _candidate_compliance(
                            brief, brand_kit, spec, lockups=lockups, sponsor_name=sponsor_name
                        ),
                    }
                )
            except Exception as e:
                out["errors"].append(f"candidate_failed_{idx}: {e}")
                traceback.print_exc()

    # 4. Rank: legibility first (gate pass, then score), stable on entry order.
    order = sorted(
        range(len(candidates)),
        key=lambda i: (
            not candidates[i]["compliance"]["passes"],
            -candidates[i]["compliance"]["score"],
            i,
        ),
    )
    out["candidates"] = [candidates[i] for i in order]
    for rank, cand in enumerate(out["candidates"], start=1):
        cand["rank"] = rank

    # 5. Pool metrics (§8C success measures) — deterministic, best-effort.
    metrics: dict[str, Any] = {"n": len(out["candidates"])}
    try:
        from mediahub.quality.variant_metrics import archetype_diversity, perceptual_spread

        metrics["archetype_diversity"] = archetype_diversity([c["spec"] for c in out["candidates"]])
        if len(png_paths) >= 2:
            metrics["perceptual_spread"] = perceptual_spread(png_paths)
    except Exception:
        pass
    out["pool_metrics"] = metrics
    return out


# ---------------------------------------------------------------------------
# Whole-pack overlay
# ---------------------------------------------------------------------------

DEFAULT_VISUAL_BUCKETS = (
    "main_feed",
    "stories",
    "athlete_spotlights",
    "weekend_in_numbers",
    "weekend_recap",
)


def attach_visuals_to_pack(
    pack: dict,
    brand_kit,
    *,
    run_id: str,
    profile_id: str,
    only_buckets: Iterable[str] = DEFAULT_VISUAL_BUCKETS,
    only_safe: bool = True,
    voice_profile=None,
    media_assets: Optional[list[dict]] = None,
    sponsor_name: str = "",
    formats: Optional[list[str]] = None,
    max_per_bucket: Optional[int] = None,
) -> dict:
    """Walk the pack buckets and attach a ``visuals`` list to each item.

    Each rendered brief's variation signature is threaded into the next item's
    ``recent_signatures``, so the deterministic archetype floor rotates past a
    seed collision instead of repeating a composition within the same pack —
    the same dedupe the per-card route keeps in its variation history. The
    burst families (ingest dHashes) of each item's sourced photos thread the
    same way into ``recent_asset_families``, so two cards in one pack never
    carry near-identical frames from the same poolside burst.
    """
    only = set(only_buckets)
    recent_sigs: list[str] = []
    recent_fams: list[str] = []
    fam_by_asset = _dhash_by_asset_id(media_assets)
    for bucket_name, bucket in list(pack.items()):
        if bucket_name not in only:
            continue
        items = bucket if isinstance(bucket, list) else ([bucket] if bucket else [])
        rendered = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if only_safe and not _safe_for_post(item):
                continue
            if max_per_bucket and rendered >= max_per_bucket:
                break
            res = create_visual_for_item(
                item,
                brand_kit,
                profile_id=profile_id,
                run_id=run_id,
                voice_profile=voice_profile,
                media_assets=media_assets,
                sponsor_name=sponsor_name,
                formats=formats,
                recent_signatures=recent_sigs[-6:],
                recent_asset_families=recent_fams[-12:],
            )
            item["visuals"] = res.get("visuals", [])
            item["visual_brief"] = res.get("brief")
            item["visual_evaluation"] = res.get("evaluation")
            item["visual_errors"] = res.get("errors") or None
            sig = (res.get("brief") or {}).get("variation_signature")
            if sig:
                recent_sigs.append(sig)
            for v in res.get("visuals") or []:
                for aid in v.get("sourced_asset_ids") or []:
                    fam = fam_by_asset.get(str(aid))
                    if fam and fam not in recent_fams:
                        recent_fams.append(fam)
            if res.get("visuals"):
                rendered += 1
    return pack


__all__ = [
    "attach_visuals_to_pack",
    "create_visual_for_item",
    "create_candidate_pool_for_item",
    "visuals_dir_for_run",
    "briefs_dir_for_run",
    "persist_visual",
    "DEFAULT_VISUAL_BUCKETS",
    "POOL_DEFAULT_N",
    "POOL_MAX_N",
]
