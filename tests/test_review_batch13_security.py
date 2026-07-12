"""Regression tests for deep-review batch 13 (security defence-in-depth).

#28 Uploaded images are rejected above a pixel budget (decompression-bomb
    guard) — asserted here via the module constant; the decode path itself is
    exercised by the media-library upload suite.
#31 Filename components interpolated into Content-Disposition headers are
    sanitised (defence-in-depth against header/quote injection).

Deferred with rationale (documented in the batch PR): #26 (committed default
operator credential) and #29 (public /healthz detail) both tension with
ADR-0018's deliberate passwordless one-click operator sign-in; #27 (cross-worker
rate-limit store) is a larger standalone SQLite change.
"""

from __future__ import annotations


def test_safe_disposition_token_sanitises():
    from mediahub.web.web import _safe_disposition_token

    assert _safe_disposition_token("abc123") == "abc123"
    assert _safe_disposition_token("a.b-c_d") == "a.b-c_d"  # dot/dash/underscore kept
    assert _safe_disposition_token("a/b/../c") == "a_b_.._c"  # separators neutralised
    # Quotes, semicolons, spaces and CR/LF (header-injection vectors) all go.
    dirty = _safe_disposition_token('x"; y\r\nContent-Length: 0')
    assert '"' not in dirty and ";" not in dirty and "\r" not in dirty and "\n" not in dirty
    assert _safe_disposition_token("") == "download"
    assert _safe_disposition_token(None) == "download"


def test_max_upload_image_pixels_is_sane():
    from mediahub.web.web import _MAX_UPLOAD_IMAGE_PIXELS

    # Comfortably above a 4K/8K photo but well below a decompression bomb.
    assert 20_000_000 <= _MAX_UPLOAD_IMAGE_PIXELS <= 100_000_000
