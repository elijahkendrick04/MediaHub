"""Multi-athlete collage / relay placement engine (roadmap G1.2).

Exercises ``graphic_renderer.collage`` — the deterministic, browser-free engine
that composites 2-4 cutouts into one balanced frame:

  * determinism — same args (and seed) always yield the identical plan / HTML;
  * balance — the weighted centroid sits on the midline for every arrangement,
    including the deliberately asymmetric size profiles (the recentring works);
  * bounds + non-degeneracy — subjects stay in frame, spread out, stand on a
    shared baseline, and front-to-back z-order is sane;
  * count clamping to 1..MAX_SUBJECTS;
  * the HTML compositor — one figure per subject, injection-safe sources,
    escaped names, empty for < 2 cutouts, byte-stable output;
  * brief integration — people-photo filtering, de-dup, cutout preference, the
    seed derivation, and the "< 2 photos → no block" honesty rule.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediahub.graphic_renderer import collage as C


# --------------------------------------------------------------------------- #
# plan_collage — determinism
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7, 41])
def test_plan_is_deterministic(n, seed):
    a = C.plan_collage(n, width=1080, height=1350, seed=seed)
    b = C.plan_collage(n, width=1080, height=1350, seed=seed)
    assert a == b
    assert a.count == n
    assert len(a.subjects) == n


def test_plan_seed_selects_variants():
    # Distinct seeds walk the variant table for a given count (n=4 has 3).
    layouts = {C.plan_collage(4, seed=s).layout for s in range(6)}
    assert len(layouts) >= 2, layouts


def test_count_is_clamped_to_supported_range():
    assert C.plan_collage(0).count == 1
    assert C.plan_collage(-5).count == 1
    assert C.plan_collage(99).count == C.MAX_SUBJECTS == 4


# --------------------------------------------------------------------------- #
# plan_collage — balance (the defining "balanced frame" property)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_every_arrangement_is_weight_balanced(n, seed):
    plan = C.plan_collage(n, seed=seed)
    # Weighted centroid sits on the vertical midline — equal visual weight
    # either side. Tolerance covers 4-dp coordinate rounding.
    assert abs(plan.centroid() - 0.5) < 0.01, (plan.layout, plan.centroid())


def test_asymmetric_profiles_are_recentred():
    # The variants whose size profile is deliberately lopsided still balance —
    # proves the centroid correction, not just symmetric-by-luck placement.
    asymmetric = {
        2: ("duo_lead", 1),
        3: ("trio_lead_left", 2),
        4: ("quad_wave", 2),
    }
    for n, (name, seed) in asymmetric.items():
        plan = C.plan_collage(n, seed=seed)
        assert plan.layout == name, (n, plan.layout)
        # Subjects carry genuinely different sizes (asymmetric profile)…
        scales = {s.scale for s in plan.subjects}
        assert len(scales) > 1, name
        # …yet the composition is balanced.
        assert abs(plan.centroid() - 0.5) < 0.01, (name, plan.centroid())


# --------------------------------------------------------------------------- #
# plan_collage — bounds, spread, baseline, z-order, facing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_subjects_stay_in_frame(n, seed):
    plan = C.plan_collage(n, seed=seed)
    for s in plan.subjects:
        assert C._CX_MIN <= s.cx <= C._CX_MAX, s
        assert 0.0 < s.scale <= 1.0, s
        assert s.bottom >= 0.0, s
        # Head stays within a sliver of the top (a small bleed is allowed).
        assert s.top <= 1.05, s


@pytest.mark.parametrize("n", [2, 3, 4])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_subjects_spread_and_are_distinct(n, seed):
    plan = C.plan_collage(n, seed=seed)
    xs = [s.cx for s in plan.subjects]
    # No two subjects stack on the same column…
    assert len(set(xs)) == n, xs
    # …and they meaningfully fan across the frame (not a tight clump).
    assert plan.spread() > 0.35, plan.spread()


def test_single_subject_is_centred():
    plan = C.plan_collage(1, seed=3)
    assert plan.subjects[0].cx == 0.5
    assert plan.centroid() == 0.5
    assert plan.spread() == 0.0


def test_central_subjects_paint_in_front():
    # An odd lineup: the middle subject overlaps the flanks (higher z-index).
    plan = C.plan_collage(3, seed=0)
    zs = [s.z for s in plan.subjects]
    assert zs[1] > zs[0] and zs[1] > zs[2], zs


def test_face_in_variant_mirrors_outer_subjects():
    # duo_face_off (seed 0) turns the left subject inward, leaves the right.
    plan = C.plan_collage(2, seed=0)
    assert plan.layout == "duo_face_off"
    assert plan.subjects[0].flip is True
    assert plan.subjects[1].flip is False
    # The non-face-in quad keeps everyone upright-facing.
    quad = C.plan_collage(4, seed=0)
    assert quad.layout == "quad_lineup"
    assert all(s.flip is False for s in quad.subjects)


def test_tilt_is_symmetric_about_the_centre():
    # A palindromic trio tilts the ends in opposite directions, middle upright.
    plan = C.plan_collage(3, seed=0)  # trio_pyramid
    assert plan.subjects[1].rotate == 0.0
    assert plan.subjects[0].rotate == -plan.subjects[2].rotate
    assert plan.subjects[0].rotate != 0.0


# --------------------------------------------------------------------------- #
# render_collage — HTML compositor
# --------------------------------------------------------------------------- #

_IMG = [f"data:image/png;base64,AAA{i}" for i in range(4)]


def test_render_needs_two_subjects():
    assert C.render_collage([]) == ""
    assert C.render_collage([_IMG[0]]) == ""


@pytest.mark.parametrize("k", [2, 3, 4])
def test_render_emits_one_figure_per_subject(k):
    html = C.render_collage(_IMG[:k], seed=1)
    assert html.count("<figure") == k
    assert f'data-collage-count="{k}"' in html
    assert "data-collage-layout=" in html
    for src in _IMG[:k]:
        assert f'src="{src}"' in html


def test_render_caps_at_max_subjects():
    extra = _IMG + ["data:image/png;base64,EXTRA"]
    html = C.render_collage(extra, seed=0)
    assert html.count("<figure") == C.MAX_SUBJECTS


def test_render_is_byte_stable():
    a = C.render_collage(_IMG[:3], width=1080, height=1350, seed=2)
    b = C.render_collage(_IMG[:3], width=1080, height=1350, seed=2)
    assert a == b


def test_render_rejects_unsafe_sources():
    # A source that could break out of src="…" is dropped, not injected.
    bad = 'data:image/png;base64,AAA" onerror="alert(1)'
    html = C.render_collage([bad, _IMG[1], _IMG[2]], seed=0)
    assert "onerror" not in html
    assert html.count("<figure") == 2  # only the two safe sources
    # All-unsafe collapses to nothing rather than a one-subject "collage".
    assert C.render_collage([bad, "<script>"], seed=0) == ""


def test_render_escapes_names():
    html = C.render_collage(
        _IMG[:2], seed=0, names=["<b>Eira</b>", "Ana & Mai"]
    )
    assert "<b>Eira</b>" not in html
    assert "&lt;b&gt;Eira&lt;/b&gt;" in html
    assert "Ana &amp; Mai" in html


# --------------------------------------------------------------------------- #
# Brief integration — people-photo resolution
# --------------------------------------------------------------------------- #


def _asset(asset_type, path, cutout=None):
    return SimpleNamespace(type=asset_type, path=path, cutout_path=cutout)


class _FakeStore:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, asset_id):
        return self._m.get(asset_id)


def test_resolve_filters_to_people_and_prefers_cutout():
    store = _FakeStore(
        {
            "a1": _asset("athlete_action", "/u/a1.jpg", cutout="/u/a1_cut.png"),
            "v1": _asset("venue_photo", "/u/v1.jpg"),  # excluded
            "lg": _asset("logo", "/u/logo.png"),  # excluded
            "a2": _asset("athlete_headshot", "/u/a2.png"),  # no cutout → raw
            "t1": _asset("team_photo", "/u/team.jpg"),
        }
    )
    brief = SimpleNamespace(
        sourced_asset_ids=["a1", "v1", "lg", "a2", "t1"], profile_id="p"
    )
    paths = C._resolve_people_paths(brief, store, C.MAX_SUBJECTS)
    assert paths == ["/u/a1_cut.png", "/u/a2.png", "/u/team.jpg"]


def test_resolve_dedups_and_caps():
    store = _FakeStore(
        {f"a{i}": _asset("athlete_action", f"/u/dup.png") for i in range(6)}
    )
    brief = SimpleNamespace(sourced_asset_ids=[f"a{i}" for i in range(6)])
    # Same path repeated → de-duplicated to one.
    assert C._resolve_people_paths(brief, store, C.MAX_SUBJECTS) == ["/u/dup.png"]


def test_resolve_override_paths_win():
    brief = SimpleNamespace(
        collage_image_paths=["/x/1.png", "/x/2.png", "/x/1.png", "/x/3.png"],
        sourced_asset_ids=["ignored"],
    )
    # Explicit override is used verbatim (de-duped, capped), store untouched.
    assert C._resolve_people_paths(brief, None, C.MAX_SUBJECTS) == [
        "/x/1.png",
        "/x/2.png",
        "/x/3.png",
    ]


def test_resolve_empty_when_no_assets():
    assert C._resolve_people_paths(SimpleNamespace(), None, 4) == []
    assert C._resolve_people_paths(SimpleNamespace(sourced_asset_ids=[]), None, 4) == []


def test_collage_images_for_brief_encodes(monkeypatch):
    # Stub the renderer helpers so resolution/ordering is asserted without I/O.
    import mediahub.graphic_renderer.render as R

    monkeypatch.setattr(R, "_maybe_cut_out_athlete", lambda p, profile_id="d": p)
    monkeypatch.setattr(R, "_img_to_data_uri", lambda p: f"data:uri:{p}")

    store = _FakeStore(
        {
            "a1": _asset("athlete_action", "/u/a1.png"),
            "a2": _asset("team_photo", "/u/a2.png"),
        }
    )
    brief = SimpleNamespace(sourced_asset_ids=["a1", "a2"], profile_id="p")
    uris = C.collage_images_for_brief(brief, store=store)
    assert uris == ["data:uri:/u/a1.png", "data:uri:/u/a2.png"]


def test_collage_block_for_brief_requires_two(monkeypatch):
    import mediahub.graphic_renderer.render as R

    monkeypatch.setattr(R, "_maybe_cut_out_athlete", lambda p, profile_id="d": p)
    monkeypatch.setattr(R, "_img_to_data_uri", lambda p: f"data:uri:{p}")

    one = SimpleNamespace(
        sourced_asset_ids=["a1"], profile_id="p", variation_seed=5
    )
    one_store = _FakeStore({"a1": _asset("athlete_action", "/u/a1.png")})
    assert C.collage_block_for_brief(one, store=one_store) == ""

    two = SimpleNamespace(
        sourced_asset_ids=["a1", "a2"], profile_id="p", variation_seed=5
    )
    two_store = _FakeStore(
        {
            "a1": _asset("athlete_action", "/u/a1.png"),
            "a2": _asset("athlete_action", "/u/a2.png"),
        }
    )
    block = C.collage_block_for_brief(two, store=two_store)
    assert "rc-collage" in block and block.count("<figure") == 2


# --------------------------------------------------------------------------- #
# Seed derivation
# --------------------------------------------------------------------------- #


def test_seed_prefers_variation_seed():
    assert C.collage_seed_for_brief(SimpleNamespace(variation_seed=12)) == 12
    assert C.collage_seed_for_brief(SimpleNamespace(variation_seed=-3)) == 3


def test_seed_falls_back_to_stable_id_hash():
    b1 = SimpleNamespace(variation_seed=0, content_item_id="card-A")
    b2 = SimpleNamespace(variation_seed=0, content_item_id="card-B")
    s1 = C.collage_seed_for_brief(b1)
    assert s1 == C.collage_seed_for_brief(b1)  # stable
    assert s1 >= 0
    assert s1 != C.collage_seed_for_brief(b2)  # spreads across cards


def test_seed_never_raises_on_bare_brief():
    # Missing/garbage attributes degrade to a usable seed, never an exception.
    assert C.collage_seed_for_brief(SimpleNamespace()) >= 0
    assert C.collage_seed_for_brief(SimpleNamespace(variation_seed="x")) >= 0
