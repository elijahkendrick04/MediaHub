"""LLM Council — embedded into the autonomous tester.

This is the Karpathy "LLM Council" methodology (vendored as a Claude Code skill
in autotest/skills/llm-council/) implemented in-process so it runs as part of
every test sweep instead of needing an interactive `claude` session:

  5 advisors (Contrarian, First-Principles, Expansionist, Outsider, Executor)
  answer in parallel → responses are anonymised → 5 peer reviewers critique →
  a Chairman synthesises a verdict → an HTML report + markdown transcript.

In the tester it plays one job: **adjudicate the semantic subagents' findings.**
Single LLM judges are sycophantic and over-flag; the council's adversarial
peer-review is the antidote — it confirms the real bugs, demotes the noise, and
surfaces blind spots the judges missed. It runs on the Claude CLI via a flat
subscription token (autotest.cli_llm) — NO API key — and self-skips cleanly when
the CLI is unavailable. Uses a reduced advisor set by default to respect
subscription rate limits (AUTOTEST_COUNCIL_ADVISORS).
"""
from __future__ import annotations

import html
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from autotest.report import Finding

COUNCIL_DIR = Path(__file__).resolve().parent / "reports" / "council"

ADVISORS: tuple[tuple[str, str], ...] = (
    ("The Contrarian",
     "You actively look for what's wrong, missing, or will fail. Assume the thing "
     "has a fatal flaw and find it. If it looks solid, dig deeper. You are the "
     "friend who saves someone from a bad call by asking the question they avoid."),
    ("The First Principles Thinker",
     "Ignore the surface question and ask what we're actually trying to solve. "
     "Strip assumptions, rebuild from the ground up. You may conclude the wrong "
     "question is being asked entirely."),
    ("The Expansionist",
     "Look for upside everyone else misses. What could be bigger or is being "
     "undervalued? You don't care about risk (that's the Contrarian's job) — you "
     "care what happens if this works better than expected."),
    ("The Outsider",
     "You have ZERO context about this product or field. React purely to what's in "
     "front of you. You catch the curse of knowledge — things obvious to insiders "
     "but confusing to everyone else."),
    ("The Executor",
     "You only care: can this be done, and what's the fastest path? Ignore theory "
     "and strategy. Every idea gets 'OK but what do you do Monday morning?' If "
     "there's no clear first step, say so."),
)


# Most bug-triage-relevant advisors first (flaws, fresh-eyes UX, actionability),
# so a reduced council still covers the key angles. Default 3 to respect Claude
# subscription rate limits; raise AUTOTEST_COUNCIL_ADVISORS for more depth.
_ADVISOR_ORDER = ("The Contrarian", "The Outsider", "The Executor",
                  "The First Principles Thinker", "The Expansionist")


def _advisors() -> list[tuple[str, str]]:
    n = max(2, min(len(ADVISORS), int(os.environ.get("AUTOTEST_COUNCIL_ADVISORS", "3"))))
    by_name = dict(ADVISORS)
    return [(nm, by_name[nm]) for nm in _ADVISOR_ORDER if nm in by_name][:n]


def available() -> bool:
    from autotest import cli_llm
    return cli_llm.available()


def _ask(system: str, user: str, max_tokens: int) -> str:
    # Council runs on the Claude CLI (subscription token), not an API key.
    from autotest import cli_llm
    return cli_llm.ask(system=system, user=user, max_tokens=max_tokens)


def _safe_ask(system: str, user: str, max_tokens: int, retries: int = 1) -> str:
    """A council member that never takes down the whole session: on error
    (e.g. a rate limit) it backs off and retries, then returns '' so the rest
    of the council can still deliberate with whoever answered."""
    for attempt in range(retries + 1):
        try:
            out = _ask(system, user, max_tokens)
            if out and out.strip():
                return out
        except Exception:
            pass
        if attempt < retries:
            time.sleep(2.5 * (attempt + 1))
    return ""


# --- the methodology ---------------------------------------------------------
def deliberate(framed_question: str) -> dict[str, Any] | None:
    """Run a full council session on a framed question. Returns the session dict
    (advisors, reviews, verdict, report paths) or None if no provider / failure."""
    if not available():
        return None
    # Gentle concurrency: parallel bursts trip free-tier rate limits, and one
    # failed call must not abandon the whole council. Default 2 in flight.
    workers = max(1, int(os.environ.get("AUTOTEST_COUNCIL_CONCURRENCY", "2")))
    try:
        # step 2: advisors (tolerate partial failures — keep whoever answered)
        def run_advisor(item: tuple[str, str]) -> tuple[str, str]:
            name, style = item
            system = (f"You are {name} on an LLM Council.\n\nYour thinking style: {style}\n\n"
                      "Respond independently. Do not hedge or try to be balanced. Lean fully "
                      "into your assigned angle. 150-300 words, no preamble.")
            return name, _safe_ask(system, framed_question, 700)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            advisor_results = {n: r for n, r in pool.map(run_advisor, _advisors()) if r.strip()}
        if len(advisor_results) < 2:
            return None  # too few advisors answered to be a real council

        # step 3: anonymise (randomised) and peer-review whoever we have
        names = list(advisor_results)
        random.shuffle(names)
        letters = [chr(65 + i) for i in range(len(names))]
        mapping = dict(zip(letters, names))   # letter -> advisor name
        anon_block = "\n\n".join(
            f"**Response {ltr}:**\n{advisor_results[mapping[ltr]]}" for ltr in letters)

        def run_review(_: int) -> str:
            system = "You are reviewing the outputs of an LLM Council. Be specific, reference responses by letter, under 200 words."
            user = (f"The question:\n---\n{framed_question}\n---\n\nAnonymised responses:\n\n"
                    f"{anon_block}\n\n1. Which response is strongest? Why?\n"
                    "2. Which has the biggest blind spot? What is it missing?\n"
                    "3. What did ALL responses miss that the council should consider?")
            return _safe_ask(system, user, 500)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            reviews = [r for r in pool.map(run_review, range(len(letters))) if r.strip()]

        # step 4: chairman synthesis (de-anonymised; retries — this one matters)
        advisor_block = "\n\n".join(f"**{n}:**\n{advisor_results[n]}" for n in advisor_results)
        review_block = "\n\n".join(f"Review {i+1}:\n{r}" for i, r in enumerate(reviews)) or "(none)"
        chair_system = ("You are the Chairman of an LLM Council. Synthesise the advisors and "
                        "peer reviews into a final verdict. Be direct, don't hedge.")
        chair_user = (
            f"The question:\n---\n{framed_question}\n---\n\nADVISOR RESPONSES:\n\n{advisor_block}\n\n"
            f"PEER REVIEWS:\n{review_block}\n\nProduce the verdict with these exact sections:\n"
            "## Where the Council Agrees\n## Where the Council Clashes\n"
            "## Blind Spots the Council Caught\n## The Recommendation\n## The One Thing to Do First")
        verdict = _safe_ask(chair_system, chair_user, 1100, retries=2)
        if not verdict.strip():
            return None

        session = {
            "framed_question": framed_question,
            "advisors": advisor_results,
            "anon_mapping": mapping,
            "reviews": reviews,
            "verdict": verdict,
        }
        _write_artifacts(session)
        return session
    except Exception:
        return None


# --- tester integration: adjudicate the subagents' findings ------------------
def adjudicate(candidates: list[Finding], artifacts: dict[str, Any],
               artifact_meta: dict[str, Any] | None = None) -> tuple[list[Finding], str]:
    """Pressure-test the semantic subagents' candidate findings. Returns
    (adjusted_findings, verdict_summary). Findings the council judges to be
    noise are demoted to non-bugs (kept in the report, out of the open list);
    blind spots the council surfaces are added as new findings.

    ``artifact_meta`` (A4) is the tester's exercised-ness map; an artifact from a
    flow not exercised this sweep is structurally excluded from the framing too."""
    if not candidates or not available():
        return candidates, ""

    from autotest.semantic import (TESTER_CONTROL, TESTER_SUMMARY,
                                   filter_artifacts, scrub_control_tokens)

    _COUNCIL_ALLOWED = frozenset({TESTER_CONTROL, TESTER_SUMMARY})
    listed = candidates[:10]
    issues_txt = "\n".join(
        f"[{i}] ({c.category}/{c.severity}) {c.title} — expected: {c.expected[:160]} | "
        f"actual: {c.actual[:160]} | evidence: {c.evidence[:300]}"
        for i, c in enumerate(listed))
    # issues_txt is the legitimate evidence channel (real page quotes MUST survive),
    # but a judge that legitimately sees a control token (e.g. the QA charter sees
    # flow_result) can author a finding whose text contains the token's VALUE — which
    # would then reach the council as if it were product evidence. Scrub only the exact
    # control-token values (provenance-keyed, covers any judge incl. future ones); all
    # genuine page quotes are untouched. This is the code gate the council required in
    # place of the functional/QA "honor system".
    issues_txt = scrub_control_tokens(issues_txt, artifacts)
    live = (str(artifacts.get("flow_result", "")).startswith("live")
            or bool(artifacts.get("live_run_id")))
    if live:
        context = (
            "IMPORTANT CONTEXT (judge against this): this swept the LIVE production "
            "deployment with the operator's REAL organisations, meets and data. So "
            "outcomes like 'zero content cards for a real meet', 'a run whose export "
            "404s', or 'no review/approve/export path' are GENUINE product bugs that "
            "affect real users — NOT expected artifacts. Be skeptical only of "
            "subjective nitpicks; treat missing/empty/broken REAL output as a real defect.")
    else:
        context = (
            "IMPORTANT TEST CONTEXT (judge fairly against this): this is an automated "
            "COLD run — a freshly-seeded test organisation that is not a real club in "
            "the meet, a single uploaded file, and NO historical personal-best data. So "
            "outcomes like 'zero/few content cards', 'no PB achievements detected', or "
            "'captions absent when no AI key' can be EXPECTED artifacts of this setup, "
            "not product bugs. Distinguish genuine defects (crashes, broken UX, "
            "fabricated/incorrect output) from test-setup artifacts.")
    # De-contaminate the adjudication MECHANICALLY (one filter_artifacts, both
    # callers — the judge and the council). The council adjudicates findings and
    # legitimately needs TESTER context, but must NEVER be handed a rendered page
    # as raw text it could mistake for product UI; and a control token like
    # flow_result must be labelled as internal, not presented as product evidence.
    # Passing allowed={TESTER_CONTROL, TESTER_SUMMARY} structurally excludes
    # rendered_page artifacts and makes the token's provenance explicit in code —
    # not via a hand-written label the model could override (the b07572c63c13 class).
    safe = filter_artifacts(artifacts, _COUNCIL_ALLOWED, artifact_meta)
    flow_token = safe.get("flow_result", "(none)")
    framed = (
        "An automated tester swept MediaHub — a tool that turns swimming-meet result "
        "files into post-ready social content (cards, captions, confidence scores). "
        "AI judges flagged the candidate issues below this sweep. From the REAL user's "
        "perspective (a busy club social-media volunteer), decide which are genuine "
        "problems worth fixing versus over-flagged noise, and what single fix matters "
        "most. Be skeptical of over-flagging — a false bug wastes the team's time.\n\n"
        f"{context}\n\n"
        # The fields below are TESTER-INTERNAL (filtered to tester provenance), never
        # product UI. A 'user sees X' finding is only sound if X was quoted from a
        # rendered page by the judge — never from this control token.
        f"Tester-internal flow token (NOT shown to any user): {flow_token}\n"
        f"Content summary (tester-derived, not product UI): {_content_summary(safe)}\n\n"
        f"Candidate issues:\n{issues_txt}")

    session = deliberate(framed)
    if session is None:
        return candidates, ""
    verdict = session["verdict"]

    # step: machine-readable triage derived from the verdict
    try:
        clerk_system = ("You are the council clerk. Convert the Chairman's verdict into strict "
                        "JSON only, no prose.")
        clerk_user = (
            f"Candidate issues (by id):\n{issues_txt}\n\nChairman verdict:\n{verdict}\n\n"
            'Output: {"decisions":[{"id":<int>,"keep":true|false,"severity":"low|medium|high",'
            '"reason":"short"}],"new_issues":[{"title":"...","severity":"...","area":"...",'
            '"expected":"...","actual":"...","evidence":"..."}]}')
        raw = _ask(clerk_system, clerk_user, 900)
        triage = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        return candidates, _verdict_summary(verdict)

    decisions = {int(d["id"]): d for d in triage.get("decisions", []) if "id" in d}
    # A5: the council panel that deliberated (which advisors + the chairman). Recorded
    # on each kept finding so a human auditor sees the verdict was an N-advisor +
    # chairman consensus after anonymised peer review — not a single sycophantic judge.
    # The full per-advisor text is in the transcript under autotest/reports/council/.
    panel = sorted(session.get("advisors", {}).keys())
    panel_note = f"[{len(panel)}-advisor council ({', '.join(panel)}) + chairman] " if panel else ""
    out: list[Finding] = []
    for i, c in enumerate(listed):
        d = decisions.get(i)
        if d and d.get("keep") is False:
            # council triaged as noise — keep for transparency, but not a bug
            c.is_bug = False
            c.category = f"{c.category} (council:noise)"
            c.evidence += f"\n\n[council triage] demoted — {d.get('reason', 'judged not a real problem')}"
        elif d:
            if d.get("severity") in ("low", "medium", "high"):
                c.severity = d["severity"]
            if d.get("reason"):
                # OPEN-PR: persist the WHY (+ the panel that confirmed it) for the PR body.
                c.rationale = (panel_note + str(d["reason"]))[:2000]
        out.append(c)
    out += candidates[10:]

    for ni in triage.get("new_issues", [])[:5]:
        if not isinstance(ni, dict):
            continue
        sev = str(ni.get("severity", "medium")).lower()
        out.append(Finding(
            category="council:blind_spot",
            severity=sev if sev in ("low", "medium", "high") else "medium",
            title=str(ni.get("title", "Council-surfaced issue"))[:140],
            route=str(ni.get("area", "(council)"))[:120],
            expected=str(ni.get("expected", ""))[:600],
            actual=str(ni.get("actual", ""))[:600],
            evidence="Surfaced by the LLM Council peer-review (a blind spot the single "
                     "judges missed):\n" + str(ni.get("evidence", ""))[:1200]))
    return out, _verdict_summary(verdict)


def _content_summary(artifacts: dict[str, Any]) -> str:
    export = artifacts.get("export_json") or {}
    cards = export.get("cards") or []
    # Do NOT append flow_result here — it is a tester-internal control token and is
    # already shown once, explicitly labelled, in the framing. Repeating it as a bare
    # "flow=..." re-leaks it as if it were product evidence (the b07572c63c13 class).
    return f"{len(cards)} cards produced"


def _verdict_summary(verdict: str) -> str:
    """Pull the recommendation + first-step lines for the report header."""
    rec, first = "", ""
    m = re.search(r"##\s*The Recommendation\s*(.+?)(?:##|$)", verdict, re.S | re.I)
    if m:
        rec = " ".join(m.group(1).split())[:300]
    m = re.search(r"##\s*The One Thing to Do First\s*(.+?)(?:##|$)", verdict, re.S | re.I)
    if m:
        first = " ".join(m.group(1).split())[:300]
    return (f"Council recommendation: {rec}  ·  Do first: {first}").strip()


# --- artifacts (skill steps 5 + 6) -------------------------------------------
def _write_artifacts(session: dict[str, Any]) -> None:
    COUNCIL_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (COUNCIL_DIR / f"council-transcript-{ts}.md").write_text(_transcript_md(session), encoding="utf-8")
    (COUNCIL_DIR / f"council-report-{ts}.html").write_text(_report_html(session), encoding="utf-8")


def _transcript_md(s: dict[str, Any]) -> str:
    parts = ["# Council transcript", "", "## Framed question", s["framed_question"], "",
             "## Advisor responses"]
    for name, resp in s["advisors"].items():
        parts += [f"### {name}", resp, ""]
    parts += ["## Peer reviews (anonymisation: "
              + ", ".join(f"{l}={n}" for l, n in s["anon_mapping"].items()) + ")"]
    for i, r in enumerate(s["reviews"], 1):
        parts += [f"### Review {i}", r, ""]
    parts += ["## Chairman verdict", s["verdict"]]
    return "\n".join(parts)


def _report_html(s: dict[str, Any]) -> str:
    def esc(t: str) -> str:
        return html.escape(t).replace("\n", "<br>")
    advisors_html = "".join(
        f"<details><summary>{esc(n)}</summary><p>{esc(r)}</p></details>"
        for n, r in s["advisors"].items())
    reviews_html = "".join(
        f"<details><summary>Peer review {i}</summary><p>{esc(r)}</p></details>"
        for i, r in enumerate(s["reviews"], 1))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Council verdict</title><style>"
        "body{font:16px/1.6 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;"
        "background:#0f1115;color:#e8eaf0}h1{font-size:1.3rem}.q{background:#1a1d25;padding:1rem;"
        "border-radius:8px;border:1px solid #2a2f3a}.verdict{background:#161922;padding:1rem 1.25rem;"
        "border-radius:8px;border:1px solid #2a2f3a}details{margin:.4rem 0;background:#14171f;"
        "padding:.5rem .75rem;border-radius:6px;border:1px solid #232833}summary{cursor:pointer;"
        "font-weight:600}h2{font-size:1.05rem;color:#9fb0ff;margin-top:1.5rem}</style></head><body>"
        "<h1>LLM Council — verdict</h1>"
        f"<div class='q'><strong>Question</strong><br>{esc(s['framed_question'])}</div>"
        f"<h2>Chairman verdict</h2><div class='verdict'>{esc(s['verdict'])}</div>"
        f"<h2>Advisors</h2>{advisors_html}"
        f"<h2>Peer review</h2>{reviews_html}"
        f"<footer><p style='color:#6b7280;margin-top:2rem'>Generated by autotest/council.py "
        f"(LLM Council methodology) · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}</p></footer>"
        "</body></html>")
