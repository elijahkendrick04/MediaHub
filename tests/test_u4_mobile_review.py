"""U.4 — mobile-aware review / approve.

Two surfaces:

1. The magic-link lite review page (``/m/<token>``) a volunteer opens on a
   phone. It was approve/edit/reject only; U.4 enriches it with a run-level
   summary (counts + progress bar), per-card quality band + confidence, and
   a 'what to check' line — enough signal to approve informed, still
   chrome-free and fast on one bar of signal.

2. The desktop-primary review page (``/review/<id>``) gains responsive rules
   so its triage controls become full-width 46px tap targets on a phone.
"""

from __future__ import annotations

import importlib
import json
import types

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    return types.SimpleNamespace(app=app, wm=wm, cp=cp, tmp=tmp_path)


def _save_org(world, pid="riverbend", name="Riverbend SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id=pid,
            display_name=name,
            brand_voice_summary="Proud, warm, community-first.",
        )
    )
    return pid


# Two cards: an elite+safe lead and a strong+needs_review card so the page
# exercises both the 'safe' (no why line) and 'needs_review' (why line) paths.
_RANKED = [
    {
        "rank": 1,
        "quality_band": "elite",
        "priority": 0.92,
        "safe_to_post": {"level": "safe", "reason": "High confidence evidence."},
        "achievement": {
            "swim_id": "s1",
            "swimmer_name": "Tamsin Veldt",
            "event": "200m IM",
            "time": "2:24.61",
            "headline": "Tamsin Veldt takes gold in the 200m IM",
            "type": "medal_gold",
            "confidence": 0.91,
            "confidence_label": "high",
        },
    },
    {
        "rank": 2,
        "quality_band": "strong",
        "priority": 0.61,
        "safe_to_post": {
            "level": "needs_review",
            "reason": "Medium confidence — verify before posting.",
        },
        "achievement": {
            "swim_id": "s2",
            "swimmer_name": "Idris Vanterpool",
            "event": "100m Freestyle",
            "time": "53.78",
            "headline": "Idris Vanterpool third in the 100m Free",
            "type": "medal_bronze",
            "confidence": 0.52,
            "confidence_label": "medium",
        },
    },
]


def _seed_run(world, run_id, *, profile_id, ranked=_RANKED):
    runs_dir = world.tmp / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Riverbend Autumn Sprint Gala"},
        "recognition_report": {"ranked_achievements": ranked},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))


def _mint(world, run_id, pid):
    from mediahub.web.magic_links import mint_review_token

    return mint_review_token(world.app.secret_key or "", run_id, pid)


# ---------------------------------------------------------------------------
# Magic-link page enrichment
# ---------------------------------------------------------------------------


def test_magic_page_shows_summary_and_progress(world):
    pid = _save_org(world)
    _seed_run(world, "mrun00000001", profile_id=pid)
    token = _mint(world, "mrun00000001", pid)
    c = world.app.test_client()
    r = c.get(f"/m/{token}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # Run-level summary: two undecided cards, a progress bar, the org name.
    assert "to review" in html
    assert "approved" in html
    assert 'class="bar"' in html
    assert 'class="summary"' in html
    assert "Riverbend SC" in html  # brand signal: whose queue this is


def test_magic_page_shows_band_and_confidence(world):
    pid = _save_org(world)
    _seed_run(world, "mrun00000002", profile_id=pid)
    token = _mint(world, "mrun00000002", pid)
    c = world.app.test_client()
    html = c.get(f"/m/{token}").get_data(as_text=True)
    # Quality bands + confidence labels surfaced as lite chips.
    assert "ELITE" in html
    assert "STRONG" in html
    assert "High confidence" in html
    assert "Medium confidence" in html
    assert 'class="band"' in html
    assert 'class="conf"' in html


def test_magic_page_why_only_when_not_clean(world):
    """The 'what to check' line shows for a needs_review card and is omitted
    for a clean high-confidence safe card (no noise on the obvious post)."""
    pid = _save_org(world)
    _seed_run(world, "mrun00000003", profile_id=pid)
    token = _mint(world, "mrun00000003", pid)
    c = world.app.test_client()
    html = c.get(f"/m/{token}").get_data(as_text=True)
    # needs_review card's reason is shown...
    assert "verify before posting" in html
    # ...but the safe card's filler reason is not surfaced as a why line.
    assert "High confidence evidence." not in html


def test_magic_page_still_has_core_actions(world):
    """Enrichment must not drop the approve / edit / reject controls."""
    pid = _save_org(world)
    _seed_run(world, "mrun00000004", profile_id=pid)
    token = _mint(world, "mrun00000004", pid)
    c = world.app.test_client()
    html = c.get(f"/m/{token}").get_data(as_text=True)
    assert 'value="approve"' in html
    assert 'value="save_caption"' in html
    assert 'value="reject"' in html
    assert "<textarea" in html
    # Touch-friendly buttons retained (min-height 48px on the lite page).
    assert "min-height:48px" in html


def test_magic_page_counts_reflect_approval(world):
    """Approve one card via the magic action, then the summary should count
    it as approved (the bar can't drift from the pills)."""
    pid = _save_org(world)
    _seed_run(world, "mrun00000005", profile_id=pid)
    token = _mint(world, "mrun00000005", pid)
    c = world.app.test_client()
    # Approve card s1 through the magic action endpoint.
    c.post(f"/m/{token}/card/s1", data={"action": "approve"})
    html = c.get(f"/m/{token}").get_data(as_text=True)
    assert "Approved" in html  # the per-card pill
    # One of two cards approved now.
    assert "1</b> approved" in html


# ---------------------------------------------------------------------------
# Desktop review page: responsive triage controls
# ---------------------------------------------------------------------------


def test_review_page_has_mobile_responsive_rules(world):
    pid = _save_org(world)
    _seed_run(world, "drun00000001", profile_id=pid)
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    html = c.get("/review/drun00000001").get_data(as_text=True)
    # The U.4 phone breakpoint + full-width 46px triage targets.
    assert "max-width: 700px" in html
    assert ".wf-actions .btn" in html
    assert "46px" in html


def test_review_page_renders_triage_controls(world):
    """Sanity: the approve/re-queue controls the responsive CSS targets are
    actually on the page."""
    pid = _save_org(world)
    _seed_run(world, "drun00000002", profile_id=pid)
    c = world.app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    html = c.get("/review/drun00000002").get_data(as_text=True)
    assert "wf-actions" in html
    assert 'data-mh-wf="approved"' in html
