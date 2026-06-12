"""tests/test_run_route_isolation_invariant.py — the run-route IDOR invariant.

``test_cross_tenant_access.py`` proves a *hand-picked* list of run-scoped routes
refuses a foreign organisation. That list is maintained by hand, so a newly added
``/api/runs/<run_id>/...`` route can silently ship without the
``_can_access_run`` guard and reintroduce the cross-tenant leak — exactly the
data-exposure risk that gates putting real clubs' (and minors') competition data
in front of a pilot.

This test closes that gap by making the guarantee an *invariant*: it introspects
the live ``app.url_map``, finds **every** route that takes a ``run_id`` argument,
and asserts that hitting each one from a different organisation's session never
leaks the owning org's data. A new run route added without the guard fails here,
loudly, with the offending endpoint named — no human has to remember to extend a
list.

It is deliberately permissive about *how* a route refuses (404 / 403 / redirect /
empty render are all fine) and strict about the one thing that matters: the
owner's secret markers must never appear in a foreign org's response.
"""

from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Markers seeded into the Alpha-owned run/pack. None of these may ever appear in
# a response served to the Beta session.
_SECRETS = ("SECRET ALPHA INVITATIONAL", "Alpha Athlete", "Alpha-only")

# How non-run path arguments are filled so a route can be reached at all. Values
# match the Alpha-owned fixture below. A run route whose extra argument is NOT in
# this map is reported as un-coverable so the maintainer adds it (and confirms the
# new route is tenant-guarded) rather than the invariant silently skipping it.
_ARG_FILL = {
    "ach_index": "0",
    "swim_id": "swim-alpha-1",
    "card_id": "card-alpha-1",
    "swimmer_key": "Alpha Athlete",
    "job_id": "job-x",
    # PC.10: the public wall's card route carries a per-org token. An
    # unknown token must 404 before any run data is touched, so sweeping
    # it with a junk token is exactly the guarantee to pin.
    "token": "no-such-wall-token",
    "pack_id": "PACK_ID",  # replaced with the real seeded pack id at runtime
}

_ARG_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")


@pytest.fixture
def two_orgs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-alpha",
            display_name="Org Alpha",
            brand_voice_summary="Bold, energetic, club-focused.",
        )
    )
    save_profile(
        ClubProfile(
            profile_id="org-beta",
            display_name="Org Beta",
            brand_voice_summary="Calm and considered.",
        )
    )

    run_id = "run-alpha-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "profile_display": "Org Alpha",
                "meet": {"name": "SECRET ALPHA INVITATIONAL"},
                "cards": [
                    {
                        "card_id": "card-alpha-1",
                        "swim_id": "swim-alpha-1",
                        "swimmer_name": "Alpha Athlete",
                        "event": "100m freestyle",
                        "headline": "Alpha-only PB",
                        "id": "card-alpha-1",
                    }
                ],
                "trust": {"score": 0.92},
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "achievement": {
                                "swim_id": "swim-alpha-1",
                                "swimmer_name": "Alpha Athlete",
                                "event": "100m freestyle",
                                "headline": "Alpha-only secret achievement",
                            }
                        }
                    ],
                    "n_elite": 1,
                    "n_strong": 0,
                    "n_story": 0,
                    "n_achievements": 1,
                    "n_swims_analysed": 1,
                },
                "parse_warnings": [],
                "self_check": {},
                "detector_summary": {},
                "dispatch_log": {},
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "SECRET ALPHA INVITATIONAL", "alpha.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.club_platform.stub_pack_store import save_pack

    pack = save_pack(
        "free_text",
        {"free_text": "ALPHA SECRET DRAFT"},
        [{"platform": "instagram", "caption": "Alpha-only secret caption", "confidence": 0.9}],
        profile_id="org-alpha",
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    with app.test_client() as c:
        yield {"app": app, "client": c, "run_id": run_id, "pack_id": pack["pack_id"]}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


def _run_rules(app):
    """Every URL rule that takes a ``run_id`` argument."""
    return [r for r in app.url_map.iter_rules() if "run_id" in r.arguments]


def _build_path(rule_str, fill):
    """Substitute ``<conv:name>`` placeholders in a rule string from ``fill``.

    Returns ``(path, missing_arg_or_None)``.
    """
    missing = None

    def sub(m):
        nonlocal missing
        name = m.group(1)
        if name not in fill:
            missing = name
            return m.group(0)
        return quote(str(fill[name]), safe="")

    path = _ARG_RE.sub(sub, rule_str)
    return path, missing


class TestRunRouteIsolationInvariant:
    def test_no_run_route_leaks_to_a_foreign_org(self, two_orgs):
        app, c = two_orgs["app"], two_orgs["client"]
        fill = dict(_ARG_FILL)
        fill["run_id"] = two_orgs["run_id"]
        fill["pack_id"] = two_orgs["pack_id"]

        _pin(c, "org-beta")

        swept, uncoverable, leaked = [], [], []
        for rule in _run_rules(app):
            path, missing = _build_path(rule.rule, fill)
            if missing is not None:
                uncoverable.append(f"{rule.rule}  (unknown arg <{missing}>)")
                continue
            methods = rule.methods or set()
            method = "GET" if "GET" in methods else ("POST" if "POST" in methods else None)
            if method is None:
                continue
            resp = c.open(path, method=method, data={}, follow_redirects=True)
            body = resp.get_data(as_text=True)
            hit = [s for s in _SECRETS if s in body]
            if hit:
                leaked.append(f"{method} {rule.rule} -> {resp.status_code} leaked {hit}")
            swept.append(rule.rule)

        # A new run route whose extra arg we can't fill must be added to _ARG_FILL
        # (and confirmed tenant-guarded) rather than silently skipped.
        assert not uncoverable, (
            "Run-scoped routes the isolation invariant can't reach — extend _ARG_FILL "
            "and confirm each is guarded by _can_access_run:\n  " + "\n  ".join(uncoverable)
        )
        # Guard against the test silently covering nothing if the route layout changes.
        assert len(swept) >= 20, f"Only swept {len(swept)} run routes; expected the full set."
        assert not leaked, (
            "Cross-tenant leak: a run-scoped route served Org Alpha's data to Org Beta. "
            "Add a _can_access_run() guard to:\n  " + "\n  ".join(leaked)
        )

    def test_owner_still_sees_her_own_run(self, two_orgs):
        # Positive control on a fresh fixture: the guard must not lock the owner out.
        c = two_orgs["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/review/{two_orgs['run_id']}")
        assert r.status_code == 200
        assert "SECRET ALPHA INVITATIONAL" in r.get_data(as_text=True)
