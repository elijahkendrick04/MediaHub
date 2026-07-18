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
# Elevation invariants: winner persistence, format coherence, canonical
# geometry, mesh-background re-sync, always-on explainability note
# --------------------------------------------------------------------------- #


def test_winner_is_persisted_onto_the_callers_brief(monkeypatch, tmp_path):
    # A measured switch must reach the CALLER's brief — that one write is what
    # keeps the stored brief, later formats, and the motion mirror (which reads
    # brief.style_pack for its pack overlay / ground / density register) on the
    # pack the still actually shipped.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [_DRIFT, _CLEAN])
    b = _brief(pack=_PACK_A)
    _capture_html(monkeypatch, tmp_path, b)
    assert b.style_pack == _PACK_B, "the winning pack must persist on the caller's brief"
    rec = getattr(b, "layout_score", None)
    assert rec and rec["changed"] and rec["winner"] == _PACK_B
    assert rec.get("decided_at", "").startswith("feed_portrait@")
    assert rec.get("signature_pack_stale") is True
    assert getattr(b, "_layout_scored", False) is True


def test_second_render_reuses_the_decision(monkeypatch, tmp_path):
    # One decision per card: after the first render decides, a second render of
    # the SAME brief (another format of the card) must reuse the stored record
    # rather than re-measuring — so all cuts of a card agree by construction.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    calls = {"n": 0}

    def _measure_once(htmls, size, **kw):
        calls["n"] += 1
        return [_DRIFT, _CLEAN]

    monkeypatch.setattr(R, "measure_html_geometry", _measure_once)
    b = _brief(pack=_PACK_A)
    _capture_html(monkeypatch, tmp_path, b)
    assert calls["n"] == 1 and b.style_pack == _PACK_B

    def _boom(*a, **k):  # pragma: no cover - must not re-measure
        raise AssertionError("F6 re-measured an already-decided brief")

    monkeypatch.setattr(R, "measure_html_geometry", _boom)
    captured: dict = {}

    def _fake_png(html, output_path, size):  # noqa: ARG001
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(b, output_dir=tmp_path, size=(1080, 1920), format_name="story")
    assert b.style_pack == _PACK_B, "the stored decision must survive the second format"


def test_decision_is_made_at_canonical_geometry(monkeypatch, tmp_path):
    # Whatever cut is being rendered, candidates are measured at the v2
    # certification anchor — so every format computes the identical winner.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    seen = {}

    def _measure(htmls, size, **kw):
        seen["size"] = size
        return [_CLEAN, _DRIFT]

    monkeypatch.setattr(R, "measure_html_geometry", _measure)
    captured: dict = {}

    def _fake_png(html, output_path, size):  # noqa: ARG001
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(
        _brief(pack=_PACK_A), output_dir=tmp_path, size=(1080, 1920), format_name="story"
    )
    assert seen["size"] == ls.DECISION_SIZE


def test_swap_onto_a_mesh_pack_resyncs_background(monkeypatch, tmp_path):
    # The generator keys background_style='gradient_mesh' to a mesh-ground pack
    # at generation time; a render-time swap must re-run that sync so the mesh
    # engine paints (or stops painting) coherently with the winning pack.
    mesh_pack = "gradient_mesh-none-none-standard"
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, mesh_pack])
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [_DRIFT, _CLEAN])
    b = _brief(pack=_PACK_A)
    b.background_style = "water"
    _capture_html(monkeypatch, tmp_path, b)
    assert b.style_pack == mesh_pack
    assert b.background_style == "gradient_mesh", "mesh coupling must follow the winning pack"


def test_switch_lands_in_safety_notes(monkeypatch, tmp_path):
    # Always-on explainability: a pack switch must be visible on the visual's
    # safety-notes trail even with the opt-in G1.30 sidecar off.
    monkeypatch.setenv("MEDIAHUB_LAYOUT_SCORE", "1")
    monkeypatch.setattr(ls, "candidate_pack_ids", lambda brief, *a, **k: [_PACK_A, _PACK_B])
    monkeypatch.setattr(R, "measure_html_geometry", lambda htmls, size, **kw: [_DRIFT, _CLEAN])

    def _fake_png(html, output_path, size):  # noqa: ARG001
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    res = R.render_brief(_brief(pack=_PACK_A), output_dir=tmp_path, size=(1080, 1350))
    notes = list(res.visual.safety_notes or [])
    assert any("layout scorer switched" in n for n in notes), notes


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
