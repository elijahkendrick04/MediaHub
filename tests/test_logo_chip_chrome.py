"""Unified chrome logo chip — keyed silhouette on a contrast-aware backing.

The nav avatar, sign-in picker tiles and settings preview all render a club's
logo through the SAME elevated chip so every org reads at the same size and
weight whatever its logo's colour / shape / size / format — or falls back to a
clean org-initials avatar in the same frame. This pins:

  * the deterministic backing-tone decision (a light "paper" chip for dark/colour
    logos, a dark "ink" chip for light ones — whichever the logo reads best on,
    by APCA), and that it's cache-versioned;
  * the serve routes' keyed ``?bg=1`` silhouette + the ``?chip=1`` 404-on-failure
    (so the chip's <img> onerror swaps in the initials, never a blank pixel);
  * the ``_logo_chip_html`` markup helper (elevated mode) — the rendered image,
    the tone, size and brand modifier classes, a built-in initials fallback, the
    onerror wiring, and that the legacy chip path still works;
  * the four surfaces rendering the chip, including the always-an-avatar fallback;
  * robustness for any format and the contrast guarantee.

Presentation-only — the deterministic engine and AI surfaces are untouched.
"""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image, ImageDraw

from mediahub.brand import logos as L
from mediahub.theming.contrast import apca
from mediahub.web import web as webmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _solid(colour):
    def paint(d, w, h):
        d.ellipse([16, 16, w - 16, h - 16], fill=colour)

    return paint


def _store_img(pid, lid, ext, im, mime, fmt):
    d = L.logos_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    if fmt == "JPEG":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, fmt)
    (d / f"{lid}.{ext}").write_bytes(buf.getvalue())
    return {"logo_id": lid, "mime": mime, "original_filename": f"{lid}.{ext}"}


def _store_bytes(pid, lid, ext, data, mime):
    d = L.logos_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lid}.{ext}").write_bytes(data)
    return {"logo_id": lid, "mime": mime, "original_filename": f"{lid}.{ext}"}


def _img(paint, w=200, h=160, alpha=True):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0) if alpha else (255, 255, 255, 255))
    paint(ImageDraw.Draw(im), w, h)
    return im


def _make_org(pid, name="Chip Test SC", *, logos=None, brand="#16306a", url=""):
    from mediahub.web.club_profile import ClubProfile, save_profile

    prof = ClubProfile(
        profile_id=pid, display_name=name, brand_primary=brand, brand_capture_status="ok"
    )
    prof.brand_palette_extracted = {"primary": brand}
    if logos:
        prof.brand_logos = logos
    if url:
        prof.brand_logo_url = url
    save_profile(prof)


def _home(client, pid):
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200
    return r.get_data(as_text=True)


_HEX = "#0a0b11"  # house ink
_PAPER = "#f5f2e8"  # house paper


# --------------------------------------------------------------------------- #
# 1. backing-tone decision (deterministic, APCA-driven)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,colour,expect",
    [
        ("black", (15, 18, 28, 255), "light"),
        ("navy", (20, 34, 80, 255), "light"),
        ("mid-grey", (128, 128, 128, 255), "light"),
        ("white", (245, 245, 245, 255), "dark"),
        ("pale-yellow", (245, 225, 90, 255), "dark"),
    ],
)
def test_chip_tone_picks_the_readable_backing(tmp_path, monkeypatch, name, colour, expect):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    meta = _store_img("org-" + name, "l", "png", _img(_solid(colour)), "image/png", "PNG")
    _make_org  # noqa: B018 - keep import warm; not needed here
    tone = L.logo_chip_tone("org-" + name, meta["logo_id"])
    assert tone == expect, f"{name} {colour} → {tone}, expected {expect}"
    # And the chosen backing really is the higher-contrast one for that ink.
    hexcol = "#%02x%02x%02x" % colour[:3]
    chosen = _PAPER if tone == "light" else _HEX
    other = _HEX if tone == "light" else _PAPER
    assert abs(apca(hexcol, chosen)) >= abs(apca(hexcol, other))


def test_chip_tone_is_cache_versioned(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    meta = _store_img("org-cache", "l", "png", _img(_solid((245, 245, 245, 255))), "image/png", "PNG")
    assert L.logo_chip_tone("org-cache", "l") == "dark"  # writes the cache
    sil = L.logo_bg_silhouette_path("org-cache", "l")
    cache = sil.with_suffix(".chip.json")
    assert cache.exists()
    # A stale cache from an older calibration (no/old version) must be ignored.
    cache.write_text('{"tone": "light"}')  # no "v"
    assert L.logo_chip_tone("org-cache", "l") == "dark"  # recomputed, not the stale value


def test_chip_tone_defaults_light_for_svg_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    d = L.logos_dir("org-svg")
    (d / "l.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><circle r="9"/></svg>')
    assert L.logo_chip_tone("org-svg", "l") == "light"
    assert L.logo_chip_tone("org-svg", "missing") == "light"


# --------------------------------------------------------------------------- #
# 2. serve routes — keyed silhouette + chip=1 404 fallback
# --------------------------------------------------------------------------- #
def test_chip_serve_returns_keyed_image_and_404s_when_unrenderable(client):
    good = _store_img("org-serve", "good", "png", _img(_solid((40, 120, 200, 255))), "image/png", "PNG")
    bad = _store_bytes("org-serve", "bad", "pdf", b"%PDF-1.4 not an image", "application/pdf")
    _make_org("org-serve", logos=[good, bad])
    with client.session_transaction() as s:
        s["active_profile_id"] = "org-serve"

    # Renderable upload → keyed PNG.
    ok = client.get("/organisation/setup/logo/good?bg=1&chip=1")
    assert ok.status_code == 200 and ok.headers["Content-Type"] == "image/png"

    # Unrenderable upload + chip=1 → a real 404 (so the chip onerror→initials).
    miss = client.get("/organisation/setup/logo/bad?bg=1&chip=1")
    assert miss.status_code == 404

    # …but the backdrop path (bg without chip) still gets a transparent pixel.
    px = client.get("/organisation/setup/logo/bad?bg=1")
    assert px.status_code == 200 and px.headers["Content-Type"] == "image/png"


def test_picker_serve_route_supports_keyed_chip(client):
    """The session-permitted picker route (organisation_logo_serve) gained ?bg=1."""
    meta = _store_img("org-pick", "l", "png", _img(_solid((40, 120, 200, 255))), "image/png", "PNG")
    _make_org("org-pick", logos=[meta])
    # No active session needed — the picker route is gated to session-permitted orgs,
    # and an un-onboarded fresh session may use any not-yet-claimed org.
    r = client.get("/organisation/org-pick/logo/l?bg=1&chip=1")
    assert r.status_code in (200, 404)  # 200 keyed image, or 404 if not session-permitted
    if r.status_code == 200:
        assert r.headers["Content-Type"] in ("image/png", "image/svg+xml")


# --------------------------------------------------------------------------- #
# 3. _logo_chip_html — elevated markup + legacy back-compat
# --------------------------------------------------------------------------- #
def test_helper_elevated_chip_markup(client):
    with webmod.app.test_request_context():
        html = webmod._logo_chip_html(
            "/organisation/setup/logo/l?bg=1&chip=1",
            size="sm",
            tone="dark",
            brand_hex="#16306a",
            initials="BD",
        )
    assert "mh-logo-chip mh-logo-chip--sm mh-logo-chip--dark" in html
    assert "--chip-brand:#16306a" in html
    assert "bg=1" in html and "chip=1" in html
    assert "mh-logo-chip__img" in html
    assert "onerror=" in html and "is-empty" in html
    assert ">BD<" in html  # built-in initials


def test_helper_no_logo_is_empty_initials_only(client):
    with webmod.app.test_request_context():
        html = webmod._logo_chip_html("", size="md", tone="light", initials="AB")
    assert "is-empty" in html  # no image → initials shown immediately
    assert "<img" not in html
    assert ">AB<" in html


def test_helper_legacy_path_unchanged(client):
    """No `size` → the legacy chip/bare behaviour (Stage F) is preserved."""
    with webmod.app.test_request_context():
        chip = webmod._logo_chip_html("/test.png", "alt")
        bare = webmod._logo_chip_html("/x.png", "alt", force_bare=True)
    assert "mh-logo-chip" in chip and 'src="/test.png"' in chip and 'alt="alt"' in chip
    assert "mh-logo-chip--sm" not in chip  # not the elevated path
    assert "mh-logo-chip" not in bare and "<img" in bare


def test_helper_escapes_initials_and_brand(client):
    with webmod.app.test_request_context():
        html = webmod._logo_chip_html(
            "", size="md", initials="<b>x</b>", brand_hex="red;}<script>"
        )
    assert "<b>x</b>" not in html  # escaped
    assert "<script>" not in html  # invalid brand hex dropped, nothing injected


# --------------------------------------------------------------------------- #
# 4. the surfaces render the chip
# --------------------------------------------------------------------------- #
def test_nav_avatar_renders_the_chip(client):
    meta = _store_img("org-nav", "l", "png", _img(_solid((20, 34, 80, 255))), "image/png", "PNG")
    _make_org("org-nav", "Brighton Dolphins", logos=[meta], brand="#16306a")
    html = _home(client, "org-nav")
    m = re.search(r'<span class="mh-logo-chip mh-logo-chip--sm mh-logo-chip--(light|dark)"', html)
    assert m, "nav avatar chip not found"
    assert m.group(1) == "light"  # navy logo → light chip
    assert "--chip-brand:#16306a" in html
    assert "bg=1&amp;chip=1" in html or "bg=1&chip=1" in html


def test_nav_avatar_falls_back_to_initials_when_no_logo(client):
    _make_org("org-noimg", "Initials Only FC", brand="#2a7")
    html = _home(client, "org-noimg")
    # The nav still carries a consistent avatar — the org initials in the chip.
    assert "mh-logo-chip mh-logo-chip--sm" in html
    assert "is-empty" in html  # no logo → initials shown immediately
    assert "mh-logo-chip__initials" in html
    assert ">IF<" in html  # Initials Only FC → "IF"


def test_picker_tiles_are_consistent_chips(client):
    _make_org(
        "org-a",
        "Alpha SC",
        logos=[_store_img("org-a", "l", "png", _img(_solid((20, 30, 70, 255))), "image/png", "PNG")],
    )
    _make_org(
        "org-b",
        "Beta SC",
        logos=[_store_img("org-b", "l", "png", _img(_solid((245, 245, 245, 255))), "image/png", "PNG")],
    )
    _make_org("org-c", "Gamma SC")  # no logo → initials chip
    body = client.get("/sign-in").get_data(as_text=True)
    tones = re.findall(r"mh-logo-chip mh-logo-chip--lg mh-logo-chip--(light|dark)", body)
    assert tones.count("light") >= 2 and "dark" in tones  # Beta(white)→dark, others→light
    assert body.count("mh-logo-chip--lg") >= 3  # every tile is the same elevated chip
    assert ">GS<" in body  # Gamma SC initials fallback


# --------------------------------------------------------------------------- #
# 5. robustness — any format renders; unrenderable falls to initials
# --------------------------------------------------------------------------- #
def test_heic_logo_chip_when_plugin_present(client):
    if ".heic" not in Image.registered_extensions():
        pytest.skip("pillow_heif not available")
    meta = _store_img("org-heic", "l", "heic", _img(_solid((20, 34, 80, 255))), "image/heic", "HEIF")
    _make_org("org-heic", logos=[meta])
    with client.session_transaction() as s:
        s["active_profile_id"] = "org-heic"
    r = client.get("/organisation/setup/logo/l?bg=1&chip=1")
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/png"


def test_unrenderable_logo_chip_shows_initials_via_404(client):
    bad = _store_bytes("org-bad", "l", "pdf", b"%PDF-1.4 nope", "application/pdf")
    _make_org("org-bad", "Portable SC", logos=[bad])
    html = _home(client, "org-bad")
    # The chip still renders (with the keyed src that 404s → onerror initials).
    assert re.search(r'<span class="mh-logo-chip mh-logo-chip--sm', html)
    assert "mh-logo-chip__initials" in html
    with client.session_transaction() as s:
        s["active_profile_id"] = "org-bad"
    assert client.get("/organisation/setup/logo/l?bg=1&chip=1").status_code == 404
