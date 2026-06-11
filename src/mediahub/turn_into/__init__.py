"""
turn_into — sport-native Turn-Into engine.

Takes a single processed meet (run_data + ClubProfile) and produces a fixed
set of seven derivative content artefacts in one click:

    1. meet_recap        — single feed card + caption
    2. swimmer_spotlight — one card per top-3 swimmer
    3. data_thread       — 3-5 numbered X/LinkedIn posts
    4. parent_newsletter — HTML + plain-text (~200 words)
    5. sponsor_thank_you — only if sponsor_name is set
    6. coach_quote       — flagged DRAFT, needs coach approval
    7. next_meet_preview — only if next meet info present, else skipped

The public entry point is :func:`turn_meet_into_pack`. Per-artefact builders
live in :mod:`mediahub.turn_into.templates`.

All builders reuse the existing brand kit, voice profile, and the
``generate_caption_for_tone`` primitive — there is no parallel generation
pipeline here.
"""

from __future__ import annotations

from .pipeline import turn_meet_into_pack, save_pack, load_pack, list_packs

__all__ = ["turn_meet_into_pack", "save_pack", "load_pack", "list_packs"]
