"""mediahub/web/caption_assist.py — inline "you write, AI assists" caption transforms.

Refines an EXISTING caption (shorter / punchier / add the time / tidy / custom)
instead of regenerating from scratch, by feeding the current caption + the
requested change to the existing caption writer via its ``requirements`` channel
(``ai_caption.generate_caption_for_tone``). The deterministic facts — names,
times, events — are preserved by instruction, and the AI remains the only
judgement (exactly as for a fresh caption), so this adds no new judgement
surface — only a faster way to nudge wording on the review screen.
"""

from __future__ import annotations

# Preset one-click transforms (slug -> instruction). `custom` is free text.
# The Magic-Write-class operations (P6.2) — summarise / expand / rewrite — join
# the original review-screen nudges; all run through the same "revise, don't
# regenerate, keep every fact" requirements channel. A tone shift is not a
# preset: it's the ``tone=`` argument (warm-club / hype / data-led), so the same
# text can be re-voiced without a new instruction.
PRESETS = {
    "shorter": "Make it shorter and punchier — keep only the essentials.",
    "fuller": "Add a little more warmth and detail, without padding.",
    "punchier": "Tighten it and lead with the strongest concrete beat — the time, the placing, the moment.",
    "calmer": "Make it warmer and more understated.",
    "add_time": "Make sure the swimmer's time is mentioned naturally.",
    "tidy": "Tidy the grammar and flow without changing the meaning.",
    # --- P6.2 Magic-Write text tools ---
    "summarise": "Summarise it to one tight, punchy sentence — the single most important point.",
    "expand": "Expand it with one more relevant, on-brand detail — no padding, no invented facts.",
    "rewrite": "Rewrite it from a fresh angle while keeping every fact and the same meaning.",
}

# Short labels for the review-screen buttons.
PRESET_LABELS = {
    "shorter": "Shorter",
    "fuller": "Fuller",
    "punchier": "Punchier",
    "calmer": "Calmer",
    "add_time": "Add time",
    "tidy": "Tidy up",
    "summarise": "Summarise",
    "expand": "Expand",
    "rewrite": "Rewrite",
}


def resolve_instruction(transform: str, custom: str = "") -> str:
    """Map a transform slug (or `custom` + free text) to an instruction string."""
    transform = (transform or "").strip().lower()
    if transform in PRESETS:
        return PRESETS[transform]
    # `custom`, or any unknown slug accompanied by free text, uses the free text.
    return (custom or "").strip()


def build_requirements(current_caption: str, instruction: str) -> str:
    """Build the `requirements` brief that asks the writer to REVISE an existing
    caption (preserving every fact) rather than start over."""
    current = (current_caption or "").strip()
    instruction = (instruction or "").strip() or "Improve this caption."
    return (
        "Revise the existing caption below rather than starting over. Keep every "
        "fact (names, times, events, places) exactly as written — change only the "
        "wording as requested. Output ONLY the revised caption, with no preamble.\n\n"
        f'Existing caption:\n"""\n{current}\n"""\n\n'
        f"Change requested: {instruction}"
    )


def assist_caption(
    achievement: dict,
    current_caption: str,
    transform: str,
    *,
    custom: str = "",
    club_brand: dict | None = None,
    club_profile=None,
    tone: str = "warm-club",
    voice_profile: dict | None = None,
) -> str:
    """Return a revised caption. Raises ``ValueError`` for an empty instruction;
    propagates the writer's ``ClaudeUnavailableError`` when no provider exists."""
    instruction = resolve_instruction(transform, custom)
    if not instruction:
        raise ValueError("no transform instruction supplied")
    from mediahub.web.ai_caption import (  # noqa: PLC0415
        _contains_ai_tell,
        generate_caption_for_tone,
    )

    requirements = build_requirements(current_caption, instruction)

    def _write(req: str) -> str:
        return generate_caption_for_tone(
            achievement,
            club_brand,
            tone=tone,
            voice_profile=voice_profile,
            club_profile=club_profile,
            requirements=req,
        )

    revised = _write(requirements)
    # The assist surface returns one caption straight to the reviewer, so it
    # bypasses the live route's post-generation AI-tell filter. If the model
    # slipped a banned cliché in, spend ONE more call to rewrite it out —
    # bounded, and only paid when a tell is actually present.
    if revised and _contains_ai_tell(revised):
        retry = _write(
            requirements + "\n\nYour previous attempt used a banned filler cliché. Rewrite it "
            "without any such phrase, keeping every fact exactly."
        )
        if retry and not _contains_ai_tell(retry):
            revised = retry
    return revised


__all__ = [
    "PRESETS",
    "PRESET_LABELS",
    "resolve_instruction",
    "build_requirements",
    "assist_caption",
]
