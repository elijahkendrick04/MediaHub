"""The /api/runs/* JSON surface (run cards, captions, workflow, exports).

Carved out of ``web.create_app`` (deep-review finding #15, stage 4).
Handlers are byte-identical to their closure versions except that
web-module globals are reached as ``W.<name>`` (call-time resolution:
reload-safe, and ``mock.patch('mediahub.web.web.x')`` still lands) and
the captured ``app`` became ``current_app``. Endpoint names are
PRESERVED — url_for targets, ``request.endpoint`` keying and the
org/terms gate exemption sets depend on them — which is why this is
an ``add_url_rule`` module, not a name-prefixing Blueprint (see
docs/REFACTOR_WEB_BLUEPRINTS.md).
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from flask import (
    Response,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    send_file,
    url_for,
)

from mediahub.web import web as W


def api_status(run_id):
    # Tenant gate: status polling would otherwise let a foreign org
    # infer when another org's pipeline finishes.
    _run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, _run_data, W._active_profile_id()):
        return jsonify({"status": "unknown", "error": "Run not found"}), 404

    def _n_achievements_from_run(rd):
        """Extract achievement count from a loaded run dict (or 0)."""
        if not rd:
            return 0
        rr = rd.get("recognition_report") or {}
        return int(rr.get("n_achievements") or 0)

    # In-memory snapshot (the worker that spawned the pipeline). Copy
    # the log list *under the lock* — copy_value only shallow-copies the
    # dict, so jsonify could otherwise iterate the list while the worker
    # appends to it ("list changed size during iteration").
    with W._active_lock:
        entry = W._active_runs.get(run_id)
        snap = None
        if isinstance(entry, dict):
            snap = {
                "status": entry.get("status"),
                "error": entry.get("error"),
                "log": list(entry.get("log") or []),
                "started_at": entry.get("started_at"),
                "heartbeat": entry.get("heartbeat"),
            }
    if snap is not None:
        status = snap.get("status")
        if status in ("queued", "running"):
            hb = snap.get("heartbeat")
            if hb is not None and (time.time() - hb) > W._RUN_STALE_SECS:
                snap["status"] = "error"
                snap["error"] = W._STALE_ERR
        if snap.get("status") == "done":
            snap["n_achievements"] = _n_achievements_from_run(_run_data)
            snap["n_standout"] = W._n_standout_from_report(
                (_run_data or {}).get("recognition_report")
            )
        # Customer-facing percent + plain-English phase (additive; the raw
        # `log`/`error` stay for operators and documented API clients).
        _pct, _phase = W._recap_progress.recap_progress(snap.get("log"), snap.get("status"))
        snap["percent"], snap["phase"] = _pct, _phase
        return jsonify(snap)

    # Fallback to persisted status — this is the path every poll takes
    # when it lands on the *other* gunicorn worker, so it must return the
    # streamed progress log (not an empty one) and honour staleness.
    conn = W._db()
    row = conn.execute(
        "SELECT status, error, progress_log, heartbeat_at FROM runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"status": "unknown", "error": "Run not found"}), 404
    status = row["status"]
    error = row["error"]
    try:
        plog = json.loads(row["progress_log"]) if row["progress_log"] else []
    except (ValueError, TypeError):
        plog = []
    if status in ("queued", "running"):
        age = W._iso_age_secs(row["heartbeat_at"])
        if age is None or age > W._RUN_STALE_SECS:
            # QA-015: this is the path a real worker recycle takes — the
            # worker that ran the pipeline is gone, so its in-memory entry
            # is too and the poll falls through to here. A dead run whose
            # launch input is still on disk is RESUMED (re-run) rather than
            # lost; only a genuinely unrecoverable one (no stored input, or
            # the resume budget is spent) surfaces the honest error.
            if W._maybe_resume_stale_run(run_id):
                status = "running"
            else:
                status = "error"
                error = error or W._STALE_ERR
    payload = {"status": status, "error": error, "log": plog}
    if status == "done":
        payload["n_achievements"] = _n_achievements_from_run(_run_data)
        payload["n_standout"] = W._n_standout_from_report(
            (_run_data or {}).get("recognition_report")
        )
    _pct, _phase = W._recap_progress.recap_progress(plog, status)
    payload["percent"], payload["phase"] = _pct, _phase
    return jsonify(payload)


def api_why_card(run_id, ach_index):
    """Build one card's "Why this card?" reasoning on demand.

    The review page renders these lazily (placeholder + this fetch) so
    the LLM-backed explanation for a 150+ card meet no longer blocks the
    whole page render. ``ach_index`` is the position in the persisted
    ``ranked_achievements`` list, which is stable for a finished run.
    """
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()) or not data:
        return ("Run not found", 404)
    rr = data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    if ach_index < 0 or ach_index >= len(ranked):
        return ("", 404)
    ra = ranked[ach_index]
    meet_ctx = rr.get("meet_context") or {}
    cuid = W._why_card_cuid(request.args.get("cuid") or f"idx-{ach_index}")
    try:
        exp = W._build_card_explanation(ra, meet_ctx)
    except Exception as e:
        exp = {
            "headline": "AI explanation unavailable.",
            "bullets": [],
            "source_lines": W._build_source_lines_from_evidence(ra.get("achievement") or {}),
            "ai_error": str(e),
        }
    html = W._render_why_inner(exp, ra=ra, run_id=run_id, card_uuid=cuid)
    return current_app.response_class(html, mimetype="text/html")


def api_recognition(run_id):
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "not found"}), 404
    if not data:
        return jsonify({"error": "not found"}), 404
    rr = data.get("recognition_report")
    if rr is None:
        return jsonify(
            {
                "error": "no recognition report",
                "recognition_error": data.get("recognition_error"),
            }
        ), 404
    return jsonify(rr)


def api_swim_trace(run_id, swim_id):
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "not found"}), 404
    if not data:
        return jsonify({"error": "not found"}), 404
    rr = data.get("recognition_report") or {}
    traces = rr.get("swim_traces") or []
    # swim_id may have special chars; do substring match
    import urllib.parse as _urlparse

    swim_id_dec = _urlparse.unquote(swim_id)
    for t in traces:
        if t.get("swim_id") == swim_id_dec:
            return jsonify(t)
    # fallback: partial match
    for t in traces:
        if swim_id_dec in (t.get("swim_id") or ""):
            return jsonify(t)
    return jsonify({"error": "trace not found", "swim_id": swim_id_dec}), 404


def api_live_caption(run_id, swim_id):
    """
    V8 Live Caption endpoint.

    POST /api/runs/<run_id>/swim/<swim_id>/caption?tone=<voice_id|ai>

    Returns JSON: {caption: str, tone: str, generated_at: iso,
                   fallback: bool, fallback_voice: str|None}

    - tone=ai  : generates LIVE via Claude Sonnet (no caching).
    - tone=<id>: renders via voice.learned.render_caption().

    Graceful degradation: if LLM unavailable, ai tone returns a
    randomly-picked voice render with fallback=True.
    """
    import urllib.parse as _up
    from datetime import datetime, timezone as _tz

    tone = request.args.get("tone", "ai").strip()
    swim_id_dec = _up.unquote(swim_id)

    # Load run data
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404
    if not data:
        return jsonify({"error": "run not found"}), 404

    rr = data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []

    # Find the achievement for this swim_id
    achievement = {}
    matched_ra = None
    for ra in ranked:
        a = ra.get("achievement") or {}
        if a.get("swim_id") == swim_id_dec:
            achievement = a
            matched_ra = ra
            break
    # Fallback: partial match
    if not achievement:
        for ra in ranked:
            a = ra.get("achievement") or {}
            if swim_id_dec in (a.get("swim_id") or ""):
                achievement = a
                matched_ra = ra
                break

    # Build achievement dict suitable for caption generation
    ach_dict = {
        "swimmer_first": achievement.get("swimmer_name", "").split()[0]
        if achievement.get("swimmer_name")
        else "",
        "swimmer_last": " ".join(achievement.get("swimmer_name", "").split()[1:])
        if achievement.get("swimmer_name")
        else "",
        "swimmer_name": achievement.get("swimmer_name", ""),
        "event": achievement.get("event", ""),
        "time": achievement.get("time", ""),
        "pb": achievement.get("pb", False),
        "club": data.get("profile_display", ""),
        "meet": (data.get("meet") or {}).get("name", ""),
        "place": achievement.get("place", ""),
        "type": achievement.get("type", ""),
        "headline": achievement.get("headline", ""),
    }

    # Phase 1.4 — "use why-this-card in the caption". When the user
    # clicks the button on the explainer panel, we re-prompt the
    # caption LLM with the explanation's headline + bullets as
    # required content. This lets the visible-intelligence layer
    # flow back into the generated caption with one click — the
    # AI-grounded reasoning literally informs the wording.
    #
    # Important: we only inject when the explainer returned a real
    # grounded headline. The explainer has two known fallback
    # shapes ("AI explanation unavailable..." when the perf-context
    # LLM is down, and "Generated for: ranked top-N..." when no
    # significant factors exist) — passing those through as
    # requirements would tell the caption LLM to include literal
    # error text in the post, which is worse than skipping the
    # feature.
    if request.args.get("include_why") == "1":
        try:
            _why = W._build_card_explanation(matched_ra or {"achievement": achievement})
            _why_headline = (_why.get("headline") or "").strip()
            _why_bullets = _why.get("bullets") or []
            _why_bullets_text = (
                "; ".join(b for b in _why_bullets if b) if isinstance(_why_bullets, list) else ""
            )
            _is_fallback_headline = (
                "unavailable" in _why_headline.lower() or _why_headline.startswith("Generated for:")
            )
            if _is_fallback_headline and not _why_bullets_text:
                # Nothing usable to inject — skip silently rather
                # than pollute the prompt.
                pass
            elif _why_headline or _why_bullets_text:
                requirement_parts = []
                if _why_headline and not _is_fallback_headline:
                    requirement_parts.append(_why_headline)
                if _why_bullets_text:
                    requirement_parts.append(
                        "Weave in at least one of these grounded "
                        "reasons: " + _why_bullets_text + "."
                    )
                if requirement_parts:
                    ach_dict["_extra_instructions"] = " ".join(requirement_parts)
        except Exception:
            # Never block caption generation on a why-build hiccup.
            pass

    # Club brand hints
    club_brand = {
        "club_name": data.get("profile_display", ""),
        "meet_name": (data.get("meet") or {}).get("name", ""),
    }

    # Load voice profile from the club profile (best-effort; None is fine)
    _run_voice_profile: Optional[dict] = None
    try:
        _run_profile_id = data.get("profile_id") or ""
        if _run_profile_id:
            _club_prof = W.load_profile(_run_profile_id)
            if _club_prof and _club_prof.voice_profile:
                _run_voice_profile = _club_prof.voice_profile
    except Exception:
        pass
    # Resolve the ClubProfile so voice_profile (brand DNA voice layer)
    # can flow into the caption prompt. Profiles with no voice_profile
    # still work &mdash; generate_caption_for_tone treats it as a no-op.
    club_profile_obj = None
    run_profile_id = data.get("profile_id") or ""
    if run_profile_id:
        try:
            club_profile_obj = W.load_profile(run_profile_id)
        except Exception:
            club_profile_obj = None

    now_iso = datetime.now(_tz.utc).isoformat()

    # V9: build the plain-English explanation once per request so every
    # response (live, fallback, error) carries it.
    explanation = W._build_card_explanation(matched_ra or {"achievement": achievement})

    from mediahub.media_ai.llm import is_available as _llm_available

    # Caption writer: the shared ai_caption.generate_caption_for_tone
    # primitive (the very writer content_engine.generate_caption delegates
    # to). Called directly so Cap-2b semantic recall can pass
    # few_shot_examples through without widening the content_engine API.
    from mediahub.web.ai_caption import (
        KNOWN_AI_TONES as _AI_TONES,
        ClaudeUnavailableError as _ClaudeUE,  # type: ignore[attr-defined]
        generate_caption_for_tone as _gen_tone,
    )

    if tone in _AI_TONES:
        # LIVE generation &mdash; fresh every call, nonce injected for uniqueness.
        # Works with Gemini (free) or Anthropic API key.
        if not _llm_available():
            return jsonify(
                {
                    "caption": "",
                    "tone": tone,
                    "live": False,
                    "generated_at": now_iso,
                    "error": "no_key",
                    "message": (
                        "AI captions are unavailable on this deployment. "
                        "Contact your administrator to enable them."
                    ),
                    "explanation": explanation,
                }
            ), 200
        # Governance (1.23): role permission + per-org caption quota.
        # Permission gates WHO may generate (editor+ on a bound org; pilot
        # orgs and the operator keep the owner seat, so their flow is
        # unchanged). Quota gates HOW MUCH, hard-blocking only where a
        # specific caption limit is configured. The plan comes from the
        # acting user. Usage is recorded once in the finally below.
        #
        # The signed-in developer/operator is fully exempt: blanking the
        # governance org skips the permission gate, the quota enforce, AND
        # the metering record below — so the operator is never blocked and
        # their test generations never count against the club they are
        # working on. (The global llm_usage ledger still tracks real cost.)
        from mediahub.governance import (
            features as _gov_features,
            permissions as _gov_perms,
            quota as _gov_quota,
        )

        _gov_org = "" if W._auth.is_dev_operator() else (run_profile_id or "")
        _gov_ok = False
        _gov_plan = W._auth.current_plan()
        if _gov_org and not _gov_perms.can_use_feature(
            W._active_role(_gov_org), _gov_features.FEATURE_CAPTION, plan=_gov_plan
        ):
            return jsonify(
                {
                    "caption": "",
                    "tone": tone,
                    "live": False,
                    "generated_at": now_iso,
                    "error": "forbidden",
                    "message": _gov_perms.denial_reason(
                        W._active_role(_gov_org),
                        _gov_features.FEATURE_CAPTION,
                        plan=_gov_plan,
                    ),
                    "explanation": explanation,
                }
            ), 403
        if _gov_org:
            try:
                _gov_quota.enforce(_gov_org, _gov_features.FEATURE_CAPTION, plan=_gov_plan)
            except _gov_quota.QuotaExceeded as _qe:
                return jsonify(
                    {
                        "caption": "",
                        "tone": tone,
                        "live": False,
                        "generated_at": now_iso,
                        "error": "quota_reached",
                        "message": str(_qe),
                        "explanation": explanation,
                    }
                ), 200
        try:
            # Generate 3 variants in parallel so the user can pick one
            # (Holo/Blaze pattern). The first is returned as `caption`
            # for backwards-compat with existing consumers; the full list
            # lives in `variants`.
            #
            # Phase 1.5 rate-limit fix: default n_variants dropped
            # from 3 → 1. Three parallel Gemini calls per click
            # blew through the free-tier 15 RPM after just a few
            # regenerates, and pool.map propagated the FIRST 429 as
            # a request-level failure even if 2 of 3 succeeded —
            # the user saw "AI captions are unavailable" after one
            # click. Each variant is now generated sequentially
            # with individual error capture so one failure doesn't
            # poison the others.
            from concurrent.futures import ThreadPoolExecutor

            # Defend against ``?n_variants=abc`` — a bare int()
            # would 500 the whole caption endpoint. Anything that
            # doesn't parse as a positive integer falls back to 1.
            try:
                n_variants = int(request.args.get("n_variants") or 1)
            except (TypeError, ValueError):
                n_variants = 1
            n_variants = max(1, min(n_variants, 4))

            # V9: feed the AI the last few captions for this swim so
            # it actively writes something different on each regenerate.
            _recent_captions = W._v9_load_caption_history(run_id, swim_id_dec)

            # Cap 2b: semantic recall — captions that worked for similar
            # past moments for this club, injected as few-shot voice
            # examples so generation is conditioned on the club's own proven
            # voice. Off-by-default ([] unless an embedding backend is
            # configured and the club's corpus passes the cold-start floor);
            # best-effort, never breaks caption generation.
            try:
                from mediahub.memory import learning as _mem

                _mem_examples = _mem.recall(run_profile_id, ach_dict)
            except Exception:
                _mem_examples = []

            # PAR-1 few-shot voice store: the most recent captions a human
            # actually approved for this club (populated by the content-pack
            # approval seam). Unlike semantic recall it needs no embedding
            # backend and no corpus floor, so the approve → learn-the-voice
            # loop works for every club from the first approval. Semantic
            # hits lead (they are moment-matched), recents fill the rest;
            # deduped, capped at 5 (the injection cap in ai_caption).
            try:
                from mediahub.web.caption_examples import (
                    load_examples as _load_caption_examples,
                )

                _approved_examples = (
                    _load_caption_examples(run_profile_id) if run_profile_id else []
                )
            except Exception:
                _approved_examples = []
            _few_shot_examples: list[str] = []
            for _ex in list(_mem_examples) + list(_approved_examples):
                _ex = (_ex or "").strip()
                if _ex and _ex not in _few_shot_examples:
                    _few_shot_examples.append(_ex)
            _few_shot_examples = _few_shot_examples[:5]

            def _gen_one():
                try:
                    return _gen_tone(
                        ach_dict,
                        club_brand,
                        tone=tone,
                        voice_profile=_run_voice_profile,
                        club_profile=club_profile_obj,
                        recent_captions=_recent_captions,
                        few_shot_examples=_few_shot_examples,
                    )
                except _ClaudeUE:
                    # Terminal-shaped errors must propagate so the
                    # outer except can distinguish "no key" from
                    # "transient" and steer the user appropriately.
                    raise
                except Exception:
                    # Per-variant failures (network blips, parse
                    # errors mid-stream) must NOT poison sibling
                    # variants — return None and filter.
                    return None

            # W.11/W.13: the PRIMARY variant rides the bundle call so the
            # result-grounded alt text (and the side-by-side translation
            # for bilingual workspaces) arrive in the SAME provider call —
            # zero added latency. Extra variants stay caption-only.
            from mediahub.web.ai_caption import (
                generate_caption_bundle as _gen_bundle,
            )
            from mediahub.web.languages import (
                get_language as _get_language,
                language_setting_for as _language_setting_for,
            )

            _pw_language = _language_setting_for(club_profile_obj)
            alt_text = ""
            caption_secondary = None
            secondary_language = None

            def _gen_primary():
                try:
                    return _gen_bundle(
                        ach_dict,
                        club_brand,
                        tone=tone,
                        voice_profile=_run_voice_profile,
                        club_profile=club_profile_obj,
                        recent_captions=_recent_captions,
                        few_shot_examples=_few_shot_examples,
                        language=_pw_language,
                    )
                except Exception:
                    # Strictly best-effort: ANY bundle failure (malformed
                    # JSON, provider blip, no key) falls through to the
                    # caption-only path below, whose error classification
                    # (terminal vs transient) is the canonical one. The
                    # caption is never lost just because alt text was.
                    return None

            _bundle = _gen_primary()
            if _bundle:
                alt_text = _bundle.get("alt_text") or ""
                caption_secondary = _bundle.get("caption_secondary")
                secondary_language = _bundle.get("secondary_language")
                variants = [_bundle.get("caption") or ""]
                extra_needed = max(0, n_variants - 1)
            else:
                variants = []
                extra_needed = n_variants
            if extra_needed == 1:
                variants.append(_gen_one())
            elif extra_needed > 1:
                with ThreadPoolExecutor(max_workers=extra_needed) as pool:
                    variants.extend(pool.map(lambda _: _gen_one(), range(extra_needed)))
            # Drop None placeholders from failed variants.
            variants = [v for v in variants if v]
            # Collapse exact + trigram near-duplicates (Gemini occasionally
            # returns the same or near-same caption twice on short prompts)
            # and drop AI-tell candidates, against the club's recent captions
            # and the kept variants — the shared quality gate from
            # generate_caption_candidates. Fail-open: never empties a
            # non-empty list (a slightly stale caption beats none).
            from mediahub.web.ai_caption import (
                filter_caption_variants as _filter_variants,
            )

            # Passing ach_dict activates the source-fact grounding check
            # (recipe #232): a variant that names no swimmer/event/time
            # from this swim is generic filler and drops in favour of a
            # grounded sibling. Fail-open, so the single-variant default
            # path is never left empty.
            variants = _filter_variants(
                variants, recent_captions=_recent_captions, achievement=ach_dict
            )

            caption_text = variants[0] if variants else ""
            # If every variant failed (e.g. provider rate-limited),
            # distinguish that from "no key configured". The former
            # is transient — the user should be told to retry, not
            # told the deployment doesn't have AI.
            if not caption_text:
                return jsonify(
                    {
                        "caption": "",
                        "tone": tone,
                        "live": True,
                        "generated_at": now_iso,
                        "error": "transient",
                        "message": (
                            "The AI is briefly busy or rate-limited. "
                            "Wait a few seconds and click regenerate "
                            "again — your key is fine."
                        ),
                        "explanation": explanation,
                    }
                ), 200
            # Persist the new caption(s) so the next regenerate can
            # ask the AI to differ. We store ALL produced variants
            # to widen the "avoid" window in one go.
            for v in variants:
                W._v9_save_caption_history(run_id, swim_id_dec, v)
            _sec_lang = _get_language(secondary_language) if secondary_language else None
            # W.13 persistence: the auto side-by-side translation a bilingual
            # workspace gets from the bundle was only ever rendered in review
            # — unlike /translate it was never saved on the card, so the
            # approved pair was dropped at export. Persist it the same way
            # /translate does (a language-keyed variant with a `slots.caption`)
            # so approving the card approves the pair and it rides into
            # exports. Best-effort; never blocks or fails the caption.
            if caption_secondary and secondary_language:
                _ws_tr = W._get_wf_store()
                if _ws_tr is not None:
                    try:
                        _ws_tr.set_translation(
                            run_id,
                            swim_id_dec,
                            secondary_language,
                            {
                                "language": secondary_language,
                                "language_label": (_sec_lang.native_name if _sec_lang else ""),
                                "rtl": bool(_sec_lang and _sec_lang.rtl),
                                "slots": {"caption": caption_secondary},
                                "provider": "caption_bundle",
                            },
                        )
                    except Exception:
                        pass
            _gov_ok = True  # one real caption produced — counts toward quota
            return jsonify(
                {
                    "caption": caption_text,
                    "variants": variants,
                    "n_variants": len(variants),
                    "tone": tone,
                    "live": True,
                    "generated_at": now_iso,
                    "fallback": False,
                    "fallback_voice": None,
                    "explanation": explanation,
                    # W.11: result-grounded alt text from the same call,
                    # editable in review and threaded into exports.
                    "alt_text": alt_text,
                    # W.13 (generalised): side-by-side translation for
                    # bilingual workspaces, plus the display metadata
                    # (native-name label, text direction) the review UI
                    # needs to render it for ANY registry language.
                    "caption_secondary": caption_secondary,
                    "secondary_language": secondary_language,
                    "secondary_language_label": (_sec_lang.native_name if _sec_lang else ""),
                    "secondary_rtl": bool(_sec_lang and _sec_lang.rtl),
                    "language": _pw_language,
                }
            )
        except _ClaudeUE as e:
            # Distinguish "no key" from "transient error". The
            # ClaudeUnavailableError message is checked for hints:
            # provider configuration issues say "unavailable on this
            # deployment"; transient errors carry rate-limit / HTTP
            # status info. Default conservatively to transient so
            # the user doesn't lose hope after a single 429.
            msg = str(e).lower()
            terminal = (
                "not configured" in msg
                or "unavailable on this deployment" in msg
                or "no provider" in msg
            )
            if terminal:
                return jsonify(
                    {
                        "caption": "",
                        "tone": tone,
                        "live": False,
                        "generated_at": now_iso,
                        "error": "no_key",
                        "message": (
                            "AI captions are unavailable on this deployment. "
                            "Contact your administrator to enable them."
                        ),
                        "explanation": explanation,
                    }
                ), 200
            return jsonify(
                {
                    "caption": "",
                    "tone": tone,
                    "live": True,
                    "generated_at": now_iso,
                    "error": "transient",
                    "message": (
                        "The AI provider returned a transient error. "
                        "Wait a few seconds and try again."
                    ),
                    "explanation": explanation,
                }
            ), 200
        finally:
            # Record exactly one caption-feature use for this request —
            # success counts toward quota, a failed attempt is logged but
            # not charged. Best-effort; never affects the response.
            if _gov_org:
                _gov_quota.record(
                    _gov_org,
                    _gov_features.FEATURE_CAPTION,
                    ok=_gov_ok,
                    detail=f"tone={tone}",
                )
    else:
        # Voice render &mdash; deterministic template, may be cached by client
        try:
            from mediahub.voice.learned.store import list_voices as _lv, load_voice as _load_v
            from mediahub.voice.learned.render import render_caption as _rc
        except ImportError:
            return jsonify({"error": "voice rendering unavailable"}), 503

        profile = None
        try:
            profile = _load_v(tone)
        except FileNotFoundError:
            pass

        if profile is None:
            voices = _lv(include_seed=True)
            for v in voices:
                if v.voice_id == tone:
                    profile = v
                    break

        if profile is None:
            return jsonify({"error": f"voice not found: {tone}"}), 404

        captions = _rc(ach_dict, profile, n_variants=1)
        caption_text = captions[0] if captions else ""
        return jsonify(
            {
                "caption": caption_text,
                "tone": tone,
                "generated_at": now_iso,
                "fallback": False,
                "fallback_voice": None,
                "explanation": explanation,
            }
        )


def api_caption_assist(run_id, swim_id):
    """Inline caption assist: REVISE an existing caption (shorter / punchier /
    add the time / tidy / custom) via the existing writer's `requirements`
    channel. Never invents facts — it only nudges wording. Mirrors
    api_live_caption's access + achievement lookup."""
    import urllib.parse as _up
    from datetime import datetime
    from datetime import timezone as _tz

    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()) or not data:
        return jsonify({"error": "run not found"}), 404

    payload = request.get_json(silent=True) or {}
    # Server-side length caps: the 140-char maxlength is client-only, so an
    # oversized body would otherwise be embedded verbatim in the provider
    # prompt (token cost, provider 400s). Real captions are ~280 chars.
    current_caption = (payload.get("current_caption") or "").strip()[:4000]
    transform = (payload.get("transform") or "").strip()
    custom = (payload.get("custom") or "").strip()[:500]
    tone = (payload.get("tone") or "warm-club").strip()
    if tone not in ("ai", "warm-club", "hype", "data-led"):
        tone = "warm-club"
    if not current_caption:
        return jsonify(
            {"error": "empty_caption", "message": "Generate a caption first, then assist it."}
        ), 400

    from mediahub.web.caption_assist import assist_caption, resolve_instruction

    if not resolve_instruction(transform, custom):
        return jsonify(
            {"error": "invalid_transform", "message": "Pick a change or type an instruction."}
        ), 400

    swim_id_dec = _up.unquote(swim_id)
    ranked = (data.get("recognition_report") or {}).get("ranked_achievements") or []
    achievement: dict = {}
    for ra in ranked:
        a = ra.get("achievement") or {}
        if a.get("swim_id") == swim_id_dec or (
            swim_id_dec and swim_id_dec in (a.get("swim_id") or "")
        ):
            achievement = a
            break
    ach_dict = {
        "swimmer_name": achievement.get("swimmer_name", ""),
        "event": achievement.get("event", ""),
        "time": achievement.get("time", ""),
        "pb": achievement.get("pb", False),
        "club": data.get("profile_display", ""),
        "meet": (data.get("meet") or {}).get("name", ""),
        "place": achievement.get("place", ""),
        "type": achievement.get("type", ""),
        "headline": achievement.get("headline", ""),
    }
    club_brand = {
        "club_name": data.get("profile_display", ""),
        "meet_name": (data.get("meet") or {}).get("name", ""),
    }
    club_profile_obj = None
    voice_profile = None
    run_profile_id = data.get("profile_id") or ""
    if run_profile_id:
        try:
            club_profile_obj = W.load_profile(run_profile_id)
            if club_profile_obj and club_profile_obj.voice_profile:
                voice_profile = club_profile_obj.voice_profile
        except Exception:
            club_profile_obj = None

    now_iso = datetime.now(_tz.utc).isoformat()
    from mediahub.media_ai.llm import is_available as _llm_available
    from mediahub.web.ai_caption import ClaudeUnavailableError as _ClaudeUE

    if not _llm_available():
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": (
                    "AI captions are unavailable on this deployment. "
                    "Contact your administrator to enable them."
                ),
            }
        ), 200
    try:
        revised = assist_caption(
            ach_dict,
            current_caption,
            transform,
            custom=custom,
            club_brand=club_brand,
            club_profile=club_profile_obj,
            tone=tone,
            voice_profile=voice_profile,
        )
    except _ClaudeUE:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": "AI captions are unavailable on this deployment.",
            }
        ), 200
    except Exception:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI is briefly busy — wait a few seconds and try again.",
            }
        ), 200
    revised = (revised or "").strip()
    if not revised:
        return jsonify(
            {
                "caption": "",
                "tone": tone,
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI returned nothing — try again.",
            }
        ), 200
    return jsonify(
        {
            "caption": revised,
            "original": current_caption,
            "tone": tone,
            "transform": transform or "custom",
            "live": True,
            "generated_at": now_iso,
        }
    )


def api_caption_platforms(run_id, swim_id):
    """Adapt one caption into per-platform variants (feed / story / X /
    LinkedIn) via ai_caption.generate_platform_variants.

    Mirrors api_caption_assist's access + honest-no-key handling: it never
    invents facts — it re-shapes the caption the reviewer already has for
    each platform's length + register. The club's brand voice and approved
    few-shot examples flow through so the adaptations stay on-voice.
    """
    from datetime import datetime
    from datetime import timezone as _tz

    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()) or not data:
        return jsonify({"error": "run not found"}), 404

    payload = request.get_json(silent=True) or {}
    # Server-side length cap: the client caption is ~280 chars; anything
    # much larger is truncated before it reaches the provider prompt.
    base_caption = (payload.get("caption") or "").strip()[:4000]
    if not base_caption:
        return jsonify(
            {
                "error": "empty_caption",
                "message": "Generate or write a caption first, then adapt it.",
            }
        ), 400
    req_platforms = payload.get("platforms")
    platforms = None
    if isinstance(req_platforms, list):
        platforms = [str(p).strip() for p in req_platforms if str(p).strip()]

    now_iso = datetime.now(_tz.utc).isoformat()
    from mediahub.media_ai.llm import is_available as _llm_available
    from mediahub.web.ai_caption import (
        ClaudeUnavailableError as _ClaudeUE,
        generate_platform_variants as _gen_platforms,
    )

    if not _llm_available():
        return jsonify(
            {
                "variants": {},
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": "AI captions are unavailable on this deployment.",
            }
        ), 200

    club_profile_obj = None
    run_profile_id = data.get("profile_id") or ""
    if run_profile_id:
        try:
            club_profile_obj = W.load_profile(run_profile_id)
        except Exception:
            club_profile_obj = None
    club_brand = {
        "club_name": data.get("profile_display", ""),
        "meet_name": (data.get("meet") or {}).get("name", ""),
    }
    # Approved-caption few-shot voice so the adaptations stay on-voice.
    try:
        from mediahub.web.caption_examples import load_examples as _load_caption_examples

        _few_shot = _load_caption_examples(run_profile_id) if run_profile_id else []
    except Exception:
        _few_shot = []

    try:
        variants = _gen_platforms(
            base_caption,
            club_brand=club_brand,
            club_profile=club_profile_obj,
            platforms=platforms,
            few_shot_examples=_few_shot,
        )
    except _ClaudeUE:
        return jsonify(
            {
                "variants": {},
                "live": False,
                "generated_at": now_iso,
                "error": "no_key",
                "message": "AI captions are unavailable on this deployment.",
            }
        ), 200
    except Exception:
        return jsonify(
            {
                "variants": {},
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI is briefly busy — wait a few seconds and try again.",
            }
        ), 200

    variants = {
        k: v.strip() for k, v in (variants or {}).items() if isinstance(v, str) and v.strip()
    }
    if not variants:
        return jsonify(
            {
                "variants": {},
                "live": True,
                "generated_at": now_iso,
                "error": "transient",
                "message": "The AI returned nothing — wait a few seconds and try again.",
            }
        ), 200
    return jsonify({"variants": variants, "live": True, "generated_at": now_iso})


def api_card_translate(run_id, card_id):
    """1.24 localisation — translate a card's text into a target language.

    POST body: {lang: "cy"|"en-US"|…, caption: str, alt_text?: str,
                headline?: str, subhead?: str}

    Translates exactly the text the approver is looking at (passed in the
    body) through the glossary-constrained engine, persists it on the card as
    a language variant (so the bilingual pair rides into approval/export),
    and returns it for side-by-side display. Honest-errors (200 + an
    {"error": "no_key"} body, like the caption/assist routes) when no
    provider is configured — never a fake translation.
    """
    import urllib.parse as _up

    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()) or not data:
        return jsonify({"error": "run not found"}), 404
    # Translating produces content for review — an edit-class action.
    denied = W._role_denied_json(W._perms.CAP_EDIT, run_id)
    if denied:
        return denied

    payload = request.get_json(silent=True) or {}
    target = (payload.get("lang") or payload.get("language") or "").strip()
    if not target:
        return jsonify(
            {"error": "no_language", "message": "Pick a language to translate into."}
        ), 400

    from mediahub.localize import base_code as _base_code
    from mediahub.web.languages import get_language as _get_language

    if _get_language(_base_code(target)) is None:
        return jsonify({"error": "bad_language", "message": "That language isn't supported."}), 400

    # Translate exactly the slots the approver sees (sent in the body).
    slots: dict[str, str] = {}
    for key in ("caption", "alt_text", "headline", "subhead"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            slots[key] = val
    if not slots:
        return jsonify(
            {"error": "empty", "message": "Generate a caption first, then translate it."}
        ), 400

    # Source language = the workspace's primary caption language.
    source_language = "en"
    run_profile_id = data.get("profile_id") or ""
    if run_profile_id:
        try:
            from mediahub.web.languages import primary_language_for as _primary

            prof = W.load_profile(run_profile_id)
            if prof:
                source_language = _primary(prof) or "en"
        except Exception:
            source_language = "en"

    # 1.23 governance: translation is metered AI spend, like captions — gate
    # on the org's feature permission + plan, enforce the quota before the
    # provider call, and record one use after (below). The signed-in
    # operator is fully exempt (org blanked → no gate, no quota, no metering),
    # so their test translations never count against the club.
    from mediahub.governance import (
        features as _gov_features,
        permissions as _gov_perms,
        quota as _gov_quota,
    )

    _gov_org = "" if W._auth.is_dev_operator() else (run_profile_id or "")
    _gov_plan = W._auth.current_plan()
    if _gov_org and not _gov_perms.can_use_feature(
        W._active_role(_gov_org), _gov_features.FEATURE_TRANSLATE, plan=_gov_plan
    ):
        return jsonify(
            {
                "error": "forbidden",
                "message": _gov_perms.denial_reason(
                    W._active_role(_gov_org), _gov_features.FEATURE_TRANSLATE, plan=_gov_plan
                ),
            }
        ), 403
    if _gov_org:
        try:
            _gov_quota.enforce(_gov_org, _gov_features.FEATURE_TRANSLATE, plan=_gov_plan)
        except _gov_quota.QuotaExceeded as _qe:
            return jsonify({"error": "quota_reached", "message": str(_qe)}), 200

    from mediahub.media_ai.llm import is_available as _llm_available

    if not _llm_available():
        # Honest "no provider" — 200 + an error body, matching the sibling
        # caption/assist routes (and the route's own transient path); the
        # review UI branches on the `error` field, not the status code.
        return jsonify(
            {
                "error": "no_key",
                "message": (
                    "AI translation is unavailable on this deployment. "
                    "Contact your administrator to enable it."
                ),
            }
        ), 200

    from mediahub.web.translate_card import (
        ClaudeUnavailableError as _CUE,
        translate_card_slots,
    )

    try:
        variant = translate_card_slots(slots, target, source_language=source_language)
    except _CUE:
        return jsonify(
            {
                "error": "no_key",
                "message": "AI translation is unavailable on this deployment.",
            }
        ), 200
    except Exception:
        return jsonify(
            {
                "error": "transient",
                "message": "The AI is briefly busy — wait a few seconds and try again.",
            }
        ), 200

    # One real translation produced — count it toward the org's quota
    # (operator exempt). Best-effort; never affects the response.
    if _gov_org:
        _gov_quota.record(
            _gov_org, _gov_features.FEATURE_TRANSLATE, ok=True, detail=f"lang={target}"
        )

    # Persist on the card so approving the card approves the pair.
    card_id_dec = _up.unquote(card_id)
    ws = W._get_wf_store()
    if ws is not None:
        try:
            ws.set_translation(run_id, card_id_dec, variant.get("language") or target, variant)
        except Exception:
            pass
    return jsonify({"ok": True, **variant})


def api_cards(run_id):
    # Tenant gate BEFORE the in_progress short-circuit — otherwise a foreign
    # org polling another org's run_id learns it exists and when it finishes.
    # _run_owner_id falls back to the runs DB row, so ownership resolves even
    # mid-pipeline before the JSON is written (same basis api_status relies on).
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "not found"}), 404
    if W._run_state(run_id) == "in_progress":
        return jsonify({"error": "in_progress", "retry_after": 4}), 202
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data.get("cards", []))


def api_trust(run_id):
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "not found"}), 404
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data.get("trust", {}))


def api_export(run_id):
    # Tenant gate BEFORE the in_progress short-circuit (see api_cards) so a
    # foreign org can't use the 202 to learn a run exists / when it finishes.
    data = W._load_run(run_id)
    if not W._can_access_run(run_id, data, W._active_profile_id()):
        return jsonify({"error": "not found"}), 404
    if W._run_state(run_id) == "in_progress":
        return jsonify({"error": "in_progress", "retry_after": 4}), 202
    if not data:
        return jsonify({"error": "not found"}), 404
    return jsonify(data)


def api_card_download(run_id, card_id):
    """Download a card's caption + visual as a ZIP for manual posting.

    Clubs grab a ZIP containing the caption text and the generated
    visual, then post manually to whatever platform they like. This is
    the always-safe option — no third-party API touched, no TOS to
    violate.
    """
    from flask import send_file
    import zipfile

    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if run_data is None:
        return jsonify({"error": "run_not_found"}), 404

    assets = W._card_export_assets(
        run_id, card_id, run_data, caption_override=request.args.get("caption") or ""
    )
    if assets is None:
        return jsonify({"error": "card_not_found"}), 404
    slug, caption, png_bytes, png_name = assets

    # Build the ZIP in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{slug}-caption.txt", caption)
        if png_bytes:
            zf.writestr(png_name or f"{slug}.png", png_bytes)
        zf.writestr(
            "README.txt",
            (
                "MediaHub card export.\n\n"
                "- The .txt file contains the ready-to-post caption.\n"
                "- The .png (if present) is the branded visual; if not,\n"
                "  open the card in the content builder and click 'Create\n"
                "  graphic' first.\n\n"
                "Post the visual + caption to your chosen platform\n"
                "manually. No third-party scheduler required.\n"
            ),
        )
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{slug}.zip",
    )


def api_card_brand_check(run_id, card_id):
    from mediahub.brand.check import check_brief

    ctx, err = W._brand_check_context(run_id, card_id)
    if err is not None:
        return err
    brief, kit, brand_kit, _prof = ctx
    report = check_brief(brief, kit, brand_kit=brand_kit)
    return jsonify(report.to_dict())


def api_card_brand_advise(run_id, card_id):
    from mediahub.brand.check import advise, check_brief

    ctx, err = W._brand_check_context(run_id, card_id)
    if err is not None:
        return err
    brief, kit, brand_kit, _prof = ctx
    report = check_brief(brief, kit, brand_kit=brand_kit)
    res = advise(report, brief, kit, brand_kit=brand_kit)
    return jsonify(res.to_dict())


def api_card_brand_autofix(run_id, card_id):
    from mediahub.brand.check import autofix

    ctx, err = W._brand_check_context(run_id, card_id)
    if err is not None:
        return err
    brief, kit, brand_kit, _prof = ctx
    res = autofix(brief, kit, brand_kit=brand_kit)
    return jsonify(res.to_dict())


def api_promote_swim(run_id):
    """Promote a swim the automation didn't flag into a custom highlight.

    Human judgement path for the all-swims list: synthesises a
    ``custom_highlight`` Achievement + RankedAchievement (append-only —
    the "Why this card?" explainer addresses cards by list index, so the
    existing order is never disturbed) from the swim's own traced facts,
    applies the tenant's child-display policy, and persists atomically
    under the same cross-process lock discipline the workflow sidecar
    uses. The new card lands in the review QUEUE — it flows through the
    normal approve → Content builder path with every gate (consent,
    brand-lock, tasks) intact; promotion never publishes anything.
    """
    from mediahub._atomic_io import cross_process_lock

    _pid = W._active_profile_id()
    if not W._can_access_run(run_id, W._load_run(run_id), _pid):
        return jsonify({"error": "run not found"}), 404
    # Creating a card is content creation (same seat as caption edits).
    denied = W._role_denied_json(W._perms.CAP_EDIT, run_id)
    if denied:
        return denied

    src = request.get_json(silent=True) if request.is_json else request.form
    src = src or {}
    swim_id = str(src.get("swim_id") or "").strip()
    headline_in = str(src.get("headline") or "").strip()[:140]
    note_in = str(src.get("note") or "").strip()[:200]
    if not swim_id:
        return jsonify({"error": "swim_id required"}), 400

    wants_json = request.is_json or (request.accept_mimetypes.best == "application/json")

    def _fail(code: int, msg: str):
        if wants_json:
            return jsonify({"error": msg}), code
        return (
            f'<p>{W._h(msg)}</p><p><a href="{url_for("review", run_id=run_id)}">'
            "Back to review</a></p>",
            code,
        )

    # Load → mutate → save under one cross-process lock so two reviewers
    # (or two gunicorn workers) can't lose each other's promotion. The
    # only prior post-run JSON write-backs used bare write_text — this
    # route deliberately uses the atomic + locked pattern instead.
    with cross_process_lock(W.RUNS_DIR / f"{run_id}.json.lock"):
        data = W._load_run(run_id)
        if not data:
            return _fail(404, "Run not found.")
        rr = data.get("recognition_report")
        if not isinstance(rr, dict):
            return _fail(400, "This run has no recognition report to add a highlight to.")
        traces = rr.get("swim_traces") or []
        trace = next(
            (t for t in traces if isinstance(t, dict) and t.get("swim_id") == swim_id),
            None,
        )
        if trace is None:
            return _fail(404, "That swim isn't in this run's analysed swims.")
        ranked = rr.get("ranked_achievements")
        if not isinstance(ranked, list):
            ranked = []
            rr["ranked_achievements"] = ranked
        # Only swims the automation flagged NOTHING for are promotable —
        # a swim with cards is already in the review list, and a second
        # promotion would duplicate the first.
        gkey = W._swim_tiers.swim_group_key(swim_id)
        try:
            groups = W._swim_tiers.group_ranked_achievements(ranked)
        except Exception:
            groups = {}
        if int(trace.get("achievement_count") or 0) > 0 or groups.get(gkey):
            return _fail(409, "This swim already has a card in the review list.")

        swimmer_name = str(trace.get("swimmer_name") or "").strip()
        event = str(trace.get("event") or "").strip()
        time_str = str(trace.get("time_str") or "").strip()
        # Deterministic fact-only default headline — the swim's own traced
        # facts, never invented copy. A club-typed headline wins.
        headline = headline_in or f"{swimmer_name} — {event} in {time_str}"
        now_iso = datetime.now(timezone.utc).isoformat()
        ach = {
            "type": W._swim_tiers.CUSTOM_HIGHLIGHT_TYPE,
            "swim_id": f"{swim_id}:custom",
            "swimmer_id": swim_id.split(":", 1)[0],
            "swimmer_name": swimmer_name,
            "event": event,
            "headline": headline,
            "angle_hint": note_in
            or "Club-chosen highlight — a reviewer promoted this swim from the all-swims list.",
            "confidence": 0.9,
            "confidence_label": "high",
            "evidence": [
                {
                    "source_type": "results_file",
                    "source_name": str(data.get("file_name") or "results file"),
                    "statement": f"Result row: {event} — {time_str}",
                    "source_url": None,
                    "fetched_at": None,
                    "confidence": "high",
                }
            ],
            "raw_facts": {
                "time_str": time_str,
                "promoted_by": "reviewer",
                "promoted_at": now_iso,
                "reviewer_note": note_in,
            },
            "uncertainty_notes": [],
            "detector_name": "manual_promotion",
            "post_angle": "recap_mention",
        }
        ra = {
            "achievement": ach,
            # Fixed, explainable placement — this is a human call, not an
            # engine score, and the single transparent factor says so.
            "priority": 0.5,
            "factors": [
                {
                    "name": "manual_promotion",
                    "value": 1.0,
                    "weight": 1.0,
                    "reason": "Promoted by a club reviewer from the all-swims list",
                    "plain_summary": (
                        "A reviewer chose this swim as a highlight — the "
                        "automation didn't rank it."
                    ),
                }
            ],
            "quality_band": "story",
            "suggested_post_type": "story",
            "rank": len(ranked) + 1,
            "safe_to_post": {
                "level": "needs_review",
                "reason": "Human-promoted highlight — check the facts and caption before posting.",
            },
            "post_angle": "recap_mention",
        }
        # Children's Code display transform — the pipeline applies this at
        # run time, so a card created after the run must apply it here or
        # a minor's full name would leak through the promotion path.
        try:
            _prof = W.load_profile(data.get("profile_id") or "") if data.get("profile_id") else None
            if _prof is not None:
                from mediahub.compliance.child_policy import apply_to_ranked

                apply_to_ranked(_prof, [ra])
        except Exception:
            W.log.warning("promote: child-policy transform failed for %s", run_id, exc_info=True)

        ranked.append(ra)
        # Keep the report's own tallies consistent with the list it carries.
        rr["n_achievements"] = int(rr.get("n_achievements") or 0) + 1
        trace["achievement_count"] = int(trace.get("achievement_count") or 0) + 1
        trace["summary"] = "promoted to a custom highlight by a reviewer"
        W._atomic_write_json(W.RUNS_DIR / f"{run_id}.json", data, default=str)

    # Refresh the cached DB counts (display never depends on this write).
    try:
        conn = W._db()
        conn.execute(
            "UPDATE runs SET n_achievements = ?, n_standout = ? WHERE id = ?",
            (
                int(rr.get("n_achievements") or 0),
                W._n_standout_from_report(rr),
                run_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    W.log.info("promote: run=%s swim=%s by profile=%s", run_id, swim_id, _pid)
    if wants_json:
        return jsonify({"ok": True, "card_id": ach["swim_id"]})
    return redirect(url_for("review", run_id=run_id) + "?promoted=1#mh-all-swims")


def api_cards_bulk_status(run_id):
    """UI 1.9 — apply one workflow status to many cards at once.

    Content-negotiated: a fetch() JSON call gets a per-card result list back;
    a no-JS HTML form POST is redirected to /review with a flash summary.
    Each card is gated independently, so the consent gate (minors / opted-out
    athletes) can block a single approval without aborting the whole batch —
    the same rule the single-card route enforces.
    """
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404
    ws = W._get_wf_store()
    if ws is None:
        return jsonify({"error": "workflow not available"}), 503

    wants_json = W._req_wants_json(request)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    # Coerce to str before .strip(): a fuzzed/AJAX body may send a non-string
    # (number, list) under "status" — that must be a clean 400, not a 500.
    status_str = str(
        payload.get("status") or request.form.get("status") or request.form.get("op") or ""
    ).strip()
    try:
        status = W.CardStatus(status_str)
    except (ValueError, NameError):
        if wants_json:
            return jsonify({"error": f"invalid status: {status_str}"}), 400
        W._flash_toast("Couldn't apply that bulk action — unknown status.", "error")
        return redirect(url_for("review", run_id=run_id))

    ids = W._bulk_ids_from_request(request, "ids", "card_ids")
    if not ids:
        if wants_json:
            return (
                jsonify({"error": "no_selection", "results": [], "summary": ws.summary(run_id)}),
                400,
            )
        W._flash_toast("Select at least one card first.", "info")
        return redirect(url_for("review", run_id=run_id))

    # 1.18 role gate: a bulk status change is the same sign-off action as
    # the single-card route — refuse a seat without the approve capability
    # before any card moves (operator / unbound pilot resolve to owner).
    if not W._run_actor_can(W._perms.CAP_APPROVE, run_id, run_data):
        reason = (
            f"Your role ({W._perms.role_label(W._run_role(run_id, run_data))}) "
            "can't approve or reject content."
        )
        if wants_json:
            return jsonify({"error": "forbidden", "reason": reason}), 403
        W._flash_toast(reason, "error")
        return redirect(url_for("review", run_id=run_id))

    need_consent = status in (W.CardStatus.APPROVED, W.CardStatus.POSTED)
    if need_consent:
        from mediahub.compliance.gate import (
            consent_block_reason_for_card,
            find_card_in_run,
        )
    owner_pid = W._run_owner_profile_id(run_id) or W._active_profile_id() or ""
    # Finding #116: audit actor for bulk approvals (the signed-in member).
    _human_actor = W._auth.current_user_email() or ""
    results: list[dict] = []
    n_ok = 0
    n_blocked = 0
    for cid in ids:
        if need_consent:
            card = find_card_in_run(run_data or {}, cid)
            reason = consent_block_reason_for_card((run_data or {}).get("profile_id", ""), card)
            if reason:
                W.log.info("consent gate blocked bulk approval run=%s card=%s", run_id, cid)
                results.append(
                    {"id": cid, "ok": False, "error": "consent_blocked", "reason": reason}
                )
                n_blocked += 1
                continue
            # 1.12 brand-lock gate — same opt-in rule as the single-card path.
            brand_reason = W._brand_lock_block_reason(run_id, cid)
            if brand_reason:
                results.append(
                    {"id": cid, "ok": False, "error": "brand_locked", "reason": brand_reason}
                )
                n_blocked += 1
                continue
        # 1.18 task gate — an open review task holds the card, same as the
        # single-card path, so bulk-approve can't skip an unresolved task.
        if status == W.CardStatus.APPROVED:
            task_reason = W._open_tasks_block_reason(run_id, cid)
            if task_reason:
                results.append(
                    {"id": cid, "ok": False, "error": "tasks_open", "reason": task_reason}
                )
                n_blocked += 1
                continue
        # 1.12 group-approver rule — record the vote; hold until satisfied so
        # bulk-approve can't bypass a governed workspace's rule.
        if status == W.CardStatus.APPROVED:
            held, info = W._group_approval_block(run_id, cid)
            if held:
                results.append({"id": cid, "ok": True, "status": "queue", **info})
                continue
        if status in (W.CardStatus.REJECTED, W.CardStatus.QUEUE):
            _led = W._get_approval_ledger()
            if _led is not None:
                _led.clear(run_id, cid)
        ws.set_status(run_id, cid, status, actor=_human_actor)
        if status in (W.CardStatus.APPROVED, W.CardStatus.REJECTED, W.CardStatus.QUEUE):
            _action = {
                W.CardStatus.APPROVED: "approved",
                W.CardStatus.REJECTED: "rejected",
                W.CardStatus.QUEUE: "requeued",
            }[status]
            W._phase_w_after_status_change(owner_pid, run_id, cid, _action, actor=_human_actor)
        results.append({"id": cid, "ok": True, "status": status.value})
        n_ok += 1
    summary = ws.summary(run_id)
    if wants_json:
        return jsonify(
            {
                "ok": True,
                "status": status.value,
                "results": results,
                "summary": summary,
                "n_ok": n_ok,
                "n_blocked": n_blocked,
            }
        )
    verb = {"approved": "Approved", "rejected": "Rejected", "queue": "Re-queued"}.get(
        status.value, status.value.capitalize()
    )
    msg = f"{verb} {n_ok} card{'' if n_ok == 1 else 's'}."
    if n_blocked:
        # Name the actual gate(s): n_blocked aggregates consent,
        # brand-lock and open-task blocks — blaming the consent gate
        # for all of them misdirects the fix.
        _reason_labels = {
            "consent_blocked": "consent",
            "brand_locked": "brand lock",
            "tasks_open": "open task",
        }
        _by_reason: dict[str, int] = {}
        for r in results:
            if not r.get("ok") and r.get("error") in _reason_labels:
                key = _reason_labels[r["error"]]
                _by_reason[key] = _by_reason.get(key, 0) + 1
        detail = ", ".join(f"{n} {label}" for label, n in _by_reason.items())
        msg += f" {n_blocked} blocked" + (f" ({detail})." if detail else " by review gates.")
    W._flash_toast(msg, "success" if n_ok else "info")
    return redirect(url_for("review", run_id=run_id))


def api_cards_bulk_export(run_id):
    """UI 1.9 — download the selected cards as one JSON file.

    Scoped sibling of the per-run /export (which dumps the whole run): a
    reviewer ticks the achievements they want and gets just those, with each
    card's live workflow status folded in. Always a native attachment
    download, so it works with or without JS.
    """
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404
    ids = W._bulk_ids_from_request(request, "ids", "card_ids")
    if not ids:
        if W._req_wants_json(request):
            return jsonify({"error": "no_selection"}), 400
        W._flash_toast("Select at least one card to export.", "info")
        return redirect(url_for("review", run_id=run_id))
    wanted = set(ids)
    rr = (run_data or {}).get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    ws = W._get_wf_store()
    wf_states = ws.load(run_id) if ws else {}
    selected: list[dict] = []
    for ra in ranked:
        ach = ra.get("achievement") or {}
        cid = ach.get("swim_id") or ra.get("id")
        if cid in wanted:
            st = wf_states.get(cid)
            selected.append(
                {
                    "card_id": cid,
                    "status": (st.status.value if st else "queue"),
                    "rank": ra.get("rank"),
                    "quality_band": ra.get("quality_band"),
                    "suggested_post_type": ra.get("suggested_post_type"),
                    "achievement": ach,
                    "factors": ra.get("factors"),
                }
            )
    export = {
        "run_id": run_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile_id": (run_data or {}).get("profile_id", ""),
        "requested": len(wanted),
        "exported": len(selected),
        "cards": selected,
    }
    fname = (
        "mediahub-cards-" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id)[:40] or "export") + ".json"
    )
    return Response(
        json.dumps(export, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def api_cards_bulk_download(run_id):
    """F-5 — download the selected cards' postable content as one ZIP.

    The reviewer's content companion to the JSON "Export data" dump: each
    selected card contributes a folder with its ready-to-post caption and
    branded visual (the same assets the per-card Download button ships,
    resolved through the shared ``_card_export_assets`` helper). A native
    attachment download, so it works with or without JS.
    """
    from flask import send_file
    import zipfile

    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404
    ids = W._bulk_ids_from_request(request, "ids", "card_ids")
    if not ids:
        if W._req_wants_json(request):
            return jsonify({"error": "no_selection"}), 400
        W._flash_toast("Select at least one card to download.", "info")
        return redirect(url_for("review", run_id=run_id))

    resolved = []
    for cid in ids:
        assets = W._card_export_assets(run_id, cid, run_data)
        if assets is not None:
            resolved.append(assets)
    if not resolved:
        if W._req_wants_json(request):
            return jsonify({"error": "no_cards_found"}), 404
        W._flash_toast("None of the selected cards could be found.", "error")
        return redirect(url_for("review", run_id=run_id))

    n_missing_visual = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, (slug, caption, png_bytes, png_name) in enumerate(resolved, start=1):
            folder = f"{idx:02d}-{slug}"
            zf.writestr(f"{folder}/{slug}-caption.txt", caption)
            if png_bytes:
                zf.writestr(f"{folder}/{png_name or slug + '.png'}", png_bytes)
            else:
                n_missing_visual += 1
        readme = [
            "MediaHub content export.\n",
            f"{len(resolved)} card(s), one folder each: the ready-to-post caption",
            "(.txt) and the branded visual (.png) where it has been generated.\n",
        ]
        if n_missing_visual:
            readme.append(
                f"{n_missing_visual} card(s) had no visual yet — open the card in the\n"
                "content builder and click 'Create graphic' first, then download again.\n"
            )
        readme.append(
            "\nPost each visual + caption to your chosen platform manually.\n"
            "No third-party scheduler required.\n"
        )
        zf.writestr("README.txt", "".join(readme))
    buf.seek(0)
    fname = (
        "mediahub-content-" + (re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id)[:40] or "export") + ".zip"
    )
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=fname)


def api_card_reaction_toggle(run_id, card_id):
    """Toggle one emoji reaction on a card for an anonymous reactor.

    Body (JSON): ``{"emoji": "👍|❤️|🔥", "reactor_id": "<anon client id>"}``.
    A reactor's first tap on an emoji adds their row; a second tap removes
    it — so the server-side tally counts each reactor once per emoji and the
    UI reads as a true toggle. Returns the fresh per-card tally plus the set
    this reactor now holds, so the client can update without a reload::

        {"ok": true, "counts": {"👍": 2, ...}, "mine": ["👍", ...]}

    Tenant-isolated (same guard as the workflow API), so a reaction can't be
    cast on a run another organisation owns; a genuinely missing run 404s
    too, so a ghost id never accretes orphan reaction rows.
    """
    run_data = W._load_run(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404

    payload = request.get_json(silent=True) or {}
    emoji = payload.get("emoji", "")
    reactor = str(payload.get("reactor_id") or "").strip()
    if emoji not in W.REACTION_EMOJI:
        return jsonify({"error": "invalid emoji"}), 400
    if not reactor or len(reactor) > 64:
        return jsonify({"error": "invalid reactor_id"}), 400
    # Card ids are short engine identifiers (swim_id / "sp:type:event"); a
    # value far longer than that is junk, so reject it rather than store it.
    if not card_id or len(card_id) > 256:
        return jsonify({"error": "invalid card_id"}), 400
    # ... and it must actually be one of THIS run's cards — the run JSON
    # is already loaded for the tenancy check, so an arbitrary made-up id
    # can never accrete rows against the run.
    if card_id not in W._run_card_id_set(run_data):
        return jsonify({"error": "invalid card_id"}), 400

    try:
        conn = W._db()
        existing = conn.execute(
            "SELECT 1 FROM card_reactions "
            "WHERE run_id=? AND card_id=? AND emoji=? AND reactor_id=?",
            (run_id, card_id, emoji, reactor),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM card_reactions "
                "WHERE run_id=? AND card_id=? AND emoji=? AND reactor_id=?",
                (run_id, card_id, emoji, reactor),
            )
        else:
            # Row-growth brake: reactor_id is client-minted, so cap the
            # number of DISTINCT reactors per card. A reactor already on
            # the card may keep toggling its other emoji freely.
            row = conn.execute(
                "SELECT COUNT(DISTINCT reactor_id) AS n, "
                "MAX(CASE WHEN reactor_id=? THEN 1 ELSE 0 END) AS mine "
                "FROM card_reactions WHERE run_id=? AND card_id=?",
                (reactor, run_id, card_id),
            ).fetchone()
            if not row["mine"] and row["n"] >= W.REACTION_MAX_REACTORS_PER_CARD:
                conn.close()
                return jsonify({"error": "too_many_reactors"}), 429
            conn.execute(
                "INSERT OR IGNORE INTO card_reactions "
                "(run_id, card_id, emoji, reactor_id, created_at) VALUES (?,?,?,?,?)",
                (
                    run_id,
                    card_id,
                    emoji,
                    reactor,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
        counts = {e: 0 for e in W.REACTION_EMOJI}
        for r in conn.execute(
            "SELECT emoji, COUNT(*) AS n FROM card_reactions "
            "WHERE run_id=? AND card_id=? GROUP BY emoji",
            (run_id, card_id),
        ).fetchall():
            if r["emoji"] in counts:
                counts[r["emoji"]] = r["n"]
        mine = [
            r["emoji"]
            for r in conn.execute(
                "SELECT emoji FROM card_reactions " "WHERE run_id=? AND card_id=? AND reactor_id=?",
                (run_id, card_id, reactor),
            ).fetchall()
            if r["emoji"] in W.REACTION_EMOJI
        ]
        conn.close()
    except Exception as e:
        W.log.warning("reaction toggle failed run=%s card=%s: %s", run_id, card_id, e)
        return jsonify({"error": "reaction_failed"}), 500

    return jsonify({"ok": True, "counts": counts, "mine": mine})


def api_run_reactions(run_id):
    """Reaction state for a whole run, for the review/builder page on load.

    Query: ``?reactor_id=<anon client id>`` (optional). Returns the full
    per-card tally plus, when a ``reactor_id`` is given, the cards/emoji that
    reactor holds — so one fetch lets the client both reconcile counts and
    light up the viewer's own reactions::

        {"ok": true,
         "counts": {"<card_id>": {"👍": 2, ...}, ...},
         "mine":   {"<card_id>": ["👍", ...], ...}}
    """
    run_data = W._load_run(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404

    reactor = str(request.args.get("reactor_id") or "").strip()
    counts: dict[str, dict[str, int]] = {}
    mine: dict[str, list[str]] = {}
    try:
        conn = W._db()
        for r in conn.execute(
            "SELECT card_id, emoji, COUNT(*) AS n FROM card_reactions "
            "WHERE run_id=? GROUP BY card_id, emoji",
            (run_id,),
        ).fetchall():
            if r["emoji"] in W.REACTION_EMOJI:
                counts.setdefault(r["card_id"], {})[r["emoji"]] = r["n"]
        if reactor and len(reactor) <= 64:
            for r in conn.execute(
                "SELECT card_id, emoji FROM card_reactions WHERE run_id=? AND reactor_id=?",
                (run_id, reactor),
            ).fetchall():
                if r["emoji"] in W.REACTION_EMOJI:
                    mine.setdefault(r["card_id"], []).append(r["emoji"])
        conn.close()
    except Exception as e:
        W.log.warning("reaction fetch failed run=%s: %s", run_id, e)
        return jsonify({"error": "reaction_failed"}), 500

    return jsonify({"ok": True, "counts": counts, "mine": mine})


def api_turn_into(run_id):
    """Generate a Turn-Into pack (up to 8 artefacts) from this run.

    Body (JSON, all optional):
      { "deterministic": bool }   force heuristic mode (no LLM)
      { "async": bool }           run in background, return job_id (default: sync)

    With async=True, returns { job_id, status_url } immediately. Poll
    GET /api/runs/<run_id>/turn-into-status/<job_id> for result.
    """
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run not found"}), 404
    if not run_data:
        return jsonify({"error": "run not found"}), 404

    profile_id = run_data.get("profile_id", "")
    profile = W.load_profile(profile_id) if profile_id else None
    if profile is None:
        profile = W.ClubProfile(
            profile_id=profile_id or "default",
            display_name=run_data.get("profile_display", "") or "Club",
        )

    payload = request.get_json(silent=True) or {}
    deterministic = bool(payload.get("deterministic", False))
    async_mode = bool(payload.get("async", False))

    # Consent gate: blocked athletes never reach the pack builder, so
    # they cannot be rendered into any artefact.
    from mediahub.compliance.gate import filter_consent_blocked

    run_data, _consent_excluded = filter_consent_blocked(run_data.get("profile_id", ""), run_data)
    if _consent_excluded:
        W.log.info(
            "consent gate excluded %d athlete(s) from turn-into pack run=%s",
            len(_consent_excluded),
            run_id,
        )

    # The generate job runs on a background thread where the current_app proxy
    # has no context — capture the real app object (what the create_app closure
    # used to close over) before the thread spawns.
    app = current_app._get_current_object()

    def _do_generate(job_id: str) -> None:
        try:
            with app.test_request_context():
                from mediahub.turn_into import turn_meet_into_pack, save_pack

                pack = turn_meet_into_pack(run_data, profile, deterministic=deterministic)
                save_pack(pack, run_id, base_dir=W.DATA_DIR / "turn_into_packs")
                pack_url = url_for("turn_into_pack_view", run_id=run_id, pack_id=pack["pack_id"])
            record = {
                "status": "done",
                "run_id": run_id,
                # Pack is persisted to disk by save_pack() above; storing
                # it here too just bloats RAM. The response builders
                # already strip "pack", so dropping it from the dict is a
                # no-op for callers.
                "pack_id": pack["pack_id"],
                "n_artefacts": len(pack.get("artefacts", [])),
                "skipped": [s.get("type") for s in pack.get("skipped", [])],
                "pack_url": pack_url,
            }
        except Exception as e:
            import traceback as _tb

            record = {
                "status": "error",
                "run_id": run_id,
                "error": str(e),
                "trace": _tb.format_exc()[-500:],
            }
        # Write to both the in-memory cache (fast same-worker reads) and
        # the shared disk record (so a poll on the other gunicorn worker
        # still resolves the job).
        W._turn_into_jobs[job_id] = record
        W._ti_job_write(job_id, record)

    import uuid as _uuid

    job_id = _uuid.uuid4().hex

    # Evict any old finished jobs before inserting a new one so the
    # dict can't grow unbounded over a long-running deploy. Also prune
    # stale on-disk job records on the same cadence.
    with W._active_lock:
        W._maybe_evict_turn_into_jobs()
        W._prune_ti_job_files()

    running = {"status": "running", "run_id": run_id}

    if async_mode:
        # Async: kick off background thread, return job_id immediately.
        # Persist the "running" record up front so a poll that lands on
        # the other gunicorn worker (before the thread finishes) still
        # finds the job instead of reporting "job not found".
        W._turn_into_jobs[job_id] = running
        W._ti_job_write(job_id, running)
        t = W.threading.Thread(target=_do_generate, args=(job_id,), daemon=True)
        t.start()
        return jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "status": "running",
                "status_url": url_for("api_turn_into_status", run_id=run_id, job_id=job_id),
            }
        )

    # Synchronous (default): block until pack is generated, return final payload
    W._turn_into_jobs[job_id] = running
    _do_generate(job_id)
    job = W._turn_into_jobs[job_id]
    if job["status"] == "error":
        return jsonify({"error": "turn_into_failed", "message": job["error"]}), 500
    return jsonify({"ok": True, **{k: v for k, v in job.items() if k != "pack" and k != "status"}})


def api_turn_into_status(run_id: str, job_id: str):
    """Poll Turn-Into job status. Returns { status: running|done|error, ... }."""
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    # In-memory first (fast, same-worker), then the shared disk record:
    # with --workers 2 the poll often lands on a different worker than
    # the one that created the job, so the on-disk copy is what keeps
    # the UI from reporting a spurious "job not found".
    job = W._turn_into_jobs.get(job_id) or W._ti_job_read(job_id)
    if job is None:
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    # A job belongs to exactly one run. Don't let one run's URL read
    # another run's job even if the (unguessable) job_id leaked.
    if job.get("run_id") and job.get("run_id") != run_id:
        return jsonify({"status": "not_found", "error": "job not found"}), 404
    if job["status"] == "running":
        return jsonify({"status": "running"})
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "unknown")}), 500
    return jsonify(
        {
            "ok": True,
            "status": "done",
            **{k: v for k, v in job.items() if k not in ("pack", "status")},
        }
    )


def api_turn_into_edit_caption(run_id, pack_id):
    """Inline-edit a caption within a saved pack.

    Body (JSON):
      {
        "artefact_index": int,
        "caption_key":    str,   # e.g. "default" | "instagram" | "swimmer_1"
        "text":           str,
        # OR for x_thread:
        "x_thread_index": int,   # 0-based
        "text":           str,
      }
    """
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return jsonify({"error": "pack not found"}), 404
    from mediahub.turn_into import load_pack, save_pack

    base = W.DATA_DIR / "turn_into_packs"
    pack = load_pack(run_id, pack_id, base_dir=base)
    if pack is None:
        return jsonify({"error": "pack not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        idx = int(data.get("artefact_index"))
    except (TypeError, ValueError):
        return jsonify({"error": "artefact_index required"}), 400
    artefacts = pack.get("artefacts") or []
    if idx < 0 or idx >= len(artefacts):
        return jsonify({"error": "artefact_index out of range"}), 400
    text = str(data.get("text", ""))

    artefact = artefacts[idx]
    captions = artefact.setdefault("captions", {})

    if "x_thread_index" in data and data["x_thread_index"] is not None:
        try:
            xi = int(data["x_thread_index"])
        except (TypeError, ValueError):
            return jsonify({"error": "x_thread_index must be int"}), 400
        posts = captions.get("x_thread") or []
        if xi < 0 or xi >= len(posts):
            return jsonify({"error": "x_thread_index out of range"}), 400
        posts[xi] = text
        captions["x_thread"] = posts
    else:
        key = str(data.get("caption_key", "default"))
        captions[key] = text

    artefacts[idx] = artefact
    pack["artefacts"] = artefacts
    save_pack(pack, run_id, base_dir=base)
    return jsonify({"ok": True})


def api_run_newsletter(run_id: str):
    fmt = (request.args.get("format") or "html").strip().lower()
    if fmt not in ("html", "text", "zip"):
        return jsonify({"error": "format must be html|text|zip"}), 400
    download = request.args.get("download") == "1"

    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if run_data is None:
        return jsonify({"error": "run_not_found"}), 404

    profile_id = run_data.get("profile_id") or ""
    profile = W.load_profile(profile_id) if profile_id else None
    # Fall back to the session-pinned active profile so a run with
    # no stored profile_id still renders with the user's branding.
    if profile is None:
        profile = W._active_profile()

    # Build the newsletter artefact directly — avoids the cost of
    # generating the full Turn-Into pack just for this one output.
    try:
        from mediahub.turn_into import templates as _ti
        from mediahub.turn_into.pipeline import _meet_summary, _resolve_voice_profile

        meet_summary = _meet_summary(run_data)
        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        voice_profile = _resolve_voice_profile(profile_id) if profile_id else None
        brand_kit = None
        try:
            if profile is not None:
                brand_kit = profile.get_brand_kit()
        except Exception:
            brand_kit = None
        artefact = _ti.build_parent_newsletter(
            meet_summary,
            ranked,
            profile=profile,
            voice_profile=voice_profile,
            brand_kit=brand_kit,
            deterministic=False,
        )
    except Exception as e:
        return jsonify({"error": f"newsletter_build_failed: {e}"}), 500

    from mediahub.brand.newsletter_renderer import (
        render_email_html,
        render_plaintext,
        render_zip,
        safe_filename_for,
    )

    slug = safe_filename_for((run_data.get("meet") or {}).get("name") or run_id)

    if fmt == "text":
        body = render_plaintext(artefact)
        resp = Response(body, mimetype="text/plain; charset=utf-8")
        if download:
            resp.headers["Content-Disposition"] = f'attachment; filename="{slug}-newsletter.txt"'
        return resp
    if fmt == "zip":
        body = render_zip(
            artefact, profile=profile, meet_summary=meet_summary, base_name=f"{slug}-newsletter"
        )
        resp = Response(body, mimetype="application/zip")
        resp.headers["Content-Disposition"] = f'attachment; filename="{slug}-newsletter.zip"'
        return resp
    # html (default)
    body = render_email_html(artefact, profile=profile, meet_summary=meet_summary)
    resp = Response(body, mimetype="text/html; charset=utf-8")
    if download:
        resp.headers["Content-Disposition"] = f'attachment; filename="{slug}-newsletter.html"'
    return resp


def api_card_photo_upload(run_id: str, card_id: str):
    """Upload a photo for ONE card's graphic and remember who's in it.

    The photo is stored in the organisation's media library linked to
    this card's athlete by name, so at the next meet the picker
    suggests it for that swimmer instead of asking for a re-upload.
    Returns the new asset so the UI can attach it to the graphic
    immediately.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req

    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    # Resolve the card so the upload is linked to a real athlete.
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    target = None
    for ra in ranked:
        _a = ra.get("achievement") or {}
        if _a.get("swim_id") == card_id or ra.get("id") == card_id:
            target = ra
            break
    if target is None:
        for c in run_data.get("cards") or []:
            if c.get("swim_id") == card_id or c.get("id") == card_id:
                target = {"achievement": c}
                break
    if target is None:
        return jsonify({"error": "card_not_found"}), 404
    athlete = str((target.get("achievement") or {}).get("swimmer_name") or "").strip()

    f = _req.files.get("photo")
    if not f or not f.filename:
        return jsonify({"error": "no_file"}), 400
    # M24 — the per-card upload accepts race clips (video/*) too: a coach
    # on the card-review page can finally say "here's the video of this
    # race". Clips route through the footage ingest spine (probe + M27
    # poster + the review-first needs_approval permission default).
    from mediahub.video.ingest import is_video_filename as _is_video_name

    _is_clip = (f.mimetype or "").startswith("video/") or _is_video_name(f.filename or "")
    if not _is_clip and not (f.mimetype or "").startswith("image/"):
        return jsonify({"error": "not_an_image"}), 400

    # Photos live under the ORGANISATION's library (not a per-run
    # synthetic id) so the athlete↔photo memory carries across meets.
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403

    if _is_clip:
        from mediahub.video.ingest import ingest_footage_stream

        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
        try:
            clip_asset = ingest_footage_stream(
                f.stream,
                f.filename or "clip.mp4",
                profile_id=profile_id,
                description=(
                    f"Race clip of {athlete} — uploaded on the card for {meet_name}".strip(" —")
                ),
                uploaded_by=W._active_profile_id(),
                # permission default needs_approval preserved (review-first).
            )
        except ValueError as e:
            return jsonify({"error": "bad_footage", "message": str(e)}), 400
        except OSError:
            W.log.exception("card race-clip upload could not be stored")
            return jsonify(
                {
                    "error": "storage_failed",
                    "message": "The clip couldn't be saved on the server — its "
                    "storage is full or unavailable. Please try again.",
                }
            ), 500
        store = W._v8_get_media_store()
        # Link the clip to THIS card's athlete + meet so M23's footage
        # sourcing (and the picker's memory) can find it.
        store.merge_links(
            clip_asset.id,
            athlete_names=[athlete] if athlete else [],
            meet_ids=[run_id],
        )
        clip_asset = store.get(clip_asset.id) or clip_asset
        # M25 — auto best-frame: the clip's top moment becomes a linked
        # photo asset (permission INHERITED, never wider) so the still
        # card lights up too. Best-effort: a frame miss never fails the
        # clip upload.
        frame_info = None
        try:
            from mediahub.video.best_frame import extract_best_frame

            frame = extract_best_frame(clip_asset, store=store)
            frame_info = {
                "id": frame.id,
                "url": url_for("api_media_library_file", asset_id=frame.id),
                "label": athlete or "best frame",
                "permission_status": frame.permission_status,
            }
        except Exception as e:
            W.log.info("card clip best-frame extraction skipped: %s", e)
        meta = clip_asset.media_meta if isinstance(clip_asset.media_meta, dict) else {}
        return jsonify(
            {
                "ok": True,
                "asset": {
                    "kind": "clip",
                    "id": clip_asset.id,
                    "url": url_for("api_media_library_file", asset_id=clip_asset.id),
                    "poster_url": (
                        url_for("api_media_library_file", asset_id=clip_asset.id, poster=1)
                        if meta.get("poster")
                        else ""
                    ),
                    "label": athlete or "race clip",
                    "filename": clip_asset.filename,
                    "duration_ms": meta.get("duration_ms", 0),
                    "permission_status": clip_asset.permission_status,
                    "frame_asset": frame_info,
                },
            }
        )

    # Same ingest gate as the library form: extension allowlist, HEIC
    # normalisation, and a real decode check — a renamed .svg/.html must
    # never be stored (library files are served back same-origin).
    try:
        dest = W._store_photo_upload(f, profile_id)
    except W._PhotoRejectedError as e:
        return jsonify({"error": e.code, "message": e.message}), 415

    store = W._v8_get_media_store()
    from mediahub.media_library import tagger as _ml_tagger
    from mediahub.media_library.models import MediaAsset

    # Same ingest spine as the library upload: upright pixels + measured
    # dimensions/orientation/quality so the selector can rank this photo.
    _ml_tagger.bake_exif_orientation(dest)

    meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
    asset = MediaAsset(
        id="",
        filename=Path(f.filename).name,
        path=str(dest),
        type="athlete_action",
        description_raw=(f"Photo of {athlete} — uploaded on the card for {meet_name}".strip(" —")),
        profile_id=profile_id,
        linked_athlete_names=[athlete] if athlete else [],
        linked_meet_ids=[run_id],
        permission_status="user_owned",
        approval_status="approved",
    )
    _ml_tagger.measure_asset(asset)
    asset = store.save(asset)
    # M34 — vision-tag the fresh upload in the background (provider-gated;
    # a no-provider deployment simply keeps the human-entered athlete link).
    W._autotag_asset_async(asset.id, profile_id, run_id=run_id)
    return jsonify(
        {
            "ok": True,
            "asset": {
                "id": asset.id,
                "url": url_for("api_media_library_file", asset_id=asset.id),
                "label": athlete or "uploaded photo",
                "suggested": True,
            },
        }
    )


def api_card_photo_confirm(run_id: str, card_id: str):
    """Confirm a picker photo as being OF this card's athlete (M4 seam).

    The PHOTOS-6 evaluator surfaces "photos uploaded for this meet" as
    pick-from candidates; a human click here is the confirmation that
    writes the athlete link (and the meet link) back onto the asset via
    the store's additive ``merge_links`` — never auto-matched, never
    overwriting human-entered links. Next meet, the picker suggests the
    right face automatically.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data, target = W._load_run_for_card(run_id, card_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if target is None:
        return jsonify({"error": "card_not_found"}), 404
    athlete = str((target.get("achievement") or {}).get("swimmer_name") or "").strip()
    body = request.get_json(silent=True) or {}
    asset_id = str(body.get("asset_id") or "").strip()
    if not asset_id:
        return jsonify({"error": "asset_id_required"}), 400
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if asset is None:
        return jsonify({"error": "asset_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    store.merge_links(
        asset_id,
        athlete_names=[athlete] if athlete else [],
        meet_ids=[run_id],
    )
    return jsonify({"ok": True, "asset_id": asset_id, "athlete": athlete})


def api_card_clip_unlink(run_id: str, card_id: str):
    """Detach a race clip from this card (M24's remove affordance).

    Removes THIS run's meet link (and this card's athlete link) from the
    footage asset so it no longer backs the card — the clip itself stays
    in the club's library. Never deletes footage.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data, target = W._load_run_for_card(run_id, card_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if target is None:
        return jsonify({"error": "card_not_found"}), 404
    athlete = str((target.get("achievement") or {}).get("swimmer_name") or "").strip()
    body = request.get_json(silent=True) or {}
    asset_id = str(body.get("asset_id") or "").strip()
    if not asset_id:
        return jsonify({"error": "asset_id_required"}), 400
    store = W._v8_get_media_store()
    asset = store.get(asset_id)
    if asset is None or asset.type != "footage":
        return jsonify({"error": "footage_not_found"}), 404
    if not W._session_can_access_profile(asset.profile_id):
        return jsonify({"error": "forbidden"}), 403
    athlete_lc = athlete.lower()
    store.update_fields(
        asset_id,
        {
            "linked_meet_ids": [m for m in (asset.linked_meet_ids or []) if m != run_id],
            "linked_athlete_names": [
                n
                for n in (asset.linked_athlete_names or [])
                if str(n).strip().lower() != athlete_lc
            ],
        },
    )
    return jsonify({"ok": True, "asset_id": asset_id})


def api_venue_import(run_id: str):
    """Save one venue-search result into the org's media library.

    The venue picker (per-graphic photo chips) calls this with a chosen
    ``venue_search.VenueImageResult``; the image is downloaded once,
    stored as a venue asset with its licence/attribution preserved, and
    returned in the same shape as a card photo upload so the UI can
    attach it to the graphic immediately.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if run_data is None:
        return jsonify({"error": "run_not_found"}), 404

    body = request.get_json(silent=True) or {}
    direct_url = str(body.get("direct_url") or "").strip()
    if not direct_url.startswith(("http://", "https://")):
        return jsonify({"error": "bad_image_url"}), 400
    title = str(body.get("title") or "").strip()
    licence = str(body.get("licence") or "").strip()
    source_url = str(body.get("source_url") or "").strip()
    attribution = str(body.get("attribution") or "").strip()

    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403

    try:
        # SSRF guard: validate direct_url + every redirect hop before we
        # fetch (an authed tenant must not be able to aim this at an
        # internal / metadata address).
        resp = W._ssrf_safe_stream_get(direct_url, timeout=15)
        resp.raise_for_status()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if not ctype.startswith("image/"):
            return jsonify({"error": "not_an_image"}), 400
        data = resp.raw.read(15 * 1024 * 1024 + 1, decode_content=True)
    except ValueError:
        return jsonify({"error": "bad_image_url"}), 400
    except Exception as e:
        return jsonify({"error": f"download_failed: {e}"}), 502
    if len(data) > 15 * 1024 * 1024:
        return jsonify({"error": "image_too_large", "max_mb": 15}), 400

    ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(
        ctype.split(";")[0].strip(), ".jpg"
    )
    upload_dir = W.UPLOADS_DIR / "media_library" / profile_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"asset_{W.uuid.uuid4().hex[:12]}{ext}"
    dest.write_bytes(data)

    store = W._v8_get_media_store()
    from mediahub.media_library.models import MediaAsset

    meet = run_data.get("meet") or {}
    venue = str(meet.get("venue") or run_data.get("venue") or "").strip()
    asset = MediaAsset(
        id="",
        filename=dest.name,
        path=str(dest),
        type="venue_photo",
        description_raw=title or (venue and f"Venue photo — {venue}") or "venue photo",
        profile_id=profile_id,
        linked_venue=venue or None,
        linked_meet_ids=[run_id],
        source_url=source_url or direct_url,
        source_attribution=attribution or None,
        source_licence=licence or None,
        permission_status=str(body.get("permission_status") or "approved_public"),
        approval_status="approved",
    )
    asset = store.save(asset)
    return jsonify(
        {
            "ok": True,
            "asset": {
                "id": asset.id,
                "url": url_for("api_media_library_file", asset_id=asset.id),
                "label": title or venue or "venue photo",
            },
        }
    )


def api_element_suggestions(run_id: str, card_id: str):
    """Suggest elements that fit this card's moment (deterministic + AI blend)."""
    from mediahub.elements import search as _el_search

    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    profile_id = (run_data or {}).get("profile_id") or W._active_profile_id()
    facts = W._card_context_facts(run_data, card_id)
    role_vars = W._elements_role_vars(profile_id)
    suggested = _el_search.suggest_for_context(facts, profile_id=profile_id, limit=12)
    return jsonify(
        {
            "elements": [W._element_to_payload(el, role_vars, profile_id) for el in suggested],
            "context": facts,
        }
    )


def api_card_elements(run_id: str, card_id: str):
    """List, add, remove or clear the library elements painted on a card.

    Placements live on the card's persisted CreativeBrief (`elements` field);
    the next render picks them up via the elements sprint hook.
    """
    from flask import request as _req
    from mediahub.elements.catalog import get_element as _get_element
    from mediahub.elements.models import ElementPlacement

    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    bdict = W._latest_brief_for_card(run_id, card_id)
    if not bdict:
        return jsonify(
            {"error": "no_design", "user_message": "Create a graphic for this card first."}
        ), 409

    current = list(bdict.get("elements") or [])

    if _req.method == "GET":
        return jsonify({"elements": current})

    body = _req.get_json(silent=True) or {}
    if body.get("clear"):
        current = []
    elif "remove_index" in body:
        try:
            idx = int(body["remove_index"])
            if 0 <= idx < len(current):
                current.pop(idx)
        except (TypeError, ValueError):
            return jsonify({"error": "bad_index"}), 400
    else:
        element_id = str(body.get("element_id") or "").strip()
        if not element_id:
            return jsonify({"error": "no_element_id"}), 400
        profile_id = (run_data or {}).get("profile_id") or W._active_profile_id()
        if _get_element(element_id, profile_id) is None:
            return jsonify({"error": "unknown_element"}), 404
        placement = ElementPlacement.from_dict({**body, "element_id": element_id})
        if placement is None:
            return jsonify({"error": "bad_placement"}), 400
        if len(current) >= 12:
            return jsonify(
                {"error": "too_many", "user_message": "Up to 12 elements per card."}
            ), 409
        current.append(placement.to_dict())

    bdict["elements"] = current
    brief_id = str(bdict.get("id") or "").strip()
    if not brief_id:
        return jsonify({"error": "brief_unreadable"}), 500
    try:
        bdir = W.RUNS_DIR / run_id / "briefs"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / f"{brief_id}.json").write_text(
            json.dumps(bdict, indent=2, default=str), encoding="utf-8"
        )
    except OSError as e:
        return jsonify({"error": f"save_failed: {e}"}), 500
    return jsonify({"ok": True, "elements": current})


def api_create_graphic(run_id: str, card_id: str):
    """Render a visual for a single content item / recognition card."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import request as _req

    # Resolve run + card. Runs are stored as runs_v4/<run_id>.json;
    # also accept the legacy nested runs_v4/<run_id>/run.json layout.
    run_data = W._load_run(run_id)
    if run_data is None:
        run_dir = W.RUNS_DIR / run_id
        run_json = run_dir / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    # Tenant isolation: even though the per-profile gate below
    # catches most cross-org access, an owned run could in theory
    # have a derived profile_id that slips through if club_filter
    # falls back to a foreign-club code. Gate on the run's stored
    # owner first.
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    # Find the matching card / achievement
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    target = None
    for ra in ranked:
        ach = ra.get("achievement") or {}
        if ach.get("swim_id") == card_id or ra.get("id") == card_id:
            target = ra
            break
    if target is None:
        # Fallback: try cards array
        for c in run_data.get("cards") or []:
            if c.get("swim_id") == card_id or c.get("id") == card_id:
                target = {"achievement": c}
                break
    if target is None:
        return jsonify({"error": "card_not_found"}), 404

    # Build a content_item shape that creative_brief expects
    ach = target.get("achievement") or {}
    item = {
        "id": ach.get("swim_id") or card_id,
        "swim_id": ach.get("swim_id") or card_id,
        "achievement": ach,
        "post_angle": ach.get("post_angle") or _req.json.get("post_angle")
        if _req.is_json
        else ach.get("post_angle"),
        "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
        "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
    }

    # V8.1: profile_id is optional. If the user used the two-step upload flow with
    # only a club_filter + per-run brand kit (no saved profile), derive a virtual
    # profile id from the club_filter so brand-kit + media-library lookups still work.
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
    # Slugify
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    # Defense-in-depth: if this run is pinned to an organisation, only
    # that organisation's session may pull its library into the render.
    # Run-scoped synthetic profiles are still allowed for everyone.
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)

    # PC.8: deterministic sponsor rotation. When the org has a sponsor
    # registry, the card's (run, card) identity decides which active
    # sponsor's slot it carries — the same seed on every re-render, so
    # stills and motion agree. Registry-only here: legacy single
    # sponsor_name profiles keep their old behaviour (sponsor appears
    # only on the dedicated sponsor-variant surface).
    rotated_sponsor = None
    try:
        from mediahub.club_platform.sponsors import sponsor_for_card as _sponsor_for_card

        _sponsor_profile = W.load_profile(profile_id)
        if _sponsor_profile is not None:
            rotated_sponsor = _sponsor_for_card(
                _sponsor_profile, run_id, card_id, include_legacy=False
            )
    except Exception:
        rotated_sponsor = None
    rotated_sponsor_name = (rotated_sponsor or {}).get("name", "")

    def _record_sponsor_exposure(surface: str = "still") -> None:
        if not rotated_sponsor:
            return
        try:
            from mediahub.club_platform.sponsors import record_exposure

            record_exposure(
                profile_id,
                run_id=run_id,
                card_id=card_id,
                sponsor_id=rotated_sponsor["sponsor_id"],
                sponsor_name=rotated_sponsor["name"],
                surface=surface,
            )
        except Exception:
            pass  # exposure accounting must never break a render

    # Pull media library assets for this profile
    media_assets = []
    try:
        from mediahub.media_library.photo_edit import asset_dicts_for_render

        store = W._v8_get_media_store()
        assets = store.list(profile_id=profile_id)
        media_assets = asset_dicts_for_render(assets, store)
    except Exception:
        pass

    # PC.8: the rotated sponsor's logo (a media-library asset) rides the
    # sponsor strip when the registry entry references one.
    rotated_sponsor_logo_path = None
    if rotated_sponsor and rotated_sponsor.get("logo_asset_id"):
        for _a in media_assets:
            _ad = _a if isinstance(_a, dict) else {}
            if str(_ad.get("id")) == str(rotated_sponsor["logo_asset_id"]):
                rotated_sponsor_logo_path = _ad.get("path") or _ad.get("file_path")
                break

    # Accept optional format from JSON body or query string
    req_fmt = None
    try:
        if _req.is_json and _req.json:
            req_fmt = _req.json.get("format")
    except Exception:
        req_fmt = None
    if not req_fmt:
        req_fmt = _req.args.get("format")
    formats_kw = [req_fmt] if req_fmt else None

    # User photo choice for THIS graphic — overrides the automatic scorer
    # so the user decides exactly which uploaded photo lands on which card.
    #   asset_id=<id>  → force that library photo as the hero (photo-led layout)
    #   no_photo=1     → force a text-led, photo-free treatment
    chosen_asset_id = None
    force_no_photo = False
    try:
        if _req.is_json and _req.json:
            chosen_asset_id = (_req.json.get("asset_id") or "").strip() or None
            # HTML checkbox truthiness — the form value is "on" or absent, never a
            # NaN literal; bool() is the intended presence test. (pre-existing web.py
            # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
            # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
            force_no_photo = bool(_req.json.get("no_photo"))
    except Exception:
        pass
    if chosen_asset_id is None:
        chosen_asset_id = (_req.args.get("asset_id") or "").strip() or None
    if not force_no_photo:
        force_no_photo = (_req.args.get("no_photo") or "").lower() in ("1", "true", "yes")

    # UI 1.18 — inspector overrides (accent swatch / manual crop / sponsor
    # toggle). Persisted per-card in the workflow store under ``insp.*`` keys
    # (no new persistence layer — same edited_captions bag as captions), so
    # a tweak made before approval also re-applies on every later render
    # (content builder, regenerate-variants and the sponsor variant — which
    # drops ``hide_sponsor``, its whole job being the sponsor slot — included).
    # An explicit value in *this* request wins over the stored one; both are
    # honoured deterministically by ``create_visual_for_item`` (the AI
    # director still picks the design).
    _persisted_insp = W._inspector_overrides_for_card(run_id, card_id)
    user_overrides = dict(_persisted_insp)

    def _ov(key):
        v = None
        try:
            if _req.is_json and _req.json and _req.json.get(key) is not None:
                v = _req.json.get(key)
        except Exception:
            v = None
        if v is None:
            v = _req.args.get(key)
        return v

    _req_accent = _ov("accent")
    if _req_accent is not None:
        user_overrides["accent"] = str(_req_accent).strip()
    _req_focus = _ov("focus")
    if _req_focus is not None:
        user_overrides["photo_pos"] = str(_req_focus).strip()
    _req_hide_sponsor = _ov("hide_sponsor")
    if _req_hide_sponsor is not None:
        user_overrides["hide_sponsor"] = str(_req_hide_sponsor).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
    # ``no_photo`` is parsed above. Fold the persisted default in so the
    # inspector's "Show photo" toggle sticks across renders — but only when
    # THIS request didn't speak to it (an explicit request value always
    # wins, true or false).
    if _ov("no_photo") is None and not force_no_photo and _persisted_insp.get("no_photo"):
        force_no_photo = True
        chosen_asset_id = None

    forced_hero_asset_id = None
    choice_allowed_families = None
    if force_no_photo:
        chosen_asset_id = None
        # Single source of truth: the generator's text-led family set, so a
        # new text-led family is honoured by this no-photo gate automatically.
        from mediahub.creative_brief.generator import _TEXT_LED_FAMILIES

        choice_allowed_families = sorted(_TEXT_LED_FAMILIES)
    elif chosen_asset_id:
        forced_hero_asset_id = chosen_asset_id
        # Constrain to photo-capable families so the chosen photo actually
        # appears (a text-led family would ignore it).
        choice_allowed_families = [
            "individual_hero",
            "big_number_hero",
            "story_card",
            "athlete_spotlight",
            "medal_card",
            "action_photo_hero",
        ]

    # The photos the user can pick from for this card (their org's library
    # images), surfaced in the panel as a per-graphic picker. Photos the
    # library remembers as being OF this card's athlete (linked when
    # they were uploaded on an earlier card/meet) are flagged and
    # sorted first, so next meet the right face is one click away.
    # Canonical types only — legacy values ("athlete_photo", "action",
    # "podium", …) are alias-mapped at deserialise (MediaAsset.from_dict),
    # so store-read assets never carry them.
    _photo_types = {
        "athlete_action",
        "athlete_headshot",
        "team_photo",
        "venue_photo",
        "other",
    }
    _card_athlete = str(ach.get("swimmer_name") or "").strip()
    _card_athlete_lc = _card_athlete.lower()
    available_photos = []
    for _ad in media_assets:
        _d = _ad if isinstance(_ad, dict) else {}
        if _d.get("id") and _d.get("type") in _photo_types:
            _names = _d.get("linked_athlete_names") or []
            _label = (_names[0] if _names else "") or str(_d.get("type") or "").replace("_", " ")
            _suggested = bool(
                _card_athlete_lc
                and any(
                    _card_athlete_lc == str(n).strip().lower()
                    or _card_athlete_lc in str(n).strip().lower()
                    or str(n).strip().lower() in _card_athlete_lc
                    for n in _names
                    if str(n).strip()
                )
            )
            available_photos.append(
                {
                    "id": _d["id"],
                    "url": url_for("api_media_library_file", asset_id=_d["id"]),
                    "label": _label,
                    "suggested": _suggested,
                }
            )
    available_photos.sort(key=lambda p: (not p["suggested"], p["label"]))

    # M24 — race clips linked to THIS card (this run + this athlete),
    # surfaced as a 'race clip' chip beside the photo picker. Read fresh
    # from the store so duration / permission / poster reflect ingest's
    # media_meta rather than the render-shaped asset dicts.
    race_clips = []
    try:
        _store_rc = W._v8_get_media_store()
        for _fa in _store_rc.list(profile_id=profile_id, asset_type="footage", limit=100):
            if run_id not in (_fa.linked_meet_ids or []):
                continue
            _fnames = [str(n).strip().lower() for n in (_fa.linked_athlete_names or [])]
            if _card_athlete_lc and not any(
                _card_athlete_lc == n or _card_athlete_lc in n or n in _card_athlete_lc
                for n in _fnames
            ):
                continue
            _fmeta = _fa.media_meta if isinstance(_fa.media_meta, dict) else {}
            race_clips.append(
                {
                    "id": _fa.id,
                    "filename": _fa.filename,
                    "duration_ms": _fmeta.get("duration_ms", 0),
                    "permission_status": _fa.permission_status,
                    "usable": _fa.is_usable_for_post(),
                    "poster_url": (
                        url_for("api_media_library_file", asset_id=_fa.id, poster=1)
                        if _fmeta.get("poster")
                        else ""
                    ),
                }
            )
    except Exception:
        race_clips = []

    # Gen v2 Tier B: ``?candidates=N`` (or JSON ``{"candidates": N}``)
    # renders a ranked candidate POOL — N design-spec-directed
    # alternatives, each carrying a deterministic brand-compliance
    # score — and returns the shortlist additively. The legacy
    # single-visual fields are populated from the top candidate so
    # existing callers are unaffected; omitting the param keeps the
    # classic single render below byte-for-byte.
    pool_n = 0
    try:
        if _req.is_json and _req.json and _req.json.get("candidates") is not None:
            pool_n = int(_req.json.get("candidates"))
    except Exception:
        pool_n = 0
    if not pool_n:
        try:
            pool_n = int(_req.args.get("candidates", "0"))
        except (TypeError, ValueError):
            pool_n = 0
    if pool_n > 1 and W._v8_create_candidate_pool is not None:
        _pool_history = W._v9_load_variation_history(run_id, card_id)
        _pool_recent = _pool_history.get("signatures", [])[-6:]
        try:
            with W._render_slot("graphic", card_id, timeout=W._RENDER_TRY_TIMEOUT):
                pool = W._v8_create_candidate_pool(
                    item,
                    brand_kit,
                    profile_id=profile_id,
                    run_id=run_id,
                    n=min(pool_n, 5),
                    media_assets=media_assets,
                    recent_signatures=_pool_recent,
                    forced_hero_asset_id=forced_hero_asset_id,
                    formats=formats_kw,
                    sponsor_name=rotated_sponsor_name,
                    sponsor_logo_path=rotated_sponsor_logo_path,
                )
        except W._RenderBusy:
            return W._render_busy_response("graphic")
        except Exception as e:
            return jsonify({"error": f"render_failed: {e}"}), 500
        cands = pool.get("candidates") or []
        if not cands:
            return jsonify({"error": "pool_failed", "detail": (pool.get("errors") or [])[:3]}), 500
        top = cands[0]
        top_brief = top.get("brief") or {}
        new_sig = top_brief.get("variation_signature") or ""
        if new_sig:
            W._v9_save_variation_history(
                run_id, card_id, new_sig, top_brief.get("primary_hook") or ""
            )
        if top.get("visuals"):
            _record_sponsor_exposure()
        return jsonify(
            {
                "ok": True,
                "ai_directed": bool(top.get("ai_directed")),
                "variation_signature": new_sig,
                "explanation": W._build_card_explanation(target),
                "available_photos": available_photos,
                "race_clips": race_clips,
                "chosen_asset_id": chosen_asset_id,
                "no_photo": force_no_photo,
                "card_athlete": _card_athlete,
                # Legacy single-visual fields ← the top-ranked candidate.
                "visuals": top.get("visuals") or [],
                "brief": top_brief,
                "evaluation": pool.get("evaluation"),
                "errors": pool.get("errors") or None,
                # Additive Tier B surface.
                "candidates": cands,
                "pool_metrics": pool.get("pool_metrics") or {},
            }
        )

    # V9 variation overhaul: every regenerate produces a fresh random
    # creative direction (different layout family + background style +
    # accent decoration + typography pair + composition + headline
    # hook). When an AI provider is configured we ask the AI to pick
    # the direction; otherwise the random profile picker fills it.
    # The route persists the last few signatures + hooks per card so
    # the AI / picker actively avoids repeating itself.
    #
    # Stability mode for callers that need it (page reload, debug):
    #   ?stable=true       → use the legacy deterministic seed
    #   ?variation_seed=N  → force a specific integer seed
    seed_raw = _req.args.get("variation_seed")
    stable_mode = (_req.args.get("stable") or "").lower() in ("1", "true", "yes")
    # None = no explicit seed: the v2 floor derives a stable per-card seed
    # from the card id, rotated past recents. An explicit integer —
    # including 0 — is an exact, reproducible archetype pick.
    variation_seed = None
    variation_profile = None
    ai_directed = False

    history = W._v9_load_variation_history(run_id, card_id)
    recent_sigs = history.get("signatures", [])[-6:]
    recent_hooks = history.get("hooks", [])[-6:]

    if seed_raw not in (None, ""):
        try:
            variation_seed = int(seed_raw)
        except (TypeError, ValueError):
            variation_seed = None
    elif stable_mode:
        try:
            from mediahub.creative_brief.generator import auto_variation_seed_for

            variation_seed = auto_variation_seed_for(
                item.get("swim_id") or item.get("id") or card_id
            )
        except Exception:
            variation_seed = 1
    else:
        # Fresh direction. The v2 design-spec director runs inside
        # generate() when a provider is configured; otherwise the
        # deterministic archetype rotation (seeded per card, walking
        # past recent_signatures) provides the variety — the honest
        # no-LLM floor, never a random tuple.
        ai_directed = True  # generate() will try the AI director first

    try:
        with W._render_slot("graphic", card_id, timeout=W._RENDER_TRY_TIMEOUT):
            res = W._v8_create_visual_for_item(
                item,
                brand_kit,
                profile_id=profile_id,
                run_id=run_id,
                media_assets=media_assets,
                formats=formats_kw,
                variation_seed=variation_seed,
                variation_profile=variation_profile,
                use_ai_director=ai_directed,
                recent_signatures=recent_sigs,
                recent_hooks=recent_hooks,
                allowed_families=choice_allowed_families,
                forced_hero_asset_id=forced_hero_asset_id,
                sponsor_name=rotated_sponsor_name,
                sponsor_logo_path=rotated_sponsor_logo_path,
                user_overrides=user_overrides,
                # M2 handoff — the pack path's burst-family threading, now on
                # the per-card route too: this render avoids near-frames of
                # photos already used by the run's OTHER rendered cards.
                recent_asset_families=W._recent_asset_families_for_run(
                    run_id, card_id, media_assets
                ),
            )
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify({"error": f"render_failed: {e}"}), 500
    if res.get("visuals"):
        _record_sponsor_exposure()
    # V9: Attach the "Why this card?" explanation so JSON consumers can
    # render the same plain-English reasoning the UI shows.
    explanation = W._build_card_explanation(target)
    # Persist the new variation signature + hook so the next
    # regenerate avoids it.
    brief_d = res.get("brief") or {}
    new_sig = brief_d.get("variation_signature") or ""
    new_hook = brief_d.get("primary_hook") or ""
    if new_sig:
        W._v9_save_variation_history(run_id, card_id, new_sig, new_hook)
    # Include the seed in the response so the UI / debugging can see it.
    return jsonify(
        {
            "ok": True,
            "variation_seed": variation_seed,
            "variation_signature": new_sig,
            "ai_directed": bool(brief_d.get("ai_directed")),
            "explanation": explanation,
            # Per-graphic photo picker state.
            "available_photos": available_photos,
            "race_clips": race_clips,
            "chosen_asset_id": chosen_asset_id,
            "no_photo": force_no_photo,
            "card_athlete": _card_athlete,
            # Roadmap 1.2 — deep-link the chosen photo into the image studio
            # so a volunteer can fix it up (fill/erase/expand/upscale) without
            # leaving the card flow. Empty unless a real library photo is on
            # the card; built with url_for so the path is never hardcoded.
            "studio_url": (
                url_for("image_studio_page", asset_id=chosen_asset_id) if chosen_asset_id else ""
            ),
            # UI 1.18 inspector state: the brand-locked swatches it may pick
            # from, plus the overrides actually in force for this render.
            "brand_swatches": W._brand_swatches(brand_kit),
            "inspector": user_overrides,
            **res,
        }
    )


def api_sponsor_variant_job(run_id: str, card_id: str):
    """D-32: background render + caption for the sponsor-variant page;
    ``202`` + ``{job_id, poll_url}``.

    The synchronous page GET used to hold the HTTP connection for the
    whole visual render *and* an LLM caption call. Fail-fast gates
    (tenant, sponsor configured) stay in the request thread; the worker
    does the heavy work and the shared ``api_reel_job_status`` route
    reports ``image_url`` / ``caption`` (or their plain-copy failure
    messages — raw exceptions go to the server log only).
    """
    run_data, target = W._load_run_for_card(run_id, card_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        run_data = None
        target = None
    if run_data is None or target is None:
        return jsonify({"error": "run_not_found"}), 404

    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or ""
    profile = W.load_profile(profile_id) if profile_id else None
    if profile is None:
        profile = W._active_profile()
    _rotated = None
    if profile is not None:
        try:
            from mediahub.club_platform.sponsors import sponsor_for_card as _sponsor_for_card

            _rotated = _sponsor_for_card(profile, run_id, card_id)
        except Exception:
            _rotated = None
    sponsor_name = (_rotated or {}).get("name", "").strip()
    if not sponsor_name:
        return (
            jsonify(
                {
                    "error": "no_sponsor",
                    "user_message": (
                        "No sponsor is configured for this organisation — "
                        "add one on the Organisation page first."
                    ),
                }
            ),
            400,
        )
    sponsor_id = (_rotated or {}).get("sponsor_id", "")
    resolved_pid = profile_id or "_run_" + run_id
    resolved_pid = re.sub(r"[^a-z0-9_-]", "-", resolved_pid.lower()).strip("-") or (
        "_run_" + run_id
    )
    if not W._session_can_access_profile(resolved_pid):
        return jsonify({"error": "run_not_found"}), 404
    sidecar = W._sponsor_variant_sidecar(run_id, card_id)
    if sidecar is None:
        return jsonify({"error": "run_not_found"}), 404

    # Capture everything the worker needs at enqueue — it has no request
    # context (_active_profile_id() returns nothing on the thread).
    ach = target.get("achievement") or {}
    meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
    item = {
        "id": ach.get("swim_id") or card_id,
        "swim_id": ach.get("swim_id") or card_id,
        "achievement": ach,
        "post_angle": ach.get("post_angle"),
        "meet_name": meet_name,
        "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
    }
    brand_kit = None
    media_assets: list[dict] = []
    if W._v8_ok:
        brand_kit = W._v8_brand_kit_for(resolved_pid, run_id=run_id)
        try:
            from mediahub.media_library.photo_edit import asset_dicts_for_render

            store = W._v8_get_media_store()
            assets = store.list(profile_id=resolved_pid)
            media_assets = asset_dicts_for_render(assets, store)
        except Exception:
            pass
    # UI 1.18 — honour the card's persisted inspector overrides, minus
    # hide_sponsor: this surface's whole job is showing the sponsor slot.
    _insp = {
        k: v
        for k, v in W._inspector_overrides_for_card(run_id, card_id).items()
        if k != "hide_sponsor"
    }

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "sponsor-variant",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "visual_id": "",
        "format_name": "",
        "png_path": "",
        "image_message": "",
        "caption": "",
        "caption_message": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            with W._job_heartbeat(job):
                # ---- 1. Sponsor-branded visual (render-engine bound) ----
                if W._v8_ok and W._v8_create_visual_for_item is not None:
                    try:
                        # A 202-accepted background job queues for the
                        # slot (like the render-all batch worker) rather
                        # than borrowing the request threads' fast-fail
                        # budget.
                        with W._render_slot(
                            "graphic", f"sponsor:{card_id}", timeout=W._RENDER_QUEUE_TIMEOUT
                        ):
                            res = W._v8_create_visual_for_item(
                                item,
                                brand_kit,
                                profile_id=resolved_pid,
                                run_id=run_id,
                                media_assets=media_assets,
                                sponsor_name=sponsor_name,
                                user_overrides=_insp,
                            )
                        visuals = res.get("visuals") or []
                        v0 = visuals[0] if visuals else {}
                        vid = v0.get("id") or v0.get("brief_id") or ""
                        if vid:
                            job["visual_id"] = vid
                            job["format_name"] = v0.get("format_name") or "feed_portrait"
                            job["png_path"] = str(v0.get("file_path") or "")
                            if sponsor_id:
                                try:
                                    from mediahub.club_platform.sponsors import (
                                        record_exposure as _rec_exposure,
                                    )

                                    _rec_exposure(
                                        resolved_pid,
                                        run_id=run_id,
                                        card_id=card_id,
                                        sponsor_id=sponsor_id,
                                        sponsor_name=sponsor_name,
                                        surface="sponsor_variant",
                                    )
                                except Exception:
                                    pass
                        else:
                            W.log.warning(
                                "sponsor variant %s/%s: no visual produced: %s",
                                run_id,
                                card_id,
                                (res.get("errors") or ["no visuals returned"])[0],
                            )
                            job["image_message"] = "The graphic couldn't be rendered — try again."
                    except W._RenderBusy:
                        job["image_message"] = (
                            "Another render is in progress — try again in a minute."
                        )
                    except Exception:
                        W.log.warning(
                            "sponsor variant %s/%s: render failed",
                            run_id,
                            card_id,
                            exc_info=True,
                        )
                        job["image_message"] = "The graphic couldn't be rendered — try again."
                else:
                    job["image_message"] = "Graphic rendering isn't available on this deployment."
                W._variant_job_save(job)
                # ---- 2. Sponsor-acknowledging caption (LLM) ----
                try:
                    from mediahub.brand.sponsor import generate_sponsor_caption

                    job["caption"] = generate_sponsor_caption(ach, profile=profile)
                except Exception as e:
                    # Detect "no LLM provider configured" by class name
                    # rather than importing ClaudeUnavailableError directly
                    # — keeps this surface resilient if the module moves.
                    if type(e).__name__ == "ClaudeUnavailableError":
                        job["caption_message"] = (
                            "AI captions are unavailable on this deployment. "
                            "The sponsor-branded graphic is still ready to "
                            "download. Contact your administrator to enable "
                            "AI captions."
                        )
                    else:
                        W.log.warning(
                            "sponsor variant %s/%s: caption failed",
                            run_id,
                            card_id,
                            exc_info=True,
                        )
                        job["caption_message"] = "The caption couldn't be generated — try again."
            job["status"] = "done"
            # A successful render is cached via the sidecar so the next
            # page load shows it instantly, without a new job.
            if job["visual_id"]:
                try:
                    sidecar.parent.mkdir(parents=True, exist_ok=True)
                    # A concurrent page GET must never read a torn sidecar
                    # (torn read = cache miss = duplicate auto-start
                    # render) — write via unique tmp + atomic os.replace,
                    # the _variant_job_save idiom.
                    _sc_tmp = sidecar.with_suffix(f".{W.uuid.uuid4().hex[:8]}.tmp")
                    _sc_tmp.write_text(
                        json.dumps(
                            {
                                "visual_id": job["visual_id"],
                                "format_name": job["format_name"],
                                "png_path": job["png_path"],
                                "caption": job["caption"],
                                "caption_message": job["caption_message"],
                                "sponsor_name": sponsor_name,
                                "created_at": time.time(),
                            }
                        ),
                        encoding="utf-8",
                    )
                    os.replace(_sc_tmp, sidecar)
                except Exception:
                    W.log.warning(
                        "sponsor variant %s/%s: sidecar write failed",
                        run_id,
                        card_id,
                        exc_info=True,
                    )
        except Exception:
            # Raw exception text stays in the server log — the client
            # only ever sees the plain user_message.
            W.log.warning("sponsor variant %s/%s: job failed", run_id, card_id, exc_info=True)
            job["status"] = "error"
            job["error"] = "sponsor_variant_failed"
            job["user_message"] = "The sponsor variant couldn't be generated — try again."
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"sponsor-variant-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_regenerate_graphic(run_id: str, card_id: str):
    """Same as create-graphic but explicit re-run for an existing card."""
    return api_create_graphic(run_id, card_id)


def api_regenerate_variants(run_id: str, card_id: str):
    """Produce 3 visibly-different design alternatives (V10: async).

    Validates the card, then hands off to a background job that
    renders three mutually-distinct variants sequentially. Returns
    ``{job_id, poll_url}`` (202) immediately; pass ``?sync=1`` for
    the legacy blocking response shape.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503

    # Resolve run + card the same way create-graphic does.
    run_data = W._load_run(run_id)
    if run_data is None:
        run_dir = W.RUNS_DIR / run_id
        run_json = run_dir / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    target = None
    for ra in ranked:
        ach = ra.get("achievement") or {}
        if ach.get("swim_id") == card_id or ra.get("id") == card_id:
            target = ra
            break
    if target is None:
        for c in run_data.get("cards") or []:
            if c.get("swim_id") == card_id or c.get("id") == card_id:
                target = {"achievement": c}
                break
    if target is None:
        return jsonify({"error": "card_not_found"}), 404

    ach = target.get("achievement") or {}
    item = {
        "id": ach.get("swim_id") or card_id,
        "swim_id": ach.get("swim_id") or card_id,
        "achievement": ach,
        "post_angle": ach.get("post_angle"),
        "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
        "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
    }

    # V8.1: profile_id optional; fall back to club_filter / synthetic id
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    # Defense-in-depth: same per-org gate as create-graphic.
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)

    media_assets = []
    try:
        from mediahub.media_library.photo_edit import asset_dicts_for_render

        store = W._v8_get_media_store()
        assets = store.list(profile_id=profile_id)
        media_assets = asset_dicts_for_render(assets, store)
    except Exception:
        pass

    # Honour the per-graphic photo choice so the three variants keep the
    # photo the user picked (just varying the rest of the treatment).
    _chosen = None
    _nop = False
    try:
        if request.is_json and request.json:
            _chosen = (request.json.get("asset_id") or "").strip() or None
            # HTML checkbox truthiness — the form value is "on" or absent, never a
            # NaN literal; bool() is the intended presence test. (pre-existing web.py
            # body exposed to semgrep by the finding-#15 carve; behaviour unchanged.)
            # nosemgrep: python.flask.security.injection.nan-injection.nan-injection
            _nop = bool(request.json.get("no_photo"))
    except Exception:
        pass
    # UI 1.18 — persisted inspector overrides (accent swatch / manual crop
    # / sponsor toggle) apply to variant renders too, so a saved tweak
    # doesn't silently vanish when the user asks for alternatives.
    _persisted_insp = W._inspector_overrides_for_card(run_id, card_id)
    _forced_asset = None
    _choice_families = None
    if _nop:
        # Single source of truth: the generator's text-led family set (same
        # gate as the create-graphic route's no-photo path).
        from mediahub.creative_brief.generator import _TEXT_LED_FAMILIES

        _choice_families = sorted(_TEXT_LED_FAMILIES)
    elif _chosen:
        _forced_asset = _chosen
        _choice_families = [
            "individual_hero",
            "big_number_hero",
            "story_card",
            "athlete_spotlight",
            "medal_card",
            "action_photo_hero",
        ]

    # V10: distinct directions, background rendering, honest progress.
    #
    # Legacy behaviour (and why it failed):
    #   * three parallel threads each called the AI director with an
    #     IDENTICAL prompt — the model returned the same direction
    #     three times, and because the AI direction WINS inside
    #     generate(), the pre-built distinct random profiles were
    #     silently discarded. Users got three near-identical cards.
    #   * the request blocked for all three renders (60-120s on the
    #     single-CPU box) while the UI promised "10-30 seconds".
    #
    # Now: ONE batch AI call returns three mutually-distinct
    # directions (random profiles fill any gap), each variant renders
    # sequentially in a daemon thread with use_ai_director=False so
    # its direction can't be overridden, a final guard re-rolls any
    # duplicate signature, and the route returns a job id the UI polls.
    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "status": "running",
        "variants": [],
        "total": 3,
        "done": 0,
        "error": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        # v2 (SEQ-3 cutover): the three variants are three distinct
        # DesignSpecs — ONE batch director call when a provider is
        # configured, the deterministic archetype walk as the floor.
        # Distinctness is by construction (each spec pins a different
        # archetype), so the old signature re-roll guard is gone.
        from mediahub.creative_brief.design_spec import normalise as _ds_normalise
        from mediahub.creative_brief.generator import auto_variation_seed_for
        from mediahub.graphic_renderer import archetypes as _arch

        try:
            history = W._v9_load_variation_history(run_id, card_id)
            recent_sigs = history.get("signatures", [])[-6:]
            angle = item.get("post_angle") or ""
            names = _arch.list_archetypes() if _arch.is_enabled() else []
            token_roles = list(_arch.TOKEN_ROLES)
            recent_archetypes = [s.split("|", 1)[0] for s in recent_sigs if s]

            specs: list[Any] = []
            if names:
                try:
                    from mediahub.creative_brief.ai_director import ai_design_specs

                    specs = list(
                        ai_design_specs(
                            content_item=item,
                            brand_kit=brand_kit,
                            archetypes=names,
                            token_roles=token_roles,
                            angle=angle,
                            recent_archetypes=recent_archetypes,
                            count=3,
                        )
                        or []
                    )[:3]
                except Exception as e:
                    W.log.warning("variants %s: batch specs failed: %s", job_id[:8], e)
                    specs = []
                base_seed = auto_variation_seed_for(card_id)
                used = [s.archetype for s in specs]
                while len(specs) < 3:
                    arch_name = _arch.pick_archetype_avoiding(base_seed, used + recent_archetypes)
                    if arch_name is None:
                        break
                    specs.append(
                        _ds_normalise(
                            {"archetype": arch_name},
                            archetypes=names,
                            token_roles=token_roles,
                        )
                    )
                    used.append(arch_name)
            # Kill-switch / no-archetype fallback: render the three
            # variants through the plain v1 path (spec=None) — the brief
            # generator then keeps the legacy family; they differ by the
            # per-variant render only. This path exists so the variants
            # button still works with MEDIAHUB_GEN_V2=0.
            spec_slots: list[Any] = specs if specs else [None, None, None]

            sigs_so_far = list(recent_sigs)
            for idx, spec in enumerate(spec_slots, start=1):
                entry: dict = {
                    "seed": idx,
                    "option": idx,
                    "variation_signature": "",
                    "visual": None,
                    "visuals": [],
                    "brief": None,
                    "errors": [],
                }
                try:
                    with W._render_slot(
                        "variant", f"{card_id}#{idx}", timeout=W._RENDER_QUEUE_TIMEOUT
                    ):
                        res = W._v8_create_visual_for_item(
                            item,
                            brand_kit,
                            profile_id=profile_id,
                            run_id=run_id,
                            media_assets=media_assets,
                            # Picker preview only — the other formats
                            # render on demand after "Pick this one".
                            # 3 variants x 1 format, not 3 x 3.
                            formats=["feed_portrait"],
                            # The direction is already fixed per-variant
                            # (one batch call upstream); letting the
                            # director run again here is exactly the
                            # convergence bug the batch call replaced.
                            design_spec=spec,
                            use_ai_director=False,
                            recent_signatures=sigs_so_far,
                            allowed_families=_choice_families,
                            forced_hero_asset_id=_forced_asset,
                            user_overrides=_persisted_insp,
                        )
                    visuals = res.get("visuals") or []
                    primary = next(
                        (v for v in visuals if v.get("format_name") == "feed_portrait"),
                        visuals[0] if visuals else None,
                    )
                    brief_d = res.get("brief") or {}
                    entry.update(
                        {
                            "variation_signature": brief_d.get("variation_signature", ""),
                            "visual": primary,
                            "visuals": visuals,
                            "brief": brief_d,
                            "errors": res.get("errors") or [],
                        }
                    )
                    # Persist immediately so the NEXT regenerate avoids
                    # these directions even if the user never picks one,
                    # and feed it back into THIS job's avoid-list so the
                    # fallback (spec=None) path can't repeat a signature.
                    new_sig = brief_d.get("variation_signature") or ""
                    if new_sig:
                        sigs_so_far.append(new_sig)
                        W._v9_save_variation_history(
                            run_id, card_id, new_sig, brief_d.get("primary_hook") or ""
                        )
                except W._RenderBusy:
                    entry["errors"] = ["renderer_busy: no render slot freed up in time"]
                except Exception as e:
                    entry["errors"] = [str(e)]
                job["variants"].append(entry)
                job["done"] = idx
                W._variant_job_save(job)
            if any(v.get("visual") for v in job["variants"]):
                job["status"] = "done"
            else:
                job["status"] = "error"
                job["error"] = (
                    "; ".join(e for v in job["variants"] for e in (v.get("errors") or []))
                    or "all variants failed"
                )
            W._variant_job_save(job)
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            W._variant_job_save(job)
            W.log.exception("variants %s: job crashed", job_id[:8])

    # ?sync=1 keeps the legacy blocking contract for tests/scripts.
    if (request.args.get("sync") or "").lower() in ("1", "true", "yes"):
        _worker()
        return jsonify(
            {
                "ok": job["status"] != "error",
                "job_id": job_id,
                "variants": job["variants"],
                "error": job["error"] or None,
            }
        )
    W.threading.Thread(target=_worker, name=f"variants-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_variant_job_status", job_id=job_id),
                "total": 3,
            }
        ),
        202,
    )


def api_card_motion(run_id: str, card_id: str):
    """Render (or serve cached) MP4 story for a single card.

    Lazy: returns the cached file on cache hit; renders via Remotion on
    cache miss. Always serves the MP4 with the correct mime type so the
    UI can use <video src=&hellip;> or a direct download.

    ``?format=story|square|landscape`` picks the output cut (default
    story, 1080×1920). Synchronous — the UI now prefers the async
    ``motion-job`` route (M32), which survives proxy timeouts on cold
    renders; this route remains for API callers and cache-hit fetches.
    """
    from flask import send_file

    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    inputs, err = W._assemble_card_motion_inputs(run_id, card_id)
    if err is not None:
        return err

    try:
        with W._render_slot("motion", card_id, timeout=W._RENDER_TRY_TIMEOUT):
            mp4 = _motion.render_story_card(
                inputs["card"],
                inputs["brand_kit"],
                inputs["out_path"],
                variation_seed=inputs["variation_seed"],
                brief=inputs["brief"],
                format_name=inputs["format"],
            )
    except W._RenderBusy:
        return W._render_busy_response("motion")
    except RuntimeError as e:
        _payload = W._motion_error_payload(e)
        return jsonify(_payload), 503 if _payload.get("kind") == "infra_missing" else 500
    except Exception as e:
        _payload = W._motion_error_payload(e)
        return jsonify(_payload), 503 if _payload.get("kind") == "infra_missing" else 500

    if not Path(mp4).exists():
        return jsonify(
            {
                "error": "render_failed",
                "kind": "internal",
                "detail": "mp4 missing after render",
                "user_message": (
                    "Motion video rendering didn't produce an output file. "
                    "This is usually a transient issue — try again in a few seconds."
                ),
            }
        ), 500
    return send_file(
        str(mp4),
        mimetype="video/mp4",
        as_attachment=False,
        download_name=inputs["out_name"],
    )


def api_card_motion_job(run_id: str, card_id: str):
    """Kick off a background per-card motion render (M32); ``202`` +
    ``{job_id, poll_url}``.

    The synchronous ``/motion`` route holds the HTTP connection for the
    whole 30–90s cold render — the exact proxy-timeout failure the reel
    already fixed with ``/reel-job``. Same cure, same disk-backed job
    store: render in a daemon thread, poll ``api_reel_job_status``, then
    stream the finished MP4 from ``motion-file``.
    """
    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    inputs, err = W._assemble_card_motion_inputs(run_id, card_id)
    if err is not None:
        return err

    # url_for needs the request context — resolve before the thread.
    _file_kwargs = {"run_id": run_id, "card_id": card_id}
    if inputs["format"] != _motion.DEFAULT_MOTION_FORMAT:
        _file_kwargs["format"] = inputs["format"]
    file_url = url_for("api_card_motion_file", **_file_kwargs)
    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "motion",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            with W._job_heartbeat(job):
                with W._render_slot("motion", card_id, timeout=W._RENDER_TRY_TIMEOUT):
                    mp4 = _motion.render_story_card(
                        inputs["card"],
                        inputs["brand_kit"],
                        inputs["out_path"],
                        variation_seed=inputs["variation_seed"],
                        brief=inputs["brief"],
                        format_name=inputs["format"],
                    )
            if not Path(mp4).exists():
                raise RuntimeError("mp4 missing after render")
            job["status"] = "done"
            job["video_url"] = file_url
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(
                    job.get("owner_pid") or "", run_id=run_id, label="motion"
                )
            except Exception:
                pass
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except Exception as e:
            _payload = W._motion_error_payload(e)
            job["status"] = "error"
            job["error"] = str(_payload.get("detail") or e)
            job["user_message"] = str(_payload.get("user_message") or "")
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_error(
                    job.get("owner_pid") or "",
                    "Motion render failed",
                    job["user_message"] or job["error"],
                    run_id=run_id,
                )
            except Exception:
                pass
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"motion-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_card_motion_batch_job(run_id: str, card_id: str):
    """Render every motion cut of one card in one background job (B-5);
    ``202`` + ``{job_id, poll_url}``.

    The reel already had an all-formats batch; per-card motion made the
    user click four separate renders. This mirrors ``api_run_reel_batch``
    over the motion job store: one job, kind ``motion-batch``, rendering
    story / portrait / square / landscape sequentially — each cut under
    its OWN render-slot acquire/release (never holding the gate across
    the batch, so a foreground render can interleave) — with per-cut
    progress in the job's ``total``/``done``/``current`` fields. On
    ``done``, ``video_urls`` maps each produced cut to its persistent
    ``motion-file`` URL and ``formats_failed`` carries the honest reason
    for any cut that could not render. The motion cache makes re-runs
    cheap: cuts already rendered complete near-instantly.
    """
    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    # Fail-fast gates (tenant / card / mix validation) stay synchronous.
    inputs, err = W._assemble_card_motion_inputs(run_id, card_id)
    if err is not None:
        return err

    out_dir = Path(inputs["out_path"]).parent
    # url_for needs the request context — resolve every cut's file URL
    # now, before the worker thread (which has none).
    file_urls: dict[str, str] = {}
    for fmt in _motion.MOTION_FORMATS:
        _file_kwargs = {"run_id": run_id, "card_id": card_id}
        if fmt != _motion.DEFAULT_MOTION_FORMAT:
            _file_kwargs["format"] = fmt
        file_urls[fmt] = url_for("api_card_motion_file", **_file_kwargs)

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "motion-batch",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "video_urls": {},
        "formats_failed": {},
        "total": len(_motion.MOTION_FORMATS),
        "done": 0,
        "current": "",
        "errors": {},
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        rendered: dict[str, str] = {}
        failed: dict[str, str] = {}
        busy_cuts: set[str] = set()
        try:
            with W._job_heartbeat(job):
                for fmt in _motion.MOTION_FORMATS:
                    job["current"] = fmt
                    W._variant_job_save(job)
                    out_name = (
                        f"{card_id}.mp4"
                        if fmt == _motion.DEFAULT_MOTION_FORMAT
                        else f"{card_id}_{fmt}.mp4"
                    )
                    try:
                        # Per-cut slot with the queue timeout (like the
                        # reel batch): wait a turn per item rather than
                        # hogging the render gate for the whole batch.
                        with W._render_slot(
                            "motion", f"{card_id}:{fmt}", timeout=W._RENDER_QUEUE_TIMEOUT
                        ):
                            mp4 = _motion.render_story_card(
                                inputs["card"],
                                inputs["brand_kit"],
                                out_dir / out_name,
                                variation_seed=inputs["variation_seed"],
                                brief=inputs["brief"],
                                format_name=fmt,
                            )
                        if not Path(mp4).exists():
                            raise RuntimeError("mp4 missing after render")
                        rendered[fmt] = file_urls[fmt]
                    except W._RenderBusy:
                        busy_cuts.add(fmt)
                        failed[fmt] = (
                            "Another video is rendering right now — try again in a minute."
                        )
                    except Exception as e:
                        # The honest per-cut reason (reel-batch parity):
                        # detail carries the real error; the generic
                        # user_message would hide which cut broke and why.
                        _payload = W._motion_error_payload(e)
                        failed[fmt] = str(
                            _payload.get("detail") or _payload.get("user_message") or e
                        )
                    job["done"] = int(job.get("done") or 0) + 1
                    job["video_urls"] = dict(rendered)
                    job["formats_failed"] = dict(failed)
                    job["errors"] = dict(failed)
                    W._variant_job_save(job)
            job["current"] = ""
            if not rendered:
                # CON2-3 — every cut hit a busy renderer: surface the
                # machine token the JS reattach branch keys on (reel-batch
                # parity), not the human copy as job["error"].
                if failed and set(failed) == busy_cuts:
                    raise W._RenderBusy()
                # Not one cut produced — surface an honest reason rather
                # than reporting a successful job with no video.
                reason = next(iter(failed.values()), "no motion formats could be rendered")
                raise RuntimeError(reason)
            job["status"] = "done"
            # Keep the legacy single field on the story cut (or the first
            # produced) so a single-format poller still gets a video_url.
            job["video_url"] = rendered.get(_motion.DEFAULT_MOTION_FORMAT) or next(
                iter(rendered.values()), ""
            )
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(
                    job.get("owner_pid") or "", run_id=run_id, label="motion (all formats)"
                )
            except Exception:
                pass
        except W._RenderBusy:
            # CON2-3 — the token in error (for the JS reattach branch),
            # the human copy in user_message: reel-batch parity.
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except Exception as e:
            _payload = W._motion_error_payload(e)
            job["status"] = "error"
            job["error"] = str(_payload.get("detail") or e)
            job["user_message"] = str(_payload.get("user_message") or "")
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_error(
                    job.get("owner_pid") or "",
                    "Motion batch render failed",
                    job["user_message"] or job["error"],
                    run_id=run_id,
                )
            except Exception:
                pass
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"motionbatch-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_card_motion_file(run_id: str, card_id: str):
    """Serve an already-rendered per-card MP4 — never triggers a render.

    The persistent counterpart of the blob URLs the old sync flow lost on
    navigation (M32). ``?format=`` picks the cut; ``?poster=1`` serves the
    poster-frame PNG sidecar written beside every rendered MP4.
    """
    from flask import send_file

    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    try:
        from mediahub.visual import motion as _motion

        fmt = (request.args.get("format") or _motion.DEFAULT_MOTION_FORMAT).strip().lower()
        valid = fmt in _motion.MOTION_FORMATS
    except Exception:
        fmt, valid = "story", True
    if not valid:
        return jsonify({"error": "bad_format"}), 400
    motion_dir = W.RUNS_DIR / run_id / "motion"
    name = f"{card_id}.mp4" if fmt == "story" else f"{card_id}_{fmt}.mp4"
    path = motion_dir / name
    # Defence-in-depth: the card id is a single URL segment, but never let
    # a crafted id escape the run's motion dir.
    try:
        if motion_dir.resolve() not in path.resolve().parents:
            return jsonify({"error": "motion_not_rendered"}), 404
    except OSError:
        return jsonify({"error": "motion_not_rendered"}), 404
    if not path.exists():
        return jsonify({"error": "motion_not_rendered"}), 404
    if (request.args.get("poster") or "").strip().lower() in {"1", "true", "yes"}:
        poster = path.with_suffix(".poster.png")
        if not poster.exists():
            return jsonify({"error": "poster_not_rendered"}), 404
        return send_file(
            str(poster),
            mimetype="image/png",
            as_attachment=False,
            download_name=poster.name,
        )
    return send_file(str(path), mimetype="video/mp4", as_attachment=False, download_name=name)


@W.require_run
def api_card_motion_manifest(run_id: str, card_id: str):
    """The motion render's explainability record — archetype, motion
    intent, mood, colour source, seed — written as a JSON sidecar beside
    every rendered MP4. 404 until the matching cut has been rendered."""
    try:
        from mediahub.visual import motion as _motion

        fmt = (request.args.get("format") or _motion.DEFAULT_MOTION_FORMAT).strip().lower()
        valid = fmt in _motion.MOTION_FORMATS
    except Exception:
        fmt, valid = "story", True
    if not valid:
        return jsonify({"error": "bad_format"}), 400
    name = f"{card_id}.json" if fmt == "story" else f"{card_id}_{fmt}.json"
    sidecar = W.RUNS_DIR / run_id / "motion" / name
    if not sidecar.exists():
        return jsonify({"error": "manifest_not_found", "detail": "render this cut first"}), 404
    try:
        return jsonify(json.loads(sidecar.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"error": f"manifest_unreadable: {e}"}), 500


def api_card_thumb(run_id: str, card_id: str):
    """A lazy, cached thumbnail of the card's real graphic (M29 / UX-1).

    The review page approves what will actually be posted, so each row
    shows the card's design instead of text-only triage. Resolution
    order — cheapest first, never a duplicate render:

    1. the per-run thumb manifest (``card_thumbs.json``, the /try demo's
       lazy render+cache pattern);
    2. any visual already persisted for this card under the run's
       ``visuals`` dir (served as-is, byte-identical);
    3. one ``feed_portrait`` render through the normal pipeline — stable
       per-card seed, the card's persisted Inspector overrides honoured —
       inside the existing ``_render_slot('graphic', …)`` gate. A
       saturated gate answers the standard 429 renderer-busy payload so
       the row can retry politely instead of hanging.
    """
    from flask import send_file

    if not W._v8_ok or W._v8_create_visual_for_item is None:
        return jsonify({"error": "v8_unavailable"}), 503

    run_data, target = W._load_run_for_card(run_id, card_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    if target is None:
        return jsonify({"error": "card_not_found"}), 404

    def _send_thumb(path: str):
        resp = send_file(str(path), mimetype="image/png")
        # Session-gated content — cacheable per browser, never shared.
        resp.headers["Cache-Control"] = "private, max-age=120"
        return resp

    # 1. Cached in the per-run thumb manifest?
    manifest_path = W.RUNS_DIR / run_id / "card_thumbs.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    cached = manifest.get(str(card_id))
    if cached and Path(cached).exists():
        return _send_thumb(cached)

    def _remember(path: str):
        manifest[str(card_id)] = str(path)
        try:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        except OSError:
            pass

    # 2. Already rendered for this card? Serve the existing PNG as-is.
    existing = W._visual_thumb_path(W._rendered_visuals_for_run(run_id).get(str(card_id)))
    if existing:
        _remember(existing)
        return _send_thumb(existing)

    # 3. First render — once, cached, deterministic (stable per-card seed;
    # the AI director is deliberately NOT engaged for a triage thumbnail).
    ach = target.get("achievement") or {}
    item = {
        "id": ach.get("swim_id") or card_id,
        "swim_id": ach.get("swim_id") or card_id,
        "achievement": ach,
        "post_angle": ach.get("post_angle"),
        "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
        "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
    }
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    try:
        brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)
    except Exception:
        brand_kit = None
    media_assets: list = []
    try:
        if W._v8_get_media_store is not None:
            from mediahub.media_library.photo_edit import asset_dicts_for_render

            _ml_store = W._v8_get_media_store()
            media_assets = asset_dicts_for_render(_ml_store.list(profile_id=profile_id), _ml_store)
    except Exception:
        media_assets = []
    try:
        from mediahub.creative_brief.generator import auto_variation_seed_for

        seed = auto_variation_seed_for(str(card_id))
    except Exception:
        seed = 1
    try:
        with W._render_slot("graphic", f"thumb:{card_id}", timeout=W._RENDER_TRY_TIMEOUT):
            res = W._v8_create_visual_for_item(
                item,
                brand_kit,
                profile_id=profile_id,
                run_id=run_id,
                media_assets=media_assets,
                formats=["feed_portrait"],
                variation_seed=seed,
                use_ai_director=False,
                user_overrides=W._inspector_overrides_for_card(run_id, card_id),
            )
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify({"error": f"render_failed: {e}"}), 503
    visuals = res.get("visuals") or []
    path = visuals[0].get("file_path") if visuals else None
    if not path or not Path(path).exists():
        return jsonify(
            {
                "error": "no_thumbnail",
                "detail": (res.get("errors") or ["no visual produced"])[:2],
            }
        ), 503
    _remember(path)
    return _send_thumb(path)


def api_card_reformat(run_id: str, card_id: str):
    """P6.1 format transformer — re-target an approved card to any format.

    Loads the card's most recent ``CreativeBrief`` (the approved design),
    re-lays it out for the target format via ``turn_into.transform_design``
    (the design-spec director with the deterministic per-aspect picker as
    the honest floor — never a fabricated layout), renders it at the
    format's canvas size through the existing ``graphic_renderer`` (which
    already adapts the composition to the aspect, so this re-lays-out rather
    than scaling), and serves the PNG directly.

    Query params:
      * ``format=<slug>``          — a catalogue format (see ``/api/formats``)
      * ``w=&h=&unit=px|mm|cm|in`` — a custom canvas size instead
      * ``blank=1``                — start on-brand from brand tokens, not
                                     from an approved design
      * ``ai=1``                   — let the director pick the re-layout
                                     (default: deterministic + cached)
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    from flask import send_file

    # Runs are stored flat (runs_v4/<id>.json); also accept the legacy
    # nested runs_v4/<id>/run.json layout (mirrors api_create_graphic).
    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception:
                return jsonify({"error": "run_not_found"}), 404
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    # Resolve the target format: a catalogue slug, or a custom canvas.
    from mediahub.club_platform import format_catalog as _fc

    fmt_slug = (request.args.get("format") or "").strip()
    w_raw = request.args.get("w")
    h_raw = request.args.get("h")
    spec = None
    try:
        if w_raw and h_raw:
            spec = _fc.custom_format(
                float(w_raw),
                float(h_raw),
                unit=(request.args.get("unit") or "px"),
                slug=(fmt_slug or "custom"),
            )
        elif fmt_slug:
            spec = _fc.format_for(fmt_slug)
    except (ValueError, TypeError) as e:
        return jsonify({"error": "bad_format", "user_message": str(e)}), 400
    if spec is None:
        return jsonify(
            {"error": "unknown_format", "user_message": "Pick a format from the catalogue."}
        ), 400

    # Profile + brand kit + media library (mirrors api_create_graphic).
    profile_id = run_data.get("profile_id") or run_data.get("club_filter") or ("_run_" + run_id)
    profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)
    media_assets: list = []
    try:
        if W._v8_get_media_store is not None:
            from mediahub.media_library.photo_edit import asset_dicts_for_render

            _ml_store = W._v8_get_media_store()
            media_assets = asset_dicts_for_render(_ml_store.list(profile_id=profile_id), _ml_store)
    except Exception:
        media_assets = []

    use_ai = (request.args.get("ai") or "").lower() in ("1", "true", "yes")
    blank = (request.args.get("blank") or "").lower() in ("1", "true", "yes")

    from mediahub.turn_into import transform_design, blank_brief_for_format
    from mediahub.creative_brief.generator import CreativeBrief

    if blank:
        new_brief = blank_brief_for_format(
            spec, brand_kit, content_item_id=str(card_id), profile_id=profile_id
        )
    else:
        bdict = W._latest_brief_for_card(run_id, card_id)
        if not bdict:
            return jsonify(
                {
                    "error": "no_design",
                    "user_message": (
                        "Create a graphic for this card first, then reformat it "
                        "— or start blank."
                    ),
                }
            ), 409
        src = CreativeBrief.from_dict(bdict)
        if src is None:
            return jsonify({"error": "brief_unreadable"}), 500
        try:
            tr = transform_design(
                source_brief=src,
                target_format=spec,
                brand_kit=brand_kit,
                use_ai_director=use_ai,
            )
        except ValueError as e:
            return jsonify({"error": "transform_failed", "user_message": str(e)}), 400
        new_brief = tr.brief

    # Deterministic renders cache on (card, format, chosen layout, source
    # brief content); the AI-directed path varies per call, so it skips the
    # cache. The source-brief digest means a persisted edit (copilot or
    # manual) re-renders instead of serving the pre-edit PNG.
    import hashlib as _hl

    key = _hl.sha256(
        f"{card_id}|{spec.slug}|{spec.width}x{spec.height}|"
        f"{new_brief.layout_template}|{'blank' if blank else 'tx'}|"
        f"{W._brief_cache_sig(None if blank else bdict)}".encode("utf-8")
    ).hexdigest()[:20]
    out_dir = W.RUNS_DIR / run_id / "reformat" / key
    cache_png = out_dir / f"{spec.render_name}.png"
    if cache_png.exists() and not use_ai:
        return send_file(str(cache_png), mimetype="image/png")

    # Resolve the hero photo (from the approved brief's stored assets) and
    # the brand logo — everything else rides the brief.
    athlete_path = None
    hero_id = (new_brief.sourced_asset_ids or [None])[0]
    if hero_id:
        for a in media_assets:
            ad = a if isinstance(a, dict) else {}
            if str(ad.get("id")) == str(hero_id):
                athlete_path = ad.get("path") or ad.get("file_path")
                break
    logo_path = None
    bk_logo = getattr(brand_kit, "logo_path", None)
    if bk_logo:
        try:
            if Path(bk_logo).exists():
                logo_path = str(bk_logo)
        except Exception:
            logo_path = None

    try:
        from mediahub.graphic_renderer.render import render_brief

        out_dir.mkdir(parents=True, exist_ok=True)
        skip_cutout = getattr(new_brief, "photo_treatment", "") == "no-photo" or not athlete_path
        with W._render_slot("graphic", card_id, timeout=W._RENDER_TRY_TIMEOUT):
            res = render_brief(
                new_brief,
                output_dir=out_dir,
                size=spec.size,
                format_name=spec.render_name,
                athlete_path=(None if skip_cutout else athlete_path),
                logo_path=logo_path,
                brand_kit=brand_kit,
                image_format="png",
            )
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify(W._reformat_error_payload(e)), 500
    return send_file(str(res.visual.file_path), mimetype="image/png")


def api_card_preflight(run_id: str, card_id: str):
    """Deterministically proof a card's design for a print product.

    When this card's artwork has already been rendered for this product
    (the print_art cache), the report proofs the actual PNG — the same
    pixels ``api_card_print`` gates on. Before any render exists, it
    proofs the brand palette at the product's print canvas (no render
    triggered) and says so explicitly in the response.
    """
    run_data, profile_id, err = W._print_resolve(run_id)
    if err:
        return err
    trip = W._print_product_placement(request.args.get("product"), request.args.get("placement"))
    if trip is None:
        return jsonify({"error": "unknown_product"}), 400
    product, placement, spec = trip
    from mediahub.print_ready import proof as _proof

    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)
    art_png = None
    try:
        art_png = W._print_card_png(
            run_id, run_data, card_id, spec, profile_id, brand_kit, cached_only=True
        )
    except Exception:
        art_png = None  # any transform hiccup falls back to the palette check
    if art_png is not None:
        prof = _proof.profile_from_image(art_png)
        checked = "artwork"
        note = ""
    else:
        prof = _proof.profile_from_design(
            W._brand_palette(brand_kit),
            width_px=spec.width,
            height_px=spec.height,
            full_bleed=True,
        )
        checked = "palette"
        note = (
            "Palette-only check — this card's artwork hasn't been rendered "
            "for this product yet, so only the brand palette was proofed. "
            "Export the print PDF for a full proof of the actual pixels."
        )
    report = _proof.run_preflight(prof, product, placement)
    out = report.to_dict()
    out["checked"] = checked
    if note:
        out["note"] = note
    return jsonify(out)


def api_card_print(run_id: str, card_id: str):
    """Render a print-ready PDF (bleed + marks + colour mode) for a product.

    ``?product=&placement=&colour=rgb|cmyk|pdfx&marks=1&force=0`` — a blocking
    pre-flight error returns 422 with the report unless ``force=1``.
    """
    from flask import send_file

    run_data, profile_id, err = W._print_resolve(run_id)
    if err:
        return err
    trip = W._print_product_placement(request.args.get("product"), request.args.get("placement"))
    if trip is None:
        return jsonify({"error": "unknown_product"}), 400
    product, placement, spec = trip
    colour = (request.args.get("colour") or "rgb").strip().lower()
    if colour not in ("rgb", "cmyk", "pdfx"):
        return jsonify({"error": "bad_colour_mode"}), 400
    force = (request.args.get("force") or "").strip().lower() in W._TRUTHY
    marks = (request.args.get("marks") or "1").strip().lower() in W._TRUTHY
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)
    try:
        png = W._print_card_png(run_id, run_data, card_id, spec, profile_id, brand_kit)
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify(W._reformat_error_payload(e)), 500
    if png is None:
        return jsonify(
            {
                "error": "no_design",
                "user_message": "Create a graphic for this card first, then print it.",
            }
        ), 409
    from mediahub.print_ready.engine import PrintRequest, prepare_print

    palette = W._brand_palette(brand_kit)
    req = PrintRequest(
        artwork=Path(png).read_bytes(),
        product_slug=product.slug,
        placement_slug=placement.slug,
        colour_mode=colour,
        crop_marks=marks,
        force=force,
        design=palette,
        full_bleed=True,
    )
    out_dir = W.RUNS_DIR / run_id / "print_out"
    try:
        res = prepare_print(req, out_dir=out_dir, brand=palette)
    except Exception as e:
        return jsonify(W._reformat_error_payload(e)), 500
    if res.blocked:
        return jsonify(
            {
                "error": "preflight_blocked",
                "preflight": res.preflight.to_dict(),
                "user_message": "Fix the blocking issue(s), or export with force=1.",
            }
        ), 422
    # Name the file for the colour mode actually ACHIEVED, not the one
    # requested — a Ghostscript-less deployment downgrades cmyk/pdfx to RGB
    # and a "…-cmyk.pdf" that is really RGB misleads the print shop. The
    # headers carry the same facts for the JS to surface.
    used = (res.colour_mode_used or colour or "rgb").strip().lower()
    resp = make_response(
        send_file(
            str(res.pdf_path),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{product.slug}-{card_id}-{used}.pdf",
        )
    )
    resp.headers["X-Print-Colour-Requested"] = colour
    resp.headers["X-Print-Colour-Used"] = used
    if res.note:
        # Header values must be latin-1-safe single-line; the note is
        # operator-written ASCII prose, but guard anyway.
        resp.headers["X-Print-Note"] = (
            res.note.replace("\n", " ").encode("latin-1", "replace").decode("latin-1")
        )
    return resp


def api_card_merch_mockup(run_id: str, card_id: str):
    """A deterministic product-mockup preview (tee / mug / tote / poster) PNG."""
    from flask import Response

    run_data, profile_id, err = W._print_resolve(run_id)
    if err:
        return err
    trip = W._print_product_placement(request.args.get("product"), request.args.get("placement"))
    if trip is None:
        return jsonify({"error": "unknown_product"}), 400
    product, placement, spec = trip
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)
    try:
        png = W._print_card_png(run_id, run_data, card_id, spec, profile_id, brand_kit)
    except W._RenderBusy:
        return W._render_busy_response("graphic")
    except Exception as e:
        return jsonify(W._reformat_error_payload(e)), 500
    if png is None:
        return jsonify({"error": "no_design"}), 409
    from mediahub.mockups.compose import MockupError, compose_mockup

    accent = W._brand_palette(brand_kit).get("accent")
    try:
        out = compose_mockup(
            Path(png).read_bytes(), product.mockup_template or "flatlay", accent=accent
        )
    except MockupError as e:
        return jsonify({"error": "mockup_failed", "user_message": str(e)}), 400
    return Response(out, mimetype="image/png")


def api_card_assistant(run_id: str, card_id: str):
    """P6.2 — one conversational copilot turn editing this card's design.

    The assistant reads the design/brand/facts and proposes structured,
    validated edits (never paints pixels, never publishes). Applied edits
    persist as a new brief version so the next render/reformat reflects
    them. Honest no-provider error keeps the manual controls working.
    """
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data = W._run_data_any(run_id)
    if run_data is None:
        return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify(
            {"error": "empty_message", "user_message": "Type what you'd like to change."}
        ), 400
    session_id = (body.get("session_id") or "").strip()

    profile_id = W._assistant_profile_id(run_id, run_data)
    if not W._session_can_access_profile(profile_id):
        return jsonify({"error": "forbidden"}), 403
    brand_kit = W._resolve_run_brand_kit(profile_id, run_id, run_data)

    bdict = W._latest_brief_for_card(run_id, card_id)
    if not bdict:
        return jsonify(
            {
                "error": "no_design",
                "user_message": (
                    "Create a graphic for this card first, then ask the copilot to refine it."
                ),
            }
        ), 409
    from mediahub.creative_brief.generator import CreativeBrief

    src = CreativeBrief.from_dict(bdict)
    if src is None:
        return jsonify({"error": "brief_unreadable"}), 500

    from mediahub.assistant import copilot as _acop
    from mediahub.assistant import session as _asess

    sess = _asess.get_or_create(run_id, card_id, session_id, profile_id=profile_id)
    try:
        from mediahub.collab import locks as _locks

        _locked = _locks.locked_elements(run_id, card_id)
    except Exception:
        _locked = set()
    turn = _acop.run_turn(
        session=sess,
        user_message=message,
        brief=src,
        brand_kit=brand_kit,
        facts=W._assistant_card_facts(run_data, card_id),
        profile_id=profile_id,
        locked_elements=_locked,
    )
    # Persist the edited brief so the existing render / reformat surfaces
    # pick it up (they read the most-recent brief for the card).
    if turn.changed:
        try:
            from mediahub.content_pack_visual.integration import briefs_dir_for_run

            bdir = briefs_dir_for_run(run_id)
            (bdir / f"{turn.brief.id}.json").write_text(
                json.dumps(turn.brief.to_dict(), indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            pass

    resp = turn.to_dict()
    resp.update(
        {
            "session_id": sess.session_id,
            "brief_id": turn.brief.id,
            "format": (turn.brief.format_priority or ["story"])[0],
            "reformat_url": url_for("api_card_reformat", run_id=run_id, card_id=card_id),
        }
    )
    return jsonify(resp)


def api_assistant_suggestions(run_id: str, card_id: str):
    """Planner-seeded prompt chips for the copilot (non-generic)."""
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data = W._run_data_any(run_id)
    if run_data is None or not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    profile_id = W._assistant_profile_id(run_id, run_data)
    sport = str(run_data.get("sport") or run_data.get("engine_sport") or "")
    from mediahub.assistant.copilot import suggested_prompts

    return jsonify({"suggestions": suggested_prompts(profile_id, sport)})


def api_run_reel(run_id: str):
    """Render (or serve cached) a multi-card MP4 reel for the meet.

    Uses the top 3 ranked achievements by default; caller can override
    the count with ?n=<int> up to a hard cap of 5.
    """
    from flask import send_file

    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    inputs, err = W._assemble_reel_inputs(run_id)
    if err is not None:
        return err

    try:
        with W._render_slot("reel", run_id, timeout=W._RENDER_TRY_TIMEOUT):
            mp4 = _motion.render_meet_reel(
                inputs["cards"],
                inputs["brand_kit"],
                inputs["out_path"],
                meet_name=inputs["meet_name"],
                briefs=inputs["briefs"],
                format_name=inputs["format"],
                rhythm=inputs["rhythm"],
                sponsor=inputs.get("sponsor", ""),
                next_meet=inputs.get("next_meet", ""),
                dub_language=inputs.get("dub_language", ""),
                reel_stat_config=inputs.get("reel_stat_config"),
            )
    except W._RenderBusy:
        return W._render_busy_response("reel")
    except RuntimeError as e:
        _payload = W._motion_error_payload(e)
        return jsonify(_payload), 503 if _payload.get("kind") == "infra_missing" else 500
    except Exception as e:
        _payload = W._motion_error_payload(e)
        return jsonify(_payload), 503 if _payload.get("kind") == "infra_missing" else 500

    if not Path(mp4).exists():
        return jsonify(
            {
                "error": "render_failed",
                "kind": "internal",
                "detail": "mp4 missing after render",
                "user_message": (
                    "Reel rendering didn't produce an output file. "
                    "This is usually a transient issue — try again."
                ),
            }
        ), 500
    return send_file(
        str(mp4),
        mimetype="video/mp4",
        as_attachment=False,
        download_name=f"meet_reel_{run_id}.mp4",
    )


def api_run_charts(run_id: str):
    """JSON list of the charts this run can support (each with an SVG URL)."""
    if not W._charts_ok:
        return jsonify({"error": "charts_unavailable"}), 503
    ctx, cands, err = W._charts_candidates_for(run_id)
    if err is not None:
        return err
    return jsonify(
        {
            "charts": [
                {
                    "chart_id": c.chart_id,
                    "title": c.title,
                    "kind": c.kind,
                    "summary": c.summary,
                    "headline_stat": c.headline_stat,
                    "n_points": c.n_points,
                    "svg_url": url_for("api_run_chart_svg", run_id=run_id, chart_id=c.chart_id),
                }
                for c in (cands or [])
            ]
        }
    )


def api_run_chart_svg(run_id: str, chart_id: str):
    """Render one candidate chart. ``?fmt=png`` rasterises a ready-to-post PNG
    (Instagram/Facebook don't accept SVG); default is the deterministic SVG.
    ``?format=square|portrait|story|landscape|wide`` picks the size."""
    if not W._charts_ok:
        return jsonify({"error": "charts_unavailable"}), 503
    from dataclasses import replace as _dc_replace

    from mediahub.charts.render import render_chart_svg

    ctx, cands, err = W._charts_candidates_for(run_id)
    if err is not None:
        return err
    match = next((c for c in (cands or []) if c.chart_id == chart_id), None)
    if match is None:
        return jsonify({"error": "chart_not_found"}), 404
    spec = match.spec
    fmt = (request.args.get("format") or "").strip().lower()
    want_png = (request.args.get("fmt") or "").strip().lower() == "png"

    if want_png:
        # Postable PNG via the still renderer's warm-pool path (needs Chromium).
        from mediahub.charts.export import EXPORT_FORMATS, chart_png_path

        size_fmt = fmt if fmt in EXPORT_FORMATS else "square"
        try:
            png = chart_png_path(spec, fmt=size_fmt, brand_kit=ctx["brand_kit"])
        except Exception as e:  # Playwright/Chromium missing → honest error
            return jsonify(
                {
                    "error": "png_unavailable",
                    "detail": str(e),
                    "user_message": (
                        "PNG export needs the image renderer, which isn't "
                        "available right now. The SVG download always works."
                    ),
                }
            ), 503
        from flask import send_file as _send_file

        return _send_file(
            str(png),
            mimetype="image/png",
            as_attachment=bool(request.args.get("download")),
            download_name=f"{chart_id}_{size_fmt}.png",
        )

    if fmt in W._CHART_FORMATS:
        w, h = W._CHART_FORMATS[fmt]
        spec = _dc_replace(spec, width=w, height=h)
    try:
        svg = render_chart_svg(spec, brand_kit=ctx["brand_kit"])
    except Exception as e:
        return jsonify({"error": "render_failed", "detail": str(e)}), 500
    resp = Response(svg, mimetype="image/svg+xml; charset=utf-8")
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f'attachment; filename="{chart_id}.svg"'
    return resp


def api_run_chart_caption(run_id: str, chart_id: str):
    """A grounded, postable caption for one chart. Honest 200 when no AI is set."""
    if not W._charts_ok:
        return jsonify({"error": "charts_unavailable"}), 503
    from mediahub.charts.caption import generate_chart_caption
    from mediahub.media_ai.llm import ClaudeUnavailableError

    ctx, cands, err = W._charts_candidates_for(run_id)
    if err is not None:
        return err
    match = next((c for c in (cands or []) if c.chart_id == chart_id), None)
    if match is None:
        return jsonify({"error": "chart_not_found"}), 404
    tone = (request.args.get("tone") or "editorial").strip().lower()
    try:
        out = generate_chart_caption(match.spec, tone=tone)
    except ClaudeUnavailableError as e:
        return jsonify({"available": False, "error": "no_ai", "message": str(e)})
    return jsonify(
        {
            "available": True,
            "caption": out.get("caption", ""),
            "provider": out.get("provider", ""),
        }
    )


def api_run_charts_recommend(run_id: str):
    """AI picks the chart that leads the story. Honest 200 when no AI is set."""
    if not W._charts_ok:
        return jsonify({"error": "charts_unavailable"}), 503
    from mediahub import charts as _charts
    from mediahub.media_ai.llm import ClaudeUnavailableError

    ctx, cands, err = W._charts_candidates_for(run_id)
    if err is not None:
        return err
    if not cands:
        return jsonify(
            {
                "available": True,
                "recommendation": None,
                "message": "No charts for this run yet.",
            }
        )
    agg = _charts.compute_aggregates(ctx["run_data"])
    try:
        rec = _charts.recommend_chart(cands, agg)
    except ClaudeUnavailableError as e:
        return jsonify({"available": False, "error": "no_ai", "message": str(e)})
    return jsonify({"available": True, "recommendation": rec})


def api_run_charts_insights(run_id: str):
    """AI takeaways grounded in the run's facts. Honest 200 when no AI is set."""
    if not W._charts_ok:
        return jsonify({"error": "charts_unavailable"}), 503
    from mediahub import charts as _charts
    from mediahub.media_ai.llm import ClaudeUnavailableError

    ctx, err = W._charts_run_context(run_id)
    if err is not None:
        return err
    agg = _charts.compute_aggregates(ctx["run_data"])
    tone = (request.args.get("tone") or "editorial").strip().lower()
    try:
        ins = _charts.generate_insights(agg, tone=tone)
    except ClaudeUnavailableError as e:
        return jsonify({"available": False, "error": "no_ai", "message": str(e)})
    return jsonify({"available": True, "insights": ins})


def api_run_reel_job(run_id: str):
    """Kick off a background reel render; returns ``{job_id, poll_url}``.

    The synchronous /reel route holds the HTTP connection for the whole
    30–90s first render, which front-line proxies are happy to kill —
    from the user's side the button simply "does nothing". Same cure as
    the V10 graphic-variants job: render in a daemon thread, poll for
    the outcome, then stream the finished MP4 from the file route.
    """
    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    inputs, err = W._assemble_reel_inputs(run_id)
    if err is not None:
        return err

    # url_for needs the request context — resolve before the thread.
    file_url = url_for(
        "api_run_reel_file", format=inputs["format"], **W._reel_file_url_kwargs(inputs, run_id)
    )
    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "reel",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            # Heartbeat: a cold render may legitimately run past the 5-min
            # stall threshold (the subprocess timeout is 600s) — keep the
            # job file fresh so the status route doesn't report job_lost.
            with W._job_heartbeat(job):
                with W._render_slot("reel", run_id, timeout=W._RENDER_TRY_TIMEOUT):
                    mp4 = _motion.render_meet_reel(
                        inputs["cards"],
                        inputs["brand_kit"],
                        inputs["out_path"],
                        meet_name=inputs["meet_name"],
                        briefs=inputs["briefs"],
                        format_name=inputs["format"],
                        rhythm=inputs["rhythm"],
                        sponsor=inputs.get("sponsor", ""),
                        next_meet=inputs.get("next_meet", ""),
                        dub_language=inputs.get("dub_language", ""),
                        reel_stat_config=inputs.get("reel_stat_config"),
                    )
            if not Path(mp4).exists():
                raise RuntimeError("mp4 missing after render")
            job["status"] = "done"
            job["video_url"] = file_url
            # Render-complete milestone in the in-app inbox (UI 1.14). The
            # async reel render is the "kick it off and walk away" flow, so
            # this is the notification a user actually wants when they come
            # back. Scoped to the org that owns the job; a no-op when signed
            # out (empty owner_pid).
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(
                    job.get("owner_pid") or "", run_id=run_id, label="reel"
                )
            except Exception:
                pass
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except Exception as e:
            _payload = W._motion_error_payload(e)
            job["status"] = "error"
            job["error"] = str(_payload.get("detail") or e)
            job["user_message"] = str(_payload.get("user_message") or "")
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_error(
                    job.get("owner_pid") or "",
                    "Reel render failed",
                    job["user_message"] or job["error"],
                    run_id=run_id,
                )
            except Exception:
                pass
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"reel-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_run_reel_batch(run_id: str):
    """Render + cache every reel format in one pass (R1.15); returns
    ``{job_id, poll_url}``.

    The single ``/reel`` / ``/reel-job`` routes produce one cut per
    request. This kicks off one background job that shapes the cards once
    and renders all four cuts (story / portrait / square / landscape),
    reusing any cut already in the motion cache so only the missing ones
    cost a render. Always async — four cold renders run several minutes —
    and the finished cuts stream from the existing ``reel-file`` route per
    format. Poll ``api_reel_job_status``: on ``done`` it carries
    ``video_urls`` (one per produced cut) and ``formats_failed`` (the
    honest reason for any cut the active engine couldn't produce — e.g.
    the ffmpeg fallback's non-story cuts).
    """
    try:
        from mediahub.visual import motion as _motion
    except Exception as e:
        return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

    inputs, err = W._assemble_reel_inputs(run_id)
    if err is not None:
        return err

    n = inputs["n"]
    out_dir = Path(inputs["out_path"]).parent
    # Same lang-suffixed stem as the single route, so cuts land where the
    # reel-file route (given the same lang) looks and cache reuse holds.
    base_name = inputs["base_name"]
    # url_for needs the request context — resolve every cut's file URL now,
    # before the worker thread (which has none).
    _file_kwargs = W._reel_file_url_kwargs(inputs, run_id)
    file_urls = {
        fmt: url_for("api_run_reel_file", format=fmt, **_file_kwargs)
        for fmt in _motion.MOTION_FORMATS
    }

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "reel-batch",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "video_urls": {},
        "formats_failed": {},
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            # Per-cut render slot: a multi-minute batch on a single-slot box
            # yields the render gate between cuts instead of hogging it for
            # the whole run, so a foreground single render can interleave.
            # Sponsor/next-meet outro, rhythm and dub ride along exactly as
            # on the single route, so the story cut's cache key matches and
            # the documented cache reuse actually happens. The heartbeat
            # keeps the job file fresh across a multi-minute batch.
            with W._job_heartbeat(job):
                result = _motion.render_meet_reel_all_formats(
                    inputs["cards"],
                    inputs["brand_kit"],
                    out_dir,
                    meet_name=inputs["meet_name"],
                    briefs=inputs["briefs"],
                    base_name=base_name,
                    render_slot=lambda fmt: W._render_slot(
                        "reel", f"{run_id}:{fmt}", timeout=W._RENDER_QUEUE_TIMEOUT
                    ),
                    rhythm=inputs["rhythm"],
                    sponsor=inputs.get("sponsor", ""),
                    next_meet=inputs.get("next_meet", ""),
                    dub_language=inputs.get("dub_language", ""),
                    reel_stat_config=inputs.get("reel_stat_config"),
                )
            rendered = result.get("rendered") or {}
            errors = result.get("errors") or {}
            if not rendered:
                # Not one cut produced — surface an honest reason rather
                # than reporting a successful job with no video.
                reason = next(iter(errors.values()), "no reel formats could be rendered")
                raise RuntimeError(reason)
            video_urls = {fmt: file_urls[fmt] for fmt in rendered if fmt in file_urls}
            job["status"] = "done"
            job["video_urls"] = video_urls
            # Keep the legacy single field on the story cut (or the first
            # produced) so a single-format poller still gets a video_url.
            job["video_url"] = video_urls.get("story") or next(iter(video_urls.values()), "")
            job["formats_failed"] = dict(errors)
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(
                    job.get("owner_pid") or "", run_id=run_id, label="reel (all formats)"
                )
            except Exception:
                pass
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another video is rendering right now — try again in a minute."
        except Exception as e:
            _payload = W._motion_error_payload(e)
            job["status"] = "error"
            job["error"] = str(_payload.get("detail") or e)
            job["user_message"] = str(_payload.get("user_message") or "")
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_error(
                    job.get("owner_pid") or "",
                    "Reel batch render failed",
                    job["user_message"] or job["error"],
                    run_id=run_id,
                )
            except Exception:
                pass
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"reelbatch-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_run_reel_file(run_id: str):
    """Serve an already-rendered reel MP4 — never triggers a render."""
    from flask import send_file

    from mediahub.visual import motion as _motion

    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    try:
        n = int(request.args.get("n", "3"))
    except (TypeError, ValueError):
        n = 3
    n = max(1, min(5, n))
    fmt = (request.args.get("format") or _motion.DEFAULT_MOTION_FORMAT).strip().lower()
    if fmt not in _motion.MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    # ?lang= mirrors the render routes' 1.24 dub gate so a dubbed cut's
    # language-suffixed file is findable; anything non-dubbable falls back
    # to the original-language name.
    from mediahub.visual import dub as _dub

    _lang = (request.args.get("lang") or "").strip()
    _suffix = (
        f"_{_lang.split('-', 1)[0]}"
        if (_lang and _dub.is_dubbable(_lang) and _lang.split("-", 1)[0] != "en")
        else ""
    )
    # M31 — a custom selection's file carries the same deterministic
    # _sel<hash8> marker the assembly derived from the final rank-ordered
    # id list (the job threads that exact list into this URL's ?cards=).
    _cards_arg = (request.args.get("cards") or "").strip()
    _sel = (
        "_sel" + W.hashlib.sha1(_cards_arg.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        if _cards_arg
        else ""
    )
    base = f"reel_{n}{_sel}{_suffix}"
    name = f"{base}.mp4" if fmt == "story" else f"{base}_{fmt}.mp4"
    path = W.RUNS_DIR / run_id / "motion" / name
    if not path.exists():
        return jsonify({"error": "reel_not_rendered"}), 404
    if (request.args.get("poster") or "").strip().lower() in {"1", "true", "yes"}:
        # The poster-frame PNG sidecar written beside the rendered MP4
        # (visual/audio_mux.py) — a thumbnail for review surfaces and
        # platforms that want one. 404s honestly when absent (e.g. a
        # reel rendered before posters existed).
        poster = path.with_suffix(".poster.png")
        if not poster.exists():
            return jsonify({"error": "poster_not_rendered"}), 404
        return send_file(
            str(poster),
            mimetype="image/png",
            as_attachment=False,
            download_name=poster.name,
        )
    return send_file(
        str(path),
        mimetype="video/mp4",
        as_attachment=False,
        download_name=f"meet_reel_{run_id}_{fmt}.mp4"
        if fmt != "story"
        else f"meet_reel_{run_id}.mp4",
    )


def api_run_reel_manifest(run_id: str):
    """The reel's explainability manifest (M22 handoff) — engine, beats,
    rhythm, honest capability notes — written as a JSON sidecar beside the
    rendered MP4 by BOTH engines. Same ``n``/``format``/``lang``/``cards``
    resolution as ``reel-file``; 404 until that cut has been rendered."""
    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    from mediahub.visual import dub as _dub
    from mediahub.visual import motion as _motion

    try:
        n = int(request.args.get("n", "3"))
    except (TypeError, ValueError):
        n = 3
    n = max(1, min(5, n))
    fmt = (request.args.get("format") or _motion.DEFAULT_MOTION_FORMAT).strip().lower()
    if fmt not in _motion.MOTION_FORMATS:
        return jsonify({"error": "bad_format"}), 400
    _lang = (request.args.get("lang") or "").strip()
    _suffix = (
        f"_{_lang.split('-', 1)[0]}"
        if (_lang and _dub.is_dubbable(_lang) and _lang.split("-", 1)[0] != "en")
        else ""
    )
    _cards_arg = (request.args.get("cards") or "").strip()
    _sel = (
        "_sel" + W.hashlib.sha1(_cards_arg.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        if _cards_arg
        else ""
    )
    base = f"reel_{n}{_sel}{_suffix}"
    name = f"{base}.json" if fmt == "story" else f"{base}_{fmt}.json"
    sidecar = W.RUNS_DIR / run_id / "motion" / name
    if not sidecar.exists():
        return jsonify({"error": "manifest_not_found", "detail": "render this cut first"}), 404
    try:
        return jsonify(json.loads(sidecar.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"error": f"manifest_unreadable: {e}"}), 500


def api_run_render_all_job(run_id: str):
    """M30 (UX-2) — "Create all graphics" in one background job.

    Ten approved cards used to mean ten clicks and ten held-open waits.
    This kicks ONE disk-backed job (the V10 variant-job store) that walks
    every approved card still missing a graphic and renders it through
    the exact same pipeline as the per-card button — AI-directed brief,
    persisted Inspector overrides, per-card sponsor rotation, and the
    pack path's ``recent_signatures`` / ``recent_asset_families``
    threading so ten cards don't come out samey or share burst frames.
    Per-card progress ("3 of 10 rendered") streams through
    ``api_reel_job_status``. ``?force=1`` re-renders cards that already
    have a graphic; the default renders only the missing ones.
    """
    if not W._v8_ok or W._v8_create_visual_for_item is None:
        return jsonify({"error": "v8_unavailable"}), 503
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    raw_profile_id = (run_data or {}).get("profile_id", "")
    try:
        from mediahub.workflow.pack import build_content_pack as _bcp

        approved = _bcp(run_id, raw_profile_id, W.RUNS_DIR)
    except Exception:
        approved = []
    if not approved:
        return jsonify(
            {
                "error": "no_approved_cards",
                "user_message": (
                    "Nothing is approved yet — approve cards on the review "
                    "page first, then build their graphics here."
                ),
            }
        ), 400

    force = (request.args.get("force") or "").strip().lower() in ("1", "true", "yes")
    already = W._rendered_visuals_for_run(run_id)
    meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
    todo: list[tuple[str, dict, str]] = []
    for card in approved:
        ach = card.get("achievement") or {}
        cid = str(card.get("_card_id") or ach.get("swim_id") or "")
        if not cid or (not force and cid in already):
            continue
        item = {
            "id": cid,
            "swim_id": ach.get("swim_id") or cid,
            "achievement": ach,
            "post_angle": ach.get("post_angle"),
            "meet_name": meet_name,
            "safe_to_post": card.get("safe_to_post") or {"level": "safe"},
        }
        todo.append((cid, item, str(ach.get("swimmer_name") or cid)))
    if not todo:
        return jsonify(
            {
                "ok": True,
                "status": "done",
                "total": 0,
                "rendered_already": len(already),
                "message": (
                    f"All {len(approved)} approved card"
                    f"{'s' if len(approved) != 1 else ''} already have graphics."
                ),
            }
        )

    # Resolve everything that needs the request context BEFORE the thread.
    norm_profile_id = raw_profile_id or run_data.get("club_filter") or "_run_" + run_id
    norm_profile_id = re.sub(r"[^a-z0-9_-]", "-", norm_profile_id.lower()).strip("-") or (
        "_run_" + run_id
    )
    brand_kit = W._resolve_run_brand_kit(norm_profile_id, run_id, run_data)
    media_assets: list = []
    try:
        if W._v8_get_media_store is not None:
            from mediahub.media_library.photo_edit import asset_dicts_for_render

            _ml_store = W._v8_get_media_store()
            media_assets = asset_dicts_for_render(
                _ml_store.list(profile_id=norm_profile_id), _ml_store
            )
    except Exception:
        media_assets = []
    try:
        sponsor_profile = W.load_profile(norm_profile_id)
    except Exception:
        sponsor_profile = None
    # PHOTOS-4/M2: dHash burst families for the anti-samey threading.
    dhash_by_id: dict[str, str] = {}
    for _ad in media_assets:
        _d = _ad if isinstance(_ad, dict) else {}
        _q = (_d.get("media_meta") or {}).get("quality") or {}
        if _d.get("id") and _q.get("dhash"):
            dhash_by_id[str(_d["id"])] = str(_q["dhash"])
    card_overrides = {cid: W._inspector_overrides_for_card(run_id, cid) for cid, _, _ in todo}

    job_id = W.uuid.uuid4().hex
    job: dict = {
        "id": job_id,
        "kind": "render-all",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "total": len(todo),
        "done": 0,
        "current": "",
        "rendered": [],
        "errors": {},
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            job_sigs: list[str] = []
            recent_fams: list[str] = []
            # Seed the burst-family avoid-list from what's already rendered
            # so a fresh batch doesn't reuse an earlier card's exact frame.
            for _info in already.values():
                for _aid in _info.get("sourced_asset_ids") or []:
                    _fam = dhash_by_id.get(str(_aid))
                    if _fam and _fam not in recent_fams:
                        recent_fams.append(_fam)
            with W._job_heartbeat(job):
                for idx, (cid, item, label) in enumerate(todo, start=1):
                    job["current"] = label
                    W._variant_job_save(job)
                    try:
                        history = W._v9_load_variation_history(run_id, cid)
                        recent_sigs = (history.get("signatures", []) + job_sigs)[-6:]
                        rotated = None
                        try:
                            from mediahub.club_platform.sponsors import (
                                sponsor_for_card as _sponsor_for_card,
                            )

                            if sponsor_profile is not None:
                                rotated = _sponsor_for_card(
                                    sponsor_profile, run_id, cid, include_legacy=False
                                )
                        except Exception:
                            rotated = None
                        rotated_logo = None
                        if rotated and rotated.get("logo_asset_id"):
                            for _a in media_assets:
                                _adx = _a if isinstance(_a, dict) else {}
                                if str(_adx.get("id")) == str(rotated["logo_asset_id"]):
                                    rotated_logo = _adx.get("path") or _adx.get("file_path")
                                    break
                        with W._render_slot(
                            "graphic", f"pack:{cid}", timeout=W._RENDER_QUEUE_TIMEOUT
                        ):
                            res = W._v8_create_visual_for_item(
                                item,
                                brand_kit,
                                profile_id=norm_profile_id,
                                run_id=run_id,
                                media_assets=media_assets,
                                use_ai_director=True,
                                recent_signatures=recent_sigs,
                                recent_hooks=history.get("hooks", [])[-6:],
                                sponsor_name=(rotated or {}).get("name", ""),
                                sponsor_logo_path=rotated_logo,
                                user_overrides=card_overrides.get(cid) or {},
                                recent_asset_families=recent_fams[-12:],
                            )
                        visuals = res.get("visuals") or []
                        if visuals:
                            job["rendered"].append(cid)
                            brief_d = res.get("brief") or {}
                            sig = brief_d.get("variation_signature") or ""
                            if sig:
                                job_sigs.append(sig)
                                W._v9_save_variation_history(
                                    run_id, cid, sig, brief_d.get("primary_hook") or ""
                                )
                            for v in visuals:
                                for aid in v.get("sourced_asset_ids") or []:
                                    fam = dhash_by_id.get(str(aid))
                                    if fam and fam not in recent_fams:
                                        recent_fams.append(fam)
                        else:
                            job["errors"][cid] = (
                                "; ".join(str(e) for e in (res.get("errors") or [])[:2])
                                or "no visual produced"
                            )
                    except W._RenderBusy:
                        job["errors"][cid] = "renderer busy — re-run to finish this card"
                    except Exception as e:
                        job["errors"][cid] = str(e)
                    job["done"] = idx
                    W._variant_job_save(job)
            if job["rendered"]:
                job["status"] = "done"
                try:
                    from mediahub.notify import inbox as _inbox

                    _inbox.record_render_complete(
                        job.get("owner_pid") or "",
                        run_id=run_id,
                        label=f"graphics ({len(job['rendered'])} cards)",
                    )
                except Exception:
                    pass
            else:
                job["status"] = "error"
                job["error"] = "; ".join(list(job["errors"].values())[:3]) or "no cards rendered"
                job["user_message"] = (
                    "No graphics could be rendered — see the per-card errors, then try again."
                )
        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"renderall-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "total": len(todo),
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_run_bulk_export(run_id: str):
    """Kick a background bulk export of a run's cards × formats → one ZIP.

    Mirrors the reel job: render in a daemon thread, poll for the outcome,
    download the finished ZIP from the file route (whose link unifies with
    the 1.18 share tokens).
    """
    run_data = W._load_run(run_id)
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    body = request.get_json(silent=True) or {}
    raw_formats = body.get("formats") or ["jpg"]
    if not isinstance(raw_formats, list):
        raw_formats = [raw_formats]
    from mediahub import export_engine as ee
    from mediahub.export_engine.bulk import BulkExportSpec, run_bulk_export
    from mediahub.export_engine.options import ExportOptions

    # Type-guard malformed client JSON into a 400, never a 500: a
    # non-string format entry would AttributeError inside normalise_key,
    # and a non-dict options blob inside ExportOptions.from_dict.
    formats = [ee.normalise_key(f) for f in raw_formats if isinstance(f, str) and ee.has_format(f)]
    if not formats:
        return jsonify({"error": "no_valid_formats"}), 400
    raw_opts = body.get("options") or {}
    opts = ExportOptions.from_dict(raw_opts if isinstance(raw_opts, dict) else {})

    items = W._bulk_items_for_run(run_id)
    if not items:
        return jsonify(
            {
                "error": "no_visuals",
                "message": "No graphics have been rendered for this run yet.",
            }
        ), 404

    meet = (run_data or {}).get("meet") or {}
    label = meet.get("name") or run_id

    job_id = W.uuid.uuid4().hex
    out_path = W.RUNS_DIR / run_id / "exports" / f"bulk_{job_id}.zip"
    file_url = url_for("api_run_bulk_export_file", run_id=run_id, job=job_id)
    owner_pid = W._active_profile_id() or ""
    job: dict = {
        "id": job_id,
        "kind": "bulk_export",
        "status": "running",
        "error": "",
        "done": 0,
        "total": len(items),
        "file_url": "",
        "file_count": 0,
        "error_count": 0,
        "created_at": time.time(),
        "owner_pid": owner_pid,
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            spec = BulkExportSpec(items=items, formats=formats, options=opts, label=label)

            def _prog(done: int, total: int, _name: str) -> None:
                job["done"] = done
                job["total"] = total
                W._variant_job_save(job)

            res = run_bulk_export(spec, out=out_path, progress=_prog)
            job["status"] = "done"
            job["file_url"] = file_url
            job["file_count"] = res.file_count
            job["error_count"] = res.error_count
            try:
                from mediahub.notify import inbox as _inbox

                _inbox.record_render_complete(owner_pid, run_id=run_id, label="bulk export")
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(exc)
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"bulkexp-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_export_job_status", job_id=job_id),
            }
        ),
        202,
    )


def api_run_bulk_export_file(run_id: str):
    """Serve a finished bulk-export ZIP. Access by session OR a 1.18 share
    token scoped to this run — the unified export download link."""
    # Access first (never leak even a 'bad request' to a foreign org): a
    # run-owning session, or a valid share token scoped to this run.
    # This endpoint is exempt from the org-setup gate (a token recipient
    # has no session), so real anonymous traffic reaches it — an anonymous
    # session (no active profile) is NOT an owner here and must present a
    # token, unlike gated routes where a None pid only occurs in
    # no-org sandboxes.
    _pid = W._active_profile_id()
    ok = _pid is not None and W._can_access_run(run_id, W._load_run(run_id), _pid)
    if not ok:
        token = (request.args.get("token") or "").strip()
        if token:
            try:
                from mediahub.collab import share_tokens as _st

                share = _st.resolve(token)
                # Run-wide tokens only: a card-scoped share exposes ONE
                # card, never the whole run's ZIP. api_run_export_share
                # mints run-wide tokens, so the intended flow is unchanged.
                ok = bool(share and share.run_id == run_id and not share.card_id)
            except Exception:
                ok = False
    if not ok:
        return jsonify({"error": "forbidden"}), 404

    job_id = (request.args.get("job") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        return jsonify({"error": "bad_job"}), 400

    path = W.RUNS_DIR / run_id / "exports" / f"bulk_{job_id}.zip"
    if not path.is_file():
        return jsonify({"error": "export_not_found"}), 404
    from flask import send_file

    return send_file(
        str(path),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"mediahub-export-{run_id}.zip",
    )


@W.require_run
def api_run_export_share(run_id: str):
    """Mint a 1.18 share token so a finished export ZIP has a shareable,
    revocable, expiring download link (no login needed to fetch it)."""
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        return jsonify({"error": "bad_job"}), 400
    # Don't mint a link for an export that doesn't exist (failed/never ran),
    # so a recipient never gets a dead 404 link.
    if not (W.RUNS_DIR / run_id / "exports" / f"bulk_{job_id}.zip").is_file():
        return jsonify({"error": "export_not_found"}), 404
    try:
        from mediahub.collab import share_tokens as _st

        share = _st.create_share(
            run_id=run_id, perm=_st.PERM_VIEW, created_by=W._active_profile_id() or "", ttl_days=7
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "share_failed", "message": str(exc)}), 500
    url = url_for("api_run_bulk_export_file", run_id=run_id, job=job_id, token=share.token)
    return jsonify({"ok": True, "token": share.token, "url": url, "expires_at": share.expires_at})


def api_reel_comments(run_id: str):
    """List (GET) or pin (POST) review comments for a run's reel/card.

    GET  ?target=<reel|card:ID>&resolved=0|1  -> {ok, target, comments:[…]}
    POST {target?, t_ms, body, author?}        -> {ok, comment:{…}}  (201)
    """
    _run_data, err = W._reel_comments_run(run_id)
    if err is not None:
        return err
    try:
        from mediahub.workflow import review_comments as _rc
    except Exception as e:
        return jsonify({"error": f"comments_unavailable: {e}"}), 503

    if request.method == "GET":
        target = request.args.get("target")
        include_resolved = (request.args.get("resolved") or "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        try:
            rows = _rc.list_comments(run_id, target, include_resolved=include_resolved)
        except _rc.ReelCommentError as e:
            return jsonify({"error": "bad_request", "detail": str(e)}), 400
        return jsonify(
            {
                "ok": True,
                "target": target or None,
                "comments": [c.to_dict() for c in rows],
            }
        )

    payload = request.get_json(silent=True) or {}
    try:
        comment = _rc.add_comment(
            run_id,
            payload.get("target"),
            payload.get("t_ms"),
            payload.get("body"),
            author=payload.get("author"),
        )
    except _rc.ReelCommentError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    return jsonify({"ok": True, "comment": comment.to_dict()}), 201


def api_reel_comment_mutate(run_id: str, comment_id: str):
    """Resolve / reopen / edit / delete a single review comment.

    Body JSON: ``{action: 'resolve'|'reopen'|'edit'|'delete', body?}``.
    Mirrors api_workflow_set's action-in-body style so one JSON POST
    (CSRF-exempt by content-type) covers every mutation. The comment id is
    scoped to ``run_id`` so it can only be touched under its own run.
    """
    _run_data, err = W._reel_comments_run(run_id)
    if err is not None:
        return err
    try:
        from mediahub.workflow import review_comments as _rc
    except Exception as e:
        return jsonify({"error": f"comments_unavailable: {e}"}), 503

    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()

    if action == "delete":
        if not _rc.delete_comment(comment_id, run_id=run_id):
            return jsonify({"error": "comment_not_found"}), 404
        return jsonify({"ok": True, "deleted": comment_id})

    if action in {"resolve", "reopen"}:
        updated = _rc.update_comment(comment_id, resolved=(action == "resolve"), run_id=run_id)
        if updated is None:
            return jsonify({"error": "comment_not_found"}), 404
        return jsonify({"ok": True, "comment": updated.to_dict()})

    if action == "edit":
        try:
            updated = _rc.update_comment(comment_id, body=payload.get("body"), run_id=run_id)
        except _rc.ReelCommentError as e:
            return jsonify({"error": "bad_request", "detail": str(e)}), 400
        if updated is None:
            return jsonify({"error": "comment_not_found"}), 404
        return jsonify({"ok": True, "comment": updated.to_dict()})

    return jsonify({"error": "unknown_action", "detail": action or "(none)"}), 400


def api_collab_comments(run_id: str):
    """List (GET) or add (POST) anchored review comments / tasks.

    GET  ?card_id=<id>&resolved=0|1 -> {ok, comments:[…], open_tasks}
    POST {card_id?, body, kind?, anchor?, parent_id?, assignee?} -> {ok, comment}
    """
    ctx, err = W._collab_run_ctx(run_id)
    if err is not None:
        return err
    from mediahub.collab import mentions as _mentions
    from mediahub.collab import threads as _threads

    if request.method == "GET":
        card_id = request.args.get("card_id")
        include_resolved = (request.args.get("resolved") or "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        rows = _threads.list_for_card(run_id, card_id, include_resolved=include_resolved)
        reactions = _threads.reactions_for([c.id for c in rows])
        return jsonify(
            {
                "ok": True,
                "comments": [W._collab_comment_payload(c, reactions) for c in rows],
                "open_tasks": _threads.open_task_count(run_id, card_id),
                "me": ctx["me"],
            }
        )

    denied = W._role_denied_json(W._perms.CAP_COMMENT, run_id, ctx["run_data"])
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    body = payload.get("body")
    kind = (payload.get("kind") or "comment").strip().lower()
    assignee = (payload.get("assignee") or "").strip().lower()
    mention_emails = _mentions.resolve_mentions(str(body or ""), ctx["members"])
    try:
        comment = _threads.add_comment(
            run_id,
            payload.get("card_id"),
            body,
            author_email=ctx["me"],
            author_name=ctx["me"],
            anchor=payload.get("anchor"),
            parent_id=payload.get("parent_id"),
            kind=kind,
            assignee_email=assignee,
            mentions=mention_emails,
        )
    except _threads.ThreadError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    W._collab_notify_mentions(ctx, run_id, comment)
    # 1.18: tag @assistant in a thread and it replies (honest-error if no AI).
    W._assistant_thread_reply(ctx, run_id, comment)
    reactions = _threads.reactions_for([comment.id])
    return jsonify({"ok": True, "comment": W._collab_comment_payload(comment, reactions)}), 201


def api_collab_comment_mutate(run_id: str, comment_id: str):
    """Mutate one comment/task: resolve | reopen | complete | edit | delete | react.

    Body JSON ``{action, body?, emoji?}``. Delete is author-or-manager;
    everything else needs the comment capability. ``complete``/``resolve``
    tick a task done; ``reopen`` un-ticks it.
    """
    ctx, err = W._collab_run_ctx(run_id)
    if err is not None:
        return err
    from mediahub.collab import threads as _threads

    denied = W._role_denied_json(W._perms.CAP_COMMENT, run_id, ctx["run_data"])
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()
    me = ctx["me"]

    if action == "delete":
        existing = _threads.get_comment(comment_id)
        if existing is None or existing.run_id != run_id:
            return jsonify({"error": "comment_not_found"}), 404
        is_manager = W._run_actor_can(
            W._perms.CAP_APPROVE, run_id, ctx["run_data"]
        ) or W._run_actor_can(W._perms.CAP_MANAGE, run_id, ctx["run_data"])
        if not is_manager and (existing.author_email or "") != (me or ""):
            return jsonify(
                {"error": "forbidden", "reason": "Only the author can delete this."}
            ), 403
        removed = _threads.delete_comment(comment_id, run_id=run_id)
        return jsonify({"ok": True, "deleted": comment_id, "removed": removed})

    if action in {"resolve", "reopen", "complete"}:
        updated = _threads.set_resolved(comment_id, action != "reopen", run_id=run_id)
        if updated is None:
            return jsonify({"error": "comment_not_found"}), 404
        return jsonify({"ok": True, "comment": updated.to_dict()})

    if action == "edit":
        try:
            updated = _threads.edit_body(
                comment_id, payload.get("body"), run_id=run_id, author_email=me or None
            )
        except _threads.ThreadError as e:
            return jsonify({"error": "bad_request", "detail": str(e)}), 400
        if updated is None:
            return jsonify({"error": "comment_not_found"}), 404
        return jsonify({"ok": True, "comment": updated.to_dict()})

    if action == "react":
        try:
            on = _threads.toggle_reaction(comment_id, payload.get("emoji"), me)
        except _threads.ThreadError as e:
            return jsonify({"error": "bad_request", "detail": str(e)}), 400
        reactions = _threads.reactions_for([comment_id])
        return jsonify({"ok": True, "on": on, "reactions": reactions.get(comment_id, {})})

    return jsonify({"error": "unknown_action", "detail": action or "(none)"}), 400


@W.require_run
def api_card_revisions(run_id: str, card_id: str):
    """List a card's design versions, oldest→newest (latest = current)."""
    from mediahub.collab import revisions as _rev

    revs = _rev.list_revisions(run_id, card_id)
    current = next((r["brief_id"] for r in revs if r["is_current"]), "")
    return jsonify({"ok": True, "revisions": revs, "current_id": current})


@W.require_run
def api_card_revisions_diff(run_id: str, card_id: str):
    """Field-level before/after between two of a card's design versions."""
    from mediahub.collab import revisions as _rev

    diff = _rev.diff_revisions(
        run_id, card_id, request.args.get("a", ""), request.args.get("b", "")
    )
    if diff is None:
        return jsonify({"error": "revision_not_found"}), 404
    return jsonify({"ok": True, "diff": diff})


@W.require_run
def api_card_revisions_restore(run_id: str, card_id: str, run_data):
    """Roll a card back to a prior version (re-issued as a fresh current)."""
    denied = W._role_denied_json(W._perms.CAP_EDIT, run_id, run_data)
    if denied:
        return denied
    from mediahub.collab import revisions as _rev

    payload = request.get_json(silent=True) or {}
    restored = _rev.restore_revision(run_id, card_id, payload.get("brief_id", ""))
    if restored is None:
        return jsonify({"error": "revision_not_found"}), 404
    return jsonify({"ok": True, "brief_id": restored.get("id", "")})


@W.require_run
def api_card_locks(run_id: str, card_id: str, run_data):
    """List (GET) or set (POST) element locks on a card.

    POST {element, locked} — locking an element refuses any later edit
    (copilot patch or inspector toggle) that would change it.
    """
    from mediahub.collab import locks as _locks

    if request.method == "GET":
        return jsonify(
            {
                "ok": True,
                "locked": sorted(_locks.locked_elements(run_id, card_id)),
                "lockable": sorted(_locks.LOCKABLE_ELEMENTS),
            }
        )

    denied = W._role_denied_json(W._perms.CAP_EDIT, run_id, run_data)
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    try:
        _locks.set_lock(
            run_id,
            card_id,
            payload.get("element", ""),
            bool(payload.get("locked")),
            by=W._auth.current_user_email() or "",
        )
    except _locks.LockError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    return jsonify({"ok": True, "locked": sorted(_locks.locked_elements(run_id, card_id))})


@W.require_run
def api_run_shares(run_id: str, run_data):
    """List (GET) or mint (POST) review-share links for a run. Owner-only —
    a share exposes club data outside the workspace."""
    denied = W._role_denied_json(W._perms.CAP_MANAGE, run_id, run_data)
    if denied:
        return denied
    from mediahub.collab import share_tokens as _shares

    if request.method == "GET":
        rows = _shares.list_for_run(run_id)
        return jsonify(
            {
                "ok": True,
                "shares": [
                    {**s.to_public_dict(), "url": url_for("share_review_page", token=s.token)}
                    for s in rows
                ],
            }
        )

    payload = request.get_json(silent=True) or {}
    try:
        share = _shares.create_share(
            run_id,
            card_id=(payload.get("card_id") or "").strip(),
            perm=(payload.get("perm") or "view"),
            created_by=W._auth.current_user_email() or "",
            ttl_days=payload.get("ttl_days", _shares.DEFAULT_TTL_DAYS),
        )
    except _shares.ShareTokenError as e:
        return jsonify({"error": "bad_request", "detail": str(e)}), 400
    return jsonify(
        {
            "ok": True,
            "share": {
                **share.to_public_dict(),
                "url": url_for("share_review_page", token=share.token, _external=True),
            },
        }
    ), 201


@W.require_run
def api_run_share_revoke(run_id: str, token: str, run_data):
    denied = W._role_denied_json(W._perms.CAP_MANAGE, run_id, run_data)
    if denied:
        return denied
    from mediahub.collab import share_tokens as _shares

    ok = _shares.revoke(token, run_id=run_id)
    return jsonify({"ok": True, "revoked": ok})


def api_card_voiceover(run_id: str, card_id: str):
    """Synthesise (or serve cached) a voiceover for a single APPROVED card.

    The spoken text is the human-approved caption, verbatim — there is no AI
    script here. This route is the *audio approval gate*: it refuses to speak
    a card that a human has not approved, mirroring the rule that nothing is
    published until a person signs off.

    Query/format:
      - default            → serves the MP3 (audio/mpeg)
      - ?format=srt        → serves the subtitle track (for muted autoplay)
      - ?format=json       → returns {transcript, voice, duration_ms, ...}
                              for the review/playback surface
    """
    if not W._voiceover_enabled():
        # Honest, specific 503 — either the backend isn't importable or the
        # operator hasn't opted in. Never a silent fallback voice.
        return jsonify(
            {
                "error": "voiceover_disabled",
                "kind": "infra_missing",
                "user_message": (
                    "Voiceover is turned off. An operator can enable it by "
                    "installing the speech backend and setting MEDIAHUB_VOICEOVER=1."
                ),
            }
        ), 503

    run_data = W._load_run(run_id)
    if run_data is None:
        run_json = W.RUNS_DIR / run_id / "run.json"
        if run_json.exists():
            try:
                run_data = json.loads(run_json.read_text())
            except Exception as e:
                return jsonify({"error": f"run_load_failed: {e}"}), 500
        else:
            return jsonify({"error": "run_not_found"}), 404
    if not W._can_access_run(run_id, run_data, W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404

    # Locate the card (same lookup the motion route uses).
    rr = run_data.get("recognition_report") or {}
    ranked = rr.get("ranked_achievements") or []
    card = None
    for ra in ranked:
        ach = ra.get("achievement") or {}
        if ach.get("swim_id") == card_id or ra.get("id") == card_id:
            card = {**ach, **ra}
            break
    if card is None:
        for c in run_data.get("cards") or []:
            if c.get("swim_id") == card_id or c.get("id") == card_id:
                card = c
                break
    if card is None:
        return jsonify({"error": "card_not_found"}), 404

    # Audio approval gate: only speak a human-approved (or posted) card.
    ws = W._get_wf_store()
    state = ws.load(run_id).get(card_id) if ws is not None else None
    approved = state is not None and state.status in (W.CardStatus.APPROVED, W.CardStatus.POSTED)
    if not approved:
        return jsonify(
            {
                "error": "not_approved",
                "user_message": (
                    "This card hasn't been approved yet. Approve the caption "
                    "first — voiceover only speaks approved content."
                ),
            }
        ), 409

    # Derive the verbatim caption text from approved state, server-side.
    text = ""
    if state is not None and state.edited_captions:
        # Honour the human's edits: join the saved slots in a stable order.
        # ``prev.*`` slots are the H-10 restore history, not current copy.
        parts = [
            state.edited_captions[k]
            for k in sorted(state.edited_captions)
            if state.edited_captions.get(k) and not str(k).startswith("prev.")
        ]
        text = "\n".join(p for p in parts if p).strip()
    if not text and W._build_caption_text is not None:
        try:
            text = W._build_caption_text(card, mode="caption_only")
        except Exception:
            text = ""
    if not text:
        return jsonify(
            {
                "error": "no_caption",
                "user_message": "This card has no caption text to speak.",
            }
        ), 422

    try:
        voice = os.environ.get("MEDIAHUB_VOICEOVER_VOICE", "").strip() or W._voiceover.DEFAULT_VOICE
        with W._render_slot("voiceover", card_id, timeout=W._RENDER_TRY_TIMEOUT):
            result = W._voiceover.synthesize(text, voice=voice, run_id=run_id)
    except W._RenderBusy:
        return W._render_busy_response("voiceover")
    except W._voiceover.VoiceoverError as e:
        return jsonify(
            {
                "error": "voiceover_unavailable",
                "kind": "infra_missing",
                "detail": str(e),
                "user_message": (
                    "Voiceover couldn't be generated right now (the speech "
                    "service is unavailable). Try again shortly."
                ),
            }
        ), 503
    except Exception as e:
        return jsonify({"error": "voiceover_failed", "detail": str(e)}), 500

    fmt = (request.args.get("format") or "").strip().lower()
    if fmt == "json":
        return jsonify(
            {
                "ok": True,
                "transcript": result.transcript,
                "voice": result.voice,
                "duration_ms": result.duration_ms,
                "cached": result.cached,
                "has_subtitles": bool(result.word_boundaries),
            }
        )
    if fmt == "srt":
        return send_file(
            str(result.srt_path),
            mimetype="application/x-subrip",
            as_attachment=False,
            download_name=f"{card_id}.srt",
        )
    return send_file(
        str(result.audio_path),
        mimetype="audio/mpeg",
        as_attachment=False,
        download_name=f"{card_id}.mp3",
    )


def api_venue_search(run_id: str):
    if not W._v8_ok:
        return jsonify({"error": "v8_unavailable"}), 503
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    from flask import request as _req

    q = _req.args.get("q", "").strip()
    if not q:
        # Default to the run's own venue / meet name so the picker can
        # offer backdrops with zero typing.
        run_data = W._load_run(run_id) or {}
        meet = run_data.get("meet") or {}
        q = str(meet.get("venue") or run_data.get("venue") or meet.get("name") or "").strip()
    if not q:
        return jsonify({"results": [], "query": ""})
    try:
        results = W._v8_search_venue(q, limit=8)
        # Venue thumbnails are cross-origin (Wikimedia/Openverse); the app CSP
        # pins ``img-src 'self'``, so the picker can't load them directly —
        # they'd show as broken tiles. Route each preview through the
        # first-party stock-thumb proxy (the same allow-listed, SSRF-safe path
        # the stock browser uses). ``direct_url`` is left raw: the import
        # downloads it server-side, where the CSP doesn't apply.
        from urllib.parse import quote as _quote

        from mediahub.elements import stock as _stock

        thumb_proxy = url_for("api_stock_thumb")
        out = []
        raw_thumbs = []
        for r in results:
            d = r.to_dict() if hasattr(r, "to_dict") else dict(r)
            tu = str(d.get("thumb_url") or "")
            if tu.startswith(("http://", "https://")):
                raw_thumbs.append(tu)
                d["thumb_url"] = f"{thumb_proxy}?u={_quote(tu, safe='')}"
            out.append(d)
        # Warm the cache in the background so the picker's proxied previews
        # are cache hits (the proxy never fetches on a request thread).
        if raw_thumbs:
            _stock.prewarm_thumbs(raw_thumbs)
        return jsonify({"query": q, "results": out})
    except Exception as e:
        return jsonify({"error": str(e), "results": []}), 500


def api_run_certificates_job(run_id: str):
    """D-12: build the certificates ZIP in the background; ``202`` +
    ``{job_id, poll_url}``.

    The synchronous ``certificates.zip`` route renders one Chromium PDF
    per approved card inside the request — the same held-connection
    failure the reel/motion routes already cured with the disk-backed
    job store. Fail-fast gates (tenant, approved set) stay in the
    request thread; the worker reports "Rendering certificate N of M"
    via the shared poll route, and completion carries the download URL
    served by the existing (equally gated) GET route."""
    if not W._can_access_run(run_id, W._load_run(run_id), W._active_profile_id()):
        return jsonify({"error": "run_not_found"}), 404
    data, pid, prof, approved = W._certificates_approved_for(run_id)
    if data is None:
        return jsonify({"error": "run_not_found"}), 404
    if not approved:
        return (
            jsonify(
                {
                    "error": "no_approved_cards",
                    "user_message": (
                        "Certificates are printed from approved achievements only "
                        "— approve some cards first, then come back."
                    ),
                }
            ),
            409,
        )
    print_mode = (request.args.get("print") or "").strip().lower() in W._TRUTHY
    bleed_mm = W._clamp_float(request.args.get("bleed"), default=3.0, lo=0.0, hi=10.0)
    crop_marks = (request.args.get("marks") or "1").strip().lower() in W._TRUTHY
    colour_bar = (
        request.args.get("colorbar") or request.args.get("colourbar") or "1"
    ).strip().lower() in W._TRUTHY
    want_cmyk = (request.args.get("cmyk") or "").strip().lower() in W._TRUTHY

    job_id = W.uuid.uuid4().hex
    out_dir = W.DATA_DIR / "print_exports" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"certificates-{job_id}.zip"
    kind_name = "print" if print_mode else "certificates"
    # url_for needs the request context — resolve before the thread.
    download_url = url_for("pack_certificates_zip", run_id=run_id, file=job_id)
    job: dict = {
        "id": job_id,
        "kind": "certificates",
        "status": "running",
        "error": "",
        "user_message": "",
        "video_url": "",
        "run_id": run_id,
        "zip_path": str(zip_path),
        "download_url": "",
        "download_name": f"{kind_name}-{run_id}.zip",
        "total": len(approved),
        "done": 0,
        "current": "",
        "created_at": time.time(),
        "owner_pid": W._active_profile_id() or "",
    }
    W._variant_jobs_gc()
    W._variant_job_save(job)

    def _worker() -> None:
        try:
            with W._job_heartbeat(job):
                # The render slot is taken per certificate inside
                # _write_certificates_zip (use_render_slot=True) with the
                # queue timeout — a 202-accepted job queues like the
                # render-all batch worker instead of fast-failing, and
                # never starves other renders for the whole ZIP build.

                def _progress(i: int, total: int, name: str) -> None:
                    job["done"] = i
                    job["total"] = total
                    job["current"] = str(name or "")
                    W._variant_job_save(job)

                with open(zip_path, "wb") as fh:
                    W._write_certificates_zip(
                        fh,
                        run_id,
                        data,
                        pid,
                        prof,
                        approved,
                        print_mode=print_mode,
                        bleed_mm=bleed_mm,
                        crop_marks=crop_marks,
                        colour_bar=colour_bar,
                        want_cmyk=want_cmyk,
                        progress=_progress,
                        use_render_slot=True,
                    )
            job["status"] = "done"
            job["done"] = int(job.get("total") or len(approved))
            job["current"] = ""
            job["download_url"] = download_url
        except W._RenderBusy:
            job["status"] = "error"
            job["error"] = "renderer_busy"
            job["user_message"] = "Another export is rendering right now — try again in a minute."
        except Exception as e:
            W.log.exception("certificates job %s failed", job_id[:8])
            job["status"] = "error"
            job["error"] = str(e)
            job["user_message"] = (
                "We couldn't finish building the certificates just now. "
                "Give it a moment and try again."
            )
        W._variant_job_save(job)

    W.threading.Thread(target=_worker, name=f"certs-{job_id[:8]}", daemon=True).start()
    return (
        jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "poll_url": url_for("api_reel_job_status", job_id=job_id),
                "total": len(approved),
            }
        ),
        202,
    )


def register(app) -> None:
    """Attach this surface's routes with their ORIGINAL endpoint names."""
    app.add_url_rule("/api/runs/<run_id>/status", endpoint="api_status", view_func=api_status)
    app.add_url_rule(
        "/api/runs/<run_id>/why/<int:ach_index>", endpoint="api_why_card", view_func=api_why_card
    )
    app.add_url_rule(
        "/api/runs/<run_id>/recognition", endpoint="api_recognition", view_func=api_recognition
    )
    app.add_url_rule(
        "/api/runs/<run_id>/swim/<swim_id>/trace",
        endpoint="api_swim_trace",
        view_func=api_swim_trace,
    )
    app.add_url_rule(
        "/api/runs/<run_id>/swim/<swim_id>/caption",
        endpoint="api_live_caption",
        view_func=api_live_caption,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/swim/<swim_id>/caption/assist",
        endpoint="api_caption_assist",
        view_func=api_caption_assist,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/swim/<swim_id>/caption/platforms",
        endpoint="api_caption_platforms",
        view_func=api_caption_platforms,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/translate",
        endpoint="api_card_translate",
        view_func=api_card_translate,
        methods=["POST"],
    )
    app.add_url_rule("/api/runs/<run_id>/cards", endpoint="api_cards", view_func=api_cards)
    app.add_url_rule("/api/runs/<run_id>/trust", endpoint="api_trust", view_func=api_trust)
    app.add_url_rule("/api/runs/<run_id>/export", endpoint="api_export", view_func=api_export)
    app.add_url_rule(
        "/api/runs/<run_id>/card/<path:card_id>/download",
        endpoint="api_card_download",
        view_func=api_card_download,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/brand-check",
        endpoint="api_card_brand_check",
        view_func=api_card_brand_check,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/brand-check/advise",
        endpoint="api_card_brand_advise",
        view_func=api_card_brand_advise,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/brand-check/autofix",
        endpoint="api_card_brand_autofix",
        view_func=api_card_brand_autofix,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/swims/promote",
        endpoint="api_promote_swim",
        view_func=api_promote_swim,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/bulk-status",
        endpoint="api_cards_bulk_status",
        view_func=api_cards_bulk_status,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/bulk-export",
        endpoint="api_cards_bulk_export",
        view_func=api_cards_bulk_export,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/bulk-download",
        endpoint="api_cards_bulk_download",
        view_func=api_cards_bulk_download,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/reactions",
        endpoint="api_card_reaction_toggle",
        view_func=api_card_reaction_toggle,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reactions",
        endpoint="api_run_reactions",
        view_func=api_run_reactions,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/turn-into",
        endpoint="api_turn_into",
        view_func=api_turn_into,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/turn-into-status/<job_id>",
        endpoint="api_turn_into_status",
        view_func=api_turn_into_status,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/turn-into/<pack_id>/caption",
        endpoint="api_turn_into_edit_caption",
        view_func=api_turn_into_edit_caption,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/newsletter",
        endpoint="api_run_newsletter",
        view_func=api_run_newsletter,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/photo",
        endpoint="api_card_photo_upload",
        view_func=api_card_photo_upload,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/photo-confirm",
        endpoint="api_card_photo_confirm",
        view_func=api_card_photo_confirm,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/clip-unlink",
        endpoint="api_card_clip_unlink",
        view_func=api_card_clip_unlink,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/venue-import",
        endpoint="api_venue_import",
        view_func=api_venue_import,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/element-suggestions",
        endpoint="api_element_suggestions",
        view_func=api_element_suggestions,
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/elements",
        endpoint="api_card_elements",
        view_func=api_card_elements,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/create-graphic",
        endpoint="api_create_graphic",
        view_func=api_create_graphic,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/sponsor-variant-job",
        endpoint="api_sponsor_variant_job",
        view_func=api_sponsor_variant_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/regenerate",
        endpoint="api_regenerate_graphic",
        view_func=api_regenerate_graphic,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/cards/<card_id>/regenerate-variants",
        endpoint="api_regenerate_variants",
        view_func=api_regenerate_variants,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/motion",
        endpoint="api_card_motion",
        view_func=api_card_motion,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/motion-job",
        endpoint="api_card_motion_job",
        view_func=api_card_motion_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/motion-batch-job",
        endpoint="api_card_motion_batch_job",
        view_func=api_card_motion_batch_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/motion-file",
        endpoint="api_card_motion_file",
        view_func=api_card_motion_file,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/motion/manifest",
        endpoint="api_card_motion_manifest",
        view_func=api_card_motion_manifest,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/thumb.png",
        endpoint="api_card_thumb",
        view_func=api_card_thumb,
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/reformat",
        endpoint="api_card_reformat",
        view_func=api_card_reformat,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/preflight",
        endpoint="api_card_preflight",
        view_func=api_card_preflight,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/print",
        endpoint="api_card_print",
        view_func=api_card_print,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/merch-mockup",
        endpoint="api_card_merch_mockup",
        view_func=api_card_merch_mockup,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/assistant",
        endpoint="api_card_assistant",
        view_func=api_card_assistant,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/assistant/suggestions",
        endpoint="api_assistant_suggestions",
        view_func=api_assistant_suggestions,
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel",
        endpoint="api_run_reel",
        view_func=api_run_reel,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/charts",
        endpoint="api_run_charts",
        view_func=api_run_charts,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/chart/<chart_id>",
        endpoint="api_run_chart_svg",
        view_func=api_run_chart_svg,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/chart/<chart_id>/caption",
        endpoint="api_run_chart_caption",
        view_func=api_run_chart_caption,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/charts/recommend",
        endpoint="api_run_charts_recommend",
        view_func=api_run_charts_recommend,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/charts/insights",
        endpoint="api_run_charts_insights",
        view_func=api_run_charts_insights,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel-job",
        endpoint="api_run_reel_job",
        view_func=api_run_reel_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel-batch",
        endpoint="api_run_reel_batch",
        view_func=api_run_reel_batch,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel-file",
        endpoint="api_run_reel_file",
        view_func=api_run_reel_file,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel-manifest",
        endpoint="api_run_reel_manifest",
        view_func=api_run_reel_manifest,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/render-all-job",
        endpoint="api_run_render_all_job",
        view_func=api_run_render_all_job,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/bulk-export",
        endpoint="api_run_bulk_export",
        view_func=api_run_bulk_export,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/bulk-export/file",
        endpoint="api_run_bulk_export_file",
        view_func=api_run_bulk_export_file,
    )
    app.add_url_rule(
        "/api/runs/<run_id>/export-share",
        endpoint="api_run_export_share",
        view_func=api_run_export_share,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel/comments",
        endpoint="api_reel_comments",
        view_func=api_reel_comments,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/reel/comments/<comment_id>",
        endpoint="api_reel_comment_mutate",
        view_func=api_reel_comment_mutate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/comments",
        endpoint="api_collab_comments",
        view_func=api_collab_comments,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/comments/<comment_id>",
        endpoint="api_collab_comment_mutate",
        view_func=api_collab_comment_mutate,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/revisions",
        endpoint="api_card_revisions",
        view_func=api_card_revisions,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/revisions/diff",
        endpoint="api_card_revisions_diff",
        view_func=api_card_revisions_diff,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/revisions/restore",
        endpoint="api_card_revisions_restore",
        view_func=api_card_revisions_restore,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/locks",
        endpoint="api_card_locks",
        view_func=api_card_locks,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/shares",
        endpoint="api_run_shares",
        view_func=api_run_shares,
        methods=["GET", "POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/shares/<token>/revoke",
        endpoint="api_run_share_revoke",
        view_func=api_run_share_revoke,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/card/<card_id>/voiceover",
        endpoint="api_card_voiceover",
        view_func=api_card_voiceover,
        methods=["POST", "GET"],
    )
    app.add_url_rule(
        "/api/runs/<run_id>/venue-search", endpoint="api_venue_search", view_func=api_venue_search
    )
    app.add_url_rule(
        "/api/runs/<run_id>/certificates-job",
        endpoint="api_run_certificates_job",
        view_func=api_run_certificates_job,
        methods=["POST"],
    )
