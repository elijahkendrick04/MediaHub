"""C-17 — the reel's AI-dub language was URL-only; a bad value dead-ended raw.

The 1.24 dub (``?lang=`` on the reel routes) had no UI: the composer sent
only format + picks, and a hand-crafted unsupported language answered bare
``{'error':'bad_language'}`` JSON.

Now the reel composer offers a "Narration language" select — populated from
the same caption-language registry the Settings picker uses, filtered to the
languages the dub pipeline can actually voice, defaulting to "No narration
dub" — gated exactly like the audio-mix select (a dub re-voices the
narration, which only exists when voiceover is enabled). The pick rides the
job request as ``?lang=``; a ``bad_language`` refusal surfaces its
plain-English message in the styled inline error panel, never the raw enum.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import re
import uuid

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-alpha", display_name="Org Alpha"))

    run_id = "run-c17-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": "org-alpha",
                "meet": {"name": "Spring Open"},
                "cards": [],
                "recognition_report": {
                    "ranked_achievements": [
                        {
                            "rank": 1,
                            "quality_band": "elite",
                            "priority": 0.9,
                            "safe_to_post": {"level": "safe", "reason": "ok"},
                            "achievement": {
                                "swim_id": "swim-1",
                                "swimmer_name": "Maya Patel",
                                "event": "100m Freestyle",
                                "headline": "New PB",
                                "type": "pb",
                                "raw_facts": {"time": "59.99"},
                            },
                        }
                    ],
                    "n_achievements": 1,
                },
            }
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
        " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    WorkflowStore(tmp_path / "runs_v4").set_status(run_id, "swim-1", CardStatus.APPROVED)

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post("/api/organisation/active", data={"profile_id": "org-alpha"})
        assert r.status_code == 200
        yield {"client": c, "run_id": run_id, "wm": wm}


def test_composer_offers_dub_select_when_voiceover_on(env, monkeypatch):
    wm = env["wm"]
    monkeypatch.setenv("MEDIAHUB_VOICEOVER", "1")
    monkeypatch.setattr(wm, "_voiceover_ok", True)
    r = env["client"].get(f"/pack/{env['run_id']}")
    assert r.status_code == 200
    page = r.data.decode("utf-8")
    assert 'id="mh-reel-dub"' in page
    assert "No narration dub" in page
    # Options come from the caption-language registry, filtered to what the
    # dub pipeline can voice; Welsh is the flagship locale.
    assert '<option value="cy">' in page
    assert "(Welsh)" in page
    # English IS the original narration — it is not offered as a dub target.
    assert not re.search(r'id="mh-reel-dub"[^<]*<option value="en">', page)


def test_dub_select_gated_like_the_mix_select(env, monkeypatch):
    wm = env["wm"]
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.setattr(wm, "_voiceover_ok", False)
    r = env["client"].get(f"/pack/{env['run_id']}")
    assert r.status_code == 200
    page = r.data.decode("utf-8")
    assert 'id="mh-reel-dub"' not in page
    assert 'id="mh-reel-mix"' not in page


def test_unsupported_language_is_refused_with_plain_message(env):
    c = env["client"]
    r = c.post(f"/api/runs/{env['run_id']}/reel-job?lang=xx")
    assert r.status_code == 400
    j = r.get_json()
    assert j["error"] == "bad_language"
    # A plain-spoken message rides beside the enum for the UI to show.
    assert "language" in (j.get("message") or "").lower()


# ---------------------------------------------------------------------------
# Source-level: the composer JS sends the pick and shows the message
# ---------------------------------------------------------------------------

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_composer_query_sends_lang_param():
    assert "document.getElementById('mh-reel-dub')" in _SRC
    assert "params.push('lang=' + encodeURIComponent(st.dub))" in _SRC


def test_bad_language_message_reaches_the_styled_inline_error():
    # The reel job-start failure chain includes the response's `message`
    # field (bad_language's plain-English copy), rendered by the shared
    # styled inline error surface (_mhJobFail), not a raw enum fallback.
    assert (
        _SRC.count(
            "res.body.user_message || res.body.message || res.body.detail || res.body.error"
        )
        >= 2
    )


def test_default_composer_still_sends_nothing():
    # An untouched composer ("" dub) must add no lang param at all, keeping
    # the default reel request — and its cache key — byte-identical.
    assert "if (st.dub) params.push(" in _SRC
