"""F6 — the layout scorer wired into ``render_brief``.

Two layers, mirroring the F3 archetype-lint split:

* **Browserless (always run):** capture the composed HTML by monkeypatching
  ``render_html_to_png`` (never launching Chromium) and drive the scorer with a
  monkeypatched ``measure_html_geometry`` that returns synthetic geometry. This
  pins the invariants that matter without a browser: OFF never scores; a scorer
  that can't improve (measurement unavailable / all candidates disqualified)
  degrades to the director's pack **byte-identically**; and a measured win
  swaps the composed HTML to exactly the winning pack's markup.

* **Chromium-gated smoke (runs when a browser is present, e.g. CI):** render a
  real card end-to-end with ``MEDIAHUB_LAYOUT_SCORE=1`` and assert the output is
  produced, deterministic (same winner → identical bytes), and collision-free.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mediahub.graphic_renderer.render as R
from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.graphic_renderer import layout_score as ls
from mediahub.graphic_renderer import style_packs as sp
from mediahub.media_requirements.evaluator import EvaluationResult

_V2_ARCHETYPE = "big_number_dominant"  # a stable v2 archetype (see archetypes.list_archetypes)
_PACK_A = "bottom_fade-none-none-bold"
_PACK_B = "corner_fade-none-none-bold"


@pytest.fixture(autouse=True)
def _force_v2(monkeypatch):
    """F6 only acts on v2 archetypes (packs). The suite-wide autouse fixture
    pins the legacy v1 engine, so every F6 render test opts into the production
    default (v2) — this runs after the conftest pin, so it wins the env var."""
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")


def _brand():
    return BrandKit(
        profile_id="f6",
        display_name="Riverside Swimming Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="RSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=_V2_ARCHETYPE,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(pack=_PACK_A, mood=""):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Mia Cox",
            "event_name": "200m Individual Medley",
            "result_time": "2:18.07",
            "raw_facts": {"drop_seconds": 2.4},
        },
    }
    b = gen_brief(
        item,
        _eval(),
        _brand(),
        profile_id="f6",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=0,
    )
    b.layout_template = _V2_ARCHETYPE
    b.style_pack = pack
    b.mood = mood
    return b


def _capture_html(monkeypatch, tmp_path, brief):
    """Compose the card's HTML without a browser (patched render_html_to_png)."""
    captured: dict = {}

    def _fake_png(html, output_path, size):  # noqa: ARG001
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350))
    return captured["html"]


def _compose_only(brief):
    """The exact HTML render_brief would compose for this brief (no scoring)."""
    return R.render_brief(brief, output_dir=Path("."), size=(1080, 1350), _html_only=True)


# Synthetic geometries: a clean, well-balanced card and a corner-jammed one.
_CLEAN = {
    "W": 1080,
    "H": 1350,
    "boxes": [
        {
            "kind": "text",
            "x": 440,
            "y": 600,
            "w": 200,
            "h": 120,
            "text": "MIA COX",
            "fontPx": 96,
            "weight": 800,
            "bgFill": False,
            "eff": 1.0,
        },
        {
            "kind": "text",
            "x": 440,
            "y": 760,
            "w": 200,
            "h": 40,
            "text": "MEDLEY",
            "fontPx": 28,
            "weight": 600,
            "bgFill": False,
            "eff": 1.0,
        },
    ],
}
_DRIFT = {
    "W": 1080,
    "H": 1350,
    "boxes": [
        {
            "kind": "text",
            "x": 10,
            "y": 10,
            "w": 200,
            "h": 120,
            "text": "MIA COX",
            "fontPx": 96,
            "weight": 800,
            "bgFill": False,
            "eff": 1.0,
        },
        {
            "kind": "text",
            "x": 10,
            "y": 140,
            "w": 200,
            "h": 40,
            "text": "MEDLEY",
            "fontPx": 28,
            "weight": 600,
            "bgFill": False,
            "eff": 1.0,
        },
    ],
}


# --------------------------------------------------------------------------- #
# Browserless invariants
# --------------------------------------------------------------------------- #


def test_off_path_never_invokes_the_scorer(monkeypatch, tmp_path):
    monkeypatch.delenv("MEDIAHUB_LAYOUT_SCORE", raising=False)

    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("F6 measured with the flag OFF")

    monkeypatch.setattr(R, "measure_html_geometry", _boom)
    html = _capture_html(monkeypatch, tmp_path, _brief())
    assert html and "<body" in html.lower()


def test_degrade_is_byte_identical_to_off(monkeypatch, tmp_path):
    brief_off = _brief()
    html_off = _capture_html(monkeypatch, tmp_path, brief_off)

    # Flag ON, but measurement is unavailable → choose() degrades to the current
    # pack → the composed HTML must be byte-identical to the flag-off render.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: None)
    html_degraded = _capture_html(monkeypatch, tmp_path, _brief())
    assert html_degraded == html_off


def test_all_disqualified_is_byte_identical_to_off(monkeypatch, tmp_path):
    html_off = _capture_html(monkeypatch, tmp_path, _brief())
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    # Every candidate measured None → all disqualified → keep current.
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [None] * len(htmls))
    html_on = _capture_html(monkeypatch, tmp_path, _brief())
    assert html_on == html_off


def test_scorer_switches_to_the_measured_winner(monkeypatch, tmp_path):
    # Force a two-candidate walk [A, B] and make B measurably better.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [_DRIFT, _CLEAN])
    html_on = _capture_html(monkeypatch, tmp_path, _brief(pack=_PACK_A))

    # The composed HTML must equal what pack B composes directly — the scorer
    # swapped the director's A for the measured winner B.
    html_b = _compose_only(_brief(pack=_PACK_B))
    html_a = _compose_only(_brief(pack=_PACK_A))
    assert html_on == html_b
    assert html_on != html_a, "precondition: the two packs compose different markup"


def test_scorer_keeps_current_when_it_is_the_best(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    # A is clean, B drifts → keep A (the director's pack).
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [_CLEAN, _DRIFT])
    html_on = _capture_html(monkeypatch, tmp_path, _brief(pack=_PACK_A))
    html_a = _compose_only(_brief(pack=_PACK_A))
    assert html_on == html_a


def test_bare_pack_card_is_untouched_on_or_off(monkeypatch, tmp_path):
    # A brief with no style_pack has nothing to score → byte-identical on==off.
    html_off = _capture_html(monkeypatch, tmp_path, _brief(pack=""))
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("scored a bare-pack card")

    monkeypatch.setattr(R, "measure_html_geometry", _boom)
    html_on = _capture_html(monkeypatch, tmp_path, _brief(pack=""))
    assert html_on == html_off


# --------------------------------------------------------------------------- #
# Chromium-gated end-to-end smoke
# --------------------------------------------------------------------------- #


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _chromium_ok(), reason="chromium unavailable")
def test_end_to_end_render_is_deterministic_and_collision_free(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    # Keep the pool out of the picture so each render is a clean one-shot.
    monkeypatch.setenv("MEDIAHUB_RENDER_POOL", "0")

    out1 = tmp_path / "r1"
    out2 = tmp_path / "r2"
    res1 = R.render_brief(_brief(), output_dir=out1, size=(1080, 1350))
    res2 = R.render_brief(_brief(), output_dir=out2, size=(1080, 1350))

    p1 = out1 / "feed_portrait.png"
    p2 = out2 / "feed_portrait.png"
    assert p1.exists() and p1.stat().st_size > 1000
    # Deterministic: the same brief scores the same winner → identical HTML and
    # identical bytes on disk.
    assert res1.html == res2.html, "F6 winner is non-deterministic"
    assert p1.read_bytes() == p2.read_bytes(), "F6 render is non-deterministic"

    # The shipped card must be collision-free: re-measure the winner's own HTML
    # (res.html is the fully-composed winning markup) and assert the hard gate
    # passes.
    geom = R.measure_html_geometry([res1.html], (1080, 1350), output_dir=tmp_path)
    assert geom and geom[0] is not None
    assert ls.score_geometry(geom[0], archetype=_V2_ARCHETYPE)["disqualified"] is False
