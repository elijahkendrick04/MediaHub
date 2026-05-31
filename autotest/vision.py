"""Vision judge — testing what the rendered screen actually *looks* like.

The deterministic finder (``run.py``) answers "did it error?". The semantic
subagents (``semantic.py``) judge *meaning* from the DOM **text** + the content
pack. Neither of them can see a pixel — so a screen that returns HTTP 200 with
sane DOM text but renders **visually broken** sails straight through:

  * a club logo or athlete photo that 404'd and left a broken-image box
  * a caption overflowing / clipped out of its result card
  * an error banner or "something went wrong" toast painted over the page
  * an empty review screen with no cards to approve/export
  * illegible contrast (brand colours that vanish into the background)
  * layout collapse on the primary review surface

This judge closes that gap. It is the one idea worth taking from ByteDance's
UI-TARS-desktop — *let an AI see the rendered screen* — applied to QA, not
control. The VLM **looks and reports**; it never clicks, never drives the UI,
and never decides a swim time / PB / ranking (that stays in the deterministic
engine). See ``autotest/reports/council/ui-tars-desktop-*`` for the verdict that
chose this shape.

It runs on MediaHub's **existing** vision capability — ``media_ai.llm`` (Gemini
first, Anthropic failover) — so there is no GPU, no second runtime, and no new
dependency. With no provider key configured it skips cleanly (one info finding,
``is_bug=False``), exactly like the honest-error rule everywhere else in
MediaHub: a missing key is surfaced, never silently faked.

Findings carry a ``vision:<surface>`` category so a human can see they are AI
judgements about appearance, and they are routed through the same LLM-Council
adjudication the semantic findings already use.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from autotest.report import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclasses.dataclass
class Surface:
    name: str               # review | home — the screen being looked at
    artifact_key: str       # artifacts[...] holding the screenshot path
    persona: str            # the "eyes" — who is looking and how
    rubric: str             # what visual defects to look for


SURFACES = (
    Surface(
        name="review",
        artifact_key="review_screenshot",
        persona=("You are a meticulous visual-QA reviewer looking at a screenshot of the "
                 "REVIEW screen of a sports-content app, where a club volunteer approves "
                 "auto-generated result cards before posting."),
        rubric=("Report only VISUAL/RENDERING defects a human would see at a glance: a "
                "broken or missing image (logo / athlete photo showing a broken-image icon "
                "or blank box), text overflowing or clipped out of a card, overlapping "
                "elements, an on-screen error banner / 'something went wrong' message, an "
                "empty review screen with nothing to approve or export, illegible contrast "
                "(text the same colour as its background), or a collapsed/garbled layout. "
                "Do NOT judge whether captions, times, or PBs are factually correct — that "
                "is verified elsewhere. Do NOT flag a missing AI caption or a sparse page "
                "when no AI provider is configured; that is expected, not a visual bug."),
    ),
    Surface(
        name="home",
        artifact_key="home_screenshot",
        persona=("You are a first-time visitor looking at a screenshot of the HOME / landing "
                 "screen of a sports-content web app."),
        rubric=("Report only VISUAL/RENDERING defects: broken or missing images, an error "
                "banner painted over the page, text overflowing or unreadable, primary "
                "buttons that are invisible or clipped, or a collapsed layout. Do NOT "
                "critique copywriting, marketing, or feature choices — only things that look "
                "broken on screen."),
    ),
)

_VERDICT_CONTRACT = (
    'Return ONLY a JSON object, no prose:\n'
    '{"issues":[{"title":"...","severity":"low|medium|high",'
    '"confidence":"low|medium|high","expected":"...","actual":"...",'
    '"evidence":"the exact visual detail you saw"}]}\n'
    'If the screen looks fine, return {"issues":[]}. Only report concrete visual '
    'defects you can actually see — when unsure, omit it.'
)


def _parse_verdict(text: str) -> list[dict]:
    if not text:
        return []
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return []
    issues = obj.get("issues") if isinstance(obj, dict) else None
    return issues if isinstance(issues, list) else []


def _abs_screenshot(rel_or_abs: str) -> str | None:
    """Screenshots are stored relative to the repo root in artifacts; resolve to
    an absolute path the vision API can open. Returns None if the file is gone."""
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs) if os.path.isabs(rel_or_abs) else (REPO_ROOT / rel_or_abs)
    return str(p) if p.exists() else None


def _judge_surface(surface: Surface, image_path: str, flow_result: str) -> list[Finding]:
    from mediahub.media_ai import llm

    system = f"{surface.persona}\n\n{surface.rubric}\n\n{_VERDICT_CONTRACT}"
    prompt = (f"Look at this screenshot of the {surface.name} screen and report any "
              f"visual defects per your instructions. Flow result for context: {flow_result}.")
    try:
        answer = llm.generate_vision([image_path], prompt, system=system, max_tokens=900)
    except llm.ClaudeUnavailableError:
        # No provider key — handled by the caller's availability gate, but stay safe.
        return []
    except Exception as exc:
        return [Finding(category=f"vision:{surface.name}", severity="info",
                        title=f"Vision judge '{surface.name}' could not run",
                        route=f"(vision:{surface.name})",
                        expected="vision judge returns a verdict",
                        actual=str(exc)[:200], evidence=str(exc)[:500], is_bug=False)]

    findings: list[Finding] = []
    for issue in _parse_verdict(answer):
        if not isinstance(issue, dict):
            continue
        if str(issue.get("confidence", "")).lower() == "low":
            continue  # conservative: drop speculation, keep the ledger clean
        sev = str(issue.get("severity", "medium")).lower()
        sev = sev if sev in ("low", "medium", "high") else "medium"
        findings.append(Finding(
            category=f"vision:{surface.name}", severity=sev,
            title=str(issue.get("title", "Visual defect"))[:140],
            route=f"({surface.name} screen)",
            expected=str(issue.get("expected", ""))[:600],
            actual=str(issue.get("actual", ""))[:600],
            evidence=("AI vision judge (" + surface.name + ", confidence "
                      + str(issue.get("confidence", "?")) + "):\n"
                      + str(issue.get("evidence", ""))[:1500]),
            screenshot=_rel_screenshot(image_path),
            repro=[f"Reproduce the flow (result: {flow_result}), open the {surface.name} "
                   f"screen, and look at the rendered page"]))
    return findings


def _rel_screenshot(path: str) -> str:
    """Path relative to the repo root for the ledger/report (consistent with the
    deterministic finder's screenshots), or '' if it sits outside the repo."""
    try:
        return os.path.relpath(path, REPO_ROOT)
    except ValueError:
        return ""


def evaluate(raw_artifacts: dict[str, Any]) -> list[Finding]:
    """Look at the captured surface screenshots and report visual defects.

    Never raises. Skips cleanly (one info finding) when no vision-capable
    provider is configured — the honest-error rule, not a silent fake.
    """
    try:
        from mediahub.media_ai import llm
    except Exception:
        return []

    if not llm.is_available():
        return [Finding(
            category="vision_skipped", severity="info",
            title="Vision judge skipped — no AI provider configured",
            route="(vision)",
            expected="The vision judge runs on media_ai.llm (Gemini/Anthropic)",
            actual="No GEMINI_API_KEY / ANTHROPIC_API_KEY in the environment",
            evidence="Set a Gemini or Anthropic key in .env so the vision judge can "
                     "look at the rendered review/home screens for visual defects.",
            is_bug=False)]

    flow_result = str(raw_artifacts.get("flow_result", "?"))
    jobs: list[tuple[Surface, str]] = []
    for surface in SURFACES:
        img = _abs_screenshot(str(raw_artifacts.get(surface.artifact_key, "")))
        if img:
            jobs.append((surface, img))

    if not jobs:
        return [Finding(
            category="vision_skipped", severity="info",
            title="Vision judge had no screenshots to inspect",
            route="(vision)",
            expected="The primary flow captures review/home screenshots",
            actual="No surface screenshots were present in this run's artifacts",
            evidence="Expected artifacts['review_screenshot'] / ['home_screenshot'].",
            is_bug=False)]

    findings: list[Finding] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(_judge_surface, s, img, flow_result): s for s, img in jobs}
        for fut in as_completed(futures):
            try:
                findings.extend(fut.result())
            except Exception:
                pass
    return findings
