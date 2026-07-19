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
from tests._helpers import web_surface_src

_SRC = web_surface_src()


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
    # The pack page's on-load restore consults the in-flight job first —
    # passing its finished-file restore as the stale-record fallback (JS-3).
    assert "mhResumeReelJob(reelUrl, mhRestoreFinishedReel)) return;" in _SRC
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
    # CON-6: the batch watcher now carries the same busy-recall attach idiom
    # as the single watches — forgetting on busy deleted the surviving job's
    # record when two tabs started batches simultaneously.
    for watcher in ("_mhReelWatch", "_mhReelBatchWatch", "_mhMotionWatch"):
        body = _fn(watcher)
        assert "j.error === 'renderer_busy'" in body, watcher
        assert "rec.poll_url !== pollUrl" in body, watcher


# ---------------------------------------------------------------------------
# Start/resume races (JS-4, JS-3)
# ---------------------------------------------------------------------------


def test_start_claims_the_panel_synchronously_before_the_202():
    """JS-4: the watching flag is set right after the guard passes — a
    double-click used to pass the guard twice while the first POST round-trip
    was still in flight, starting two jobs."""
    for starter in ("generateReel", "generateReelBatch", "generateMotion"):
        body = _fn(starter)
        assert "panel.dataset.mhWatching = '1';" in body, starter
        # The synchronous claim comes before any fetch leaves the function.
        assert body.index("panel.dataset.mhWatching = '1';") < body.index("fetch("), starter


def test_resume_paths_claim_and_release_the_panel():
    """JS-4: the on-load resume claims the panel before its async poll
    resolves, and releases it on every non-watching outcome."""
    for name in ("mhResumeReelJob", "mhResumeMotionJobs"):
        body = _fn(name)
        assert "panel.dataset.mhWatching = '1';" in body, name
        assert "delete panel.dataset.mhWatching;" in body, name


def test_stale_reel_record_falls_through_to_the_finished_restore():
    """JS-3: a stale/unreachable record is forgotten and the caller's
    finished-file restore runs — it no longer leaves a claimed, blank panel
    with the record stuck in localStorage forever."""
    assert "function mhResumeReelJob(reelUrl, onIdle)" in _SRC
    body = _fn("mhResumeReelJob")
    assert "mhJobForget(kind, reelUrl);" in body
    assert ".catch(idle);" in body
    assert "typeof onIdle === 'function'" in body
    # The pack page extracts the restore and runs it when nothing was claimed.
    assert "var mhRestoreFinishedReel = function()" in _SRC
    assert "mhRestoreFinishedReel();" in _SRC


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
