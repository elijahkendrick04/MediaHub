"""mediahub/autonomy/tools.py — the narrow, fixed tool surface + dispatch.

This module is the security core of the autonomy runner. Per the council:

- **Fixed allow-list.** Tools live in a literal ``REGISTRY`` of typed Python
  callables. ``dispatch()`` is the single chokepoint: a name not in the
  registry (or not permitted at the session's level) is **blocked and audited,
  never executed**. There is no ``eval``/``getattr``/dynamic import — the model
  cannot reach anything that is not here.
- **No publish, structurally.** The only status a tool may set is a
  *pre-approval* one (``queue``/``edited``); ``_safe_set_status`` refuses
  anything else, so the runner can never approve, post, or reject — those are
  human-only and unreachable from here. The runner holds no posting credentials.
- **Tenancy bound once.** ``ToolContext.org_id`` is the ONLY source of tenancy.
  It is set at session start and never read from model output / tool args; every
  run-scoped tool re-verifies ownership via the injected ``owns_run``.
- **Id-only params.** Tools take internal ids (run_id, card_id) — never a URL,
  path, or template free-string — so there is no SSRF / path-traversal re-entry.
- **Post-deterministic only.** Tools read the already-ranked, already-detected
  ``recognition_report`` and write only into the workflow overlay; they never
  touch the deterministic engine's state (parser / PB / ranker / confidence).

App-specific data access (loading runs, listing an org's runs, the workflow
store, caption generation) is **injected** via :class:`AutonomyEnv`, so this
engine is decoupled from ``web.py`` and fully testable with fakes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

from mediahub.workflow.autonomy import AuditLog
from mediahub.workflow.status import CardStatus

log = logging.getLogger(__name__)


class RunnerReach(IntEnum):
    """How far the runner may go without a human. The human gate is fixed at
    publish for EVERY level — higher levels never shorten the approval step."""

    OFF = 0  # disabled
    SUGGEST = 1  # read-only: look at runs/cards, propose ideas
    DRAFT = 2  # + draft/rewrite captions (stored as edits, never approved)
    PREPARE = 3  # + flag prepared cards for the human's review queue


# Plain-English labels for non-technical committee members (the Outsider).
LEVEL_LABELS = {
    RunnerReach.OFF: "Off",
    RunnerReach.SUGGEST: "Show me ideas",
    RunnerReach.DRAFT: "Write it for me",
    RunnerReach.PREPARE: "Get it ready to review",
}

# The runner may only ever move a card to a PRE-APPROVAL status. APPROVED /
# POSTED / REJECTED are human-only decisions, structurally unreachable here.
_RUNNER_ALLOWED_STATUSES = (CardStatus.QUEUE, CardStatus.EDITED)


class ToolError(RuntimeError):
    """A tool-level problem surfaced to the model as a string, not a crash."""


class OwnershipError(ToolError):
    """The requested resource does not belong to the runner's organisation."""


@dataclass
class AutonomyEnv:
    """Injected, app-specific data access — the swappable seam between the
    autonomy engine and the Flask app (wired in web.py; faked in tests)."""

    load_run: Callable[[str], Optional[dict]]  # run_id -> run dict | None
    list_runs: Callable[
        [str], list
    ]  # org_id -> [ {id, meet_name, n_achievements, finished_at}, … ]
    owns_run: Callable[[str, str], bool]  # (org_id, run_id) -> owned?
    workflow: object  # a WorkflowStore (load / summary / set_status / set_edits)
    gen_caption: Callable[[dict, str], str]  # (achievement, instruction) -> caption text
    draft_slot: str = "ai_headline"  # workflow edited_captions slot to store a draft under
    audit: Optional[AuditLog] = None
    notify: Optional[Callable[[str, str, str], None]] = None  # (org, session, summary)


@dataclass
class ToolContext:
    """Immutable per-session context handed to every tool. ``org_id`` is bound
    once and is the sole tenancy source."""

    org_id: str
    session_id: str
    env: AutonomyEnv

    @property
    def audit(self) -> AuditLog:
        return self.env.audit or AuditLog()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    min_level: RunnerReach
    fn: Callable[["ToolContext", dict], str]


REGISTRY: dict[str, Tool] = {}


def _register(name: str, description: str, input_schema: dict, min_level: RunnerReach):
    def deco(fn: Callable[["ToolContext", dict], str]):
        REGISTRY[name] = Tool(name, description, input_schema, min_level, fn)
        return fn

    return deco


def tools_for_level(level: RunnerReach) -> list[dict]:
    """Anthropic-shaped schemas for exactly the tools allowed at ``level`` — the
    model is never even shown a tool above its level."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in REGISTRY.values()
        if t.min_level != RunnerReach.OFF and t.min_level <= level
    ]


def dispatch(ctx: ToolContext, level: RunnerReach, name: str, args: dict) -> str:
    """The single execution chokepoint. Only a registered tool permitted at the
    session's level is ever called; everything else is blocked + audited."""
    args = args if isinstance(args, dict) else {}
    tool = REGISTRY.get(name)
    if tool is None or tool.min_level == RunnerReach.OFF:
        ctx.audit.record(
            ctx.org_id, ctx.session_id, "blocked", tool=str(name), args=args, result="unknown tool"
        )
        return f"ERROR: unknown tool {name!r} — blocked. Use only the provided tools."
    if tool.min_level > level:
        ctx.audit.record(
            ctx.org_id,
            ctx.session_id,
            "blocked",
            tool=name,
            args=args,
            result=f"not permitted at level {int(level)}",
        )
        return f"ERROR: tool {name!r} is not permitted at this autonomy level — blocked."
    try:
        result = tool.fn(ctx, args)
    except (OwnershipError, ToolError) as e:
        result = f"ERROR: {e}"
    except Exception as e:  # a tool bug must never crash the loop
        log.warning("autonomy tool %s errored: %s", name, e)
        result = f"(tool {name!r} failed unexpectedly)"
    ctx.audit.record(ctx.org_id, ctx.session_id, "tool_call", tool=name, args=args, result=result)
    return result


# ── shared guards ──────────────────────────────────────────────────────────


def _require_run(ctx: ToolContext, args: dict) -> str:
    run_id = str(args.get("run_id") or "").strip()
    if not run_id:
        raise ToolError("run_id is required")
    if not ctx.env.owns_run(ctx.org_id, run_id):
        # Same message whether the run is absent or another org's, so the model
        # cannot probe for the existence of other tenants' runs.
        raise OwnershipError(f"run {run_id!r} was not found for this organisation")
    return run_id


def _load_owned_run(ctx: ToolContext, args: dict) -> tuple[str, dict]:
    run_id = _require_run(ctx, args)
    data = ctx.env.load_run(run_id)
    if not data:
        raise OwnershipError(f"run {run_id!r} was not found for this organisation")
    return run_id, data


def _safe_set_status(workflow, run_id: str, card_id: str, status: CardStatus, note: str) -> None:
    """The ONLY status write the runner may perform. Structurally refuses any
    non-pre-approval status, so the runner can never approve/post/reject."""
    if status not in _RUNNER_ALLOWED_STATUSES:
        raise ToolError("autonomy may only set a pre-approval status")
    workflow.set_status(run_id, card_id, status, notes=note)


def _ranked(run_data: dict) -> list[dict]:
    rr = run_data.get("recognition_report") or {}
    return rr.get("ranked_achievements") or []


def _card_id_of(ra: dict) -> str:
    ach = ra.get("achievement") or {}
    return str(ach.get("swim_id") or ach.get("swimmer_id") or ra.get("rank", "")).strip()


def _find_card(run_data: dict, card_id: str) -> Optional[dict]:
    card_id = (card_id or "").strip()
    for ra in _ranked(run_data):
        if _card_id_of(ra) == card_id:
            return ra
    return None


def _wf_status(ctx: ToolContext, run_id: str, card_id: str):
    """Read a card's workflow status, failing CLOSED on error.

    Returns the stored ``CardStatus``; ``CardStatus.QUEUE`` for a genuinely
    absent card (no state yet); and ``None`` when the read itself failed.
    ``None`` is deliberate: it is not in ``_RUNNER_ALLOWED_STATUSES``, so
    ``_queue_for_approval`` SKIPS the card rather than re-writing over a status a
    human may have set — the runner fails closed exactly when the state is least
    trustworthy, instead of assuming QUEUE and clobbering an approval."""
    try:
        st = ctx.env.workflow.load(run_id).get(card_id)
    except Exception:
        return None
    return st.status if st else CardStatus.QUEUE


# ── the fixed tool set ─────────────────────────────────────────────────────

_RUN_ID_SCHEMA = {
    "type": "object",
    "properties": {"run_id": {"type": "string", "description": "The run's id."}},
    "required": ["run_id"],
}
_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "description": "The run's id."},
        "card_id": {"type": "string", "description": "The card's id (from list_cards)."},
    },
    "required": ["run_id", "card_id"],
}


@_register(
    "list_recent_runs",
    "List this organisation's recent meet runs (id, meet, number of achievements). "
    "Start here to find a run to work on.",
    {"type": "object", "properties": {}},
    RunnerReach.SUGGEST,
)
def _list_recent_runs(ctx: ToolContext, args: dict) -> str:
    runs = ctx.env.list_runs(ctx.org_id) or []
    if not runs:
        return "(no runs found for this organisation)"
    lines = []
    for r in runs[:20]:
        lines.append(
            f"- run {r.get('id')}: {r.get('meet_name') or 'meet'} "
            f"— {r.get('n_achievements', 0)} achievements "
            f"(finished {r.get('finished_at') or '—'})"
        )
    return "\n".join(lines)


@_register(
    "get_run_summary",
    "Summarise one run: meet context and how many achievements were detected by "
    "quality band, plus how many cards are queued / approved / posted.",
    _RUN_ID_SCHEMA,
    RunnerReach.SUGGEST,
)
def _get_run_summary(ctx: ToolContext, args: dict) -> str:
    run_id, data = _load_owned_run(ctx, args)
    rr = data.get("recognition_report") or {}
    mc = rr.get("meet_context") or {}
    parts = [
        f"Run {run_id}: {mc.get('meet_name') or data.get('meet', {}) or 'meet'}",
        f"course={mc.get('course') or '—'} level={mc.get('meet_level') or '—'}",
        f"achievements={rr.get('n_achievements', 0)} "
        f"(elite={rr.get('n_elite', 0)}, strong={rr.get('n_strong', 0)}, "
        f"story={rr.get('n_story', 0)}, nice={rr.get('n_nice', 0)})",
    ]
    try:
        wf = ctx.env.workflow.summary(run_id)
        parts.append(
            f"review: queue={wf.get('queue', 0)} edited={wf.get('edited', 0)} "
            f"approved={wf.get('approved', 0)} posted={wf.get('posted', 0)}"
        )
    except Exception:
        pass
    return "\n".join(parts)


@_register(
    "list_cards",
    "List the content opportunities (cards) in a run — each with its id, the "
    "swimmer/event, the headline, quality band, confidence, and current review "
    "status. These are already ranked and detected; you cannot change that.",
    _RUN_ID_SCHEMA,
    RunnerReach.SUGGEST,
)
def _list_cards(ctx: ToolContext, args: dict) -> str:
    run_id, data = _load_owned_run(ctx, args)
    ranked = _ranked(data)
    if not ranked:
        return "(this run has no detected achievements)"
    out = []
    for ra in ranked[:40]:
        ach = ra.get("achievement") or {}
        cid = _card_id_of(ra)
        status = _wf_status(ctx, run_id, cid)
        out.append(
            f"- card {cid}: {ach.get('swimmer_name') or '?'} — {ach.get('event') or '?'} "
            f"| {ach.get('headline') or ach.get('type') or ''} "
            f"[band={ra.get('quality_band') or '?'}, conf={ach.get('confidence', '?')}, "
            f"status={getattr(status, 'value', status)}]"
        )
    return "\n".join(out)


@_register(
    "get_card_detail",
    "Get the full detail of one card: swimmer, event, the facts behind the "
    "achievement, the evidence, the confidence, and any current caption draft.",
    _CARD_SCHEMA,
    RunnerReach.SUGGEST,
)
def _get_card_detail(ctx: ToolContext, args: dict) -> str:
    run_id, data = _load_owned_run(ctx, args)
    ra = _find_card(data, str(args.get("card_id") or ""))
    if ra is None:
        raise ToolError(f"card {args.get('card_id')!r} not found in this run")
    ach = ra.get("achievement") or {}
    cid = _card_id_of(ra)
    lines = [
        f"card {cid} — {ach.get('swimmer_name') or '?'} — {ach.get('event') or '?'}",
        f"type={ach.get('type')} band={ra.get('quality_band')} confidence={ach.get('confidence')}",
        f"headline: {ach.get('headline') or '—'}",
        f"facts: {ach.get('raw_facts') or {}}",
        f"status: {getattr(_wf_status(ctx, run_id, cid), 'value', '?')}",
    ]
    sp = ra.get("safe_to_post") or {}
    if sp:
        lines.append(f"safe_to_post: {sp.get('level')} ({sp.get('reason')})")
    try:
        st = ctx.env.workflow.load(run_id).get(cid)
        if st and st.edited_captions:
            lines.append(f"current draft: {st.edited_captions}")
    except Exception:
        pass
    return "\n".join(lines)


@_register(
    "draft_caption",
    "Draft (or redraft) a caption for one card and save it as a DRAFT for the "
    "human to review. Provide a short instruction for the angle/emphasis. This "
    "never approves or posts — it only stores a draft.",
    {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "The run's id."},
            "card_id": {"type": "string", "description": "The card's id."},
            "instruction": {
                "type": "string",
                "description": "Short guidance for the caption (tone, angle, emphasis).",
            },
        },
        "required": ["run_id", "card_id"],
    },
    RunnerReach.DRAFT,
)
def _draft_caption(ctx: ToolContext, args: dict) -> str:
    run_id, data = _load_owned_run(ctx, args)
    ra = _find_card(data, str(args.get("card_id") or ""))
    if ra is None:
        raise ToolError(f"card {args.get('card_id')!r} not found in this run")
    ach = ra.get("achievement") or {}
    instruction = str(args.get("instruction") or "").strip()
    try:
        caption = ctx.env.gen_caption(ach, instruction)
    except Exception as e:
        # honest error — never fabricate a caption
        return f"(could not draft a caption: {e})"
    caption = (caption or "").strip()
    if not caption:
        return "(the caption generator returned nothing)"
    cid = _card_id_of(ra)
    try:
        ctx.env.workflow.set_edits(run_id, cid, {ctx.env.draft_slot: caption})
    except Exception as e:
        return f"(drafted, but could not save: {e})"
    return f"Saved a draft for card {cid} (status: edited, awaiting your review):\n{caption}"


@_register(
    "queue_for_approval",
    "Flag one or more prepared cards for the human's review queue, with a note. "
    "This NEVER approves or posts — a person still has to approve each card. "
    "Cards a human has already decided on are left untouched.",
    {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "The run's id."},
            "card_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The card ids to flag for review.",
            },
            "note": {"type": "string", "description": "A short note for the reviewer."},
        },
        "required": ["run_id", "card_ids"],
    },
    RunnerReach.PREPARE,
)
def _queue_for_approval(ctx: ToolContext, args: dict) -> str:
    run_id, data = _load_owned_run(ctx, args)
    card_ids = args.get("card_ids") or []
    if not isinstance(card_ids, list):
        raise ToolError("card_ids must be a list")
    runner_note = str(
        args.get("note") or "Prepared by the autonomy assistant — ready for your review."
    )
    # The runner must never be able to set a schedule: a note beginning
    # "scheduled:" is parsed as a schedule label by workflow/pack.py, so
    # neutralise that prefix on the model-supplied note.
    if runner_note.startswith("scheduled:"):
        runner_note = " " + runner_note
    flagged, skipped, missing = 0, 0, 0
    for raw in card_ids[:50]:
        cid = str(raw).strip()
        if _find_card(data, cid) is None:
            missing += 1
            continue
        current = _wf_status(ctx, run_id, cid)
        # Never override a human's decision (approved/posted/rejected) — only
        # ever (re)flag pre-approval cards.
        if current not in _RUNNER_ALLOWED_STATUSES:
            skipped += 1
            continue
        # Preserve any existing note (a human's note may carry a `scheduled:LABEL`
        # label) — only fall back to the runner's note when the card has none, so
        # flagging never clobbers a human's note or schedule.
        existing_note = ""
        try:
            st = ctx.env.workflow.load(run_id).get(cid)
            existing_note = (getattr(st, "notes", "") or "").strip() if st else ""
        except Exception:
            existing_note = ""
        # The reviewer-facing NOTE is the flag; the status is deliberately
        # re-written unchanged (QUEUE stays QUEUE, EDITED stays EDITED) so
        # flagging can never move a card anywhere new.
        _safe_set_status(ctx.env.workflow, run_id, cid, current, existing_note or runner_note)
        flagged += 1
    return (
        f"Flagged {flagged} card(s) for your review"
        + (f", skipped {skipped} already decided by a human" if skipped else "")
        + (f", {missing} not found" if missing else "")
        + ". Nothing has been approved or posted."
    )


__all__ = [
    "RunnerReach",
    "LEVEL_LABELS",
    "AutonomyEnv",
    "ToolContext",
    "Tool",
    "REGISTRY",
    "tools_for_level",
    "dispatch",
    "ToolError",
    "OwnershipError",
]
