"""assistant — the club content copilot (P6.2).

A conversational creative assistant that edits an already-designed card by
emitting **structured, validated patches** to its ``CreativeBrief`` (never
painting pixels, never publishing). The agent rides the bounded
``ai_core.ask_with_tools`` loop with a fixed read/propose tool allow-list; every
proposed edit is vocabulary- and APCA-checked before it touches the brief, and
every turn is recorded for audit + reversibility.

Modules:
  * ``patch``    — the SpecPatch schema + deterministic validator/applier.
  * ``tools``    — the bounded tool allow-list for ``ask_with_tools``.
  * ``session``  — per-(run, card) conversation + edit-history store.
  * ``memory``   — org assistant preference book (inspect/delete; gated writes).
  * ``copilot``  — orchestrates one conversational turn; honest no-provider error.

Magic-Write-class caption text-tools live on the shipped caption engine
(``web/caption_assist.py``), and voice input rides the ASR seam
(``assistant/asr.py``) with browser speech capture — both honest-erroring until
a provider lands.
"""

from __future__ import annotations

from .copilot import AssistantTurn, run_turn, suggested_prompts
from .patch import PatchOp, PatchResult, SpecPatch, apply_patch, parse_patch
from .session import AssistantSession, create_session, get_or_create, load_session

__all__ = [
    "AssistantTurn",
    "run_turn",
    "suggested_prompts",
    "SpecPatch",
    "PatchOp",
    "PatchResult",
    "parse_patch",
    "apply_patch",
    "AssistantSession",
    "create_session",
    "load_session",
    "get_or_create",
]
