#!/usr/bin/env python3
"""Seed a synthetic ``test_run`` and ``big_run`` JSON for benchmarking.

Most route benchmarks need ``run_id`` paths to resolve, but a real
upload + recognition pipeline takes 30+ seconds and depends on an LLM
key. This script writes well-formed run JSONs straight onto disk so
``/pack/test_run/grouped``, ``/audit/test_run``, ``/api/runs/test_run/cards``,
etc., all light up immediately.

Usage:
    DATA_DIR=/tmp/perf_data python scripts/perf/seed_test_run.py
"""
from __future__ import annotations
import json
import os
import random
from pathlib import Path

from mediahub.web.club_profile import ClubProfile, save_profile


def _build_card(i: int, swimmers: list[str], events: list[str],
                bands: list[str]) -> dict:
    sw = swimmers[i % len(swimmers)]
    ev = events[i % len(events)]
    band = bands[i % len(bands)]
    swim_id = f"sw_{i:03d}"
    achievement = {
        "swimmer_name": sw,
        "swimmer_id": sw.lower().replace(" ", "_"),
        "event": ev,
        "headline": f"{sw} crushes a PB in the {ev}!",
        "swim_id": swim_id,
        "card_id": swim_id,
        "time": f"1:{random.randint(0, 59):02d}.{random.randint(0, 99):02d}",
        "is_pb": True,
        "pb_delta_seconds": -round(random.uniform(0.5, 5), 2),
    }
    return {
        "achievement": achievement,
        "quality_band": band,
        "score": random.uniform(0.5, 1.0),
        "safe_to_post": {
            "level": "safe" if i % 4 != 0 else "needs_review",
            "reason": "PB validated" if i % 4 != 0 else "ambiguous",
        },
        "post_angle": "Personal best",
        "n_achievements": 1,
        "priority": i,
        "caption_only": f"{sw} smashed a PB in the {ev}.",
        "caption_with_hashtags": f"{sw} smashed a PB in the {ev}. #swim #PB",
        "caption_full_brief": f"{sw} delivered a personal-best swim in the {ev}.",
        "active_caption": {
            "headline": f"{sw} - new PB",
            "body": f"{sw} dropped time in the {ev}.",
            "cta": "Tag a teammate!",
        },
        "brand_captions": {
            "warm-club": {"headline": f"Big up {sw}!",
                          "body": f"PB time in the {ev}.",
                          "cta": "Well done!"},
            "hype":      {"headline": f"{sw.upper()} ON FIRE",
                          "body": f"NEW PB IN THE {ev.upper()}",
                          "cta": "LFG"},
            "data-led":  {"headline": f"{sw}: PB",
                          "body": f"{ev}: -{abs(achievement['pb_delta_seconds'])}s",
                          "cta": "See full splits"},
        },
        "_card_id": swim_id,
    }


def _build_run(run_id: str, n_cards: int) -> dict:
    random.seed(42 + n_cards)
    swimmers = ["Alex Smith", "Jamie Lee", "Sam Jones", "Riley Patel",
                "Casey Wong", "Morgan Davis", "Taylor Kim", "Jordan Brown",
                "Avery Chen", "Quinn Murphy"]
    events = ["50 Free", "100 Free", "200 Free", "400 Free", "50 Back",
              "100 Back", "50 Breast", "100 Breast", "50 Fly", "100 Fly",
              "200 IM", "400 IM"]
    bands = ["elite", "strong", "story", "nice"]
    ranked = [_build_card(i, swimmers, events, bands) for i in range(n_cards)]
    cards = [{
        "achievement": it["achievement"],
        "card_id": it["achievement"]["card_id"],
        "swim_id": it["achievement"]["swim_id"],
        "bucket": "queue",
        "caption": it["caption_with_hashtags"],
    } for it in ranked]
    return {
        "run_id": run_id,
        "started_at": "2026-05-19T22:00:00Z",
        "finished_at": "2026-05-19T22:00:05Z",
        "profile_id": "test_club",
        "profile_display": "Test Club",
        "file_name": "test.hy3",
        "meet": {"name": "Test Meet", "date": "2026-05-19", "venue": "Test Pool"},
        "dispatch_log": None,
        "parse_warnings": [],
        "parsed_swim_count": n_cards * 3,
        "our_swim_count": n_cards * 2,
        "other_swim_count": n_cards,
        "n_swimmers_ours": min(len(swimmers), n_cards),
        "pb_fetch_ok": min(len(swimmers), n_cards),
        "pb_fetch_failed": 0,
        "pb_fetch_errors": [],
        "detector_summary": {},
        "self_check": {},
        "standards_meta": {},
        "cards": cards,
        "trust": None,
        "ground_truth_report": None,
        "recognition_report": {"ranked_achievements": ranked},
        "recognition_error": None,
        "progress_log": [],
        "error": None,
        "pb_audit": None,
    }


def main() -> None:
    data_dir = Path(os.environ.get("DATA_DIR", "/tmp/perf_data"))
    runs_dir = data_dir / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Profile - is_ready() needs name + (voice summary OR keywords OR
    # tone_notes OR voice_examples OR guidelines).
    prof = ClubProfile(profile_id="test_club", display_name="Test Club")
    prof.org_type = "club"
    prof.country = "UK"
    prof.brand_voice_summary = "A friendly local swimming club focused on developing young swimmers."
    prof.brand_keywords = ["friendly", "community", "swim"]
    prof.tone_notes = "Warm, supportive, athlete-first. Celebrate every PB."
    prof.voice_examples = ["Massive PB for Jane today!",
                            "Big PB! Well done.",
                            "Great session."]
    save_profile(prof)

    (runs_dir / "test_run.json").write_text(
        json.dumps(_build_run("test_run", 30), indent=2, default=str)
    )
    (runs_dir / "big_run.json").write_text(
        json.dumps(_build_run("big_run", 100), indent=2, default=str)
    )
    print(f"Seeded {runs_dir}/test_run.json (30 cards)")
    print(f"Seeded {runs_dir}/big_run.json (100 cards)")


if __name__ == "__main__":
    main()
