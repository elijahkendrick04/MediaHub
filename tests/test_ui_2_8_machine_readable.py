"""tests/test_ui_2_8_machine_readable.py — UI2.8 Codeblock raw parsed-data view.

Roadmap **UI2.8** (UI2 design-system-uplift follow-on): give the kit's Codeblock
effect the *purpose-built host surface* it was waiting for — an inline,
syntax-highlighted, copyable view of the **machine-readable data the recognition
engine produced** for a run, on the review page's Recognition-summary card.

It is the UI2 pattern exactly: the kit (the first-party, no-CDN server-side
highlighter ``mediahub.web.code_highlight`` + its ``mh-cs-*`` / ``mh-tok-*`` CSS,
shipped for UI 1.11) already existed; UI2.8 builds the surface that reuses it for
a real explainability payload rather than force-fitting it.

This module pins the whole feature:

  1. Kit layer — the Codeblock CSS (``.mh-cs-panel`` + ``.mh-tok-*``) and the
     copy behaviour (``.mh-cs-copy`` → ``bindCopy`` in ui-kit.js) are present.
  2. The ``_machine_readable_run`` helper — a *whitelisted*, bounded, never-raising
     JSON assembler (so no DATA_DIR path / provider key / internal blob leaks, and
     a huge meet can't render a multi-megabyte block).
  3. Rendering — ``code_highlight.code_block`` HTML-escapes the payload and ships
     the copy affordance.
  4. Wiring — the real ``/review/<run_id>`` page carries the inline block with the
     run's genuine meet / counts / ranked achievements, next to the existing
     download link (no regression).
  5. Safety — every shown value is HTML-escaped, the surface is server-rendered
     (works with JS disabled), it adds no CDN dependency, and it rides the run's
     existing access guard.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import mediahub.web as _webpkg  # noqa: E402

_WEB_DIR = Path(_webpkg.__file__).resolve().parent
_COMPONENTS_CSS = (_WEB_DIR / "static" / "theme" / "theme-components.css").read_text()
_UI_KIT_JS = (_WEB_DIR / "static" / "js" / "ui-kit.js").read_text()


@pytest.fixture(scope="module")
def web():
    import mediahub.web.web as wm

    return wm


# ===========================================================================
# 1. Kit layer — the reused Codeblock styling + copy behaviour exist
# ===========================================================================
class TestKitCss:
    def test_codeblock_panel_and_token_classes_present(self):
        # UI2.8 reuses the first-party highlighter's classes — they must be
        # styled, or the inline view would render as unstyled text.
        for sel in (".mh-code", ".mh-cs-panel", ".mh-cs-copy", ".mh-cs-head"):
            assert sel in _COMPONENTS_CSS, f"{sel} missing from theme-components.css"
        for tok in (".mh-tok-property", ".mh-tok-string", ".mh-tok-number"):
            assert tok in _COMPONENTS_CSS, f"{tok} missing — JSON wouldn't colour"

    def test_copy_button_behaviour_registered_in_kit(self):
        # The copy button is a progressive enhancement bound by ui-kit.js; with
        # no JS the JSON stays selectable (the button is hidden until `.mh-js`).
        assert "function bindCopy" in _UI_KIT_JS
        assert 'each(root, ".mh-cs-copy", bindCopy)' in _UI_KIT_JS


# ===========================================================================
# 2. The _machine_readable_run helper — whitelist, bounds, robustness
# ===========================================================================
def _sample_run(n_ach: int = 3) -> dict:
    achs = []
    for i in range(n_ach):
        achs.append(
            {
                "rank": i + 1,
                "quality_band": "standout" if i == 0 else "nice",
                "suggested_post_type": "spotlight" if i == 0 else "feed",
                "achievement": {
                    "type": "personal_best",
                    "swimmer_name": f"Swimmer {i}",
                    "event": "100m Freestyle",
                    "time": f"5{i}.21",
                    "confidence_label": "high",
                },
            }
        )
    return {
        "meet": {
            "name": "County Champs",
            "date": "2026-03-01",
            "course": "SCM",
            "venue": "Wales NPC",
            # Non-whitelisted sensitive-ish fields that MUST NOT leak:
            "_source_path": "/home/user/DATA/runs_v4/secret.json",
        },
        "recognition_report": {
            "n_achievements": n_ach,
            "ranked_achievements": achs,
        },
        "parsed_swim_count": 120,
        "our_swim_count": 18,
        "parse_warnings": ["row 12 ambiguous age group"],
        # Top-level sensitive blobs that MUST NOT leak (the helper is
        # field-whitelisted, so none of these ever surface):
        "ANTHROPIC_API_KEY": "sk-should-never-appear",
        "abs_path": "/home/user/DATA/uploads_v4/file.hy3",
    }


class TestMachineReadableHelper:
    def test_output_is_valid_json_with_expected_shape(self, web):
        doc = json.loads(web._machine_readable_run(_sample_run(), "run-1"))
        assert doc["run_id"] == "run-1"
        assert doc["meet"]["name"] == "County Champs"
        assert doc["counts"] == {
            "parsed_swims": 120,
            "club_swims": 18,
            "achievements": 3,
        }
        assert len(doc["achievements"]) == 3
        a0 = doc["achievements"][0]
        assert a0["rank"] == 1
        assert a0["swimmer"] == "Swimmer 0"
        assert a0["suggested_post_type"] == "spotlight"
        assert doc["parse_warnings"] == ["row 12 ambiguous age group"]

    def test_whitelist_blocks_sensitive_leakage(self, web):
        # The single most important property: a key/path that happens to sit in
        # the run dict can never ride into a user-visible page.
        out = web._machine_readable_run(_sample_run(), "run-1")
        assert "ANTHROPIC_API_KEY" not in out
        assert "sk-should-never-appear" not in out
        assert "_source_path" not in out
        assert "/home/user/DATA" not in out
        assert "abs_path" not in out

    def test_achievements_are_capped_with_an_honest_marker(self, web):
        out = web._machine_readable_run(_sample_run(50), "run-1", max_achievements=10)
        doc = json.loads(out)
        assert len(doc["achievements"]) == 10
        assert doc["achievements_truncated"] == {"shown": 10, "total": 50}

    def test_no_truncation_marker_when_under_cap(self, web):
        doc = json.loads(web._machine_readable_run(_sample_run(3), "run-1"))
        assert "achievements_truncated" not in doc

    def test_parse_warnings_are_bounded(self, web):
        run = _sample_run(0)
        run["parse_warnings"] = [f"warn {i}" for i in range(200)]
        doc = json.loads(web._machine_readable_run(run, "run-1"))
        assert len(doc["parse_warnings"]) == 50

    def test_empty_or_missing_report_is_still_valid_json(self, web):
        # A run mid-pipeline (no recognition_report yet) must not break the view.
        doc = json.loads(web._machine_readable_run({}, "run-empty"))
        assert doc["run_id"] == "run-empty"
        assert doc["achievements"] == []
        assert doc["meet"]["name"] is None

    def test_never_raises_on_garbage(self, web):
        # Defensive: malformed achievement entries → honest doc, never a 500.
        run = {"recognition_report": {"ranked_achievements": ["not-a-dict", 7, None]}}
        out = web._machine_readable_run(run, "run-x")
        doc = json.loads(out)  # still parseable
        assert "achievements" in doc or "error" in doc

    def test_non_serialisable_values_do_not_crash(self, web):
        run = _sample_run(1)
        run["recognition_report"]["ranked_achievements"][0]["achievement"]["time"] = object()
        out = web._machine_readable_run(run, "run-1")  # default=str catches it
        json.loads(out)  # parseable


# ===========================================================================
# 3. Rendering through the real Codeblock highlighter — escaping + copy
# ===========================================================================
class TestCodeblockRendering:
    def test_payload_is_html_escaped_in_the_block(self, web):
        run = _sample_run(1)
        run["recognition_report"]["ranked_achievements"][0]["achievement"]["swimmer_name"] = (
            "<script>alert(1)</script>"
        )
        payload = web._machine_readable_run(run, "run-xss")
        # Raw (un-rendered) JSON still contains the literal text...
        assert "<script>" in payload
        block = web._code_hl.code_block(payload, "json", label="Recognition data")
        # ...but the rendered Codeblock escapes it — no live markup breaks out.
        assert "<script>alert(1)</script>" not in block
        assert "&lt;script&gt;" in block

    def test_block_ships_label_panel_and_copy(self, web):
        block = web._code_hl.code_block(
            web._machine_readable_run(_sample_run(2), "run-1"),
            "json",
            label="Recognition data",
        )
        assert "mh-code-block" in block
        assert 'class="language-json"' in block
        assert "Recognition data" in block
        assert "mh-cs-copy" in block  # the copy affordance
        assert "mh-tok-property" in block  # JSON keys actually highlighted


# ===========================================================================
# Integration — a seeded run rendered through the real /review route
# ===========================================================================
@pytest.fixture
def mr_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for env in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="riverside", display_name="Riverside SC"))

    run_id = "run-mr-" + uuid.uuid4().hex[:8]
    achievements = [
        {
            "achievement": {
                "swim_id": "riverside:Patel,Maya:100FR:gold",
                "swimmer_name": "Maya Patel",
                "event": "100m Freestyle (LC)",
                "type": "medal_gold",
                "headline": "Maya Patel wins gold in 100m Freestyle",
                "time": "59.10",
                "confidence_label": "high",
                "confidence": 0.95,
            },
            "rank": 1,
            "priority": 9.0,
            "quality_band": "elite",
            "suggested_post_type": "feed",
        },
        {
            "achievement": {
                # An XSS attempt persisted into the run must render escaped.
                "swim_id": "riverside:Lee,Jordan:50BK:pb",
                "swimmer_name": "Jordan <script>alert(1)</script> Lee",
                "event": "50m Backstroke (LC)",
                "type": "personal_best",
                "headline": "Jordan Lee sets a PB",
                "time": "31.40",
                "confidence_label": "high",
                "confidence": 0.9,
            },
            "rank": 2,
            "priority": 5.0,
            "quality_band": "strong",
            "suggested_post_type": "story",
        },
    ]
    run_payload = {
        "run_id": run_id,
        "profile_id": "riverside",
        "profile_display": "Riverside SC",
        "club_filter": "Riverside SC",
        "meet": {"name": "Spring Invitational", "course": "LCM"},
        "cards": [],
        "trust": {"score": 0.9},
        "recognition_report": {
            "meet_name": "Spring Invitational",
            "ranked_achievements": achievements,
            "n_achievements": 2,
            "n_swims_analysed": 2,
        },
        "parsed_swim_count": 64,
        "our_swim_count": 12,
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
        # A secret that must never reach the page (proves the whitelist end-to-end).
        "ANTHROPIC_API_KEY": "sk-end-to-end-should-never-appear",
    }
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))

    wm._init_db()
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
        "meet_name, file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "riverside", "Spring Invitational", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["active_profile_id"] = "riverside"
        yield {"client": c, "run_id": run_id}


class TestReviewWiring:
    def _body(self, mr_app):
        r = mr_app["client"].get(f"/review/{mr_app['run_id']}")
        assert r.status_code == 200
        return r.get_data(as_text=True)

    def test_inline_machine_readable_block_present(self, mr_app):
        body = self._body(mr_app)
        assert 'id="mh-machine-readable"' in body
        assert "mh-machine-readable" in body
        # Rendered through the Codeblock kit, not as a raw <pre> dump.
        assert "mh-code-block" in body
        assert 'class="language-json"' in body

    def test_block_carries_the_runs_real_data(self, mr_app):
        body = self._body(mr_app)
        # The codeblock tokenises JSON keys, so assert on the highlighted spans.
        assert "Spring Invitational" in body
        assert "Maya Patel" in body
        # Counts surfaced (parsed/club-matched).
        assert "parsed_swims" in body
        assert "club_swims" in body

    def test_existing_download_link_still_present(self, mr_app):
        # No regression: the surface is added *alongside* the download, not in
        # place of it.
        body = self._body(mr_app)
        assert "Download recognition JSON" in body

    def test_persisted_xss_is_escaped_in_the_block(self, mr_app):
        # Scope the assertion to the UI2.8 block: a swimmer name carrying a
        # persisted XSS attempt renders escaped inside the machine-readable
        # codeblock (the highlighter HTML-escapes every run of text).
        body = self._body(mr_app)
        i = body.index('id="mh-machine-readable"')
        block = body[i : i + 8000]  # the inline codeblock lives in this region
        assert "<script>alert(1)</script>" not in block
        assert "&lt;script&gt;" in block

    def test_no_raw_persisted_xss_anywhere_on_the_page(self, mr_app):
        # Hardening uncovered while building UI2.8: the review queue's
        # `.ach-row` carried `data-swimmer` / `data-event` *unescaped*, so a
        # swimmer name with a quote could break out of the attribute (a stored
        # XSS from a parsed results file). Those attributes are now `_h()`-escaped
        # consistently with the filter `<option>` values, so the raw script tag
        # appears nowhere in the rendered page.
        body = self._body(mr_app)
        assert "<script>alert(1)</script>" not in body
        assert 'data-swimmer="Jordan <script>' not in body

    def test_secret_never_reaches_the_page(self, mr_app):
        # End-to-end whitelist proof: an API key sitting in the run JSON is not
        # rendered anywhere on /review.
        body = self._body(mr_app)
        assert "sk-end-to-end-should-never-appear" not in body
        assert "ANTHROPIC_API_KEY" not in body


class TestFailSafeAndNoCdn:
    def test_block_is_server_rendered_not_js_injected(self, mr_app):
        # The whole point of server-side highlighting: the JSON is in the HTML,
        # so a no-JS / reduced-motion reader sees it (only copy needs JS).
        body = mr_app["client"].get(f"/review/{mr_app['run_id']}").get_data(as_text=True)
        # The block sits before </html> as real markup, not built by a script.
        assert "mh-machine-readable" in body

    def test_helper_output_introduces_no_external_url(self, web):
        out = web._machine_readable_run(_sample_run(3), "run-1")
        for bad in ("http://", "https://", "fonts.googleapis", "gstatic", "@import"):
            assert bad not in out
