"""B-8 — pairing a presenter phone no longer needs ~30 hand-typed characters.

The presenter console showed "Open <url> and enter:" plus a 6-character code —
two screens of hand-typing to pair a phone. The console now renders a QR that
encodes the ABSOLUTE /remote/<code> deep link (which connects directly — J-14
guarantees a valid code always connects), plus a tappable link of the same URL.
Honest fallback: without the QR backend (segno) the block is empty and the
text-only pairing info stands on its own, exactly as before.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A"))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _save_deck(pid="club-a", title="AGM 2026"):
    from mediahub.documents import models as m
    from mediahub.documents.models import DocumentSpec, Section
    from mediahub.documents.store import save_document

    spec = DocumentSpec(
        title=title,
        kind="deck",
        doc_format="agm_deck",
        geometry="slide_16_9",
        brand_profile_id=pid,
        sections=[
            Section(layout="cover", blocks=[m.heading(title, 1)], notes="Welcome."),
            Section(blocks=[m.heading("The year", 2)], notes="Numbers."),
        ],
    )
    save_document(pid, spec)
    return spec


def _live_code(doc_id, pid="club-a"):
    from mediahub.documents import presenter as _pres

    session = _pres.get_live_for(doc_id, pid)
    assert session is not None
    return session.pairing_code


def test_console_shows_qr_and_tappable_deep_link(app_env):
    c = app_env.test_client()
    _login(c)
    spec = _save_deck()

    html = c.get(f"/documents/{spec.doc_id}/present").get_data(as_text=True)
    code = _live_code(spec.doc_id)
    deep_link = f"http://localhost/remote/{code}"

    # The QR block is on the page with a real inline SVG inside it.
    assert 'id="remote-qr"' in html
    assert "<svg" in html.split('id="remote-qr"', 1)[1]
    # Tappable fallback <a> of the same absolute deep-link URL.
    assert f'href="{deep_link}"' in html
    # The manual path (landing URL + code) survives alongside the QR.
    assert "and enter:" in html
    assert code in html


def test_qr_encodes_the_remote_deep_link(app_env, monkeypatch):
    """The QR data is the ABSOLUTE /remote/<code> deep link — not the bare
    /remote landing page."""
    from mediahub.web import qr as _qr

    encoded = []
    real_qr_svg = _qr.qr_svg

    def _capture(data, **kwargs):
        encoded.append(str(data))
        return real_qr_svg(data, **kwargs)

    monkeypatch.setattr("mediahub.web.qr.qr_svg", _capture)

    c = app_env.test_client()
    _login(c)
    spec = _save_deck()
    r = c.get(f"/documents/{spec.doc_id}/present")
    assert r.status_code == 200
    code = _live_code(spec.doc_id)

    assert encoded == [f"http://localhost/remote/{code}"]
    # Absolute (scannable off-device), and the deep link — not the landing page.
    assert encoded[0].startswith("http")
    assert not encoded[0].endswith("/remote")


def test_text_only_fallback_without_segno(app_env, monkeypatch):
    """No segno → no QR, no half-rendered block: today's text-only pairing
    info (landing URL + big code) stands on its own."""
    monkeypatch.setattr("mediahub.web.qr.is_available", lambda: False)

    c = app_env.test_client()
    _login(c)
    spec = _save_deck()
    html = c.get(f"/documents/{spec.doc_id}/present").get_data(as_text=True)
    code = _live_code(spec.doc_id)

    assert 'id="remote-qr"' not in html
    assert f"/remote/{code}" not in html  # no dangling deep link either
    assert "__REMOTE_QR_SVG__" not in html  # token always filled
    assert "http://localhost/remote" in html  # landing URL still shown
    assert "and enter:" in html
    assert code in html


def test_qr_render_failure_degrades_to_text_only(app_env, monkeypatch):
    """A QR backend error must never break the console — the page renders
    with the text-only pairing info."""

    def _boom(data, **kwargs):
        raise RuntimeError("segno exploded")

    monkeypatch.setattr("mediahub.web.qr.qr_svg", _boom)

    c = app_env.test_client()
    _login(c)
    spec = _save_deck()
    r = c.get(f"/documents/{spec.doc_id}/present")
    html = r.get_data(as_text=True)

    assert r.status_code == 200
    assert 'id="remote-qr"' not in html
    assert "__REMOTE_QR_SVG__" not in html
    assert "and enter:" in html
    assert _live_code(spec.doc_id) in html
