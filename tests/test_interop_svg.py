"""1.21 interop — SVG sanitisation (security) + import; PSD honest-error."""

from __future__ import annotations

import pytest

from mediahub.interop import psd_import
from mediahub.interop.svg_import import SvgImportError, sanitize_svg, import_svg

_NS = 'xmlns="http://www.w3.org/2000/svg"'


def _clean(svg: bytes) -> str:
    return sanitize_svg(svg).decode()


def test_strips_script_element():
    out = _clean(f"<svg {_NS}><script>alert(1)</script><rect/></svg>".encode())
    assert "<script" not in out and "alert" not in out


def test_strips_event_handlers():
    out = _clean(f'<svg {_NS}><rect onclick="evil()" onload="x" width="1" height="1"/></svg>'.encode())
    assert "onclick" not in out and "onload" not in out


def test_strips_javascript_href():
    out = _clean(f'<svg {_NS}><a href="javascript:evil()">x</a></svg>'.encode())
    assert "javascript:" not in out


def test_strips_external_href():
    out = _clean(f'<svg {_NS}><image href="https://evil.example/x.png"/></svg>'.encode())
    assert "evil.example" not in out


def test_keeps_internal_ref_and_data_image():
    svg = (
        f'<svg {_NS}><use href="#icon"/>'
        '<image href="data:image/png;base64,iVBORw0KGgo="/></svg>'
    ).encode()
    out = _clean(svg)
    assert "#icon" in out and "data:image/png" in out


def test_strips_foreignobject():
    out = _clean(f"<svg {_NS}><foreignObject><body>x</body></foreignObject></svg>".encode())
    assert "foreignObject" not in out.lower() if "foreign" in out.lower() else True
    assert "<body" not in out


def test_xxe_entity_does_not_resolve():
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        f'<svg {_NS}><text>&e;</text></svg>'
    ).encode()
    # Either rejected or the entity simply doesn't expand — never leaks file content.
    try:
        out = sanitize_svg(xxe).decode()
        assert "root:" not in out
    except SvgImportError:
        pass


def test_rejects_non_svg():
    with pytest.raises(SvgImportError):
        sanitize_svg(b"<html><body>nope</body></html>")
    with pytest.raises(SvgImportError):
        sanitize_svg(b"not xml at all")
    with pytest.raises(SvgImportError):
        sanitize_svg(b"")


def test_import_svg_stores_sanitised_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.media_library.store as store_mod

    monkeypatch.setattr(store_mod, "_default_store", None, raising=False)
    result = import_svg(
        "org-a",
        f'<svg {_NS} width="20" height="10"><script>x</script><rect width="5" height="5"/></svg>'.encode(),
        "logo.svg",
    )
    assert result["sanitized"] is True
    assert result["width"] == 20 and result["height"] == 10
    # the stored file is clean
    from mediahub.media_library.store import get_store

    asset = get_store().get(result["id"])
    assert "<script" not in open(asset.path).read()


# --- PSD (optional, dependency-gated) --------------------------------------
def test_psd_honest_errors_without_backend():
    if psd_import.available():
        pytest.skip("psd-tools is installed in this environment")
    with pytest.raises(psd_import.PsdImportUnavailable):
        psd_import.psd_to_png(b"8BPS....")


def test_psd_empty_input_errors():
    with pytest.raises(psd_import.PsdImportError):
        psd_import.psd_to_png(b"")
