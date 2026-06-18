"""
turn_into — sport-native Turn-Into engine.

Takes a single processed meet (run_data + ClubProfile) and produces a fixed
set of eight derivative content artefacts in one click:

    1. meet_recap        — single feed card + caption
    2. swimmer_spotlight — one card per top-3 swimmer
    3. data_thread       — 3-5 numbered X/LinkedIn posts
    4. parent_newsletter — email-ready: subject + preheader + HTML + plain text
    5. club_report       — long-form website report (~350-450 words)
    6. sponsor_thank_you — only if sponsor_name is set
    7. coach_quote       — flagged DRAFT, needs coach approval
    8. next_meet_preview — only if next meet info present, else skipped

The public entry point is :func:`turn_meet_into_pack`. Per-artefact builders
live in :mod:`mediahub.turn_into.templates`.

All builders reuse the existing brand kit, voice profile, and the
``generate_caption_for_tone`` primitive (long-form artefacts use the same
brand briefing via ``media_ai.generate``) — there is no parallel generation
pipeline here.
"""

from __future__ import annotations

from .pipeline import turn_meet_into_pack, save_pack, load_pack, list_packs
from .transform import transform_design, blank_brief_for_format, TransformResult

__all__ = [
    "turn_meet_into_pack",
    "save_pack",
    "load_pack",
    "list_packs",
    # turn_into v2 — the P6.1 format transformer ("turn this into that").
    "transform_design",
    "blank_brief_for_format",
    "TransformResult",
]
