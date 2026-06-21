"""brand/check.py — Brand Check + Brand Assist (roadmap 1.12).

Canva/Adobe ship "Brand Check" (does this design obey the brand kit?) and
"Brand Assist" (real-time on-brand suggestions + auto-fix). MediaHub's version
keeps the **judgement deterministic** and the **advice optional**:

* :func:`check_brief` scores a :class:`~mediahub.creative_brief.generator.CreativeBrief`
  against a :class:`~mediahub.brand.kits.BrandKitRef` using only the existing
  colour-science maths — CIEDE2000 palette distance (``coloraide``), the APCA
  legibility gate (:mod:`mediahub.quality.compliance`), the logo clear-space /
  contrast gate (:func:`mediahub.theming.logo_chip.decide_logo_chip`), and a
  flat font-pairing comparison. **No LLM** — "is this on-brand?" is exactly the
  kind of reproducible check the deterministic-engine rule says must not be
  AI-replaced.

* :func:`advise` and :func:`autofix` are the *optional* AI layer. ``advise``
  returns short human notes; ``autofix`` asks the model for a
  :class:`~mediahub.assistant.patch.SpecPatch` and runs it through the **same**
  ``parse_patch`` → ``apply_patch`` machinery the copilot uses (P6.2), so every
  proposed fix is re-validated through the deterministic gate before it can
  touch a brief. Both honest-error when no provider is configured — never a
  fabricated note or a guessed fix.

The report's :attr:`BrandCheckReport.locked_failures` is what the approval gate
(roadmap 1.12 build 4) reads: a failed check on a token the kit has *locked*
blocks a volunteer from shipping off-brand.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# A brief colour within this CIEDE2000 distance of a kit colour counts as "the
# kit colour" — comfortably above the ~2 just-noticeable-difference and the ~10
# ColorBrewer distinctness floor, so tone-mapped renders pass but a genuinely
# different hue (an off-palette manual override) fails.
PALETTE_DELTA_E_MAX = 12.0


# --------------------------------------------------------------------------
# Report data model
# --------------------------------------------------------------------------


@dataclass
class BrandCheckFinding:
    """One deterministic check's verdict."""

    check: str  # "palette" | "contrast" | "fonts" | "logo"
    passed: bool
    score: float  # 0..1
    detail: str
    offenders: list[str] = field(default_factory=list)
    locked: bool = False  # True when the kit has locked the token this check covers

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BrandCheckReport:
    """The full Brand Check verdict for one design against one kit."""

    kit_id: str
    findings: list[BrandCheckFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(f.passed for f in self.findings)

    @property
    def score(self) -> float:
        if not self.findings:
            return 1.0
        return round(min(f.score for f in self.findings), 3)

    @property
    def locked_failures(self) -> list[BrandCheckFinding]:
        """Failed checks on tokens the kit has locked — the approval blockers."""
        return [f for f in self.findings if f.locked and not f.passed]

    def explain(self) -> str:
        if self.passed:
            return f"on-brand (score {self.score:.2f})"
        bad = ", ".join(f"{f.check}: {f.detail}" for f in self.findings if not f.passed)
        return f"off-brand — {bad}"

    def to_dict(self) -> dict:
        return {
            "kit_id": self.kit_id,
            "passed": self.passed,
            "score": self.score,
            "findings": [f.to_dict() for f in self.findings],
            "locked_failures": [f.check for f in self.locked_failures],
            "explanation": self.explain(),
        }


# --------------------------------------------------------------------------
# Colour-science helpers (deterministic — reuse existing maths)
# --------------------------------------------------------------------------


def _is_hex(v) -> bool:
    return isinstance(v, str) and v.strip().startswith("#") and len(v.strip()) in (4, 7)


def _delta_e_2000(a: str, b: str) -> float:
    """CIEDE2000 distance between two hex colours (same maths as logo_chip)."""
    from coloraide import Color

    return float(Color(a).delta_e(Color(b), method="2000"))


def _min_delta_e(colour: str, palette: list[str]) -> float:
    """Smallest CIEDE2000 distance from ``colour`` to any palette colour."""
    distances = [_delta_e_2000(colour, p) for p in palette if _is_hex(p)]
    return min(distances) if distances else 999.0


def _coerce_brief(brief):
    """Accept a CreativeBrief or its dict form; return a CreativeBrief or None."""
    from mediahub.creative_brief.generator import CreativeBrief

    if isinstance(brief, CreativeBrief):
        return brief
    if isinstance(brief, dict):
        return CreativeBrief.from_dict(brief)
    return None


# --------------------------------------------------------------------------
# The four deterministic checks
# --------------------------------------------------------------------------


def _palette_finding(brief, kit, *, delta_e_max: float) -> BrandCheckFinding:
    locked = kit.is_locked("palette")
    kit_palette = [c for c in (kit.palette or {}).values() if _is_hex(c)]
    used = [c for c in (brief.palette or {}).values() if _is_hex(c)]
    if not kit_palette or not used:
        # Nothing to compare against — treat as a pass with full score so an
        # un-themed kit never blocks (honest: we can't measure drift).
        return BrandCheckFinding(
            "palette", True, 1.0, "no kit palette to compare against", locked=locked
        )
    offenders: list[str] = []
    worst = 0.0
    for colour in used:
        d = _min_delta_e(colour, kit_palette)
        worst = max(worst, d)
        if d > delta_e_max:
            offenders.append(colour)
    passed = not offenders
    # Score: how far the worst colour is, normalised against 2× the threshold.
    score = round(max(0.0, 1.0 - worst / (2 * delta_e_max)), 3)
    if passed:
        detail = f"all colours within ΔE {delta_e_max:.0f} of the kit palette"
    else:
        detail = f"off-palette colour(s): {', '.join(offenders)} (ΔE>{delta_e_max:.0f})"
    return BrandCheckFinding("palette", passed, score, detail, offenders, locked)


def _contrast_finding(brief, brand_kit) -> BrandCheckFinding:
    """Reuse the renderer's role resolver + the APCA legibility gate verbatim."""
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief
    from mediahub.quality.compliance import check_roles

    roles = resolved_role_vars_for_brief(brief, brand_kit)
    report = check_roles(roles)
    detail = report.explain()
    # Contrast is reported but not a *kit lock*: legibility is already enforced
    # deterministically at render time (the renderer's compliance gate refuses
    # an illegible role assignment), so it never gates approval here — only the
    # owner's chosen palette/fonts/logo locks do (locked=False).
    return BrandCheckFinding(
        "contrast", report.passes, report.score, detail, list(report.failures), locked=False
    )


def _font_finding(brief, kit) -> BrandCheckFinding:
    locked = kit.is_locked("fonts")
    want = (kit.font_pairing or "").strip()
    if not want:
        return BrandCheckFinding("fonts", True, 1.0, "kit pins no font pairing", locked=locked)
    have = (getattr(brief, "typography_pair", "") or "").strip()
    if not have or have == want:
        return BrandCheckFinding(
            "fonts", True, 1.0, f"font pairing matches kit ({want})", locked=locked
        )
    return BrandCheckFinding(
        "fonts",
        False,
        0.0,
        f"font pairing '{have}' does not match the kit's '{want}'",
        [have],
        locked,
    )


def _logo_finding(brief, kit, brand_kit, *, logo_dominant_hex: Optional[str]) -> BrandCheckFinding:
    """Does the brand mark read on this card's ground (bare or via the chip)?

    Informational, never a hard blocker: the renderer always produces a legible
    logo via the chip fallback, so this surfaces *cleanliness* (does it sit
    cleanly bare, or does it need a chip) rather than gating approval.
    """
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief
    from mediahub.theming.logo_chip import decide_logo_chip

    roles = resolved_role_vars_for_brief(brief, brand_kit)
    surface = roles.get("--mh-surface") or roles.get("--mh-primary")
    dominant = logo_dominant_hex or (kit.palette or {}).get("primary")
    if not (_is_hex(surface) and _is_hex(dominant)):
        return BrandCheckFinding("logo", True, 1.0, "no logo colour to check", locked=False)
    decision = decide_logo_chip(dominant, surface)
    # Both presentations are valid, on-brand ways to place the mark — the chip
    # is part of the brand system, not a defect — so both score 1.0; the detail
    # records which clear-space treatment the renderer will use.
    if decision.mode == "bare":
        detail = "logo reads cleanly bare on the card ground"
    else:
        detail = "logo placed on its brand chip for clear-space contrast"
    return BrandCheckFinding("logo", True, 1.0, detail, locked=False)


def check_brief(
    brief,
    kit,
    *,
    brand_kit=None,
    logo_dominant_hex: Optional[str] = None,
    palette_delta_e_max: float = PALETTE_DELTA_E_MAX,
) -> BrandCheckReport:
    """Deterministically score ``brief`` against ``kit``.

    ``brand_kit`` is the renderer-facing :class:`~mediahub.brand.kit.BrandKit`
    the card paints with (resolve it via
    :func:`mediahub.brand.kits.brand_kit_from_ref`); when ``None`` the brief's
    own palette is used. ``logo_dominant_hex`` lets a caller pass the pinned
    logo's vision-extracted dominant colour; otherwise the kit primary is used
    as a proxy.
    """
    cb = _coerce_brief(brief)
    if cb is None:
        return BrandCheckReport(kit_id=getattr(kit, "kit_id", ""))
    findings = [
        _palette_finding(cb, kit, delta_e_max=palette_delta_e_max),
        _contrast_finding(cb, brand_kit),
        _font_finding(cb, kit),
        _logo_finding(cb, kit, brand_kit, logo_dominant_hex=logo_dominant_hex),
    ]
    return BrandCheckReport(kit_id=getattr(kit, "kit_id", ""), findings=findings)


# --------------------------------------------------------------------------
# Brand Assist — optional AI advisory + auto-fix (honest-error)
# --------------------------------------------------------------------------


@dataclass
class AdvisoryResult:
    available: bool
    notes: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {"available": self.available, "notes": self.notes, "message": self.message}


_ADVISE_SYSTEM = (
    "You are MediaHub's Brand Assist. Given a deterministic brand-check report "
    "for a club graphic, write at most three short, concrete, plain-English "
    "notes a volunteer could act on to make the design more on-brand. Never "
    "invent brand rules; only address the failed checks in the report. Return "
    'JSON: {"notes": ["..."]}.'
)


def advise(report: BrandCheckReport, brief, kit, *, brand_kit=None) -> AdvisoryResult:
    """Optional AI notes layered on the deterministic report.

    Honest-errors (``available=False``) when no provider is configured — never
    a fabricated suggestion.
    """
    from mediahub.media_ai.llm import ClaudeUnavailableError, generate_json

    if report.passed:
        return AdvisoryResult(True, [], "Design is on-brand — no changes needed.")
    prompt = (
        "Brand-check report (deterministic):\n"
        + "\n".join(
            f"- {f.check}: {'PASS' if f.passed else 'FAIL'} — {f.detail}" for f in report.findings
        )
        + f"\n\nKit: {kit.name} (role={kit.role}). Suggest fixes for the FAILED checks only."
    )
    try:
        data = generate_json(prompt, system=_ADVISE_SYSTEM, max_tokens=400)
    except ClaudeUnavailableError as e:
        return AdvisoryResult(False, [], str(e))
    notes = [str(n).strip() for n in (data.get("notes") or []) if str(n).strip()][:3]
    return AdvisoryResult(True, notes, "")


@dataclass
class AutofixResult:
    available: bool
    changed: bool = False
    brief: object = None  # the new CreativeBrief (or the original if unchanged)
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "changed": self.changed,
            "applied": self.applied,
            "rejected": self.rejected,
            "message": self.message,
        }


_AUTOFIX_SYSTEM = (
    "You are MediaHub's Brand Assist auto-fix. Propose a minimal SpecPatch that "
    "brings the design back on-brand for the failed checks ONLY. You may only use "
    "these op kinds: set_colour_role (slot, role), set_archetype (archetype), "
    "set_accent_treatment (treatment), set_tone (tone). Prefer reassigning colour "
    "roles to the kit's own tokens over anything else. Do not change the wording. "
    'Return JSON: {"ops": [{"kind": "...", ...}]}.'
)


def autofix(brief, kit, *, brand_kit=None) -> AutofixResult:
    """Ask the model for a fix, then re-validate it through the P6.2 gate.

    The proposed patch is parsed and applied with the same ``parse_patch`` →
    ``apply_patch`` machinery the copilot uses, so a fix that would break
    legibility is rejected by the deterministic gate, not blindly painted.
    Honest-errors (``available=False``) when no provider is configured.
    """
    from mediahub.assistant.patch import apply_patch, parse_patch, _describe
    from mediahub.media_ai.llm import ClaudeUnavailableError, generate_json

    cb = _coerce_brief(brief)
    if cb is None:
        return AutofixResult(True, False, brief, message="no brief to fix")

    report = check_brief(cb, kit, brand_kit=brand_kit)
    if report.passed:
        return AutofixResult(True, False, cb, message="Design is already on-brand.")

    kit_roles = [s for s in (kit.palette or {}).keys()]
    prompt = (
        "Failed checks:\n"
        + "\n".join(f"- {f.check}: {f.detail}" for f in report.findings if not f.passed)
        + f"\n\nKit palette roles available: {', '.join(kit_roles) or '(none)'}."
        + "\nPropose the smallest patch that fixes them."
    )
    try:
        data = generate_json(prompt, system=_AUTOFIX_SYSTEM, max_tokens=500)
    except ClaudeUnavailableError as e:
        return AutofixResult(False, False, cb, message=str(e))

    patch = parse_patch(data)
    result = apply_patch(cb, patch, brand_kit=brand_kit)
    return AutofixResult(
        available=True,
        changed=result.changed,
        brief=result.brief,
        applied=[_describe(o) for o in result.applied],
        rejected=[f"{_describe(o)} ({why})" for o, why in result.rejected],
        message=result.summary(),
    )


__all__ = [
    "PALETTE_DELTA_E_MAX",
    "BrandCheckFinding",
    "BrandCheckReport",
    "check_brief",
    "AdvisoryResult",
    "advise",
    "AutofixResult",
    "autofix",
]
