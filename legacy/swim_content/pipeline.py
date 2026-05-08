"""
End-to-end pipeline orchestrator.

Single entry point: process_meet(...) takes the inputs and returns a
PipelineResult containing everything the UI needs to render.

This is deliberately a thin orchestrator. Each module it composes is
independently testable. No DB writes, no IO except reading the inputs.
The Flask app (app_v2.py) handles persistence and HTTP wiring on top.
"""
from __future__ import annotations
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .parsers_hy3 import parse_hy3_file, ParsedMeet
from .parsers_pb_pdf import import_pb_pdfs, PBStore
from .club_filter import ClubRoster, swansea_uni_roster
from .detector_v2 import detect, DetectionResult
from .ranker import rank, RankedQueue
from .upload_report import UploadReport, build_report
from .content_gen_v2 import captions_for_card, weekend_recap


@dataclass
class PipelineResult:
    meet: ParsedMeet
    pb_store: PBStore
    roster: ClubRoster
    detection: DetectionResult
    queue: RankedQueue
    report: UploadReport
    weekend_recap_text: str

    def caption_for_card_idx(self, idx: int, *, n: int = 2) -> list[str]:
        """Helper for UI: get captions for the idx-th queue card."""
        if idx < 0 or idx >= len(self.queue.queue):
            return []
        return captions_for_card(self.queue.queue[idx], n_variants=n)


def _hy3_from_zip(zip_path: str | Path) -> str:
    """Extract the .hy3 file from a Hytek meet zip into a temp file and
    return its path. The zip typically contains both .hy3 and .cl2; we
    prefer .hy3."""
    z = Path(zip_path)
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        hy3 = next((n for n in names if n.lower().endswith('.hy3')), None)
        if not hy3:
            raise ValueError(f"No .hy3 in {z.name}; only {names}")
        # Extract alongside the zip (same directory) for inspection.
        out_dir = z.parent / f"_extracted_{z.stem}"
        out_dir.mkdir(exist_ok=True)
        zf.extract(hy3, out_dir)
        return str(out_dir / hy3)


def process_meet(
    *,
    hy3_path: str | None = None,
    meet_zip_path: str | None = None,
    pb_pdf_paths: dict[str, str],
    roster: ClubRoster | None = None,
    pb_store_generated_iso: str | None = None,
) -> PipelineResult:
    """Run the full pipeline.

    Provide EITHER hy3_path OR meet_zip_path (not both). pb_pdf_paths
    maps {'female_lc', 'female_sc', 'male_lc', 'male_sc'} to file paths.

    roster defaults to the Swansea Uni pilot roster.
    """
    if not (hy3_path or meet_zip_path):
        raise ValueError("Provide hy3_path or meet_zip_path")
    if hy3_path and meet_zip_path:
        raise ValueError("Provide only one of hy3_path / meet_zip_path")

    if meet_zip_path:
        hy3_path = _hy3_from_zip(meet_zip_path)

    meet = parse_hy3_file(hy3_path)
    pb_store = import_pb_pdfs(pb_pdf_paths)
    roster = roster or swansea_uni_roster()

    our_swims = roster.filter_swims(meet.swims)
    detection = detect(meet, pb_store, our_swims, meet.swimmers)
    ranked = rank(detection.cards)
    report = build_report(
        meet, pb_store, roster,
        ranked.queue, ranked.recap, ranked.archive,
        pb_store_generated_iso=pb_store_generated_iso,
    )
    recap_text = weekend_recap(meet.name, ranked.queue, ranked.recap)

    return PipelineResult(
        meet=meet, pb_store=pb_store, roster=roster,
        detection=detection, queue=ranked, report=report,
        weekend_recap_text=recap_text,
    )
