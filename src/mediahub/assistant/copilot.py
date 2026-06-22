"""The club content copilot (P6.2) — orchestrates one conversational turn.

Ties the pieces together: the bounded tool loop (``ai_core.ask_with_tools``)
drives the model through *read the design / brand / facts → propose a structured
edit*; every proposed :class:`~mediahub.assistant.patch.SpecPatch` is validated
and applied to a working copy of the brief (APCA-gated), with the real
applied/rejected result fed back so the model can react. Org preferences
(:mod:`mediahub.assistant.memory`) ride in the system prompt. The turn is
recorded in the session (auditable, reversible).

Honest about failure: with no provider configured the turn returns an honest
message and leaves the design untouched — the UI's manual controls keep working
(the deterministic engine, the catalogue, the renderer all run without AI).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from mediahub.assistant import memory as _memory
from mediahub.assistant import tools as _tools
from mediahub.assistant.patch import PatchOp, SpecPatch, apply_patch
from mediahub.assistant.session import AssistantSession
from mediahub.creative_brief.generator import CreativeBrief

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are the club content copilot for a sports club's social graphics. You "
    "help a volunteer edit ONE already-designed card by conversation. You never "
    "paint pixels and you never publish — you change the design only by calling "
    "propose_edit with structured ops, which a deterministic renderer then "
    "applies. Rules:\n"
    "- Read the design, brand and facts before editing.\n"
    "- Use ONLY the verified facts for any number, name or time — never invent a "
    "stat.\n"
    "- Reassign colour ROLES (e.g. make the accent the secondary brand colour); "
    "never invent hex values. An edit that would be illegible is rejected — react "
    "to that, don't fight it.\n"
    "- Keep copy punchy and on-brand; no emoji, no AI cliches ('delve', "
    "'elevate').\n"
    "- When the request is just a question ('why did this rank first?'), answer "
    "from the facts without editing.\n"
    "- After proposing edits, reply with one short sentence telling the user what "
    "you changed."
)


@dataclass
class AssistantTurn:
    """The result of one copilot turn."""

    reply: str
    brief: CreativeBrief
    applied: list[PatchOp] = field(default_factory=list)
    rejected: list[tuple] = field(default_factory=list)  # (PatchOp, reason)
    provider: str = ""
    ai_available: bool = True
    changed: bool = False

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "applied": [op.to_dict() for op in self.applied],
            "rejected": [[op.to_dict(), reason] for op, reason in self.rejected],
            "provider": self.provider,
            "ai_available": self.ai_available,
            "changed": self.changed,
        }


_NO_PROVIDER_MSG = (
    "The conversational assistant needs an AI provider, which isn't configured on "
    "this deployment. Your manual controls still work — edit the caption, pick a "
    "format, change the photo or accent directly."
)


def run_turn(
    *,
    session: AssistantSession,
    user_message: str,
    brief: CreativeBrief,
    brand_kit=None,
    facts: Optional[dict] = None,
    profile_id: str = "",
    max_rounds: int = 4,
    locked_elements=None,
) -> AssistantTurn:
    """Run one conversational edit turn against ``brief``.

    Returns an :class:`AssistantTurn` whose ``brief`` is the (possibly edited)
    new brief — the input is never mutated. Records the turn on ``session`` and
    saves it. Never raises for a provider problem: an unconfigured/erroring
    provider yields an honest reply with the design unchanged.

    ``locked_elements`` (1.18) — element keys a reviewer has locked on this card;
    the copilot's edits to those elements are refused at patch time.
    """
    user_message = (user_message or "").strip()
    session.add_message("user", user_message)

    # Working brief evolves within the turn; each accepted op chains onto it.
    work = CreativeBrief.from_dict(brief.to_dict())
    design_ref = {"brief": work}
    applied_all: list[PatchOp] = []
    rejected_all: list[tuple] = []

    def on_propose(patch: SpecPatch) -> str:
        res = apply_patch(
            design_ref["brief"], patch, brand_kit=brand_kit, locked_elements=locked_elements
        )
        design_ref["brief"] = res.brief
        applied_all.extend(res.applied)
        rejected_all.extend(res.rejected)
        return res.summary()

    dispatch = _tools.make_dispatch(
        design_ref=design_ref, brand_kit=brand_kit, facts=facts, on_propose=on_propose
    )

    mem_block = _memory.as_prompt_block(profile_id, user_message) if profile_id else ""
    system = _SYSTEM + (("\n\n" + mem_block) if mem_block else "")
    user = _build_user_prompt(session, user_message)

    try:
        from mediahub.ai_core import ask_with_tools, ProviderNotConfigured, ProviderError

        convo = ask_with_tools(
            system,
            user,
            tools=_tools.TOOLS,
            on_tool_call=dispatch,
            max_tokens=1200,
            max_rounds=max_rounds,
        )
    except ProviderNotConfigured:
        session.add_message("assistant", _NO_PROVIDER_MSG)
        _save(session)
        return AssistantTurn(reply=_NO_PROVIDER_MSG, brief=brief, ai_available=False, changed=False)
    except ProviderError as e:
        msg = f"The assistant hit a provider error and made no changes: {str(e)[:200]}"
        session.add_message("assistant", msg)
        _save(session)
        return AssistantTurn(reply=msg, brief=brief, ai_available=True, changed=False)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("copilot turn failed: %s", e)
        msg = "The assistant ran into a problem and made no changes. Try rephrasing."
        session.add_message("assistant", msg)
        _save(session)
        return AssistantTurn(reply=msg, brief=brief, ai_available=True, changed=False)

    final = design_ref["brief"]
    reply = (convo.text or "").strip() or _default_reply(applied_all, rejected_all)
    session.add_message("assistant", reply)
    if applied_all or rejected_all:
        session.add_edit(
            applied=applied_all,
            rejected=rejected_all,
            brief_before=brief.id,
            brief_after=final.id,
        )
    _save(session)
    return AssistantTurn(
        reply=reply,
        brief=final,
        applied=applied_all,
        rejected=rejected_all,
        provider=getattr(convo, "provider", ""),
        ai_available=True,
        changed=bool(applied_all),
    )


def _build_user_prompt(session: AssistantSession, user_message: str) -> str:
    history = session.recent_chat(8)[:-1]  # exclude the message we just added
    if not history:
        return user_message
    lines = [f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history]
    return "Conversation so far:\n" + "\n".join(lines) + f"\n\nNew request: {user_message}"


def _default_reply(applied: list[PatchOp], rejected: list[tuple]) -> str:
    if applied:
        return "Done — updated the design."
    if rejected:
        return "I couldn't apply that change (see the skipped edits)."
    return "I didn't change anything."


def _save(session: AssistantSession) -> None:
    try:
        from mediahub.assistant.session import save_session

        save_session(session)
    except Exception:  # pragma: no cover
        log.debug("assistant session save skipped", exc_info=True)


# ---------------------------------------------------------------------------
# Planner-seeded prompt suggestions (non-generic)
# ---------------------------------------------------------------------------

_FALLBACK_SUGGESTIONS = (
    "Make the headline punchier",
    "Switch this to a square post",
    "Lead with the time",
    "Make the accent the club's secondary colour",
    "Try a bolder layout",
)


def suggested_prompts(profile_id: str = "", sport: str = "", *, limit: int = 5) -> list[str]:
    """Prompt chips for the copilot, seeded from the planner's ranked items.

    Falls back to a small editing-focused default set when the planner has no
    profile/sport or is unavailable — never generic AI filler.
    """
    out: list[str] = []
    if profile_id and sport:
        try:
            from mediahub.content_engine.planner import build_content_plan

            plan = build_content_plan(sport, profile_id)
            for item in plan.items[:limit]:
                title = getattr(item, "title", "") or ""
                if title:
                    out.append(f"Make a {title.lower()}")
        except Exception:
            out = []
    for s in _FALLBACK_SUGGESTIONS:
        if len(out) >= limit:
            break
        if s not in out:
            out.append(s)
    return out[:limit]


__all__ = ["AssistantTurn", "run_turn", "suggested_prompts"]
