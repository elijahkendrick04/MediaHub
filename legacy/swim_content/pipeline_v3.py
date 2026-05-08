"""
V3 pipeline orchestrator.

Glue layer that takes (uploaded HY3 file, club selection, course/date overrides,
output preference) through:

  1. Parse HY3
  2. Filter to our club
  3. Fetch PB snapshots from swimmingresults.org for our roster
  4. Load qualification standards registry
  5. Detect Claims (medals + PBs + qual hits)
  6. Group claims into ContentCards
  7. Attach evidence rows from claims onto cards
  8. Generate captions (3 voices)
  9. Rank + bucket
 10. Run self-check
 11. Hand back a Run object the Flask app can render

This module makes only ONE network call type: PB enrichment from
swimmingresults.org. Everything else is local.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .parsers_hy3 import parse_hy3_file
from .club_filter import ClubRoster, swansea_uni_roster
from .enrichment_swimmingresults import (
    fetch_roster, SwimmerPBSnapshot, DEFAULT_CACHE_DIR,
)
from .quals_registry import (
    load_registry, stale_standards, relevant_standards,
)
from .detector_v3 import detect_v3, DetectorOutput
from .grouper import group_claims_into_cards
from .evidence_aggregate import attach_evidence_from_claims
from .captions_v3 import write_captions
from .ranker_v3 import rank_cards
from .self_check import run_self_check, SelfCheckReport
from .cards import ContentCard


@dataclass
class PipelineRun:
    meet_name: str
    course: str                       # LC | SC
    club_code: str
    club_display: str
    parsed_swim_count: int
    our_swim_count: int
    other_swim_count: int
    n_swimmers_ours: int
    pb_fetch_ok: int
    pb_fetch_failed: int
    pb_fetch_errors: list[str] = field(default_factory=list)
    detector: Optional[DetectorOutput] = None
    cards: list[ContentCard] = field(default_factory=list)
    self_check: Optional[SelfCheckReport] = None
    standards_meta: dict = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""
    progress_log: list[str] = field(default_factory=list)


def _extract_hy3_from_zip(zip_path: str, tmp_dir: str) -> Optional[str]:
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.lower().endswith(".hy3"):
                z.extract(n, tmp_dir)
                return os.path.join(tmp_dir, n)
    return None


def run_pipeline(
    *,
    file_path: str,
    club_choice: str = "SUNY",         # 'SUNY' or 'SWAY' for the pilot
    course_override: Optional[str] = None,
    date_override: Optional[str] = None,
    exclude_host: bool = True,
    output_pref: str = "both",         # 'social' | 'recap' | 'both'
    use_pb_cache: bool = True,
    progress_cb=None,
) -> PipelineRun:
    log: list[str] = []
    def step(msg: str):
        log.append(msg)
        if progress_cb:
            try: progress_cb(msg)
            except Exception: pass

    started = datetime.now(timezone.utc).isoformat()
    step("Starting pipeline")

    # 1) Parse HY3 (handle .zip)
    if file_path.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(prefix="hy3_")
        try:
            hy3 = _extract_hy3_from_zip(file_path, tmp)
            if not hy3:
                raise RuntimeError("No .hy3 file found inside the uploaded zip.")
            step(f"Extracted HY3 from zip: {os.path.basename(hy3)}")
            meet = parse_hy3_file(hy3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        meet = parse_hy3_file(file_path)

    step(f"Parsed meet: {meet.name} ({len(meet.swims)} swims, {len(meet.swimmers)} swimmers, {len(meet.clubs)} clubs)")

    # Determine course
    courses = {sw.course for sw in meet.swims if sw.course}
    if course_override:
        course = course_override
    elif len(courses) == 1:
        course = courses.pop()
    elif "LC" in courses:
        course = "LC"
    else:
        course = next(iter(courses)) if courses else "LC"
    step(f"Meet course: {course}")

    # 2) Filter to our club
    if club_choice == "SUNY":
        roster = swansea_uni_roster()
    elif club_choice == "SWAY":
        roster = ClubRoster(club_codes={"SWAY"}, exclude_codes=({"SUNY"} if exclude_host else set()),
                             display_name="City of Swansea Aquatics")
    else:
        roster = ClubRoster(club_codes={club_choice}, display_name=club_choice)

    our_swims = roster.filter_swims(meet.swims)
    our_asa = sorted({sw.asa_id for sw in our_swims if sw.asa_id})
    other_count = len(meet.swims) - len(our_swims)
    step(f"Filtered to our club ({roster.display_name}): {len(our_swims)} swims, {len(our_asa)} swimmers, {other_count} excluded.")

    # 3) Fetch PB snapshots for our roster
    pb_progress = {"ok": 0, "fail": 0, "errors": []}
    def _pb_cb(i, total, snap):
        if snap.fetch_ok:
            pb_progress["ok"] += 1
        else:
            pb_progress["fail"] += 1
            if snap.error:
                pb_progress["errors"].append(f"{snap.tiref}: {snap.error}")
        if i % 5 == 0 or i == total:
            step(f"PB enrichment: {i}/{total} (ok {pb_progress['ok']}, fail {pb_progress['fail']})")

    pb_snapshots = fetch_roster(
        our_asa, use_cache=use_pb_cache, progress_cb=_pb_cb,
    )

    # 4) Quals
    standards = load_registry()
    stale = stale_standards(standards)
    standards_meta = {
        "total": len(standards),
        "stale_ids": [s.standard_id for s in stale],
        "relevant_ids": [s.standard_id for s in relevant_standards(standards, club_choice, course)],
    }
    step(f"Loaded {len(standards)} qualification standards ({len(stale)} stale, {len(standards_meta['relevant_ids'])} relevant to this meet).")

    # meet.swimmers is already keyed by asa_id
    swimmers_by_asa = meet.swimmers

    # 5) Detect
    det = detect_v3(
        meet=meet,
        our_swims=our_swims,
        swimmers_by_asa=swimmers_by_asa,
        pb_snapshots=pb_snapshots,
        standards=standards,
        club_code=club_choice,
    )
    step(f"Detector produced {len(det.claims)} claims (PB confirmed {det.n_pb_confirmed}, likely {det.n_pb_likely}, qual hits {det.n_qual_hits}, medals {det.n_medals}).")

    # 6) Group
    cards = group_claims_into_cards(det.claims, meet_name=meet.name)
    step(f"Grouped into {len(cards)} content cards.")

    # 7) Evidence aggregation
    cards = attach_evidence_from_claims(cards)

    # 8) Captions (3 voices)
    cards = write_captions(cards, club_short=roster.display_name)

    # 9) Rank + bucket
    cards = rank_cards(cards)
    n_queue = sum(1 for c in cards if c.bucket == "queue")
    step(f"Ranked: {n_queue} in queue.")

    # 10) Self-check
    opposition_leak = 0
    for card in cards:
        for c in card.claims:
            if c.swimmer_tiref and c.swimmer_tiref not in {sw.asa_id for sw in our_swims}:
                opposition_leak += 1
                break
    sc = run_self_check(
        cards=cards,
        parsed_swim_count=len(meet.swims),
        our_swim_count=len(our_swims),
        other_swim_count=other_count,
        opposition_leak_count=opposition_leak,
        standards_meta=standards_meta,
        course=course,
    )
    step(f"Self-check: {sc.pass_count} pass, {sc.warn_count} warn, {sc.fail_count} fail.")

    finished = datetime.now(timezone.utc).isoformat()

    return PipelineRun(
        meet_name=meet.name,
        course=course,
        club_code=club_choice,
        club_display=roster.display_name,
        parsed_swim_count=len(meet.swims),
        our_swim_count=len(our_swims),
        other_swim_count=other_count,
        n_swimmers_ours=len(our_asa),
        pb_fetch_ok=pb_progress["ok"],
        pb_fetch_failed=pb_progress["fail"],
        pb_fetch_errors=pb_progress["errors"][:20],
        detector=det,
        cards=cards,
        self_check=sc,
        standards_meta=standards_meta,
        started_at=started,
        finished_at=finished,
        progress_log=log,
    )
