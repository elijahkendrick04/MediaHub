"""Integration tests for responsive meta tags & CSS delivery.

These tests boot the Flask app and assert that every rendered HTML response
ships with the responsive guardrails — the viewport meta tag, the
``color-scheme`` meta, and the guardrails CSS payload — so future template
edits can't silently regress mobile / tablet / accessibility behaviour.

Routes exercised here are deliberately the no-auth, always-reachable
trust-signal endpoints (``/status``, ``/healthz``, ``/healthz/usage``).
Adding more routes to ``_PUBLIC_HTML_ROUTES`` extends coverage automatically.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def fresh_app(app):
    """A clean app instance with isolated DATA_DIR per test (via the canonical
    ``app`` fixture in tests/conftest.py)."""
    with app.test_client() as c:
        # /healthz/usage is operator-only; sign the spot-check client in as the
        # operator so both public-HTML routes render their full template.
        with c.session_transaction() as s:
            s["dev_operator"] = True
        yield c


# Routes that always render full HTML through the shared template,
# don't require an active organisation, and so are safe to spot-check.
# /healthz returns JSON so it's intentionally excluded.
_PUBLIC_HTML_ROUTES = ["/status", "/healthz/usage"]


# ---------------------------------------------------------------------------
# Viewport meta tag — the single most important responsive primitive.
# ---------------------------------------------------------------------------


class TestViewportMetaTag:
    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_viewport_meta_present(self, fresh_app, route):
        resp = fresh_app.get(route)
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert '<meta name="viewport"' in body, f"missing viewport meta on {route}"

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_viewport_sets_device_width(self, fresh_app, route):
        body = fresh_app.get(route).get_data(as_text=True)
        m = re.search(r'<meta name="viewport"[^>]*content="([^"]+)"', body)
        assert m is not None
        content = m.group(1)
        assert (
            "width=device-width" in content
        ), f"viewport on {route} doesn't set width=device-width: {content!r}"
        assert "initial-scale=1" in content

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_viewport_allows_zoom(self, fresh_app, route):
        """WCAG 1.4.4 Resize Text — users must be able to zoom to 200%.
        That means user-scalable=no or maximum-scale=1 are forbidden.
        Axe & Lighthouse both fail builds that disable scaling."""
        body = fresh_app.get(route).get_data(as_text=True)
        m = re.search(r'<meta name="viewport"[^>]*content="([^"]+)"', body)
        assert m is not None
        content = m.group(1).lower().replace(" ", "")
        assert "user-scalable=no" not in content, f"{route} disables zoom — fails WCAG 1.4.4"
        # If maximum-scale is set, it must be ≥ 2 so 200% zoom is reachable.
        ms = re.search(r"maximum-scale=([\d.]+)", content)
        if ms:
            assert float(ms.group(1)) >= 2.0

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_viewport_fit_cover_for_notch_support(self, fresh_app, route):
        """viewport-fit=cover is the modern hint that lets safe-area-inset
        env vars resolve to non-zero on notched / Dynamic Island devices.
        Without it the page renders inside the safe area and the guardrails
        body padding has no effect."""
        body = fresh_app.get(route).get_data(as_text=True)
        m = re.search(r'<meta name="viewport"[^>]*content="([^"]+)"', body)
        assert m is not None
        assert "viewport-fit=cover" in m.group(1)


# ---------------------------------------------------------------------------
# Other modern meta tags
# ---------------------------------------------------------------------------


class TestModernMetaTags:
    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_color_scheme_meta(self, fresh_app, route):
        """color-scheme meta colours the native browser UI (scrollbar,
        form controls) consistently with the app theme."""
        body = fresh_app.get(route).get_data(as_text=True)
        assert '<meta name="color-scheme"' in body

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_theme_color_meta(self, fresh_app, route):
        """theme-color colours the mobile browser address bar."""
        body = fresh_app.get(route).get_data(as_text=True)
        assert '<meta name="theme-color"' in body


# ---------------------------------------------------------------------------
# Guardrails CSS delivery — the inline <style> block must include the
# guardrails on every page.
# ---------------------------------------------------------------------------


class TestResponsiveGuardrailsDelivered:
    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_guardrails_marker_in_html(self, fresh_app, route):
        body = fresh_app.get(route).get_data(as_text=True)
        assert "RESPONSIVE GUARDRAILS" in body, f"guardrails CSS not present in {route}"

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_dvh_in_html(self, fresh_app, route):
        body = fresh_app.get(route).get_data(as_text=True)
        assert "100dvh" in body

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_safe_area_inset_in_html(self, fresh_app, route):
        body = fresh_app.get(route).get_data(as_text=True)
        assert "safe-area-inset" in body

    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    def test_touch_target_min_in_html(self, fresh_app, route):
        body = fresh_app.get(route).get_data(as_text=True)
        assert "--mh-touch-min" in body


# ---------------------------------------------------------------------------
# Sanity check the existing brand layer survived — these tokens are part of
# the design contract and downstream rules depend on them.
# ---------------------------------------------------------------------------


class TestExistingDesignTokensSurvive:
    @pytest.mark.parametrize("route", _PUBLIC_HTML_ROUTES)
    @pytest.mark.parametrize("token", ["--lane:", "--medal:", "--ink:", "--bg:"])
    def test_brand_token_in_html(self, fresh_app, route, token):
        body = fresh_app.get(route).get_data(as_text=True)
        assert token in body, f"brand token {token!r} missing on {route}"
