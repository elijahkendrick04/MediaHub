"""Phase 1.6 Stage I1 — golden-master snapshot regression.

For each of the 30 seed colours in ``seeds_catalogue.SEEDS_CATALOGUE``,
load the committed snapshot from ``tests/theming/snapshots/`` and
assert the live engine's output matches.

When the engine legitimately changes:
    $ python scripts/update_theme_snapshots.py
    $ git diff tests/theming/snapshots/   # review the change
    $ git add tests/theming/snapshots/ && git commit

The script is the only path that writes snapshots; this test
only reads.

References:
    - docs/stage_i_test_coverage_plan.md §4
    - Feathers (2004) — characterisation tests
"""
from __future__ import annotations

import pytest

from mediahub.theming import derive_theme

from .seeds_catalogue import SEEDS_CATALOGUE, assert_catalogue_invariants
from ._snapshot_helpers import (
    SNAPSHOTS_DIR,
    build_snapshot,
    diff_snapshots,
    load_snapshot,
)


class TestCatalogueInvariants:
    """Lightweight contract on the catalogue itself."""

    def test_invariants(self):
        assert_catalogue_invariants()


class TestSnapshotFilesPresent:
    """One snapshot file per catalogue entry."""

    def test_snapshots_dir_exists(self):
        assert SNAPSHOTS_DIR.is_dir(), (
            f"missing {SNAPSHOTS_DIR}; run scripts/update_theme_snapshots.py"
        )

    def test_count_matches_catalogue(self):
        files = list(SNAPSHOTS_DIR.glob("*.json"))
        assert len(files) == len(SEEDS_CATALOGUE), (
            f"expected {len(SEEDS_CATALOGUE)} snapshots, found {len(files)}; "
            f"run scripts/update_theme_snapshots.py"
        )

    @pytest.mark.parametrize("seed_hex,label,category", SEEDS_CATALOGUE)
    def test_each_seed_has_snapshot(self, seed_hex, label, category):
        snap = load_snapshot(seed_hex)
        assert snap is not None, (
            f"no snapshot for {seed_hex} ({label}); "
            f"run scripts/update_theme_snapshots.py"
        )


@pytest.mark.parametrize("seed_hex,label,category", SEEDS_CATALOGUE)
def test_snapshot_matches(seed_hex, label, category, tmp_path, monkeypatch):
    """The headline test — derive the theme live and compare to the
    committed snapshot."""
    # Isolate DATA_DIR so the disk-mirror side-effect of
    # ensure_derived_palette doesn't pollute the repo or other tests.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()

    expected = load_snapshot(seed_hex)
    assert expected is not None, f"missing snapshot for {seed_hex}"

    theme = derive_theme(seed_hex)
    actual = build_snapshot(theme.to_json(), label=label)

    if actual != expected:
        diffs = diff_snapshots(expected, actual)
        diff_text = "\n".join(diffs)
        pytest.fail(
            f"snapshot mismatch for {seed_hex} ({label}, {category}):\n"
            f"{diff_text}\n\n"
            f"Re-run with the regenerator to accept:\n"
            f"  python scripts/update_theme_snapshots.py\n\n"
            f"Or revert the algorithm change that produced this drift."
        )


class TestCategoryCoverage:
    """The catalogue must hit every category — protects against
    accidentally dropping all hostile seeds in a refactor."""

    def test_identity_seeds_present(self):
        categories = {cat for _h, _l, cat in SEEDS_CATALOGUE}
        for required in ("identity", "common", "hostile", "saturated", "pastel"):
            assert required in categories, f"category {required!r} missing"

    def test_hostile_count(self):
        n = sum(1 for _h, _l, cat in SEEDS_CATALOGUE if cat == "hostile")
        # The Stage I plan §4 fixes this at 8 deliberately-hostile seeds.
        assert n == 8, f"expected 8 hostile seeds, got {n}"


class TestRegeneratorIdempotent:
    """Running the regenerator twice should produce identical
    snapshots — proves the engine output is deterministic."""

    def test_double_run_produces_no_diff(self, tmp_path, monkeypatch):
        # We run the regenerator-equivalent twice (just build_snapshot
        # for each seed) and compare. We don't shell out to the actual
        # script because we want the test to be hermetic.
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from mediahub.theming.theme_store import _read_cached
        _read_cached.cache_clear()
        # Sample 4 seeds across categories to keep the test fast.
        sample = [
            ("#D4FF3A", "lane yellow"),
            ("#A30D2D", "brand red"),
            ("#DFFF00", "fluorescent yellow (hostile)"),
            ("#7C3AED", "vivid purple"),
        ]
        for seed_hex, label in sample:
            a = build_snapshot(derive_theme(seed_hex).to_json(), label=label)
            b = build_snapshot(derive_theme(seed_hex).to_json(), label=label)
            assert a == b, f"{seed_hex}: non-deterministic output"


class TestSnapshotShape:
    """The snapshot files must keep their documented shape so PR
    diffs stay readable. Sanity-check one snapshot."""

    def test_documented_top_level_keys(self):
        snap = load_snapshot("#D4FF3A")
        required = {
            "seed_hex", "label", "seed_hct", "seed_source",
            "schema_version", "was_repaired", "harmonic_fit",
            "palette_anchors", "roles_light", "roles_dark",
            "quality_summary",
        }
        assert set(snap.keys()) == required, (
            f"snapshot shape drift: expected {required}, got {set(snap.keys())}"
        )
