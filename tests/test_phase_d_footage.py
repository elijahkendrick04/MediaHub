"""Phase D (M23/M25/M27/M28 + leftovers) — club footage into the engines.

Unit coverage:
* M23 — deterministic clip sourcing (race_footage role, permission gate,
  photo-vs-footage priority rule), trim-window maths, bounded-resolution dims,
  trim-cache naming + pruning, attach-only-when-present props, story/reel
  cache-key folds (byte-identical no-footage cards), manifest provenance.
* M25 — best-frame timestamp maths + extraction with inherited permission.
* M27 — poster extraction at ingest + honest no-FFmpeg fallback.
* M28 — self-hosted ASS caption fonts (ttf conversion, fonts.conf, the
  six-family guarantee) and the branded end-card (EDL append + cache fold).
* LEFTOVER-1 — inspector photo_pos → photoPos threading (manual crop wins).
* LEFTOVER-2 — scene-tag boost in score_asset (absent context byte-identical).

Route coverage lives in tests/test_phase_d_footage_routes.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.media_library.models import MediaAsset  # noqa: E402
from mediahub.media_library.selector import score_asset, select_assets  # noqa: E402
from mediahub.video.moments import Moment  # noqa: E402
from mediahub.visual import footage as footage_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeStore:
    """Minimal media-library stand-in: list/get/save/store_blob."""

    def __init__(self, assets=(), tmp_path=None):
        self.assets = {a.id: a for a in assets}
        self.tmp_path = tmp_path

    def list(self, *, profile_id=None, asset_type=None, limit=500, **kw):
        out = []
        for a in self.assets.values():
            if profile_id and a.profile_id != profile_id:
                continue
            if asset_type and a.type != asset_type:
                continue
            out.append(a)
        return out[:limit]

    def get(self, asset_id):
        return self.assets.get(asset_id)

    def save(self, asset):
        if not asset.id:
            asset.id = f"ma_{len(self.assets) + 1}"
        self.assets[asset.id] = asset
        return asset

    def store_blob(self, data, filename, profile_id):
        p = Path(self.tmp_path) / f"{profile_id or '_shared'}_{filename}"
        p.write_bytes(data)
        return p


def _footage_asset(tmp_path, *, asset_id="ft_1", permission="approved_by_club", duration_ms=12000):
    src = tmp_path / f"{asset_id}.mp4"
    if not src.exists():
        src.write_bytes(b"\x00" * 4096)
    return MediaAsset(
        id=asset_id,
        filename=f"{asset_id}.mp4",
        path=str(src),
        type="footage",
        profile_id="alpha",
        linked_athlete_names=["Eira Hughes"],
        linked_meet_ids=["r1"],
        permission_status=permission,
        approval_status="approved",
        width=1920,
        height=1080,
        orientation="landscape",
        media_meta={"duration_ms": duration_ms, "fps": 30.0, "has_audio": True},
    )


def _photo_asset(tmp_path, *, asset_id="ph_1", permission="user_owned"):
    p = tmp_path / f"{asset_id}.jpg"
    if not p.exists():
        from PIL import Image

        Image.new("RGB", (1200, 900), (20, 80, 150)).save(p, quality=90)
    return MediaAsset(
        id=asset_id,
        filename=f"{asset_id}.jpg",
        path=str(p),
        type="athlete_action",
        profile_id="alpha",
        linked_athlete_names=["Eira Hughes"],
        permission_status=permission,
        approval_status="approved",
        width=1200,
        height=900,
        orientation="landscape",
    )


def _brief(archetype="full_bleed_photo_lower_third", **over):
    b = {
        "id": "cb_test",
        "content_item_id": "swim-1",
        "profile_id": "alpha",
        "layout_template": archetype,
        "photo_treatment": "photo",
        "sourced_asset_ids": ["ph_1"],
        "text_layers": {
            "athlete_full_name": "Eira Hughes",
            "athlete_first_name": "Eira",
            "athlete_surname": "Hughes",
            "event_name": "100m Freestyle",
            "result_value": "59.80",
            "achievement_label": "NEW PB",
        },
        "palette": {"primary": "#0A2540", "secondary": "#101418", "accent": "#FFD86E"},
    }
    b.update(over)
    return b


def _card(**over):
    c = {
        "id": "swim-1",
        "swim_id": "swim-1",
        "achievement": {
            "swim_id": "swim-1",
            "swimmer_name": "Eira Hughes",
            "event_name": "100m Freestyle",
            "result_time": "59.80",
            "type": "PB",
        },
        "meet_name": "Test Open",
    }
    c.update(over)
    return c


BRAND = {
    "profile_id": "alpha",
    "display_name": "Alpha SC",
    "short_name": "ASC",
    "primary_colour": "#0A2540",
    "secondary_colour": "#101418",
    "accent_colour": "#FFD86E",
}


@pytest.fixture
def footage_env(tmp_path, monkeypatch):
    """A DATA_DIR-isolated footage environment with ffmpeg stubbed out."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    # Deterministic detected moments — no FFmpeg in the loop.
    moments = [
        Moment(1000, 7000, 0.5, "energy", "audio energy 0.5 at 1s"),
        Moment(4000, 10000, 0.9, "energy+scene", "loud cheer at 4s with a scene cut"),
    ]
    monkeypatch.setattr(
        "mediahub.video.moments.detect_moments",
        lambda path, *, duration_ms, target_len_ms=6000, max_moments=5: [
            Moment(
                m.start_ms,
                min(duration_ms, m.start_ms + target_len_ms),
                m.score,
                m.kind,
                m.reason,
            )
            for m in moments
        ],
    )
    # Fake trim: writes a deterministic file instead of shelling FFmpeg.
    trims: list[dict] = []

    def fake_trim(src, out_path, *, in_ms, out_ms, dims, stabilize=False):
        trims.append(
            {"src": str(src), "in": in_ms, "out": out_ms, "dims": dims, "stabilize": stabilize}
        )
        Path(out_path).write_bytes(b"clip" * 512)
        return True

    monkeypatch.setattr(footage_mod, "_normalise_clip", fake_trim)
    # Point the footage cache into the tmp tree so tests never touch the repo.
    cache = tmp_path / "footage_cache"
    monkeypatch.setattr(
        footage_mod, "footage_cache_dir", lambda: cache.mkdir(exist_ok=True) or cache
    )
    return {"tmp": tmp_path, "trims": trims, "cache": cache}


# ---------------------------------------------------------------------------
# Selector: race_footage role + consent gate (M23) + scene boost (LEFTOVER-2)
# ---------------------------------------------------------------------------


class TestSelectorFootage:
    def test_race_footage_role_selects_footage(self, tmp_path):
        ft = _footage_asset(tmp_path)
        ph = _photo_asset(tmp_path)
        picks = select_assets([ft, ph], role="race_footage", athlete_name="Eira Hughes")
        assert [p["asset_id"] for p in picks][:1] == ["ft_1"]

    @pytest.mark.parametrize("status", ["do_not_use", "needs_parental_consent"])
    def test_consent_statuses_zero_score(self, tmp_path, status):
        ft = _footage_asset(tmp_path, permission=status)
        assert score_asset(ft, role="race_footage", athlete_name="Eira Hughes") == 0.0
        assert select_assets([ft], role="race_footage", athlete_name="Eira Hughes") == []

    def test_scene_boost_requires_context(self, tmp_path):
        ph = _photo_asset(tmp_path)
        ph.tags = ["podium"]
        base = score_asset(ph, role="hero_athlete", athlete_name="Eira Hughes")
        boosted = score_asset(
            ph, role="hero_athlete", athlete_name="Eira Hughes", card_context="medal_gold"
        )
        assert boosted > base
        # Absent context — byte-identical to the pre-context behaviour.
        again = score_asset(ph, role="hero_athlete", athlete_name="Eira Hughes")
        assert again == base

    def test_scene_boost_reads_vision_record(self, tmp_path):
        ph = _photo_asset(tmp_path)
        ph.description_parsed = {"vision": {"scene_tags": ["celebration"]}}
        base = score_asset(ph, role="hero_athlete", athlete_name="Eira Hughes")
        pb = score_asset(
            ph,
            role="hero_athlete",
            athlete_name="Eira Hughes",
            card_context="confirmed_official_pb",
        )
        assert pb > base

    def test_scene_boost_ignores_unrelated_context(self, tmp_path):
        ph = _photo_asset(tmp_path)
        ph.tags = ["podium"]
        base = score_asset(ph, role="hero_athlete", athlete_name="Eira Hughes")
        other = score_asset(
            ph, role="hero_athlete", athlete_name="Eira Hughes", card_context="venue_preview"
        )
        assert other == base

    def test_scene_boost_capped(self, tmp_path):
        from mediahub.media_library.selector import _scene_boost, _SCENE_BOOST_CAP

        ph = _photo_asset(tmp_path)
        ph.tags = ["podium", "celebration", "team-huddle"]
        assert _scene_boost(ph, "relay medal pb gold team") <= _SCENE_BOOST_CAP


# ---------------------------------------------------------------------------
# M23 — pure maths: dims, trim window, prune
# ---------------------------------------------------------------------------


class TestFootageMaths:
    def test_clip_scale_dims_caps_long_edge_even(self):
        assert footage_mod.clip_scale_dims(3840, 2160) == (1280, 720)
        assert footage_mod.clip_scale_dims(2160, 3840) == (720, 1280)
        # Never upscales; rounds to even.
        assert footage_mod.clip_scale_dims(641, 361) == (640, 360)
        assert footage_mod.clip_scale_dims(640, 360) == (640, 360)

    def test_pick_trim_window_prefers_score_then_chronology(self):
        moments = [
            Moment(0, 6000, 0.7, "energy", "a"),
            Moment(8000, 14000, 0.7, "energy", "b"),
            Moment(4000, 10000, 0.9, "scene", "c"),
        ]
        best, why = footage_mod.pick_trim_window(moments, beat_ms=6000)
        assert best is not None and best.start_ms == 4000 and why == ""
        # Tie on score → earliest wins.
        best2, _ = footage_mod.pick_trim_window(moments[:2], beat_ms=6000)
        assert best2.start_ms == 0

    def test_pick_trim_window_rejects_short_clip(self):
        best, why = footage_mod.pick_trim_window(
            [Moment(0, 3000, 0.9, "energy", "x")], beat_ms=6000
        )
        assert best is None and why == "clip-shorter-than-beat"
        assert footage_mod.pick_trim_window([], beat_ms=6000) == (None, "no-moment-detected")

    def test_prune_footage_cache_count_cap(self, footage_env):
        cache = footage_env["cache"]
        cache.mkdir(exist_ok=True)
        for i in range(6):
            p = cache / f"clip{i}.mp4"
            p.write_bytes(b"x" * 10)
            os.utime(p, (1000 + i, 1000 + i))
        pruned = footage_mod.prune_footage_cache(keep=3)
        assert pruned == 3
        left = sorted(p.name for p in cache.glob("*.mp4"))
        assert left == ["clip3.mp4", "clip4.mp4", "clip5.mp4"]  # newest kept


# ---------------------------------------------------------------------------
# M23 — sourcing determinism, priority rule, gates
# ---------------------------------------------------------------------------


class TestResolveCardFootage:
    def _resolve(self, tmp_path, *, store, photo=None, brief=None, card=None, beat=6.0):
        return footage_mod.resolve_card_footage(
            card or _card(),
            brief or _brief(),
            BRAND,
            beat_seconds=beat,
            photo_asset=photo,
            store=store,
        )

    def test_deterministic_same_inputs_same_clip_and_window(self, footage_env):
        tmp = footage_env["tmp"]
        store = FakeStore([_footage_asset(tmp)])
        r1, _ = self._resolve(tmp, store=store)
        r2, _ = self._resolve(tmp, store=store)
        assert r1 is not None and r2 is not None
        assert r1.video_src == r2.video_src
        assert r1.cache_sig == r2.cache_sig
        # The window is the top-scoring detected moment sized to the beat.
        assert r1.cache_sig["in_ms"] == 4000 and r1.cache_sig["out_ms"] == 10000
        assert r1.video_duration_sec == 6.0
        assert r1.video_start_sec == 0.0
        assert r1.video_src.startswith("footage_cache/")

    def test_fingerprint_changes_when_source_replaced(self, footage_env):
        tmp = footage_env["tmp"]
        asset = _footage_asset(tmp)
        store = FakeStore([asset])
        r1, _ = self._resolve(tmp, store=store)
        # Replace the source bytes in place → new fingerprint → new trim name.
        Path(asset.path).write_bytes(b"\xff" * 8192)
        r2, _ = self._resolve(tmp, store=store)
        assert r1.video_src != r2.video_src
        assert r1.cache_sig["fingerprint"] != r2.cache_sig["fingerprint"]

    def test_priority_rule_footage_wins_at_or_above_photo_score(self, footage_env):
        tmp = footage_env["tmp"]
        ft = _footage_asset(tmp)  # approved_by_club + approved → strong
        ph = _photo_asset(tmp, permission="needs_approval")  # weak photo
        ph.approval_status = "draft"
        res, why = self._resolve(tmp, store=FakeStore([ft]), photo=ph)
        assert res is not None and why == ""
        assert res.provenance["decision"] == "footage"
        assert res.provenance["footage_score"] >= res.provenance["photo_score"]

    def test_priority_rule_photo_wins_when_it_outscores(self, footage_env):
        tmp = footage_env["tmp"]
        ft = _footage_asset(tmp, permission="needs_approval")
        ft.approval_status = "draft"
        ph = _photo_asset(tmp)  # user_owned + approved → strong
        res, why = self._resolve(tmp, store=FakeStore([ft]), photo=ph)
        assert res is None
        assert why.startswith("photo-outscores-footage")

    @pytest.mark.parametrize("status", ["do_not_use", "needs_parental_consent"])
    def test_consent_gate_never_uses_blocked_clip(self, footage_env, status):
        tmp = footage_env["tmp"]
        ft = _footage_asset(tmp, permission=status)
        res, why = self._resolve(tmp, store=FakeStore([ft]))
        assert res is None
        assert footage_env["trims"] == []  # never even trimmed

    def test_gates_no_photo_treatment_and_non_photo_archetype(self, footage_env):
        tmp = footage_env["tmp"]
        store = FakeStore([_footage_asset(tmp)])
        res, why = self._resolve(tmp, store=store, brief=_brief(photo_treatment="no-photo"))
        assert (res, why) == (None, "")
        # Cutout-mode archetype (spotlight_disc) → no footage.
        res, why = self._resolve(tmp, store=store, brief=_brief(archetype="spotlight_disc"))
        assert (res, why) == (None, "")
        # Type-led (no photo slot) → no footage.
        res, why = self._resolve(tmp, store=store, brief=_brief(archetype="stat_ribbon"))
        assert (res, why) == (None, "")

    def test_manual_crop_pins_the_photo(self, footage_env):
        tmp = footage_env["tmp"]
        store = FakeStore([_footage_asset(tmp)])
        card = _card(inspector_overrides={"photo_pos": "center 40%"})
        res, why = self._resolve(tmp, store=store, card=card)
        assert res is None and why == "photo-pinned-by-manual-crop"

    def test_clip_shorter_than_beat_skips_honestly(self, footage_env):
        tmp = footage_env["tmp"]
        store = FakeStore([_footage_asset(tmp, duration_ms=3000)])
        res, why = self._resolve(tmp, store=store)
        assert res is None and why == "clip-shorter-than-beat"

    def test_ffmpeg_failure_falls_back_with_reason(self, footage_env, monkeypatch):
        tmp = footage_env["tmp"]
        monkeypatch.setattr(footage_mod, "_normalise_clip", lambda *a, **k: False)
        res, why = self._resolve(tmp, store=FakeStore([_footage_asset(tmp)]))
        assert res is None and why == "ffmpeg-trim-failed-or-unavailable"

    # -- opt-in deterministic stabilization (footage-stabilization) --

    def test_stabilize_off_is_byte_identical(self, footage_env):
        """A clip that doesn't request stabilization keeps the exact historic
        filename, cache_sig, and (no) provenance — trim invoked with stabilize=False."""
        tmp = footage_env["tmp"]
        res, why = self._resolve(tmp, store=FakeStore([_footage_asset(tmp)]))
        assert res is not None and why == ""
        assert "-stab" not in res.video_src
        assert "stabilize" not in res.cache_sig
        assert "stabilize" not in res.provenance
        assert footage_env["trims"][-1]["stabilize"] is False

    def test_stabilize_applied(self, footage_env, monkeypatch):
        tmp = footage_env["tmp"]
        monkeypatch.setattr("mediahub.video.enhance.is_stabilize_available", lambda: True)
        ft = _footage_asset(tmp)
        ft.media_meta["stabilize"] = True
        res, why = self._resolve(tmp, store=FakeStore([ft]))
        assert res is not None and why == ""
        assert res.video_src.endswith("-stab.mp4")
        assert res.cache_sig["stabilize"] == "applied"
        assert res.provenance["stabilize"] == {
            "requested": True,
            "applied": True,
            "reason": "",
        }
        assert footage_env["trims"][-1]["stabilize"] is True

    def test_stabilize_unavailable_honest_fallback(self, footage_env, monkeypatch):
        """vidstab requested but the host FFmpeg lacks the filter → plain trim,
        honestly recorded, never a faked steadied clip."""
        tmp = footage_env["tmp"]
        monkeypatch.setattr("mediahub.video.enhance.is_stabilize_available", lambda: False)
        ft = _footage_asset(tmp)
        ft.media_meta["stabilize"] = True
        res, why = self._resolve(tmp, store=FakeStore([ft]))
        assert res is not None and why == ""
        assert "-stab" not in res.video_src
        assert res.cache_sig["stabilize"] == "unavailable"
        assert res.provenance["stabilize"]["applied"] is False
        assert res.provenance["stabilize"]["reason"] == "vidstab-unavailable"
        assert footage_env["trims"][-1]["stabilize"] is False

    def test_stabilize_folds_into_content_hash(self, footage_env):
        """The stabilize cache_sig key changes the motion content hash; the
        default cache_sig (no key) hashes byte-identically to before."""
        from mediahub.visual import motion

        tmp = footage_env["tmp"]
        base, _ = self._resolve(tmp, store=FakeStore([_footage_asset(tmp)]))
        assert "stabilize" not in base.cache_sig
        # Same footage sig ± only the stabilize key isolates the fold.
        stabbed_sig = {**base.cache_sig, "stabilize": "applied"}
        h_plain = motion._content_hash({"footage": base.cache_sig}, kind="story")
        h_stab = motion._content_hash({"footage": stabbed_sig}, kind="story")
        assert h_plain == motion._content_hash({"footage": base.cache_sig}, kind="story")
        assert h_plain != h_stab  # stabilize state re-keys the render


# ---------------------------------------------------------------------------
# M23 — motion props + cache folds (attach only when present)
# ---------------------------------------------------------------------------


class TestMotionFootageFold:
    def _props(self, footage=None, card=None, brief=None):
        from mediahub.visual import motion

        return motion._card_to_props(
            card or _card(), variation_seed=7, brief=brief or _brief(), footage=footage
        )

    def test_props_attach_only_when_footage_resolved(self):
        d1 = self._props(footage=None)
        assert "videoSrc" not in d1 and "videoStartSec" not in d1 and "videoDurationSec" not in d1
        res = footage_mod.FootageResolution(
            video_src="footage_cache/abc-0-6000.mp4",
            video_start_sec=0.0,
            video_duration_sec=6.0,
            cache_sig={
                "src": "footage_cache/abc-0-6000.mp4",
                "fingerprint": "abc",
                "in_ms": 0,
                "out_ms": 6000,
            },
            provenance={"used": True},
        )
        d2 = self._props(footage=res)
        assert d2["videoSrc"] == "footage_cache/abc-0-6000.mp4"
        assert d2["videoDurationSec"] == 6.0
        # Everything else byte-identical — the no-footage card is untouched.
        d2_minus = {
            k: v
            for k, v in d2.items()
            if k not in ("videoSrc", "videoStartSec", "videoDurationSec")
        }
        assert d2_minus == d1

    def test_story_cache_key_folds_footage_only_when_present(
        self, footage_env, monkeypatch, tmp_path
    ):
        from mediahub.visual import motion

        keys: list[str] = []

        def fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
            keys.append(Path(out_path).stem)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"0" * 2048)
            return Path(out_path)

        monkeypatch.setattr(motion, "_run_remotion", fake_run)

        tmp = footage_env["tmp"]
        ph = _photo_asset(tmp)
        ft = _footage_asset(tmp)

        # A real store singleton scoped to this test.
        from mediahub.media_library import store as store_mod

        real = store_mod.MediaLibraryStore(db_path=tmp / "data.db", uploads_dir=tmp / "uploads")
        monkeypatch.setattr(store_mod, "_default_store", real)
        real.save(ph)

        out = tmp / "out"
        # 1) No footage in the library → no fold; manifest carries no footage.
        motion.render_story_card(_card(), BRAND, out / "a.mp4", variation_seed=7, brief=_brief())
        key_no_footage = keys[-1]
        manifest = json.loads((out / "a.json").read_text())
        assert "footage" not in manifest
        assert manifest["card"]["has_footage"] is False

        # 2) Add a footage clip that outscores the photo → fold + provenance.
        ph2 = real.get("ph_1")
        ph2.permission_status = "needs_approval"
        ph2.approval_status = "draft"
        real.save(ph2)
        real.save(ft)
        motion.render_story_card(_card(), BRAND, out / "b.mp4", variation_seed=7, brief=_brief())
        key_with_footage = keys[-1]
        assert key_with_footage != key_no_footage
        manifest2 = json.loads((out / "b.json").read_text())
        assert manifest2["footage"]["used"] is True
        assert manifest2["footage"]["asset_id"] == "ft_1"
        assert manifest2["footage"]["in_ms"] == 4000
        assert manifest2["card"]["has_footage"] is True

    def test_reel_cache_key_folds_footage_only_when_present(self, footage_env, monkeypatch):
        from mediahub.visual import motion

        keys: list[str] = []

        def fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
            keys.append(Path(out_path).stem)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_bytes(b"0" * 2048)
            return Path(out_path)

        monkeypatch.setattr(motion, "_run_remotion", fake_run)
        monkeypatch.delenv("MEDIAHUB_REEL_PARALLEL", raising=False)

        tmp = footage_env["tmp"]
        from mediahub.media_library import store as store_mod

        real = store_mod.MediaLibraryStore(db_path=tmp / "data.db", uploads_dir=tmp / "uploads")
        monkeypatch.setattr(store_mod, "_default_store", real)

        out = tmp / "reel"
        motion.render_meet_reel([_card()], BRAND, out / "r1.mp4", briefs=[_brief()])
        key_no_footage = keys[-1]
        manifest = json.loads((out / "r1.json").read_text())
        assert "footage" not in manifest

        real.save(_footage_asset(tmp))
        motion.render_meet_reel([_card()], BRAND, out / "r2.mp4", briefs=[_brief()])
        key_with = keys[-1]
        assert key_with != key_no_footage
        manifest2 = json.loads((out / "r2.json").read_text())
        assert manifest2["footage"][0]["used"] is True
        assert manifest2["cards"][0]["has_footage"] is True

    def test_photo_scale_withheld_for_footage_beats(self):
        res = footage_mod.FootageResolution(
            video_src="footage_cache/x.mp4",
            video_start_sec=0.0,
            video_duration_sec=6.0,
            cache_sig={},
            provenance={},
        )
        d = self._props(footage=res, brief=_brief(crop_intent="tight_portrait"))
        assert "photoScale" not in d


# ---------------------------------------------------------------------------
# LEFTOVER-1 — inspector photo_pos threading
# ---------------------------------------------------------------------------


class TestInspectorPhotoPos:
    def test_manual_crop_overrides_saliency_and_marks_manual(self, tmp_path, monkeypatch):
        from mediahub.visual import motion

        ph = _photo_asset(tmp_path)
        from mediahub.media_library import store as store_mod

        real = store_mod.MediaLibraryStore(db_path=tmp_path / "d.db", uploads_dir=tmp_path / "u")
        monkeypatch.setattr(store_mod, "_default_store", real)
        real.save(ph)

        card = _card(inspector_overrides={"photo_pos": "center 40%"})
        d = motion._card_to_props(card, variation_seed=7, brief=_brief())
        assert d["photoPos"] == "center 40%"
        assert d.get("photoPosManual") is True
        # Untouched cards attach neither.
        d2 = motion._card_to_props(_card(), variation_seed=7, brief=_brief())
        assert "photoPosManual" not in d2

    def test_invalid_manual_crop_is_dropped(self, tmp_path, monkeypatch):
        from mediahub.visual import motion

        ph = _photo_asset(tmp_path)
        from mediahub.media_library import store as store_mod

        real = store_mod.MediaLibraryStore(db_path=tmp_path / "d.db", uploads_dir=tmp_path / "u")
        monkeypatch.setattr(store_mod, "_default_store", real)
        real.save(ph)
        card = _card(inspector_overrides={"photo_pos": "url(javascript:x) 40px"})
        d = motion._card_to_props(card, variation_seed=7, brief=_brief())
        assert "photoPosManual" not in d

    def test_format_focus_never_clobbers_manual_crop(self):
        from mediahub.visual.motion import _apply_format_photo_focus

        cards = [{"photoPos": "center 40%", "photoPosManual": True, "photoSrc": "data:x"}]
        out = _apply_format_photo_focus(cards, [None], "landscape")
        assert out[0]["photoPos"] == "center 40%"


# ---------------------------------------------------------------------------
# M25 — best-frame extraction
# ---------------------------------------------------------------------------


class TestBestFrame:
    def test_frame_timestamp_is_top_moment_centre(self):
        from mediahub.video.best_frame import frame_timestamp_ms

        ms = frame_timestamp_ms(
            [
                Moment(0, 6000, 0.4, "energy", "a"),
                Moment(4000, 10000, 0.9, "scene", "b"),
            ]
        )
        assert ms == 7000
        assert frame_timestamp_ms([]) is None

    def test_extract_inherits_links_and_permission_never_wider(self, tmp_path):
        from mediahub.video.best_frame import extract_best_frame

        ft = _footage_asset(tmp_path, permission="needs_parental_consent")
        ft.approval_status = "draft"
        store = FakeStore([ft], tmp_path=tmp_path)
        frame = extract_best_frame(
            ft,
            store=store,
            detect_fn=lambda p, *, duration_ms, target_len_ms, max_moments: [
                Moment(2000, 8000, 0.9, "energy", "cheer")
            ],
            extract_fn=lambda src, at_ms: b"\xff\xd8\xff fakejpeg",
        )
        assert frame.type == "athlete_action"
        assert frame.permission_status == "needs_parental_consent"  # inherited, never wider
        assert frame.approval_status == "draft"
        assert frame.linked_athlete_names == ["Eira Hughes"]
        assert frame.linked_meet_ids == ["r1"]
        assert frame.media_meta["source_footage_id"] == "ft_1"
        assert frame.media_meta["frame_at_ms"] == 5000
        assert "frame from ft_1.mp4 at 5.0s" == frame.description_raw
        assert Path(frame.path).exists()

    def test_unmeasured_clip_is_an_honest_error(self, tmp_path):
        from mediahub.video.best_frame import BestFrameUnavailable, extract_best_frame

        ft = _footage_asset(tmp_path)
        ft.media_meta = {}
        with pytest.raises(BestFrameUnavailable):
            extract_best_frame(ft, store=FakeStore([ft], tmp_path=tmp_path))


# ---------------------------------------------------------------------------
# M27 — poster extraction at ingest
# ---------------------------------------------------------------------------


class TestIngestPoster:
    def test_no_ffmpeg_no_poster_current_behaviour(self, tmp_path, monkeypatch):
        from mediahub.video import ingest

        monkeypatch.setattr("mediahub.visual.reel_ffmpeg.ffmpeg_exe", lambda: None)
        blob = tmp_path / "c.mp4"
        blob.write_bytes(b"x" * 100)
        assert ingest.extract_poster(blob, duration_ms=8000, width=1280, height=720) is None

    def test_unmeasured_clip_no_poster(self, tmp_path):
        from mediahub.video import ingest

        blob = tmp_path / "c.mp4"
        blob.write_bytes(b"x" * 100)
        assert ingest.extract_poster(blob, duration_ms=0, width=0, height=0) is None

    def test_real_poster_extraction(self, tmp_path):
        from mediahub.visual.reel_ffmpeg import ffmpeg_exe

        exe = ffmpeg_exe()
        if not exe:
            pytest.skip("no FFmpeg on this box")
        import subprocess

        src = tmp_path / "real.mp4"
        subprocess.run(
            [
                exe,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=30:duration=2",
                "-pix_fmt",
                "yuv420p",
                str(src),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        from mediahub.video import ingest

        name = ingest.extract_poster(src, duration_ms=2000, width=640, height=360)
        assert name == "real.poster.png"
        poster = ingest.poster_path_for_blob(src)
        assert poster.exists() and poster.stat().st_size > 0


# ---------------------------------------------------------------------------
# M28 — caption fonts + end-card
# ---------------------------------------------------------------------------


class TestCaptionFonts:
    def test_ass_family_is_always_one_of_the_six(self):
        from mediahub.video.caption_fonts import SELF_HOSTED_FAMILIES, ass_font_family

        assert ass_font_family("") in SELF_HOSTED_FAMILIES
        assert ass_font_family("Comic Sans MS") in SELF_HOSTED_FAMILIES
        assert ass_font_family("Space Grotesk") == "Space Grotesk"

    def test_karaoke_ass_style_family_is_self_hosted(self):
        from mediahub.video.caption_fonts import SELF_HOSTED_FAMILIES
        from mediahub.video.caption_render import karaoke_ass_document

        doc = karaoke_ass_document(
            {"style": "karaoke", "cues": [{"from": 0, "dur": 30, "text": "go Eira"}]},
            width=1080,
            height=1920,
        )
        style_line = next(line for line in doc.splitlines() if line.startswith("Style: Caption,"))
        family = style_line.split(",")[1]
        assert family in SELF_HOSTED_FAMILIES

    def test_static_ass_style_family_is_self_hosted(self):
        from mediahub.video.caption_fonts import SELF_HOSTED_FAMILIES
        from mediahub.visual.subtitle_burn import ass_document

        doc = ass_document(
            {"cues": [{"from": 0, "dur": 30, "text": "go"}]}, width=1080, height=1920
        )
        style_line = next(line for line in doc.splitlines() if line.startswith("Style: Caption,"))
        assert style_line.split(",")[1] in SELF_HOSTED_FAMILIES

    def test_ensure_ttf_converts_woff2_deterministically(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.video.caption_fonts import ensure_ttf

        out = ensure_ttf("Inter")
        assert out.exists()
        # Real TrueType magic — not a woff2 copy, not an empty stub.
        assert out.read_bytes()[:4] == b"\x00\x01\x00\x00"
        # Second call is the cached file (no rewrite).
        mtime = out.stat().st_mtime_ns
        assert ensure_ttf("Inter") == out
        assert out.stat().st_mtime_ns == mtime

    def test_fontconfig_file_scopes_to_ttf_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.video.caption_fonts import ensure_caption_fonts, ttf_dir

        env = ensure_caption_fonts()
        conf = Path(env["FONTCONFIG_FILE"])
        assert conf.exists()
        text = conf.read_text()
        assert str(ttf_dir()) in text
        # All six families were provisioned.
        assert len(list(ttf_dir().glob("*.ttf"))) == 6

    def test_unknown_family_raises_honest_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.video.caption_fonts import CaptionFontsUnavailable, ensure_ttf

        with pytest.raises(CaptionFontsUnavailable):
            ensure_ttf("Papyrus")


class TestEndCard:
    def _edl(self, src: Path):
        from mediahub.video.edl import EDL, Clip

        return EDL(
            width=1080, height=1920, fps=30, clips=[Clip(source=str(src), in_ms=0, out_ms=4000)]
        )

    def test_no_brand_kit_keeps_timeline_unchanged(self, tmp_path):
        from mediahub.video.end_card import append_end_card

        src = tmp_path / "a.mp4"
        src.write_bytes(b"x" * 2048)
        edl = self._edl(src)
        out, note = append_end_card(edl, None)
        assert out is edl and note

    def test_append_folds_into_render_cache_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.video import end_card as ec
        from mediahub.video.render import cache_key

        src = tmp_path / "a.mp4"
        src.write_bytes(b"x" * 2048)
        card_mp4 = tmp_path / "endcard.mp4"
        card_mp4.write_bytes(b"c" * 2048)
        monkeypatch.setattr(ec, "end_card_clip_path", lambda bk, *, width, height, fps=30: card_mp4)

        edl = self._edl(src)
        base_key = cache_key(edl)
        appended, note = ec.append_end_card(edl, object())
        assert note == ""
        assert len(appended.clips) == len(edl.clips) + 1  # copy, original untouched
        last = appended.clips[-1]
        assert last.source == str(card_mp4)
        assert last.mute is True
        assert last.transition_in.kind == "dissolve"
        # The end-card is a clip source → the render cache key folds its
        # fingerprint exactly like music beds.
        assert cache_key(appended) != base_key

    def test_end_card_content_addressing_by_brand(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.video.end_card import _brand_fingerprint

        a = _brand_fingerprint(
            {"primary": "#111111", "accent": "#FFD86E", "displayName": "Alpha SC"},
            width=1080,
            height=1920,
            fps=30,
        )
        b = _brand_fingerprint(
            {"primary": "#222222", "accent": "#FFD86E", "displayName": "Alpha SC"},
            width=1080,
            height=1920,
            fps=30,
        )
        assert a != b


# ---------------------------------------------------------------------------
# Moments memo: warm renders skip the FFmpeg analysis passes (sweep follow-up)
# ---------------------------------------------------------------------------


class TestMomentMemo:
    def test_trim_window_memoised_per_fingerprint_and_beat(
        self, footage_env, tmp_path, monkeypatch
    ):
        import mediahub.video.moments as moments_mod

        src = tmp_path / "race.mp4"
        src.write_bytes(b"x" * 4096)
        inner = moments_mod.detect_moments
        calls = {"n": 0}

        def counting(path, **kw):
            calls["n"] += 1
            return inner(path, **kw)

        monkeypatch.setattr(moments_mod, "detect_moments", counting)
        fp = footage_mod.source_fingerprint(src)

        first, why = footage_mod._cached_trim_window(src, fp, duration_ms=10000, beat_ms=6000)
        again, _ = footage_mod._cached_trim_window(src, fp, duration_ms=10000, beat_ms=6000)
        assert why == "" and calls["n"] == 1, "second identical request must hit the memo"
        assert (first.start_ms, first.end_ms, first.score, first.kind, first.reason) == (
            again.start_ms,
            again.end_ms,
            again.score,
            again.kind,
            again.reason,
        )
        assert list(footage_env["cache"].glob("*.moments.json")), "memo persisted beside clips"

        # A different beat length is a different memo (window is beat-sized).
        footage_mod._cached_trim_window(src, fp, duration_ms=10000, beat_ms=4000)
        assert calls["n"] == 2

        # Honest negative outcomes are memoised too.
        none1, reason1 = footage_mod._cached_trim_window(src, fp, duration_ms=8000, beat_ms=20000)
        none2, reason2 = footage_mod._cached_trim_window(src, fp, duration_ms=8000, beat_ms=20000)
        assert none1 is None and none2 is None and reason1 == reason2 == "clip-shorter-than-beat"
        assert calls["n"] == 3

    def test_memo_pruned_with_clip_budget(self, footage_env):
        cache = footage_env["cache"]
        cache.mkdir(exist_ok=True)
        for i in range(15):
            (cache / f"aa{i:02d}-0-6000.mp4").write_bytes(b"clip")
            (cache / f"aa{i:02d}-6000.moments.json").write_text("{}")
        pruned = footage_mod.prune_footage_cache(keep=12)
        assert pruned == 6, "3 clips + 3 memos beyond the budget"
        assert len(list(cache.glob("*.mp4"))) == 12
        assert len(list(cache.glob("*.moments.json"))) == 12
