"""R1.30 — Reel cover & outro redesign system.

Two coordinated upgrades to the meet reel's bookend scenes (the
`CoverScreen` / `OutroScreen` region of `MeetReel.tsx`, plus a thin,
guarded thread through `render_meet_reel` and the reel web route):

  * **Data-driven cover variants** — the cover is no longer one fixed
    layout. A per-meet seed (stable, FNV-1a over the meet identity) picks
    among four structurally-distinct covers (stack / masthead / spotlight
    / banner), and the meet's HONEST stats bias the pool: a medal/PB-heavy
    weekend can lead with a big counted-up number (spotlight), a quiet one
    never fabricates a hero stat it doesn't have. Same meet → same cover
    (deterministic); different meets → different covers (anti-samey).

  * **Outro CTA variants** — the close picks its call-to-action from the
    data: a sponsor thank-you when the club configured one, a "next up"
    nudge when a next meet was supplied, else the universal follow-the-club
    close. Honest: it only ever names a sponsor / next meet the caller
    actually passed; the sponsor is sourced from the club's real registry /
    legacy `sponsor_name` by the reel route.

The TSX is checked as a source contract (same shape the existing parity
suites use — no Node needed); the Python thread + web wiring are checked
behaviourally with `_run_remotion` / `render_meet_reel` stubbed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from mediahub.visual import motion


# --------------------------------------------------------------------------- #
# Source readers
# --------------------------------------------------------------------------- #
def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


def _cover_outro_region() -> str:
    """The CoverScreen→OutroScreen region only (excludes the reel assembly
    and the transition wrapper that live after `export const MeetReel`)."""
    src = _reel_src()
    return src.split("// Cover — a data-driven variant SYSTEM", 1)[1].split(
        "export const MeetReel", 1
    )[0]


# =========================================================================== #
# 1) Cover variant system — data-driven, deterministic, honest
# =========================================================================== #
class TestCoverVariants:
    def test_four_distinct_cover_variants_exist(self):
        src = _reel_src()
        assert 'export type CoverVariant = "stack" | "masthead" | "spotlight" | "banner"' in src
        for comp in ("StackCover", "MastheadCover", "SpotlightCover", "BannerCover"):
            assert f"const {comp}" in src, f"cover variant component {comp} missing"

    def test_cover_is_chosen_deterministically_from_a_per_meet_seed(self):
        src = _reel_src()
        # A pure string hash seeds the pick — no non-deterministic CALLS
        # (the paren form avoids matching the "no Math.random" doc comment).
        assert "function reelSeed(" in src
        assert "Math.random(" not in src and "Date.now(" not in src
        # CoverScreen dispatches via the seeded, stats-aware picker.
        assert "export function coverVariantFor(" in src
        assert "coverVariantFor(" in src and "reelSeed(" in src

    def test_cover_selection_is_data_driven_and_honest(self):
        """The stat-forward 'spotlight' cover is only ever eligible when the
        weekend actually produced a number worth leading with — a quiet
        weekend's pool excludes it, so the cover never fabricates a hero stat."""
        fn = _reel_src().split("export function coverVariantFor", 1)[1].split("\n}", 1)[0]
        assert "statForward" in fn
        assert "stats.medals > 0 || stats.pbs >= 2" in fn
        # spotlight present in the stat-forward pool, absent from the quiet pool.
        assert '["spotlight", "masthead", "stack", "banner"]' in fn
        assert '["masthead", "stack", "banner"]' in fn
        # Deterministic index into the eligible pool.
        assert "seed % pool.length" in fn

    def test_spotlight_leads_with_an_honest_counted_up_number(self):
        """The spotlight hero numeral derives ONLY from reelStats (medals →
        PBs → swims) and counts up to land on EXACTLY that verified total —
        never a fabricated figure."""
        src = _reel_src()
        spot = src.split("const SpotlightCover", 1)[1].split("\n};", 1)[0]
        # Hero number is one of the honest stat totals, in priority order.
        assert "stats.medals > 0" in spot
        assert "stats.pbs > 0" in spot
        assert "stats.swims" in spot
        # Count-up lands on the true total: round(n · progress) → n at progress 1.
        assert "Math.round(hero.n * countP)" in spot
        # Stacked/animated number carries tabular figures (no width jitter).
        assert "tabular-nums" in spot

    def test_every_cover_variant_is_brand_locked(self):
        """Variants paint text only from the brand roles (accent on the
        primary ground; secondary for bars) — the reel cover's legibility
        contract. Each variant references the brand palette, never a fresh hex."""
        for comp in ("StackCover", "MastheadCover", "SpotlightCover", "BannerCover"):
            body = _reel_src().split(f"const {comp}", 1)[1].split("\n};", 1)[0]
            assert "brand.accent" in body, f"{comp} ignores the brand accent"
            assert "brand.primary" in body or "ground" in body, comp
            assert "brand.secondary" in body, f"{comp} never uses the brand secondary"


# =========================================================================== #
# 2) Outro CTA system — follow / next-meet / sponsor, data-driven + honest
# =========================================================================== #
class TestOutroCtaVariants:
    def test_three_cta_kinds_exist(self):
        src = _reel_src()
        assert 'export type OutroCtaKind = "sponsor" | "next_meet" | "follow"' in src
        assert "export function outroCtaFor(" in src

    def test_cta_priority_is_sponsor_then_next_meet_then_follow(self):
        """A paying sponsor's thank-you is the most valuable close, then a
        next-meet nudge, then the always-available follow. The function checks
        them in that order."""
        fn = _reel_src().split("export function outroCtaFor", 1)[1].split("\n}", 1)[0]
        i_sponsor = fn.find('kind: "sponsor"')
        i_next = fn.find('kind: "next_meet"')
        i_follow = fn.find('kind: "follow"')
        assert -1 < i_sponsor < i_next < i_follow, "CTA priority order is wrong"
        # Sponsor / next-meet are only emitted when actually supplied (honest).
        assert "const s = (sponsor || \"\").trim();" in fn and "if (s) {" in fn
        assert "const nm = (nextMeet || \"\").trim();" in fn and "if (nm) {" in fn
        # Follow handle reads off the brand, never invented.
        assert "brand.shortName || brand.displayName" in fn

    def test_outro_consumes_the_cta_inputs_and_keeps_the_meet_secondary(self):
        outro = _reel_src().split("const OutroScreen", 1)[1].split("\n};", 1)[0]
        assert "sponsor: string;" in outro and "nextMeet: string;" in outro
        assert "const cta = outroCtaFor(brand, sponsor, nextMeet);" in outro
        # When a sponsor thank-you is the primary close but a next meet is also
        # known, the next meet rides along as the quiet secondary line.
        assert 'cta.kind === "sponsor"' in outro and "NEXT UP ·" in outro


# =========================================================================== #
# 3) Schema + parity preservation (the redesign keeps every public contract)
# =========================================================================== #
class TestSchemaAndParity:
    def test_schema_declares_optional_cta_inputs(self):
        src = _reel_src()
        schema = src.split("export const meetReelSchema", 1)[1].split("});", 1)[0]
        assert 'sponsor: z.string().default("")' in schema
        assert 'nextMeet: z.string().default("")' in schema

    def test_parity_contracts_still_hold(self):
        """The redesign must not drop any of the surfaces the motion parity
        suite pins."""
        src = _reel_src()
        for token in (
            "OutroScreen",
            "export function reelStats",
            "export function transitionFor",
            "chipsProgress",
            "progress: number",
            'stats.pbs === 1 ? "" : "S"',
            'from "./StoryCard"',
            "cardSchema",
        ):
            assert token in src, f"parity contract {token!r} lost in the redesign"
        # reelStats stays honest (label-derived medals, never a bare place).
        stats_fn = src.split("export function reelStats", 1)[1].split("\n}", 1)[0]
        assert "achievementLabel" in stats_fn and ".place" not in stats_fn

    def test_cover_and_outro_motion_is_frame_pure(self):
        """No CSS transitions / @keyframes in the bookend scenes — motion is a
        pure function of the frame (Remotion interpolate/spring only)."""
        region = _cover_outro_region()
        assert "transition:" not in region
        assert "@keyframes" not in region
        # The redesign does animate (it isn't a static slide).
        assert "interpolate(" in region and "spring(" in region


# =========================================================================== #
# 4) Python thread — render_meet_reel forwards the CTA inputs, guarded
# =========================================================================== #
BRAND = {
    "profile_id": "r130",
    "display_name": "R130 Swimming Club",
    "short_name": "R130SC",
    "primary_colour": "#0E2A47",
    "secondary_colour": "#C9A227",
}


def _card(i: int) -> dict:
    return {
        "id": f"swim-{i}",
        "swim_id": f"swim-{i}",
        "achievement": {
            "swim_id": f"swim-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "R130 Invitational",
    }


def _render_reel_capture(tmp_path, monkeypatch, cards, **kwargs):
    """Run render_meet_reel with _run_remotion stubbed; return the captured call."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_meet_reel(cards, BRAND, tmp_path / "out" / "reel.mp4", **kwargs)
    return captured


class TestRenderMeetReelThread:
    def test_sponsor_flows_into_the_props(self, tmp_path, monkeypatch):
        cap = _render_reel_capture(tmp_path, monkeypatch, [_card(1)], sponsor="Acme Corp")
        assert cap["props"].get("sponsor") == "Acme Corp"

    def test_next_meet_flows_into_the_props(self, tmp_path, monkeypatch):
        cap = _render_reel_capture(
            tmp_path, monkeypatch, [_card(1)], next_meet="County Champs"
        )
        assert cap["props"].get("nextMeet") == "County Champs"

    def test_both_ride_together_and_are_whitespace_trimmed(self, tmp_path, monkeypatch):
        cap = _render_reel_capture(
            tmp_path, monkeypatch, [_card(1)], sponsor="  Speedo  ", next_meet="  Finals  "
        )
        assert cap["props"].get("sponsor") == "Speedo"
        assert cap["props"].get("nextMeet") == "Finals"

    def test_absent_cta_keeps_props_byte_identical(self, tmp_path, monkeypatch):
        """No sponsor / next meet → the CTA keys are simply absent, so a reel
        without them stays identical to before R1.30 landed."""
        cap = _render_reel_capture(tmp_path / "a", monkeypatch, [_card(1)])
        assert "sponsor" not in cap["props"]
        assert "nextMeet" not in cap["props"]
        # blank/whitespace strings are treated the same as absent (fresh
        # DATA_DIR so this is a cache miss we can inspect, not a cache hit).
        cap2 = _render_reel_capture(
            tmp_path / "b", monkeypatch, [_card(1)], sponsor="   ", next_meet=""
        )
        assert "sponsor" not in cap2["props"] and "nextMeet" not in cap2["props"]

    def test_sponsor_changes_the_cache_key(self, tmp_path, monkeypatch):
        """A sponsored reel and an unsponsored one of the same cards must not
        collide in the motion cache (a stale cross-hit would drop the close)."""
        _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
        _render_reel_capture(tmp_path, monkeypatch, [_card(1)], sponsor="Acme Corp")
        cache = motion._cache_dir()
        assert len(list(cache.glob("*.mp4"))) == 2

    def test_unsponsored_rerender_still_hits_cache(self, tmp_path, monkeypatch):
        """The guard must not bust the cache for the common (no-CTA) path."""
        _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        with mock.patch.object(motion, "_run_remotion") as rerun:
            motion.render_meet_reel([_card(1)], BRAND, tmp_path / "o2" / "reel.mp4")
        rerun.assert_not_called()

    def test_manifest_records_the_cta(self, tmp_path, monkeypatch):
        _render_reel_capture(tmp_path, monkeypatch, [_card(1)], sponsor="Acme Corp")
        manifests = list(motion._cache_dir().glob("*.json"))
        assert manifests
        data = json.loads(manifests[0].read_text())
        assert data["cta"] == {"sponsor": "Acme Corp"}


# =========================================================================== #
# 5) Web wiring — the reel route sources the sponsor from the real profile
# =========================================================================== #
@pytest.fixture
def reel_app(tmp_path, monkeypatch):
    import importlib

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

    save_profile(ClubProfile(profile_id="sponsored", display_name="Sponsored SC", sponsor_name="Speedo"))
    save_profile(ClubProfile(profile_id="plain", display_name="Plain SC"))

    def _run(rid: str, pid: str) -> None:
        run = {
            "run_id": rid,
            "profile_id": pid,
            "meet_name": "Spring Open",
            "meet": {"name": "Spring Open"},
            "recognition_report": {
                "ranked_achievements": [
                    {
                        "id": "swim-1",
                        "priority": 0.9,
                        "achievement": {
                            "swim_id": "swim-1",
                            "swimmer_name": "Eira Hughes",
                            "event": "100m Freestyle",
                            "time": "59.80",
                        },
                    }
                ]
            },
        }
        (wm.RUNS_DIR / f"{rid}.json").write_text(json.dumps(run), encoding="utf-8")

    _run("rs", "sponsored")
    _run("rp", "plain")
    return app, wm, tmp_path


def _capture_reel_sponsor(app, wm, run_id: str):
    import mediahub.visual.motion as motion

    out_dir = wm.RUNS_DIR / run_id / "motion"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "reel_3.mp4"
    mp4.write_bytes(b"0" * 2048)
    captured: dict = {}

    def _cap(*a, **k):
        captured.update(k)
        return mp4

    profile = "sponsored" if run_id == "rs" else "plain"
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": profile})
        with mock.patch.object(motion, "render_meet_reel", side_effect=_cap):
            resp = c.post(f"/api/runs/{run_id}/reel")
            assert resp.status_code == 200, resp.get_data(as_text=True)
    return captured


class TestReelRouteSponsorWiring:
    def test_route_passes_the_clubs_real_sponsor(self, reel_app):
        app, wm, _ = reel_app
        captured = _capture_reel_sponsor(app, wm, "rs")
        assert captured.get("sponsor") == "Speedo"

    def test_route_passes_empty_sponsor_for_a_club_without_one(self, reel_app):
        app, wm, _ = reel_app
        captured = _capture_reel_sponsor(app, wm, "rp")
        assert captured.get("sponsor") == ""
