"""F-10 — the brand-kit editor must not be an expert-only config form.

The kit forms asked for palette values as bare "#hex" text (a typo or "red" was
silently dropped while the page still flashed "Saved kit"), a free-text "font
pairing id" (an internal identifier with no list), a free-text "tone override",
and raw "Lock tokens" checkboxes. Palette is now colour pickers, font + tone are
dropdowns of the real catalogue, locks are plain-language, and a dropped colour
is reported instead of a blanket success.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="brandclub", display_name="Brand Club", brand_primary="#0E2A47")
    )
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "brandclub"
        yield c


def _make_kit(client, name="Gala"):
    client.post("/api/brand/kits", data={"name": name, "role": "event"})
    from mediahub.web.club_profile import load_profile
    from mediahub.brand.kits import list_kits

    return next(k.kit_id for k in list_kits(load_profile("brandclub")) if k.name == name)


def test_kit_form_uses_pickers_and_dropdowns_not_hex_text(client):
    _make_kit(client)
    html = client.get("/brand").get_data(as_text=True)
    # Colour pickers, not bare hex text inputs.
    assert 'type="color" name="primary"' in html
    assert 'placeholder="primary #hex"' not in html
    # Font pairing is a dropdown of the real catalogue…
    assert 'name="font_pairing"' in html and "<select" in html
    assert "Anton + Inter" in html
    assert 'placeholder="font pairing id (optional)"' not in html
    # …tone is a dropdown of the real tones…
    assert "Warm club" in html and "Data-led" in html
    assert 'placeholder="tone override (optional)"' not in html
    # …and lock tokens read in plain language.
    assert "Lock colours" in html
    assert ">palette</label>" not in html


def test_update_reports_unreadable_colour_instead_of_blanket_success(client):
    kid = _make_kit(client)
    # A hand-crafted POST can still carry an unreadable value (the colour picker
    # can't, but a palette import or scripted POST can) — the user must be told.
    r = client.post(
        f"/api/brand/kits/{kid}",
        data={"name": "Gala", "primary": "reddish"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "could not read" in body and "primary" in body


def test_valid_update_still_saves_cleanly(client):
    kid = _make_kit(client)
    r = client.post(
        f"/api/brand/kits/{kid}",
        data={"name": "Gala 2026", "primary": "#123456", "font_pairing": "bebas-grotesk"},
        follow_redirects=True,
    )
    from mediahub.web.club_profile import load_profile
    from mediahub.brand.kits import list_kits

    kit = next(k for k in list_kits(load_profile("brandclub")) if k.kit_id == kid)
    assert kit.palette.get("primary") == "#123456"
    assert kit.font_pairing == "bebas-grotesk"
    assert "could not read" not in r.get_data(as_text=True)
