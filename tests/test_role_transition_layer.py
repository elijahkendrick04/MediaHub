"""R1.22 — colour-role transition overlay (``sprint/layers/role_transition.tsx``).

The reel-generator sprint's first additive overlay layer: a colour-role
transition animation across the clip (fade / gradient / pulse) that is
**APCA-safe every frame**. It washes a resolved *role* colour over the scene
and clamps the wash, on every frame, to the largest opacity that keeps every
text/background role pair above the exact APCA ``Lc`` floor the still engine
required (``quality/compliance.py``) — so the motion is never a frame less
legible than the approved still.

Two layers of verification:

* **Source contracts (pure Python, always run)** — the file is a conforming
  registry drop-in, paints only role colours, uses a radial (not full-frame
  linear) gradient, is a deterministic function of the frame, and ports the
  APCA constants/thresholds verbatim from ``theming.contrast`` /
  ``quality.compliance``.
* **Runtime proof (esbuild + Node; skipped when absent)** — bundles the REAL
  ``.tsx`` and executes its exported helpers, proving the APCA port matches the
  Python reference and that the per-frame opacity cap actually keeps every
  guarded pair legible across the whole ``[0, cap]`` range it can render.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from mediahub.quality import compliance as _compliance
from mediahub.theming import contrast as _contrast
from mediahub.theming.contrast import apca
from mediahub.visual import motion

SPRINT = motion.REMOTION_DIR / "src" / "compositions" / "sprint"
LAYER = SPRINT / "layers" / "role_transition.tsx"
REGISTRY = SPRINT / "registry.ts"


def _src() -> str:
    return LAYER.read_text()


# ===========================================================================
# Source contracts (no Node needed)
# ===========================================================================


def test_layer_lives_in_the_registry_layers_folder():
    assert LAYER.exists(), "R1.22 builds sprint/layers/role_transition.tsx"
    assert LAYER.suffix == ".tsx"
    assert LAYER.parent.name == "layers"


def test_default_export_is_a_conforming_layer_module():
    src = _src()
    # The drop-in contract: default-export { Layer, order } (../registry).
    assert re.search(r"export default \{\s*Layer,\s*order:", src), (
        "must default-export { Layer, order } per the registry contract"
    )
    assert re.search(r"const Layer: SceneComponent =", src), (
        "Layer must be typed as a SceneComponent receiving { ctx }"
    )
    assert 'from "../registry"' in src, "types come from one place (../registry)"


def test_order_is_low_so_later_overlays_paint_on_top():
    m = re.search(r"order:\s*(\d+)", _src())
    assert m, "the module must declare a numeric paint order"
    # A colour grade sits UNDER future text-fx / captions / logo overlays.
    assert int(m.group(1)) < 10, "the colour-grade wash should paint early (low order)"


def test_registry_auto_discovers_tsx_layers():
    reg = REGISTRY.read_text()
    assert 'require.context("./layers"' in reg, "layers folder must be enumerated"
    assert r"/\.tsx?$/" in reg, "the enumerator must match .ts/.tsx files"
    # EXTRA_LAYERS keeps only modules that expose a Layer — our default does.
    assert "EXTRA_LAYERS" in reg and "m.Layer" in reg


def test_all_three_documented_modes_are_implemented():
    src = _src()
    for mode in ("fade", "gradient", "pulse"):
        assert f'"{mode}"' in src, f"mode {mode!r} (roadmap R1.22) must exist"


def test_pure_function_of_the_frame_no_randomness_or_wall_clock():
    src = _src()
    # Match the CALL form so the "no Math.random/Date.now" doc note doesn't
    # trip the guard against itself.
    assert "Math.random(" not in src, "motion must be deterministic (no Math.random)"
    assert "Date.now(" not in src and "new Date(" not in src, "no wall-clock reads"
    # Animation derives from the frame via Remotion primitives + frame-pure trig.
    assert "useVideoConfig" in src and "ctx.frame" in src
    assert "interpolate" in src


def test_brand_locked_paints_only_resolved_roles_never_an_invented_hex():
    src = _src()
    # The wash colour comes only from washTarget(), which returns a role.
    target_fn = src.split("export function washTarget", 1)[1].split("\n}", 1)[0]
    assert "roles.accent" in target_fn and "roles.surface" in target_fn
    # No invented colour literals anywhere in the code: no rgb()/rgba()/hsl()
    # and no quoted hex string. (The doc comments mention `#RGB` in backticks,
    # which this quoted-literal probe deliberately ignores.)
    assert "rgba(" not in src and "rgb(" not in src and "hsl(" not in src
    assert not re.search(r"""['"]#[0-9a-fA-F]{3,8}['"]""", src), (
        "no hard-coded hex colour literal — colours are resolved roles only"
    )


def test_gradient_mode_is_radial_not_a_full_frame_linear():
    src = _src()
    # motion-craft: no full-frame linear gradient on a dark ground (H.264 banding).
    assert "radial-gradient" in src
    assert "linear-gradient" not in src


def test_apca_constants_are_ported_verbatim_from_theming_contrast():
    src = _src()
    sa = _contrast._SA98G
    for key in (
        "mainTRC",
        "sRco",
        "sGco",
        "sBco",
        "normBG",
        "normTXT",
        "revTXT",
        "revBG",
        "blkThrs",
        "blkClmp",
        "scaleBoW",
        "loBoWoffset",
        "loClip",
    ):
        assert str(sa[key]) in src, f"APCA constant {key}={sa[key]} missing from the port"


def test_thresholds_match_quality_compliance_module():
    src = _src()
    assert f"LC_LARGE = {int(_compliance.LC_LARGE)}" in src
    assert f"LC_SUPPORT = {int(_compliance.LC_SUPPORT)}" in src
    # The primary name+labels pair is guarded at the stricter support floor.
    assert "lc: LC_SUPPORT" in src and "lc: LC_LARGE" in src


def test_legacy_and_director_static_cards_stay_inert():
    src = _src()
    plan = src.split("export function planMode", 1)[1].split("\n}", 1)[0]
    assert "hasDirection" in plan, "brief-less callers must render byte-identically"
    assert '"static"' in plan, "the director's static intent must disable the wash"
    assert plan.count("return null") >= 2


def test_overlay_is_inert_to_layout_and_input():
    src = _src()
    assert 'pointerEvents: "none"' in src, "an overlay must never capture input"
    assert "aria-hidden" in src, "a decorative wash must be hidden from a11y tree"
    assert "AbsoluteFill" in src, "a full-frame overlay"


def test_pure_helpers_are_exported_for_runtime_verification():
    src = _src()
    for fn in (
        "export function hexToRgb",
        "export function apcaLc",
        "export function over",
        "export function guardedPairs",
        "export function maxSafeAlpha",
        "export function planMode",
        "export function washTarget",
    ):
        assert fn in src, f"{fn} must be exported so the safety maths is testable"


# ===========================================================================
# Runtime proof — bundle the real .tsx with esbuild and execute its helpers
# ===========================================================================

_HARNESS = r"""
import * as L from "%(bundle)s";
import fs from "node:fs";
const req = JSON.parse(fs.readFileSync(0, "utf8"));
const out = {};

out.shape = {
  hasLayer: !!(L.default && typeof L.default.Layer === "function"),
  order: L.default ? L.default.order : null,
  lcLarge: L.LC_LARGE,
  lcSupport: L.LC_SUPPORT,
};

if (req.apca) {
  out.apca = req.apca.map(([f, b]) => L.apcaLc(L.hexToRgb(f), L.hexToRgb(b)));
}
if (req.blend) {
  out.blend = req.blend.map(([a, b, t]) => L.over(L.hexToRgb(a), L.hexToRgb(b), t));
}
if (req.plan) {
  out.plan = req.plan.map((c) => L.planMode(c));
}
if (req.target) {
  out.target = req.target.map(({ roles, seed }) => L.washTarget(roles, seed));
}
if (req.safety) {
  out.safety = req.safety.map(({ roles, seed }) => {
    const pairs = L.guardedPairs(roles);
    const target = L.washTarget(roles, seed);
    const paint = L.hexToRgb(target);
    const cap = L.maxSafeAlpha(paint, pairs);
    const live = pairs.filter((p) => Math.abs(L.apcaLc(p.fg, p.bg)) >= p.lc);
    // Fine sub-grid sweep across the WHOLE renderable range [0, cap]: the worst
    // (smallest) margin above any guarded pair's floor. >= 0 ⇒ every frame the
    // layer can paint (alpha <= cap) is APCA-safe.
    let minMargin = Infinity;
    for (let i = 0; i * 0.002 <= cap + 1e-9; i++) {
      const a = i * 0.002;
      for (const p of live) {
        const lc = Math.abs(L.apcaLc(L.over(p.fg, paint, a), L.over(p.bg, paint, a)));
        minMargin = Math.min(minMargin, lc - p.lc);
      }
    }
    // Tightness: just past the cap, some live pair should fail (the cap is the
    // real APCA limit, not needless conservatism) — only when APCA-limited.
    const past = cap + 0.05;
    let breaksJustPast = null;
    if (live.length && past <= 0.6 && cap < 0.5 - 1e-9) {
      breaksJustPast = live.some(
        (p) => Math.abs(L.apcaLc(L.over(p.fg, paint, past), L.over(p.bg, paint, past))) < p.lc,
      );
    }
    return {
      cap,
      target,
      liveCount: live.length,
      minMargin: minMargin === Infinity ? null : minMargin,
      breaksJustPast,
    };
  });
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def run_layer():
    """Bundle the real role_transition.tsx and return a JSON request runner."""
    node = shutil.which("node")
    esbuild = motion.REMOTION_DIR / "node_modules" / ".bin" / "esbuild"
    if not node or not esbuild.exists():
        pytest.skip("node + esbuild required for the runtime APCA-safety proof")

    tmp = Path(tempfile.mkdtemp(prefix="r122-"))
    # The pure helpers never touch these at runtime, but the module imports them.
    (tmp / "remotion_stub.js").write_text(
        "export const AbsoluteFill=null;"
        "export const Easing={inOut:(f)=>f,sin:(x)=>x};"
        "export const interpolate=()=>0;"
        "export const useVideoConfig=()=>({durationInFrames:180});"
    )
    (tmp / "jsx_stub.js").write_text(
        "export const jsx=()=>null;export const jsxs=()=>null;export const Fragment=null;"
    )
    bundle = tmp / "layer.mjs"
    build = subprocess.run(
        [
            str(esbuild),
            str(LAYER),
            "--bundle",
            "--format=esm",
            "--platform=node",
            "--log-level=warning",
            "--jsx=automatic",
            f"--alias:remotion={tmp / 'remotion_stub.js'}",
            f"--alias:react/jsx-runtime={tmp / 'jsx_stub.js'}",
            f"--outfile={bundle}",
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"esbuild failed:\n{build.stderr}"

    harness = tmp / "harness.mjs"
    harness.write_text(_HARNESS % {"bundle": bundle.as_posix()})

    def run(request: dict) -> dict:
        proc = subprocess.run(
            [node, str(harness)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
        return json.loads(proc.stdout)

    yield run
    shutil.rmtree(tmp, ignore_errors=True)


def test_bundle_exposes_the_layer_and_mirrored_thresholds(run_layer):
    shape = run_layer({})["shape"]
    assert shape["hasLayer"] is True
    assert shape["order"] == 5
    # Thresholds in the shipped module equal the Python compliance module.
    assert shape["lcLarge"] == _compliance.LC_LARGE
    assert shape["lcSupport"] == _compliance.LC_SUPPORT


def test_shipped_apca_matches_the_python_reference(run_layer):
    pairs = [
        ("#FFFFFF", "#000000"),
        ("#000000", "#FFFFFF"),
        ("#FFFFFF", "#0E2A47"),
        ("#0E2A47", "#C9A227"),
        ("#C9A227", "#0E2A47"),
        ("#FF0000", "#00FF00"),
        ("#123456", "#7890AB"),
        ("#F5F2E8", "#0A0B11"),
        ("#7A0019", "#FFD200"),
        ("#888888", "#888888"),  # equal → low-clip 0
    ]
    got = run_layer({"apca": pairs})["apca"]
    for (fg, bg), ts_lc in zip(pairs, got):
        py_lc = apca(fg, bg)
        assert abs(ts_lc - py_lc) <= 0.06, f"{fg} on {bg}: TS {ts_lc} vs PY {py_lc}"


def test_shipped_blend_is_srgb_linear_compositing(run_layer):
    cases = [("#000000", "#FFFFFF", 0.5), ("#0E2A47", "#C9A227", 0.25)]
    got = run_layer({"blend": cases})["blend"]
    for (a, b, t), rgb in zip(cases, got):
        ar = [int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)]
        br = [int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)]
        want = [ar[i] + (br[i] - ar[i]) * t for i in range(3)]
        assert rgb == pytest.approx(want, abs=1e-6)


# A spread of real-shaped brand palettes (resolved-role shape: ground / surface
# / accent / onGround), including light-ground and medal-gold cases.
_PALETTES = [
    {"ground": "#0E2A47", "surface": "#13345A", "accent": "#C9A227", "onGround": "#FFFFFF"},
    {"ground": "#0A0B11", "surface": "#1A1D26", "accent": "#F5F2E8", "onGround": "#F5F2E8"},
    {"ground": "#7A0019", "surface": "#A3002A", "accent": "#FFD200", "onGround": "#FFFFFF"},
    {"ground": "#FFE08A", "surface": "#FFFFFF", "accent": "#0E2A47", "onGround": "#101418"},
    {"ground": "#103A2A", "surface": "#0B2A1E", "accent": "#E8B4BC", "onGround": "#F4FFF8"},
]


def test_opacity_cap_keeps_every_renderable_frame_apca_safe(run_layer):
    """The core R1.22 guarantee: across the whole [0, cap] range the layer can
    paint, every guarded text pair stays at or above its APCA floor."""
    req = {"safety": [{"roles": p, "seed": s} for p in _PALETTES for s in range(4)]}
    res = run_layer(req)["safety"]
    assert res
    for r in res:
        assert 0.0 <= r["cap"] <= 0.5 + 1e-9
        if r["minMargin"] is not None:
            # >= 0 means safe; allow a hair of float noise from the sub-grid.
            assert r["minMargin"] >= -0.05, f"unsafe wash for {r}"


def test_cap_is_visible_for_normal_brand_palettes(run_layer):
    """Every well-formed brand must afford a clearly visible wash on at least
    one variation — the APCA cap is a safety net, not a global mute. (The
    surface-target variant may stay subtle by design when the surface role sits
    close to the ground; that is deliberate per-card range, not a muted layer.)"""
    for p in _PALETTES:
        caps = [
            r["cap"]
            for r in run_layer(
                {"safety": [{"roles": p, "seed": s} for s in range(4)]}
            )["safety"]
        ]
        assert max(caps) >= 0.1, (p, caps)


def test_cap_is_tight_when_apca_limited(run_layer):
    """Where the cap is below the aesthetic ceiling it is the genuine APCA
    limit: a hair past it, some guarded pair drops below its floor."""
    res = run_layer({"safety": [{"roles": p, "seed": s} for p in _PALETTES for s in range(2)]})[
        "safety"
    ]
    checked = [r for r in res if r["breaksJustPast"] is not None]
    assert checked, "expected at least one APCA-limited palette in the sample"
    assert all(r["breaksJustPast"] for r in checked)


def test_fragile_palette_yields_no_wash(run_layer):
    """When no role pair has contrast headroom, the cap collapses to 0 and the
    layer paints nothing (it bails on cap < STEP_EPS)."""
    fragile = {"ground": "#444444", "surface": "#484848", "accent": "#505050", "onGround": "#565656"}
    res = run_layer({"safety": [{"roles": fragile, "seed": 0}]})["safety"][0]
    assert res["cap"] < 0.02


def test_planmode_gating_is_correct_and_deterministic(run_layer):
    cards = [
        {},  # legacy / brief-less → inert
        {"mood": "electric", "motionIntent": "static", "variationSeed": 1},  # static → inert
        {"mood": "electric", "variationSeed": 1},  # energetic → pulse
        {"mood": "calm, precise", "variationSeed": 1},  # composed → fade
        {"mood": "warm", "variationSeed": 1},  # warm → gradient
        {"mood": "triumphant", "variationSeed": 2},  # → pulse
        {"roleGround": "#0E2A47", "variationSeed": 0},  # unknown mood, seed 0 → fade
        {"roleGround": "#0E2A47", "variationSeed": 1},  # seed 1 → gradient
        {"roleGround": "#0E2A47", "variationSeed": 2},  # seed 2 → pulse
    ]
    got = run_layer({"plan": cards})["plan"]
    assert got == [
        None,
        None,
        "pulse",
        "fade",
        "gradient",
        "pulse",
        "fade",
        "gradient",
        "pulse",
    ]
    # Determinism: identical request → identical answer.
    assert run_layer({"plan": cards})["plan"] == got


def test_washtarget_returns_a_role_and_avoids_a_no_op(run_layer):
    roles = {"ground": "#0E2A47", "surface": "#13345A", "accent": "#C9A227", "onGround": "#FFFFFF"}
    got = run_layer({"target": [{"roles": roles, "seed": s} for s in range(4)]})["target"]
    # Always one of the non-ground roles, never an invented colour.
    for t in got:
        assert t in (roles["surface"], roles["accent"])
    # When the seed-picked role equals the ground, it falls back to the other.
    clash = {"ground": "#C9A227", "surface": "#13345A", "accent": "#C9A227", "onGround": "#101418"}
    even = run_layer({"target": [{"roles": clash, "seed": 0}]})["target"][0]
    assert even == clash["surface"], "must avoid washing toward the ground (a no-op)"
