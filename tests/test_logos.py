"""tests/test_logos.py — D1. Multi-logo storage + metadata.

The user wants every logo variant the org has on file (PNG, JPG, SVG,
WEBP, PDF, EPS, AI). Each one is stored under
``{DATA_DIR}/club_logos/<profile_id>/<uuid>.<ext>`` and a metadata dict
appended to ClubProfile.brand_logos. The metadata feeds:

  - the signup-page thumbnail grid (rename + delete)
  - brand.context._logos_prose (so the AI knows which variants exist
    when picking imagery for generated posts)

These tests cover the storage primitives — the web routes and AI
vision integration are covered separately. Vision is gated behind a
``describe_image`` helper on the llm module; if not present the AI
fields stay empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.brand import logos  # noqa: E402


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n" + b"x" * 50


@pytest.fixture
def iso_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# logos_dir
# ---------------------------------------------------------------------------

def test_logos_dir_namespaces_per_profile(iso_root):
    a = logos.logos_dir("club-a")
    b = logos.logos_dir("club-b")
    assert a != b
    assert a.exists() and b.exists()


def test_logos_dir_sanitises_profile_id(iso_root):
    # Profile ids with awkward chars must not yield directory escapes
    d = logos.logos_dir("../etc/passwd")
    # The directory must stay under club_logos/ — even though "../"
    # gets sanitised to "_etc_passwd", confirm the resolved path is
    # genuinely inside iso_root/club_logos and not at /etc/passwd.
    resolved = d.resolve()
    safe_root = (iso_root / "club_logos").resolve()
    assert str(resolved).startswith(str(safe_root))
    # Slash, the actual traversal character, must be gone from the name.
    assert "/" not in d.name


def test_logos_dir_requires_profile_id():
    with pytest.raises(ValueError):
        logos.logos_dir("")


# ---------------------------------------------------------------------------
# store_logo
# ---------------------------------------------------------------------------

def test_store_logo_writes_file_and_returns_metadata(iso_root):
    meta = logos.store_logo(
        profile_id="acme",
        filename="navy-on-white.png",
        file_bytes=PNG_SIGNATURE,
    )
    assert meta["logo_id"]
    assert meta["original_filename"] == "navy-on-white.png"
    assert meta["mime"] == "image/png"
    assert meta["byte_size"] == len(PNG_SIGNATURE)
    assert meta["uploaded_at"]
    # stored_path is relative to DATA_DIR
    full = iso_root / meta["stored_path"]
    assert full.exists()
    assert full.read_bytes() == PNG_SIGNATURE


def test_store_logo_rejects_unsupported_extension(iso_root):
    with pytest.raises(ValueError) as ei:
        logos.store_logo(profile_id="acme",
                          filename="hack.exe", file_bytes=b"MZ")
    assert "unsupported format" in str(ei.value)


def test_store_logo_rejects_oversize(iso_root):
    big = b"x" * (logos.MAX_LOGO_BYTES + 1)
    with pytest.raises(ValueError) as ei:
        logos.store_logo(profile_id="acme",
                          filename="big.png", file_bytes=big)
    assert "exceeds" in str(ei.value)


def test_store_logo_rejects_empty(iso_root):
    with pytest.raises(ValueError):
        logos.store_logo(profile_id="acme",
                          filename="x.png", file_bytes=b"")


def test_store_logo_enforces_per_profile_cap(iso_root):
    existing = [{"logo_id": f"x{i}"} for i in range(logos.MAX_LOGOS_PER_PROFILE)]
    with pytest.raises(ValueError) as ei:
        logos.store_logo(profile_id="acme",
                          filename="extra.png", file_bytes=PNG_SIGNATURE,
                          existing_logos=existing)
    assert "delete one before uploading" in str(ei.value)


def test_store_logo_supports_svg_pdf_eps_ai(iso_root):
    for ext in ("svg", "pdf", "eps", "ai", "webp", "jpg", "jpeg"):
        meta = logos.store_logo(
            profile_id="acme",
            filename=f"variant.{ext}",
            file_bytes=b"<dummy file content>",
        )
        assert meta["mime"]
        assert meta["original_filename"].endswith(f".{ext}")


# ---------------------------------------------------------------------------
# resolve_logo_path — IDOR guard
# ---------------------------------------------------------------------------

def test_resolve_returns_path_for_owned_logo(iso_root):
    meta = logos.store_logo(profile_id="acme",
                              filename="x.png", file_bytes=PNG_SIGNATURE)
    p = logos.resolve_logo_path("acme", meta["logo_id"])
    assert p is not None and p.exists()


def test_resolve_returns_none_for_other_profile(iso_root):
    meta = logos.store_logo(profile_id="acme",
                              filename="x.png", file_bytes=PNG_SIGNATURE)
    p = logos.resolve_logo_path("evil-other", meta["logo_id"])
    assert p is None


def test_resolve_rejects_path_traversal(iso_root):
    p = logos.resolve_logo_path("acme", "../etc/passwd")
    assert p is None


def test_resolve_returns_none_for_unknown_id(iso_root):
    p = logos.resolve_logo_path("acme", "nonexistent")
    assert p is None


# ---------------------------------------------------------------------------
# delete_logo
# ---------------------------------------------------------------------------

def test_delete_removes_file(iso_root):
    meta = logos.store_logo(profile_id="acme",
                              filename="x.png", file_bytes=PNG_SIGNATURE)
    path = iso_root / meta["stored_path"]
    assert path.exists()
    assert logos.delete_logo("acme", meta["logo_id"]) is True
    assert not path.exists()


def test_delete_unknown_returns_false(iso_root):
    assert logos.delete_logo("acme", "nope") is False


def test_delete_missing_inputs():
    assert logos.delete_logo("", "x") is False
    assert logos.delete_logo("acme", "") is False


# ---------------------------------------------------------------------------
# AI description — no vision helper → empty dict
# ---------------------------------------------------------------------------

def test_describe_returns_empty_when_no_vision_helper(monkeypatch):
    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True, raising=False)
    # Ensure no describe_image attribute exists on the llm module
    if hasattr(_llm, "describe_image"):
        monkeypatch.delattr(_llm, "describe_image", raising=True)
    out = logos.describe_logo_with_ai(b"\x89PNG...", "image/png")
    assert out == {}


def test_describe_handles_vision_failure(monkeypatch):
    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True, raising=False)

    def boom(*a, **kw):
        raise RuntimeError("vision API exploded")
    monkeypatch.setattr(_llm, "describe_image", boom, raising=False)
    out = logos.describe_logo_with_ai(b"\x89PNG...", "image/png")
    assert out == {}


def test_describe_normalises_response(monkeypatch):
    import mediahub.media_ai.llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True, raising=False)
    monkeypatch.setattr(
        _llm, "describe_image",
        lambda *a, **kw: {
            "description": "Wordmark in navy on transparent. Suits dark backgrounds.",
            "dominant_colours": ["#0A2540", "0f0", "garbage"],
        },
        raising=False,
    )
    out = logos.describe_logo_with_ai(b"\x89PNG...", "image/png")
    assert out["description"].startswith("Wordmark in navy")
    # 3-digit expanded, garbage rejected
    assert "#0a2540" in out["dominant_colours"]
    assert "#00ff00" in out["dominant_colours"]
    assert len(out["dominant_colours"]) == 2


# ---------------------------------------------------------------------------
# brand_context_for_llm surfaces the logo inventory
# ---------------------------------------------------------------------------

def test_context_lists_logo_variants(iso_root):
    from mediahub.brand.context import brand_context_for_llm
    from mediahub.web.club_profile import ClubProfile
    prof = ClubProfile(
        profile_id="acme",
        display_name="ACME",
        brand_logos=[
            {"logo_id": "a", "original_filename": "navy.svg",
              "label": "Navy on white", "mime": "image/svg+xml",
              "ai_description": "Wordmark, primary mark for light backgrounds.",
              "ai_dominant_colours": ["#0a2540"]},
            {"logo_id": "b", "original_filename": "white.png",
              "label": "White mono", "mime": "image/png",
              "ai_description": "Mono variant for dark backgrounds.",
              "ai_dominant_colours": ["#ffffff"]},
        ],
    )
    ctx = brand_context_for_llm(prof)
    assert "2 logo variants" in ctx
    assert "Navy on white" in ctx
    assert "Mono variant for dark backgrounds" in ctx
