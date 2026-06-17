"""R1.14 — Reel transition library expansion + per-card timing.

The meet reel's beat handoffs gain three new bold cuts and a per-card duration:

  * **Library expansion** — `glitch` (a deterministic digital jolt that
    resolves clean), `slide-stack` (a structured slide that settles onto its
    rest position) and `light-sweep` (a brand-accent glint sweeping across a
    celebration beat) join the bold catalog the *peak* beat draws from. The
    quiet connective handoffs stay the original three (crossfade/push/wipe) so
    a reel still reads as one continuous piece with one bold accent
    (motion-craft transitions.md).
  * **Per-card timing** — `transitionFor` now returns a `(kind, durationSeconds)`
    spec, and the reel converts each beat's duration to a frame window
    (`transitionFramesFor`) capped at the handoff budget, so a snappy glitch
    flicks and a reveal breathes without ever eating the next beat's build.

The owner region is `MeetReel.tsx` `transitionFor` + `TransitionWrap`; the only
Python touch is a reel cache-revision token so the upgrade reaches re-requested
meets rather than serving a stale cut.

The TSX is checked as a source contract (the shape the existing parity suites
use) AND, when Node + the Remotion deps are present, genuinely type-checked
with `tsc --noEmit`. No real render is required.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from mediahub.visual import motion


NEW_KINDS = ("glitch", "slide-stack", "light-sweep")
ORIGINAL_CONNECTIVE = ("crossfade", "push", "wipe")


def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


def _wrap_region(src: str) -> str:
    """The TransitionWrap body — the frame-pure execution of each kind."""
    return src.split("const TransitionWrap", 1)[1]


def _transition_for_body(src: str) -> str:
    return src.split("export function transitionFor", 1)[1].split(
        "export function transitionFramesFor", 1
    )[0]


# --------------------------------------------------------------------------- #
# Library expansion — the three new kinds exist and execute frame-pure
# --------------------------------------------------------------------------- #


def test_new_transition_kinds_are_declared():
    src = _reel_src()
    # The original vocabulary survives (back-compat for the connective +
    # the earlier bold cuts)…
    for kind in (*ORIGINAL_CONNECTIVE, "blur", "zoom", "whip", "iris"):
        assert f'"{kind}"' in src, kind
    # …and the three R1.14 cuts join it.
    for kind in NEW_KINDS:
        assert f'"{kind}"' in src, f"new transition kind {kind!r} not declared"


def test_every_new_kind_has_a_frame_pure_branch():
    """Each new kind must be executed in TransitionWrap as a frame-derived
    transform / opacity / clip / filter — never a CSS transition (which does
    not render under Remotion)."""
    wrap = _wrap_region(_reel_src())
    for kind in NEW_KINDS:
        assert f'kind === "{kind}"' in wrap, f"{kind} not executed in TransitionWrap"
    # No CSS transitions / keyframes anywhere in the wrapper (motion is a pure
    # function of the frame — this guard already covered the old kinds).
    assert "transition:" not in wrap and "@keyframes" not in wrap
    # The new branches ride the shared fadeInFrames window like the rest.
    assert "interpolate(frame, [0, fadeInFrames]" in wrap


def test_new_branches_are_deterministic_no_wallclock_or_random():
    """Same props → byte-identical render: no Math.random() / Date.now() /
    new Date() *calls* (the glitch jolt derives its jitter from the frame, not
    randomness).

    Checks for actual invocations, not the bare names — a sibling scene may
    legitimately carry a comment documenting the contract ("no Math.random /
    Date.now here"), and that prose must not trip the guard.
    """
    src = _reel_src()
    assert "Math.random(" not in src
    assert "Date.now(" not in src
    assert "new Date(" not in src


# --------------------------------------------------------------------------- #
# Per-card timing — transitionFor returns a (kind, duration) spec
# --------------------------------------------------------------------------- #


def test_transition_for_returns_a_kind_and_duration_field():
    src = _reel_src()
    # The picker is still the named, deterministic, peak/mood-aware function…
    assert "export function transitionFor" in src
    assert "peak" in src and "mood" in src
    # …and now carries the duration field on a spec type.
    assert "TransitionSpec" in src
    assert "durationSeconds" in src
    assert "kind:" in src and "durationSeconds:" in src
    # A duration table backs every kind.
    assert "TRANSITION_SECONDS" in src


def test_duration_table_has_a_value_per_kind_within_the_budget():
    """Every kind has a duration, and none exceeds the ~0.35s handoff budget
    (transitions.md: a transition must never outlast the overlap it plays
    against). The quiet connective cuts sit exactly at the budget so existing
    reels keep their pre-R1.14 timing."""
    src = _reel_src()
    table = src.split("TRANSITION_SECONDS", 1)[1].split("};", 1)[0]
    pairs = re.findall(r'"?([a-zA-Z-]+)"?\s*:\s*([0-9.]+)', table)
    durations = {k: float(v) for k, v in pairs}
    for kind in (*ORIGINAL_CONNECTIVE, "blur", "zoom", "whip", "iris", *NEW_KINDS):
        assert kind in durations, f"{kind} missing a duration"
        assert 0.0 < durations[kind] <= 0.35, (kind, durations[kind])
    # The connective trio fills the whole window (byte-identical timing).
    for kind in ORIGINAL_CONNECTIVE:
        assert durations[kind] == 0.35, kind
    # A glitch is genuinely snappier than a reveal — per-card timing is real,
    # not cosmetic.
    assert durations["glitch"] < durations["light-sweep"]
    assert durations["whip"] < durations["blur"]


def test_per_card_duration_is_capped_at_the_handoff_budget():
    """`transitionFramesFor` converts a duration to a frame window, floored so
    it never degenerates and capped at the beat's budget."""
    src = _reel_src()
    assert "export function transitionFramesFor" in src
    fn = src.split("export function transitionFramesFor", 1)[1].split("\n}", 1)[0]
    assert "Math.min(budgetFrames" in fn  # never longer than the overlap
    assert "Math.max(floor" in fn  # never shorter than the floor


def test_reel_wires_the_spec_kind_and_per_card_window_into_the_wrapper():
    """The reel must consume the spec: pick a kind, derive that beat's frame
    window from its duration, and pass both into TransitionWrap (instead of the
    old single fixed `transitionFrames` for every beat)."""
    src = _reel_src()
    assert "transitionFramesFor(spec.durationSeconds, transitionFrames, fps)" in src
    assert "kind={spec.kind}" in src
    assert "fadeInFrames={fadeFrames}" in src
    # Peak still earns the bold cut; the connective spec is shared.
    assert "const connective = transitionFor(" in src
    assert "isPeak" in src


# --------------------------------------------------------------------------- #
# Narrative discipline — new cuts are peak-only; connective stays quiet
# --------------------------------------------------------------------------- #


def test_new_kinds_are_peak_only_not_connective():
    """One bold accent per reel: the three new cuts may only be chosen for the
    peak beat. The connective tail must keep yielding the quiet original
    three."""
    body = _transition_for_body(_reel_src())
    peak_block, connective_tail = body.split("const mode =", 1)
    # Every new kind is selectable in the peak block…
    for kind in NEW_KINDS:
        assert f'"{kind}"' in peak_block, f"{kind} not offered to the peak beat"
    # …and none leaks into the connective handoff selection.
    for kind in NEW_KINDS:
        assert f'"{kind}"' not in connective_tail, f"{kind} leaked into connective cuts"
    for kind in ORIGINAL_CONNECTIVE:
        assert f'"{kind}"' in connective_tail, f"connective lost {kind}"


def test_light_sweep_glints_the_brand_accent_not_an_invented_colour():
    """The light-sweep is the only new kind that paints a colour — it must use
    the resolved accent threaded through the wrapper, never a hard-coded brand
    hex (white is tolerated only as the no-accent fallback)."""
    src = _reel_src()
    # The wrapper accepts the accent and the reel passes the card's resolved one.
    assert "accent?: string" in src
    assert "card.roleAccent || brand.accent" in src
    wrap = _wrap_region(src)
    sweep = wrap.split('kind === "light-sweep"', 1)[1].split("if (kind ===", 1)[0]
    assert "accent ||" in sweep  # accent-first, fallback second
    # The only hex permitted in the sweep is the white fallback.
    hexes = set(re.findall(r"#[0-9a-fA-F]{3,6}", sweep))
    assert hexes <= {"#FFFFFF"}, f"unexpected hard-coded colour in light-sweep: {hexes}"


# --------------------------------------------------------------------------- #
# Real compile gate — the TSX actually type-checks (when Node + deps present)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not (motion.node_available() and motion.remotion_installed()),
    reason="Node + Remotion node_modules required for the tsc type-check gate",
)
def test_meet_reel_typechecks_with_tsc():
    """Strongest signal that the change actually builds: the strict-mode
    TypeScript compiler accepts the whole composition, new kinds and all."""
    tsc = motion.REMOTION_DIR / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        pytest.skip("typescript compiler not installed in remotion node_modules")
    proc = subprocess.run(
        [str(tsc), "--noEmit"],
        cwd=str(motion.REMOTION_DIR),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"


# --------------------------------------------------------------------------- #
# Python — reel cache revision retires stale reels without breaking hits
# --------------------------------------------------------------------------- #


BRAND = {
    "profile_id": "r114",
    "display_name": "R114 Swimming Club",
    "primary_colour": "#0E2A47",
    "secondary_colour": "#C9A227",
}


def _card(i: int) -> dict:
    return {
        "id": f"swim-r114-{i}",
        "swim_id": f"swim-r114-{i}",
        "achievement": {
            "swim_id": f"swim-r114-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "R114 Invitational",
    }


def _render_reel_capture(tmp_path, monkeypatch, cards, **kwargs):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    real_hash = motion._content_hash

    def _capture_hash(payload, *, kind):
        if kind == "reel":
            captured["payload"] = payload
        return real_hash(payload, kind=kind)

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run), mock.patch.object(
        motion, "_content_hash", side_effect=_capture_hash
    ):
        result = motion.render_meet_reel(
            cards, BRAND, tmp_path / "out" / "reel.mp4", **kwargs
        )
    return captured, result


def test_revision_constant_exists_and_is_a_token():
    assert isinstance(motion.REEL_COMPOSITION_REVISION, str)
    assert motion.REEL_COMPOSITION_REVISION.strip()


def test_reel_cache_key_folds_in_the_composition_revision(tmp_path, monkeypatch):
    cap, _ = _render_reel_capture(tmp_path, monkeypatch, [_card(1), _card(2)])
    assert cap["payload"]["rev"] == motion.REEL_COMPOSITION_REVISION


def test_reel_manifest_records_the_composition_revision(tmp_path, monkeypatch):
    _, result = _render_reel_capture(tmp_path, monkeypatch, [_card(1), _card(2)])
    import json

    manifest = Path(result).with_suffix(".json")
    assert manifest.exists(), "reel render must write an explainability manifest"
    data = json.loads(manifest.read_text())
    assert data["kind"] == "reel"
    assert data["composition_revision"] == motion.REEL_COMPOSITION_REVISION


def test_revision_is_constant_so_cache_hits_still_land(tmp_path, monkeypatch):
    """The token is constant across renders of the same payload — it retires
    *old* caches, it does not defeat the cache for the same input."""
    _render_reel_capture(tmp_path, monkeypatch, [_card(1)])
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with mock.patch.object(motion, "_run_remotion") as rerun:
        motion.render_meet_reel([_card(1)], BRAND, tmp_path / "out2" / "reel.mp4")
    rerun.assert_not_called()
