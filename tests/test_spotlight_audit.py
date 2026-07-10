"""tests/test_spotlight_audit.py — regression locks for the Athlete Spotlight
(meet recap) end-to-end audit.

Each test pins the corrected behaviour of one audited defect:

  * build_spotlight_pack tolerates a present-but-null ``priority`` instead of
    crashing the whole spotlight (TypeError on ``-None``).
  * the re-rank no longer carries the dead ``QualityBand`` import / band_labels
    map, and the band counts stay correct.
  * the spotlight row's onclick handlers are safe for a swimmer whose key /
    swim_id carries an apostrophe (O'Brien) — no JS-string breakout, so a
    crafted results file cannot inject script and the buttons keep working.
  * the copied caption carries real newlines, not literal backslash-n.
  * spotlight_landing rejects a path-traversal ``?run_id=`` (no arbitrary-file
    swimmer-PII reflection) and shows an honest message for an unopenable meet.
  * the composite reel endpoints enforce the athlete-spotlight type guard and
    the run-level tenant check (parity with the caption endpoints).
  * the tone-rewrite endpoint names the "no approved moments" cause instead of
    a misleading generic AI-transient error.
"""

from __future__ import annotations

import html as _htmlmod
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))


# ---------------------------------------------------------------------------
# Pure-unit tests on the core module (no app needed).
# ---------------------------------------------------------------------------


def _run_with_priorities(priorities):
    achs = []
    for i, prio in enumerate(priorities):
        achs.append(
            {
                "achievement": {
                    "swim_id": f"s1:evt{i}",
                    "swimmer_id": "s1",
                    "swimmer_name": "Sam Stroke",
                    "event": f"{50 * (i + 1)}m Freestyle",
                    "time": "1:00.00",
                },
                "priority": prio,
                "quality_band": "elite" if i == 0 else "strong",
            }
        )
    return {
        "run_id": "r",
        "recognition_report": {"meet_name": "Meet", "ranked_achievements": achs},
    }


def test_build_spotlight_pack_tolerates_null_priority():
    """A persisted achievement with ``"priority": null`` (JSON null -> None)
    must not crash the sort — it should rank as the lowest, not raise
    TypeError on ``-None``."""
    from mediahub.club_platform.athlete_spotlight import build_spotlight_pack

    # numeric first, null second — the null must sink to the bottom, no crash.
    pack = build_spotlight_pack(_run_with_priorities([5.0, None]), "s1")
    assert pack is not None
    assert pack["n_achievements"] == 2
    ranks = [ra["rank"] for ra in pack["ranked_achievements"]]
    assert ranks == [1, 2]
    # The 5.0-priority moment outranks the null one.
    assert pack["ranked_achievements"][0]["priority"] == 5.0
    assert (pack["ranked_achievements"][1].get("priority")) is None


def test_build_spotlight_pack_all_null_priority_does_not_crash():
    from mediahub.club_platform.athlete_spotlight import build_spotlight_pack

    pack = build_spotlight_pack(_run_with_priorities([None, None]), "s1")
    assert pack is not None
    assert pack["n_achievements"] == 2


def test_band_counts_correct_without_dead_qualityband_map():
    """The dead ``QualityBand`` import + ``band_labels`` map were removed; the
    band counts must still be right using the plain string literals."""
    import inspect

    from mediahub.club_platform import athlete_spotlight as mod
    from mediahub.club_platform.athlete_spotlight import build_spotlight_pack

    src = inspect.getsource(mod.build_spotlight_pack)
    assert "band_labels" not in src, "dead band_labels map should be gone"
    assert "import QualityBand" not in src, "dead QualityBand import should be gone"

    run = {
        "run_id": "r",
        "recognition_report": {
            "meet_name": "Meet",
            "ranked_achievements": [
                {
                    "achievement": {"swimmer_id": "s", "swimmer_name": "S", "event": "A"},
                    "priority": 9.0,
                    "quality_band": "elite",
                },
                {
                    "achievement": {"swimmer_id": "s", "swimmer_name": "S", "event": "B"},
                    "priority": 8.0,
                    "quality_band": "strong",
                },
                {
                    "achievement": {"swimmer_id": "s", "swimmer_name": "S", "event": "C"},
                    "priority": 7.0,
                    "quality_band": "story",
                },
                {
                    "achievement": {"swimmer_id": "s", "swimmer_name": "S", "event": "D"},
                    "priority": 6.0,
                    "quality_band": "nice",
                },
            ],
        },
    }
    pack = build_spotlight_pack(run, "s")
    assert (pack["n_elite"], pack["n_strong"], pack["n_story"]) == (1, 1, 1)
    assert pack["n_achievements"] == 4  # "nice" counted in total, not in a band


# ---------------------------------------------------------------------------
# App-level tests. Isolated DATA_DIR, one profile, provider keys stripped.
# ---------------------------------------------------------------------------


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    for env in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="acme", display_name="ACME Aquatics"))
    save_profile(ClubProfile(profile_id="rival", display_name="Rival Swim"))

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _persist_run(
    runs_dir, run_id, swim_id, sid, sname, *, owner=None, approve=True, event="100m Freestyle (LC)"
):
    ach = {
        "achievement": {
            "swim_id": swim_id,
            "swimmer_id": sid,
            "swimmer_name": sname,
            "event": event,
            "time": "1:00.00",
            "place": 1,
            "type": "medal_gold",
            "headline": "A strong swim",
            "angle_hint": "season best",
            "pb": True,
        },
        "priority": 9.0,
        "quality_band": "elite",
    }
    doc = {
        "run_id": run_id,
        "meet": {"name": "Test Meet"},
        "recognition_report": {"meet_name": "Test Meet", "ranked_achievements": [ach]},
    }
    if owner:
        doc["profile_id"] = owner
    (runs_dir / f"{run_id}.json").write_text(json.dumps(doc))
    if approve:
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        WorkflowStore(runs_dir).set_status(run_id, swim_id, CardStatus.APPROVED)


def _db_row(wm, run_id, owner):
    from datetime import datetime, timezone

    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, meet_name, file_name, status, created_at, profile_id) "
        "VALUES (?,?,?,?,?,?)",
        (run_id, "Test Meet", "t.pdf", "done", datetime.now(timezone.utc).isoformat(), owner),
    )
    conn.commit()
    conn.close()


def _client(app, pid="acme"):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = pid
    return c


def test_spotlight_row_onclick_safe_for_apostrophe_name(app_ctx):
    """A swimmer whose key carries an apostrophe (O'Brien) — common Irish/British
    surname, and only spaces are stripped upstream — must not break out of the
    inline JS. Before the fix the HTML-escaped id (&#39;) decoded back to ' and
    closed the JS string; a crafted name could inject script."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    sid = "acme:O'Brien,Sean"
    # embed an injection attempt in the swim_id tail (mirrors a hostile upload)
    swim_id = f"{sid}:100'-alert(document.cookie)-'FR"
    _persist_run(runs, "r1", swim_id, sid, "Sean O'Brien")

    c = _client(app)
    html = c.get(f"/spotlight/r1/{sid}").get_data(as_text=True)
    assert html  # rendered, not a recovery page
    assert "A strong swim" in html

    # The copy button no longer takes an interpolated id arg.
    assert "copySpotlightCaption(this)" in html
    assert "copySpotlightCaption(this, '" not in html

    # Every mhCreateGraphic / copy onclick, once the browser decodes the HTML
    # entities, must keep the payload inside a double-quoted JS string literal —
    # i.e. no bare, executable alert(...).
    for oc in re.findall(r'onclick="([^"]*)"', html):
        decoded = _htmlmod.unescape(oc)
        # strip balanced double-quoted string literals; nothing executable
        # (an alert call) may remain in the residue.
        residue = re.sub(r'"(?:\\.|[^"\\])*"', '""', decoded)
        assert "alert(" not in residue, f"JS injection survives in: {decoded}"
        # a raw single quote must never sit outside a string literal
        assert "'" not in residue, f"apostrophe breaks the JS string in: {decoded}"


def test_copy_caption_span_has_real_newlines(app_ctx):
    """The hidden caption span (copied verbatim to the clipboard) must contain
    real line breaks between headline and angle, not literal backslash-n."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    sid = "acme:Doe,Jane"
    _persist_run(runs, "r1", f"{sid}:100FR", sid, "Jane Doe")
    c = _client(app)
    html = c.get(f"/spotlight/r1/{sid}").get_data(as_text=True)
    m = re.search(r'<span class="sp-cap-src"[^>]*>(.*?)</span>', html, re.S)
    assert m, "sp-cap-src span present"
    span = m.group(1)
    assert "\\n" not in span, "must not contain literal backslash-n"
    assert "\n" in span, "must contain a real newline between headline and angle"


def test_spotlight_landing_rejects_path_traversal_run_id(app_ctx, tmp_path_factory):
    """A tampered ?run_id=../../<dir>/victim must not read a JSON file outside
    DATA_DIR and reflect its swimmer roster (PII)."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"

    # a legit run so the picker is non-empty (avoids the early empty-return)
    _persist_run(runs, "good", "acme:G,G:50FR", "acme:G,G", "Good Person")
    _db_row(wm, "good", None)

    # victim file entirely outside DATA_DIR
    outside = tmp_path_factory.mktemp("outside")
    victim = {
        "run_id": "v",
        "recognition_report": {
            "meet_name": "SECRET",
            "ranked_achievements": [
                {
                    "achievement": {
                        "swimmer_id": "x",
                        "swimmer_name": "OutsidePII_Victim",
                        "event": "100 Free",
                    },
                    "priority": 1.0,
                    "quality_band": "elite",
                }
            ],
        },
    }
    vpath = outside / "victim.json"
    vpath.write_text(json.dumps(victim))
    import os

    rel = os.path.relpath(str(vpath)[:-5], str(runs))  # drop .json; _load_run re-appends

    c = _client(app)
    resp = c.get(f"/spotlight?run_id={rel}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "OutsidePII_Victim" not in body, "path-traversal leaked an outside file's PII"
    assert "SECRET" not in body


def test_spotlight_landing_message_for_unopenable_run(app_ctx):
    """A selected meet that _load_run can't open (legacy dir-form, wrong tenant,
    or corrupt) must show an honest message, not a silent blank dead-end."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    # a legit run so the picker is non-empty
    _persist_run(runs, "good", "acme:G,G:50FR", "acme:G,G", "Good Person")
    _db_row(wm, "good", "acme")

    # a run stored ONLY in the legacy nested layout that _load_run doesn't read
    dir_run = runs / "rDir"
    dir_run.mkdir(parents=True, exist_ok=True)
    (dir_run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "rDir",
                "recognition_report": {
                    "meet_name": "DirMeet",
                    "ranked_achievements": [
                        {
                            "achievement": {"swimmer_id": "s", "swimmer_name": "S", "event": "A"},
                            "priority": 1.0,
                            "quality_band": "story",
                        }
                    ],
                },
            }
        )
    )
    _db_row(wm, "rDir", "acme")

    c = _client(app)
    body = c.get("/spotlight?run_id=rDir").get_data(as_text=True)
    assert "open that meet" in body.lower()


# ---- composite reel endpoint guards -------------------------------------


def _build_spotlight_pack_id(wm, c, run_id, sid, monkeypatch=None):
    import mediahub.ai_core as ai_core_pkg

    ai_core_pkg.ask = lambda system, user, **kw: "CAP"
    r = c.post(f"/spotlight/{run_id}/{sid}/build", follow_redirects=False)
    assert r.status_code == 302
    return r.headers["Location"].rstrip("/").split("/")[-1]


def test_reel_rejects_non_spotlight_pack(app_ctx):
    """The composite reel endpoints must 400 unsupported_type for a pack whose
    source isn't athlete_spotlight, even if it carries run_id + swimmer_key."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    sid = "acme:Doe,Jane"
    _persist_run(runs, "r1", f"{sid}:100FR", sid, "Jane Doe")
    c = _client(app)

    from mediahub.club_platform.stub_pack_store import save_pack

    sneaky = save_pack(
        "session_update",
        {"source": "session_update", "run_id": "r1", "swimmer_key": sid},
        [{"caption": "x"}],
        profile_id="acme",
    )
    r = c.post(f"/api/drafts/{sneaky['pack_id']}/card/0/reel-job")
    assert r.status_code == 400
    assert r.get_json().get("error") == "unsupported_type"

    r2 = c.get(f"/api/drafts/{sneaky['pack_id']}/card/0/reel-file")
    assert r2.status_code == 400
    assert r2.get_json().get("error") == "unsupported_type"


def test_reel_enforces_run_tenant_isolation(app_ctx, monkeypatch):
    """A pack owned by org B that names org A's run must not render a reel off
    A's run — the reel path must apply _can_access_run like the caption path."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    sid = "acme:Doe,Jane"
    # r1 is OWNED by acme
    _persist_run(runs, "r1", f"{sid}:100FR", sid, "Jane Doe", owner="acme")
    _db_row(wm, "r1", "acme")

    import mediahub.visual.motion as _m

    monkeypatch.setattr(_m, "render_meet_reel", lambda *a, **k: str(a[2]))

    from mediahub.club_platform.stub_pack_store import save_pack

    fd = {
        "source": "athlete_spotlight",
        "run_id": "r1",
        "swimmer_key": sid,
        "swimmer_name": "Jane",
        "meet_name": "Test Meet",
        "n_approved": 1,
        "n_pbs": 1,
        "n_medals": 1,
        "results_lines": "100 Free",
    }
    rival_pack = save_pack("free_text", fd, [{"caption": "x"}], profile_id="rival")

    c = _client(app, pid="rival")
    r = c.post(f"/api/drafts/{rival_pack['pack_id']}/card/0/reel-job")
    assert r.status_code == 404
    assert r.get_json().get("error") == "run_not_found"

    # positive control: the owner CAN render its own reel (guard not over-broad)
    acme_pack = save_pack("free_text", fd, [{"caption": "x"}], profile_id="acme")
    c2 = _client(app, pid="acme")
    r2 = c2.post(f"/api/drafts/{acme_pack['pack_id']}/card/0/reel-job")
    assert r2.status_code == 202


def test_tone_rewrite_names_no_approved_cause(app_ctx, monkeypatch):
    """If the reviewer un-approves every moment after building, the tone-rewrite
    endpoint must say so — not the misleading generic 'AI couldn't finish'."""
    app, wm, tmp = app_ctx
    runs = tmp / "runs_v4"
    sid = "acme:Doe,Jane"
    swim_id = f"{sid}:100FR"
    _persist_run(runs, "r1", swim_id, sid, "Jane Doe")
    c = _client(app)

    pack_id = _build_spotlight_pack_id(wm, c, "r1", sid)

    # AI available, but every moment is now un-approved.
    monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(runs).set_status("r1", swim_id, CardStatus.REJECTED)

    r = c.post(f"/api/drafts/{pack_id}/card/0/caption?tone=hype")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("error") == "no_approved"
    assert "approve" in (j.get("message") or "").lower()
