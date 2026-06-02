"""Deduplicated bug ledger + fix-ready Markdown report.

``reports/ledger.json`` is the source of truth: one entry per unique defect,
keyed by a stable fingerprint so re-running the tester every few hours updates
``last_seen`` / ``seen_count`` instead of appending duplicates. ``BUGS.md`` is
rendered from the ledger — for a human to read and for a Claude Code fix
session to act on by reading alone.

The fingerprint normalises away run-specific noise (uuids, timestamps, hex run
ids, line offsets, memory addresses) so the *same* defect produces the *same*
fingerprint across runs and machines.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
LEDGER_PATH = REPORTS_DIR / "ledger.json"
BUGS_MD_PATH = REPORTS_DIR / "BUGS.md"

# Schema v2 (Tier A): per-finding lifecycle fields — confirmations / pending
# tracking (A1), absent_streak + auto_closed_at (A2). ``load_ledger`` backfills
# them onto pre-v2 entries so an old ledger.json keeps working unchanged.
SCHEMA_VERSION = 2
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Statuses the fix loop owns. The finder (run.py) must never downgrade these
# back to "open" — once a fix is in flight or merged we stop re-filing it.
# ``verified-fixed`` is a TERMINAL audit state (council): a finding confirmed
# already-resolved by external evidence (a prior commit and/or a finder-precision
# fix that eliminates a false-positive) and retired with a commit/test/signature
# record — NOT a loop-authored fix. It is fix-owned so a re-detection cannot
# reopen it.
# ``needs_disproof`` is a QUARANTINE state (council 2026-06-01): the coder
# investigated the finding, completed cleanly, and DECLINED to edit (a likely
# false-positive / already-correct behaviour). It is removed from the fix loop so
# we stop the infinite-retry bleed, but it is NOT a close — it awaits a
# deterministic ground-truth repro to either reopen (real) or confirm false. It is
# fix-owned so the noisy live finder cannot silently reopen it; only a deliberate
# ground-truth sweep or a human audit should.
FIX_OWNED_STATUSES = {"fixing", "fixed", "wontfix", "verified-fixed", "needs_disproof"}


# --- finding lifecycle (Tier A: trust) ---------------------------------------
# A SUBJECTIVE finding is a judgement call — an LLM judge (``semantic:*``), the
# vision judge (``vision:*``), or the council (``council:*``). These get the
# pending→open *confirm-on-repeat* gate (A1) and faster decay (A2): a single AI
# sighting is too noisy to open a bug on (the report's core finding — mirrors
# Prometheus ``for:`` / Grafana "Pending period"). Everything else is
# DETERMINISTIC (code-produced: http_5xx, server_traceback, broken_link,
# ground_truth_*, baseline:*, and the new a11y / contract / visual_regression
# classes) → inserts straight to ``open`` and decays only slowly.
SUBJECTIVE_PREFIXES = ("semantic", "vision", "council")

# A3 — a defect that recurs after being closed is a REGRESSION: reopened and
# surfaced at the top of BUGS.md. ``verified-fixed`` is deliberately EXCLUDED: it
# is a terminal, evidence-backed audit state (often a *confirmed false-positive*),
# and the noisy finder must never resurrect it — that preserves the council Q3
# invariant and ``test_redetection_does_not_reopen_a_retired_finding``. ``wontfix``
# / ``needs_disproof`` are human / ground-truth-owned, likewise not finder-reopened.
_REGRESSION_REOPEN_FROM = {"fixed", "auto-closed"}

# Only actionable states decay (A2); terminal / fix-owned / quarantine states never do.
_DECAYABLE = {"open", "pending"}

# Ledger fields added in schema v2 (A1–A3). ``load_ledger`` backfills these onto
# every pre-v2 entry, so an old ledger.json loads unchanged.
_V2_DEFAULTS: dict[str, Any] = {
    "confirmations": 0,
    "first_pending_run_id": None,
    "first_pending_at": None,
    "absent_streak": 0,
    "auto_closed_at": None,
}


def is_subjective(category: str) -> bool:
    """True for an AI/judgement finding — gets the A1 confirm gate + A2 fast decay."""
    return (category or "").startswith(SUBJECTIVE_PREFIXES)


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _confirm_sweeps() -> int:
    """Extra sweeps a *subjective* finding must recur before pending→open (A1).
    Default 2 → seen in 3 sweeps total. 0 disables the gate (straight to open)."""
    return _env_int("AUTOTEST_CONFIRM_SWEEPS", 2)


def _decay_sweeps(subjective: bool) -> int:
    """Consecutive absent sweeps before a finding auto-closes (A2). 0 disables decay."""
    return (_env_int("AUTOTEST_DECAY_SWEEPS_SUBJECTIVE", 3) if subjective
            else _env_int("AUTOTEST_DECAY_SWEEPS_DETERMINISTIC", 6))


def council_precision() -> float | None:
    """The council's measured precision vs the human calibration set, if computed
    (``autotest/metrics.py`` writes ``calibration/precision.json``). None when
    unknown → callers fall back to default behaviour. Used to scale the A1 confirm
    gate (low precision → demand more confirmations) and to print the BUGS.md
    "🔬 Judge trust" line (A5)."""
    path = REPORTS_DIR.parent / "calibration" / "precision.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        p = data.get("precision")
        return float(p) if p is not None else None
    except (OSError, ValueError, TypeError):
        return None


def effective_confirm_sweeps(base: int, precision: float | None) -> int:
    """Scale the A1 confirm gate by measured council precision (A5, optional):
    lower precision → trust the judges less → require more confirmations. Falls
    back to ``base`` when precision is unknown or the gate is already disabled."""
    if precision is None or base <= 0:
        return base
    if precision >= 0.8:
        return base
    if precision >= 0.6:
        return base + 1
    return base + 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- normalisation -----------------------------------------------------------
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*")
_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_NUM = re.compile(r"\b\d+\b")


def normalise(text: str) -> str:
    """Strip run-specific tokens so equivalent defects hash identically."""
    t = text or ""
    t = _UUID.sub("<id>", t)
    t = _TS.sub("<ts>", t)
    t = _ADDR.sub("<addr>", t)
    t = _HEX.sub("<id>", t)
    t = _NUM.sub("<n>", t)
    return " ".join(t.split()).strip().lower()


def fingerprint(category: str, route: str, signal: str) -> str:
    """Stable 12-char id for a defect = hash(category | route | key signal)."""
    basis = "|".join((category or "", normalise(route), normalise(signal)))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


# Coarse, STABLE "what kind of defect is this" buckets. LLM judges phrase the
# same defect a dozen ways across runs (and vary the route), so hashing their
# wording explodes one defect into many fingerprints. For LLM findings we hash a
# defect CLASS instead, collapsing the re-phrasings into one ledger entry.
_DEFECT_CLASSES = (
    ("zero_cards", ("0 card", "zero card", "no card", "no content", "empty content",
                    "content pack", "produced no", "produced zero", "cards=0",
                    "content is empty", "no content cards")),
    ("blank_page", ("blank", "empty page", "empty review", "review page",
                    "review screen", "review pages")),
    ("data_leak", ("data leak", "cross-operator", "cross operator", "idor",
                   "another operator", "not belong", "isolation")),
    ("export_broken", ("export 404", "export fails", "export unreachable", "download fails")),
    ("http_404", ("404", "not found")),
    ("http_5xx", ("500", "5xx", "server error", "internal server")),
    ("traceback", ("traceback", "stack trace", "unhandled exception")),
    ("missing_feedback", ("no feedback", "actionable feedback", "user feedback",
                          "unclear status", "raw internal status")),
)


def _defect_class(text: str) -> str:
    """Map free-text (title/expected/actual) to a stable defect bucket, or '' if
    none matches (caller then falls back to the normalised title)."""
    t = (text or "").lower()
    for name, kws in _DEFECT_CLASSES:
        if any(k in t for k in kws):
            return name
    return ""


@dataclasses.dataclass
class Finding:
    """One thing the tester observed. ``is_bug=False`` means expected/infra
    (e.g. AI provider not configured) — recorded so the operator can see what
    was deliberately *not* filed, but kept out of the open-bug list."""

    category: str          # http_5xx | server_traceback | js_console_error | ...
    severity: str          # critical | high | medium | low | info
    title: str
    route: str             # URL/route template where it happened
    expected: str
    actual: str
    evidence: str = ""     # traceback / console text / response excerpt
    suspect: str = ""      # best-guess "file:line" in the repo
    repro: list[str] = dataclasses.field(default_factory=list)
    screenshot: str = ""   # path relative to repo root
    rationale: str = ""    # the LLM-Council's WHY, persisted for the fix PR body
    is_bug: bool = True

    def fingerprint(self) -> str:
        # LLM judges (semantic/council/vision) phrase one defect many ways and
        # vary the route, so for them hash a STABLE defect class — collapsing
        # re-phrasings of the same defect into a single ledger entry.
        # Deterministic findings keep their precise suspect/evidence signal.
        if (self.category or "").startswith(("semantic", "council", "vision")):
            dc = _defect_class(f"{self.title} {self.expected} {self.actual}")
            if dc:
                return fingerprint("llm", "", dc)
            # No defect-class match: DON'T hash the LLM's exact title (it rewords it
            # every run, exploding one defect into many entries). Hash (category,
            # normalised route) so the same kind of finding at the same surface
            # collapses to one entry regardless of wording (generation-time dedup).
            return fingerprint(self.category, self.route, "")
        signal = self.suspect or self.evidence[:200] or self.title
        return fingerprint(self.category, self.route, signal)


# --- ledger I/O --------------------------------------------------------------
def load_ledger() -> dict[str, Any]:
    if LEDGER_PATH.exists():
        try:
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            data.setdefault("bugs", {})
            data.setdefault("skipped", {})
            return _migrate(data)
        except (ValueError, OSError):
            pass
    return {"schema": SCHEMA_VERSION, "generated_at": None, "bugs": {}, "skipped": {}}


def _migrate(ledger: dict[str, Any]) -> dict[str, Any]:
    """Backfill schema-v2 lifecycle fields (A1–A3) onto old entries so a pre-v2
    ledger keeps loading. Idempotent; NEVER changes an entry's status (existing
    ``open`` findings stay open — the pending gate applies only to NEWLY seen
    subjective findings, so a migrated ledger isn't retroactively re-gated)."""
    for bucket in ("bugs", "skipped"):
        for entry in ledger.get(bucket, {}).values():
            for k, v in _V2_DEFAULTS.items():
                entry.setdefault(k, v)
    ledger["schema"] = SCHEMA_VERSION
    return ledger


def save_ledger(ledger: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    # Trailing newline so the ledger is POSIX-clean and passes the end-of-file
    # hygiene hook if it ever rides in a PR (the loop's own pushes skip CI).
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def merge_findings(findings: list[Finding], run_id: str) -> dict[str, int]:
    """Fold this run's findings into the ledger. Returns summary counts.

    Finding lifecycle (Tier A — trust):
      * A1 confirm-on-repeat — a newly-seen **subjective** finding enters
        ``pending`` (not ``open``); each sweep it recurs bumps ``confirmations``;
        at ``AUTOTEST_CONFIRM_SWEEPS`` it transitions ``pending → open``. A
        **deterministic** finding inserts straight to ``open``.
      * A2 decay — a finding not seen this run has ``absent_streak`` incremented;
        when it crosses the (subjective vs deterministic) decay threshold an
        ``open``/``pending`` finding transitions to ``auto-closed`` (the record is
        KEPT, never deleted, so a recurrence can reopen it). Terminal / fix-owned
        states never decay.
      * A3 regression — a fingerprint in ``fixed``/``auto-closed`` that recurs is
        reopened as ``regressed`` and surfaced at the top of BUGS.md.

    Fix-owned statuses are never downgraded by the finder (only ``fixed`` and
    ``auto-closed`` reopen, as regressions — ``verified-fixed`` stays terminal).
    """
    ledger = load_ledger()
    now = _now_iso()
    seen_fps: set[str] = set()
    new_bugs = 0
    confirm_target = effective_confirm_sweeps(_confirm_sweeps(), council_precision())

    for f in findings:
        fp = f.fingerprint()
        seen_fps.add(fp)
        bucket = "bugs" if f.is_bug else "skipped"
        store = ledger[bucket]
        subjective = is_subjective(f.category)
        if fp in store:
            entry = store[fp]
            entry["last_seen"] = now
            entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
            entry["last_run_id"] = run_id
            entry["present_last_run"] = True
            entry["absent_streak"] = 0   # A2: a recurrence resets the decay clock
            # Refresh the volatile detail (latest evidence wins) but never
            # touch fix-loop-owned fields or first_seen.
            entry["severity"] = f.severity
            entry["title"] = f.title
            entry["expected"] = f.expected
            entry["actual"] = f.actual
            entry["evidence"] = f.evidence
            entry["suspect"] = f.suspect
            if f.rationale:
                entry["rationale"] = f.rationale[:2000]
            entry["repro"] = f.repro
            if f.screenshot:
                entry["screenshot"] = f.screenshot
            # --- lifecycle transitions on recurrence (bugs only) ---
            if f.is_bug:
                status = entry.get("status")
                if status in _REGRESSION_REOPEN_FROM:
                    entry["status"] = "regressed"          # A3: it came back
                    entry["regressed_at"] = now
                elif status == "pending":
                    entry["confirmations"] = int(entry.get("confirmations", 0)) + 1
                    if entry["confirmations"] >= confirm_target:
                        entry["status"] = "open"           # A1: confirmed
                        entry["opened_at"] = now
                # open / fixing / fixed-owned / regressed: unchanged.
        else:
            # A1: a new SUBJECTIVE bug starts ``pending`` (confirm-on-repeat);
            # deterministic bugs and all skipped/info entries start ``open``.
            pending = bool(f.is_bug and subjective and confirm_target > 0)
            store[fp] = {
                "fingerprint": fp,
                "category": f.category,
                "severity": f.severity,
                "title": f.title,
                "route": f.route,
                "expected": f.expected,
                "actual": f.actual,
                "evidence": f.evidence,
                "suspect": f.suspect,
                "rationale": (f.rationale or "")[:2000],
                "repro": f.repro,
                "screenshot": f.screenshot,
                "status": "pending" if pending else "open",
                "first_seen": now,
                "last_seen": now,
                "seen_count": 1,
                "last_run_id": run_id,
                "present_last_run": True,
                "fix_pr": None,
                "fix_branch": None,
                "confirmations": 0,
                "first_pending_run_id": run_id if pending else None,
                "first_pending_at": now if pending else None,
                "absent_streak": 0,
                "auto_closed_at": None,
            }
            if f.is_bug:
                new_bugs += 1

    # Mark everything not seen this run, then decay (A2) the ones that have been
    # absent too long. The record is kept (status flips to ``auto-closed``), so a
    # later recurrence reopens it as a regression (A3).
    for bucket in ("bugs", "skipped"):
        for fp, entry in ledger[bucket].items():
            if fp in seen_fps:
                continue
            entry["present_last_run"] = False
            entry["absent_streak"] = int(entry.get("absent_streak", 0)) + 1
            if bucket != "bugs" or entry.get("status") not in _DECAYABLE:
                continue
            threshold = _decay_sweeps(is_subjective(entry.get("category", "")))
            if threshold and entry["absent_streak"] >= threshold:
                entry["status"] = "auto-closed"
                entry["auto_closed_at"] = now
                entry["archived_reason"] = (
                    f"decayed: not reproduced for {entry['absent_streak']} consecutive sweeps")

    ledger["schema"] = SCHEMA_VERSION
    ledger["generated_at"] = now
    save_ledger(ledger)

    def _n(status: str) -> int:
        return sum(1 for b in ledger["bugs"].values() if b.get("status") == status)

    return {
        "open": _n("open"),
        "pending": _n("pending"),
        "regressed": _n("regressed"),
        "auto_closed": _n("auto-closed"),
        "new": new_bugs,
        "fixing": _n("fixing"),
        "fixed": _n("fixed"),
        "verified_fixed": _n("verified-fixed"),
        "needs_disproof": _n("needs_disproof"),
        "skipped": len(ledger["skipped"]),
        "total_bugs": len(ledger["bugs"]),
    }


def retire_verified_fixed(fingerprint: str, *, commit: str, tests: str, note: str,
                          verified_by: str) -> bool:
    """Retire a finding to the TERMINAL ``verified-fixed`` state with an evidence
    record (council Q3). Use for a finding confirmed already-resolved by external
    evidence — a prior commit and/or a finder-precision fix that eliminates a
    false-positive — rather than by a loop-authored fix. Records the council's
    required fields (commit hash, test evidence, human signature, note) as a
    permanent audit trail. The change itself ships as a harness PR, so the human
    who merges it is the signing gate. Returns False for an unknown fingerprint.
    """
    ledger = load_ledger()
    entry = ledger["bugs"].get(fingerprint)
    if not entry:
        return False
    entry["status"] = "verified-fixed"
    entry["verified_fixed"] = {
        "commit": commit, "tests": tests, "note": note,
        "verified_by": verified_by, "at": _now_iso(),
    }
    save_ledger(ledger)
    return True


def quarantine_needs_disproof(fingerprint: str, *, conclusion: str, coder_attempts: int) -> bool:
    """Quarantine a finding to ``needs_disproof`` (council 2026-06-01). Use when the
    coder investigated the finding, completed cleanly, and made NO edits — i.e. it
    DECLINED to change anything (a likely false-positive / already-correct
    behaviour). This removes the finding from the fix loop so we stop burning ~900s
    per never-ending retry, WITHOUT closing it (not ``wontfix`` — the accused coder
    does not get to self-acquit): it awaits a deterministic ground-truth repro to
    reopen (real) or confirm false. Records the coder's own conclusion for audit.
    Returns False for an unknown fingerprint."""
    ledger = load_ledger()
    entry = ledger["bugs"].get(fingerprint)
    if not entry:
        return False
    entry["status"] = "needs_disproof"
    entry["needs_disproof"] = {
        "coder_conclusion": (conclusion or "")[:1500],
        "coder_attempts": coder_attempts,
        "at": _now_iso(),
    }
    save_ledger(ledger)
    return True


# --- Markdown rendering ------------------------------------------------------
def _sev_rank(entry: dict[str, Any]) -> tuple[int, str]:
    return (SEVERITY_ORDER.get(entry.get("severity", "low"), 3), entry.get("last_seen", ""))


def _trust_line() -> str:
    """The "🔬 Judge trust" line (A5): the council's measured precision/recall vs
    the human calibration set, if computed. Empty when not yet measured."""
    path = REPORTS_DIR.parent / "calibration" / "precision.json"
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    p, r, n = m.get("precision"), m.get("recall"), m.get("n_labelled")
    if p is None:
        return ""
    parts = [f"**🔬 Judge trust:** council precision `{p:.2f}`"]
    if r is not None:
        parts.append(f"recall `{r:.2f}`")
    parts.append(f"(vs {n if n is not None else '?'} human-labelled findings; "
                 "`python -m autotest.metrics`)")
    return " · ".join(parts)


def _render_bug(entry: dict[str, Any]) -> str:
    sev = entry.get("severity", "low").upper()
    lines = [
        f"### [{sev}] {entry.get('title', 'Untitled')} · `{entry['fingerprint']}`",
        "",
        f"- **Category:** `{entry.get('category', '?')}`",
        f"- **Where:** `{entry.get('route', '?')}`",
        f"- **Seen:** {entry.get('seen_count', 1)}× · first `{entry.get('first_seen', '?')}` · last `{entry.get('last_seen', '?')}`"
        + ("" if entry.get("present_last_run", True) else " · ⚠️ not reproduced in latest run"),
    ]
    if entry.get("suspect"):
        lines.append(f"- **Suspected source:** `{entry['suspect']}`")
    if entry.get("repro"):
        lines.append("- **Repro:**")
        lines += [f"  {i}. {step}" for i, step in enumerate(entry["repro"], 1)]
    lines.append(f"- **Expected:** {entry.get('expected', '?')}")
    lines.append(f"- **Actual:** {entry.get('actual', '?')}")
    if entry.get("evidence"):
        ev = entry["evidence"].strip()
        if len(ev) > 4000:
            ev = ev[:4000] + "\n… (truncated; full text in ledger.json)"
        lines += ["- **Evidence:**", "", "```", ev, "```"]
    if entry.get("screenshot"):
        lines.append(f"- **Screenshot:** `{entry['screenshot']}` (also uploaded as a CI run artifact)")
    lines.append("")
    return "\n".join(lines)


def render_markdown(run_meta: dict[str, Any]) -> str:
    ledger = load_ledger()
    bugs = list(ledger["bugs"].values())
    regressed = sorted((b for b in bugs if b.get("status") == "regressed"), key=_sev_rank)
    open_bugs = sorted((b for b in bugs if b.get("status") == "open"), key=_sev_rank)
    pending = sorted((b for b in bugs if b.get("status") == "pending"),
                     key=lambda b: (_sev_rank(b), -int(b.get("confirmations", 0))))
    auto_closed = sorted((b for b in bugs if b.get("status") == "auto-closed"),
                         key=lambda b: b.get("auto_closed_at", ""), reverse=True)
    fixing = sorted((b for b in bugs if b.get("status") == "fixing"), key=_sev_rank)
    fixed = sorted((b for b in bugs if b.get("status") == "fixed"),
                   key=lambda b: b.get("last_seen", ""), reverse=True)
    verified = sorted((b for b in bugs if b.get("status") == "verified-fixed"),
                      key=lambda b: (b.get("verified_fixed") or {}).get("at", ""), reverse=True)
    needs_disproof = sorted((b for b in bugs if b.get("status") == "needs_disproof"),
                            key=lambda b: (b.get("needs_disproof") or {}).get("at", ""), reverse=True)
    skipped = sorted(ledger["skipped"].values(), key=_sev_rank)

    by_sev: dict[str, int] = {}
    for b in open_bugs:
        by_sev[b["severity"]] = by_sev.get(b["severity"], 0) + 1

    out: list[str] = []
    out.append("# MediaHub — Autonomous Test Bug Report")
    out.append("")
    out.append("> Generated by `autotest/run.py`. **Do not hand-edit** — this file is "
               "regenerated from `ledger.json` every run. To fix a bug, paste its "
               "section into a Claude Code session; everything needed to reproduce and "
               "locate it is below.")
    out.append("")
    out.append(f"- **Last run:** `{run_meta.get('run_id', '?')}` at `{ledger.get('generated_at', '?')}`")
    out.append(f"- **Target:** `{run_meta.get('base_url', '?')}`")
    out.append(f"- **Routes probed:** {run_meta.get('routes_probed', '?')} · "
               f"**Pages crawled:** {run_meta.get('pages_crawled', '?')} · "
               f"**Primary flow:** {run_meta.get('flow_result', '?')}")
    sev_summary = ", ".join(f"{n} {s}" for s, n in
                            sorted(by_sev.items(), key=lambda kv: SEVERITY_ORDER.get(kv[0], 9))) or "none"
    out.append(f"- **Open bugs:** {len(open_bugs)} ({sev_summary}) · "
               f"**Regressed:** {len(regressed)} · **Pending confirmation:** {len(pending)} · "
               f"**In progress:** {len(fixing)} · **Fixed:** {len(fixed)} · "
               f"**Verified-fixed (retired):** {len(verified)} · "
               f"**Auto-closed (decayed):** {len(auto_closed)} · "
               f"**Needs-disproof (quarantined):** {len(needs_disproof)} · "
               f"**Skipped (expected/infra):** {len(skipped)}")
    trust = _trust_line()
    if trust:
        out.append(f"- {trust}")
    if run_meta.get("council_verdict"):
        out.append(f"- **🏛️ {run_meta['council_verdict']}** "
                   "(full transcript under `autotest/reports/council/`)")
    out.append("")

    if regressed:
        out.append("## 🔁 Regressed (a closed defect came back — fix first)")
        out.append("")
        out.append("_These were previously fixed or auto-closed and have RE-APPEARED. "
                   "A recurrence after closure is the highest-signal finding here._")
        out.append("")
        for b in regressed:
            prior = b.get("fix_pr") or b.get("fix_branch")
            out.append(_render_bug(b))
            if prior:
                out.append(f"- **Prior fix:** `{prior}` (regressed {b.get('regressed_at', '?')})")
                out.append("")

    out.append("## 🔴 Open bugs")
    out.append("")
    if open_bugs:
        for b in open_bugs:
            out.append(_render_bug(b))
    else:
        out.append("_No open bugs detected in the latest run._")
        out.append("")

    if pending:
        out.append("## ⏳ Pending confirmation (subjective — not yet a bug)")
        out.append("")
        out.append("_AI/judge findings seen too few times to open. The fixer IGNORES "
                   "these; each sweep they recur bumps the count, and at "
                   f"`AUTOTEST_CONFIRM_SWEEPS` they become open bugs. One-shot noise "
                   "decays out instead._")
        out.append("")
        for b in pending:
            conf = int(b.get("confirmations", 0))
            out.append(f"- [{b.get('severity', '?').upper()}] {b.get('title', '?')} · "
                       f"`{b['fingerprint']}` ({b.get('category', '?')}) — confirmed "
                       f"{conf}× since `{b.get('first_pending_at', '?')}`"
                       + ("" if b.get("present_last_run", True) else " · not in latest run"))
        out.append("")

    if fixing:
        out.append("## 🟡 In progress (fix loop has an open PR — don't double-assign)")
        out.append("")
        for b in fixing:
            pr = b.get("fix_pr") or "?"
            out.append(f"- [{b['severity'].upper()}] {b['title']} · `{b['fingerprint']}` → PR {pr}")
        out.append("")

    if fixed:
        out.append("<details><summary>✅ Fixed (audit trail)</summary>")
        out.append("")
        for b in fixed[:50]:
            pr = b.get("fix_pr") or "?"
            out.append(f"- {b['title']} · `{b['fingerprint']}` → PR {pr} (fixed {b.get('last_seen', '?')})")
        out.append("")
        out.append("</details>")
        out.append("")

    if verified:
        out.append("<details><summary>🗂️ Verified-fixed — retired with evidence "
                   f"({len(verified)})</summary>")
        out.append("")
        for b in verified:
            vf = b.get("verified_fixed") or {}
            out.append(f"- {b['title']} · `{b['fingerprint']}` — verified via "
                       f"`{vf.get('commit', '?')}` ({vf.get('tests', '?')}); "
                       f"{vf.get('note', '')} — by {vf.get('verified_by', '?')} "
                       f"at {vf.get('at', '?')}")
        out.append("")
        out.append("</details>")
        out.append("")

    if auto_closed:
        out.append("<details><summary>🗃️ Auto-closed — decayed, not reproduced for N "
                   f"sweeps ({len(auto_closed)})</summary>")
        out.append("")
        out.append("_Findings that stopped recurring and aged out (A2 decay). The record "
                   "is KEPT — if the same fingerprint recurs it reopens at the top as a "
                   "regression (A3). This is how one-shot noise leaves the open list "
                   "without being lost._")
        out.append("")
        for b in auto_closed[:80]:
            out.append(f"- [{b.get('severity', '?').upper()}] {b.get('title', '?')} · "
                       f"`{b['fingerprint']}` ({b.get('category', '?')}) — "
                       f"{b.get('archived_reason', 'decayed')} (closed {b.get('auto_closed_at', '?')})")
        out.append("")
        out.append("</details>")
        out.append("")

    if needs_disproof:
        out.append("<details><summary>🔬 Needs-disproof — coder investigated &amp; "
                   f"declined to edit; awaiting a ground-truth repro ({len(needs_disproof)})</summary>")
        out.append("")
        out.append("_The coder completed cleanly but made no edits — a likely "
                   "false-positive / already-correct behaviour. Quarantined from the fix "
                   "loop (no more retries) but NOT closed: a deterministic seeded sweep or "
                   "a human audit reopens it if real._")
        out.append("")
        for b in needs_disproof:
            nd = b.get("needs_disproof") or {}
            concl = " ".join((nd.get("coder_conclusion") or "").split())[:240]
            out.append(f"- [{b.get('severity', '?').upper()}] {b['title']} · "
                       f"`{b['fingerprint']}` ({b.get('category', '?')}) — after "
                       f"{nd.get('coder_attempts', '?')} attempt(s): {concl}")
        out.append("")
        out.append("</details>")
        out.append("")

    if skipped:
        out.append("<details><summary>⚪ Skipped — expected / infrastructure, NOT bugs "
                   f"({len(skipped)})</summary>")
        out.append("")
        out.append("These matched a known-expected signature (e.g. AI provider not "
                   "configured in CI) and were deliberately not filed as bugs.")
        out.append("")
        for s in skipped:
            out.append(f"- `{s.get('category', '?')}` at `{s.get('route', '?')}` — "
                       f"{s.get('title', '?')} (seen {s.get('seen_count', 1)}×)")
        out.append("")
        out.append("</details>")
        out.append("")

    return "\n".join(out)


def write_report(run_meta: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BUGS_MD_PATH.write_text(render_markdown(run_meta), encoding="utf-8")
