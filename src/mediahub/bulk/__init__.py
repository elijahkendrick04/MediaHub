"""bulk — generate many outputs at once, every one review-queued (roadmap 1.13).

The data hub's "killer feature": *"a certificate for all 47 PB swimmers"*. One
click fans out over a run's ranked achievements, queues each card into the normal
review queue (a human still approves), and best-effort renders the chosen
format's artifact. Targets are resolved deterministically; nothing is ever
auto-approved or auto-posted.

* :mod:`~mediahub.bulk.models`   — the job + item records (with progress).
* :mod:`~mediahub.bulk.store`    — persist jobs under ``DATA_DIR/bulk_jobs``.
* :mod:`~mediahub.bulk.generate` — resolve targets, queue for review, render.
"""

from __future__ import annotations

from .generate import (
    DEFAULT_CAP,
    PB_ANGLES,
    bulk_generate,
    plan_bulk,
    register_format,
    register_task,
    resolve_cards,
    run_bulk,
)
from .models import BulkItem, BulkJob
from .store import list_jobs, load_job, save_job

__all__ = [
    "DEFAULT_CAP",
    "PB_ANGLES",
    "BulkItem",
    "BulkJob",
    "bulk_generate",
    "plan_bulk",
    "run_bulk",
    "resolve_cards",
    "register_format",
    "register_task",
    "save_job",
    "load_job",
    "list_jobs",
]
