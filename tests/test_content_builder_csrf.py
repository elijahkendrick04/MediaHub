"""CSRF coverage for JS-built non-JSON writes on the content builder.

The CSRF layer (``_csrf_protect``) exempts ``application/json`` fetches but
blocks every other write without a token. The pytest suite runs with
``TESTING=True`` where ``_csrf_enforced()`` is False — which is exactly how
the content builder's FormData photo upload shipped green and then 403'd in
production ("Upload failed: Missing or invalid CSRF token."). These tests pin
the two halves of the fix:

1. every ``_layout`` page exposes the session token via
   ``<meta name="csrf-token">`` so page JS can attach ``X-CSRF-Token``;
2. with ``ENFORCE_CSRF`` on (production behaviour), the card photo upload
   403s without the header and passes the CSRF gate with it.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


class TestCsrfMetaTag:
    def test_layout_exposes_csrf_meta(self, app):
        with app.test_client() as c:
            resp = c.get("/")
            html = resp.get_data(as_text=True)
            assert '<meta name="csrf-token" content="' in html
            # The meta carries the session token the CSRF layer compares.
            with c.session_transaction() as s:
                tok = s.get("_csrf") or ""
            assert tok and f'content="{tok}"' in html

    def test_photo_upload_js_sends_the_header(self, web_module):
        src = Path(web_module.__file__).read_text(encoding="utf-8")
        upload_fn = src.split("function mhCardPhotoUpload", 1)[1][:2000]
        assert "X-CSRF-Token" in upload_fn, (
            "mhCardPhotoUpload must attach X-CSRF-Token — its FormData POST "
            "is not exempt from the CSRF layer and 403s in production without it"
        )
        assert "function mhCsrfToken" in src


class TestNoTokenlessWritesShipped:
    def test_every_embedded_js_write_is_json_tokened_or_form(self):
        """Repo guard for the bug class behind "Upload failed: Missing or
        invalid CSRF token": every JS write shipped from the web package must
        be CSRF-safe — JSON content-type (exempt), an explicit token
        (``X-CSRF-Token`` header / ``csrf_token`` field), or
        ``FormData(form)`` built from a rendered form (which carries the
        auto-injected hidden token). TESTING mode disables the CSRF layer, so
        without this scan a tokenless write only fails in production."""
        import re

        web_dir = _ROOT / "src" / "mediahub" / "web"
        files = [
            web_dir / "web.py",
            *web_dir.glob("routes_*.py"),
            *web_dir.glob("*.py"),
            *web_dir.glob("static/js/*.js"),
        ]
        pat = re.compile(r"""method\s*:\s*['"](POST|PUT|PATCH|DELETE)['"]""")
        bad: list[str] = []
        for f in {p.resolve() for p in files}:
            lines = f.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if not pat.search(line):
                    continue
                window = "\n".join(lines[max(0, i - 4) : i + 5])
                if (
                    "application/json" in window
                    or "X-CSRF-Token" in window
                    or "csrf" in window.lower()
                    or "FormData(form)" in window
                    or "sendBeacon" in window
                    # Non-executing docs samples on the API reference page.
                    or "__BASE__" in window
                ):
                    continue
                bad.append(f"{f.name}:{i + 1}: {line.strip()[:100]}")
        assert not bad, (
            "JS write(s) shipped without CSRF protection — these 403 in "
            "production even though the TESTING suite passes:\n" + "\n".join(bad)
        )


class TestPhotoUploadCsrfEnforced:
    @pytest.fixture
    def enforced_app(self, app, web_module):
        app.config["ENFORCE_CSRF"] = True
        return app

    def test_upload_without_token_is_403_csrf(self, enforced_app):
        with enforced_app.test_client() as c:
            resp = c.post(
                "/api/runs/nope/cards/x/photo",
                data={"photo": (io.BytesIO(b"not-an-image"), "p.png")},
                content_type="multipart/form-data",
            )
            assert resp.status_code == 403
            assert (resp.get_json() or {}).get("error") == "csrf"

    def test_upload_with_header_token_passes_the_gate(self, enforced_app):
        with enforced_app.test_client() as c:
            c.get("/")  # mints the session token
            with c.session_transaction() as s:
                tok = s.get("_csrf") or ""
            assert tok
            resp = c.post(
                "/api/runs/nope/cards/x/photo",
                data={"photo": (io.BytesIO(b"not-an-image"), "p.png")},
                content_type="multipart/form-data",
                headers={"X-CSRF-Token": tok},
            )
            # Past the CSRF gate: the missing run answers 404, never 403 csrf.
            assert resp.status_code == 404
            assert (resp.get_json() or {}).get("error") == "run_not_found"
