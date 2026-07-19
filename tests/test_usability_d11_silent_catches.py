"""D-11 — empty fetch ``.catch`` handlers swallowed failures app-wide.

Deleting or reacting to a comment, restoring a version, toggling a lock,
picking a variant, saving a copilot preference, marking notifications read and
creating/deleting a collection all failed silently on a network error — the
named offenders being ``commentsMutate`` and ``commentsReact`` (delete/react
failed silently while comment-send surfaced "Network error") and the photo
editor's one-click Enhance (both its error-JSON branch and its network catch
were silent).

Every user-initiated mutation now surfaces its failure through the surface's
existing mechanism (``.cm-status`` inline element, ``MH.toast``, the photo
editor's ``flash``), and the user-initiated panel loads that previously left a
stuck "Loading…" (or an indistinguishable blank) report honestly too.

Genuine fire-and-forget paths (status pollers, explainability-manifest
sidecars, prefetches, resume-on-load checks, the service worker's sync
registration) stay deliberately silent; the count assertions keep new silent
catches from creeping back in.
"""

from __future__ import annotations

import pathlib
import re
from tests._helpers import web_surface_src

_SRC = web_surface_src()
_PE = pathlib.Path("src/mediahub/web/photo_editor.py").read_text(encoding="utf-8")

_EMPTY_CATCH = ".catch(function(){})"


def _fn(name: str) -> str:
    """Slice a top-level ``function <name>(...)`` body out of the review JS."""
    start = _SRC.index("function " + name + "(")
    nxt = _SRC.index("\nfunction ", start)
    return _SRC[start:nxt]


# ---- the named offenders --------------------------------------------------


def test_comments_mutate_reports_failure():
    body = _fn("commentsMutate")
    assert _EMPTY_CATCH not in body
    # Error-JSON branch mirrors commentsSend's status-element pattern...
    assert "Could not update the comment" in body
    # ...and the network catch is no longer silent.
    assert "status.textContent='Network error'" in body


def test_comments_react_reports_failure():
    body = _fn("commentsReact")
    assert _EMPTY_CATCH not in body
    assert "Could not add the reaction" in body
    assert "status.textContent='Network error'" in body


def test_photo_editor_enhance_reports_failure():
    # The Enhance click handler: error-JSON branch and network catch both
    # surface via the page's flash() status mechanism.
    start = _PE.index("pe-enhance').addEventListener")
    body = _PE[start : _PE.index("});", _PE.index(".catch", start)) + 3]
    assert _EMPTY_CATCH not in body
    assert "flash('Enhance failed — try again')" in body
    assert "flash('Enhance failed — check your connection')" in body


# ---- the rest of the user-initiated mutations -----------------------------


def test_pick_variant_persist_reports_failure():
    body = _fn("pickVariant")
    assert _EMPTY_CATCH not in body
    assert "Could not save your pick" in body


def test_copilot_remember_reports_failure():
    body = _fn("copilotRemember")
    assert _EMPTY_CATCH not in body
    assert "Could not save the preference — check your connection." in body


def test_history_restore_reports_failure():
    body = _fn("historyRestore")
    assert _EMPTY_CATCH not in body
    assert "Could not restore — check your connection." in body


def test_locks_set_reports_failure():
    body = _fn("locksSet")
    assert _EMPTY_CATCH not in body
    assert "Could not change the lock — check your connection." in body


def test_notifications_mark_all_read_reports_failure():
    assert "Could not mark notifications read — check your connection." in _SRC


def test_collections_create_and_delete_report_failure():
    # Create: the network catch toasts instead of dying silently.
    assert "the collection was not created." in _SRC
    # Delete: no longer a blind location.reload() with a silent catch.
    assert (
        ".then(function(r){return r.json();}).then(function(){location.reload();})"
        ".catch(function(){});};" not in _SRC
    )
    assert "the collection was not deleted." in _SRC


# ---- user-initiated panel loads (stuck "Loading…" / blank-means-broken) ---


def test_panel_loads_report_failure():
    for name, marker in [
        ("commentsLoad", "Could not load comments — check your connection."),
        ("historyLoad", "Could not load version history — check your connection."),
        ("historyDiff", "Could not load the diff — check your connection."),
        ("locksLoad", "Could not load the locks — check your connection."),
    ]:
        body = _fn(name)
        assert _EMPTY_CATCH not in body, name
        assert marker in body, name


def test_reel_comments_refresh_reports_failure():
    assert "showErr('Could not load comments — check your connection.')" in _SRC


# ---- the intentionally-silent allowlist -----------------------------------

# Every remaining empty catch is a genuine fire-and-forget path. Each entry is
# a source fragment that must appear on the same line as the silent catch.
_ALLOWED_CONTEXTS = [
    "requestFullscreen().catch(function(){});",  # browser gesture policy
    "self.registration.sync.register(SYNC_TAG).catch(function(){});",  # SW sync
]


def test_no_new_silent_catches_in_web():
    # 10 deliberate fire-and-forget silents remain: 2 resume-on-load job
    # checks, 2 explainability-manifest sidecars, the self-healing LLM status
    # poll, the copilot suggestion prefetch, the pre-navigation notification
    # mark-read, the reactions load reconcile, the fullscreen request and the
    # service worker's sync registration. Anything above that is a regression.
    assert _SRC.count(_EMPTY_CATCH) <= 10
    for frag in _ALLOWED_CONTEXTS:
        assert frag in _SRC


def test_no_new_silent_catches_in_photo_editor():
    # Only the debounced live-preview loop stays silent (it self-heals on the
    # next slider tick and its busy flag is cleared by the trailing .then).
    assert _PE.count(_EMPTY_CATCH) == 1
    ctx = _PE[_PE.index(_EMPTY_CATCH) - 400 : _PE.index(_EMPTY_CATCH)]
    assert "previewUrl" in ctx


def test_no_empty_arrow_catches_appear():
    # The audit found only function(){} forms; keep the arrow variants out too.
    assert not re.search(r"\.catch\(\(\s*[a-zA-Z_]*\s*\)?\s*=>\s*\{\s*\}\)", _SRC)
    assert not re.search(r"\.catch\(function\([a-zA-Z_]+\)\s*\{\s*\}\)", _SRC)
