"""Tenant-scoping of the run-keyed pbs/ research cache in the DSR engine
(follow-up to finding #111, adjacent research-cache item).

Finding #111 confined the DSR *runs* walk to the tenant. One layer down, the
export/erasure walk over the global ``discovered/`` research cache was still
tenant-blind. The ``pbs/`` subdir is keyed by run id
(``pb_discovery.cache.RunCache`` → ``discovered/pbs/<_safe(run_id)>/``), so it
carries the run's tenant attribution and is now confined to the requesting
tenant's own runs (``_tenant_pbs_dirs``). ``swimmers/`` and ``search_cache/``
stay global by design — they have no tenant dimension (keyed by
``md5(name|club)`` / query hash) and hold the subject's own public-results data,
which the export already row-redacts per subject.

These tests pin: (1) a SAR export does not disclose another tenant's pbs cache;
(2) an erasure does not delete another tenant's pbs cache; (3) the exported
cache path is relative (no DATA_DIR filesystem-layout leak) and carries an
explicit ``rows_redacted``. Verified red before the fix, green after.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ATHLETE = "Jamie Shared"


def _seed_run(runs: Path, rid: str, pid: str) -> None:
    (runs / f"{rid}.json").write_text(
        json.dumps(
            {
                "run_id": rid,
                "profile_id": pid,
                "cards": [],
                "recognition_report": {
                    "ranked_achievements": [
                        {"achievement": {"swim_id": "c1", "swimmer_name": ATHLETE}}
                    ]
                },
            }
        )
    )


def _seed_pbs(discovered: Path, rid: str, time: str) -> Path:
    """Write a per-run pbs cache file mentioning the athlete, under the same
    ``pbs/<_safe(run_id)>/`` path the real RunCache writer uses."""
    from mediahub.pb_discovery.cache import _safe

    d = discovered / "pbs" / _safe(rid)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "swimmer.json"
    f.write_text(
        json.dumps(
            {"swimmer_query": f"{ATHLETE} (Otter SC)", "pbs": [{"event": "100 Free", "time": time}]}
        )
    )
    return f


@pytest.fixture
def two_tenant_pbs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    discovered = tmp_path / "discovered"
    _seed_run(runs, "runA", "org-a")
    _seed_run(runs, "runB", "org-b")
    a = _seed_pbs(discovered, "runA", "57.10")
    b = _seed_pbs(discovered, "runB", "58.20")
    return {"discovered": discovered, "pbs_a": a, "pbs_b": b}


def test_export_pbs_cache_confined_to_tenant_runs(two_tenant_pbs):
    from mediahub.compliance.dsr import export_athlete

    export = export_athlete("org-a", ATHLETE, include_ownerless=False)
    paths = " ".join(c["path"] for c in export["pb_caches"])
    # org-a's own run pbs is exported; org-b's is not (it is a different tenant).
    assert "runA" in paths, paths
    assert "runB" not in paths, paths


def test_erase_pbs_cache_confined_to_tenant_runs(two_tenant_pbs):
    from mediahub.compliance.dsr import erase_athlete

    erase_athlete("org-a", ATHLETE, include_ownerless=False)
    assert not two_tenant_pbs["pbs_a"].exists(), "org-a's own pbs cache should be erased"
    assert two_tenant_pbs["pbs_b"].exists(), "org-b's pbs cache must NOT be deleted by org-a"


def test_export_pb_cache_path_is_relative_and_has_rows_redacted(two_tenant_pbs, tmp_path):
    from mediahub.compliance.dsr import export_athlete

    export = export_athlete("org-a", ATHLETE, include_ownerless=False)
    assert export["pb_caches"], "expected at least the tenant's own pbs cache"
    for c in export["pb_caches"]:
        # No absolute DATA_DIR path leaks into the signed SAR export.
        assert not c["path"].startswith("/"), c["path"]
        assert str(tmp_path) not in c["path"], c["path"]
        # Honest completeness signal is always present.
        assert "rows_redacted" in c
