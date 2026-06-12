"""The human-approval signal = the autonomy toggle (P2.2).

The approval lifecycle is ``CardStatus.QUEUE → APPROVED → POSTED``
(``docs/AUTONOMY_MODEL.md`` §3). This module decides *who drives* the
``QUEUE → APPROVED`` transition for each card, per the org's per-type
autonomy policy (P2.4):

* ``draft_only`` / ``approval_required`` (the default) — the card **pauses
  on the signal**: it stays in QUEUE/EDITED until a human approves it on the
  review page. This module never touches it.
* ``fully_autonomous`` — the card **skips the human wait** only if the full
  publish gate (``publishing.publish_gate``, P2.3) passes for the exact
  caption that would be posted; it is then auto-APPROVED and, when the org
  has chosen autonomous channels, published through the same Buffer path a
  human click uses. Any guardrail failure leaves the card in the queue for
  a human — autonomy degrades to approval, never the other way round.

Everything is audited (``workflow.autonomy.AuditLog``): the gate verdict,
the auto-approval, and every publish attempt (also in
``publishing.posting_log``). Tenant isolation: the cycle refuses to act on
a run not owned by the org. The deterministic engine is read-only here —
the signal changes the *publish path*, never the data.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mediahub.club_platform.post_types import canonical_slug
from mediahub.publishing.per_type_policy import AutonomyLevel, load_policy
from mediahub.publishing.publish_gate import evaluate_publish_gate
from mediahub.workflow.autonomy import AuditLog
from mediahub.workflow.status import CardStatus, ScheduleStatus
from mediahub.workflow.store import WorkflowStore

log = logging.getLogger(__name__)

RUN_CONTENT_TYPE = "meet_recap"  # a pipeline run IS the meet-recap surface
MAX_CARDS_PER_CYCLE = 25
_CAPTION_SLOT_ORDER = ("headline", "body", "cta")


@dataclass
class ApprovalOutcome:
    """One card's pass through the signal — explainable, auditable."""

    card_id: str
    decision: str  # awaiting_human | draft_only | auto_approved | held_for_human
    detail: str = ""
    blockers: list[str] = field(default_factory=list)
    published: bool = False
    publish_detail: str = ""

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "decision": self.decision,
            "detail": self.detail,
            "blockers": list(self.blockers),
            "published": self.published,
            "publish_detail": self.publish_detail,
        }


def _runs_dir(data_dir: Optional[Path] = None) -> Path:
    env = os.environ.get("RUNS_DIR")
    if env and data_dir is None:
        return Path(env)
    base = Path(data_dir) if data_dir is not None else Path(os.environ.get("DATA_DIR", "."))
    return base / "runs_v4"


def _load_owned_run(org_id: str, run_id: str, runs_dir: Path) -> Optional[dict]:
    path = runs_dir / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    # Tenant isolation: the cycle only ever acts on the org's own runs.
    if (data.get("profile_id") or "").strip() != (org_id or "").strip() or not org_id:
        return None
    return data


def _card_id_of(ra: dict) -> str:
    ach = ra.get("achievement") or {}
    return str(ach.get("swim_id") or ach.get("swimmer_id") or ra.get("rank", "")).strip()


def _gate_card_view(ra: dict) -> dict:
    """The card facts the publish gate reads, merged from where the pipeline
    actually puts them (RankedAchievement carries safe_to_post; the
    achievement carries confidence/age). Read-only view — never written back."""
    ach = ra.get("achievement") or {}
    view = {
        "safe_to_post": ra.get("safe_to_post") or ach.get("safe_to_post"),
        "confidence": ach.get("confidence", ra.get("confidence")),
        "age": ach.get("age"),
        "raw_facts": ach.get("raw_facts") or {},
    }
    return view


def _caption_for_card(run_data: dict, ra: dict, wf_state, profile_id: str) -> str:
    """The exact caption text an autonomous publish would post.

    Mirrors ``pack.build_content_pack``'s caption resolution (brand captions
    for the org's active tone, human edits taking precedence) so the gate
    checks what would actually ship — but without requiring APPROVED status
    and without the approved-caption learning side effects (machine-approved
    captions deliberately don't feed the voice store).
    """
    card = dict(ra)
    tone = None
    try:
        from mediahub.brand.store import load_brand  # noqa: PLC0415

        kit, tone, caption_templates = load_brand(profile_id)
        if kit is not None and tone is not None:
            from mediahub.brand.apply import apply_brand  # noqa: PLC0415

            card = apply_brand(card, kit, tone, RUN_CONTENT_TYPE, caption_templates)
    except Exception:
        pass

    slots: dict[str, str] = {}
    brand_captions = card.get("brand_captions")
    if isinstance(brand_captions, dict) and tone is not None:
        active = brand_captions.get(tone)
        if isinstance(active, dict):
            slots = {k: str(v) for k, v in active.items() if isinstance(v, str)}

    # Human edits always win, exactly as on the review page.
    edited = getattr(wf_state, "edited_captions", None) or {}
    for key, val in edited.items():
        parts = str(key).rsplit("_", 1)
        if len(parts) == 2 and isinstance(val, str):
            t_str, slot = parts
            if tone is None or t_str == tone:
                slots[slot] = val

    if not slots:
        ach = ra.get("achievement") or {}
        headline = str(ach.get("headline") or "").strip()
        return headline

    ordered = [slots[s] for s in _CAPTION_SLOT_ORDER if str(slots.get(s) or "").strip()]
    ordered += [
        str(v) for k, v in sorted(slots.items()) if k not in _CAPTION_SLOT_ORDER and str(v).strip()
    ]
    return "\n\n".join(part.strip() for part in ordered if part.strip())


def _resolve_buffer_token(profile) -> str:
    """Per-profile Buffer token first, env fallback — the same resolution
    order as the human schedule route."""
    tok = (getattr(profile, "buffer_access_token", "") or "").strip()
    if tok:
        return tok
    return (os.environ.get("BUFFER_ACCESS_TOKEN") or "").strip()


def _publish_card(
    org_id: str,
    run_id: str,
    card_id: str,
    caption: str,
    *,
    channels: list[str],
    profile,
    store: WorkflowStore,
    audit: AuditLog,
    session_id: str,
) -> tuple[bool, str]:
    """Publish one auto-approved card through the same Buffer path a human
    click uses. Returns (published, detail). Honest failures: no token, no
    channels, or Buffer errors leave the card APPROVED for a human."""
    if not channels:
        return False, "no autonomous channels configured — approved for human scheduling"
    token = _resolve_buffer_token(profile)
    if not token:
        return False, "no Buffer token for this org — approved for human scheduling"

    from mediahub.publishing import posting_log
    from mediahub.publishing.buffer import BufferError, schedule_post
    from mediahub.publishing.kill_switch import PublishingHalted

    ok_ids: list[str] = []
    failures: list[str] = []
    for channel_id in channels:
        try:
            res = schedule_post(
                token=token, channel_id=str(channel_id), text=caption, media_urls=None
            )
            ok_ids.append(str(res.get("update_id") or ""))
            posting_log.record_attempt(
                profile_id=org_id,
                run_id=run_id,
                card_id=card_id,
                channel_id=str(channel_id),
                service="buffer",
                status="ok",
                update_id=str(res.get("update_id") or ""),
                caption=caption,
            )
        except PublishingHalted as e:
            # The kill switch engaged between the gate check and the post —
            # stop touching every remaining channel immediately and say so.
            failures.append(f"{channel_id}: {e}")
            posting_log.record_attempt(
                profile_id=org_id,
                run_id=run_id,
                card_id=card_id,
                channel_id=str(channel_id),
                service="buffer",
                status="failed",
                error_kind="PublishingHalted",
                error_message=str(e)[:300],
                caption=caption,
            )
            audit.record(
                org_id,
                session_id,
                "blocked",
                tool="buffer.schedule_post",
                args={"run_id": run_id, "card_id": card_id},
                result="kill switch engaged mid-cycle — publishing halted",
            )
            break
        except BufferError as e:
            failures.append(f"{channel_id}: {e}")
            posting_log.record_attempt(
                profile_id=org_id,
                run_id=run_id,
                card_id=card_id,
                channel_id=str(channel_id),
                service="buffer",
                status="failed",
                error_kind=type(e).__name__,
                error_message=str(e)[:300],
                caption=caption,
            )
    if ok_ids:
        store.set_schedule(
            run_id,
            card_id,
            ScheduleStatus.SCHEDULED,
            buffer_update_id=";".join(i for i in ok_ids if i) or None,
            schedule_error="; ".join(failures)[:500] or None,
        )
        detail = f"scheduled on {len(ok_ids)} channel(s)" + (
            f"; {len(failures)} failed" if failures else ""
        )
        audit.record(
            org_id,
            session_id,
            "auto_publish",
            tool="buffer.schedule_post",
            args={"run_id": run_id, "card_id": card_id, "channels": list(channels)},
            result=detail,
        )
        return True, detail
    store.set_schedule(
        run_id,
        card_id,
        ScheduleStatus.FAILED,
        schedule_error="; ".join(failures)[:500] or "no channel accepted the post",
    )
    detail = "publish failed on every channel: " + ("; ".join(failures) or "unknown")
    audit.record(
        org_id,
        session_id,
        "auto_publish",
        tool="buffer.schedule_post",
        args={"run_id": run_id, "card_id": card_id, "channels": list(channels)},
        result=detail,
    )
    return False, detail


def apply_approval_signal(
    org_id: str,
    run_id: str,
    *,
    content_type: str = RUN_CONTENT_TYPE,
    data_dir: Optional[Path] = None,
    publish: bool = True,
    limit: int = MAX_CARDS_PER_CYCLE,
) -> dict:
    """Run the approval signal over one run's pre-approval cards.

    Gated types pause (nothing is touched); a ``fully_autonomous`` type's
    cards are gate-checked one by one against the exact caption that would
    ship — passing cards are auto-APPROVED and (``publish=True``, channels
    configured) published; failing cards stay queued for a human with the
    blockers recorded. Returns an explainable summary. Never raises on a
    per-card basis; a missing/foreign run returns ``{"ok": False}``.
    """
    slug = canonical_slug(content_type)
    runs_dir = _runs_dir(data_dir)
    audit = AuditLog()
    run_data = _load_owned_run(org_id, run_id, runs_dir)
    if run_data is None:
        return {"ok": False, "error": "run not found for this organisation", "run_id": run_id}

    policy_level = AutonomyLevel.from_str(load_policy(org_id, data_dir=data_dir).get(slug))
    ranked = (run_data.get("recognition_report") or {}).get("ranked_achievements") or []
    store = WorkflowStore(runs_dir)
    states = store.load(run_id)
    session_id = f"signal:{run_id}"

    outcomes: list[ApprovalOutcome] = []
    pre_approval = 0
    for ra in ranked:
        if pre_approval >= max(1, int(limit)):
            break
        card_id = _card_id_of(ra)
        if not card_id:
            continue
        state = states.get(card_id)
        status = state.status if state is not None else CardStatus.QUEUE
        if status not in (CardStatus.QUEUE, CardStatus.EDITED):
            continue  # a human already decided — never revisit
        pre_approval += 1

        if policy_level is AutonomyLevel.DRAFT_ONLY:
            outcomes.append(
                ApprovalOutcome(
                    card_id,
                    "draft_only",
                    "draft-only type — never enters the schedule queue automatically",
                )
            )
            continue
        if policy_level is AutonomyLevel.APPROVAL_REQUIRED:
            outcomes.append(
                ApprovalOutcome(card_id, "awaiting_human", "paused on the human-approval signal")
            )
            continue

        # fully_autonomous: gate against the exact caption that would ship.
        caption = _caption_for_card(run_data, ra, state, org_id)
        verdict = evaluate_publish_gate(
            org_id,
            slug,
            card=_gate_card_view(ra),
            caption=caption,
            run_id=run_id,
            card_id=card_id,
            data_dir=data_dir,
        )
        if not verdict.allowed:
            outcomes.append(
                ApprovalOutcome(
                    card_id,
                    "held_for_human",
                    "guardrails held this card for human review",
                    blockers=verdict.blockers(),
                )
            )
            continue

        store.set_status(
            run_id, card_id, CardStatus.APPROVED, notes="Auto-approved: publish gate passed"
        )
        audit.record(
            org_id,
            session_id,
            "auto_approve",
            tool="apply_approval_signal",
            args={"run_id": run_id, "card_id": card_id, "content_type": slug},
            result="auto-approved — all guardrails passed",
        )
        outcome = ApprovalOutcome(card_id, "auto_approved", "all guardrails passed")

        if publish:
            try:
                from mediahub.web.club_profile import load_profile  # noqa: PLC0415

                profile = load_profile(org_id)
            except Exception:
                profile = None
            channels = [
                str(c)
                for c in (getattr(profile, "autonomy_channel_ids", []) or [])
                if str(c).strip()
            ]
            published, detail = _publish_card(
                org_id,
                run_id,
                card_id,
                caption,
                channels=channels,
                profile=profile,
                store=store,
                audit=audit,
                session_id=session_id,
            )
            outcome.published = published
            outcome.publish_detail = detail
        outcomes.append(outcome)

    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.decision] = counts.get(o.decision, 0) + 1
    return {
        "ok": True,
        "run_id": run_id,
        "content_type": slug,
        "policy_level": policy_level.value,
        "considered": pre_approval,
        "counts": counts,
        "published": sum(1 for o in outcomes if o.published),
        "outcomes": [o.to_dict() for o in outcomes],
    }


# ---------------------------------------------------------------------------
# Scheduler task — the cadence that makes "skip the wait" real
# ---------------------------------------------------------------------------


def _recent_run_ids(org_id: str, *, limit: int = 5) -> list[str]:
    try:
        import sqlite3

        db = Path(os.environ.get("DATA_DIR", ".")) / "data.db"
        conn = sqlite3.connect(str(db), timeout=5.0)
        rows = conn.execute(
            "SELECT id FROM runs WHERE profile_id = ? AND status = 'done' "
            "ORDER BY created_at DESC LIMIT ?",
            (org_id, int(limit)),
        ).fetchall()
        conn.close()
        return [str(r[0]) for r in rows]
    except Exception:
        return []


def _approval_signal_task_handler(params: dict) -> None:
    """Scheduler handler: run the signal over an org's recent runs. Inert for
    fully-gated orgs (every card just reports awaiting_human)."""
    org_id = (params.get("org_id") or "").strip()
    if not org_id:
        raise ValueError("approval-signal task requires an org_id")
    run_ids = [str(params["run_id"])] if params.get("run_id") else _recent_run_ids(org_id)
    for run_id in run_ids:
        try:
            apply_approval_signal(org_id, run_id)
        except Exception as e:  # one run's failure must not stop the rest
            log.warning("approval signal failed for run %s: %s", run_id, e)


def register_approval_signal_task() -> None:
    """Register the ``approval_signal`` scheduler task type (idempotent)."""
    try:
        from mediahub.scheduler import register_task_type  # noqa: PLC0415

        register_task_type("approval_signal", _approval_signal_task_handler)
    except Exception as e:  # never block app startup on this
        log.warning("could not register approval_signal task type: %s", e)


# The cadence that makes fully_autonomous real: one hourly scheduled task per
# opted-in org. Hourly keeps "skip the human wait" timely without hammering
# the gate; the rate caps inside evaluate_publish_gate still bound output.
APPROVAL_SIGNAL_CADENCE = ("cron", "0 * * * *")


def _org_has_autonomous_type(org_id: str) -> bool:
    try:
        policy = load_policy(org_id)
    except Exception:
        return False
    return any(
        AutonomyLevel.from_str(level) is AutonomyLevel.FULLY_AUTONOMOUS
        for level in policy.values()
    )


def ensure_approval_signal_cadence(org_id: str) -> bool:
    """Reconcile the org's ``approval_signal`` scheduled task with its policy.

    Any ``fully_autonomous`` type → ensure exactly one hourly task exists for
    the org; none → delete the org's task so a fully-gated org runs no cycles
    at all. Idempotent and safe to call on every policy save and at startup.
    Returns True when a cadence task exists after reconciliation.
    """
    org_id = (org_id or "").strip()
    if not org_id:
        return False
    try:
        from mediahub.workflow.schedule import create_task, delete_task, list_tasks
    except Exception as e:
        log.warning("approval-signal cadence unavailable: %s", e)
        return False

    wanted = _org_has_autonomous_type(org_id)
    existing = [
        t
        for t in list_tasks()
        if t.task_type == "approval_signal" and (t.params or {}).get("org_id") == org_id
    ]
    if wanted and not existing:
        kind, expr = APPROVAL_SIGNAL_CADENCE
        create_task(
            name=f"Autonomy approval signal ({org_id})",
            task_type="approval_signal",
            schedule_kind=kind,
            schedule_expr=expr,
            params={"org_id": org_id},
        )
        return True
    if not wanted:
        for t in existing:
            delete_task(t.id)
        return False
    # Collapse duplicates (two workers can race the startup reconciliation);
    # the per-slot atomic claim already de-dupes firing, this de-dupes rows.
    for t in sorted(existing, key=lambda t: t.created_at)[1:]:
        delete_task(t.id)
    return True


def reconcile_all_approval_signal_cadences() -> None:
    """Startup pass: make every org's cadence match its saved policy (covers
    orgs that opted into fully_autonomous before cadence wiring existed)."""
    try:
        from mediahub.web.club_profile import list_profiles  # noqa: PLC0415

        org_ids = [p.profile_id for p in list_profiles()]
    except Exception as e:
        log.warning("could not list orgs for approval-signal reconciliation: %s", e)
        return
    for org_id in org_ids:
        try:
            ensure_approval_signal_cadence(org_id)
        except Exception as e:  # one org's failure must not stop the rest
            log.warning("approval-signal reconciliation failed for %s: %s", org_id, e)


__all__ = [
    "ApprovalOutcome",
    "apply_approval_signal",
    "ensure_approval_signal_cadence",
    "reconcile_all_approval_signal_cadences",
    "register_approval_signal_task",
    "RUN_CONTENT_TYPE",
]
