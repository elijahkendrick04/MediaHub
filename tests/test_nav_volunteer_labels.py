"""Regression: topnav must not show jargon labels that confuse non-technical volunteers.

'Developer ✓' appeared in the top nav bar under dev_operator sessions.
With text-transform:uppercase applied by the nav CSS it rendered as
'DEVELOPER ✓' — meaningless and alarming to a volunteer uploading their
club's results.  The top nav must only contain labels a volunteer can
understand; operator sign-in status belongs in the footer ('Developer
access') and any logout link should be labelled what it does.
"""
from __future__ import annotations

import re

import pytest

_DEV_SESSION_KEY = "dev_operator"  # mirrors mediahub.web.auth._DEV_SESSION_KEY


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def _primary_nav_link_texts(html: str) -> list[str]:
    """Return stripped text of every <a> inside #mh-primary-nav."""
    m = re.search(
        r'<nav\s[^>]*id="mh-primary-nav"[^>]*>(.*?)</nav>',
        html,
        re.DOTALL,
    )
    if not m:
        return []
    return [
        re.sub(r"<[^>]+>", "", frag).strip()
        for frag in re.findall(r"<a\b[^>]*>(.*?)</a>", m.group(1), re.DOTALL)
    ]


def test_developer_label_absent_from_topnav_in_dev_operator_session(app):
    """'Developer' must not appear as a nav link — confuses non-technical volunteers."""
    with app.test_client() as c:
        with c.session_transaction() as s:
            s[_DEV_SESSION_KEY] = True
        resp = c.get("/")
    assert resp.status_code == 200
    labels = _primary_nav_link_texts(resp.data.decode("utf-8", errors="replace"))
    assert not any("developer" in t.lower() for t in labels), (
        f"'developer' still in topnav labels: {labels!r}. "
        "Volunteers don't know what DEVELOPER means in the nav."
    )
