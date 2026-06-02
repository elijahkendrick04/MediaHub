"""B2 (Tier B): accessibility findings from axe-core results are DETERMINISTIC.

Tests the pure result→Finding mapping and the honest-skip behaviour (no axe source
→ no findings, never a crash) — no browser needed. The category is ``a11y`` (not
subjective), so report.is_subjective is False → these open immediately, bypassing
the A1 confirm gate.
"""
from __future__ import annotations

from autotest import a11y, report


_SAMPLE = {
    "violations": [
        {"id": "color-contrast", "impact": "serious", "help": "Elements must have sufficient colour contrast",
         "helpUrl": "https://dequeuniversity.com/rules/axe/color-contrast",
         "nodes": [{"target": [".cta"]}, {"target": ["h1"]}]},
        {"id": "image-alt", "impact": "critical", "help": "Images must have alternate text",
         "nodes": [{"target": ["img.logo"]}]},
        {"id": "landmark-one-main", "impact": "moderate", "help": "Document should have one main landmark",
         "nodes": [{"target": ["body"]}]},
        {"id": "region", "impact": None, "help": "All content should be in a landmark",
         "nodes": [{"target": ["div"]}]},
    ]
}


def test_impact_maps_to_severity():
    assert a11y._impact_severity("critical") == "high"
    assert a11y._impact_severity("serious") == "high"
    assert a11y._impact_severity("moderate") == "medium"
    assert a11y._impact_severity("minor") == "low"
    assert a11y._impact_severity(None) == "low"
    assert a11y._impact_severity("weird") == "low"


def test_findings_from_results_one_per_violation():
    fs = a11y.findings_from_results(_SAMPLE, "/review")
    assert len(fs) == 4
    by_rule = {f.suspect: f for f in fs}
    assert by_rule["axe:color-contrast"].severity == "high"
    assert by_rule["axe:image-alt"].severity == "high"
    assert by_rule["axe:landmark-one-main"].severity == "medium"
    assert by_rule["axe:region"].severity == "low"
    assert all(f.category == "a11y" for f in fs)
    assert all(f.route == "/review" for f in fs)


def test_a11y_findings_are_deterministic_not_subjective():
    f = a11y.findings_from_results(_SAMPLE, "/")[0]
    assert report.is_subjective(f.category) is False   # opens immediately, no confirm gate


def test_fingerprint_stable_per_route_and_rule():
    a = a11y.findings_from_results(_SAMPLE, "/review")[0]
    # Same rule + route, but a different node set next run → same fingerprint (stable
    # suspect axe:<rule>), so it dedupes instead of exploding.
    alt = a11y.findings_from_results(
        {"violations": [{"id": "color-contrast", "impact": "serious", "help": "x",
                         "nodes": [{"target": [".different"]}, {"target": [".more"]}]}]}, "/review")[0]
    assert a.fingerprint() == alt.fingerprint()
    # Different route → distinct.
    other = a11y.findings_from_results(_SAMPLE, "/settings")[0]
    assert a.fingerprint() != other.fingerprint()


def test_empty_results_no_findings():
    assert a11y.findings_from_results({}, "/") == []
    assert a11y.findings_from_results({"violations": []}, "/") == []


def test_run_honest_skips_without_axe_source(monkeypatch):
    # No axe source → run() returns [] and never touches the (here, None) page.
    monkeypatch.setattr(a11y, "axe_source", lambda: None)
    assert a11y.run(page=None, route="/") == []


def test_available_respects_flag(monkeypatch):
    monkeypatch.setattr(a11y, "axe_source", lambda: "window.axe={}")
    monkeypatch.setenv("AUTOTEST_A11Y", "1")
    assert a11y.available() is True
    monkeypatch.setenv("AUTOTEST_A11Y", "0")
    assert a11y.available() is False
