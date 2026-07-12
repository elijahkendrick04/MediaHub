"""mediahub/log_sentinel/detectors.py — deterministic log-pattern detectors.

Each detector is a compiled regex + a threshold over one polled batch of log
lines, producing a :class:`Finding` with the evidence attached. Deliberately
NOT an LLM: "did the log say WORKER TIMEOUT?" is a fact, and facts are matched
mechanically (same philosophy as the deterministic recognition engine). The
optional AI layer only ever *summarises* a traceback cluster for the operator
notification — it never decides whether something fired.

Detector knowledge comes from MediaHub's own production history (gunicorn flag
comments in ``scripts/docker-entrypoint.sh``, the June 2026 SearXNG incident,
``docs/SEARXNG.md``), so each finding carries a suggestion in plain operator
language, not a generic "an error occurred".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mediahub.log_sentinel.render_api import LogLine

MAX_EVIDENCE = 5
EVIDENCE_TRIM = 300  # chars per evidence line

# Evidence is verbatim production log text that leaves the process — it is
# written to the audit ledger, pushed to ntfy topics, fed to AI triage and filed
# into an external GitHub issue whose title flows into docs/ROADMAP.md. Access
# logs can carry provider keys in query strings (Gemini's ``?key=AIza...``),
# Authorization headers and athlete PII (emails). Redact BEFORE evidence is built
# so every downstream sink is covered at once (CLAUDE.md: keys/PII must never
# appear in user-visible text).
_REDACTIONS: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(
            r"(?i)\b((?:api[_-]?key|access[_-]?token|key|token|secret|password|pwd)\s*[=:]\s*)"
            r"[^\s&'\"]+"
        ),
        r"\1***",
    ),
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)\S+"), r"\1***"),
    (re.compile(r"(?i)\b(bearer\s+)\S+"), r"\1***"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{6,}"), "sk-ant-***"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{10,}"), "AIza***"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email redacted>"),
)


def redact_evidence(text: str) -> str:
    """Mask provider keys, auth headers and emails from a log line before it
    leaves the box (audit ledger, ntfy, GitHub issue, AI triage)."""
    for pat, repl in _REDACTIONS:
        text = pat.sub(repl, text)
    return text


@dataclass(frozen=True)
class Finding:
    """One detected issue in a polled log batch."""

    issue_id: str
    severity: str  # "info" | "warning" | "critical"
    title: str
    suggestion: str
    count: int
    evidence: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Detector:
    issue_id: str
    severity: str
    title: str
    pattern: re.Pattern
    suggestion: str
    threshold: int = 1  # min matches in one batch before it becomes a Finding
    # A line that matches ``pattern`` but ALSO matches ``exclude`` is not a
    # finding — used to skip MediaHub's own benign diagnostics that merely name
    # an error class in prose (e.g. the boot env-check warning that documents the
    # honest-error behaviour, #1065) without dropping the genuine runtime event.
    exclude: re.Pattern | None = None
    # How many lines AFTER each match to fold into the evidence. Tracebacks are
    # logged frame-per-line, so a header-only pattern yields contentless evidence
    # unless the following frames come with it.
    context_after: int = 0


DETECTORS: tuple[Detector, ...] = (
    Detector(
        issue_id="searxng_unavailable",
        severity="warning",
        title="SearXNG search backend unreachable",
        pattern=re.compile(r"SearXNG unavailable, falling back to DuckDuckGo"),
        suggestion=(
            "The in-container SearXNG isn't answering, so web research is running on "
            "the weaker DuckDuckGo fallback. Check /healthz/search for the live state "
            "and the deploy's boot log for the SearXNG start lines (docs/SEARXNG.md)."
        ),
    ),
    Detector(
        issue_id="searxng_boot_failed",
        severity="info",
        title="SearXNG did not start at boot",
        pattern=re.compile(r"SearXNG did not answer on 127\.0\.0\.1:8888|SearXNG is not installed"),
        suggestion=(
            "The entrypoint reported SearXNG missing or not answering at boot; the app "
            "fell back to DuckDuckGo honestly. If this repeats every deploy, the image "
            "build's SearXNG install step is failing — check the build log for "
            "'searxng OK' vs the WARN line (Dockerfile, docs/SEARXNG.md)."
        ),
    ),
    Detector(
        issue_id="worker_timeout",
        severity="critical",
        title="Gunicorn worker timeout (wedged request)",
        pattern=re.compile(r"WORKER TIMEOUT"),
        suggestion=(
            "A request held a worker past the 300s timeout; gunicorn killed it. If this "
            "repeats, a route is hanging (often a render or an outbound call without a "
            "timeout). Auto-fix (when enabled): restart the service to clear wedged state."
        ),
    ),
    Detector(
        issue_id="worker_sigterm_churn",
        severity="warning",
        title="Workers repeatedly SIGTERMed (memory pressure?)",
        # The bang form is gunicorn's abnormal-kill message. Routine max-requests
        # recycling logs "Autorestarting worker after current request", which this
        # deliberately does NOT match. Threshold 3: one deploy SIGTERMs each worker
        # once; a churn loop produces a stream.
        pattern=re.compile(r"Worker was sent SIGTERM!"),
        suggestion=(
            "Multiple workers were SIGTERMed in one window — the historical signature of "
            "memory pressure on this deployment (see the gunicorn flag notes in "
            "scripts/docker-entrypoint.sh). Check /healthz/memory; consider "
            "MEDIAHUB_RUN_SEARXNG=0 to free ~150-250 MB."
        ),
        threshold=3,
    ),
    Detector(
        issue_id="out_of_memory",
        severity="critical",
        title="Out-of-memory signals",
        pattern=re.compile(r"MemoryError|Cannot allocate memory|Out of memory|oom-kill"),
        suggestion=(
            "The container is hitting its RAM ceiling (renders can spike ~800 MB per "
            "worker). Check /healthz/memory. Auto-fix (when enabled): restart the "
            "service; durable fixes are MEDIAHUB_RUN_SEARXNG=0 or a larger instance."
        ),
    ),
    Detector(
        issue_id="disk_full",
        severity="critical",
        title="Persistent disk full",
        pattern=re.compile(r"No space left on device|\[Errno 28\]"),
        suggestion=(
            "DATA_DIR's disk is full — uploads, runs and motion_cache will start "
            "failing. Grow the Render disk or clear old runs/motion_cache. A restart "
            "will NOT fix this."
        ),
    ),
    Detector(
        issue_id="http_5xx",
        severity="warning",
        title="HTTP 5xx responses",
        # Matches the entrypoint's access-log format: ... "GET /path HTTP/1.1" 500 ...
        pattern=re.compile(r'HTTP/[\d.]+"\s+5\d\d\b'),
        suggestion=(
            "Requests are failing server-side. The evidence lines show which routes; "
            "correlate with tracebacks in the same window."
        ),
        threshold=5,
    ),
    Detector(
        issue_id="llm_provider_down",
        severity="warning",
        title="AI provider unavailable",
        pattern=re.compile(r"ClaudeUnavailableError|ProviderNotConfigured"),
        # The env-check warning at boot/build ("env check: No LLM provider
        # configured — AI surfaces will honest-error (ClaudeUnavailableError) …")
        # names the exception class in prose to DOCUMENT the intended honest-error
        # behaviour; it is not a runtime provider failure. Excluding it stops the
        # sentinel from filing a spurious "provider down" incident every keyless
        # build/boot (#1065) while a genuine raised ClaudeUnavailableError /
        # ProviderNotConfigured during request handling still fires.
        exclude=re.compile(r"env check:|will honest-error"),
        suggestion=(
            "AI surfaces are raising honest 'unavailable' errors (MediaHub never "
            "substitutes fake output). Check GEMINI_API_KEY / ANTHROPIC_API_KEY validity "
            "and /healthz/usage for provider errors or quota exhaustion."
        ),
    ),
    Detector(
        issue_id="unhandled_traceback",
        severity="warning",
        title="Unhandled Python traceback",
        pattern=re.compile(r"Traceback \(most recent call last\)"),
        suggestion=(
            "An exception escaped to the logs. The evidence shows the surrounding "
            "lines; fix belongs in code, so this is notify-only."
        ),
        # Carry the frames after the header, or the evidence is just the bare
        # "Traceback (most recent call last):" line repeated with no context.
        context_after=6,
    ),
)


def detect(lines: list[LogLine]) -> list[Finding]:
    """Run every detector over one batch; return findings that met threshold."""
    findings: list[Finding] = []
    for det in DETECTORS:
        match_idxs = [
            i
            for i, ln in enumerate(lines)
            if det.pattern.search(ln.message)
            and not (det.exclude and det.exclude.search(ln.message))
        ]
        if len(match_idxs) < det.threshold:
            continue
        # Evidence is each match plus the following ``context_after`` lines (so a
        # traceback carries its frames, not just the header), de-duplicated by
        # index and capped at MAX_EVIDENCE total lines.
        ev_idxs: list[int] = []
        seen: set[int] = set()
        for i in match_idxs:
            for j in range(i, min(i + 1 + det.context_after, len(lines))):
                if j not in seen:
                    seen.add(j)
                    ev_idxs.append(j)
        evidence = tuple(
            redact_evidence(f"{lines[j].timestamp} {lines[j].message}".strip())[:EVIDENCE_TRIM]
            for j in ev_idxs[:MAX_EVIDENCE]
        )
        findings.append(
            Finding(
                issue_id=det.issue_id,
                severity=det.severity,
                title=det.title,
                suggestion=det.suggestion,
                count=len(match_idxs),
                evidence=evidence,
            )
        )
    return findings


__all__ = ["Finding", "Detector", "DETECTORS", "detect", "redact_evidence", "MAX_EVIDENCE"]
