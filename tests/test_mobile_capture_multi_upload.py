"""tests/test_mobile_capture_multi_upload.py — the mobile-capture enhancement
uploads every selected photo, not just the first (audit finding H-1).

The media-library form is `multiple` and the copy invites picking a batch, but
the client enhancement intercepted the submit and uploaded only
``fileInput.files[0]`` — so a volunteer choosing 30 gala photos got 1 uploaded
and 29 silently dropped, under a banner that read "1 photo added".

There is no JS unit harness in this repo, so this is a source-level guard (the
same shape as the existing test that asserts the script is referenced): the
multi-file path must exist and the batch must redirect with the REAL saved
count, not a hard-coded 1.
"""
from __future__ import annotations

from pathlib import Path

_JS = (
    Path(__file__).resolve().parents[1]
    / "src" / "mediahub" / "web" / "static" / "js" / "mobile-capture.js"
)


def test_script_present():
    assert _JS.is_file()


def test_uploads_all_selected_files():
    src = _JS.read_text(encoding="utf-8")
    # A dedicated multi-file uploader exists...
    assert "processAndUploadAll" in src
    # ...the submit handler routes a multi-select into it...
    assert "fileInput.files.length > 1" in src
    # ...and the batch redirect carries the real saved count, never a fixed 1.
    assert '"?shared=" + saved' in src


def test_single_submit_no_longer_hardwires_only_first_file():
    """The submit handler must not upload only files[0] for every submit."""
    src = _JS.read_text(encoding="utf-8")
    handler = src[src.index('form.addEventListener("submit"'):]
    handler = handler[: handler.index("});") + 3]
    # The multi-select branch must be present in the submit handler itself.
    assert "processAndUploadAll(fileInput.files)" in handler


def test_camera_fallback_carries_the_captured_photo():
    """The native fallback must not lose a camera capture.

    ``nativeFallback()`` used to call ``form.submit()`` with the photo still
    stuck in the hidden, NAMELESS ``#ml-capture`` input — so a failed AJAX
    upload fell back to a multipart POST carrying no file at all, the server
    answered ``{"error":"no_file"}`` and the capture was gone. The fallback
    must give the capture input a form name (only when the named input is
    empty, so the form-submit path never double-posts) BEFORE submitting.
    """
    src = _JS.read_text(encoding="utf-8")
    fn = src[src.index("function nativeFallback") : src.index("function processAndUpload")]
    # The capture input is named just-in-time so the native POST carries it...
    assert "captureInput.name" in fn, "fallback must name the capture input"
    # ...before the submit statement fires (";" pins the call, not a comment)...
    assert fn.index("captureInput.name") < fn.index("form.submit();")
    # ...and only when a capture is pending and the named input is empty.
    assert "captureInput.files" in fn
    assert "fileInput.files" in fn
