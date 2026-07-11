"""J-2 — Video Studio fetch handlers must not swallow failures or use alert().

If a render/clip/AI-reel request failed at the network level (the likely outcome
of the studio's long synchronous endpoints), the promise rejected with no
handler: the Render button stayed disabled on "Rendering..." forever and
"Analysing footage…" never cleared. Server errors surfaced via window.alert().
Every studio fetch chain now has a .catch that re-enables its button and writes a
styled inline message / MH.toast; the error alert()s are gone.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def _studio_js() -> str:
    # The Video Studio JS block only — from its template to the next template
    # (_VISUAL_PANEL_JS), so unrelated JS elsewhere in web.py isn't scanned.
    start = _SRC.index("_VIDEO_STUDIO_HTML")
    end = _SRC.index("_VISUAL_PANEL_JS")
    return _SRC[start:end]


def test_shared_error_toast_helper_exists():
    js = _studio_js()
    assert "function vsToast(m)" in js
    assert "MH.toast(m, 'error')" in js


def test_render_and_clip_and_reel_have_catch_handlers():
    js = _studio_js()
    # renderProject now runs as a background job (J-1) via the shared runVideoJob
    # helper; its failure path re-enables the button (restore) and surfaces the
    # error via vsToast + an inline panel instead of sticking on "Rendering...".
    assert "function runVideoJob(" in js
    assert "Network error: " in js  # the outer job-POST .catch
    assert "btn.disabled=false" in js  # restore() re-enables the render button
    # make-clip and reel-direct now also run as polled background jobs (J-1)
    # through the same runVideoJob helper, so their failures re-enable the button
    # and surface a styled error rather than sticking on "Analysing..."/leaving a
    # stuck status line. Each carries its own error label.
    assert "CLIPMAKER_URL + '-job'" in js
    assert "REEL_URL + '-job'" in js
    assert "errLabel: 'Clip error'" in js
    assert "errLabel: 'Reel error'" in js


def test_save_timeline_has_catch_handler():
    """The editor's Save handler used to have no .catch, so a network failure left
    it stuck on 'Saving...' forever — the same class the other studio fetches fixed.
    """
    js = _studio_js()
    assert "The timeline may not have saved" in js


def test_make_clip_button_guards_double_submit():
    """A double-click on 'Make clip' must not create duplicate projects. Analysis
    runs through the shared ``runVideoJob`` runner, which disables the triggering
    button for the whole polled run and only restores it once the job settles — so
    a second click can't fire a second clip-maker request.
    """
    js = _studio_js()
    assert "runVideoJob(btn, CLIPMAKER_URL + '-job'" in js  # wired through the guarded runner
    assert "function runVideoJob(btn, jobUrl, body, panel, opts, onDone)" in js
    assert "btn.disabled = true" in js  # disabled for the whole run
    assert "if(btn){ btn.disabled=false;" in js  # restored only on settle


def test_no_error_alert_in_studio():
    js = _studio_js()
    # The three named error alert()s (permission change, render, load-clip) are gone.
    assert "alert(j.message)" not in js
    assert "alert('Could not load this clip.')" not in js
    assert "alert(j.message || j.error || 'Could not change the permission.')" not in js
    # The permission-change error now routes through the styled toast instead.
    assert "vsToast(j.message || j.error || 'Could not change the permission.')" in js
    # No bare alert() error dialogs remain in the studio (the only dialog is the
    # deliberate window.confirm approve-for-export gate).
    assert "alert(" not in js


# --- accessibility caveats (F-08..F-11) -----------------------------------


def test_editor_modal_has_focus_management():
    """F-08: the timeline editor modal must trap focus, close on Escape, restore
    focus to the trigger, and expose itself to AT as a labelled modal dialog.
    """
    js = _studio_js()
    assert 'aria-modal="true"' in js and 'aria-labelledby="vs-ed-title"' in js
    assert "function showEditor()" in js and "function closeEditor()" in js
    assert "editorPrevFocus = document.activeElement" in js  # remember trigger
    assert "if(editorPrevFocus && editorPrevFocus.focus){ editorPrevFocus.focus(); }" in js
    assert "e.key === 'Escape'" in js  # Escape closes
    assert "e.key === 'Tab'" in js  # Tab is trapped within the dialog
    # Backdrop click closes, and the modal is opened via the a11y helper.
    assert "if(e.target === this){ closeEditor(); }" in js
    assert "showEditor();" in js


def test_reel_brief_has_accessible_label():
    """F-09: the reel brief input was labelled by placeholder only."""
    js = _studio_js()
    assert 'aria-label="What this reel is about' in js


def test_reel_has_independent_format_control():
    """F-11: the reel used to read the Clip-Maker's format select (hidden unless a
    clip was selected). It now has its own format control.
    """
    js = _studio_js()
    assert 'id="vs-reel-format"' in js
    assert "format: $('vs-reel-format').value" in js  # the reel submit reads its own select


def test_editor_inputs_and_icon_buttons_have_accessible_names():
    """F-10: the editor's trim/speed number inputs and glyph-only icon buttons were
    named by adjacent text / a title only — add explicit accessible names.
    """
    js = _studio_js()
    assert "aria-label=\"Clip '+cn+' trim start (ms)\"" in js
    assert "aria-label=\"Clip '+cn+' trim end (ms)\"" in js
    assert "aria-label=\"Clip '+cn+' playback speed\"" in js
    assert "aria-label=\"Move clip '+cn+' up\"" in js
    assert "aria-label=\"Remove clip '+cn+'\"" in js
    assert "aria-label=\"Caption line '+(i+1)+' text\"" in js


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.media_library import store as _mlstore

    _mlstore._default_store = _mlstore.MediaLibraryStore(
        db_path=tmp_path / "media.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "alpha"
    return c, wm


def test_studio_page_renders_error_handling(client):
    c, wm = client
    if not wm._v8_ok:
        pytest.skip("V8 media engine not enabled in this environment")
    html = c.get("/video").get_data(as_text=True)
    assert "function vsToast(m)" in html
    # J-1: the render error handling now lives in the background-job helper.
    assert "function runVideoJob(" in html
