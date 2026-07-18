"""tests/test_brand_guidelines_binary_guard.py — Phase 1.5 screenshot-leak fix.

The user reported: "AI captions returned the uploaded screenshots."

Root cause was binary content (PNG, JPG) being uploaded as the
brand-guidelines file. The old extract path fell through to a
plaintext UTF-8 decode of the binary bytes, with a too-permissive 5%
replacement-char threshold, so noisy garbage ended up in
``prof.brand_guidelines["summary"]`` and then in every subsequent
caption prompt via ``brand_context_for_llm``.

This test pins:
  * `_dispatch_extract` returns empty for image extensions.
  * `_dispatch_extract` returns empty for known binary magic bytes
    even when the extension is unknown.
  * The web route surfaces a friendly "unsupported_binary" status
    instead of silently storing garbage.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


class TestDispatchExtractBinaryGuard:
    """The internal _dispatch_extract takes (ext, data) — extension
    only, not full filename. The public extract_text() does the split."""

    def test_png_extension_returns_empty_not_decoded_garbage(self):
        from mediahub.brand.guidelines import _dispatch_extract

        png_like = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"\x00" * 30 + b"some words"
        assert _dispatch_extract("png", png_like) == ""

    def test_jpg_extension_returns_empty(self):
        from mediahub.brand.guidelines import _dispatch_extract

        jpg_like = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 50
        assert _dispatch_extract("jpg", jpg_like) == ""

    def test_unknown_ext_but_png_magic_returns_empty(self):
        """Defence in depth — an attacker renames foo.png to foo.gdoc;
        the magic-byte check must still reject even when ext is unknown."""
        from mediahub.brand.guidelines import _dispatch_extract

        png_like = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"\x00" * 30
        assert _dispatch_extract("gdoc", png_like) == ""

    def test_genuine_text_passes_through(self):
        from mediahub.brand.guidelines import _dispatch_extract

        body = "Brand Guidelines\n\nUse warm, friendly language. " * 5
        result = _dispatch_extract("txt", body.encode("utf-8"))
        assert "Brand Guidelines" in result

    def test_markdown_passes_through(self):
        from mediahub.brand.guidelines import _dispatch_extract

        body = "# Brand voice\n\nWarm. Friendly. Specific."
        result = _dispatch_extract("md", body.encode("utf-8"))
        assert "Brand voice" in result

    def test_mp4_extension_rejected(self):
        from mediahub.brand.guidelines import _dispatch_extract

        mp4_like = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
        assert _dispatch_extract("mp4", mp4_like) == ""

    def test_extract_text_public_api_rejects_png_by_filename(self):
        """The public extract_text() splits filename → ext and routes
        to _dispatch_extract. End-to-end PNG must produce no usable text."""
        from mediahub.brand.guidelines import extract_text

        png_like = b"\x89PNG\r\n\x1a\n" + b"IHDR" + b"\x00" * 100
        result = extract_text("screenshot.png", png_like)
        assert (result.get("text") or "") == ""


class TestWebRouteBinaryGuard:
    def test_screenshot_upload_at_setup_does_not_poison_profile(self, client):
        """Uploading a PNG as the brand-guidelines file must NOT make
        its bytes end up in the profile's brand_guidelines.summary.
        Before this fix, the binary was UTF-8 decoded and the resulting
        garbage flowed into every later caption prompt."""
        import io

        png_like = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200 + b"ssss"  # Looks binary.
        resp = client.post(
            "/organisation/setup/capture",
            data={
                "display_name": "Test Club",
                "country": "UK",
                "org_type": "swim_club",
                "governing_body": "Swim England",
                "brand_guidelines_file": (io.BytesIO(png_like), "screenshot.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        # Always redirects regardless — the user shouldn't see a crash.
        assert resp.status_code == 302

        # Load the saved profile and inspect.
        from mediahub.web.club_profile import load_profile

        prof = load_profile("test-club")
        assert prof is not None
        # No binary garbage in brand_guidelines / summary.
        # The status should reflect rejection.
        status = (prof.brand_guidelines_status or "").lower()
        assert "unsupported_binary" in status or status.startswith(
            "unsupported"
        ), f"Expected unsupported_binary status, got {status!r}"
        # brand_guidelines dict empty (no summary stored).
        assert not prof.brand_guidelines.get("summary", "")
