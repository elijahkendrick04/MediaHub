"""The spec-patch contract (P6.2) — the deterministic heart of the copilot.

The conversational creative assistant never paints pixels. It proposes a
**SpecPatch**: a small, bounded list of structured edits to a persisted
``CreativeBrief``. This module is the contract that sits between the (possibly
hallucinated) model output and the deterministic renderer:

* :class:`PatchOp` / :class:`SpecPatch` — the typed shape.
* :func:`parse_patch` — coerce arbitrary model JSON into a ``SpecPatch``
  (unknown op kinds and out-of-vocabulary values are dropped, never guessed).
* :func:`apply_patch` — apply the valid ops to a **copy** of the brief
  (the source is never mutated) and return the new brief plus an explicit list
  of which ops were applied and which were rejected and *why*. A colour-role
  change is re-checked through the same APCA legibility gate the renderer uses
  (``quality.compliance``); an edit that would make the card illegible is
  rejected and the brief left unchanged for that op — never blindly painted.

There is **no LLM call here** — schema + validator + applier only, so it is
fully deterministic and unit-testable without any provider. Every edit is
auditable (the applied/rejected lists) and reversible (a new brief is returned;
the caller keeps the prior one).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from mediahub.creative_brief.design_spec import (
    ACCENT_TREATMENTS,
    COLOUR_ROLE_SLOTS,
    MOODS,
    MOTION_INTENTS,
)
from mediahub.creative_brief.generator import CreativeBrief

# Caption tones the assistant may set (mirrors web/ai_caption KNOWN_AI_TONES).
TONES: tuple[str, ...] = ("ai", "warm-club", "hype", "data-led")

# The closed vocabulary of edit operations the assistant may propose. Each maps
# to a single, reversible mutation on the brief; anything outside this set is
# dropped at parse time so a hallucinated op can never reach the renderer.
OP_KINDS: tuple[str, ...] = (
    "set_headline",  # text → text_layers.headline_line1
    "set_subhead",  # text → text_layers.headline_line2
    "set_hook",  # text → primary_hook
    "set_colour_role",  # slot, role → colour_role_assignment (APCA-gated)
    "set_archetype",  # archetype → layout_template
    "set_mood",  # mood → mood
    "set_motion_intent",  # motion_intent → motion_intent
    "set_accent_treatment",  # treatment → accent_style
    "set_format",  # format → format_priority (P6.1 catalogue)
    "set_tone",  # tone → tone
    "clear_photo",  # → photo_treatment = no-photo
)

# Bounds on free-text op fields so a runaway model can't bloat the brief.
_MAX_HEADLINE = 80
_MAX_HOOK = 80

# Bound on the ops list itself — apply_patch runs every op (set_colour_role
# re-runs the APCA role resolver each time), so a runaway/adversarial model
# returning thousands of ops would burn CPU in one turn. Far above any real
# assistant patch; the tail past the cap is dropped at parse time.
_MAX_OPS = 25

# 1.18 — each op maps to the lockable element it would change, so a locked
# element (collab.locks) refuses the matching op at patch time. Element keys
# mirror collab.locks.LOCKABLE_ELEMENTS.
_OP_ELEMENT: dict[str, str] = {
    "set_headline": "headline",
    "set_subhead": "subhead",
    "set_hook": "hook",
    "set_colour_role": "palette",
    "set_archetype": "layout",
    "set_accent_treatment": "accent",
    "set_format": "format",
    "clear_photo": "photo",
}


@dataclass(frozen=True)
class PatchOp:
    """One structured edit. ``params`` carries op-specific fields."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, **self.params}


@dataclass
class SpecPatch:
    """An ordered list of edits the assistant proposes for one design."""

    ops: list[PatchOp] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ops": [op.to_dict() for op in self.ops]}

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.ops)


@dataclass
class PatchResult:
    """The outcome of applying a patch: the new brief + an audit trail."""

    brief: CreativeBrief
    applied: list[PatchOp] = field(default_factory=list)
    # (op, human reason) for each rejected op — surfaced to the user verbatim.
    rejected: list[tuple[PatchOp, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def summary(self) -> str:
        """One human line describing what landed and what didn't."""
        bits = []
        if self.applied:
            bits.append(
                f"applied {len(self.applied)} change(s): "
                + ", ".join(_describe(o) for o in self.applied)
            )
        if self.rejected:
            bits.append(
                "skipped " + "; ".join(f"{_describe(o)} ({why})" for o, why in self.rejected)
            )
        return ". ".join(bits) if bits else "no changes."


def _describe(op: PatchOp) -> str:
    p = op.params
    if op.kind == "set_colour_role":
        return f"{op.kind} {p.get('slot')}→{p.get('role')}"
    if op.kind in (
        "set_archetype",
        "set_mood",
        "set_motion_intent",
        "set_accent_treatment",
        "set_format",
        "set_tone",
    ):
        return f"{op.kind} {next(iter(p.values()), '')}"
    return op.kind


# ---------------------------------------------------------------------------
# Parsing model output → a SpecPatch (drop, never guess)
# ---------------------------------------------------------------------------


def _clean_text(value: Any, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_len].strip()


def parse_patch(raw: Any) -> SpecPatch:
    """Coerce arbitrary model output into a :class:`SpecPatch`.

    Accepts ``{"ops": [...]}`` or a bare list. Each op must have a known
    ``kind``; out-of-vocabulary kinds and malformed ops are dropped (the
    validator/applier is the second gate, but parse already refuses to invent).
    The list itself is capped at ``_MAX_OPS`` valid ops — the "small, bounded"
    contract — and anything past the cap is dropped, matching the module's
    drop-never-guess parse behaviour.
    """
    if isinstance(raw, dict):
        items = raw.get("ops")
    elif isinstance(raw, list):
        items = raw
    else:
        items = None
    if not isinstance(items, list):
        return SpecPatch()
    ops: list[PatchOp] = []
    for it in items:
        if len(ops) >= _MAX_OPS:
            break
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "").strip()
        if kind not in OP_KINDS:
            continue
        params = {k: v for k, v in it.items() if k != "kind"}
        ops.append(PatchOp(kind=kind, params=params))
    return SpecPatch(ops=ops)


# ---------------------------------------------------------------------------
# Validation + application
# ---------------------------------------------------------------------------


def _live_archetypes() -> list[str]:
    try:
        from mediahub.graphic_renderer import archetypes as _a

        return list(_a.list_archetypes())
    except Exception:  # pragma: no cover
        return []


def _token_roles() -> list[str]:
    try:
        from mediahub.graphic_renderer import archetypes as _a

        return list(_a.TOKEN_ROLES)
    except Exception:  # pragma: no cover
        return ["primary", "secondary", "surface", "accent", "on_primary", "on_surface"]


def _colour_roles_legible(brief: CreativeBrief, brand_kit) -> bool:
    """True when the brief's resolved colour roles clear the APCA gate.

    Reuses the renderer's exact role resolver + the deterministic compliance
    check, so the assistant rejects exactly what the renderer would refuse to
    paint legibly. On any error (missing optional dep) it returns True — the
    renderer's own gate still runs at paint time, so we never hard-block here.
    """
    try:
        from mediahub.graphic_renderer.render import resolved_role_vars_for_brief
        from mediahub.quality.compliance import check_roles

        roles = resolved_role_vars_for_brief(brief, brand_kit)
        return check_roles(roles).passes
    except Exception:
        return True


def _apply_one(
    op: PatchOp, brief: CreativeBrief, *, brand_kit, archetypes: list[str]
) -> Optional[str]:
    """Apply ``op`` onto ``brief`` in place; return None on success or a reason.

    Caller passes a *copy* of the brief — this mutates it. Colour-role edits are
    staged then re-checked against the APCA gate; an illegible result is
    reverted and rejected with a reason.
    """
    p = op.params
    if op.kind == "set_headline":
        text = _clean_text(p.get("text"), _MAX_HEADLINE)
        if not text:
            return "no text given"
        brief.text_layers = {**(brief.text_layers or {}), "headline_line1": text}
        return None
    if op.kind == "set_subhead":
        text = _clean_text(p.get("text"), _MAX_HEADLINE)
        brief.text_layers = {**(brief.text_layers or {}), "headline_line2": text}
        return None
    if op.kind == "set_hook":
        text = _clean_text(p.get("text"), _MAX_HOOK)
        if not text:
            return "no text given"
        brief.primary_hook = text
        return None
    if op.kind == "set_colour_role":
        slot = str(p.get("slot") or "").strip().lower()
        role = str(p.get("role") or "").strip().lower()
        if slot not in COLOUR_ROLE_SLOTS:
            return f"unknown slot {slot!r}"
        if role not in _token_roles():
            return f"unknown colour role {role!r}"
        prior = dict(getattr(brief, "colour_role_assignment", {}) or {})
        staged = {**prior, slot: role}
        brief.colour_role_assignment = staged
        if not _colour_roles_legible(brief, brand_kit):
            brief.colour_role_assignment = prior  # revert — never paint illegibly
            return "would fail the legibility (APCA) check"
        return None
    if op.kind == "set_archetype":
        arch = str(p.get("archetype") or "").strip()
        if arch not in archetypes:
            return f"unknown layout {arch!r}"
        brief.layout_template = arch
        return None
    if op.kind == "set_mood":
        mood = str(p.get("mood") or "").strip().lower()
        if mood not in MOODS:
            return f"unknown mood {mood!r}"
        brief.mood = mood
        return None
    if op.kind == "set_motion_intent":
        mi = str(p.get("motion_intent") or "").strip().lower()
        if mi not in MOTION_INTENTS:
            return f"unknown motion intent {mi!r}"
        brief.motion_intent = mi
        return None
    if op.kind == "set_accent_treatment":
        t = str(p.get("treatment") or "").strip().lower()
        if t not in ACCENT_TREATMENTS:
            return f"unknown accent treatment {t!r}"
        brief.accent_style = t
        return None
    if op.kind == "set_format":
        from mediahub.club_platform.format_catalog import format_for

        slug = str(p.get("format") or "").strip()
        spec = format_for(slug)
        if spec is None:
            return f"unknown format {slug!r}"
        rest = [f for f in (brief.format_priority or []) if f != spec.render_name]
        brief.format_priority = [spec.render_name] + rest
        return None
    if op.kind == "set_tone":
        tone = str(p.get("tone") or "").strip().lower()
        if tone not in TONES:
            return f"unknown tone {tone!r}"
        brief.tone = tone
        return None
    if op.kind == "clear_photo":
        brief.photo_treatment = "no-photo"
        brief.image_treatment = "no photo, text-led layout"
        return None
    return "unknown operation"  # pragma: no cover - parse already filters


def apply_patch(
    brief: CreativeBrief, patch: SpecPatch, *, brand_kit=None, locked_elements=None
) -> PatchResult:
    """Apply ``patch`` to a copy of ``brief``; return the new brief + audit trail.

    The source brief is never mutated. Each op is validated against the closed
    vocabularies; colour-role edits are additionally re-checked against the APCA
    legibility gate. Valid ops are applied in order; invalid ones are recorded
    in ``rejected`` with a human reason. The dedupe/audit signature is re-stamped
    so downstream callers see the edited design.

    ``locked_elements`` (1.18) is the set of element keys a reviewer has locked
    on this card (``collab.locks``); an op that would change a locked element is
    refused before it touches the brief, recorded in ``rejected`` with a clear
    reason — so a lock holds even against the copilot.
    """
    new = CreativeBrief.from_dict(brief.to_dict()) if isinstance(brief, CreativeBrief) else None
    if new is None:
        raise ValueError("apply_patch requires a CreativeBrief")
    locks = {str(e).strip().lower() for e in (locked_elements or set())}
    archetypes = _live_archetypes()
    applied: list[PatchOp] = []
    rejected: list[tuple[PatchOp, str]] = []
    for op in patch.ops:
        locked_el = _OP_ELEMENT.get(op.kind)
        if locked_el and locked_el in locks:
            rejected.append((op, f"the {locked_el} is locked on this card"))
            continue
        reason = _apply_one(op, new, brand_kit=brand_kit, archetypes=archetypes)
        if reason is None:
            applied.append(op)
        else:
            rejected.append((op, reason))
    if applied:
        # A changed design is a NEW, distinct version: fresh id (so it persists
        # alongside the original — reversible) and a re-stamped signature.
        import uuid as _uuid

        new.id = "cb_" + _uuid.uuid4().hex[:12]
        try:
            from mediahub.creative_brief.generator import _stamp_signature

            new.ai_directed = True
            _stamp_signature(new)
        except Exception:  # pragma: no cover
            pass
    return PatchResult(brief=new, applied=applied, rejected=rejected)


__all__ = [
    "OP_KINDS",
    "TONES",
    "PatchOp",
    "SpecPatch",
    "PatchResult",
    "parse_patch",
    "apply_patch",
]
