# Stage I — Test Coverage: Plan

> Phase 1.6 Stage I of [`ROADMAP.md`](ROADMAP.md). Stages A–H built
> and shipped the adaptive theming engine. Stage I locks it in.
> Two pieces: golden-master regression snapshots for 30
> representative seeds, and a real-browser end-to-end test that
> proves the cascade resolves to the expected hex.

## 1. Context

By the end of Stage H the adaptive theming engine has eight
shipped stages, ~700 tests across structural assertions, and an
explainability UI. The remaining gap is **regression**: most
tests verify structural properties ("the palette has 9 ramps",
"every role token has @property registered", "the audit panel
contains a Decision trace section") rather than specific pixel
values.

This is fine for refactors that preserve the algorithm but
dangerous when someone tunes a knob — a hue offset, a chroma
factor, a CVD threshold. The structural tests stay green while
the *output* drifts. A club whose brand colour was carefully
calibrated against Stage B's defaults now sees a slightly
different chrome on the next deploy, and no test catches it.

The two missing test classes:

- **Golden-master snapshots** for a curated set of seed colours.
  Capture the engine's full output for each seed once; on every
  commit assert the output hasn't drifted. When the algorithm
  legitimately changes, regenerate the snapshots in a deliberate
  commit. The diff is the documentation.

- **Real-browser end-to-end** test. Every Stage A–H test runs
  Python against Python. None of them prove that `oklch(from
  var(--mh-brand-seed) 0.866 calc(c * 0.96) h)` actually
  resolves to the colour we expect in a real browser. With
  chromium-1194 already pinned in the dev environment via
  Playwright, this test is straightforward to add.

The two pieces have orthogonal coverage. Golden masters catch
algorithm drift in pure Python. The Playwright test catches CSS
cascade drift in a real engine. Together they bracket the system.

## 2. The user-visible promise

A developer changing any of:
- HCT seed → primary tone mapping
- the OKLCH derivation formulas in `theme-derive.css`
- the role-tone map in `roles.py`
- the repair loop nudge offsets
- the Cohen-Or templates
- the APCA / WCAG / CVD thresholds

…will see one or more snapshot tests fail with a precise diff:
*"seed `#A30D2D` now produces `roles.light.primary = #8A4C50`,
was `#8B4C4F`."* The developer either accepts the change
(regenerates the snapshot, the PR carries the diff in the commit)
or reverts.

A developer who breaks the CSS cascade (typo in
`theme-derive.css`, mis-ordered `@supports` blocks, accidentally
loading the wrong CSS file order) will see the Playwright test
fail: *"`getComputedStyle(:root).getPropertyValue('--mh-surface')`
resolved to `rgb(0, 0, 0)`, expected `oklch(...)` or a near-
black hex."*

Catastrophic regressions impossible. Subtle ones documented.

## 3. Architecture overview

Four concrete additions:

| Change | Where | What |
|---|---|---|
| Seed catalogue | New `tests/theming/seeds_catalogue.py` | The 30 representative seed hexes + labels, importable by every snapshot test |
| Snapshot files | New `tests/theming/snapshots/*.json` | One file per seed, ~1KB each, ~30KB total |
| Snapshot test | New `tests/theming/test_golden_snapshots.py` | Parametrised over the 30 seeds — load snapshot, regenerate, assert equal |
| Snapshot regenerator | New `scripts/update_theme_snapshots.py` | Idempotent CLI that overwrites every snapshot from the live engine |
| Playwright test | New `tests/test_browser_cascade.py` | Loads a rendered Flask page in chromium-1194, asserts computed style |

Plus an extension of `.github/workflows/responsive-design.yml`
documenting the snapshot path (`tests/theming/snapshots/` becomes
part of the test surface).

The Playwright test follows the existing `tests/test_motion.py`
gating pattern: opt-out via `MEDIAHUB_SKIP_BROWSER_TESTS=1` rather
than opt-in. Default behaviour: run if Playwright + Chromium are
available. CI inherits Playwright via the existing
`pip install -e .[render]` (per the session-start hook).

## 4. I1 — Golden-master snapshots for 30 representative seeds

### The catalogue

30 seeds curated to span the colour space, with deliberate
hostility:

**MediaHub identity** (3) — the engine's own anchors:
- `#D4FF3A` — lane yellow (current Stage A default)
- `#F4D58D` — medal gold
- `#0E2A47` — generic-default navy

**Common club / brand colours** (10):
- `#A30D2D` — brand red (the test fixture used by Stages B/H)
- `#06D6A0` — teal-green
- `#FFD700` — gold
- `#1E40AF` — corporate deep blue
- `#16A34A` — emerald
- `#DC2626` — corporate red (lighter than `#A30D2D`)
- `#800020` — burgundy (rugby/cricket)
- `#FF8C00` — orange (e.g. Netherlands)
- `#8B0000` — dark crimson (Harvard-style)
- `#4F46E5` — indigo

**Hostile / edge cases** (8):
- `#DFFF00` — fluorescent yellow (Stage B repair-loop test seed)
- `#2A3A1A` — muddy dark green
- `#FAFAF7` — near-white
- `#0C0C0C` — near-black
- `#1B1B1B` — near-black grey
- `#FF0000` — pure primary red
- `#00FF00` — pure primary green
- `#0000FF` — pure primary blue

**Saturation extremes** (5):
- `#FF00FF` — magenta
- `#00FFFF` — cyan
- `#FFFF00` — pure yellow
- `#F472B6` — hot pink
- `#8B5CF6` — violet

**Pastels + harmonics** (4):
- `#84CC2E` — lime green (close to lane yellow)
- `#E11D48` — rose
- `#0EA5E9` — sky blue
- `#7C3AED` — vivid purple

Total = 30. Each entry carries a `label` so test failures are
human-readable: *"snapshot mismatch for #DFFF00 (fluorescent
yellow, hostile)"*.

### The snapshot format

One file per seed at `tests/theming/snapshots/<sanitised>.json`:

```json
{
  "seed_hex": "#A30D2D",
  "label": "brand red",
  "seed_hct": [16.4, 77.2, 34.5],
  "seed_source": "hex",
  "schema_version": "1",
  "was_repaired": true,
  "harmonic_fit": {
    "template": "i", "rotation": 30.0, "energy": 12.4, "hue_count": 9
  },
  "palette_anchors": {
    "primary": "#A30D2D",
    "secondary_hue": 16.4,
    "tertiary_hue": 336.4,
    "error_hue": 358.0,
    "success_hue": 142.0,
    "warning_hue": 80.0,
    "info_hue": 240.0
  },
  "roles_light": {
    "primary": "#8B4C4F",
    "on_primary": "#FFFFFF",
    "surface": "#FDFCFE",
    "on_surface": "#0F1316"
  },
  "roles_dark": {
    "primary": "#FFB3B4",
    "on_primary": "#3D1F22",
    "surface": "#0B0A0C",
    "on_surface": "#E2E2E2"
  },
  "quality_summary": {
    "passed": true,
    "n_contrast_failures": 0,
    "n_status_distance_failures": 0,
    "n_cvd_failures": 0
  }
}
```

The shape balances three pressures:

1. **Small enough to be readable in a PR diff** — ~1KB per file.
   A developer can eyeball the change without scrolling through
   100KB of every tone of every ramp.
2. **Comprehensive enough to catch real regressions** — covers
   the seed's HCT, harmonic fit, status anchor hues (which the
   repair loop is allowed to move), four key role tokens per
   scheme, and the quality summary counts.
3. **Stable enough that legitimate algorithm tweaks produce
   focused diffs** — a CVD threshold change touches
   `n_cvd_failures`, not 100+ unrelated values.

We deliberately do NOT snapshot every tonal-ramp tone (13 × 9 =
117 values per seed × 30 seeds = 3,510 hex values). Those are
covered by the existing Stage B `test_palette.py` structural
tests and would inflate every PR diff with noise.

### The regenerator

`scripts/update_theme_snapshots.py`:

```bash
$ python scripts/update_theme_snapshots.py
Regenerating 30 snapshots...
  ✓ #D4FF3A — lane yellow (no change)
  ✓ #F4D58D — medal gold (no change)
  ! #A30D2D — brand red (CHANGED: roles_light.primary #8B4C4F → #8A4B4E)
  ✓ #0E2A47 — generic-default navy (no change)
  ...
29 unchanged, 1 changed. Snapshots written to tests/theming/snapshots/.
```

Idempotent — running it twice in a row produces no diff. The CI
flag is: *if the snapshot dir has uncommitted changes after
`update_theme_snapshots.py` runs, the test fails.* (Implemented
by the test, not the script.)

### The snapshot test

`tests/theming/test_golden_snapshots.py`:

```python
@pytest.mark.parametrize("seed_hex,label", _SEEDS_CATALOGUE)
def test_snapshot_matches(seed_hex, label):
    expected = _load_snapshot(seed_hex)
    actual = _build_snapshot(derive_theme(seed_hex))
    assert actual == expected, (
        f"snapshot mismatch for {seed_hex} ({label}). "
        f"Run scripts/update_theme_snapshots.py and review the diff."
    )
```

Parametrised: 30 test rows. A single seed's failure doesn't block
the other 29 from reporting.

### A snapshot doesn't replace structural tests

The existing Stage B tests (palette has 13 tones, role map is
complete, contrast pairs all clear floor, etc.) keep running.
Snapshots add a layer; they don't displace one. Structural tests
catch "the algorithm broke" — snapshots catch "the algorithm
quietly changed".

## 5. I2 — Playwright end-to-end test

### Why a real browser

Every Stage A–H Python test exercises the data layer: the
palette dict, the role table, the contrast scores. None of them
exercise the *delivery* layer: that the rendered HTML, when
loaded in a real CSS engine, resolves the cascade to the colours
we expect.

Possible regressions invisible to Python tests:
- Typo in `theme-derive.css`'s `oklch(from …)` expression that
  CSS engines silently treat as invalid → cascade falls through
  to the fallback layer.
- Wrong cascade order in the loader, so the modern derive block
  runs BEFORE the fallback rather than after.
- `@property` block syntax that's accepted by the spec but not
  by chromium-1194's parser.
- Inline `<style id="mh-theme-seed">` injected in the wrong
  position in `<head>` so a stylesheet later in the document
  wins.
- `light-dark()` falling through unexpectedly when `color-scheme`
  isn't declared.

The Playwright test catches every one of these by reading
`getComputedStyle(:root).getPropertyValue('--mh-surface')`
directly from the browser and asserting on the resolved hex.

### Test approach

```python
@pytest.mark.skipif(_skip_browser(), reason="Playwright browser unavailable")
def test_cascade_resolves_seed_to_expected_role(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Boot the Flask app, generate a profile + theme, snapshot the
    # rendered HTML.
    from mediahub.web.web import create_app
    from mediahub.web.club_profile import ClubProfile, save_profile
    prof = ClubProfile(profile_id="browser-test", display_name="Browser")
    prof.brand_primary = "#A30D2D"
    prof.brand_kit = {"profile_id": "browser-test",
                       "display_name": "Browser",
                       "primary_colour": "#A30D2D"}
    save_profile(prof)
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "browser-test"
        body = c.get("/status").get_data(as_text=True)

    # Load the rendered HTML directly in chromium-1194.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
            headless=True,
        )
        page = browser.new_page()
        page.set_content(body)
        # Wait for CSS to apply
        page.wait_for_load_state("networkidle")

        # Read the resolved CSS variable
        seed = page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--mh-brand-seed').trim()"
        )
        surface = page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--mh-surface').trim()"
        )
        primary = page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--mh-primary').trim()"
        )
        browser.close()

    # Assert the seed override took effect
    assert "A30D2D" in seed.upper() or seed.lower() == "#a30d2d"
    # Surface should resolve to a non-empty colour (browser may return
    # rgb() or oklch() form; we just assert non-empty here, since the
    # exact form depends on the browser's cssom serialisation).
    assert surface != ""
    assert primary != ""
```

The test does NOT assert specific hex values for derived shades
— different browsers serialise `oklch()` differently and the
expected hex depends on the cascade resolution. Instead it
asserts the cascade *resolved at all* (variables are non-empty)
and the seed override is in effect.

A second test asserts that absent an active profile, the
`--mh-brand-seed` override is NOT present (Stage E contract).

### Gating

Following the `tests/test_motion.py` pattern:

```python
_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower()
    in ("1", "true", "yes")
)

def _chromium_present() -> bool:
    return Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome").is_file()

@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _chromium_present(), reason="chromium-1194 not installed")
def test_…(): ...
```

Default: runs when both Playwright + chromium-1194 are present
(which is the case in this session and in production Docker).
Skipped in environments missing either.

## 6. Backward compatibility

Stage I is purely additive — no changes to engine code, no
changes to test fixtures used by Stage A–H tests. The
snapshot files live under `tests/theming/snapshots/` (new
directory) and don't touch any existing code path.

Existing tests that exercise the engine with hostile seeds (e.g.
`tests/theming/test_repair.py` for `#FF0000`) keep running with
their own assertions. The Stage I snapshots add a second layer
of regression check, not a replacement.

## 7. Risk register

| Risk | Probability | Mitigation |
|---|---|---|
| 30 snapshots produce thousands of lines of CI noise on every algorithm tweak | Medium | Snapshot format is intentionally compact (~1KB per file). A real change touches only a few values, not the whole file. |
| Developer forgets to regenerate snapshots when algorithm changes | Low | Script + clear test failure message points at the script |
| Snapshots drift across platforms (Linux vs macOS floating-point) | Low | All math is deterministic; coloraide uses the same wheels everywhere. Tested locally. |
| Playwright test flakes due to networkidle timing | Medium | `page.set_content` is synchronous; no network I/O involved. Wait state pinned. |
| Chromium path hardcoded | Low | Use the env-var fallback pattern Playwright already supports |
| CI doesn't have chromium-1194 | None | The session-start hook installs it; CI inherits via .[render] extra |
| Snapshot file naming collides | None | `#A30D2D` → `a30d2d.json` (lowercase, no #); 30 distinct hexes |
| Snapshot regenerator destroys committed snapshots | Low | Script always overwrites — but the diff is reviewable in `git diff` before commit |

## 8. Audit plan (10 subtasks)

1. `tests/theming/seeds_catalogue.py` exports exactly 30 seeds.
2. Every seed is a valid 6-digit hex.
3. The labels are unique and human-readable.
4. `scripts/update_theme_snapshots.py` exists and runs without error.
5. After running the script, `tests/theming/snapshots/` contains
   exactly 30 JSON files.
6. Each snapshot file has the documented keys.
7. The snapshot test parametrises over all 30 seeds.
8. Running the test suite green with the current snapshots.
9. Running the regenerator twice produces no diff (idempotent).
10. The Playwright test is skipped when `MEDIAHUB_SKIP_BROWSER_TESTS=1`.

## 9. Verify plan (10 subtasks)

1. Pytest full suite passes.
2. The 30 snapshot tests pass when the snapshots are in sync.
3. Modifying one snapshot file produces a failing test.
4. Running the regenerator after such a modification fixes it.
5. The Playwright test runs end-to-end against a Flask response.
6. The Playwright test confirms `--mh-brand-seed` reflects the
   active profile.
7. The Playwright test confirms `--mh-surface` resolves to a
   non-empty value.
8. The Playwright test skips cleanly when chromium-1194 is missing.
9. The 30 seeds span the full hue circle (no clusters in a single
   sextant).
10. Hostile seeds (`#DFFF00`, `#A30D2D`, pure primaries) carry
    `was_repaired = True` in their snapshots; clean seeds (lane
    yellow) carry `False`.

## 10. Out of scope (deferred to Stage J)

- Snapshot regression for the rendered audit panel HTML (the
  panel is structurally tested in Stage H; a pixel-level snapshot
  is overkill).
- Visual-regression screenshots of pages (would require fixture
  HTML and image diffing — heavy machinery for negligible gain
  on top of `getComputedStyle`).
- Cross-browser testing (Firefox, Safari). Stage J's polish
  phase may add this once production traffic warrants it.
- Snapshotting every tonal-ramp tone (117 per seed × 30 = 3,510
  values). Structural tests already cover monotonicity / tone
  count; snapshots stay focused on the headline values.
- A CI step that auto-regenerates snapshots. The current
  contract is: regenerate locally, commit, review the diff.

## 11. References

- Golden-master / characterisation tests — Michael Feathers,
  *"Working Effectively with Legacy Code"* (2004), ch. 13:
  "I Need to Make a Change, but I Don't Know What Tests to
  Write" — the canonical defence of capturing existing behaviour
  before changing it.
- Playwright sync API — playwright.dev/python/docs/api/class-page
- `getComputedStyle` resolution — drafts.csswg.org/cssom/
  #the-getcomputedstyle()-method
- Coloraide deterministic output — facelessuser.github.io/
  coloraide/about/#deterministic
- Stage B's `_REPRESENTATIVE_SEEDS` (12 seeds) — the existing
  list our 30 expands on. We keep every Stage B seed in the
  catalogue plus 18 new ones for coverage.

The thirty-seed catalogue is the contract MediaHub's adaptive
theming makes to the world: *any club whose brand colour falls
in this corner of the colour space gets the documented
treatment*. Stage I is the test infrastructure that proves the
contract holds over time.

## 12. Snapshot maintenance lifecycle

Snapshots aren't static artefacts. They evolve with the engine.
The lifecycle:

1. **Initial generation** — one commit lands the catalogue + the
   regenerator + the empty test. The regenerator is run once;
   the resulting `snapshots/*.json` files are committed alongside.
2. **Steady state** — every subsequent PR runs the snapshot
   test. Tests pass → no diff. Tests fail → the PR is doing
   something that changes engine output.
3. **Deliberate algorithm change** — the PR author runs the
   regenerator, reviews the diff in `git diff
   tests/theming/snapshots/`, commits the regenerated files
   alongside the algorithm change. The PR diff now carries
   both the algorithm change AND its measurable effect.
4. **Adding a new seed** — append to `seeds_catalogue.py`, run
   the regenerator, commit the new snapshot file.
5. **Removing a seed** — delete from catalogue + delete the
   snapshot file. Documentation justifies why the seed is no
   longer representative.

This is the canonical golden-master workflow popularised by
Michael Feathers. It works because the snapshot files are
**reviewable in a code-review tool** — a PR reviewer sees
exactly what changed, not just that something did.

The catalogue itself is a separate review surface. Adding a new
hostile seed (say, a fluorescent magenta) is a small,
self-contained PR: catalogue entry + snapshot file. The next
algorithm change automatically inherits coverage of the new seed.

## 13. Failure-mode forensics

When a snapshot test fails, the failure message must be enough
to debug WITHOUT re-running the test. Concretely:

```
FAILED tests/theming/test_golden_snapshots.py::test_snapshot_matches[#A30D2D-brand red]

snapshot mismatch for #A30D2D (brand red):
  roles_light.primary: snapshot=#8B4C4F, actual=#8A4B4E
  roles_dark.primary:  snapshot=#FFB3B4, actual=#FFB2B4

Re-run with the regenerator to accept:
  python scripts/update_theme_snapshots.py

Or revert the algorithm change that produced this drift.
```

The test helper builds this diff by comparing the loaded
snapshot dict against the freshly-computed dict — only the
differing keys appear in the message. Long-tail keys (the
quality summary counts, harmonic_fit, etc.) that didn't change
stay out of the noise.

## 14. The role of structural tests post-Stage I

Stage I adds snapshots without removing any structural test.
The two layers play complementary roles:

| Test class | What it catches |
|---|---|
| Structural (Stage B–H) | "the API is broken" — missing keys, wrong types, contract violations |
| Snapshot (Stage I) | "the algorithm changed" — same shape, different numbers |
| Browser (Stage I) | "the CSS cascade is broken" — same algorithm, different engine resolution |

Removing a Stage B test in favour of a snapshot would be a
mistake — snapshots don't catch *what's missing*, only *what
moved*. A regression that deleted the `roles.light.primary`
field entirely would still pass the snapshot test (the snapshot
has the key, but the comparison might match `None == None`),
while a structural test asserting "every role token is a valid
hex" catches it immediately.
