"""E-10 — photo editor Reset is confirmed, unsaved edits are guarded, reset is undoable.

Audit: edits exist only client-side until "Apply & save"; no beforeunload
guard (a mis-click on the "← Library" link above the canvas silently loses
work); "Reset" immediately POSTs and permanently clears the persisted recipe
and caches.

Fix (all in ``mediahub.web.photo_editor`` — a Flask-free body builder whose
JS is a plain string, so we assert on the source directly):

* a ``dirty`` flag tracks unsaved tweaks and arms a ``beforeunload`` prompt;
* Reset asks first, and distinguishes discarding client-side tweaks (saved
  edit kept) from deleting the saved edit (the POST);
* after a saved edit is deleted, a one-click "Undo reset" re-applies the
  previous recipe through the existing apply endpoint (which accepts a
  recipe payload — see ``api_photo_edit_apply``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web import photo_editor as pe  # noqa: E402

_JS = pe._JS


def _body():
    return pe.render_editor_body(
        asset_id="ma_x",
        asset_label="Eira Hughes",
        asset_type="athlete_action",
        asset_url="/file",
        edited_url="/edited",
        apply_url="/apply",
        preview_url="/preview",
        enhance_url="/enhance",
        reset_url="/reset",
        profile_pic_url="/profilepic",
        back_url="/library",
        width=1280,
        height=960,
    )


# --------------------------------------------------------------------------- #
# Unsaved-edit guard
# --------------------------------------------------------------------------- #


def test_dirty_flag_arms_beforeunload_guard():
    # Navigation with unsaved tweaks prompts; a clean page never does.
    assert "window.addEventListener('beforeunload'" in _JS
    assert "if(!dirty) return; ev.preventDefault(); ev.returnValue=''" in _JS


def test_every_edit_marks_dirty_and_save_clears_it():
    # All controls funnel through the debounced preview, so marking dirty
    # there covers sliders, filters, brush strokes, crop — everything.
    assert "function schedulePreview(){ markDirty();" in _JS
    # Apply & save is the only place work is persisted; it disarms the guard.
    assert "cfg.recipe=rec; dirty=false;" in _JS


# --------------------------------------------------------------------------- #
# Reset is confirmed and two-staged
# --------------------------------------------------------------------------- #


def test_reset_no_longer_posts_without_confirmation():
    # OLD: the click handler snapshotted and fetched cfg.resetUrl inline.
    assert "addEventListener('click',function(){ snapshot();\n    fetch(cfg.resetUrl" not in _JS
    # NEW: the click handler routes through the confirm box.
    handler = _JS.split("document.getElementById('pe-reset')")[1].split("});", 1)[0]
    assert "confirmBox(" in handler
    assert "fetch(" not in handler  # no direct POST from the click handler


def test_reset_distinguishes_discard_tweaks_from_delete_saved_edit():
    # Discarding client-side tweaks (saved edit kept) and deleting the saved
    # edit (the destructive POST) are separate, separately-worded confirms.
    assert "Discard your unsaved tweaks?" in _JS
    assert "Delete the saved edit?" in _JS
    assert "onConfirm:discardTweaks" in _JS
    assert "onConfirm:serverReset" in _JS
    # Only the server reset touches the reset endpoint.
    assert "fetch(cfg.resetUrl,{method:'POST'" in _JS


def test_confirm_uses_ui_kit_modal_with_native_fallback():
    assert "if(window.MH&&MH.confirm){ MH.confirm(opts); }" in _JS
    assert "window.confirm(" in _JS  # graceful fallback if ui-kit failed to load


def test_reset_with_nothing_to_reset_is_a_noop_message():
    assert "flash('Nothing to reset')" in _JS


# --------------------------------------------------------------------------- #
# Undo reset
# --------------------------------------------------------------------------- #


def test_undo_reset_button_ships_hidden():
    b = _body()
    assert '<button type="button" class="btn ghost" id="pe-undo-reset" hidden>Undo reset</button>' in b


def test_server_reset_keeps_previous_recipe_and_reveals_undo():
    assert "var previous=hasSavedEdit()?cfg.recipe:null;" in _JS
    assert "undoRecipe=previous;" in _JS
    # The button only appears after a reset that actually deleted a saved edit.
    assert "if(ur&&undoRecipe) ur.hidden=false;" in _JS
    assert "flash(undoRecipe?'Saved edit deleted':'Reset')" in _JS


def test_undo_reset_reapplies_recipe_via_apply_endpoint():
    # api_photo_edit_apply persists a posted recipe, so undo is a re-apply of
    # the recipe the reset threw away — no bespoke endpoint.
    handler = _JS.split("document.getElementById('pe-undo-reset').addEventListener")[1]
    assert "fetch(cfg.applyUrl,{method:'POST'" in handler
    assert "body:JSON.stringify(rec)" in handler
    assert "flash('Edit restored')" in handler


def test_new_edits_after_reset_retire_the_undo_offer():
    # Once the user starts editing again, silently re-applying the old recipe
    # would clobber their new work — markDirty clears the offer.
    assert "function markDirty(){ dirty=true;\n    undoRecipe=null;" in _JS
