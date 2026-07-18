"""Mobile-parity audit tool (`/tools/mobile-parity`).

Pins the operator diagnostic that loads every in-app page in a phone-sized
frame and scores it for mobile readiness. The audit logic itself runs in the
browser (client-side, same-origin), so these tests cover the server contract:

  * the route is operator-gated (404 for everyone else),
  * it auto-discovers a sensible set of GET pages and excludes machinery
    (api / webhooks / static / downloads / JSON probes / the tool itself),
  * the rendered page carries the audit shell + the checks the engine runs.
"""

from __future__ import annotations

import json
import re


def _operator_get(app, path):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["dev_operator"] = True
        return c.get(path)


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_tool_is_404_for_non_operator(app):
    with app.test_client() as c:
        r = c.get("/tools/mobile-parity")
    assert r.status_code == 404


def test_tool_renders_for_operator(app):
    r = _operator_get(app, "/tools/mobile-parity")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "data-mp" in html
    assert "Mobile" in html and "parity" in html


# ---------------------------------------------------------------------------
# Target discovery
# ---------------------------------------------------------------------------


def _targets(app):
    html = _operator_get(app, "/tools/mobile-parity").get_data(as_text=True)
    m = re.search(r"data-targets='(\[.*?\])'", html, re.S)
    assert m, "audit targets not embedded in the page"
    raw = m.group(1).replace("&#39;", "'").replace("&#34;", '"')
    return json.loads(raw)


def test_discovers_core_product_pages(app):
    urls = {t["url"] for t in _targets(app)}
    # The core workflow surfaces must be in the sweep.
    for expected in ("/", "/make", "/media-library", "/season", "/activity", "/settings"):
        assert expected in urls, f"{expected} missing from audit targets"


def test_excludes_machinery_and_self(app):
    urls = {t["url"] for t in _targets(app)}
    # No API, webhooks, static, the JSON health probe, or the tool itself.
    assert not any(u.startswith("/api") for u in urls)
    assert not any(u.startswith("/webhooks") for u in urls)
    assert not any(u.startswith("/static") for u in urls)
    assert "/health" not in urls  # JSON probe, not an HTML page
    assert "/tools/mobile-parity" not in urls


def test_targets_have_label_and_url(app):
    targets = _targets(app)
    assert len(targets) >= 20
    for t in targets:
        assert t["url"].startswith("/")
        assert t["label"].strip()


# ---------------------------------------------------------------------------
# The checks the engine actually runs are present in the page
# ---------------------------------------------------------------------------


def test_audit_engine_covers_the_parity_checks(app):
    html = _operator_get(app, "/tools/mobile-parity").get_data(as_text=True)
    # Each mobile-parity check must be wired into the shipped engine.
    assert "scrollWidth" in html  # horizontal overflow
    assert "viewport" in html  # viewport meta
    assert "getBoundingClientRect" in html  # touch-target sizing
    assert "mh-nav-toggle" in html  # navigation reachability
    # Self-correcting on the two false-positive classes the audit found.
    assert "contentType" in html  # skips non-HTML JSON probes
    assert "WCAG 2.5.8" in html or "inline" in html  # exempts inline links


def test_devices_include_phone_and_desktop(app):
    from mediahub.web.mobile_parity import MOBILE_PARITY_DEVICES

    kinds = {d["kind"] for d in MOBILE_PARITY_DEVICES}
    assert "phone" in kinds and "desktop" in kinds
    assert sum(1 for d in MOBILE_PARITY_DEVICES if d.get("default")) == 1
