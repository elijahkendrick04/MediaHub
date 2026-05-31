"""Semantic subagents — testing *meaning*, not just crashes.

The deterministic finder (run.py) answers "did it error?". These AI judges
answer the questions a human tester would:

  * functional   — "is this doing what it's meant to be doing?"
  * output       — "is the output correct?" (captions grounded, confidence
                    sane, ranking sensible — no fabricated swimmers/times)
  * user_brain   — "I have the brain of the user — does this work in all the
                    ways I'd want it to?" (a club social-media volunteer's POV)

Each charter is dispatched as its own subagent (parallel threads) through the
Claude CLI on a flat subscription token (autotest.cli_llm) — NO API key. With
the CLI unavailable this skips cleanly — it never crashes the loop and never
invents findings.

Judges are told to be conservative and cite evidence; low-confidence verdicts
are dropped, so the bug ledger isn't polluted by speculation. Findings carry a
``semantic:<charter>`` category so a human can see they are AI judgements (which
can be subjective) rather than hard crashes.
"""
from __future__ import annotations

import dataclasses
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from autotest.report import Finding

_MAX_TEXT = 4500
_MAX_CARDS = 12

# --- artifact provenance (the single source of truth) ------------------------
# Every artifact a judge can see is one of three KINDS. This is the one mechanism
# the de-contamination depends on (council mandate): a control variable the TESTER
# assembles (e.g. flow_result = "live:judged-6-runs") must never reach a judge that
# is told "you ARE the user", or the judge flags the tester's own internal token as
# if it were on-screen product text — which is exactly how the false bug
# b07572c63c13 was fabricated. Enforce on the KIND, not the key name, so a control
# token leaking into a different bag (or a key being renamed) is still dropped.
RENDERED_PAGE = "rendered_page"      # page.inner_text(body) — genuinely user-visible
TESTER_CONTROL = "tester_control"    # a tester control/flow token — NEVER user-visible
TESTER_SUMMARY = "tester_summary"    # derived from internal state / the export JSON

# The complete set — a charter that may see EVERYTHING declares this explicitly,
# so "fully permissive" is a deliberate choice in the source, not an accident a
# future charter author falls into by listing all three kinds by hand.
ALL_PROVENANCE = frozenset({RENDERED_PAGE, TESTER_CONTROL, TESTER_SUMMARY})

PROVENANCE: dict[str, str] = {
    "home_text": RENDERED_PAGE,
    "signup_text": RENDERED_PAGE,
    "review_text": RENDERED_PAGE,
    "flow_result": TESTER_CONTROL,
    "pages": TESTER_SUMMARY,
    "content_summary": TESTER_SUMMARY,
    "content_pack": TESTER_SUMMARY,
    "meet_summary": TESTER_SUMMARY,
    # The raw export the content_summary/content_pack/meet_summary are derived from;
    # tester-side data (the product's export JSON as the tester captured it), so it
    # is adjudication context, never user-visible page text.
    "export_json": TESTER_SUMMARY,
}


def filter_artifacts(artifacts: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    """Return only the artifacts whose provenance KIND is in ``allowed``.

    The single guard called by BOTH the judge (``_run_charter``) and the council
    framing (``adjudicate``), so there is one implementation, not several that drift.

    An artifact with no known provenance is treated as TESTER_CONTROL. Note the
    asymmetry this creates, by design: for a caller whose ``allowed`` excludes
    TESTER_CONTROL (e.g. the user_brain judge, allowed={RENDERED_PAGE}) an unknown
    key is FAIL-CLOSED (dropped — never shown to a user-perspective judge). For a
    caller whose ``allowed`` includes TESTER_CONTROL (e.g. the council, which is
    meant to see tester context) an unknown key is FAIL-OPEN (passed through as
    internal context). That is correct: a stray unknown value must never reach the
    "you ARE the user" judge, but it is harmless as tester-side adjudication context."""
    return {k: v for k, v in artifacts.items()
            if PROVENANCE.get(k, TESTER_CONTROL) in allowed}


def scrub_control_tokens(text: str, artifacts: dict[str, Any]) -> str:
    """Redact the literal VALUES of tester_control artifacts from ``text``.

    The council's ``issues_txt`` is the legitimate evidence channel — it must keep
    every real page quote a judge cites. But a judge that legitimately SEES a
    control token (e.g. the QA charter sees flow_result) can author a finding whose
    text contains the token's value, which then reaches the council framing as if it
    were product evidence (the b07572c63c13 class, via a different judge). This scrubs
    only the exact control-token VALUES — keyed on the PROVENANCE map, so it covers
    every tester_control artifact PRESENT IN THIS RUN's ``artifacts`` dict (not a
    hardcoded list, and not limited to the current judge roster) — while leaving all
    genuine page quotes intact.

    Boundary conditions (declared, not silently assumed):
      * Value gate, NOT existence gate: the literal value is replaced with
        ``<redacted KEY>``; the council still learns a control artifact was present.
      * It redacts the literal STRING only — a judge that PARAPHRASES a control
        signal's meaning ("confirmed a live run with 6 judged sources") is NOT
        caught. Judges are trusted not to summarise control semantics as product
        evidence; if that holds, the gate is sufficient; if violated, it fails open.
      * Short/common values are skipped (``len >= 4`` after strip) to avoid redacting
        substrings of genuine page quotes — a deliberate false-positive guard."""
    if not text:
        return text
    for key, kind in PROVENANCE.items():
        if kind != TESTER_CONTROL:
            continue
        val = artifacts.get(key)
        if isinstance(val, str) and len(val.strip()) >= 4:   # >=4: don't redact trivial tokens
            text = text.replace(val, f"<redacted {key}>")
    return text


@dataclasses.dataclass
class Charter:
    name: str
    persona: str          # the "brain" — who is judging and how
    rubric: str           # what to check
    allowed_provenance: frozenset[str]   # which artifact KINDS this charter may see
    artifact_keys: tuple[str, ...]


CHARTERS = (
    Charter(
        name="functional",
        persona=("You are a meticulous QA engineer verifying that a sports-content "
                 "web app does what its UI promises at each step."),
        rubric=("Given the flow result, the routes visited (with HTTP status), and a "
                "summary of the produced content pack, decide whether each step did "
                "what it claims. Flag silent functional failures: e.g. a real meet "
                "file that yielded ZERO cards, a 'done' run with no content, export "
                "that returns nothing, a step that 'succeeds' but produces empty/"
                "placeholder output. Do NOT flag missing AI captions when no AI key "
                "is configured — that is expected."),
        artifact_keys=("flow_result", "pages", "content_summary"),
        # A QA persona checking flow STATUS is *meant* to inspect internal state.
        allowed_provenance=ALL_PROVENANCE,
    ),
    Charter(
        name="output",
        persona=("You are a swimming results editor checking that auto-generated "
                 "social content is factually grounded in the meet data."),
        rubric=("Inspect the generated cards (captions, achievement type, confidence). "
                "Flag: captions that name swimmers/events/times NOT present in the data "
                "(fabrication), captions that are broken/templated/empty, confidence "
                "scores that contradict the achievement (e.g. 0.95 on a trivial result, "
                "or a clear PB scored near 0), and ranking that puts minor results above "
                "major ones. Quote the exact card text you object to as evidence. If a "
                "field is just absent because AI is unconfigured, that is NOT a bug."),
        artifact_keys=("content_pack", "meet_summary"),
        # An editor fact-checking cards is meant to see the produced content/export.
        allowed_provenance=ALL_PROVENANCE,
    ),
    Charter(
        name="user_brain",
        persona=("You ARE the user: a busy swimming-club social-media volunteer who "
                 "uploaded a meet results file to get post-ready content fast. You are "
                 "not technical and you have low patience for confusion."),
        rubric=("From the home page, the SIGN-UP/onboarding text, and the review page text "
                "plus the flow outcome, ask: could I actually accomplish what I came to do — "
                "from first-time sign-up through to getting content? Flag anything confusing, "
                "broken, mislabeled, dead-ending, or missing that would stop a real volunteer "
                "— a sign-up/onboarding step that's unclear or fails, empty states with no "
                "next step, primary actions that don't obviously work, jargon, or a review "
                "screen with nothing to approve/export. Be concrete about what blocked you."),
        artifact_keys=("home_text", "signup_text", "review_text", "flow_result"),
        # "You ARE the user" => may see ONLY genuinely-rendered page text. The
        # provenance guard drops flow_result (a tester control token) here, which
        # is what fabricated b07572c63c13. flow_result stays declared in
        # artifact_keys for documentation but is filtered out before the prompt.
        allowed_provenance=frozenset({RENDERED_PAGE}),
    ),
)

_VERDICT_CONTRACT = (
    'Return ONLY a JSON object, no prose:\n'
    '{"issues":[{"title":"...","severity":"low|medium|high",'
    '"confidence":"low|medium|high","area":"route or feature",'
    '"expected":"...","actual":"...","evidence":"quote/specifics"}]}\n'
    'If everything is correct, return {"issues":[]}. Only report concrete, '
    'evidence-backed problems — when unsure, omit it.'
)


def _trim(text: str, n: int = _MAX_TEXT) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + "\n…(truncated)"


def _content_summary(export: dict[str, Any]) -> str:
    cards = export.get("cards") or []
    meet = export.get("meet") or {}
    have_caps = sum(1 for c in cards if (c.get("caption") or "").strip())
    return (f"meet={meet.get('name') or meet.get('meet_name') or '?'}; "
            f"cards={len(cards)}; cards_with_caption={have_caps}; "
            f"trust={json.dumps(export.get('trust') or {})[:300]}")


def _content_pack(export: dict[str, Any]) -> str:
    cards = (export.get("cards") or [])[:_MAX_CARDS]
    slim = []
    for c in cards:
        slim.append({
            "caption": (c.get("caption") or "")[:400],
            "achievement": c.get("achievement") or c.get("type") or c.get("headline"),
            "confidence": c.get("confidence") or c.get("score"),
            "swimmer": c.get("swimmer") or c.get("athlete"),
        })
    return _trim(json.dumps(slim, indent=2), 6000)


def _meet_summary(export: dict[str, Any]) -> str:
    meet = export.get("meet") or {}
    return _trim(json.dumps(meet, indent=2), 2500)


def _build_artifacts(raw: dict[str, Any]) -> dict[str, str]:
    export = raw.get("export_json") or {}
    pages = raw.get("pages") or []
    return {
        "flow_result": str(raw.get("flow_result", "?")),
        "pages": _trim("\n".join(f"{p.get('status')} {p.get('route')}" for p in pages), 2500),
        "content_summary": _content_summary(export),
        "content_pack": _content_pack(export),
        "meet_summary": _meet_summary(export),
        "home_text": _trim(raw.get("home_text", "")),
        "signup_text": _trim(raw.get("signup_text", "")),
        "review_text": _trim(raw.get("review_text", "")),
    }


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


def _run_charter(charter: Charter, arts: dict[str, str]) -> list[Finding]:
    from autotest import cli_llm  # judges run on the Claude CLI (subscription, no API key)

    # Provenance guard: drop any artifact whose KIND this charter may not see, so a
    # tester-internal control token never reaches a user-perspective judge.
    safe = filter_artifacts(arts, charter.allowed_provenance)
    body = "\n\n".join(f"## {k}\n{safe.get(k, '(none)')}"
                       for k in charter.artifact_keys if k in safe)
    system = f"{charter.persona}\n\n{charter.rubric}\n\n{_VERDICT_CONTRACT}"
    try:
        answer = cli_llm.ask(system=system, user=body, max_tokens=1100)
    except Exception as exc:
        return [Finding(category=f"semantic:{charter.name}", severity="info",
                        title=f"Semantic charter '{charter.name}' could not run",
                        route="(semantic)", expected="charter returns a verdict",
                        actual=str(exc)[:200], evidence=str(exc), is_bug=False)]

    findings: list[Finding] = []
    for issue in _parse_verdict(answer):
        if not isinstance(issue, dict):
            continue
        if str(issue.get("confidence", "")).lower() == "low":
            continue  # conservative: drop speculation
        sev = str(issue.get("severity", "medium")).lower()
        sev = sev if sev in ("low", "medium", "high") else "medium"
        findings.append(Finding(
            category=f"semantic:{charter.name}", severity=sev,
            title=str(issue.get("title", "Semantic issue"))[:140],
            route=str(issue.get("area", "(semantic)"))[:120],
            expected=str(issue.get("expected", ""))[:600],
            actual=str(issue.get("actual", ""))[:600],
            evidence=("AI judge (" + charter.name + ", confidence "
                      + str(issue.get("confidence", "?")) + "):\n"
                      + str(issue.get("evidence", ""))[:1500]),
            repro=[f"Reproduce the flow (result: {arts.get('flow_result')}) and inspect "
                   f"the {charter.name} aspect described above"]))
    return findings


def evaluate(raw_artifacts: dict[str, Any]) -> list[Finding]:
    """Dispatch all charters in parallel; return their findings. Never raises."""
    try:
        from autotest import cli_llm
        if not cli_llm.available():
            return [Finding(
                category="semantic_skipped", severity="info",
                title="Semantic subagents skipped — Claude CLI not available",
                route="(semantic)",
                expected="The judges run on the Claude CLI (subscription token)",
                actual="claude CLI not installed / no CLAUDE_CODE_OAUTH_TOKEN",
                evidence="Install @anthropic-ai/claude-code and set CLAUDE_CODE_OAUTH_TOKEN "
                         "(from `claude setup-token`) so the judges can evaluate output + UX.",
                is_bug=False)]
    except Exception:
        return []

    arts = _build_artifacts(raw_artifacts)
    findings: list[Finding] = []
    with ThreadPoolExecutor(max_workers=len(CHARTERS)) as pool:
        futures = {pool.submit(_run_charter, c, arts): c for c in CHARTERS}
        for fut in as_completed(futures):
            try:
                findings.extend(fut.result())
            except Exception:
                pass
    return findings
