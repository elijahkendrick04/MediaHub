"""Bot-upgrade behaviours (2026-06): the fixing→fixed reconcile, the deploy-grace
window, the judges-ran lifecycle freeze, the meta-finding partition, the asset-link
crawl fix, the clean-status merge fallthrough, judge evidence grounding, and the
coder/test-gate knobs.

These pin the failure modes observed in production CI on 2026-06-11:
  * GH006 rejected every report push to protected main → bot memory loss →
    the SAME finding fixed twice in one day (PRs #321 + #325);
  * `fixing` was a black hole (nothing ever set status="fixed");
  * `.woff2` links navigated with page.goto → "Download is starting" filed as
    HIGH navigation_error non-bugs that burned fixer ticks;
  * `gh pr merge --auto` refuses a PR whose checks already pass ("clean
    status") → fix PRs sat unmerged until a human intervened;
  * council precision measured at 0.06 — judges confirming unquoted claims.
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from autotest import fix_loop, gitops, report, run as autorun, semantic
from autotest.report import Finding


@pytest.fixture
def temp_ledger(tmp_path, monkeypatch):
    led = tmp_path / "ledger.json"
    led.write_text(json.dumps({"schema": report.SCHEMA_VERSION, "bugs": {}, "skipped": {}}))
    monkeypatch.setattr(report, "LEDGER_PATH", led)
    monkeypatch.setenv("AUTOTEST_CONFIRM_SWEEPS", "2")
    monkeypatch.setenv("AUTOTEST_DECAY_SWEEPS_SUBJECTIVE", "3")
    monkeypatch.setenv("AUTOTEST_DECAY_SWEEPS_DETERMINISTIC", "6")
    monkeypatch.setattr(report, "council_precision", lambda: None)
    fix_loop._JOURNAL.clear()
    return led


def _det(title="HTTP 500 at /x", route="/x"):
    return Finding(category="http_5xx", severity="high", title=title, route=route,
                   expected="2xx", actual="500", evidence="boom")


def _subj(title="confusing label", route="/dash"):
    return Finding(category="semantic:user_brain", severity="high", title=title,
                   route=route, expected="clear", actual="confusing")


def _entry(led, fp):
    return json.loads(led.read_text())["bugs"][fp]


def _seed(led, fp, **fields):
    data = json.loads(led.read_text())
    base = {"fingerprint": fp, "category": "http_5xx", "severity": "high",
            "title": "t", "route": "/x", "expected": "", "actual": "",
            "evidence": "", "suspect": "", "rationale": "", "repro": [],
            "screenshot": "", "status": "open", "first_seen": "2026-06-01T00:00:00+00:00",
            "last_seen": "2026-06-01T00:00:00+00:00", "seen_count": 1,
            "last_run_id": "r", "present_last_run": True, "fix_pr": None,
            "fix_branch": None, "confirmations": 0, "first_pending_run_id": None,
            "first_pending_at": None, "absent_streak": 0, "auto_closed_at": None}
    base.update(fields)
    data["bugs"][fp] = base
    led.write_text(json.dumps(data))
    return base


# --- deploy-grace window ------------------------------------------------------
def test_fixed_reseen_inside_grace_stays_fixed(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_DEPLOY_GRACE_HOURS", "24")
    f = _det()
    fp = f.fingerprint()
    _seed(temp_ledger, fp, status="fixed", fixed_at=report._now_iso(),
          fix_pr="https://x/pr/1", category=f.category, route=f.route)
    report.merge_findings([f], "run-2")
    e = _entry(temp_ledger, fp)
    assert e["status"] == "fixed", "a re-sighting during deploy lag is NOT a regression"
    assert e["reseen_during_grace"] is True
    assert e["fix_pr"] == "https://x/pr/1", "the surface stays claimed during grace"


def test_fixed_reseen_after_grace_regresses_and_releases_claim(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_DEPLOY_GRACE_HOURS", "24")
    f = _det()
    fp = f.fingerprint()
    _seed(temp_ledger, fp, status="fixed", fixed_at="2026-06-01T00:00:00+00:00",
          fix_pr="https://x/pr/1", fix_branch="autotest/fix-1",
          category=f.category, route=f.route)
    report.merge_findings([f], "run-2")
    e = _entry(temp_ledger, fp)
    assert e["status"] == "regressed"
    assert e["fix_pr"] is None and e["last_fix_pr"] == "https://x/pr/1", \
        "a real regression releases the in-flight claim so the fixer can retry"
    assert e["fix_branch"] is None and e["last_fix_branch"] == "autotest/fix-1"


def test_fixed_without_fixed_at_regresses_immediately(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_DEPLOY_GRACE_HOURS", "24")
    f = _det()
    fp = f.fingerprint()
    _seed(temp_ledger, fp, status="fixed", category=f.category, route=f.route)
    report.merge_findings([f], "run-2")
    assert _entry(temp_ledger, fp)["status"] == "regressed"


def test_grace_zero_disables_the_window(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_DEPLOY_GRACE_HOURS", "0")
    f = _det()
    fp = f.fingerprint()
    _seed(temp_ledger, fp, status="fixed", fixed_at=report._now_iso(),
          category=f.category, route=f.route)
    report.merge_findings([f], "run-2")
    assert _entry(temp_ledger, fp)["status"] == "regressed"


def test_mark_fixed_sets_status_and_anchor(temp_ledger):
    f = _det()
    fp = f.fingerprint()
    _seed(temp_ledger, fp, status="fixing", fix_pr="https://x/pr/9")
    assert report.mark_fixed(fp, merged_at="2026-06-11T12:00:00+00:00") is True
    e = _entry(temp_ledger, fp)
    assert e["status"] == "fixed" and e["fixed_at"] == "2026-06-11T12:00:00+00:00"
    assert report.mark_fixed("nope") is False


# --- judges-ran lifecycle freeze ------------------------------------------------
def test_subjective_clock_frozen_when_judges_did_not_run(temp_ledger):
    s = _subj()
    fp = s.fingerprint()
    _seed(temp_ledger, fp, status="open", category=s.category, route=s.route,
          absent_streak=2, present_last_run=True)
    report.merge_findings([], "run-2", judges_ran=False)
    e = _entry(temp_ledger, fp)
    assert e["absent_streak"] == 2 and e["status"] == "open"
    assert e["present_last_run"] is True, \
        "no judge looked — 'not reproduced' would be a false signal"


def test_subjective_decays_normally_when_judges_ran(temp_ledger):
    s = _subj()
    fp = s.fingerprint()
    _seed(temp_ledger, fp, status="open", category=s.category, route=s.route,
          absent_streak=2)
    report.merge_findings([], "run-2", judges_ran=True)
    e = _entry(temp_ledger, fp)
    assert e["absent_streak"] == 3 and e["status"] == "auto-closed"


def test_deterministic_decay_unaffected_by_judges_flag(temp_ledger):
    d = _det()
    fp = d.fingerprint()
    _seed(temp_ledger, fp, status="open", absent_streak=5)
    report.merge_findings([], "run-2", judges_ran=False)
    e = _entry(temp_ledger, fp)
    assert e["absent_streak"] == 6 and e["status"] == "auto-closed", \
        "the finder DID run — deterministic findings keep their decay clock"


# --- meta partition -------------------------------------------------------------
def test_meta_findings_partition_out_of_open_stats(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_CONFIRM_SWEEPS", "0")   # subjective opens immediately
    meta = Finding(category="council:blind_spot", severity="high",
                   title="Export path untested", route="export",
                   expected="covered", actual="uncovered")
    real = _det()
    stats = report.merge_findings([meta, real], "run-1")
    assert stats["open"] == 1, "the headline open count is product-actionable only"
    assert stats["meta_open"] == 1


def test_meta_findings_render_in_their_own_section(temp_ledger, monkeypatch):
    monkeypatch.setenv("AUTOTEST_CONFIRM_SWEEPS", "0")   # subjective opens immediately
    meta = Finding(category="council:blind_spot", severity="high",
                   title="ZZZ-meta-coverage-gap", route="export",
                   expected="covered", actual="uncovered")
    report.merge_findings([meta], "run-1")
    md = report.render_markdown({"run_id": "r"})
    gaps = md.index("Coverage gaps & harness notes")
    assert "ZZZ-meta-coverage-gap" in md[gaps:]
    open_section = md[md.index("## 🔴 Open bugs"):gaps]
    assert "ZZZ-meta-coverage-gap" not in open_section


def test_is_meta_entry_single_source_for_fixer_and_report():
    bug = {"category": "council:blind_spot", "route": "x", "title": "y"}
    assert report.is_meta_entry(bug) is True
    assert fix_loop._is_meta_finding(bug) is True
    bug2 = {"category": "semantic:output", "route": "/review", "title": "broken caption"}
    assert report.is_meta_entry(bug2) is False


# --- reconcile in-flight fixes ---------------------------------------------------
def test_reconcile_merged_pr_marks_fixed(temp_ledger, monkeypatch):
    _seed(temp_ledger, "aaa", status="fixing", fix_pr="https://x/pr/1")
    monkeypatch.setattr(gitops, "pr_state",
                        lambda ref: ("merged", "2026-06-11T10:00:00+00:00"))
    changes = fix_loop.reconcile_in_flight()
    e = _entry(temp_ledger, "aaa")
    assert e["status"] == "fixed" and e["fixed_at"] == "2026-06-11T10:00:00+00:00"
    assert changes and changes[0]["reconciled"] == "fixed"


def test_reconcile_closed_pr_reopens(temp_ledger, monkeypatch):
    _seed(temp_ledger, "bbb", status="fixing", fix_pr="https://x/pr/2")
    monkeypatch.setattr(gitops, "pr_state", lambda ref: ("closed", ""))
    fix_loop.reconcile_in_flight()
    e = _entry(temp_ledger, "bbb")
    assert e["status"] == "open" and e["fix_pr"] is None
    assert e["last_fix_pr"] == "https://x/pr/2"


def test_update_mirrors_into_state_snapshot(temp_ledger, tmp_path, monkeypatch):
    """A hard-killed fix pass must not lose its in-flight memory: _update writes
    through to the CI snapshot, which the workflow persists even on a crash."""
    import shutil as _shutil
    snap = tmp_path / "snap"
    snap.mkdir()
    _seed(temp_ledger, "ddd", status="open")
    _shutil.copy2(temp_ledger, snap / "ledger.json")
    monkeypatch.setenv("AUTOTEST_STATE_SNAPSHOT", str(snap))
    fix_loop._update("ddd", status="fixing", fix_pr="https://x/pr/5")
    snap_data = json.loads((snap / "ledger.json").read_text())
    assert snap_data["bugs"]["ddd"]["status"] == "fixing"
    assert snap_data["bugs"]["ddd"]["fix_pr"] == "https://x/pr/5"


def test_reconcile_open_or_unknown_pr_left_alone(temp_ledger, monkeypatch):
    _seed(temp_ledger, "ccc", status="fixing", fix_pr="https://x/pr/3")
    monkeypatch.setattr(gitops, "pr_state", lambda ref: ("open", ""))
    assert fix_loop.reconcile_in_flight() == []
    assert _entry(temp_ledger, "ccc")["status"] == "fixing"
    monkeypatch.setattr(gitops, "pr_state", lambda ref: ("unknown", ""))
    assert fix_loop.reconcile_in_flight() == []
    assert _entry(temp_ledger, "ccc")["status"] == "fixing"


# --- asset links: request-checked, never page.goto -------------------------------
def test_asset_urls_recognised():
    assert autorun._is_asset_url("https://x/static/fonts/a.woff2")
    # query strings don't fool it: the PATH decides
    assert autorun._is_asset_url("https://x/files/results.pdf?dl=1")
    assert autorun._is_asset_url("https://x/files/results.pdf")
    assert not autorun._is_asset_url("https://x/review/abc")
    assert not autorun._is_asset_url("https://x/")


def _bare_tester():
    t = object.__new__(autorun.Tester)
    t.findings = []
    t.engine = "chromium"
    return t


def test_check_asset_files_deterministic_finding_on_404():
    t = _bare_tester()
    t.page = SimpleNamespace(request=SimpleNamespace(
        get=lambda url, timeout: SimpleNamespace(status=404)))
    t._check_asset("https://x/static/f.woff2", "/static/f.woff2")
    assert len(t.findings) == 1
    f = t.findings[0]
    assert f.category == "network_error" and f.severity == "medium"
    assert "404" in f.title


def test_check_asset_quiet_on_success():
    t = _bare_tester()
    t.page = SimpleNamespace(request=SimpleNamespace(
        get=lambda url, timeout: SimpleNamespace(status=200)))
    t._check_asset("https://x/static/f.woff2", "/static/f.woff2")
    assert t.findings == [], "a font that serves fine is not a finding"


def test_crawl_never_navigates_an_asset(monkeypatch):
    t = _bare_tester()
    t.pages_crawled, t.max_pages = 0, 10
    navigated, checked = [], []
    monkeypatch.setattr(autorun.Tester, "probe",
                        lambda self, url, label, **kw: navigated.append(url) or (200, "", []))
    monkeypatch.setattr(autorun.Tester, "_check_asset",
                        lambda self, url, route: checked.append(url))
    t.crawl(["https://x/page", "https://x/static/f.woff2"])
    assert "https://x/static/f.woff2" in checked
    assert "https://x/static/f.woff2" not in navigated


# --- clean-status merge fallthrough ----------------------------------------------
def test_merge_to_main_falls_through_to_direct_merge(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/gh")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "--auto" in cmd:
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr="GraphQL: Pull request Pull request is in "
                                          "clean status (enablePullRequestAutoMerge)")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gitops.subprocess, "run", fake_run)
    msg = gitops._merge_to_main("b", has_pr=True, files=["src/mediahub/web/web.py"])
    assert "merged directly" in msg
    assert any("--auto" in c for c in calls) and any("--auto" not in c for c in calls)


def test_merge_to_main_reports_other_failures_honestly(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/gh")
    monkeypatch.setattr(gitops.subprocess, "run",
                        lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="",
                                                          stderr="HTTP 502 from GitHub"))
    msg = gitops._merge_to_main("b", has_pr=True, files=["src/mediahub/web/web.py"])
    assert "auto-merge NOT armed" in msg and "502" in msg


# --- judge evidence grounding -----------------------------------------------------
def test_evidence_grounded_accepts_verbatim_quote():
    material = "## home_text\nWelcome to Autotest Aquatics Club — review 3 cards now"
    assert semantic.evidence_grounded(
        "the page says 'Welcome to Autotest Aquatics Club — review 3 cards'", material)


def test_evidence_grounded_rejects_fabrication():
    material = "## home_text\nWelcome to Autotest Aquatics Club"
    assert not semantic.evidence_grounded(
        "the export button returned an empty ZIP archive for every meet", material)


def test_evidence_grounded_short_evidence_substring():
    assert semantic.evidence_grounded("3 cards", "produced 3 cards today")
    assert not semantic.evidence_grounded("9 reels", "produced 3 cards today")


# --- volatile normaliser ------------------------------------------------------------
def test_normalise_volatile_keeps_numbers_strips_timestamps():
    a = report.normalise_volatile("cards=3 at 2026-06-11T10:00:00+00:00 run 4fe01d0e3bb7")
    b = report.normalise_volatile("cards=3 at 2026-06-12T22:33:44+00:00 run 8ec8f4aa37fe")
    assert a == b and "cards=3" in a
    assert (report.normalise_volatile("cards=3 ...")
            != report.normalise_volatile("cards=4 ..."))


def test_judge_digest_roundtrip(temp_ledger):
    report.set_judge_inputs_digest("abc123")
    assert report.get_judge_inputs_digest() == "abc123"


# --- knobs ---------------------------------------------------------------------------
def test_test_gate_uses_xdist_when_enabled(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(gitops.subprocess, "run", fake_run)
    monkeypatch.setenv("AUTOTEST_GATE_XDIST", "1")
    gitops._test_gate()
    assert "-n" in captured["cmd"] and "auto" in captured["cmd"]
    monkeypatch.delenv("AUTOTEST_GATE_XDIST")
    gitops._test_gate()
    assert "-n" not in captured["cmd"], "serial by default — opt-in only"


def test_claude_coder_model_knob(monkeypatch):
    from autotest import coder
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(coder.shutil, "which", lambda x: "/usr/bin/claude")
    monkeypatch.setattr(coder.subprocess, "run", fake_run)
    monkeypatch.setenv("AUTOTEST_CODER", "claude")
    monkeypatch.setenv("AUTOTEST_CODER_MODEL_CLAUDE", "opus")
    coder.run_coder("task")
    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opus"
    monkeypatch.delenv("AUTOTEST_CODER_MODEL_CLAUDE")
    coder.run_coder("task")
    assert "--model" not in captured["cmd"], "no pin → the CLI/subscription default"


# --- fix prompt context ----------------------------------------------------------------
def test_fix_prompt_carries_regression_and_deploy_context():
    bug = {"fingerprint": "f", "category": "http_5xx", "severity": "high",
           "title": "t", "route": "/x", "expected": "e", "actual": "a",
           "status": "regressed", "last_fix_pr": "https://x/pr/7",
           "rationale": "council says so", "screenshot": "autotest/screenshots/s.png",
           "engine": "webkit"}
    p = fix_loop._fix_prompt(bug)
    assert "DEPLOY LAG CHECK" in p
    assert "https://x/pr/7" in p and "RE-APPEARED" in p
    assert "council says so" in p
    assert "autotest/screenshots/s.png" in p
    assert "webkit" in p
