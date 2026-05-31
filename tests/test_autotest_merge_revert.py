"""MERGE hardening (council): post-merge auto-revert also fires on a SILENT
content regression (FIND baseline:regression) — but guarded so it never thrashes
main or reverts a merge that couldn't have caused it, and reports honestly when
the revert/push itself fails."""
from __future__ import annotations

from autotest import accept
from autotest.report import Finding


def _f(category, *, is_bug=True):
    return Finding(category=category, severity="high", title=f"{category} title", route="/r",
                   expected="e", actual="a", evidence="ev", is_bug=is_bug)


# --- _judge gate -----------------------------------------------------------
def test_judge_reverts_on_crash():
    v = accept._judge({"item_id": "X", "intent": "i"}, [_f("server_traceback")], {})
    assert v["passed"] is False and v.get("content_only") is False  # crash always reverts


def test_judge_reverts_on_content_regression():
    v = accept._judge({"item_id": "X"}, [_f("baseline:regression")], {})
    assert v["passed"] is False
    assert v.get("content_only") is True  # content-only -> needs the path filter


def test_judge_content_only_false_when_both():
    v = accept._judge({"item_id": "X"}, [_f("server_traceback"), _f("baseline:regression")], {})
    assert v["passed"] is False and v["content_only"] is False  # a crash present -> always revert


def test_judge_ignores_non_bug_baseline_drift():
    v = accept._judge({"item_id": "X"}, [_f("baseline:drift", is_bug=False)], {})
    assert v["passed"] is not False  # no regression -> not a forced fail


# --- content-path filter ---------------------------------------------------
def test_touches_content_true_for_product_code(monkeypatch):
    monkeypatch.setattr(accept, "_git", lambda *a: (0, "src/mediahub/pipeline_v4.py\nweb/web.py"))
    assert accept._touches_content("deadbeef") is True


def test_touches_content_false_for_docs_only(monkeypatch):
    monkeypatch.setattr(accept, "_git", lambda *a: (0, "README.md\ndocs/THEMING.md"))
    assert accept._touches_content("deadbeef") is False


def test_touches_content_false_for_tests_only(monkeypatch):
    monkeypatch.setattr(accept, "_git", lambda *a: (0, "tests/test_x.py"))
    assert accept._touches_content("deadbeef") is False


def test_touches_content_failsafe_true_when_unknown(monkeypatch):
    monkeypatch.setattr(accept, "_git", lambda *a: (0, ""))
    assert accept._touches_content("deadbeef") is True   # unknown -> fail safe (allow)
    assert accept._touches_content("") is True


def test_revert_cap_default_is_one():
    assert accept.REVERT_CAP == 1   # per-sweep cap -> never thrash


# --- revert honesty (council blind-spot: revert/push can fail) -------------
def _apply_env(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BUILD_MERGE", "1")
    monkeypatch.setenv("AUTOTEST_ACCEPT_APPLY", "1")
    monkeypatch.setattr("autotest.notify.notify", lambda *a, **k: None)


def _git_script(monkeypatch, revert_rc, push_rc):
    def g(*a):
        if a and a[0] == "log":
            return 0, "deadbeefcafe\n"
        if a and a[0] == "revert":
            return revert_rc, "conflict" if revert_rc else ""
        if a and a[0] == "push":
            return push_rc, "rejected" if push_rc else ""
        return 0, ""
    monkeypatch.setattr(accept, "_git", g)


def test_revert_failure_reported_honestly(monkeypatch):
    _apply_env(monkeypatch)
    _git_script(monkeypatch, revert_rc=1, push_rc=0)
    out = accept._auto_revert({"item_id": "X", "title": "t"})
    assert "FAILED" in out and not out.startswith("reverted")


def test_push_failure_reported_honestly(monkeypatch):
    _apply_env(monkeypatch)
    _git_script(monkeypatch, revert_rc=0, push_rc=1)
    out = accept._auto_revert({"item_id": "X", "title": "t"})
    assert "PUSH FAILED" in out and not out.startswith("reverted")


def test_successful_revert_returns_reverted(monkeypatch):
    _apply_env(monkeypatch)
    _git_script(monkeypatch, revert_rc=0, push_rc=0)
    out = accept._auto_revert({"item_id": "X", "title": "t"})
    assert out.startswith("reverted")


def test_content_only_skip_when_no_content_touched(monkeypatch):
    _apply_env(monkeypatch)
    def g(*a):
        if a and a[0] == "log":
            return 0, "deadbeef\n"
        if a and a[0] == "show":
            return 0, "README.md"
        return 0, ""
    monkeypatch.setattr(accept, "_git", g)
    out = accept._auto_revert({"item_id": "X", "title": "t"}, content_only=True)
    assert "skipped" in out and not out.startswith("reverted")
