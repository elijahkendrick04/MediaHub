"""P11 — per-card workflow-state keying (F11) + cautious safe_to_post (F51).

F11 (``src/mediahub/web/web.py``): one swim can yield several ranked
achievements that share a ``swim_id`` (a PB + a medal from the same race, or
the double-registered milestone / club-record detectors). Interactive workflow
state is keyed per ``(run_id, card_id)``, so two rows sharing a card_id used to
make an approve / reject / caption-edit on one silently apply to its twin, and
the per-tab counts double-counted the single state. The review + spotlight
surfaces now assign each ranked achievement a UNIQUE ``~n``-deduped card id
(first occurrence keeps the bare swim_id for back-compat, later duplicates get
a ``~n`` suffix), so twins decide independently — while the render/preview
routes still key on the bare swim_id so a twin's graphic still resolves.

F51: a missing ``safe_to_post`` must never default to ``safe`` — the honest
default is the cautious ``needs_review`` verdict with the gap flagged.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import re
import sys
import uuid

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_WEB_SRC = (_ROOT / "src" / "mediahub" / "web" / "web.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Pure-helper unit tests (no app / fixtures needed)
# --------------------------------------------------------------------------- #
class TestHelpers:
    def _ranked(self):
        return [
            {"achievement": {"swim_id": "a:1:F:pb", "type": "pb"}, "rank": 1},
            {"achievement": {"swim_id": "a:1:F:pb", "type": "pb"}, "rank": 2},  # twin
            {"achievement": {"swim_id": "b:2:M:gold", "type": "medal_gold"}, "rank": 3},
            {"achievement": {"type": "weekend"}, "rank": 4},  # no swim_id
        ]

    def test_unique_card_ids_dedup(self):
        import mediahub.web.web as W

        assert W._unique_card_ids(self._ranked()) == [
            "a:1:F:pb",
            "a:1:F:pb~2",
            "b:2:M:gold",
            "",
        ]

    def test_unique_card_ids_no_duplicates_is_identity(self):
        """A run with no duplicate swim_ids keys byte-identically to the bare
        swim_id — the back-compat guarantee for persisted workflow state."""
        import mediahub.web.web as W

        ranked = [
            {"achievement": {"swim_id": "x"}},
            {"achievement": {"swim_id": "y"}},
            {"achievement": {"swim_id": "z"}},
        ]
        assert W._unique_card_ids(ranked) == ["x", "y", "z"]

    def test_unique_card_ids_sp_fallback(self):
        import mediahub.web.web as W

        ids = W._unique_card_ids(self._ranked(), base_fn=W._card_base_id_for)
        assert ids == ["a:1:F:pb", "a:1:F:pb~2", "b:2:M:gold", "sp:weekend:"]

    def test_base_card_id_strips_suffix(self):
        import mediahub.web.web as W

        assert W._base_card_id("a:1:F:pb~2") == "a:1:F:pb"
        assert W._base_card_id("a:1:F:pb~17") == "a:1:F:pb"
        assert W._base_card_id("a:1:F:pb") == "a:1:F:pb"
        assert W._base_card_id("sp:x:y") == "sp:x:y"
        # A swim_id never carries a bare '~digits' tail today; only ~n suffixes
        # minted here are stripped.
        assert W._base_card_id("") == ""

    def test_dom_card_uuid_neutralises_tilde(self):
        import mediahub.web.web as W

        assert W._dom_card_uuid("a:1,F~2") == "a_1_F_2"
        # No ~/:/, → byte-identical to the old inline slug.
        assert W._dom_card_uuid("plainid") == "plainid"

    def test_resolve_card_ra_by_unique_id(self):
        import mediahub.web.web as W

        ranked = self._ranked()
        assert W._resolve_card_ra(ranked, "a:1:F:pb") is ranked[0]
        assert W._resolve_card_ra(ranked, "a:1:F:pb~2") is ranked[1]
        assert W._resolve_card_ra(ranked, "b:2:M:gold") is ranked[2]
        assert W._resolve_card_ra(ranked, "missing") is None
        assert W._resolve_card_ra(ranked, "") is None

    def test_run_card_id_set_includes_twins(self):
        import mediahub.web.web as W

        rd = {"recognition_report": {"ranked_achievements": self._ranked(), "meet_name": "M"}}
        s = W._run_card_id_set(rd)
        assert {"a:1:F:pb", "a:1:F:pb~2", "b:2:M:gold"} <= s

    def test_safe_to_post_missing_is_cautious(self):
        import mediahub.web.web as W

        for empty in (None, {}, "", [], {"reason": "x"}):
            v = W._safe_to_post_or_cautious(empty)
            assert v["level"] == "needs_review", empty
            assert v.get("missing") is True, empty

    def test_safe_to_post_real_verdict_untouched(self):
        import mediahub.web.web as W

        assert W._safe_to_post_or_cautious({"level": "safe"}) == {"level": "safe"}
        assert W._safe_to_post_or_cautious({"level": "do_not_post", "reason": "r"})["level"] == (
            "do_not_post"
        )


# --------------------------------------------------------------------------- #
# Source guards
# --------------------------------------------------------------------------- #
class TestSourceGuards:
    def test_no_fail_open_safe_to_post(self):
        """F51: the fail-open default must be gone — a missing verdict may
        never resolve to 'safe'."""
        assert 'get("safe_to_post") or {"level": "safe"}' not in _WEB_SRC
        assert "_safe_to_post_or_cautious(" in _WEB_SRC

    def test_dedup_scheme_matches_pipeline(self):
        """F11 mints the same ~n scheme as the export-stub bridge, so ids agree
        across the review page, the content pack and the export stubs."""
        assert 'f"{base}~{n}"' in _WEB_SRC


# --------------------------------------------------------------------------- #
# End-to-end: review page + workflow routes
# --------------------------------------------------------------------------- #
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

    save_profile(ClubProfile(profile_id="org-p11", display_name="Org P11"))

    def _make_run(athletes):
        """athletes: list of (swim_id, name, age). Duplicate swim_ids are the
        twin case F11 fixes."""
        run_id = "run-p11-" + uuid.uuid4().hex[:8]
        ranked = []
        for i, (sid, name, age) in enumerate(athletes):
            ranked.append(
                {
                    "rank": i + 1,
                    "quality_band": "elite",
                    "priority": 0.9,
                    "achievement": {
                        "type": "pb_confirmed",
                        "swim_id": sid,
                        "swimmer_name": name,
                        "event": "100m Freestyle",
                        "headline": f"{name} set a PB",
                        "confidence": 0.9,
                        "raw_facts": {"time": "57.10", "age": age},
                    },
                    "safe_to_post": {"level": "safe", "reason": "high confidence"},
                    "factors": [],
                }
            )
        (tmp_path / "runs_v4" / f"{run_id}.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "profile_id": "org-p11",
                    "status": "done",
                    "meet": {"name": "Spring Open"},
                    "cards": [],
                    "recognition_report": {
                        "ranked_achievements": ranked,
                        "n_achievements": len(ranked),
                    },
                }
            )
        )
        conn = wm._db()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name,"
            " file_name) VALUES (?, datetime('now'), 'done', ?, ?, ?)",
            (run_id, "org-p11", "Spring Open", "spring.hy3"),
        )
        conn.commit()
        conn.close()
        return run_id

    app = wm.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    with app.test_client() as c:
        r = c.post("/api/organisation/active", data={"profile_id": "org-p11"})
        assert r.status_code == 200
        yield {"client": c, "wm": wm, "make_run": _make_run}


def _review_html(env, run_id):
    r = env["client"].get(f"/review/{run_id}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _row_status(html, card_id):
    """data-status for the .ach-row whose row identity (the inspect button's
    data-card-id, i.e. the unique ~n id) is exactly card_id."""
    marker = f'data-card-id="{card_id}"'
    for m in re.finditer(r'<div class="ach-row"[^>]*data-status="([^"]*)"[^>]*>', html):
        s = m.start()
        end = html.find('<div class="ach-row"', s + 10)
        chunk = html[s : end if end > 0 else len(html)]
        if marker in chunk:
            return m.group(1)
    raise AssertionError(f"no .ach-row for card_id={card_id!r}")


class TestReviewDuplicateSwimIds:
    def test_twins_get_distinct_card_ids(self, env):
        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        html = _review_html(env, run_id)
        # Row identity (workflow state) is the unique ~n id.
        assert 'data-card-id="dup"' in html
        assert 'data-card-id="dup~2"' in html

    def test_bulk_select_checkbox_carries_resolvable_base_id(self, env):
        """The bulk-select checkbox feeds the BULK approve route, whose consent
        gate resolves on the base swim_id — so a twin's checkbox must carry the
        base id (never a ~n id the bulk consent gate can't resolve)."""
        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        html = _review_html(env, run_id)
        # Both twins' checkboxes carry the resolvable base id...
        assert html.count('name="card_ids" value="dup"') == 2
        # ...never the ~n id (which the bulk consent gate can't resolve).
        assert 'name="card_ids" value="dup~2"' not in html

    def test_approve_one_twin_does_not_flip_the_other(self, env):
        from mediahub.workflow.status import CardStatus

        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        # Approve ONLY the second occurrence (the ~n twin).
        env["wm"]._get_wf_store().set_status(run_id, "dup~2", CardStatus.APPROVED)
        html = _review_html(env, run_id)
        assert _row_status(html, "dup") == "queue"
        assert _row_status(html, "dup~2") == "approved"

    def test_approve_via_route_is_independent(self, env):
        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        # Approve the first occurrence through the real workflow route.
        r = env["client"].post(
            f"/api/workflow/{run_id}/dup",
            json={"action": "set_status", "status": "approved"},
        )
        assert r.status_code == 200
        html = _review_html(env, run_id)
        assert _row_status(html, "dup") == "approved"
        assert _row_status(html, "dup~2") == "queue"

    def test_tab_counts_do_not_double_count(self, env):
        from mediahub.workflow.status import CardStatus

        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        env["wm"]._get_wf_store().set_status(run_id, "dup", CardStatus.APPROVED)
        html = _review_html(env, run_id)
        # Exactly one row is approved, one is queued — not two collapsed onto one.
        assert _row_status(html, "dup") == "approved"
        assert _row_status(html, "dup~2") == "queue"

    def test_non_duplicate_still_keys_on_bare_swim_id(self, env):
        """Back-compat: a non-duplicate run keys on the bare swim_id, so state
        persisted before this fix still resolves."""
        from mediahub.workflow.status import CardStatus

        run_id = env["make_run"]([("solo", "Grace Hopper", 30)])
        env["wm"]._get_wf_store().set_status(run_id, "solo", CardStatus.APPROVED)
        html = _review_html(env, run_id)
        assert 'name="card_ids" value="solo"' in html
        assert "solo~2" not in html
        assert _row_status(html, "solo") == "approved"


class TestConsentGateResolvesTwin:
    def test_consent_gate_still_blocks_a_twin(self, env):
        """F11 must not open a consent hole: approving the ~n twin resolves the
        shared card on its base id, so an opted-out athlete is still blocked."""
        from mediahub.compliance.consent import ConsentRegistry

        run_id = env["make_run"]([("dup", "Eira Hughes", 14), ("dup", "Eira Hughes", 14)])
        ConsentRegistry("org-p11").record(athlete_name="Eira Hughes", status="refused")

        # The twin (~n) id must hit the consent gate, not slip past it.
        r = env["client"].post(
            f"/api/workflow/{run_id}/dup~2",
            json={"action": "set_status", "status": "approved"},
        )
        assert r.status_code == 403
        assert r.get_json()["error"] == "consent_blocked"

    def test_caption_edit_is_independent_per_twin(self, env):
        run_id = env["make_run"]([("dup", "Ada Lovelace", 25), ("dup", "Ada Lovelace", 25)])
        ws = env["wm"]._get_wf_store()
        # Save a caption edit on the twin only, via the real set_edits route.
        r = env["client"].post(
            f"/api/workflow/{run_id}/dup~2",
            json={"action": "set_edits", "edits": {"warm-club_headline": "Twin caption"}},
        )
        assert r.status_code == 200
        st_base = ws.load(run_id).get("dup")
        st_twin = ws.load(run_id).get("dup~2")
        twin_caps = getattr(st_twin, "edited_captions", {}) or {}
        assert twin_caps.get("warm-club_headline") == "Twin caption"
        # The first occurrence has no such edit — states are independent.
        base_caps = getattr(st_base, "edited_captions", {}) if st_base else {}
        assert (base_caps or {}).get("warm-club_headline") != "Twin caption"
