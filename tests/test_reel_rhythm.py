"""R1.12 — Reel beat-rhythm & duration customisation.

Per-card beat weights + custom cover/outro durations, the build targets being
``MeetReel.tsx``'s beat-carving region (sole owner) and ``reel_duration_for``
in ``visual/motion.py`` (plus the helpers that thread a caller's rhythm through
both render engines and the reel route).

The non-negotiable spine of every test here: **a default (uncustomised) reel is
byte-identical to before this feature existed** — same duration maths, same
cache key, same render props, same ffmpeg segment split — so no cached reel is
invalidated. On top of that spine, the customisation must actually take effect
(duration grows with weights, bookends stretch) and must be folded into the
cache key so two rhythms never collide.

No Node/Remotion needed: ``_run_remotion`` / the ffmpeg binary are stubbed or
the TSX is read as a source contract, the same way the sibling reel suites do.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from mediahub.visual import motion
from mediahub.visual import reel_ffmpeg

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


BRAND = {
    "profile_id": "rhythm",
    "display_name": "Rhythm SC",
    "primary_colour": "#0E2A47",
    "secondary_colour": "#C9A227",
}


def _card(i: int) -> dict:
    return {
        "id": f"swim-rhythm-{i}",
        "swim_id": f"swim-rhythm-{i}",
        "achievement": {
            "swim_id": f"swim-rhythm-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Rhythm Invitational",
    }


# ===========================================================================
# reel_duration_for — back-compat spine
# ===========================================================================


@pytest.mark.parametrize("n,expected", [(1, 7.0), (2, 11.0), (3, 15.0), (4, 19.0), (5, 23.0)])
def test_default_duration_unchanged(n, expected):
    """The original 2 + 4·n + 1 formula must survive verbatim — every keyword
    defaulted, the result is exactly what it was before R1.12."""
    assert motion.reel_duration_for(n) == expected


def test_default_duration_clamps_card_count_as_before():
    assert motion.reel_duration_for(0) == 7.0  # never a zero-card reel
    assert motion.reel_duration_for(99) == 23.0  # capped at the 5-card max
    assert motion.reel_duration_for(3) == 15.0  # the historic default


def test_passing_default_values_explicitly_is_a_no_op():
    """cover=2/outro=1/per_card=4/uniform weights must reproduce the default."""
    assert motion.reel_duration_for(3, cover_sec=2.0, outro_sec=1.0, per_card_sec=4.0) == 15.0
    assert motion.reel_duration_for(3, beat_weights=[1, 1, 1]) == 15.0


# ===========================================================================
# reel_duration_for — customisation
# ===========================================================================


def test_custom_cover_and_outro_shift_the_total():
    # 3 cards: cover 3 + 4·3 + outro 2 = 17
    assert motion.reel_duration_for(3, cover_sec=3.0, outro_sec=2.0) == 17.0


def test_custom_per_card_rescales_the_card_budget():
    # 2 cards at 6s each: 2 + 6·2 + 1 = 15
    assert motion.reel_duration_for(2, per_card_sec=6.0) == 15.0


def test_beat_weights_grow_the_total_honestly():
    """A weighted card earns proportionally more seconds — the reel lengthens
    rather than silently squeezing the connective beats."""
    # weights [2,1,1] → per-card budget 4·(2+1+1) = 16 → 2 + 16 + 1 = 19
    assert motion.reel_duration_for(3, beat_weights=[2, 1, 1]) == 19.0
    # single dominant card
    assert motion.reel_duration_for(1, beat_weights=[3]) == 2 + 4 * 3 + 1  # 15


def test_duration_grows_monotonically_with_emphasis():
    base = motion.reel_duration_for(3)
    more = motion.reel_duration_for(3, beat_weights=[2, 1, 1])
    most = motion.reel_duration_for(3, beat_weights=[3, 2, 1])
    assert base < more < most


# ===========================================================================
# reel_duration_for — clamps (readable + render-safe)
# ===========================================================================


def test_bookend_and_per_card_inputs_are_clamped():
    lo_cover, hi_cover = motion.REEL_COVER_RANGE
    # Absurdly small/large requests pin to the range, never escape it.
    tiny = motion.reel_duration_for(1, cover_sec=0.0, outro_sec=0.0, per_card_sec=0.0)
    assert tiny == round(lo_cover + motion.REEL_PER_CARD_RANGE[0] + motion.REEL_OUTRO_RANGE[0], 3)


def test_total_is_pinned_to_the_render_safe_ceiling():
    """No rhythm may produce a reel longer than the worker/delayRender budget."""
    huge = motion.reel_duration_for(
        5, cover_sec=99, outro_sec=99, per_card_sec=99, beat_weights=[99, 99, 99, 99, 99]
    )
    assert huge == motion.REEL_TOTAL_RANGE[1]


def test_total_floor_protects_against_a_sub_three_second_reel():
    floor = motion.REEL_TOTAL_RANGE[0]
    assert motion.reel_duration_for(1, cover_sec=1, outro_sec=0.75, per_card_sec=1.5) >= floor


def test_fit_beat_weights_pads_truncates_and_clamps():
    lo, hi = motion.REEL_WEIGHT_RANGE
    assert motion._fit_beat_weights([2], 3) == [2.0, 1.0, 1.0]  # pad with 1.0
    assert motion._fit_beat_weights([1, 2, 3, 4], 2) == [1.0, 2.0]  # truncate
    assert motion._fit_beat_weights([99], 1) == [hi]  # clamp high
    assert motion._fit_beat_weights([0.0], 1) == [lo]  # clamp low
    assert motion._fit_beat_weights(["junk"], 1) == [1.0]  # junk → plain beat


# ===========================================================================
# normalise_reel_rhythm — parsing + the default-detection that protects caches
# ===========================================================================


def test_normalise_returns_none_for_nothing_or_defaults():
    assert motion.normalise_reel_rhythm(None, 3) is None
    assert motion.normalise_reel_rhythm({}, 3) is None
    assert motion.normalise_reel_rhythm("not-a-dict", 3) is None
    # Values equal to the defaults are still "default" — no cache-busting key.
    assert motion.normalise_reel_rhythm({"cover_sec": 2.0, "outro_sec": 1.0}, 3) is None
    assert motion.normalise_reel_rhythm({"cover": 2, "outro": 1, "per_card": 4}, 3) is None


def test_normalise_accepts_snake_camel_and_aliases():
    snake = motion.normalise_reel_rhythm({"cover_sec": 3, "outro_sec": 1.5}, 3)
    camel = motion.normalise_reel_rhythm({"coverSec": 3, "outroSec": 1.5}, 3)
    alias = motion.normalise_reel_rhythm({"cover": 3, "outro": 1.5}, 3)
    assert snake == camel == alias
    assert snake == {
        "coverSec": 3.0,
        "outroSec": 1.5,
        "perCardSec": 4.0,
        "beatWeights": [],
    }


def test_normalise_accepts_bare_beat_alias():
    """The reel route's ?beat= query param arrives as a bare 'beat' key — it
    must set the per-card seconds, not silently no-op."""
    bare = motion.normalise_reel_rhythm({"beat": 6}, 3)
    assert bare is not None
    assert bare["perCardSec"] == 6.0
    assert bare == motion.normalise_reel_rhythm({"per_card_sec": 6}, 3)


def test_normalise_explicit_weights_are_never_treated_as_default():
    """Even uniform explicit weights differ from the default top-card emphasis,
    so the rhythm must be carried (a different carve = a different render)."""
    r = motion.normalise_reel_rhythm({"weights": [1, 1, 1]}, 3)
    assert r is not None
    assert r["beatWeights"] == [1.0, 1.0, 1.0]


def test_normalise_fits_weights_to_card_count():
    r = motion.normalise_reel_rhythm({"weights": [3, 9]}, 4)
    assert r["beatWeights"] == [3.0, 4.0, 1.0, 1.0]  # 9 clamps to 4, padded to n


def test_normalise_tolerates_a_scalar_weight():
    r = motion.normalise_reel_rhythm({"weights": 2}, 2)
    assert r["beatWeights"] == [2.0, 1.0]


def test_reel_duration_kwargs_round_trip():
    r = motion.normalise_reel_rhythm({"cover": 3, "outro": 1.5}, 3)
    assert motion.reel_duration_for(3, **motion._reel_duration_kwargs(r)) == 3 + 4 * 3 + 1.5
    r2 = motion.normalise_reel_rhythm({"weights": [2, 1, 1]}, 3)
    assert motion.reel_duration_for(3, **motion._reel_duration_kwargs(r2)) == 19.0
    assert motion._reel_duration_kwargs(None) == {}


# ===========================================================================
# reel_card_beat_frames — the Python mirror of MeetReel.tsx's beat carve
# ===========================================================================


def test_beat_frames_default_carve_matches_the_tsx_maths():
    """3 cards @ the historic 15s: durationInFrames=450, cover 60, outro 30,
    transition round(30*0.35)=11, remaining 360, weights [1.25,1,1] →
    [floor(360*1.25/3.25)+11, floor(360/3.25)+11, …] = [149, 121, 121]."""
    assert motion.reel_card_beat_frames(3, 15.0, None) == [149, 121, 121]
    # A single card gets no top-card emphasis (safeCards.length > 1 in the tsx).
    # 7s → 210 frames, remaining 120 → floor(120)+11 = 131.
    assert motion.reel_card_beat_frames(1, 7.0, None) == [131]
    assert motion.reel_card_beat_frames(0, 15.0, None) == []


def test_beat_frames_honour_weights_and_bookends():
    rhythm = motion.normalise_reel_rhythm(
        {"cover": 3.0, "outro": 2.0, "per_card_sec": 5.0, "weights": [2.0, 1.0, 1.0]}, 3
    )
    total = motion.reel_duration_for(3, **motion._reel_duration_kwargs(rhythm))  # 25s
    beats = motion.reel_card_beat_frames(3, total, rhythm)
    # 750 frames, cover 90, outro 60, remaining 600, weights sum 4 →
    # [floor(600*2/4)+11, floor(600/4)+11, …] = [311, 161, 161].
    assert beats == [311, 161, 161]
    # Explicit weights are authoritative — no hidden 1.25 emphasis on top.
    flat = motion.normalise_reel_rhythm({"weights": [1.0, 1.0, 1.0]}, 3)
    total_flat = motion.reel_duration_for(3, **motion._reel_duration_kwargs(flat))
    b = motion.reel_card_beat_frames(3, total_flat, flat)
    assert b[0] == b[1] == b[2]


def test_beat_frames_respect_the_min_beat_floor():
    """A tiny weight can never starve a beat below the tsx minBeat
    (2*transition + round(fps*0.5) = 37 frames at 30fps)."""
    rhythm = motion.normalise_reel_rhythm({"per_card_sec": 1.5, "weights": [10.0, 0.1, 0.1]}, 3)
    total = motion.reel_duration_for(3, **motion._reel_duration_kwargs(rhythm))  # 9.75s
    beats = motion.reel_card_beat_frames(3, total, rhythm)
    # Weights clamp to [4.0, 0.25, 0.25]; 293 frames, remaining 203 →
    # [floor(203*4/4.5)+11, max(37, floor(203*0.25/4.5)+11), …].
    assert beats == [191, 37, 37]
    assert all(bf >= 37 for bf in beats)


def test_tsx_carve_constants_match_the_python_mirror():
    """Source contract: the tsx constants reel_card_beat_frames mirrors must
    stay verbatim — if this fails, update BOTH sides in lock-step."""
    src = _reel_src()
    carve = src.split("export const MeetReel", 1)[1].split("let cursor = 0", 1)[0]
    assert "Math.round(fps * 0.35)" in carve  # transitionFrames
    assert "transitionFrames * 2 + Math.round(fps * 0.5)" in carve  # minBeat
    assert "Math.floor((remaining * w) / weightSum) + transitionFrames" in carve


# ===========================================================================
# render_meet_reel — duration derivation, cache identity, props, manifest
# ===========================================================================


def _render_capture(tmp_path, monkeypatch, cards, **kwargs):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        captured["duration_sec"] = duration_sec
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        result = motion.render_meet_reel(cards, BRAND, tmp_path / "out" / "reel.mp4", **kwargs)
    return captured, result


def test_default_reel_omits_the_rhythm_prop_and_keeps_15s(tmp_path, monkeypatch):
    cap, _ = _render_capture(tmp_path, monkeypatch, [_card(i) for i in range(3)])
    assert cap["duration_sec"] == 15.0
    assert "rhythm" not in cap["props"], "a default reel must not carry a rhythm prop"


def test_custom_rhythm_flows_into_duration_and_props(tmp_path, monkeypatch):
    cap, _ = _render_capture(
        tmp_path,
        monkeypatch,
        [_card(i) for i in range(3)],
        rhythm={"cover": 3, "weights": [2, 1, 1]},
    )
    # cover 3 + 4·(2+1+1) + 1 = 20
    assert cap["duration_sec"] == 20.0
    assert cap["props"]["rhythm"]["coverSec"] == 3.0
    assert cap["props"]["rhythm"]["beatWeights"] == [2.0, 1.0, 1.0]


def test_default_reel_reuses_the_legacy_cache_entry(tmp_path, monkeypatch):
    """The clinching back-compat proof: a default render writes a cache entry,
    and a second default render is a pure cache hit (identical key)."""
    _render_capture(tmp_path, monkeypatch, [_card(1)])
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with mock.patch.object(motion, "_run_remotion") as rerun:
        motion.render_meet_reel([_card(1)], BRAND, tmp_path / "out2" / "reel.mp4")
    rerun.assert_not_called()


def test_distinct_rhythms_get_distinct_cache_entries(tmp_path, monkeypatch):
    _render_capture(tmp_path, monkeypatch, [_card(i) for i in range(3)])  # default
    _render_capture(
        tmp_path, monkeypatch, [_card(i) for i in range(3)], rhythm={"cover": 3}
    )
    _render_capture(
        tmp_path, monkeypatch, [_card(i) for i in range(3)], rhythm={"weights": [2, 1, 1]}
    )
    cache = motion._cache_dir()
    assert len(list(cache.glob("*.mp4"))) == 3  # no cross-rhythm cache collisions


def test_explicit_duration_still_wins_but_rhythm_still_carves(tmp_path, monkeypatch):
    cap, _ = _render_capture(
        tmp_path,
        monkeypatch,
        [_card(1), _card(2)],
        duration_sec=12.5,
        rhythm={"cover": 3, "weights": [2, 1]},
    )
    assert cap["duration_sec"] == 12.5  # caller override wins the total…
    assert cap["props"]["rhythm"]["coverSec"] == 3.0  # …rhythm still shapes the carve


def test_manifest_records_the_effective_rhythm(tmp_path, monkeypatch):
    _render_capture(tmp_path, monkeypatch, [_card(1)])  # default
    _render_capture(tmp_path, monkeypatch, [_card(1)], rhythm={"cover": 3})  # custom
    recs = [
        json.loads(p.read_text())
        for p in motion._cache_dir().glob("*.json")
        if json.loads(p.read_text()).get("kind") == "reel"
    ]
    assert any(r.get("rhythm") == "default" for r in recs)
    assert any(isinstance(r.get("rhythm"), dict) for r in recs)


# ===========================================================================
# ffmpeg fallback — same rhythm, mirrored carve, default byte-identical
# ===========================================================================


def test_ffmpeg_default_segments_are_byte_identical():
    """rhythm=None must reproduce the original flat-beat split exactly."""
    X = reel_ffmpeg.CROSSFADE_SEC
    for n in range(1, 6):
        total = motion.reel_duration_for(n)
        plain = reel_ffmpeg.reel_segment_durations(n, total)
        explicit_none = reel_ffmpeg.reel_segment_durations(n, total, rhythm=None)
        assert plain == explicit_none
        chained = sum(plain) - X * (len(plain) - 1)
        assert chained == pytest.approx(total, abs=1e-9)


def test_ffmpeg_segments_honour_custom_cover_outro():
    X = reel_ffmpeg.CROSSFADE_SEC
    rhythm = motion.normalise_reel_rhythm({"cover": 3, "outro": 2}, 2)
    total = motion.reel_duration_for(2, cover_sec=3, outro_sec=2)
    segs = reel_ffmpeg.reel_segment_durations(2, total, rhythm=rhythm)
    assert segs[0] == pytest.approx(3.0 + X)  # cover stretched to 3s
    assert segs[-1] == pytest.approx(4.0 + 2.0)  # last card carries the 2s outro
    assert sum(segs) - X * (len(segs) - 1) == pytest.approx(total, abs=1e-9)


def test_ffmpeg_segments_honour_beat_weights():
    X = reel_ffmpeg.CROSSFADE_SEC
    rhythm = motion.normalise_reel_rhythm({"weights": [2, 1]}, 2)
    total = motion.reel_duration_for(2, beat_weights=[2, 1])
    segs = reel_ffmpeg.reel_segment_durations(2, total, rhythm=rhythm)
    assert segs[1] == pytest.approx(8.0 + X)  # card0 weighted 2× → 8s
    assert segs[2] == pytest.approx(5.0)  # card1 4s + 1s outro
    assert sum(segs) - X * (len(segs) - 1) == pytest.approx(total, abs=1e-9)


def test_motion_dispatch_forwards_rhythm_to_the_ffmpeg_engine(tmp_path, monkeypatch):
    """When the ffmpeg engine is selected, the normalised rhythm must reach
    reel_ffmpeg.render_meet_reel_from_props (so the free engine renders the
    same custom rhythm, not the default)."""
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls: dict = {}

    def _fake(cards_props, brand_dict, brand_kit, out_path, **kw):
        calls.update(kw)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
        return out

    monkeypatch.setattr(reel_ffmpeg, "render_meet_reel_from_props", _fake)
    with mock.patch.object(motion, "_run_remotion") as remotion_run:
        motion.render_meet_reel(
            [_card(1), _card(2)], BRAND, tmp_path / "r.mp4", rhythm={"weights": [2, 1]}
        )
    assert not remotion_run.called
    assert calls["rhythm"]["beatWeights"] == [2.0, 1.0]
    # cover 2 + 4·(2+1) + 1 = 15 flows through as the total too
    assert calls["duration_sec"] == 15.0


def test_ffmpeg_render_folds_rhythm_into_the_cache_key(tmp_path, monkeypatch):
    """Two ffmpeg reels that differ only in rhythm must not share a cache file."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(reel_ffmpeg, "_require_available", lambda: "/bin/true")
    props = [{"athleteFullName": "A", "variationSeed": 1}]
    seen: set = set()

    real_hash = motion._content_hash

    def _spy(payload, *, kind):
        key = real_hash(payload, kind=kind)
        seen.add(key)
        # Stop before any real ffmpeg work by raising once the key is computed.
        raise RuntimeError("stop-after-keying")

    with mock.patch.object(motion, "_content_hash", side_effect=_spy):
        for rh in (None, {"coverSec": 3.0, "outroSec": 1.0, "perCardSec": 4.0, "beatWeights": []}):
            with pytest.raises(RuntimeError, match="stop-after-keying"):
                reel_ffmpeg.render_meet_reel_from_props(
                    props, BRAND, None, tmp_path / "r.mp4", rhythm=rh
                )
    assert len(seen) == 2, "rhythm must change the ffmpeg cache key"


# ===========================================================================
# MeetReel.tsx — source contract for the beat-carving region (sole owner)
# ===========================================================================


def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


def test_tsx_declares_the_rhythm_schema():
    src = _reel_src()
    assert "reelRhythmSchema" in src
    for field in ("coverSec", "outroSec", "perCardSec", "beatWeights"):
        assert field in src, field
    # Optional on the reel schema = a rhythm-less reel is byte-identical.
    assert "rhythm: reelRhythmSchema.optional()" in src


def test_tsx_carving_reads_the_rhythm_and_keeps_the_defaults():
    """The beat-carving region must consume the rhythm AND fall back to the
    exact original constants (2.0 cover, 1.0 outro, 1.25 top-card emphasis)."""
    src = _reel_src()
    carve = src.split("export const MeetReel", 1)[1].split("let cursor = 0", 1)[0]
    assert "rhythm.coverSec" in carve and "rhythm.outroSec" in carve
    assert "rhythm.beatWeights" in carve or "explicitWeights" in carve
    # Default fallbacks preserved verbatim.
    assert ": 2.0" in carve and ": 1.0" in carve
    assert "1.25" in carve, "the default top-card emphasis must survive"


def test_tsx_carving_is_deterministic_no_rng():
    """Determinism guard: the carving (like all motion) is a pure function of
    props/frame — no Math.random / Date.now sneaks into the region."""
    src = _reel_src()
    carve = src.split("export const MeetReel", 1)[1].split("let cursor = 0", 1)[0]
    assert "Math.random" not in carve
    assert "Date.now" not in carve


# ===========================================================================
# Reel route — the rhythm query params reach render_meet_reel
# ===========================================================================


@pytest.fixture
def reel_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))

    run = {
        "run_id": "r1",
        "profile_id": "alpha",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": f"swim-{i}",
                    "priority": 1.0 - i * 0.1,
                    "achievement": {
                        "swim_id": f"swim-{i}",
                        "swimmer_name": f"Swimmer {i}",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
                for i in range(3)
            ]
        },
    }
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    return app, wm


def test_route_passes_rhythm_query_params_through(reel_app, tmp_path):
    app, wm = reel_app
    import mediahub.visual.motion as _motion

    captured: dict = {}

    def _fake_render(cards, brand_kit, out_path, **kw):
        captured.update(kw)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        with mock.patch.object(_motion, "render_meet_reel", side_effect=_fake_render):
            resp = c.post("/api/runs/r1/reel?n=3&cover=3&outro=1.5&weights=2,1,1")
    assert resp.status_code == 200
    assert captured["rhythm"] is not None
    assert captured["rhythm"]["coverSec"] == 3.0
    assert captured["rhythm"]["outroSec"] == 1.5
    assert captured["rhythm"]["beatWeights"] == [2.0, 1.0, 1.0]


def test_route_without_rhythm_params_sends_none(reel_app, tmp_path):
    app, wm = reel_app
    import mediahub.visual.motion as _motion

    captured: dict = {}

    def _fake_render(cards, brand_kit, out_path, **kw):
        captured.update(kw)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        with mock.patch.object(_motion, "render_meet_reel", side_effect=_fake_render):
            resp = c.post("/api/runs/r1/reel?n=3")
    assert resp.status_code == 200
    assert captured["rhythm"] is None  # untouched default path


def test_route_rejects_bad_rhythm_params(reel_app):
    app, wm = reel_app
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        bad_cover = c.post("/api/runs/r1/reel?cover=lots")
        bad_weights = c.post("/api/runs/r1/reel?weights=2,oops,1")
    assert bad_cover.status_code == 400
    assert bad_cover.get_json()["error"] == "bad_rhythm"
    assert bad_weights.status_code == 400
