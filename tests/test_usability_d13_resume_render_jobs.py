"""D-13 — an in-flight reel/motion render must survive navigation.

Jobs already survived server-side (disk-backed store + heartbeat up to the
600s render budget), but the client forgot them: the pack page re-attached
only to FINISHED files on load, a second click errored "Another video is
rendering right now", and the poll loops gave up at 4-6 minutes while the
server kept the job alive.

Now the shared client JS:

* remembers the active job ({poll_url, fmt, …}) per (kind, url) in
  localStorage when a job starts (kinds: reel / reel-batch / motion);
* on page load re-attaches to a still-running job (mhResumeReelJob /
  mhResumeMotionJobs) and renders the video if it finished while away;
* on a repeat click resumes the stored running job instead of starting a
  doomed duplicate, and a renderer_busy error mid-poll re-attaches to the
  stored job rather than surfacing the error;
* clears the stored record on every terminal state;
* polls up to 200 × 3s = 600s, matching the server's render budget.

Source-level guards (the j2/g13 idiom) — this is JS inside the web.py
template strings.
"""

from __future__ import annotations

import pathlib
import re

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """The source slice of one top-level JS function (brace-matched)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\) \{{", _SRC)
    assert m, f"function {name} not found"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[m.start() : j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


# ---------------------------------------------------------------------------
# Persistence: jobs are remembered per (kind, url) in localStorage
# ---------------------------------------------------------------------------


def test_job_store_helpers_exist_and_use_localstorage():
    assert "function mhJobRemember(" in _SRC
    assert "function mhJobRecall(" in _SRC
    assert "function mhJobForget(" in _SRC
    assert "'mh-job:' + kind + ':' + url" in _SRC
    assert "localStorage.setItem(" in _SRC
    assert "localStorage.removeItem(" in _SRC


def test_each_kind_is_remembered_on_job_start():
    assert "mhJobRemember('reel', reelUrl" in _fn("generateReel")
    assert "mhJobRemember('reel-batch', reelUrl" in _fn("generateReelBatch")
    assert "mhJobRemember('motion', motionUrl" in _fn("generateMotion")


def test_terminal_states_forget_the_record():
    for watcher, kind in (
        ("_mhReelWatch", "'reel'"),
        ("_mhReelBatchWatch", "'reel-batch'"),
        ("_mhMotionWatch", "'motion'"),
    ):
        body = _fn(watcher)
        # done + error + timeout all clear the stored job.
        assert body.count(f"mhJobForget({kind},") >= 2, watcher


# ---------------------------------------------------------------------------
# Resume: on load, and instead of a renderer-busy duplicate
# ---------------------------------------------------------------------------


def test_page_load_resume_hooks_exist():
    assert "function mhResumeReelJob(" in _SRC
    assert "function mhResumeMotionJobs(" in _SRC
    # The pack page's on-load restore consults the in-flight job first.
    assert "mhResumeReelJob(reelUrl)) return;" in _SRC
    # The motion resume auto-runs on every page carrying the shared block.
    assert "document.addEventListener('DOMContentLoaded', mhResumeMotionJobs)" in _SRC


def test_resume_renders_video_finished_while_away():
    body = _fn("mhResumeReelJob")
    assert "mhRenderReel(panel, reelUrl" in body
    assert "mhRenderReelBatch(panel, reelUrl" in body
    body = _fn("mhResumeMotionJobs")
    assert "mhRenderMotion(panel, motionUrl" in body


def test_click_resumes_running_job_instead_of_restarting():
    for starter in ("generateReel", "generateReelBatch", "generateMotion"):
        body = _fn(starter)
        assert "mhJobRecall(" in body, starter
        assert "j.status === 'running'" in body, starter


def test_renderer_busy_repolls_stored_job_not_error():
    for watcher in ("_mhReelWatch", "_mhMotionWatch"):
        body = _fn(watcher)
        assert "j.error === 'renderer_busy'" in body, watcher
        assert "rec.poll_url !== pollUrl" in body, watcher


# ---------------------------------------------------------------------------
# Poll budget matches the server's 600s render budget
# ---------------------------------------------------------------------------


def test_poll_caps_extended_to_600s():
    for watcher in ("_mhReelWatch", "_mhReelBatchWatch", "_mhMotionWatch"):
        assert "tries > 200" in _fn(watcher), watcher
    # The old premature caps are gone from the shared reel/motion path.
    for starter in ("generateReel", "generateReelBatch", "generateMotion"):
        body = _fn(starter)
        assert "tries > 80" not in body, starter
        assert "tries > 120" not in body, starter
