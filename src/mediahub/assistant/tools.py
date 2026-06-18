"""The copilot's bounded tool allow-list (P6.2).

The conversational assistant rides ``ai_core.ask_with_tools`` with a **fixed**
set of tools — a deliberately small allow-list that can *read* the design, brand
and run facts, *list* the format catalogue, and *propose* a structured edit.
There is deliberately **no tool that publishes, posts, writes outside the staged
patch, or reaches the network** — the same human-approval-before-publish rule
that governs the rest of MediaHub, enforced by simply never giving the agent the
capability.

Each tool is an Anthropic-shape dict (``name`` / ``description`` /
``input_schema``) — the format ``ask_with_tools`` normalises for Gemini and
OpenAI-compatible providers too. The handler (``make_dispatch``) is a pure
closure over the current design context; the ``propose_edit`` tool stages a
:class:`~mediahub.assistant.patch.SpecPatch` for the orchestrator to validate and
apply (the model never mutates the brief directly).
"""

from __future__ import annotations

from typing import Callable, Optional

from mediahub.assistant.patch import OP_KINDS, SpecPatch, parse_patch

# ---------------------------------------------------------------------------
# Tool schemas (read-only + propose; never publish)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "read_design",
        "description": (
            "Read the current design you are editing: its layout, colours, "
            "headline, hook, mood, format and whether it has a photo. Call this "
            "first to see what you're working with."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_brand",
        "description": (
            "Read the club's brand: name, the palette hex values and the colour "
            "role names you may assign (primary, secondary, surface, accent, "
            "on_primary, on_surface). Never invent a hex — only reassign roles."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_facts",
        "description": (
            "Read the verified facts behind this card (athlete, event, time, "
            "placing, why it ranked). Use these for the copy — never invent a "
            "stat that isn't here."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_formats",
        "description": (
            "List the design formats you can switch this design to (social "
            "sizes, poster, certificate, wallpaper, …) with their slugs. Use a "
            "slug with set_format in propose_edit."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "propose_edit",
        "description": (
            "Propose a set of structured edits to the design. This is how you "
            "change anything — you never paint pixels. Each edit is one op from "
            "the allowed kinds: " + ", ".join(OP_KINDS) + ". The system "
            "validates every op (vocabulary + colour legibility) and applies the "
            "valid ones, then re-renders. Call this once you know the change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ops": {
                    "type": "array",
                    "description": "The edits to apply, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": list(OP_KINDS)},
                            "text": {"type": "string"},
                            "slot": {"type": "string"},
                            "role": {"type": "string"},
                            "archetype": {"type": "string"},
                            "mood": {"type": "string"},
                            "motion_intent": {"type": "string"},
                            "treatment": {"type": "string"},
                            "format": {"type": "string"},
                            "tone": {"type": "string"},
                        },
                        "required": ["kind"],
                    },
                }
            },
            "required": ["ops"],
        },
    },
]


def tool_names() -> list[str]:
    return [t["name"] for t in TOOLS]


# ---------------------------------------------------------------------------
# The dispatcher — a pure closure over the design context
# ---------------------------------------------------------------------------


def _design_summary(brief) -> str:
    layers = getattr(brief, "text_layers", {}) or {}
    roles = getattr(brief, "colour_role_assignment", {}) or {}
    fmt = (getattr(brief, "format_priority", []) or ["story"])[0]
    return (
        f"layout (archetype): {getattr(brief, 'layout_template', '')}\n"
        f"format: {fmt}\n"
        f"headline: {layers.get('headline_line1', '') or '(none)'}\n"
        f"subhead: {layers.get('headline_line2', '') or '(none)'}\n"
        f"hook: {getattr(brief, 'primary_hook', '') or '(none)'}\n"
        f"mood: {getattr(brief, 'mood', '') or '(default)'}\n"
        f"motion: {getattr(brief, 'motion_intent', '') or '(default)'}\n"
        f"accent treatment: {getattr(brief, 'accent_style', '') or '(default)'}\n"
        f"colour role overrides: {roles or '(brand defaults)'}\n"
        f"photo: {'no' if getattr(brief, 'photo_treatment', '') == 'no-photo' else 'yes/auto'}\n"
        f"tone: {getattr(brief, 'tone', '')}"
    )


def _brand_summary(brand_kit) -> str:
    if brand_kit is None:
        return "No brand kit loaded; using safe defaults."
    name = getattr(brand_kit, "display_name", "") or ""
    pri = getattr(brand_kit, "primary_colour", "") or ""
    sec = getattr(brand_kit, "secondary_colour", "") or ""
    acc = getattr(brand_kit, "accent_colour", "") or ""
    return (
        f"club: {name}\n"
        f"palette: primary {pri}, secondary {sec}, accent {acc}\n"
        "assignable colour roles: primary, secondary, surface, accent, on_primary, on_surface\n"
        "(reassign roles only — never change the hex values)"
    )


def _facts_summary(facts: Optional[dict]) -> str:
    if not facts:
        return "No structured facts available for this card."
    keys = (
        "swimmer_name",
        "athlete_name",
        "event",
        "event_name",
        "time",
        "result_time",
        "place",
        "headline",
        "why",
    )
    bits = []
    for k in keys:
        v = facts.get(k)
        if v:
            bits.append(f"{k}: {v}")
    return "\n".join(bits) or "No structured facts available for this card."


def _formats_summary() -> str:
    try:
        from mediahub.club_platform.format_catalog import all_formats

        return "\n".join(f"- {f.slug}: {f.title} ({f.width}x{f.height})" for f in all_formats())
    except Exception:  # pragma: no cover
        return "(format catalogue unavailable)"


def make_dispatch(
    *,
    design_ref: dict,
    brand_kit=None,
    facts: Optional[dict] = None,
    on_propose: Callable[[SpecPatch], str],
) -> Callable[[str, dict], str]:
    """Build the ``on_tool_call`` handler bound to one design context.

    ``design_ref`` is a mutable ``{"brief": CreativeBrief}`` so ``read_design``
    always reflects edits applied earlier in the same turn. ``on_propose`` is
    called with the parsed :class:`SpecPatch`; it applies the patch (validating
    every op) and returns a human result string that is fed back to the model so
    it can react to what actually landed.
    """

    def dispatch(name: str, args: dict) -> str:
        args = args or {}
        if name == "read_design":
            return _design_summary(design_ref.get("brief"))
        if name == "read_brand":
            return _brand_summary(brand_kit)
        if name == "read_facts":
            return _facts_summary(facts)
        if name == "list_formats":
            return _formats_summary()
        if name == "propose_edit":
            patch = parse_patch(args)
            if not patch.ops:
                return "No valid edits in that proposal — use the allowed op kinds."
            return on_propose(patch)
        return f"(unknown tool: {name})"

    return dispatch


__all__ = ["TOOLS", "tool_names", "make_dispatch"]
