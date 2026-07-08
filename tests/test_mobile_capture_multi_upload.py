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
