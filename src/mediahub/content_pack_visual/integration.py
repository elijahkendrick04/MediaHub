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
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Disk layout helpers
# ---------------------------------------------------------------------------

def visuals_dir_for_run(run_id: str) -> Path:
    p = Path("runs_v4") / run_id / "visuals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def briefs_dir_for_run(run_id: str) -> Path:
    p = Path("runs_v4") / run_id / "briefs"
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
    variation_seed: int = 0,
) -> dict:
    """Full pipeline for one content item. Returns a dict of:
        { brief, evaluation, visuals (list of dicts with file_path), errors }

    The caller normally writes the returned ``visuals`` list back onto the item.
    """
    out: dict[str, Any] = {"errors": []}

    # 1. Requirements evaluation
    try:
        from mediahub.media_requirements.evaluator import evaluate
        from mediahub.media_library.models import MediaAsset
        # Accept either a list of MediaAsset objects or list of dicts
        library = []
        for a in (media_assets or []):
            if isinstance(a, MediaAsset):
                library.append(a)
            elif isinstance(a, dict):
                try:
                    library.append(MediaAsset.from_dict(a))
                except Exception:
                    pass
        evaluation = evaluate(
            item, library_assets=library,
            profile_logo_present=bool(getattr(brand_kit, "logo_svg", None)),
        )
        out["evaluation"] = evaluation.to_dict() if hasattr(evaluation, "to_dict") else dict(evaluation.__dict__)
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
        )
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

    # 3. Resolve athlete photo path from matched assets (if any)
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

    # 4. Render variants
    try:
        from mediahub.graphic_renderer.variants import render_all_formats
        out_root = visuals_dir_for_run(run_id)
        # Each visual gets its own dir so multi-format files stay grouped
        # We'll let render_all_formats place files inside out_root/<brief.id>/
        per_brief_dir = out_root / brief.id
        per_brief_dir.mkdir(parents=True, exist_ok=True)

        # Honour the seed-3 "text-led / no photo" treatment by skipping the
        # athlete cutout entirely.
        skip_cutout_for_render = (variation_seed == 3)
        athlete_for_render = None if skip_cutout_for_render else athlete_path

        results = render_all_formats(
            brief,
            output_dir=per_brief_dir,
            formats=formats,
            athlete_path=athlete_for_render,
            venue_path=venue_path,
            logo_path=logo_path,
            brand_kit=brand_kit,
            sponsor_name=sponsor_name,
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
        visuals_summary.append({
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
        })

    out["visuals"] = visuals_summary
    return out


# ---------------------------------------------------------------------------
# Whole-pack overlay
# ---------------------------------------------------------------------------

DEFAULT_VISUAL_BUCKETS = ("main_feed", "stories", "athlete_spotlights",
                          "weekend_in_numbers", "weekend_recap")


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
    """Walk the pack buckets and attach a ``visuals`` list to each item."""
    only = set(only_buckets)
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
                item, brand_kit,
                profile_id=profile_id, run_id=run_id,
                voice_profile=voice_profile,
                media_assets=media_assets,
                sponsor_name=sponsor_name,
                formats=formats,
            )
            item["visuals"] = res.get("visuals", [])
            item["visual_brief"] = res.get("brief")
            item["visual_evaluation"] = res.get("evaluation")
            item["visual_errors"] = res.get("errors") or None
            if res.get("visuals"):
                rendered += 1
    return pack


__all__ = [
    "attach_visuals_to_pack",
    "create_visual_for_item",
    "visuals_dir_for_run",
    "briefs_dir_for_run",
    "persist_visual",
    "DEFAULT_VISUAL_BUCKETS",
]
