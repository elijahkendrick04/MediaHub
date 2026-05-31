"""De-contaminate FIND/adjudicate (council mandate after 6 deliberations).

The autonomous loop never closed a product bug because its FIND/adjudicate INPUT
was contaminated: the tester's own control token ``flow_result`` (e.g.
"live:judged-6-runs", assembled in run.py, never shown to a user) was fed to the
"you ARE the user" judge AND to the council framing, fabricating + confirming the
false bug b07572c63c13.

These tests are the council's required machine-verifiable proof — they assert on
the artifact bag / framing (ground truth), not on any model verdict.
"""
from __future__ import annotations

from autotest import council, fix_loop, semantic
from autotest.report import Finding


# --- Fix 0/A: the provenance guard (filter_artifacts) ----------------------
def test_provenance_map_classifies_every_artifact():
    # Every key _build_artifacts can emit must have a known provenance (no silent
    # gaps — an unclassified key fails closed to tester_control).
    sample = semantic._build_artifacts({
        "flow_result": "live:judged-6-runs", "home_text": "h", "signup_text": "s",
        "review_text": "r", "export_json": {"cards": []}, "pages": [],
    })
    for k in sample:
        assert k in semantic.PROVENANCE, f"artifact {k} has no provenance classification"


def test_filter_drops_disallowed_kinds():
    arts = {"home_text": "h", "flow_result": "live:judged-6-runs", "pages": "200 /"}
    only_rendered = semantic.filter_artifacts(arts, frozenset({semantic.RENDERED_PAGE}))
    assert set(only_rendered) == {"home_text"}


def test_unknown_artifact_fails_closed_to_control():
    # An unclassified key is treated as tester_control (unsafe), so a rendered-only
    # charter drops it rather than leaking an unknown value to a user-perspective judge.
    arts = {"mystery_new_key": "x", "home_text": "h"}
    out = semantic.filter_artifacts(arts, frozenset({semantic.RENDERED_PAGE}))
    assert "mystery_new_key" not in out and "home_text" in out


# --- THE RECURSION BREAK: zero tester_control reaches user_brain ------------
def test_user_brain_never_sees_tester_control():
    """Machine-verifiable proof Fix A works, run against the b07572c63c13 bag."""
    raw = {
        "flow_result": "live:judged-6-runs",        # the contaminant
        "home_text": "MediaHub home ...", "signup_text": "Create club ...",
        "review_text": "review body ...", "export_json": {"cards": []}, "pages": [],
    }
    arts = semantic._build_artifacts(raw)
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    safe = semantic.filter_artifacts(arts, ub.allowed_provenance)

    leaked = [k for k in safe if semantic.PROVENANCE.get(k) == semantic.TESTER_CONTROL]
    assert leaked == [], f"tester_control leaked to user_brain: {leaked}"
    assert "flow_result" not in safe
    # the genuine rendered pages are still present (we didn't break the judge):
    assert {"home_text", "signup_text", "review_text"} <= set(safe)


def test_functional_qa_charter_still_sees_flow_result():
    # The QA persona legitimately inspects flow STATUS — the guard must NOT strip it.
    arts = semantic._build_artifacts({"flow_result": "passed-empty", "export_json": {"cards": []}})
    fn = next(c for c in semantic.CHARTERS if c.name == "functional")
    safe = semantic.filter_artifacts(arts, fn.allowed_provenance)
    assert "flow_result" in safe


def test_permissive_charters_are_intentionally_full_pass():
    # Council blind-spot: functional/output declare the FULL provenance set, so the
    # guard is a deliberate no-op for them. Assert that is BY DESIGN (the explicit
    # ALL_PROVENANCE sentinel), not an accident a future author falls into.
    for name in ("functional", "output"):
        ch = next(c for c in semantic.CHARTERS if c.name == name)
        assert ch.allowed_provenance is semantic.ALL_PROVENANCE, (
            f"{name} must use the explicit ALL_PROVENANCE sentinel, not a hand-listed set")
    # and user_brain is deliberately NOT full-pass:
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    assert ub.allowed_provenance != semantic.ALL_PROVENANCE
    assert semantic.TESTER_CONTROL not in ub.allowed_provenance


def test_unknown_key_fail_closed_for_user_brain_but_open_for_council():
    # Documents the by-design asymmetry: an unknown artifact is dropped for a
    # user-perspective judge (fail-closed) but passes as tester context for a
    # caller that allows TESTER_CONTROL (fail-open) — the council.
    arts = {"some_future_key": "x"}
    ub_allowed = frozenset({semantic.RENDERED_PAGE})
    council_allowed = frozenset({semantic.TESTER_CONTROL, semantic.TESTER_SUMMARY})
    assert "some_future_key" not in semantic.filter_artifacts(arts, ub_allowed)   # fail-closed
    assert "some_future_key" in semantic.filter_artifacts(arts, council_allowed)  # fail-open


def test_run_charter_body_excludes_filtered_keys(monkeypatch):
    # End-to-end through _run_charter: stub the LLM, capture the prompt body, and
    # assert the user_brain prompt contains NO flow_result token.
    captured = {}

    def fake_ask(system, user, max_tokens=0):
        captured["system"], captured["user"] = system, user
        return '{"issues":[]}'

    import autotest.cli_llm as cli
    monkeypatch.setattr(cli, "ask", fake_ask)
    arts = semantic._build_artifacts({
        "flow_result": "live:judged-6-runs", "home_text": "h", "signup_text": "s",
        "review_text": "r", "export_json": {"cards": []}, "pages": [],
    })
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    semantic._run_charter(ub, arts)
    assert "live:judged-6-runs" not in captured["user"], "control token reached the user_brain prompt"
    assert "flow_result" not in captured["user"]


# --- Fix B (behavioral): council framing labels the token, not as product UI --
def test_council_framing_labels_flow_result_as_tester_internal(monkeypatch):
    """Behavioral test (council pt 4): inspect the ACTUAL framing string the council
    builds, not merely that an instruction exists. The control token must be
    labelled tester-internal, never presented as user-facing product evidence."""
    captured = {}

    def fake_deliberate(framed):
        captured["framed"] = framed
        return None   # short-circuit; we only need the framing

    monkeypatch.setattr(council, "deliberate", fake_deliberate)
    cands = [Finding(category="semantic:user_brain", severity="high",
                     title="x", route="/r", expected="e", actual="a", evidence="ev")]
    # Pass a RENDERED PAGE in the artifacts too — it must be MECHANICALLY excluded
    # from the council framing (not just relabelled), proving Fix B is code.
    council.adjudicate(cands, {
        "flow_result": "live:judged-6-runs",
        "home_text": "SECRET_RENDERED_PAGE_TEXT_THE_COUNCIL_MUST_NOT_SEE",
        "export_json": {"cards": []}})

    framed = captured["framed"]
    assert "live:judged-6-runs" in framed                  # the value is present...
    # ...but explicitly labelled as NOT user-visible, never as bare "Flow result:".
    assert "NOT shown to any user" in framed
    assert "Flow result: live:judged-6-runs" not in framed
    # And it appears EXACTLY ONCE (no second un-labelled leak via content_summary).
    assert framed.count("live:judged-6-runs") == 1
    assert "flow=live:judged-6-runs" not in framed
    # MECHANICAL proof (council blocker): the rendered page is STRUCTURALLY absent
    # from the framing — filter_artifacts removed it, not a prose label.
    assert "SECRET_RENDERED_PAGE_TEXT_THE_COUNCIL_MUST_NOT_SEE" not in framed


def test_context_string_is_static_no_artifact_interpolation(monkeypatch):
    """council re-review (Contrarian): prove ``context`` carries no artifact data —
    it is one of two static guidance strings chosen by a bool, so a rendered page
    or control token in the artifacts cannot leak through it."""
    captured = {}
    def _cap(framed):
        captured["f"] = framed
        return None
    monkeypatch.setattr(council, "deliberate", _cap)
    cands = [Finding(category="semantic:functional", severity="high", title="t",
                     route="/r", expected="e", actual="a", evidence="ev")]
    # cold-path artifacts carrying a secret rendered page + control token:
    council.adjudicate(cands, {"flow_result": "CONTROL_TOKEN_X",
                               "home_text": "CONTEXT_LEAK_SECRET", "export_json": {"cards": []}})
    framed = captured["f"]
    # The cold-context guidance block must be present, with NO artifact values in it.
    assert "IMPORTANT TEST CONTEXT" in framed              # the static cold guidance
    assert "CONTEXT_LEAK_SECRET" not in framed             # no rendered page via context
    # control token only appears in its single labelled line, nowhere via context:
    assert framed.count("CONTROL_TOKEN_X") <= 1


def test_control_token_in_a_finding_is_scrubbed_from_issues_txt(monkeypatch):
    """council re-review (Contrarian's residual path, now CLOSED by the scrubber): if
    any finding's text contains a control-token value, scrub_control_tokens redacts the
    value from issues_txt — so even a poisoned finding can't carry the token. This is
    the code gate that replaced the functional/QA 'honor system'."""
    captured = {}
    def _cap(framed):
        captured["f"] = framed
        return None
    monkeypatch.setattr(council, "deliberate", _cap)
    poisoned = Finding(category="semantic:user_brain", severity="high",
                       title="x", route="/r", expected="e",
                       actual="user sees live:judged-6-runs", evidence="ev")
    council.adjudicate([poisoned], {"flow_result": "live:judged-6-runs", "export_json": {"cards": []}})
    # The control-token VALUE is scrubbed from issues_txt (code gate), so even a
    # poisoned finding cannot carry it to the council; the rest of the finding survives.
    issues_part = captured["f"].split("Candidate issues")[1]
    assert "live:judged-6-runs" not in issues_part
    assert "<redacted flow_result>" in issues_part
    assert "user sees" in issues_part


def test_qa_finding_control_token_scrubbed_from_rendered_framing(monkeypatch):
    """council re-review #2 (THE one thing): assert against the RENDERED framing the
    council receives — not the inputs. A functional/QA judge legitimately sees
    flow_result and can author a finding citing it; the control token's VALUE must be
    scrubbed from issues_txt (code gate, not the 'honor system'), while genuine page
    quotes survive."""
    captured = {}

    def _cap(framed):
        captured["f"] = framed
        return None

    monkeypatch.setattr(council, "deliberate", _cap)
    qa = Finding(category="semantic:functional", severity="high",
                 title="Pipeline done but zero cards", route="/review", expected="cards",
                 actual="flow shows live:judged-6-runs yet content pack empty",
                 evidence="flow_result=live:judged-6-runs; cards=0")
    real_quote = Finding(category="semantic:user_brain", severity="medium",
                         title="jargon", route="/dash", expected="clear",
                         actual="the page shows 'Ready TO FILE' which is confusing",
                         evidence="quoted from page: 'Ready TO FILE'")
    council.adjudicate([qa, real_quote],
                       {"flow_result": "live:judged-6-runs", "export_json": {"cards": []}})
    framed = captured["f"]
    issues = framed.split("Candidate issues")[1]
    # The control token VALUE is gone from the evidence channel (scrubbed, code gate)...
    assert "live:judged-6-runs" not in issues
    assert "<redacted flow_result>" in issues
    # ...the genuine rendered-page quote SURVIVES (evidence channel not lobotomised)...
    assert "Ready TO FILE" in issues
    # ...and the ONLY remaining occurrence of the token in the whole framing is the
    # intentionally-labelled tester-internal line (a DECLARED existence signal the
    # council reads by design — value gate, not existence gate). Verify it is that
    # exact line, not a stray leak: this is the council's `<=1x` carve-out, made precise.
    occurrences = [ln for ln in framed.split("\n") if "live:judged-6-runs" in ln]
    assert len(occurrences) == 1
    assert "Tester-internal flow token (NOT shown to any user)" in occurrences[0]


def test_scrub_covers_any_tester_control_artifact_not_a_hardcoded_list():
    """new-judge / temporal-coupling guard: scrub_control_tokens is keyed on the
    PROVENANCE map, so a FUTURE tester_control artifact is redacted automatically —
    no per-token edit, no convention about the current judge roster."""
    # Simulate a future control artifact by adding one to the provenance map.
    semantic.PROVENANCE["future_ctrl"] = semantic.TESTER_CONTROL
    try:
        text = "a finding mentioning SECRET_FUTURE_TOKEN and a real 'Ready TO FILE' quote"
        out = semantic.scrub_control_tokens(text, {"future_ctrl": "SECRET_FUTURE_TOKEN"})
        assert "SECRET_FUTURE_TOKEN" not in out          # future control token redacted
        assert "Ready TO FILE" in out                    # real quote untouched
    finally:
        del semantic.PROVENANCE["future_ctrl"]


def test_scrub_no_false_redaction_on_real_page_quotes():
    """council blind-spot #3 (false-positive risk): the scrub must NOT corrupt genuine
    page quotes. A corpus of realistic finding text + a normal control token: every
    real phrase survives intact, only the token value is redacted."""
    corpus = [
        "the review page shows 'Ready TO FILE' which reads like tax filing",
        "'AQUATICA highlights' appears on a Swansea-branded page",
        "the header still says 'CHECKING…' after the run finished",
        "'032 TOTAL RUNS' uses an unexplained leading zero",
        "two CTAs 'Start a content pack' and 'Create new content' look identical",
    ]
    artifacts = {"flow_result": "live:judged-6-runs"}   # a normal, non-trivial token
    for phrase in corpus:
        out = semantic.scrub_control_tokens(phrase, artifacts)
        assert out == phrase, f"false redaction corrupted a real page quote: {out!r}"


def test_scrub_skips_short_control_values():
    # A short control value (< 4 chars) is NOT scrubbed, to avoid mangling common
    # substrings in genuine quotes (the deliberate false-positive guard).
    out = semantic.scrub_control_tokens("the page says done and ok", {"flow_result": "ok"})
    assert out == "the page says done and ok"


def test_scrub_leaves_rendered_pages_and_summaries_untouched():
    # Only tester_control values are scrubbed — a rendered page or summary value that
    # happens to appear in a finding (legitimate evidence) is NOT redacted.
    text = "user sees home page text 'Welcome' and review 'Ready TO FILE'"
    out = semantic.scrub_control_tokens(text, {
        "home_text": "Welcome", "review_text": "Ready TO FILE", "flow_result": "live:judged-6-runs"})
    assert "Welcome" in out and "Ready TO FILE" in out   # rendered pages survive


def test_user_brain_judge_cannot_author_a_control_token_finding(monkeypatch):
    """The UPSTREAM defence (closes the issues_txt path at its source): because the
    provenance guard removes flow_result from the user_brain prompt, the judge never
    sees the control token and so cannot quote it in a finding. We assert the prompt
    body the user_brain judge receives contains no control token, for the exact
    b07572c63c13 artifacts — so no such finding can be authored to flow into issues_txt."""
    captured = {}

    def fake_ask(system, user, max_tokens=0):
        captured["user"] = user
        return '{"issues":[]}'

    import autotest.cli_llm as cli
    monkeypatch.setattr(cli, "ask", fake_ask)
    arts = semantic._build_artifacts({
        "flow_result": "live:judged-6-runs", "home_text": "h", "signup_text": "s",
        "review_text": "r", "export_json": {"cards": []}, "pages": [],
    })
    ub = next(c for c in semantic.CHARTERS if c.name == "user_brain")
    semantic._run_charter(ub, arts)
    assert "live:judged-6-runs" not in captured["user"], (
        "the user_brain judge must never see the control token (else it could quote it "
        "into a finding that then reaches the council via issues_txt)")


# --- Fix C: meta/diagnostic findings stay out of the product-fix queue ------
def test_council_blindspot_diagnostic_route_is_meta():
    bug = {"category": "council:blind_spot", "route": "diagnostic/functional",
           "title": "Response body of /review never verified"}
    assert fix_loop._is_meta_finding(bug) is True


def test_council_blindspot_with_real_route_is_not_meta():
    # A real product bug the council surfaces with a real route must STILL be fixable.
    bug = {"category": "council:blind_spot", "route": "/upload/configure",
           "title": "Real product issue at a real route"}
    assert fix_loop._is_meta_finding(bug) is False


def test_ordinary_product_finding_is_not_meta():
    bug = {"category": "semantic:functional", "route": "/review",
           "title": "Zero content cards generated"}
    assert fix_loop._is_meta_finding(bug) is False


# --- Fix D: generation-time dedup collapses reworded LLM findings -----------
def test_reworded_llm_findings_collapse_to_one_fingerprint():
    # Same defect class + same route, different LLM wording each run => one fingerprint.
    f1 = Finding(category="semantic:user_brain", severity="high",
                 title="'Ready TO FILE' status label is ambiguous jargon",
                 route="/dashboard", expected="clear label", actual="jargon")
    f2 = Finding(category="semantic:user_brain", severity="medium",
                 title="'Ready TO FILE' sounds like tax filing, not content",
                 route="/dashboard", expected="clear label", actual="confusing")
    assert f1.fingerprint() == f2.fingerprint(), "reworded same-route findings must dedupe"


def test_different_routes_stay_distinct():
    f1 = Finding(category="semantic:functional", severity="high", title="t",
                 route="/upload/configure", expected="e", actual="a")
    f2 = Finding(category="semantic:functional", severity="high", title="t",
                 route="/review", expected="e", actual="a")
    assert f1.fingerprint() != f2.fingerprint()
