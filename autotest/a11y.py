"""B2 — accessibility (axe-core) as a DETERMINISTIC finding source.

The deterministic finder answers "did it error?", the AI judges judge meaning, the
vision judge looks at pixels — none check accessibility. A paid human tester would.
After a page renders, this runs axe-core (Deque's WCAG engine, the one inside
Lighthouse a11y) against the live DOM and emits violations as ``a11y`` findings.

``a11y`` is a CODE-produced category, not a judgement, so its findings are
DETERMINISTIC: they open immediately (no A1 confirm gate) and decay slowly — the
right lifecycle for a reproducible WCAG violation. Severity maps from axe's
``impact`` (critical/serious → high, moderate → medium, minor → low).

No new Python dependency: axe-core's JS is injected into the page and run via
``page.evaluate``. The source is located, in order, from:
  1. ``$AUTOTEST_AXE_JS`` (an explicit path to axe.min.js),
  2. a vendored ``autotest/vendor/axe.min.js``,
  3. the ``axe-core`` npm package under ``node_modules`` (the CI installs it).
None found → honest-skip (no crash, no invented finding), exactly like the AI
judges with no key. Toggle with ``AUTOTEST_A11Y`` (default 1).
"""
from __future__ import annotations

import os
from pathlib import Path

from autotest.report import Finding

REPO_ROOT = Path(__file__).resolve().parent.parent

# axe impact → MediaHub severity. A missing impact is treated as low (axe leaves
# ``impact`` null for some best-practice rules).
_IMPACT_SEVERITY = {"critical": "high", "serious": "high",
                    "moderate": "medium", "minor": "low"}

_AXE_CANDIDATES = (
    REPO_ROOT / "autotest" / "vendor" / "axe.min.js",
    REPO_ROOT / "node_modules" / "axe-core" / "axe.min.js",
    REPO_ROOT / "src" / "mediahub" / "remotion" / "node_modules" / "axe-core" / "axe.min.js",
)


def axe_source() -> str | None:
    """Locate axe-core's JS source, or None to honest-skip."""
    explicit = os.environ.get("AUTOTEST_AXE_JS", "").strip()
    candidates = ([Path(explicit)] if explicit else []) + list(_AXE_CANDIDATES)
    for p in candidates:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def available() -> bool:
    return os.environ.get("AUTOTEST_A11Y", "1") != "0" and axe_source() is not None


def _impact_severity(impact: str | None) -> str:
    return _IMPACT_SEVERITY.get((impact or "").lower(), "low")


def findings_from_results(results: dict, route: str) -> list[Finding]:
    """Turn an axe.run() result object into deterministic ``a11y`` findings — one
    per (rule, page), with a STABLE suspect (``axe:<rule_id>``) so the same violation
    on the same route collapses to one ledger entry across runs."""
    out: list[Finding] = []
    for v in (results or {}).get("violations", []) or []:
        if not isinstance(v, dict):
            continue
        rule_id = str(v.get("id", "unknown"))
        impact = v.get("impact")
        nodes = v.get("nodes") or []
        # A few example targets as evidence (capped — don't dump the whole DOM).
        targets = []
        for n in nodes[:5]:
            tgt = n.get("target") if isinstance(n, dict) else None
            if tgt:
                targets.append(" ".join(map(str, tgt)) if isinstance(tgt, list) else str(tgt))
        help_text = str(v.get("help") or v.get("description") or rule_id)[:160]
        out.append(Finding(
            category="a11y", severity=_impact_severity(impact),
            title=f"a11y: {help_text} ({rule_id})"[:140],
            route=route,
            expected="The page meets the WCAG rule axe-core checks",
            actual=f"axe-core '{rule_id}' violation ({impact or 'no-impact'}) on "
                   f"{len(nodes)} element(s)",
            evidence=(f"axe-core rule: {rule_id}\nhelp: {help_text}\n"
                      f"helpUrl: {v.get('helpUrl', '')}\nexample targets:\n  "
                      + "\n  ".join(targets[:5]))[:1500],
            suspect=f"axe:{rule_id}",
            repro=[f"Open {route}", f"Run axe-core; rule '{rule_id}' flags {len(nodes)} node(s)"]))
    return out


def run(page, route: str) -> list[Finding]:
    """Inject axe-core into ``page`` and run it against ``route``'s DOM. Returns
    deterministic findings, or [] (honest-skip) when axe isn't available or anything
    goes wrong — never raises, never invents a finding."""
    src = axe_source()
    if src is None:
        return []
    try:
        page.evaluate(src)               # define window.axe
        results = page.evaluate(
            "async () => await axe.run(document, "
            "{resultTypes:['violations'], reporter:'v2'})")
        return findings_from_results(results or {}, route)
    except Exception:
        return []
