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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
LEDGER_PATH = REPORTS_DIR / "ledger.json"
BUGS_MD_PATH = REPORTS_DIR / "BUGS.md"

SCHEMA_VERSION = 1
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Statuses the fix loop owns. The finder (run.py) must never downgrade these
# back to "open" — once a fix is in flight or merged we stop re-filing it.
FIX_OWNED_STATUSES = {"fixing", "fixed", "wontfix"}


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
    is_bug: bool = True

    def fingerprint(self) -> str:
        # LLM judges (semantic/council) phrase one defect many ways and vary the
        # route, so for them hash a STABLE defect class — collapsing re-phrasings
        # of the same defect into a single ledger entry. Deterministic findings
        # keep their precise suspect/evidence signal.
        if (self.category or "").startswith(("semantic", "council")):
            dc = _defect_class(f"{self.title} {self.expected} {self.actual}")
            if dc:
                return fingerprint("llm", "", dc)
            return fingerprint(self.category, self.route, self.title)
        signal = self.suspect or self.evidence[:200] or self.title
        return fingerprint(self.category, self.route, signal)


# --- ledger I/O --------------------------------------------------------------
def load_ledger() -> dict[str, Any]:
    if LEDGER_PATH.exists():
        try:
            data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            data.setdefault("bugs", {})
            data.setdefault("skipped", {})
            return data
        except (ValueError, OSError):
            pass
    return {"schema": SCHEMA_VERSION, "generated_at": None, "bugs": {}, "skipped": {}}


def save_ledger(ledger: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, sort_keys=False), encoding="utf-8")


def merge_findings(findings: list[Finding], run_id: str) -> dict[str, int]:
    """Fold this run's findings into the ledger. Returns summary counts.

    New defects are inserted (status ``open``); already-known defects have
    ``last_seen`` / ``seen_count`` bumped without disturbing fix-loop state.
    Defects not seen this run are flagged ``present_last_run = False`` but are
    NOT auto-closed — detection can be non-deterministic, so closure is the fix
    loop's job (on merge) or a human's.
    """
    ledger = load_ledger()
    now = _now_iso()
    seen_fps: set[str] = set()
    new_bugs = 0

    for f in findings:
        fp = f.fingerprint()
        seen_fps.add(fp)
        bucket = "bugs" if f.is_bug else "skipped"
        store = ledger[bucket]
        if fp in store:
            entry = store[fp]
            entry["last_seen"] = now
            entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
            entry["last_run_id"] = run_id
            entry["present_last_run"] = True
            # Refresh the volatile detail (latest evidence wins) but never
            # touch fix-loop-owned fields or first_seen.
            entry["severity"] = f.severity
            entry["title"] = f.title
            entry["expected"] = f.expected
            entry["actual"] = f.actual
            entry["evidence"] = f.evidence
            entry["suspect"] = f.suspect
            entry["repro"] = f.repro
            if f.screenshot:
                entry["screenshot"] = f.screenshot
        else:
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
                "repro": f.repro,
                "screenshot": f.screenshot,
                "status": "open",
                "first_seen": now,
                "last_seen": now,
                "seen_count": 1,
                "last_run_id": run_id,
                "present_last_run": True,
                "fix_pr": None,
                "fix_branch": None,
            }
            if f.is_bug:
                new_bugs += 1

    # Mark everything not seen this run.
    for bucket in ("bugs", "skipped"):
        for fp, entry in ledger[bucket].items():
            if fp not in seen_fps:
                entry["present_last_run"] = False

    ledger["schema"] = SCHEMA_VERSION
    ledger["generated_at"] = now
    save_ledger(ledger)

    open_bugs = [b for b in ledger["bugs"].values() if b.get("status") == "open"]
    return {
        "open": len(open_bugs),
        "new": new_bugs,
        "fixing": sum(1 for b in ledger["bugs"].values() if b.get("status") == "fixing"),
        "fixed": sum(1 for b in ledger["bugs"].values() if b.get("status") == "fixed"),
        "skipped": len(ledger["skipped"]),
        "total_bugs": len(ledger["bugs"]),
    }


# --- Markdown rendering ------------------------------------------------------
def _sev_rank(entry: dict[str, Any]) -> tuple[int, str]:
    return (SEVERITY_ORDER.get(entry.get("severity", "low"), 3), entry.get("last_seen", ""))


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
    open_bugs = sorted((b for b in bugs if b.get("status") == "open"), key=_sev_rank)
    fixing = sorted((b for b in bugs if b.get("status") == "fixing"), key=_sev_rank)
    fixed = sorted((b for b in bugs if b.get("status") == "fixed"),
                   key=lambda b: b.get("last_seen", ""), reverse=True)
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
               f"**In progress:** {len(fixing)} · **Fixed:** {len(fixed)} · "
               f"**Skipped (expected/infra):** {len(skipped)}")
    if run_meta.get("council_verdict"):
        out.append(f"- **🏛️ {run_meta['council_verdict']}** "
                   "(full transcript under `autotest/reports/council/`)")
    out.append("")

    out.append("## 🔴 Open bugs")
    out.append("")
    if open_bugs:
        for b in open_bugs:
            out.append(_render_bug(b))
    else:
        out.append("_No open bugs detected in the latest run._")
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
