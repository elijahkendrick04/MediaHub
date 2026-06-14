"""UI 1.30 — "Weekend at a glance" summary panel.

The review surface (``/review/<run_id>``) leads its achievement list with an
at-a-glance digest of the meet's key story — top swims, PBs and medals —
assembled **purely from the recognition report the pipeline already produced**.
No new LLM call, no external API: counts are tallied from the already-ranked
achievements and every line of copy is either a fixed factual template over
those counts or a headline detection already wrote.

These tests pin three layers:
  * the pure builder (``build_weekend_glance``) — classification of PBs / medals
    / records, the deterministic lede, ranking + de-duplication, and the
    defensive degradation that keeps it from ever raising on an odd run;
  * the pure renderer (``render_weekend_glance_html``) — structure, the
    reused ``.stat`` / ``data-mh-count`` / ``.mh-reveal`` hooks, and strict
    HTML-escaping of every dynamic field (XSS);
  * the wired-in panel against the real ``/review`` route — that it appears,
    sits above "Top achievements", reflects the run, and stays absent (without
    crashing) on a run with nothing to summarise.

It also guards the no-LLM contract (the module must import no provider client)
and the CSS contract in ``theme-components.css``.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web.weekend_glance import (  # noqa: E402
    GlanceMoment,
    WeekendGlance,
    build_weekend_glance,
    render_weekend_glance_html,
)

CSS_PATH = (
    _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
)
MODULE_PATH = _ROOT / "src" / "mediahub" / "web" / "weekend_glance.py"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _ach(swimmer="Jane Smith", event="100m Free", headline="A headline",
         type="pb_confirmed", rank=1, post_angle=None, raw_facts=None):
    a = {"swimmer_name": swimmer, "event": event, "headline": headline, "type": type}
    if post_angle is not None:
        a["post_angle"] = post_angle
    if raw_facts is not None:
        a["raw_facts"] = raw_facts
    return {"rank": rank, "achievement": a}


def _run(meet="Spring Invitational", ranked=None, n_analysed=10, n_achievements=None):
    rr = {"ranked_achievements": ranked or []}
    if n_analysed is not None:
        rr["n_swims_analysed"] = n_analysed
    if n_achievements is not None:
        rr["n_achievements"] = n_achievements
    return {"meet": {"name": meet}, "recognition_report": rr}


# --------------------------------------------------------------------------- #
# build_weekend_glance — emptiness / defensiveness
# --------------------------------------------------------------------------- #

class TestBuildEmptiness:
    def test_none_for_empty_dict(self):
        assert build_weekend_glance({}) is None

    def test_none_for_no_ranked(self):
        assert build_weekend_glance(_run(ranked=[])) is None

    def test_none_for_missing_recognition_report(self):
        assert build_weekend_glance({"meet": {"name": "X"}}) is None

    @pytest.mark.parametrize("bad", [None, 5, "x", [], (), 3.2])
    def test_none_for_non_dict(self, bad):
        assert build_weekend_glance(bad) is None

    def test_none_when_ranked_not_a_list(self):
        assert build_weekend_glance(
            {"recognition_report": {"ranked_achievements": {"not": "a list"}}}
        ) is None

    def test_does_not_raise_on_malformed_entries(self):
        ranked = [None, 5, "x", {}, {"achievement": None}, _ach()]
        g = build_weekend_glance(_run(ranked=ranked))
        assert g is not None
        # Only the valid/usable entries become moments (the {} and
        # {"achievement": None} entries are dicts and still produce a moment
        # with empty fields; the scalars are skipped).
        assert g.n_pbs == 1  # only the real pb_confirmed counts as a PB


# --------------------------------------------------------------------------- #
# PB / medal / record classification
# --------------------------------------------------------------------------- #

class TestClassification:
    @pytest.mark.parametrize("type", [
        "pb_confirmed", "pb_likely", "official_pb_confirmed",
        "pb_cache", "multi_pb_weekend",
    ])
    def test_pb_types_counted(self, type):
        g = build_weekend_glance(_run(ranked=[_ach(type=type)]))
        assert g.n_pbs == 1
        assert g.n_medals == 0

    @pytest.mark.parametrize("angle", [
        "confirmed_official_pb", "pb_improvement", "likely_pb",
    ])
    def test_pb_post_angle_counted_even_if_type_blank(self, angle):
        g = build_weekend_glance(_run(ranked=[_ach(type="", post_angle=angle)]))
        assert g.n_pbs == 1

    @pytest.mark.parametrize("type,colour,g,s,b", [
        ("medal_gold", "gold", 1, 0, 0),
        ("medal_silver", "silver", 0, 1, 0),
        ("medal_bronze", "bronze", 0, 0, 1),
    ])
    def test_medal_types_counted_and_coloured(self, type, colour, g, s, b):
        gl = build_weekend_glance(_run(ranked=[_ach(type=type, headline="X")]))
        assert gl.n_medals == 1
        assert (gl.n_golds, gl.n_silvers, gl.n_bronzes) == (g, s, b)
        assert gl.top_moments[0].kind == colour

    def test_medal_from_raw_facts_place(self):
        # No medal token on the type — the detector's place stamp drives it.
        gl = build_weekend_glance(_run(ranked=[
            _ach(type="final_appearance", raw_facts={"place": 1}),
        ]))
        assert gl.n_medals == 1 and gl.n_golds == 1
        assert gl.top_moments[0].kind == "gold"

    def test_medal_from_raw_facts_medal_field(self):
        gl = build_weekend_glance(_run(ranked=[
            _ach(type="x", raw_facts={"medal": "bronze"}),
        ]))
        assert gl.n_medals == 1 and gl.n_bronzes == 1

    def test_medal_and_pb_combo_counts_as_both(self):
        gl = build_weekend_glance(_run(ranked=[
            _ach(type="medal_and_pb_combo", post_angle="medal_and_pb_combo",
                 raw_facts={"place": 1, "medal": "gold"}),
        ]))
        assert gl.n_pbs == 1  # contains "pb"
        assert gl.n_medals == 1 and gl.n_golds == 1
        # Medal outranks PB for the single headline chip.
        assert gl.top_moments[0].kind == "gold"

    @pytest.mark.parametrize("type", [
        "first_sub_barrier", "biggest_drop_candidate", "fastest_since",
        "return_to_form", "club_debut",
    ])
    def test_milestones_not_padded_into_pb_tally(self, type):
        """Honesty: '4 personal bests' must mean four literal PBs — milestones
        that are not strict PBs are standout moments, not PB count."""
        g = build_weekend_glance(_run(ranked=[_ach(type=type, post_angle="")]))
        assert g.n_pbs == 0
        assert g.n_medals == 0
        assert g.top_moments[0].kind == "moment"

    def test_club_record_is_record_kind(self):
        g = build_weekend_glance(_run(ranked=[_ach(type="club_record", post_angle="club_record")]))
        assert g.top_moments[0].kind == "record"
        assert g.n_pbs == 0 and g.n_medals == 0

    def test_mixed_meet_counts(self):
        ranked = [
            _ach(type="pb_confirmed", rank=1),
            _ach(type="pb_likely", rank=2),
            _ach(type="medal_gold", rank=3, raw_facts={"place": 1}),
            _ach(type="medal_gold", rank=4, raw_facts={"place": 1}),
            _ach(type="medal_bronze", rank=5, raw_facts={"place": 3}),
            _ach(type="club_record", rank=6),
            _ach(type="first_sub_barrier", rank=7),
        ]
        g = build_weekend_glance(_run(ranked=ranked, n_analysed=40))
        assert g.n_pbs == 2
        assert g.n_medals == 3
        assert g.n_golds == 2 and g.n_bronzes == 1 and g.n_silvers == 0


# --------------------------------------------------------------------------- #
# Lede sentence (fixed template, deterministic)
# --------------------------------------------------------------------------- #

class TestLede:
    def test_pbs_and_medals(self):
        g = build_weekend_glance(_run(
            ranked=[_ach(type="pb_confirmed"), _ach(type="medal_gold", raw_facts={"place": 1})],
            n_analysed=24,
        ))
        assert g.lede_stats == "1 personal best and 1 medal across 24 analysed swims."

    def test_plural_pbs_and_medals(self):
        ranked = [_ach(type="pb_confirmed"), _ach(type="pb_likely"),
                  _ach(type="medal_gold", raw_facts={"place": 1}),
                  _ach(type="medal_silver", raw_facts={"place": 2})]
        g = build_weekend_glance(_run(ranked=ranked, n_analysed=2))
        assert g.lede_stats == "2 personal bests and 2 medals across 2 analysed swims."

    def test_only_pbs(self):
        g = build_weekend_glance(_run(ranked=[_ach(type="pb_confirmed")], n_analysed=8))
        assert g.lede_stats == "1 personal best across 8 analysed swims."

    def test_no_pbs_no_medals_falls_back_to_standouts(self):
        ranked = [_ach(type="club_record", post_angle="club_record"),
                  _ach(type="first_sub_barrier")]
        g = build_weekend_glance(_run(ranked=ranked, n_analysed=12, n_achievements=2))
        assert g.lede_stats == "2 standout moments across 12 analysed swims."

    def test_singular_analysed_swim(self):
        g = build_weekend_glance(_run(ranked=[_ach(type="pb_confirmed")], n_analysed=1))
        assert g.lede_stats.endswith("across 1 analysed swim.")

    def test_no_analysed_count_drops_clause(self):
        g = build_weekend_glance(_run(ranked=[_ach(type="pb_confirmed")], n_analysed=0))
        assert g.lede_stats == "1 personal best."

    def test_lede_carries_no_unescaped_meet_name(self):
        # The lede the builder stores never contains the meet name — that is
        # composed (and escaped) at render time, so injection cannot ride in.
        g = build_weekend_glance(_run(meet='<b>x</b>', ranked=[_ach(type="pb_confirmed")]))
        assert "<b>" not in g.lede_stats


# --------------------------------------------------------------------------- #
# Meet name handling
# --------------------------------------------------------------------------- #

class TestMeetName:
    @pytest.mark.parametrize("name", ["", "  ", "(unknown meet)", "unknown", "Unknown Meet"])
    def test_unknown_names_blanked(self, name):
        g = build_weekend_glance(_run(meet=name, ranked=[_ach(type="pb_confirmed")]))
        assert g.meet_name == ""

    def test_real_name_kept_and_trimmed(self):
        g = build_weekend_glance(_run(meet="  County Champs  ", ranked=[_ach()]))
        assert g.meet_name == "County Champs"


# --------------------------------------------------------------------------- #
# Ranking, top-N, de-duplication, fallbacks
# --------------------------------------------------------------------------- #

class TestMomentsShape:
    def test_sorted_by_rank_ascending(self):
        ranked = [_ach(swimmer="C", rank=3), _ach(swimmer="A", rank=1), _ach(swimmer="B", rank=2)]
        g = build_weekend_glance(_run(ranked=ranked))
        assert [m.swimmer for m in g.top_moments] == ["A", "B", "C"]

    def test_default_top_3(self):
        ranked = [_ach(swimmer=f"S{i}", rank=i) for i in range(1, 8)]
        g = build_weekend_glance(_run(ranked=ranked))
        assert len(g.top_moments) == 3
        assert [m.swimmer for m in g.top_moments] == ["S1", "S2", "S3"]

    def test_custom_top_n(self):
        ranked = [_ach(swimmer=f"S{i}", rank=i) for i in range(1, 8)]
        g = build_weekend_glance(_run(ranked=ranked), top_n=5)
        assert len(g.top_moments) == 5

    def test_top_n_zero(self):
        g = build_weekend_glance(_run(ranked=[_ach()]), top_n=0)
        assert g.top_moments == ()
        # Counts are still tallied across the whole report.
        assert g.n_pbs == 1

    def test_dedup_leading_swimmer_name(self):
        g = build_weekend_glance(_run(ranked=[
            _ach(swimmer="Tom Davies", headline="Tom Davies wins gold medal (1st) in 100m Free",
                 type="medal_gold", raw_facts={"place": 1}),
        ]))
        assert g.top_moments[0].sub == "Wins gold medal (1st) in 100m Free"

    def test_dedup_noop_when_name_absent(self):
        g = build_weekend_glance(_run(ranked=[
            _ach(swimmer="Tom Davies", headline="New club record in the 100m Free"),
        ]))
        assert g.top_moments[0].sub == "New club record in the 100m Free"

    def test_sub_falls_back_to_event_when_headline_blank(self):
        g = build_weekend_glance(_run(ranked=[
            _ach(swimmer="Tom", event="100m Free", headline="", type="pb_confirmed"),
        ]))
        assert g.top_moments[0].sub == "100m Free"

    def test_moment_carries_kind_label(self):
        g = build_weekend_glance(_run(ranked=[_ach(type="medal_gold", raw_facts={"place": 1})]))
        assert g.top_moments[0].kind_label == "Gold medal"


class TestCountFallbacks:
    def test_n_analysed_from_our_swim_count(self):
        run = _run(ranked=[_ach()], n_analysed=None)
        run["our_swim_count"] = 33
        g = build_weekend_glance(run)
        assert g.n_analysed == 33

    def test_n_achievements_defaults_to_len_ranked(self):
        ranked = [_ach(rank=1), _ach(rank=2)]
        run = _run(ranked=ranked)  # no n_achievements key
        g = build_weekend_glance(run)
        assert g.n_achievements == 2

    def test_garbage_counts_degrade_to_zero(self):
        run = {"meet": {"name": "M"}, "recognition_report": {
            "ranked_achievements": [_ach()],
            "n_swims_analysed": "not-a-number",
            "n_achievements": None,
        }}
        g = build_weekend_glance(run)
        assert g.n_analysed == 0
        # n_achievements falls back to len(ranked) when not a valid int.
        assert g.n_achievements == 1


# --------------------------------------------------------------------------- #
# Renderer — structure
# --------------------------------------------------------------------------- #

class TestRenderStructure:
    def _html(self, **kw):
        ranked = kw.pop("ranked", [
            _ach(swimmer="Jane Smith", type="pb_confirmed", headline="PB in 200m Fly", rank=1),
            _ach(swimmer="Tom Davies", type="medal_gold", raw_facts={"place": 1},
                 headline="Tom Davies wins gold (1st)", rank=2),
        ])
        return render_weekend_glance_html(build_weekend_glance(_run(ranked=ranked, **kw)))

    def test_render_none_is_empty_string(self):
        assert render_weekend_glance_html(None) == ""

    def test_panel_present(self):
        html = self._html()
        assert 'class="card mh-glance mh-reveal"' in html
        assert "Weekend at a glance" in html
        assert 'id="mh-glance-h"' in html

    def test_lede_with_meet_name(self):
        html = self._html(meet="County Champs", n_analysed=24)
        assert "County Champs:" in html
        assert "across 24 analysed swims." in html

    def test_stat_tiles_use_count_up_hook(self):
        html = self._html(n_analysed=24)
        # PBs / Medals / Standout moments / Swims analysed
        assert html.count('class="stat') >= 4
        assert 'data-mh-count=' in html
        for label in ("PBs", "Medals", "Standout moments", "Swims analysed"):
            assert f">{label}<" in html

    def test_moments_rendered_with_attributes(self):
        html = self._html()
        assert '<ol class="mh-glance-moments">' in html
        assert 'data-kind="pb"' in html
        assert 'data-kind="gold"' in html
        assert 'data-swimmer="Jane Smith"' in html
        assert 'class="mh-glance-chip mh-glance-chip--gold"' in html

    def test_jump_link_to_ach_list(self):
        html = self._html()
        assert 'href="#ach-list"' in html
        assert "See all" in html

    def test_medal_breakdown_title(self):
        html = self._html(ranked=[
            _ach(type="medal_gold", raw_facts={"place": 1}, rank=1),
            _ach(type="medal_silver", raw_facts={"place": 2}, rank=2),
        ])
        assert 'title="1 gold · 1 silver"' in html

    def test_no_moments_block_when_top_n_zero(self):
        html = render_weekend_glance_html(
            build_weekend_glance(_run(ranked=[_ach()]), top_n=0)
        )
        assert "mh-glance-moments" not in html
        # but the stat band is still there
        assert "Weekend at a glance" in html


# --------------------------------------------------------------------------- #
# Renderer — escaping / XSS
# --------------------------------------------------------------------------- #

class TestRenderEscaping:
    def test_swimmer_name_escaped(self):
        html = render_weekend_glance_html(build_weekend_glance(_run(ranked=[
            _ach(swimmer='<script>alert(1)</script>', type="pb_confirmed"),
        ])))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_headline_escaped(self):
        html = render_weekend_glance_html(build_weekend_glance(_run(ranked=[
            _ach(swimmer="Jo", headline='<img src=x onerror=alert(1)>', type="pb_confirmed"),
        ])))
        assert "<img src=x" not in html
        assert "&lt;img" in html

    def test_meet_name_escaped_in_lede(self):
        html = render_weekend_glance_html(build_weekend_glance(_run(
            meet='<b>EVIL</b>', ranked=[_ach(type="pb_confirmed")],
        )))
        assert "<b>EVIL</b>" not in html
        assert "&lt;b&gt;EVIL&lt;/b&gt;" in html

    def test_event_attribute_escaped(self):
        html = render_weekend_glance_html(build_weekend_glance(_run(ranked=[
            _ach(event='100m " onmouseover="x', type="pb_confirmed"),
        ])))
        assert 'onmouseover="x' not in html
        assert "&#34;" in html or "&quot;" in html


# --------------------------------------------------------------------------- #
# No-LLM contract + CSS contract
# --------------------------------------------------------------------------- #

class TestContracts:
    def test_module_imports_no_llm_client(self):
        """UI 1.30's mandate: no new LLM call. The module must not pull in any
        provider client / LLM wrapper — checked on the actual import statements
        (the docstring is free to *say* "no LLM call")."""
        import_lines = [
            ln.strip() for ln in MODULE_PATH.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(("import ", "from "))
        ]
        blob = "\n".join(import_lines).lower()
        for needle in ("media_ai", "ai_core", "anthropic", "genai", "gemini",
                       "replicate", ".llm", "media_ai.llm"):
            assert needle not in blob, f"weekend_glance must import no LLM client (found {needle!r})"

    def test_css_rules_present(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        for sel in (
            ".mh-glance",
            ".mh-glance-eyebrow",
            ".mh-glance-lede",
            ".mh-glance-moments",
            ".mh-glance-moment",
            ".mh-glance-chip",
            ".mh-glance-chip--gold",
            ".mh-glance-chip--pb",
            ".mh-glance-jump",
        ):
            assert sel in css, f"missing CSS rule {sel}"

    def test_css_motion_is_reduced_motion_gated(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        block = css[css.find("UI 1.30"):]
        assert "prefers-reduced-motion: reduce" in block
        rm = block[block.find("prefers-reduced-motion"):]
        assert "transform: none" in rm

    def test_css_uses_brand_tokens_not_hardcoded_hex(self):
        css = CSS_PATH.read_text(encoding="utf-8")
        block = css[css.find("UI 1.30"):]
        # The medal/lane/ink accents must come from the design tokens, not
        # ad-hoc hex (keeps the panel on-theme through the cascade).
        assert "var(--medal)" in block and "var(--lane)" in block
        assert not re.search(r"color:\s*#[0-9a-fA-F]{3,6}", block), "no hardcoded hex colours"


# --------------------------------------------------------------------------- #
# Integration — the real /review route
# --------------------------------------------------------------------------- #

def _seed_run(tmp_path, wm, profile_id, run_payload):
    run_id = run_payload["run_id"]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(run_payload))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs "
        "(id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, profile_id, run_payload["meet"]["name"], "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


@pytest.fixture
def review_env(tmp_path, monkeypatch):
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
    save_profile(ClubProfile(
        profile_id="org-test",
        display_name="Test Club",
        brand_voice_summary="Clear and energetic.",
    ))

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    with app.test_client() as client:
        r = client.post("/api/organisation/active", data={"profile_id": "org-test"})
        assert r.status_code == 200, r.get_json()
        yield {"client": client, "wm": wm, "tmp_path": tmp_path}


def _review_payload(profile_id, ranked, meet="GLANCE TEST INVITATIONAL", n_analysed=20):
    run_id = "run-glance-" + uuid.uuid4().hex[:8]
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "profile_display": "Test Club",
        "meet": {"name": meet},
        "cards": [],
        "trust": {"score": 0.85},
        "recognition_report": {
            "ranked_achievements": ranked,
            "n_elite": len(ranked),
            "n_strong": 0,
            "n_story": 0,
            "n_achievements": len(ranked),
            "n_swims_analysed": n_analysed,
        },
        "parse_warnings": [],
        "self_check": {},
        "detector_summary": {},
        "dispatch_log": {},
    }


class TestReviewIntegration:
    def test_panel_appears_on_review(self, review_env):
        ranked = [
            _ach(swimmer="Jane Smith", event="200m Fly", headline="PB in 200m Fly",
                 type="pb_confirmed", rank=1),
            _ach(swimmer="Tom Davies", event="100m Free", headline="Tom Davies wins gold (1st)",
                 type="medal_gold", rank=2, raw_facts={"place": 1}),
        ]
        payload = _review_payload("org-test", ranked, n_analysed=18)
        run_id = _seed_run(review_env["tmp_path"], review_env["wm"], "org-test", payload)

        r = review_env["client"].get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        # `id="mh-glance-h"` only exists in the rendered panel — the bare token
        # `mh-glance` is also in the inlined CSS, so it is not a usable sentinel.
        assert 'id="mh-glance-h"' in body
        assert "Weekend at a glance" in body
        # Lede reflects the meet + the real counts.
        assert "GLANCE TEST INVITATIONAL:" in body
        assert "1 personal best and 1 medal across 18 analysed swims." in body
        # Top swimmers surface in the digest.
        assert "Jane Smith" in body and "Tom Davies" in body

    def test_panel_sits_above_top_achievements(self, review_env):
        ranked = [_ach(swimmer="Jane Smith", type="pb_confirmed", rank=1)]
        payload = _review_payload("org-test", ranked)
        run_id = _seed_run(review_env["tmp_path"], review_env["wm"], "org-test", payload)

        body = review_env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        i_glance = body.find('id="mh-glance-h"')
        i_top = body.find(">Top achievements<")
        assert -1 < i_glance < i_top, (i_glance, i_top)

    def test_panel_absent_on_empty_run_without_crash(self, review_env):
        payload = _review_payload("org-test", [])
        run_id = _seed_run(review_env["tmp_path"], review_env["wm"], "org-test", payload)

        r = review_env["client"].get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'id="mh-glance-h"' not in body  # nothing to summarise -> no panel
        assert "Traceback" not in body

    def test_panel_escapes_malicious_swimmer_name(self, review_env):
        ranked = [_ach(swimmer='<script>alert(1)</script>', type="pb_confirmed", rank=1)]
        payload = _review_payload("org-test", ranked)
        run_id = _seed_run(review_env["tmp_path"], review_env["wm"], "org-test", payload)

        body = review_env["client"].get(f"/review/{run_id}").get_data(as_text=True)
        assert 'id="mh-glance-h"' in body
        # Scope the XSS assertion to the glance panel itself (the rest of the
        # review page is out of this feature's scope). The panel must escape the
        # name everywhere it surfaces it — visible text and data-attribute alike.
        start = body.find('<section class="card mh-glance')
        assert start != -1
        panel = body[start:body.find("</section>", start)]
        assert "<script>alert(1)</script>" not in panel
        assert "&lt;script&gt;" in panel

    def test_review_still_ok_when_glance_build_fails(self, review_env, monkeypatch):
        """The panel is fail-soft: if the digest blows up, /review still
        renders its achievements rather than 500-ing."""
        wm = review_env["wm"]
        monkeypatch.setattr(
            wm, "_build_weekend_glance",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        ranked = [_ach(swimmer="Jane Smith", event="200m Fly", headline="PB set",
                       type="pb_confirmed", rank=1)]
        payload = _review_payload("org-test", ranked)
        run_id = _seed_run(review_env["tmp_path"], wm, "org-test", payload)

        r = review_env["client"].get(f"/review/{run_id}")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert 'id="mh-glance-h"' not in body    # panel suppressed
        assert "Jane Smith" in body             # but the page still rendered cards
        assert "Top achievements" in body


# --------------------------------------------------------------------------- #
# Dataclass sanity
# --------------------------------------------------------------------------- #

class TestDataclasses:
    def test_glance_is_frozen(self):
        g = build_weekend_glance(_run(ranked=[_ach()]))
        assert isinstance(g, WeekendGlance)
        with pytest.raises(Exception):
            g.n_pbs = 99  # type: ignore[misc]

    def test_moment_is_frozen(self):
        m = build_weekend_glance(_run(ranked=[_ach()])).top_moments[0]
        assert isinstance(m, GlanceMoment)
        with pytest.raises(Exception):
            m.kind = "x"  # type: ignore[misc]
