"""Phase C — motion/reel craft (M15–M22).

Covers the quality-overhaul items shipped in this phase:

  * M15 — default cinematic photo camera (photoScale + photoDriftX/Y on every
    intent, seed-chosen; `static` genuinely still) + the story-side cache
    revision field.
  * M16 — paired velocity-matched transitions (`inReel` suppresses the story
    self-fade inside reels; ExitWrap mirrors the incoming TransitionSpec).
  * M17 — legible outro (2.5s default, retimed OutroScreen ramps, ffmpeg
    carve mirrored — the carve itself is pinned in test_reel_rhythm /
    test_reel_ffmpeg).
  * M18 — brand-true cover/outro (Python-resolved APCA-gated coverRoles, top
    card typography, pool-gated photo cover variant).
  * M19 — beat-proportional choreography + resolve-phase micro-accent +
    ambient lift (the alpha value itself is pinned in
    test_motion_ambient_layer).
  * M20 — reel chrome (progress rail + club mark) and relay photoSrcs.
  * M21 — edited-photo parity (effective_image_path + EXIF transpose + the
    edit-recipe signature in the cache key).
  * M22 — honest ffmpeg-engine manifests (same sidecar shape as Remotion).

TSX is checked as source contracts (the shape every parity suite here uses);
Python behaviour is exercised with the render subprocesses stubbed.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import motion, reel_ffmpeg


BRAND = BrandKit(
    profile_id="phasec",
    display_name="Phase C SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="PCSC",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-pc-{i}",
        "swim_id": f"swim-pc-{i}",
        "achievement": {
            "swim_id": f"swim-pc-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Phase C Invitational",
    }


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


def _fake_run(
    *, composition_id, props, out_path, duration_sec=None, size=None, timeout=600, supersample=1.0
):
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)
    return out


# =========================================================================== #
# M15 — default cinematic photo camera
# =========================================================================== #
class TestM15PhotoCamera:
    def test_anim_channels_declare_the_camera(self):
        src = _story_src()
        for chan in ("photoScale", "photoDriftX", "photoDriftY"):
            assert f"{chan}: number" in src, chan

    def test_every_intent_defaults_to_a_seed_chosen_move(self):
        """photoCameraFor is seed-keyed (4 variants) and rides the shared
        base, so every intent that spreads ...base gets a camera move."""
        src = _story_src()
        assert "function photoCameraFor(" in src
        fn = src.split("function photoCameraFor(", 1)[1].split("\nfunction ", 1)[0]
        assert "% 4" in fn, "camera variant must be seed-keyed (variationSeed % 4)"
        # Saliency-safe bounds: ≤1.06 scale and ≤2% lateral travel.
        assert "1.06" in fn
        for num in re.findall(r"photoDriftX:\s*(-?[0-9.]+)", fn):
            assert abs(float(num)) <= 2.0, num
        # The base channels carry the camera into every intent.
        assert "photoScale: camera.photoScale" in src
        assert "photoDriftX: camera.photoDriftX" in src

    def test_static_intent_is_genuinely_still(self):
        src = _story_src()
        fn = src.split("function photoCameraFor(", 1)[1].split("\nfunction ", 1)[0]
        assert re.search(
            r'if \(intent === "static"\) \{\s*\n\s*return \{ photoScale: 1, photoDriftX: 0, photoDriftY: 0 \}',
            fn,
        ), "static must return the identity camera"

    def test_parallax_keeps_its_stronger_dual_rate_treatment(self):
        src = _story_src()
        para = src.split('case "parallax"', 1)[1].split("case ", 1)[0]
        assert "1.07" in para  # the stronger push survives
        assert "photoDriftX: 0" in para  # no lateral drift stacked on top

    def test_photo_layer_applies_translate_and_scale(self):
        src = _story_src()
        assert (
            "translate(${anim.photoDriftX}%, ${anim.photoDriftY}%) scale(${anim.photoScale})" in src
        )

    def test_camera_is_frame_pure(self):
        src = _story_src()
        fn = src.split("function photoCameraFor(", 1)[1].split("\nfunction ", 1)[0]
        assert "interpolate(frame, [0, durationInFrames]" in fn
        assert "Math.random" not in fn and "Date.now" not in fn

    def test_story_cache_payload_carries_the_revision(self, tmp_path, monkeypatch):
        """The story payload now has a revision field: same constant → cache
        hit; a bumped constant → a new key (the deliberate upgrade lever)."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
            motion.render_story_card(_card(1), BRAND, tmp_path / "a" / "s.mp4")
        assert len(list(motion._cache_dir().glob("*.mp4"))) == 1
        # Same revision → pure cache hit.
        with mock.patch.object(motion, "_run_remotion") as rerun:
            motion.render_story_card(_card(1), BRAND, tmp_path / "b" / "s.mp4")
        rerun.assert_not_called()
        # Bumped revision → a distinct cache entry.
        monkeypatch.setattr(motion, "STORY_COMPOSITION_REVISION", "test-bump")
        with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
            motion.render_story_card(_card(1), BRAND, tmp_path / "c" / "s.mp4")
        assert len(list(motion._cache_dir().glob("*.mp4"))) == 2

    def test_reel_revision_bumped_for_phase_c(self):
        # Phase C bumped the reel revision to "3"; later visual passes (the
        # still↔motion parity pass → "4") keep moving it forward — the
        # contract is that Phase C's bump is never rolled back.
        assert int(motion.REEL_COMPOSITION_REVISION) >= 3


# =========================================================================== #
# M16 — paired velocity-matched transitions
# =========================================================================== #
class TestM16PairedTransitions:
    def test_card_schema_declares_in_reel_default_false(self):
        src = _story_src()
        assert "inReel: z.boolean().default(false)" in src

    def test_story_self_fade_is_gated_on_in_reel(self):
        src = _story_src()
        assert re.search(
            r"card\.inReel\s*\n?\s*\?\s*1", src
        ), "inside a reel the beat must hold fully visible (the transition is the exit)"

    def test_reel_beats_pass_in_reel(self):
        assert "card={{ ...card, inReel: true }}" in _reel_src()

    def test_exit_wrap_exists_and_mirrors_the_spec(self):
        src = _reel_src()
        assert "const ExitWrap" in src
        wrap = src.split("const ExitWrap", 1)[1]
        # Velocity matching: the outgoing side accelerates.
        assert "Easing.in(Easing.cubic)" in wrap
        # Directional kinds get mirrored exits; the rest hold beneath.
        for kind in ("push", "whip", "zoom", "slide-stack"):
            assert f'kind === "{kind}"' in wrap, kind
        # Frame-pure — no CSS transitions, no wallclock, no randomness.
        assert "transition:" not in wrap and "@keyframes" not in wrap
        assert "Math.random" not in wrap and "Date.now" not in wrap

    def test_outgoing_beat_uses_the_next_beats_spec(self):
        src = _reel_src()
        assert "specs[i + 1].kind" in src
        assert "beatFades[i + 1]" in src
        # The cover's exit is the first beat's incoming spec.
        assert "kind={specs[0].kind}" in src

    def test_cover_self_fade_only_for_the_cardless_reel(self):
        src = _reel_src()
        assert "selfExit ? env.outroFade : 1" in src
        # The empty-cards early return is the only selfExit caller.
        assert src.count("selfExit\n") + src.count("selfExit ") >= 1
        body = src.split("if (safeCards.length === 0)", 1)[1].split("/>", 1)[0]
        assert "selfExit" in body


# =========================================================================== #
# M17 — legible outro
# =========================================================================== #
class TestM17LegibleOutro:
    def test_default_outro_is_two_and_a_half_seconds_everywhere(self):
        assert motion.REEL_OUTRO_SEC == 2.5
        src = _reel_src()
        assert "outroSec: z.number().default(2.5)" in src
        assert "rhythm.outroSec > 0 ? rhythm.outroSec : 2.5" in src

    def test_outro_ramps_leave_a_readable_hold(self):
        """CTA fully on by 0.9s; the self-fade takes the last 0.35s — with the
        2.5s default that is a ≥1.2s fully-readable hold."""
        outro = _reel_src().split("const OutroScreen", 1)[1].split("\n};", 1)[0]
        assert "[fps * 0.5, fps * 0.9]" in outro  # CTA opacity + Y
        assert "durationInFrames - fps * 0.35" in outro  # closing fade
        hold = 2.5 - 0.9 - 0.35
        assert hold >= 1.2

    def test_outro_stays_within_the_clamp_range(self):
        lo, hi = motion.REEL_OUTRO_RANGE
        assert lo <= motion.REEL_OUTRO_SEC <= hi

    def test_explicit_outro_callers_keep_full_control(self):
        assert motion.reel_duration_for(3, outro_sec=1.0) == 15.0
        r = motion.normalise_reel_rhythm({"outro": 1.0}, 3)
        assert r is not None and r["outroSec"] == 1.0


# =========================================================================== #
# M18 — brand-true cover/outro
# =========================================================================== #
class TestM18BrandTrueCover:
    def test_cover_roles_resolve_from_the_brand(self):
        brand_dict = motion._brand_to_dict(BRAND)
        roles = motion._cover_brand_roles(brand_dict, BRAND)
        assert roles, "a full brand kit must resolve bookend roles"
        for key in ("ground", "surface", "accent", "onGround"):
            assert roles[key].startswith("#"), key
        # The ground is the club's canonical primary (Tier A baseline).
        assert roles["ground"].upper() == "#0E2A47"

    def test_cover_props_carry_roles_typography_and_photo(self):
        cards = [
            {"typographyPair": "", "photoSrc": "", "photoPos": ""},
            {
                "typographyPair": "bebas-grotesk",
                "photoSrc": "data:image/jpeg;base64,xx",
                "photoPos": "center 30%",
            },
        ]
        props = motion._reel_cover_props(cards, motion._brand_to_dict(BRAND), BRAND)
        assert props["coverRoleGround"].startswith("#")
        assert props["coverTypography"] == "bebas-grotesk"
        assert props["coverPhotoSrc"] == "data:image/jpeg;base64,xx"
        assert props["coverPhotoPos"] == "center 30%"

    def test_cover_props_flow_into_the_reel_render(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        captured: dict = {}

        def _capture(
            *,
            composition_id,
            props,
            out_path,
            duration_sec=None,
            size=None,
            timeout=600,
            supersample=1.0,
        ):
            captured["props"] = props
            return _fake_run(
                composition_id=composition_id,
                props=props,
                out_path=out_path,
                duration_sec=duration_sec,
                size=size,
            )

        with mock.patch.object(motion, "_run_remotion", side_effect=_capture):
            motion.render_meet_reel([_card(1)], BRAND, tmp_path / "out" / "reel.mp4")
        assert captured["props"].get("coverRoleGround", "").startswith("#")
        assert captured["props"].get("coverRoleOnGround", "").startswith("#")

    def test_reel_manifest_records_the_cover_treatment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
            motion.render_meet_reel([_card(1)], BRAND, tmp_path / "out" / "reel.mp4")
        manifests = [
            json.loads(p.read_text())
            for p in motion._cache_dir().glob("*.json")
            if not p.name.endswith(".audio.json")
        ]
        reel = next(m for m in manifests if m.get("kind") == "reel")
        assert reel["cover"]["roles_source"] == "brand-resolved"
        assert reel["cover"]["role_ground"].startswith("#")
        assert reel["cover"]["has_photo"] is False

    def test_photo_cover_variant_is_pool_gated(self):
        src = _reel_src()
        assert "const PhotoCover" in src
        fn = src.split("export function coverVariantFor", 1)[1].split("\n}", 1)[0]
        assert "hasPhoto" in fn
        assert 'pool.push("photo")' in fn
        # Prop-less reels keep the original pools (and modulo pick).
        assert '["spotlight", "masthead", "stack", "banner"]' in fn
        assert '["masthead", "stack", "banner"]' in fn

    def test_photo_cover_is_full_bleed_with_a_role_scrim(self):
        body = _reel_src().split("const PhotoCover", 1)[1].split("\n};", 1)[0]
        assert "photoSrc" in body and "objectFit" in body
        assert "roles.ground || brand.primary" in body  # scrim colour is a role
        assert "Math.random" not in body and "Date.now" not in body

    def test_outro_consumes_the_cover_roles(self):
        outro = _reel_src().split("const OutroScreen", 1)[1].split("\n};", 1)[0]
        assert "roles.ground || brand.primary" in outro
        assert "roles.onGround || brand.accent" in outro

    def test_cover_typography_follows_the_top_card(self):
        src = _reel_src()
        assert "fontStackFor(coverTypography)" in src


# =========================================================================== #
# M19 — beat-proportional choreography + resolve accent
# =========================================================================== #
class TestM19ProportionalChoreography:
    def test_keyframes_are_fractions_of_the_clip(self):
        src = _story_src()
        # The proportional-keyframe helper (3-frame offset, strictly monotonic).
        assert "const at = (f: number) => 3 + (durationInFrames - 3) * f;" in src
        # The base build lands by ~30% (chips are the last entrance).
        assert "[at(0.17), at(0.26)]" in src

    def test_resolve_accent_channel_exists_and_fires_at_seventy_percent(self):
        src = _story_src()
        assert "resolveAccent: number" in src
        assert 'resolveAccentKind: "stat" | "underline" | "label" | "none"' in src
        assert "durationInFrames * 0.68" in src
        # Seed-picked among three expressions; mood scales the amplitude.
        assert '["stat", "underline", "label"]' in src
        assert "% 3" in src

    def test_static_intent_fires_no_resolve_accent(self):
        src = _story_src()
        static_case = src.split('case "static"', 1)[1].split("default:", 1)[0]
        assert 'resolveAccentKind: "none"' in static_case
        assert "resolveAccent: 0" in static_case

    def test_accent_expressions_execute(self):
        src = _story_src()
        # stat: the shared result re-pulse; label: chip scale; underline: layer.
        assert 'ch.resolveAccentKind === "stat"' in src
        assert 'anim.resolveAccentKind === "label"' in src
        assert "const ResolveAccentLayer" in src
        assert "<ResolveAccentLayer ctx={ctx} />" in src


# =========================================================================== #
# M20 — reel chrome + relay photos
# =========================================================================== #
def _reel_layer_src(name: str) -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "reel" / name).read_text()


class TestM20ReelChrome:
    def test_progress_rail_registered_and_frame_pure(self):
        src = _reel_layer_src("progress_rail.tsx")
        assert "export default { Layer" in src
        assert "beatStarts" in src and "outroStart" in src
        assert "ctx.frame" in src or "frame" in src
        assert "Math.random" not in src and "Date.now" not in src
        assert "transition:" not in src and "@keyframes" not in src
        # Painted only in the accent role — no invented hex.
        assert not re.findall(r"#[0-9a-fA-F]{3,6}", src)

    def test_club_mark_registered_and_brand_locked(self):
        src = _reel_layer_src("club_mark.tsx")
        assert "export default { Layer" in src
        assert "logoDataUri" in src and "clubLabel" in src
        assert "Math.random" not in src and "Date.now" not in src
        assert not re.findall(r"#[0-9a-fA-F]{3,6}", re.sub(r"//.*", "", src))

    def test_reel_ctx_carries_the_chrome_data(self):
        reg = (
            motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "reelRegistry.ts"
        ).read_text()
        for field in (
            "accent",
            "ground",
            "onGround",
            "clubLabel",
            "logoDataUri",
            "beatStarts",
            "outroStart",
        ):
            assert field in reg, field
        # MeetReel provides them.
        src = _reel_src()
        assert "beatStarts," in src and "outroStart," in src

    def test_card_schema_declares_photo_srcs(self):
        assert "photoSrcs: z.array(z.string()).default([])" in _story_src()

    def test_relay_collage_fills_panels_from_photo_srcs(self):
        src = (
            motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "scenes" / "relay_collage.tsx"
        ).read_text()
        assert "card.photoSrcs" in src
        assert "panelSrc" in src

    def test_split_scene_consumes_photo_srcs_for_duo_and_triptych(self):
        src = _story_src()
        assert 'card.archetype === "duo_athlete_split"' in src
        assert 'card.archetype === "triptych_progression"' in src

    def test_photo_srcs_resolved_from_linked_relay_athletes(self, tmp_path, monkeypatch):
        """A relay card naming individual swimmers pulls each linked athlete's
        best photo through select_assets; a single-athlete archetype gets []."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from PIL import Image

        from mediahub.media_library.models import MediaAsset
        from mediahub.media_library.store import MediaLibraryStore

        store = MediaLibraryStore(db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads")
        for i, name in enumerate(["Ada Lovelace", "Grace Hopper"]):
            p = tmp_path / f"athlete{i}.jpg"
            Image.new("RGB", (900, 1200), (10 + i, 60, 140)).save(p, "JPEG")
            store.save(
                MediaAsset(
                    id=f"asset-{i}",
                    filename=p.name,
                    path=str(p),
                    type="athlete_action",
                    linked_athlete_names=[name],
                    permission_status="user_owned",
                    approval_status="approved",
                    profile_id="phasec",
                )
            )
        monkeypatch.setattr("mediahub.media_library.store.get_store", lambda: store)

        card = {
            "achievement": {
                "swimmer_name": "Phase C relay",
                "relay_swimmers": ["Ada Lovelace", "Grace Hopper"],
            }
        }
        brief = {"layout_template": "relay_collage"}
        srcs = motion._photo_srcs_for_card(card, brief, BRAND)
        assert len(srcs) == 2
        assert all(s.startswith("data:image/jpeg;base64,") for s in srcs)
        # A single-hero archetype never pays the lookup.
        assert (
            motion._photo_srcs_for_card(card, {"layout_template": "big_number_dominant"}, BRAND)
            == []
        )
        # No individual names → honest empty (never guess a lineup).
        anon = {"achievement": {"swimmer_name": "Phase C relay"}}
        assert motion._photo_srcs_for_card(anon, brief, BRAND) == []

    def test_photo_srcs_only_attach_when_resolved(self):
        props = motion._card_to_props(_card(1), variation_seed=1)
        assert "photoSrcs" not in props, "empty photoSrcs must not touch the cache key"


# =========================================================================== #
# M21 — edited-photo parity (safeguarding blur reaches the MP4)
# =========================================================================== #
@pytest.fixture
def edited_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from PIL import Image

    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import MediaLibraryStore

    store = MediaLibraryStore(db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads")
    src = tmp_path / "face.jpg"
    im = Image.new("RGB", (640, 480), (200, 40, 40))
    for x in range(0, 640, 8):
        for y in range(0, 480, 8):
            im.putpixel((x, y), (0, 0, 0))
    im.save(src, "JPEG")
    asset = store.save(
        MediaAsset(id="edit-1", filename="face.jpg", path=str(src), type="athlete_action")
    )
    monkeypatch.setattr("mediahub.media_library.store.get_store", lambda: store)
    return store, asset, src


class TestM21EditedPhotoParity:
    def test_blur_recipe_feeds_the_same_bytes_to_still_and_motion(self, edited_asset):
        store, asset, src = edited_asset
        from mediahub.media_library import photo_edit
        from mediahub.media_library.photo_ops import EditRecipe

        brief = {"sourced_asset_ids": ["edit-1"]}
        # Unedited: motion reads the original, byte-identical to the still.
        assert motion._photo_asset_path_for_brief(brief) == src
        assert motion._photo_edit_signature_for_brief(brief) == ""
        before_uri = motion._photo_data_uri_for_brief(brief)

        recipe = EditRecipe.build([("blur", {"radius": 12})])
        asset = photo_edit.save_recipe(asset, recipe, store)
        # The motion path resolves through the SAME effective_image_path the
        # still pipeline reads — the safeguarding blur reaches the MP4.
        motion_path = motion._photo_asset_path_for_brief(brief)
        still_path = Path(photo_edit.effective_image_path(store.get("edit-1"), store))
        assert motion_path == still_path
        assert motion_path != src
        assert motion_path.read_bytes() == still_path.read_bytes()
        # The embedded bytes actually change.
        assert motion._photo_data_uri_for_brief(brief) != before_uri
        # And the recipe signature is exposed for the cache key.
        assert motion._photo_edit_signature_for_brief(brief) == recipe.canonical().signature()

    def test_edit_signature_folds_into_the_story_cache_key(self, edited_asset, tmp_path):
        store, asset, src = edited_asset
        from mediahub.media_library import photo_edit
        from mediahub.media_library.photo_ops import EditRecipe

        brief = {
            "sourced_asset_ids": ["edit-1"],
            "photo_treatment": "photo",
        }
        with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
            motion.render_story_card(_card(1), BRAND, tmp_path / "a.mp4", brief=brief)
            n_before = len(list(motion._cache_dir().glob("*.mp4")))
            photo_edit.save_recipe(
                store.get("edit-1"), EditRecipe.build([("blur", {"radius": 9})]), store
            )
            motion.render_story_card(_card(1), BRAND, tmp_path / "b.mp4", brief=brief)
        assert (
            len(list(motion._cache_dir().glob("*.mp4"))) == n_before + 1
        ), "an edited photo must re-render, never serve the pre-edit MP4"

    def test_exif_orientation_is_normalised_in_the_thumbnail(self, tmp_path):
        """A phone-portrait JPEG (EXIF orientation 6) must play upright."""
        from PIL import Image

        src = tmp_path / "rotated.jpg"
        im = Image.new("RGB", (400, 200), (10, 120, 60))
        exif = im.getexif()
        exif[0x0112] = 6  # rotate 90° CW to display
        im.save(src, "JPEG", exif=exif)

        uri = motion._photo_data_uri_for_path(src)
        assert uri.startswith("data:image/jpeg;base64,")
        decoded = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        assert (decoded.width, decoded.height) == (
            200,
            400,
        ), "EXIF orientation must be baked (transposed), not dropped"


# =========================================================================== #
# M22 — honest ffmpeg-engine manifests
# =========================================================================== #
def _stub_ffmpeg(monkeypatch, tmp_path):
    """Make the ffmpeg engine runnable without Playwright/FFmpeg binaries."""
    from PIL import Image

    def _fake_still(brief, brand_kit, out_dir, *, name, size=(1080, 1920), format_name="story"):
        p = Path(out_dir) / f"{name}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (10, 20, 30)).save(p, "PNG")
        return p

    def _fake_run_ffmpeg(args, *, timeout=600):
        out = Path(args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 4096)

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")
    monkeypatch.setattr(reel_ffmpeg, "_require_available", lambda: "ffmpeg")
    monkeypatch.setattr(reel_ffmpeg, "_render_still", _fake_still)
    monkeypatch.setattr(reel_ffmpeg, "_run_ffmpeg", _fake_run_ffmpeg)


def _cache_manifests() -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in motion._cache_dir().glob("*.json")
        if not p.name.endswith(".audio.json") and p.parent == motion._cache_dir()
    ]


class TestM22FfmpegManifests:
    def test_ffmpeg_story_writes_the_remotion_manifest_shape(self, tmp_path, monkeypatch):
        _stub_ffmpeg(monkeypatch, tmp_path)
        with mock.patch.object(motion, "_run_remotion") as remotion_run:
            motion.render_story_card(_card(1), BRAND, tmp_path / "s.mp4")
            assert not remotion_run.called
        manifests = _cache_manifests()
        assert manifests, "the ffmpeg story must write an explainability sidecar"
        m = manifests[0]
        assert m["kind"] == "story"
        assert m["engine"] == "ffmpeg"
        assert m["format"] == "story"
        assert m["duration_sec"] == 6.0
        # Same per-card axes the Remotion manifest records.
        assert "motion_intent" in m["card"] and "variation_seed" in m["card"]
        assert m["kb_variant"] in (*reel_ffmpeg.KEN_BURNS_VARIANTS, "parallax", "hold")
        assert "audio" in m and "poster" in m
        assert "engine_note" in m["notes"]

    def test_ffmpeg_reel_writes_manifest_with_honest_notes(self, tmp_path, monkeypatch):
        _stub_ffmpeg(monkeypatch, tmp_path)
        with mock.patch.object(motion, "_run_remotion") as remotion_run:
            motion.render_meet_reel([_card(1), _card(2)], BRAND, tmp_path / "reel.mp4")
            assert not remotion_run.called
        reel = next(m for m in _cache_manifests() if m.get("kind") == "reel")
        assert reel["engine"] == "ffmpeg"
        assert len(reel["cards"]) == 2
        # kb-variant per still (cover + cards) and one xfade per join.
        assert len(reel["kb_variants"]) == 3
        assert len(reel["transitions"]) == 2
        # Honest capability notes: no burned captions, static cover chips.
        assert reel["captions"] == {"status": "unsupported-on-engine"}
        assert reel["notes"]["captions"] == "unsupported-on-engine"
        assert reel["notes"]["stat_chips"] == "static-cover"
        assert "engine_note" in reel["notes"]
