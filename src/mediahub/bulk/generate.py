"""bulk.generate — many outputs from one click, all review-queued (1.13).

The killer feature Canva can't ground: *"a certificate for all 47 PB swimmers"*,
*"a spotlight per graduating senior"*. Each target is one achievement already in
a run; bulk generation, for each one:

1. **queues the card into the normal review queue** (``CardStatus.QUEUE``) — the
   non-negotiable rule is that bulk never bypasses a human's approval; and
2. **best-effort renders the chosen format's artifact** (e.g. a certificate
   PDF), recording an honest per-item error if a renderer/dependency is missing.

Targets are resolved **deterministically** from the run's ranked achievements
(no AI picks who gets a certificate). A safety cap bounds a job; the full
per-org/per-feature quota ledger lands with 1.23.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from mediahub.workflow.status import CardStatus
from mediahub.workflow.store import WorkflowStore

from . import store as _store
from .models import (
    ITEM_FAILED,
    ITEM_QUEUED,
    ITEM_SKIPPED,
    JOB_DONE,
    JOB_RUNNING,
    BulkItem,
    BulkJob,
)

# A sane safety cap on one job. Per-org/per-feature quotas arrive with 1.23.
DEFAULT_CAP = 200

# PB-family post angles, so "PB swimmers" resolves deterministically.
PB_ANGLES = {
    "confirmed_official_pb",
    "pb_improvement",
    "likely_pb",
    "first_sub_barrier",
    "biggest_drop",
    "multi_pb_weekend",
    "fastest_since",
    "return_to_form",
    "medal_and_pb_combo",
}


def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[1])))


def _runs_dir(runs_dir: Optional[Path] = None) -> Path:
    if runs_dir is not None:
        return Path(runs_dir)
    env = os.environ.get("RUNS_DIR")
    return Path(env) if env else _data_dir() / "runs_v4"


def _load_run(run_id: str, runs_dir: Optional[Path]) -> Optional[dict]:
    path = _runs_dir(runs_dir) / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _card_id_for(ra: dict) -> str:
    """Mirror workflow.pack: the stable id a ranked achievement reviews under."""
    ach = ra.get("achievement") or {}
    return ach.get("swim_id") or ach.get("swimmer_id") or str(ra.get("rank", ""))


def _label_for(ra: dict) -> str:
    ach = ra.get("achievement") or {}
    name = ach.get("swimmer_name") or "Swimmer"
    event = ach.get("event") or ach.get("headline") or ""
    return f"{name} — {event}".strip(" —")


# ---------------------------------------------------------------------------
# Deterministic target resolution
# ---------------------------------------------------------------------------


def resolve_cards(run_data: dict, row_query: Optional[dict] = None) -> list[dict]:
    """Pick the ranked achievements a bulk job targets — deterministically.

    ``row_query`` (all optional):
      * ``pb_only``       — keep only PB-family achievements
      * ``post_angles``   — keep these post angles
      * ``types``         — keep these achievement ``type`` values
      * ``quality_bands`` — keep these quality bands
      * ``swimmer_keys``  — keep only these swimmers
    With no query, every ranked achievement is a target.
    """
    q = row_query or {}
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    angles = set(q.get("post_angles") or [])
    if q.get("pb_only"):
        angles |= PB_ANGLES
    types = set(q.get("types") or [])
    bands = set(q.get("quality_bands") or [])
    keys = set(q.get("swimmer_keys") or [])

    out: list[dict] = []
    for ra in ranked:
        if not isinstance(ra, dict):
            continue
        ach = ra.get("achievement") or {}
        if angles:
            angle = ra.get("post_angle") or ach.get("post_angle") or ""
            atype = str(ach.get("type") or "")
            if angle not in angles and not (q.get("pb_only") and "pb" in atype.lower()):
                continue
        if types and str(ach.get("type") or "") not in types:
            continue
        if bands and str(ra.get("quality_band") or "") not in bands:
            continue
        if keys and str(ach.get("swimmer_id") or "") not in keys:
            continue
        out.append(ra)
    return out


# ---------------------------------------------------------------------------
# Per-format artifact generators
# ---------------------------------------------------------------------------


@dataclass
class GenContext:
    profile_id: str
    run_id: str
    run_data: dict
    card: dict  # the ranked achievement
    card_id: str
    out_dir: Path
    bindings: dict


@dataclass
class GenOutput:
    ok: bool
    path: str = ""
    error: str = ""


# A format generator turns one card into one artifact file.
FormatGenerator = Callable[[GenContext], GenOutput]
_FORMAT_GENERATORS: dict[str, FormatGenerator] = {}


def register_format(slug: str, gen: FormatGenerator) -> None:
    _FORMAT_GENERATORS[slug] = gen


def format_generator(slug: str) -> Optional[FormatGenerator]:
    return _FORMAT_GENERATORS.get(slug)


def _certificate_generator(ctx: GenContext) -> GenOutput:
    """Render one achievement as a print certificate PDF (best-effort, honest)."""
    try:
        from mediahub.graphic_renderer.print_export import export_certificate_print_pdf
        from mediahub.web.club_profile import load_profile
    except Exception as exc:  # noqa: BLE001 — missing optional render deps → honest error
        return GenOutput(False, error=f"Certificate renderer unavailable: {exc}")

    ach = ctx.card.get("achievement") or {}
    facts = ach.get("raw_facts") or {}
    meet = ctx.run_data.get("meet") or {}
    try:
        profile = load_profile(ctx.profile_id)
        club_name = getattr(profile, "display_name", "") or ctx.profile_id
        brand = {
            "primary": getattr(profile, "brand_primary", "") or "#1746a2",
            "secondary": getattr(profile, "brand_secondary", "") or "#0b1f44",
        }
    except Exception:
        club_name = ctx.profile_id
        brand = {"primary": "#1746a2", "secondary": "#0b1f44"}

    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = ctx.out_dir / f"certificate-{ctx.card_id}.pdf"
    try:
        export_certificate_print_pdf(
            pdf_path,
            swimmer_name=ach.get("swimmer_name", ""),
            event_label=ach.get("event", ""),
            time_str=str(facts.get("time_str") or ach.get("time") or ""),
            achievement_headline=ach.get("headline", ""),
            meet_name=meet.get("name", ""),
            meet_date=meet.get("start_date", "") or "",
            club_name=club_name,
            brand=brand,
        )
    except Exception as exc:  # noqa: BLE001 — render failure is per-item, never fatal
        return GenOutput(False, error=f"Certificate render failed: {exc}")
    return GenOutput(True, path=str(pdf_path))


register_format("certificate", _certificate_generator)


# ---------------------------------------------------------------------------
# Plan + run
# ---------------------------------------------------------------------------


def plan_bulk(
    profile_id: str,
    run_id: str,
    format_slug: str,
    *,
    row_query: Optional[dict] = None,
    title: str = "",
    cap: int = DEFAULT_CAP,
    runs_dir: Optional[Path] = None,
) -> BulkJob:
    """Resolve targets into a planned job (no generation yet) — for preview."""
    run_data = _load_run(run_id, runs_dir)
    if run_data is None:
        raise ValueError(f"Run not found: {run_id}")
    if profile_id and run_data.get("profile_id") not in (None, "", profile_id):
        raise PermissionError("Run belongs to another organisation.")

    cards = resolve_cards(run_data, row_query)
    if cap and len(cards) > cap:
        cards = cards[:cap]

    job = BulkJob(
        job_id=uuid.uuid4().hex[:12],
        profile_id=profile_id,
        run_id=run_id,
        format_slug=format_slug,
        title=title or f"{format_slug} × {len(cards)}",
        cap=cap,
    )
    for ra in cards:
        cid = _card_id_for(ra)
        ach = ra.get("achievement") or {}
        job.items.append(
            BulkItem(
                item_id=uuid.uuid4().hex[:10],
                card_id=cid,
                label=_label_for(ra),
                post_angle=ra.get("post_angle") or ach.get("post_angle") or "",
            )
        )
    return job


def run_bulk(
    profile_id: str,
    job: BulkJob,
    *,
    runs_dir: Optional[Path] = None,
    render: bool = True,
    generator: Optional[FormatGenerator] = None,
    progress_cb: Optional[Callable[[BulkJob], None]] = None,
) -> BulkJob:
    """Queue each item's card for review and best-effort render its artifact.

    NEVER approves or posts: items are placed in ``CardStatus.QUEUE`` only, and
    any card a human already decided (APPROVED/POSTED) is left untouched.
    """
    run_data = _load_run(job.run_id, runs_dir)
    if run_data is None:
        job.status = "failed"
        job.message = f"Run not found: {job.run_id}"
        return job

    ws = WorkflowStore(_runs_dir(runs_dir))
    states = ws.load(job.run_id)
    by_card = {_card_id_for(ra): ra for ra in (run_data.get("recognition_report", {}) or {}).get("ranked_achievements", [])}

    gen = generator or format_generator(job.format_slug)
    out_dir = _runs_dir(runs_dir) / job.run_id / "bulk" / job.job_id

    job.status = JOB_RUNNING
    n_rendered = 0
    for item in job.items:
        existing = states.get(item.card_id)
        if existing is not None and existing.status in (CardStatus.APPROVED, CardStatus.POSTED):
            item.status = ITEM_SKIPPED
            item.error = "Already decided by a reviewer — left as is."
            if progress_cb:
                progress_cb(job)
            continue

        # Queue for review (idempotent: only create a state when none exists).
        if existing is None:
            ws.set_status(job.run_id, item.card_id, CardStatus.QUEUE, notes=f"bulk:{job.format_slug}")

        item.status = ITEM_QUEUED
        if render and gen is not None:
            ra = by_card.get(item.card_id) or {"achievement": {}}
            ctx = GenContext(
                profile_id=profile_id,
                run_id=job.run_id,
                run_data=run_data,
                card=ra,
                card_id=item.card_id,
                out_dir=out_dir,
                bindings=dict(job.__dict__.get("_bindings", {})),
            )
            out = gen(ctx)
            if out.ok:
                item.output_path = out.path
                n_rendered += 1
            else:
                item.status = ITEM_FAILED
                item.error = out.error
        if progress_cb:
            progress_cb(job)

    job.status = JOB_DONE
    rendered_note = f"{n_rendered} artifact(s) rendered" if render else "queued for review"
    job.message = f"{job.n_queued} queued, {job.n_failed} failed, {job.n_skipped} skipped — {rendered_note}."
    return job


def bulk_generate(
    profile_id: str,
    run_id: str,
    format_slug: str,
    *,
    row_query: Optional[dict] = None,
    title: str = "",
    cap: int = DEFAULT_CAP,
    runs_dir: Optional[Path] = None,
    render: bool = True,
    generator: Optional[FormatGenerator] = None,
    progress_cb: Optional[Callable[[BulkJob], None]] = None,
    save: bool = True,
    jobs_dir: Optional[Path] = None,
) -> BulkJob:
    """Plan + run a bulk job. The one-call entry point used by the route."""
    job = plan_bulk(
        profile_id, run_id, format_slug, row_query=row_query, title=title, cap=cap, runs_dir=runs_dir
    )
    if save:
        _store.save_job(job, jobs_dir=jobs_dir)
    run_bulk(
        profile_id,
        job,
        runs_dir=runs_dir,
        render=render,
        generator=generator,
        progress_cb=progress_cb,
    )
    if save:
        _store.save_job(job, jobs_dir=jobs_dir)
    return job


# ---------------------------------------------------------------------------
# Optional scheduler integration (large jobs run in the background)
# ---------------------------------------------------------------------------


def _bulk_task_handler(params: dict) -> None:
    """Scheduler handler: re-run a saved job by id (idempotent)."""
    profile_id = params.get("profile_id", "")
    job_id = params.get("job_id", "")
    job = _store.load_job(profile_id, job_id)
    if job is None:
        return
    run_bulk(profile_id, job)
    _store.save_job(job)


def register_task() -> None:
    """Register the bulk task type with the in-process scheduler (idempotent)."""
    try:
        from mediahub.scheduler import register_task_type

        register_task_type("bulk_generate", _bulk_task_handler)
    except Exception:  # noqa: BLE001 — scheduler optional; never block import
        pass


__all__ = [
    "DEFAULT_CAP",
    "PB_ANGLES",
    "GenContext",
    "GenOutput",
    "resolve_cards",
    "register_format",
    "format_generator",
    "plan_bulk",
    "run_bulk",
    "bulk_generate",
    "register_task",
]
