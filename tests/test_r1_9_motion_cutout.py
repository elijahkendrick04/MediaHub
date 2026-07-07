"""R1.9 — Cutout-layer compositing in motion.

Two halves, mirroring the build:

  * ``visual/motion.py`` asset prep — ``_cutout_data_uri_for_brief`` turns the
    brief's sourced photo into an alpha-cutout PNG data URI using the same
    configured background remover the still renderer uses, caches it per source
    photo, and is honest on every miss (no brief / no-photo / no usable remover
    / provider error → ``""``, never a fake passthrough rectangle, never a
    failed render). The cut rides into the card props as ``cutoutSrc`` and is
    recorded on the explainability manifest as ``has_cutout``.

  * ``sprint/layers/cutout.tsx`` — the additive overlay that composites the cut
    as a parallax FOREGROUND plane. Validated at the source-contract level
    (no Node needed): it default-exports the layer contract, strictly no-ops
    without a prepared cut, animates as a pure function of the frame, keeps the
    ambient parallax displacement small, and is picked up by the parity corpus.

No Node render happens here — the dev sandbox has no rembg, so the populated
path is exercised with a stub remover; the source contracts read the TSX as
text, exactly like ``tests/test_motion_v2_parity.py``.
"""
from __future__ import annotations

import re
import types
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion


BRAND = BrandKit(
    profile_id="cutout-r19",
    display_name="Cutout SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="CSC",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-cut-{i}",
        "swim_id": f"swim-cut-{i}",
        "achievement": {
            "swim_id": f"swim-cut-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Cutout Invitational",
    }


def _layer_src() -> str:
    return (
        motion.REMOTION_DIR
        / "src"
        / "compositions"
        / "sprint"
        / "layers"
        / "cutout.tsx"
    ).read_text()


def _storycard_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


# ---------------------------------------------------------------------------
# Stub-remover fixture: a real source photo + a provider that writes alpha
# ---------------------------------------------------------------------------


class _StubRemover:
    """A background remover that genuinely produces a plausible alpha matte.

    The subject is a single bottom-anchored blob (~28% coverage, one connected
    component, bottom-edge contact only) so it PASSES the M14 matte gate the
    parity pass wired into motion's cutout resolution — a full-rectangle
    passthrough would now be honestly rejected (see the gate tests below).
    """

    def __init__(self) -> None:
        self.calls = 0
        self.available = True

    def is_available(self) -> bool:
        return self.available

    def remove(self, src_path: str, dst_path: str) -> str:
        self.calls += 1
        from PIL import Image, ImageDraw

        im = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        # A person-ish silhouette: torso column touching the bottom edge.
        draw.rectangle([200, 320, 400, 800], fill=(20, 60, 140, 255))
        draw.ellipse([230, 180, 370, 340], fill=(20, 60, 140, 255))
        im.save(dst_path, "PNG")
        return dst_path


class _PassthroughRemover:
    """A dishonest 'remover' that returns the whole opaque rectangle."""

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def remove(self, src_path: str, dst_path: str) -> str:
        self.calls += 1
        from PIL import Image

        Image.new("RGBA", (600, 800), (20, 60, 140, 255)).save(dst_path, "PNG")
        return dst_path


@pytest.fixture
def photo_brief(tmp_path, monkeypatch):
    """A brief dict whose sourced asset resolves to a real on-disk photo,
    plus a patched ``get_bg_remover`` returning a controllable stub."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from PIL import Image

    src = tmp_path / "athlete.jpg"
    Image.new("RGB", (600, 800), (20, 60, 140)).save(src, "JPEG")

    asset = types.SimpleNamespace(path=str(src))
    store = types.SimpleNamespace(get=lambda aid: asset)
    remover = _StubRemover()

    monkeypatch.setattr("mediahub.media_library.store.get_store", lambda: store)
    monkeypatch.setattr("mediahub.media_ai.providers.get_bg_remover", lambda: remover)

    brief = {"sourced_asset_ids": ["a1"], "photo_treatment": "cutout"}
    return types.SimpleNamespace(brief=brief, src=src, remover=remover, tmp=tmp_path)


# ---------------------------------------------------------------------------
# Asset prep — honest misses
# ---------------------------------------------------------------------------


def test_cutout_empty_without_brief():
    assert motion._cutout_data_uri_for_brief(None) == ""
    assert motion._cutout_data_uri_for_brief({}) == ""


def test_cutout_empty_for_no_photo_treatment():
    assert (
        motion._cutout_data_uri_for_brief(
            {"sourced_asset_ids": ["a1"], "photo_treatment": "no-photo"}
        )
        == ""
    )


def test_card_props_without_brief_have_empty_cutout():
    props = motion._card_to_props(_card(1), variation_seed=3)
    assert "cutoutSrc" in props
    assert props["cutoutSrc"] == ""


def test_card_props_with_brief_but_no_sourced_photo_have_empty_cutout():
    props = motion._card_to_props(
        _card(1), variation_seed=3, brief={"background_style": "dots"}
    )
    assert props["cutoutSrc"] == ""


# ---------------------------------------------------------------------------
# Asset prep — populated path, caching, determinism
# ---------------------------------------------------------------------------


def test_cutout_data_uri_real_photo_with_remover(photo_brief):
    uri = motion._cutout_data_uri_for_brief(photo_brief.brief)
    assert uri.startswith("data:image/png;base64,")
    assert len(uri) > 200  # a real inlined PNG, not a stub token
    assert photo_brief.remover.calls == 1


def test_cutout_is_cached_per_source_photo(photo_brief):
    a = motion._cutout_data_uri_for_brief(photo_brief.brief)
    b = motion._cutout_data_uri_for_brief(photo_brief.brief)
    assert a == b  # deterministic
    assert photo_brief.remover.calls == 1  # the second call hit the PNG cache


def test_cutout_flows_into_card_props_and_manifest(photo_brief):
    props = motion._card_to_props(
        _card(1), variation_seed=2, brief=photo_brief.brief, brand_kit=BRAND
    )
    assert props["cutoutSrc"].startswith("data:image/png;base64,")
    axes = motion._card_manifest_axes(props)
    assert axes["has_cutout"] is True


# ---------------------------------------------------------------------------
# Asset prep — honesty + robustness (a cutout must never fake or fail)
# ---------------------------------------------------------------------------


def test_cutout_honest_when_remover_unavailable(photo_brief):
    """An unavailable remover would passthrough the whole rectangle — we'd
    rather show no cutout than a flat photo masquerading as one."""
    photo_brief.remover.available = False
    assert motion._cutout_data_uri_for_brief(photo_brief.brief) == ""
    assert photo_brief.remover.calls == 0


def test_cutout_never_raises_on_provider_error(photo_brief, monkeypatch):
    """A provider that explodes mid-cut must degrade to "" — never bubble up
    and fail the motion render."""

    class _Boom:
        def is_available(self):
            return True

        def remove(self, s, d):
            raise RuntimeError("rembg model exploded")

    monkeypatch.setattr("mediahub.media_ai.providers.get_bg_remover", lambda: _Boom())
    assert motion._cutout_data_uri_for_brief(photo_brief.brief) == ""


# ---------------------------------------------------------------------------
# Matte-gate parity (still ↔ motion): the SAME M14 gate the still runs
# ---------------------------------------------------------------------------


def test_matte_gate_rejects_a_passthrough_rectangle(photo_brief, monkeypatch):
    """A full-rectangle 'cutout' (the background never removed) is the exact
    matte the still's M14 gate rejects — motion must reject it identically and
    fall back to the original-photo path, never a fake silhouette."""
    remover = _PassthroughRemover()
    monkeypatch.setattr("mediahub.media_ai.providers.get_bg_remover", lambda: remover)
    assert motion._cutout_data_uri_for_brief(photo_brief.brief) == ""
    assert remover.calls == 1


def test_matte_gate_rejection_is_measured_once(photo_brief, monkeypatch):
    """A rejection persists a .rejected.json marker beside the would-be cut,
    so a bad matte is measured once — not re-matted every render (the still's
    exact marker behaviour)."""
    remover = _PassthroughRemover()
    monkeypatch.setattr("mediahub.media_ai.providers.get_bg_remover", lambda: remover)
    assert motion._cutout_data_uri_for_brief(photo_brief.brief) == ""
    assert motion._cutout_data_uri_for_brief(photo_brief.brief) == ""
    assert remover.calls == 1  # the second call short-circuits on the marker
    markers = list((motion._cutout_cache_dir()).glob("*.rejected.json"))
    assert markers, "the rejection must be persisted beside the would-be cut"


def test_cutout_for_brief_returns_the_cut_path(photo_brief):
    """The full-res cut path rides along for the band_break placement maths
    (render._band_top_fraction) so both surfaces break at identical pixels."""
    uri, cut_path = motion._cutout_for_brief(photo_brief.brief)
    assert uri.startswith("data:image/png;base64,")
    assert cut_path is not None and Path(cut_path).exists()


def test_manifest_records_has_cutout_false_without_photo():
    props = motion._card_to_props(_card(1))
    assert motion._card_manifest_axes(props)["has_cutout"] is False


# ---------------------------------------------------------------------------
# Cache-key sensitivity (the motion-craft cache gotcha): a prepared cut must
# change the render hash so a cutout render can't serve a stale silent file.
# ---------------------------------------------------------------------------


def test_cutout_changes_the_render_cache_key(photo_brief):
    with_cut = motion._card_to_props(
        _card(1), variation_seed=2, brief=photo_brief.brief, brand_kit=BRAND
    )
    without = dict(with_cut)
    without["cutoutSrc"] = ""
    h_with = motion._content_hash({"card": with_cut}, kind="story")
    h_without = motion._content_hash({"card": without}, kind="story")
    assert h_with != h_without


# ---------------------------------------------------------------------------
# TSX source contracts — the cutout sprint layer
# ---------------------------------------------------------------------------


def test_cutout_layer_file_exists_and_exports_the_contract():
    src = _layer_src()
    # Default-exports the layer registry contract { Layer, order }.
    assert re.search(r"export default \{\s*Layer,\s*order:", src)
    # Imports its types from the one place every sprint module does.
    assert 'from "../registry"' in src


def test_cutout_layer_is_a_strict_noop_without_a_cut():
    src = _layer_src()
    assert "card.cutoutSrc" in src
    # The empty-cut guard returns null → byte-identical to pre-R1.9.
    assert re.search(r"if \(!cutout\)\s*\{[^}]*return null", src, re.S)


def test_cutout_layer_is_a_pure_function_of_the_frame():
    src = _layer_src()
    assert "interpolate(" in src
    assert "useVideoConfig" in src
    # Deterministic: no wallclock, no RNG (the parity-breaking sins). Match the
    # call forms so the docstring that *names* these to forbid them is ignored.
    assert "Math.random(" not in src
    assert "Date.now(" not in src
    assert "new Date(" not in src


def test_cutout_layer_uses_seeded_orthogonal_parallax():
    src = _layer_src()
    # Frame-derived ambient drift/float (the parallax), seed-keyed direction.
    assert "Math.sin" in src and "Math.cos" in src
    assert "variationSeed" in src
    # Horizontal drift + vertical float = motion orthogonal to the background's
    # vertical drift, which is what makes the planes read as separate depths.
    assert "driftX" in src and "floatY" in src


def test_cutout_layer_keeps_ambient_displacement_small():
    """motion-craft: keep the parallax displacement small (≤ 24px) so the cut
    edge never travels far enough to reveal background it cannot show."""
    src = _layer_src()
    amps = [int(m) for m in re.findall(r"Math\.(?:sin|cos)\([^)]*\)\s*\*\s*(\d+)", src)]
    assert amps, "expected frame-derived sinusoid amplitudes in the layer"
    for a in amps:
        assert a <= 24, f"ambient parallax amplitude {a}px exceeds the 24px bound"


def test_cutout_layer_mirrors_left_side_like_the_still():
    # Parity with render.py _composition_overrides_css: a left-standing subject
    # faces into the card via scaleX(-1).
    assert "scaleX(-1)" in _layer_src()


def test_cutout_layer_grounds_with_brand_role_not_an_invented_hex():
    src = _layer_src()
    # The seating shadow uses the resolved ground role, never a hardcoded hex.
    assert "roles.ground" in src
    assert "drop-shadow" in src


# ---------------------------------------------------------------------------
# Wiring: schema field + parity corpus + studio default
# ---------------------------------------------------------------------------


def test_card_schema_declares_cutout_src():
    src = _storycard_src()
    assert re.search(r"cutoutSrc:\s*z\.string\(\)\.default\(\"\"\)", src)


def test_cutout_layer_is_in_the_motion_parity_corpus():
    """The parity scan unions StoryCard.tsx with every sprint file, so a
    registered layer counts as a real execution path. Prove the cutout layer
    is part of that corpus (else a future drift check would miss it)."""
    comp = motion.REMOTION_DIR / "src" / "compositions"
    sprint_files = [p for p in (comp / "sprint").rglob("*") if p.suffix in {".ts", ".tsx"}]
    assert any(p.name == "cutout.tsx" for p in sprint_files)


def test_root_default_card_lists_cutout_src():
    """Root.tsx's sample card lists every field; cutoutSrc must be present so
    the studio preview and `tsc` stay valid."""
    root = (motion.REMOTION_DIR / "src" / "Root.tsx").read_text()
    assert "cutoutSrc:" in root
