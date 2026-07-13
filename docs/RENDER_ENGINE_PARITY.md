# Render-Engine Parity — testing the still engine customers actually get

**Status:** in progress · first slice shipped · closes deep-review finding
**#132** ("the production render engine is under-tested").

## In plain words (start here)

MediaHub has two still-graphic engines. **v1** is the older "legacy" layout
engine. **v2** ("Gen Engine v2") is the newer archetype engine, and it is the
one that runs in production — a real customer's card is rendered by v2 unless an
operator explicitly flips the `MEDIAHUB_GEN_V2=0` kill-switch.

The test suite, however, pins **every** test to the *legacy* v1 engine. It does
this in one line, an autouse fixture in `tests/conftest.py`:

```python
monkeypatch.setenv("MEDIAHUB_GEN_V2", "0")
```

That pin exists for a good reason — dozens of render tests were written before
v2 and assert v1-specific layout behaviour, so pinning v1 keeps them green
without hand-editing each one. But the side effect is that the engine customers
*actually use* (v2) was barely exercised: of ~34 render test files, only a
handful ever turned v2 on. **The majority of our render coverage validated a
path customers don't get.**

The fix is **not** to flip the global default — that would destabilise the many
v1-assuming tests all at once. Instead we add a **parity layer**: a small pytest
fixture that lets a render test run **twice** — once on v1, once on the real
production default — so both engines get covered from one test body. We then
move render tests onto it, slice by slice.

## Why the two engines actually differ (the mechanism)

The render entry point is `graphic_renderer.render.render_brief`. Its v1/v2
branch (`render.py:4640-4658`) only diverges when **the brief's family is a v2
archetype**:

```python
if _archetypes.is_enabled() and family in _archetypes.list_archetypes():
    _v2_archetype = family
    template_path = _archetypes.V2_DIR / f"{family}.html"
```

So a brief whose `layout_template` is a *legacy* family (e.g. `individual_hero`,
`text_led_recap`) renders **identically** whether v2 is on or off — the v2 branch
is simply not taken. The real divergence is created one level up, in the
**generator** (`creative_brief/generator.py`): when v2 is on it *picks a v2
archetype* for the card; when v2 is off it leaves a legacy family. Concretely,
for the same individual-PB content across seeds 0–9:

| Engine | Families the generator picks (seeds 0–9) |
| --- | --- |
| **v1** (`MEDIAHUB_GEN_V2=0`) | `text_led_recap`, `big_number_hero`, `weekend_numbers`, `meet_preview`, `sponsor_branded`, `story_card`, `reel_cover`, `action_photo_hero` |
| **v2** (production default) | `band_break`, `big_number_dominant`, `broadcast_scorebug`, `centered_medal_spotlight`, `contact_sheet`, `cornerstone_numeral`, `duo_athlete_split`, `editorial_numbers_grid`, `full_bleed_photo_lower_third`, `full_height_portrait_split` |

**Consequence for the parity layer:** a render test only gains real v2 coverage
if it lets the **generator** choose the family (i.e. it calls `generate()` /
`gen_brief()` without pinning `layout_template` to a legacy name). Tests that
hard-code a legacy family are *engine-invariant* — parametrising them proves the
invariance but exercises no new code.

Only the resolved-role/autofit CSS custom properties (`--mh-primary:`,
`--mh-fit-surname-px:`, `--mh-photo-pos:`, `:root{ … }`) are injected on the v2
path; the legacy engine never emits them. They are the reliable fingerprint that
a render actually took the production path — the parity module asserts on them.

## The parity layer (what shipped in the first slice)

Two pieces, both in `tests/conftest.py`:

1. **`render_engine`** — a parametrised fixture (`params=("v1", "v2")`). `v1`
   sets `MEDIAHUB_GEN_V2=0`; `v2` **deletes** the var so the test runs under the
   genuine production default (`archetypes.is_enabled()` → True), not a
   look-alike. A test that requests it runs once per engine.
2. **The autouse pin stands down** for any test that requests `render_engine`
   (it checks `request.fixturenames`). This removes any ordering race over the
   env var — the parity fixture owns the flag for its test, and every other test
   in the suite is pinned to v1 exactly as before. **No existing test changes
   behaviour.**

The first slice's coverage lives in **`tests/test_render_engine_parity.py`**. It
drives the real `generate()` → `render_brief()` path (Playwright stubbed, so it
runs with no Chromium) under both engines and asserts:

- **the wiring** — `is_enabled()` matches the selected engine (proves the fixture
  + back-off actually flip the gate);
- **the crux of #132** — under the production default the render routes through a
  real `layouts/v2` archetype; under v1 through a legacy family;
- **the v2 brand-role injection** — the `--mh-*` role tokens + autofit vars are
  present under v2 and absent under v1;
- **the shared contract** (10 seeds × both engines) — a clean, placeholder-free
  card assembles, a PNG is written, provenance is populated, and the club
  identity always lands;
- **content fidelity** — the athlete's real result value survives the layout swap
  on either engine.

## Rollout plan for the remaining render tests

Convert files onto `render_engine` in priority order. Ship each phase as its own
small, green PR. **Never loosen an assertion or a tolerance to force green** —
if a v2 render genuinely needs a different expected value (or its own committed
baseline), capture it and eyeball it honestly.

**Phase 1 — generator-driven, browser-stubbed (highest value, lowest risk).**
Tests that build the brief through `generate()`/`gen_brief()` and stub
`render_html_to_png`, so they diverge under v2 *and* run everywhere. The first
slice (`test_render_engine_parity.py`) is the template. Extend into:
`test_gen_v2_tier_a.py` assembly assertions (run the "clean assembly" checks
under v1 too, guarded for the legacy shape).

**Phase 2 — generator-driven, real render (high value, CI-gated on Chromium).**
`test_render_cache.py`, `test_svg_export.py`, `test_g1_14_output_formats.py`,
`test_g13_landscape_formats.py`. These currently render a legacy fallback under
the pin; on v2 they will render a real archetype. Their assertions are
filename/format/dimension driven and should hold on both, but re-verify each.
**Watch `test_gradient_mesh.py`** — its `changed_fraction` pixel thresholds were
tuned against the v1 fallback (`big_number_dominant` falls back to
`text_led_recap` under the pin); running it under v2 renders the real archetype,
so its thresholds must be re-measured against v2 output, not relaxed.

**Phase 3 — engine-invariant families (prove-invariance, lower value).**
`test_metadata_embed.py`, `test_g1_30_inspect_overlay.py`,
`test_g1_21_depth_of_field.py`, `test_animated_still.py`, `test_photo_adjust.py`
hard-code `individual_hero`/`text_led_recap`, so both engines render the same
template. Either (a) parametrise to lock in that the post-render features (EXIF,
inspect sidecar, APNG, DOF, photo-adjust) are engine-independent, or (b) add an
archetype-family variant so those features are also proven on the v2 body.

**Phase 4 — render is mocked out (not applicable).**
`test_print_ready_web.py`, `test_brand_resweep.py`, `test_ui_1_18_inspector.py`
replace `render_brief`/`render_all_formats` entirely — they test routes and
orchestration, not the engine. Leave them on the suite-wide pin.

## Visual-regression baselines — the honest position

The committed **motion** pixel baselines (`tests/baseline/motion_frames/`) are
driven through **Remotion** by `scripts/motion_vr.py` /
`test_motion_regression.py::test_committed_baselines_match`, they are **opt-in**
(`MEDIAHUB_MOTION_VR=1`) and **Node-gated**, and they do **not** flow through
`render_brief`. The still-render parity slice therefore does **not** touch them,
and this PR captured no new pixel baselines.

If a later phase extends parity to *pixel* diffs of the still engine (rather than
the current structural/HTML-contract diffs), a v2 render may warrant its **own**
committed baselines separate from v1. When that happens: capture them with the
real renderer, **eyeball every frame** before committing, and never rewrite a
baseline automatically or widen a tolerance to make a red diff pass — a bug must
never be allowed to bless itself.
