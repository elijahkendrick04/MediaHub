"""Proof-of-concept for deep-review finding #111 — the DSR engine
(``compliance.dsr``) discloses and mutates *ownerless* runs cross-tenant.

Background (ADR-0014 §5, "the ownerless-run blast radius is closed"): on a
shared multi-tenant instance a signed-in *regular* tenant must NOT reach a run
whose ``profile_id`` is empty (legacy / pre-multi-tenancy data that may belong
to a different club). The web guard ``_can_access_run`` →
``_ownerless_run_readable`` enforces exactly that on every ``run_id`` route, and
``tests/test_workspace_membership_invariant.py::TestOwnerlessRunBlastRadius``
sweeps those routes to pin it.

But the Art-15/17/20 data-subject-rights engine walks runs through
``compliance.dsr._tenant_runs``, which uses ``owner == pid or not owner`` — it
folds EVERY ownerless run into whichever tenant asks, and never consults
``_ownerless_run_readable``. So a signed-in regular tenant's ``export`` reads,
and ``erasure``/``rectification`` destructively rewrite, ownerless runs that the
very same session is refused on every ordinary run route. The invariant sweeps
miss it because the DSR routes are keyed on a DSR-request id, not ``run_id``, so
they are never in the swept route set.

These two tests reproduce the disclosure and the mutation end-to-end, driven by
``stranger@clubg.org`` — a real signed-in owner of the BOUND org ``org-gamma``,
i.e. precisely the "signed-in regular tenant" ADR-0014 says must be refused.

They are marked ``xfail(strict=True)`` because they assert the *secure*
(post-fix) behaviour, which the current code violates. When finding #111 is
fixed, drop the ``xfail`` markers so they become the regression guard. The
sibling ``privacy.erasure.erase_athlete`` already uses the strict rule
(``!= profile_id``) and is pinned owned-vs-owned by
``test_privacy_erasure.py::test_athlete_erasure_is_tenant_scoped`` — this file
closes the untested ownerless seam for the ``compliance.dsr`` engine.
"""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import pytest

ORPHAN_ATHLETE = "Orphan Athlete"
STRANGER_EMAIL = "stranger@clubg.org"
PASSWORD = "twelve-chars-long"


def _seed_ownerless_run(runs_dir: Path, run_id: str, athlete: str) -> None:
    """A legacy run with NO ``profile_id`` key — ownerless, as pre-multi-tenancy
    rows are. Shaped so ``_athlete_entries_in_run`` matches the athlete."""
    data = {
        "run_id": run_id,
        "meet": {"name": "SECRET ORPHAN GALA"},
        "cards": [
            {
                "card_id": "card-orphan-1",
                "swim_id": "swim-orphan-1",
                "id": "card-orphan-1",
                "swimmer_name": athlete,
                "event": "100m freestyle",
                "headline": "Orphan-only PB",
            }
        ],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "swim-orphan-1",
                        "swimmer_name": athlete,
                        "event": "100m freestyle",
                        "headline": "Orphan-only PB",
                    }
                }
            ],
            "n_achievements": 1,
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


@pytest.fixture
def shared_instance(tmp_path, monkeypatch):
    """A shared instance: a signed-up stranger owning the BOUND org
    ``org-gamma``, plus one ownerless legacy run holding the orphan athlete."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-gamma", display_name="Org Gamma"))

    run_orphan = "run-orphan-" + uuid.uuid4().hex[:8]
    _seed_ownerless_run(tmp_path / "runs_v4", run_orphan, ORPHAN_ATHLETE)

    from mediahub.web.auth import UserStore
    from mediahub.web.tenancy import ROLE_OWNER, MembershipStore

    UserStore().create(STRANGER_EMAIL, PASSWORD)
    MembershipStore().add(STRANGER_EMAIL, "org-gamma", role=ROLE_OWNER)  # BOUND

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return {"app": app, "run_orphan": run_orphan, "runs_dir": tmp_path / "runs_v4"}


def _login_and_pin_gamma(client) -> None:
    r = client.post("/login", data={"email": STRANGER_EMAIL, "password": PASSWORD})
    assert r.status_code in (302, 303), r.status_code
    r = client.post("/api/organisation/active", data={"profile_id": "org-gamma"})
    assert r.status_code in (200, 302, 303), r.status_code


def _open_dsr(client, request_type: str) -> str:
    client.post(
        "/organisation/athlete-rights/open",
        data={"athlete_name": ORPHAN_ATHLETE, "request_type": request_type},
    )
    from mediahub.compliance.dsr import DsrRequestLog

    return DsrRequestLog().all(profile_id="org-gamma")[0].id


@pytest.mark.xfail(
    strict=True,
    reason="finding #111: DSR erasure reaches ownerless runs cross-tenant "
    "(remove xfail once _tenant_runs honours the _ownerless_run_readable rule)",
)
def test_dsr_erasure_must_not_mutate_an_ownerless_run(shared_instance):
    """A signed-in regular tenant's erasure must not rewrite a legacy ownerless
    run — that run may belong to a different club (ADR-0014 §5)."""
    app = shared_instance["app"]
    run_file = shared_instance["runs_dir"] / f"{shared_instance['run_orphan']}.json"

    with app.test_client() as c:
        _login_and_pin_gamma(c)
        req_id = _open_dsr(c, "erasure")
        c.post(f"/organisation/athlete-rights/{req_id}/run")

    after = json.loads(run_file.read_text())
    # SECURE expectation: the ownerless run is untouched by org-gamma's erasure.
    assert after["recognition_report"]["ranked_achievements"], (
        "org-gamma erased an ownerless run it does not own (finding #111)"
    )
    assert after["cards"], "org-gamma stripped cards from an ownerless run (finding #111)"


@pytest.mark.xfail(
    strict=True,
    reason="finding #111: DSR export discloses ownerless runs cross-tenant "
    "(remove xfail once _tenant_runs honours the _ownerless_run_readable rule)",
)
def test_dsr_export_must_not_disclose_an_ownerless_run(shared_instance):
    """A signed-in regular tenant's SAR export must not include records read out
    of a legacy ownerless run it does not own (ADR-0014 §5)."""
    app = shared_instance["app"]

    with app.test_client() as c:
        _login_and_pin_gamma(c)
        req_id = _open_dsr(c, "access")
        c.post(f"/organisation/athlete-rights/{req_id}/run")  # generates export
        dl = c.get(f"/organisation/athlete-rights/{req_id}/export.json")
        assert dl.status_code == 200, dl.status_code
        export = json.loads(dl.get_data(as_text=True))

    disclosed = {r.get("run_id") for r in export.get("runs", [])}
    # SECURE expectation: the ownerless run is NOT among the disclosed runs.
    assert shared_instance["run_orphan"] not in disclosed, (
        "org-gamma's SAR export disclosed an ownerless run it does not own (finding #111)"
    )
