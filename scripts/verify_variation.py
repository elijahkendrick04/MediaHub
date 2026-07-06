#!/usr/bin/env python3
"""Verification harness for regenerate variety (Gen Engine v2).

Goal
----
Prove that regenerating a graphic for ONE swim produces visibly
different output every time — with no LLM key. Under v2 the variety is
the deterministic archetype rotation: each regenerate walks the
``layouts/v2`` library past the card's recent signatures (the same
mechanism the create-graphic route persists between clicks), so
consecutive briefs land on different archetypes by construction.

This script:
  1. Builds a fixed synthetic swim (Eira Hughes, 200m Freestyle, 2:08.41 PB).
  2. Calls ``creative_brief.generator.generate()`` N times, threading each
     brief's variation_signature into the next call's ``recent_signatures``.
  3. Asserts every brief has a distinct variation_signature.
  4. Prints a per-iteration table so the human can eyeball the variety.
  5. (Optional) renders N PNGs and confirms their byte hashes differ
     when Playwright + Chromium are available.

Exit code 0 on success, non-zero on failure. Runs with NO external API
keys — the deterministic floor provides the variety; the design-spec
director layers on transparently when a key is configured.

Usage
-----
  python scripts/verify_variation.py [--render] [--count N]

  --render          Also render each brief to a PNG (slow, ~30-60s).
  --count N         Generate N briefs instead of 10.
  --output DIR      Where to write PNGs (default: $DATA_DIR/verify_variation).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Ensure we can import mediahub when running this script directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))


def _build_swim() -> dict:
    """A fixed achievement — the same swim used in test_v8_variation_seed."""
    return {
        "id": "verify-eira-200free",
        "post_angle": "confirmed_official_pb",
        "achievement": {
            "swim_id": "verify-eira-200free",
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
            "post_angle": "confirmed_official_pb",
        },
    }


def _build_brand():
    from mediahub.brand.kit import BrandKit
    return BrandKit(
        profile_id="verify",
        display_name="Test Swim Club",
        primary_colour="#A30D2D",
        secondary_colour="#101820",
        accent_colour="#FFD86E",
        short_name="TSC",
    )


def _build_eval():
    from mediahub.media_requirements.evaluator import EvaluationResult
    return EvaluationResult(
        content_item_id="verify-eira-200free",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=None,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _truncate(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _generate_briefs(count: int) -> list:
    """Build ``count`` briefs via the deterministic v2 archetype rotation."""
    from mediahub.creative_brief.generator import generate

    item = _build_swim()
    brand = _build_brand()
    ev = _build_eval()
    briefs = []
    recent_sigs: list[str] = []
    for i in range(count):
        brief = generate(
            item, ev, brand,
            profile_id="verify",
            meet_name="County Long Course Championships",
            recent_signatures=recent_sigs,
            # use_ai_director stays False: the verification's job is to
            # prove the deterministic floor produces variety on its own.
        )
        briefs.append(brief)
        recent_sigs.append(brief.variation_signature)
    return briefs


def _summarise(briefs: list) -> None:
    headers = [
        "#", "Layout", "BgStyle", "Accent", "Type", "Comp",
        "Photo", "Pal-P", "Hook",
    ]
    rows = [headers]
    for i, b in enumerate(briefs, 1):
        rows.append([
            str(i),
            b.layout_template,
            b.background_style,
            b.accent_style,
            b.typography_pair,
            b.composition,
            b.photo_treatment,
            (b.palette or {}).get("primary", "")[:7],
            _truncate(b.primary_hook, 22),
        ])
    widths = [max(len(r[c]) for r in rows) for c in range(len(headers))]
    sep = "  "
    print()
    for r in rows:
        print(sep.join(c.ljust(w) for c, w in zip(r, widths)))
    print()


def _assert_distinct(briefs: list) -> bool:
    sigs = [b.variation_signature for b in briefs]
    seen: dict[str, int] = {}
    duplicates: list[tuple[int, int]] = []
    for idx, s in enumerate(sigs, 1):
        if s in seen:
            duplicates.append((seen[s], idx))
        else:
            seen[s] = idx
    if not duplicates:
        print(f"PASS: {len(briefs)} briefs all have distinct variation signatures.")
        return True
    print(f"FAIL: {len(duplicates)} duplicate signature pairs found:")
    for a, b in duplicates:
        print(f"  briefs #{a} and #{b} both share signature: {sigs[a-1]}")
    return False


def _render_and_compare(briefs: list, output_dir: Path) -> bool:
    """Render each brief to a PNG and compare byte hashes.

    Returns False if PNGs don't differ pairwise.
    """
    try:
        from mediahub.graphic_renderer.render import render_brief
    except Exception as e:
        print(f"SKIP: graphic_renderer unavailable: {e}")
        return True
    brand = _build_brand()
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes: list[tuple[int, str, Path]] = []
    print(f"Rendering {len(briefs)} PNGs into {output_dir} (this is slow)...")
    for i, b in enumerate(briefs, 1):
        out_sub = output_dir / f"render_{i:02d}"
        out_sub.mkdir(parents=True, exist_ok=True)
        try:
            res = render_brief(
                b,
                output_dir=out_sub,
                size=(1080, 1350),
                format_name="feed_portrait",
                brand_kit=brand,
            )
        except Exception as e:
            print(f"  render #{i} failed: {e}")
            return False
        p = Path(res.visual.file_path)
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        hashes.append((i, h, p))
        print(f"  #{i:2d}  {b.layout_template:<18} {b.background_style:<10} "
              f"{b.accent_style:<10} {b.typography_pair:<14} "
              f"hash={h}  ({p.stat().st_size//1024}KB)")
    seen: dict[str, int] = {}
    dup_pairs: list[tuple[int, int]] = []
    for i, h, _ in hashes:
        if h in seen:
            dup_pairs.append((seen[h], i))
        else:
            seen[h] = i
    if dup_pairs:
        print(f"FAIL: {len(dup_pairs)} pairs of PNGs are byte-identical:")
        for a, b in dup_pairs:
            print(f"  PNG #{a} and #{b} share hash")
        return False
    print(f"PASS: all {len(hashes)} PNGs are byte-distinct.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--render", action="store_true",
                    help="Also render PNGs and compare byte hashes")
    ap.add_argument("--output", type=Path,
                    default=Path(os.environ.get("DATA_DIR")
                                 or (_REPO_ROOT / "data")) / "verify_variation")
    args = ap.parse_args()

    briefs = _generate_briefs(args.count)
    _summarise(briefs)
    ok_briefs = _assert_distinct(briefs)
    ok_pngs = True
    if args.render:
        ok_pngs = _render_and_compare(briefs, args.output)
    return 0 if (ok_briefs and ok_pngs) else 1


if __name__ == "__main__":
    sys.exit(main())
