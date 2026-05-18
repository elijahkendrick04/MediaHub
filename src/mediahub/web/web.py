"""
V4 web app &mdash; Flask backend + single-file UI.

Routes:
  GET  /                       Home (recent runs, profiles, status)
  GET  /upload                 Upload form
  POST /upload                 Kick off pipeline in a background thread
  GET  /runs/<id>              Wait/poll page; redirects to /review when done
  GET  /api/runs/<id>/status   JSON progress for poll
  GET  /review/<id>            Review queue (cards) + trust UI
  GET  /api/runs/<id>/cards    JSON of cards
  GET  /api/runs/<id>/trust    JSON of trust report
  GET  /api/runs/<id>/export   JSON evidence + audit export
  GET  /ground-truth/<id>      Ground-truth evaluation page
  POST /ground-truth/<id>      Submit moments and get precision/recall
  GET  /privacy                Data inventory + delete controls
  POST /privacy/run/<id>/delete   Delete a single run
  POST /privacy/cache/clear        Clear PB cache
  GET  /research               Research roadmap page (parser priorities)
  GET  /healthz                health check

State: SQLite at data.db (so publish_website snapshots it across deploys)
       + uploads_v4/ (transient HY3) + runs/<id>.json (full run)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid

log = logging.getLogger(__name__)
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flask import (
    Flask, request, redirect, url_for, render_template_string,
    jsonify, abort, send_file, Response, session, make_response,
)
from markupsafe import escape as _h

from mediahub.pipeline.pipeline_v4 import run_pipeline_v4, PipelineRunV4
from .humanise import humanise as _humanise, format_post_angle as _format_angle, humanise_status as _humanise_status
from .club_profile import (
    ClubProfile, list_profiles, load_profile, save_profile,
    seed_default_profiles,
)
from .ground_truth import evaluate as gt_evaluate
from .canonical import Meet
from .bounded_cache import BoundedCache

# V7 imports
try:
    from mediahub.club_platform.content_types import REGISTRY as _CT_REGISTRY, ContentType as _ContentType
    from mediahub.club_platform.athlete_spotlight import build_spotlight_pack, list_swimmers_in_run
    from mediahub.club_platform.stubs import WeekendPreviewStub, SponsorPostStub, SessionUpdateStub, FreeTextStub
    _club_platform_ok = True
except ImportError:
    _club_platform_ok = False

try:
    from mediahub.brand.kit import BrandKit
    from mediahub.brand.tone import Tone, TONE_META, tone_from_str
    from mediahub.brand.templates import get_default_templates, render_template as _render_brand_template
    from mediahub.brand.store import load_brand, save_brand
    from mediahub.brand.apply import apply_brand
    _brand_ok = True
except ImportError:
    _brand_ok = False

try:
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.pack import build_content_pack
    _workflow_ok = True
except ImportError:
    _workflow_ok = False


# V7.3 imports
try:
    from mediahub.content_pack.builder import build_grouped_pack as _build_grouped_pack
    from mediahub.recognition.copy_text import build_caption_text as _build_caption_text
    from mediahub.recognition.weekend_in_numbers import build_weekend_in_numbers as _build_win
    from mediahub.voice.store import load_voice_profile as _load_voice_profile, save_voice_profile as _save_voice_profile
    from mediahub.voice.profile import VoiceProfile as _VoiceProfile, VoiceExemplar as _VoiceExemplar
    _v73_ok = True
except ImportError as _v73_err:
    _v73_ok = False
    _build_grouped_pack = None
    _build_caption_text = None
    _build_win = None
    _load_voice_profile = None
    _save_voice_profile = None

# V9: "Why this card?" explainer.
# The legacy rule-based explainer (recognition/explainer.py) is no longer
# called — _build_card_explanation now requires an AI provider and surfaces
# an honest "AI unavailable: configure a provider" message when none is
# configured, instead of falling back to a hardcoded type-phrase template.


# LLM-derived performance-context sentence, keyed by
# (swimmer, event, time, meet level) so page re-renders are cheap.
# Bounded LRU so a busy day can't fill RAM with cache strings.
_perf_context_cache: BoundedCache = BoundedCache(max_size=512)


def _llm_performance_context(achievement: dict, meet_context: Optional[dict] = None) -> str:
    """Return a 1-sentence LLM judgement on whether this swim is good *for this swimmer's level*.

    The model gets a natural-language description of the swim (no JSON
    blob) plus a `research_web` tool it can call on its own to verify
    elite recognition. Honours the user's provider preference
    (Claude / Gemini); empty string when none is configured.
    """
    try:
        from mediahub.ai_core import (
            ask_with_tools, narrate_achievement, narrate_meet,
            ProviderNotConfigured, ProviderError,
        )
    except Exception:
        return ""

    swimmer = (achievement.get("swimmer_name") or "").strip()
    event = (achievement.get("event") or "").strip()
    time_s = (achievement.get("time") or "").strip()
    if not (swimmer and event and time_s):
        return ""

    meet = meet_context or {}
    cache_key = "|".join([
        swimmer.lower(), event.lower(), time_s,
        str(meet.get("level", "")), str(meet.get("governing_body", "")),
    ])
    cached = _perf_context_cache.get(cache_key)
    if cached is not None:
        return cached

    # Natural-language prompt — no JSON. The model reads it and uses
    # research_web on its own if it wants to verify elite recognition.
    swim_prose = narrate_achievement(achievement, meet=meet or None)
    meet_prose = narrate_meet(meet or None)
    user = swim_prose + (("\n\nMeet context: " + meet_prose) if meet_prose else "")
    user += (
        "\n\nWrite ONE short sentence (max 25 words) putting this time in "
        "context FOR THIS SWIMMER'S LEVEL. Use research_web if you need "
        "to verify whether the swimmer is recognisably elite."
    )

    system = (
        "You are a swimming performance analyst. Output exactly one sentence "
        "putting a swim in context for the swimmer's level. No questions, "
        "no lists, no markdown, no preamble. Reason only from the swim "
        "details I give you and any web evidence you fetch via "
        "research_web. Never invent PBs, ages, clubs, rankings, or "
        "biographical facts. If you cite a research result, mention the "
        "domain in parentheses, e.g. '(swimmingresults.org)'."
    )

    research_tool = [{
        "name": "research_web",
        "description": (
            "Search the web for evidence about this swimmer (elite "
            "recognition, PB history). Returns title/url/snippet/domain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    }]

    def _tool(name, inp):
        if name != "research_web":
            return "(unknown tool)"
        q = (inp.get("query") or "").strip()
        if not q:
            return "(empty query)"
        try:
            from mediahub.context_engine.research import ResearchClient
            client = ResearchClient(num_results=4)
            hits = client.search(q, num=4)
        except Exception as e:
            return f"(search failed: {e})"
        evidence = []
        for h in hits:
            snip = (h.snippet or "").strip()
            if not snip:
                continue
            evidence.append({
                "title": (h.title or "")[:160],
                "url":   h.url,
                "snippet": snip[:300],
                "domain":  h.domain,
            })
        return json.dumps({"hits": evidence}, ensure_ascii=False)

    out = ""
    try:
        convo = ask_with_tools(
            system=system, user=user,
            tools=research_tool, on_tool_call=_tool,
            max_tokens=200, max_rounds=3,
        )
        out = (convo.text or "").strip()
    except (ProviderNotConfigured, ProviderError):
        out = ""
    except Exception:
        out = ""
    if out:
        for ln in out.splitlines():
            ln = ln.strip().lstrip("-* ").strip()
            if ln:
                out = ln
                break
    if out.lower().startswith(("i need", "i'd need", "please provide",
                                "can you provide", "could you",
                                "i don't have")):
        out = ""
    _perf_context_cache[cache_key] = out
    return out


# "Why this card?" LLM cache, keyed by (swim_id, swimmer_name, event,
# time, rank, meet_level). Bounded LRU — values are small dicts.
_explanation_cache: BoundedCache = BoundedCache(max_size=512)


def _llm_build_explanation(achievement: dict, factors: list,
                            rank: Optional[int] = None,
                            meet_context: Optional[dict] = None
                            ) -> tuple[Optional[dict], Optional[str]]:
    """Have the LLM write the headline + bullets for "Why this card?"
    based on the achievement and the ranker's factors.

    Returns (result, error). ``result`` is ``{"headline", "bullets"}``
    on success; ``error`` is a human-readable string explaining WHY the
    AI didn't answer (no provider configured, rate-limit, etc.) so the
    UI can show "your AI is unavailable: configure a provider in
    Settings" instead of falling back to a hardcoded template.
    """
    try:
        from mediahub.ai_core import (
            ask_with_tools, narrate_achievement, narrate_meet,
            ProviderNotConfigured, ProviderError,
        )
    except Exception as e:
        return None, f"ai_core import failed: {e}"
    a = achievement or {}
    swim_prose = narrate_achievement(a, meet=meet_context or None)
    if not swim_prose:
        return None, "not enough achievement detail to narrate"

    # English summary of the factors — no JSON dump.
    factor_lines: list[str] = []
    for f in (factors or []):
        if hasattr(f, "to_dict"):
            try:
                f = f.to_dict()
            except Exception:
                pass
        if not isinstance(f, dict):
            continue
        ps = (f.get("plain_summary") or f.get("reason") or "").strip()
        if not ps:
            continue
        try:
            val = float(f.get("value", 0.0) or 0.0)
            wt = float(f.get("weight", 0.0) or 0.0)
            contrib = val * wt
        except (TypeError, ValueError):
            contrib = 0.0
        factor_lines.append(f"- {ps} (contribution {contrib:.2f})")
    factors_prose = "\n".join(factor_lines[:8]) or "(no factor list)"

    meet_prose = narrate_meet(meet_context or None)
    user_prose = (
        swim_prose
        + (("\n\nMeet context: " + meet_prose) if meet_prose else "")
        + "\n\nRanker factors that contributed (highest first):\n" + factors_prose
        + (f"\n\nThis swim ranked #{int(rank)} overall." if isinstance(rank, int) else "")
        + "\n\nPlease emit one `submit_explanation` call with a "
          "15-25 word headline plus 3-5 short bullets covering the "
          "reasons. Use ONLY the facts above — never invent ranker "
          "factors that aren't listed."
    )

    system = (
        "You are MediaHub's content-rationale writer. Your job is to "
        "tell the user, in plain English, why a specific swim got "
        "selected as a content card. Be specific, grounded, no fluff. "
        "Never invent achievements or factors. Always emit exactly one "
        "`submit_explanation` tool call."
    )
    tool = [{
        "name": "submit_explanation",
        "description": (
            "Submit the final explanation: a one-sentence headline plus "
            "3-5 short factor bullets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "bullets":  {"type": "array",
                              "items": {"type": "string"}},
            },
            "required": ["headline", "bullets"],
        },
    }]

    captured: dict[str, Any] = {}

    def _tool(name, inp):
        if name == "submit_explanation":
            hl = (inp.get("headline") or "").strip()
            bullets = inp.get("bullets") or []
            if isinstance(bullets, str):
                bullets = [bullets]
            bullets = [str(b).strip() for b in bullets if str(b).strip()]
            captured["headline"] = hl
            captured["bullets"] = bullets[:6]
            return "ok"
        return "(unknown tool)"

    try:
        ask_with_tools(
            system=system, user=user_prose,
            tools=tool, on_tool_call=_tool,
            max_tokens=500, max_rounds=2,
        )
    except ProviderNotConfigured as e:
        return None, str(e)
    except ProviderError as e:
        return None, f"AI provider error: {e}"
    except Exception as e:
        return None, f"AI call failed: {e}"
    if not captured.get("headline"):
        return None, "AI returned no explanation."
    return ({
        "headline": captured["headline"],
        "bullets":  captured.get("bullets") or [],
    }, None)


def _build_source_lines_from_evidence(achievement: dict) -> list[dict]:
    """Pull up to 3 verbatim evidence quotes off the achievement."""
    out: list[dict] = []
    for ev in (achievement.get("evidence") or [])[:3]:
        if not isinstance(ev, dict):
            try:
                ev = ev.to_dict()
            except Exception:
                continue
        statement = (ev.get("statement") or "").strip()
        if not statement:
            continue
        source_name = (ev.get("source_name") or "").strip()
        source_type = (ev.get("source_type") or "").strip()
        if source_name and source_type and source_name != source_type:
            label = f"{source_type} ({source_name.replace('_', ' ')})"
        elif source_name:
            label = source_name
        elif source_type:
            label = source_type.replace("_", " ")
        else:
            label = "source"
        out.append({
            "file_offset": ev.get("file_offset"),
            "raw_text":    statement,
            "label":       label,
        })
    return out


def _build_card_explanation(ra: dict, meet_context: Optional[dict] = None) -> dict:
    """Build the "Why this card?" explanation dict for a ranked-achievement.

    Headline + bullets are written by the active LLM (Claude /
    Gemini) using a `submit_explanation` tool — no template strings,
    no hardcoded type-phrase dictionary. Source lines remain verbatim
    quotes from evidence (no LLM reasoning involved). Performance
    context is the LLM's level-context sentence.

    Falls back to the legacy rule-based explainer ONLY when no LLM
    provider is configured at all, so tests + offline dev still work.
    """
    achievement = ra.get("achievement") or {}
    factors = ra.get("factors") or []
    rank = ra.get("rank")

    cache_key_parts = [
        (achievement.get("swim_id") or ""),
        (achievement.get("swimmer_name") or ""),
        (achievement.get("event") or ""),
        (achievement.get("time") or ""),
        str(rank or ""),
        str((meet_context or {}).get("level", "")),
    ]
    cache_key = "|".join(cache_key_parts)
    cached = _explanation_cache.get(cache_key)
    if cached is not None:
        # Re-read perf context separately — its cache key is finer-grained.
        exp = dict(cached)
        try:
            ctx = _llm_performance_context(achievement, meet_context)
            if ctx:
                exp["performance_context"] = ctx
        except Exception:
            pass
        return exp

    llm_exp, llm_error = _llm_build_explanation(achievement, factors, rank, meet_context)
    if llm_exp is not None:
        exp = {
            "headline":     llm_exp["headline"],
            "bullets":      llm_exp["bullets"],
            "source_lines": _build_source_lines_from_evidence(achievement),
        }
    else:
        # No hardcoded template here — the user explicitly wants the AI
        # to do the reasoning, full stop. If no provider can answer we
        # tell them why and how to fix it.
        exp = {
            "headline":     "AI explanation unavailable.",
            "bullets":      [],
            "source_lines": _build_source_lines_from_evidence(achievement),
            "ai_error":     llm_error or "No AI provider is configured.",
        }
    _explanation_cache[cache_key] = exp

    try:
        ctx = _llm_performance_context(achievement, meet_context)
        if ctx:
            exp["performance_context"] = ctx
    except Exception:
        pass
    return exp


def _render_why_this_card(
    ra: dict,
    *,
    card_uuid: str,
    run_id: str = "",
) -> str:
    """Render the "Why this card?" disclosure HTML.

    Phase 1.4 changes the visibility default: the disclosure now opens
    by default (``<details open>`` below) because the editorial
    reasoning is the most marketable surface the product has — no
    horizontal player can match per-card data-grounded "why".

    The block is grounded: the headline / bullets come from the
    ranker's factors and the source_lines are quoted verbatim from
    the achievement's evidence entries. Two buttons:

      • Copy reasoning — clipboard the plain-text reasoning.
      • Use in next caption — when ``run_id`` is supplied, re-prompt
        the caption LLM with the explanation as required content so
        the visible intelligence flows back into the generated copy.
    """
    exp = _build_card_explanation(ra)
    headline = _h(exp.get("headline", ""))
    bullets = exp.get("bullets") or []
    source_lines = exp.get("source_lines") or []

    bullets_html = ""
    for b in bullets:
        bullets_html += f'<li style="margin-bottom:3px">{_h(b)}</li>'
    if not bullets_html:
        bullets_html = ""

    src_html = ""
    for sl in source_lines:
        label = _h(sl.get("label", "source"))
        raw = _h(sl.get("raw_text", ""))
        offset = sl.get("file_offset")
        offset_tag = (
            f'<span class="muted" style="font-size:10px;margin-left:6px">#{int(offset)}</span>'
            if isinstance(offset, int) else ""
        )
        src_html += (
            f'<li style="margin-bottom:6px">'
            f'<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px">'
            f'{label}{offset_tag}</div>'
            f'<blockquote style="margin:2px 0 0 0;padding:6px 10px;border-left:2px solid var(--accent);'
            f'background:rgba(34,211,238,0.05);font-family:ui-monospace,Menlo,monospace;font-size:12px;'
            f'color:var(--ink)">{raw}</blockquote>'
            f'</li>'
        )
    if not src_html:
        src_html = (
            '<li class="muted" style="font-size:12px">'
            'No source lines available &mdash; explanation is based on the ranker only.'
            '</li>'
        )

    # Plain-text payload for the "Copy reasoning" button (kept in a hidden textarea
    # so the copy works without an extra round-trip to the server).
    plain_lines = [exp.get("headline", "")]
    for b in bullets:
        plain_lines.append(f"- {b}")
    if source_lines:
        plain_lines.append("")
        plain_lines.append("Source lines:")
        for sl in source_lines:
            plain_lines.append(f"  [{sl.get('label','source')}] {sl.get('raw_text','')}")
    plain_text = _h("\n".join(p for p in plain_lines if p is not None))

    bullets_block = (
        f'<ul style="margin:6px 0 10px 0;padding-left:20px;font-size:12px;color:var(--ink-dim)">{bullets_html}</ul>'
        if bullets_html else ""
    )

    # LLM-derived performance context (Olympic-level vs county-level
    # judgement). Rendered as a distinct callout so reviewers can see at a
    # glance that this is the LLM's read, not a grounded factor.
    perf_ctx = (exp.get("performance_context") or "").strip()
    perf_block = ""
    if perf_ctx:
        perf_block = (
            '<div style="margin:8px 0 10px 0;padding:8px 10px;background:rgba(34,211,238,0.06);'
            'border-left:2px solid #22D3EE;border-radius:4px">'
            '<div style="font-size:10px;text-transform:uppercase;color:#22D3EE;letter-spacing:0.5px;'
            'margin-bottom:2px">Performance context (AI)</div>'
            f'<div style="font-size:12px;color:var(--ink);line-height:1.4">{_h(perf_ctx)}</div>'
            '</div>'
        )

    # AI-unavailable callout. When the explanation couldn't be generated
    # (no provider configured, rate-limit on every provider, etc.) the
    # explainer attaches an `ai_error`. We render an honest red callout
    # pointing the user at the administrator (AI keys are env-var
    # configured at deploy time) instead of inventing a fake explanation.
    ai_error = (exp.get("ai_error") or "").strip()
    ai_error_block = ""
    if ai_error:
        ai_error_block = (
            '<div style="margin:8px 0 10px 0;padding:10px 12px;'
            'background:rgba(244,63,94,0.06);border-left:2px solid #f43f5e;'
            'border-radius:4px">'
            '<div style="font-size:10px;text-transform:uppercase;color:#f43f5e;'
            'letter-spacing:0.5px;margin-bottom:2px">AI unavailable</div>'
            f'<div style="font-size:12px;color:var(--ink);line-height:1.4">{_h(ai_error)}</div>'
            f'<div style="margin-top:6px;font-size:12px">'
            '<span style="color:var(--ink-dim)">AI features are configured by your administrator.</span>'
            '</div></div>'
        )

    # Phase 1.4 — "Use in next caption" button. Only rendered when
    # the caller passed run_id (so legacy callers without a run
    # context don't break). The button piggybacks on the existing
    # /api/runs/<run>/swim/<swim>/caption?include_why=1 channel.
    _swim_id_for_btn = ""
    try:
        ach_for_btn = ra.get("achievement") if isinstance(ra, dict) else None
        if isinstance(ach_for_btn, dict):
            _swim_id_for_btn = str(ach_for_btn.get("swim_id") or ra.get("id") or "")
        elif isinstance(ra, dict):
            _swim_id_for_btn = str(ra.get("id") or ra.get("swim_id") or "")
    except Exception:
        _swim_id_for_btn = ""
    use_in_caption_btn, use_in_caption_panel = _use_in_caption_html(
        run_id, _swim_id_for_btn, card_uuid,
    )

    # Phase 1.4: explainer is now DEFAULT-VISIBLE everywhere. The
    # editorial reasoning is the single most marketable surface MediaHub
    # has — no horizontal player can match data-grounded "why" per
    # card — so it shouldn't sit behind a click. The user can still
    # collapse it via the disclosure triangle if they need pure
    # caption-density.
    return f"""
<details open class="why-card" style="margin-top:10px;padding:10px 12px;background:rgba(139,92,246,0.06);
  border:1px solid rgba(139,92,246,0.25);border-radius:8px">
  <summary style="cursor:pointer;font-size:12px;font-weight:600;color:#A78BFA;user-select:none;
    list-style:none;display:flex;align-items:center;gap:6px">
    <span aria-hidden="true">&#9432;</span> Why this card?
  </summary>
  <div style="margin-top:8px">
    <div style="font-size:13px;color:var(--ink);line-height:1.45;margin-bottom:6px">{headline}</div>
    {bullets_block}
    {ai_error_block}
    {perf_block}
    <div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;
      margin-bottom:4px">Source lines (verbatim)</div>
    <ul style="list-style:none;margin:0;padding:0">{src_html}</ul>
    <div style="margin-top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="btn secondary" type="button" style="font-size:11px;padding:4px 10px"
        onclick="copyWhyCard(this, 'why-text-{card_uuid}')">Copy reasoning</button>
      <textarea id="why-text-{card_uuid}" style="display:none">{plain_text}</textarea>
      {use_in_caption_btn}
    </div>
    {use_in_caption_panel}
  </div>
</details>"""


def _use_in_caption_html(run_id: str, swim_id: str, card_uuid: str) -> tuple[str, str]:
    """Return (button_html, panel_html) for the "Use in next caption"
    affordance. Empty strings when ``run_id`` / ``swim_id`` are missing.

    The button POSTs to /api/runs/<run>/swim/<swim>/caption with
    ?include_why=1 — the endpoint then builds the same explanation,
    injects it as `_extra_instructions`, and returns the regenerated
    caption. The result lands in a small panel below the explainer.
    """
    if not run_id or not swim_id:
        return "", ""
    panel_id = f"why-cap-{card_uuid}"
    # JSON-encode the URLs so Jinja-style interpolation can't be
    # tricked by a card_id containing quotes — defence-in-depth.
    cap_url = url_for("api_live_caption", run_id=run_id, swim_id=swim_id)
    btn = (
        f'<button class="btn secondary" type="button" '
        f'style="font-size:11px;padding:4px 10px;'
        f'background:rgba(139,92,246,0.15);border-color:rgba(139,92,246,0.4);color:#A78BFA" '
        f'onclick="mhUseWhyInCaption(this, {json.dumps(cap_url)}, {json.dumps(panel_id)})">'
        f'Use in next caption</button>'
    )
    panel = (
        f'<div id="{panel_id}" data-mh-why-caption '
        f'style="display:none;margin-top:8px;padding:8px 10px;'
        f'background:rgba(139,92,246,0.04);border:1px dashed rgba(139,92,246,0.3);'
        f'border-radius:6px;font-size:12px;color:var(--ink);line-height:1.45"></div>'
    )
    return btn, panel

# V8: media generation engine
try:
    from mediahub.media_library.store import MediaLibraryStore as _V8MediaStore, get_store as _v8_get_media_store
    from mediahub.media_library.describe import parse_description as _v8_parse_description
    from mediahub.content_pack_visual.integration import (
        attach_visuals_to_pack as _v8_attach_visuals,
        create_visual_for_item as _v8_create_visual_for_item,
        visuals_dir_for_run as _v8_visuals_dir,
    )
    from mediahub.venue_search.search import search as _v8_search_venue
    _v8_ok = True
except ImportError as _v8_err:
    _v8_ok = False
    _V8MediaStore = None
    _v8_get_media_store = None
    _v8_parse_description = None
    _v8_attach_visuals = None
    _v8_create_visual_for_item = None
    _v8_visuals_dir = None
    _v8_search_venue = None


_SRC_ROOT = Path(__file__).resolve().parents[1]   # src/mediahub/ &mdash; local dev default
DATA_DIR   = Path(os.environ.get("DATA_DIR",   str(_SRC_ROOT)))
RUNS_DIR   = Path(os.environ.get("RUNS_DIR",   str(DATA_DIR / "runs_v4")))
UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", str(DATA_DIR / "uploads_v4")))
DB_PATH    = DATA_DIR / "data.db"               # MUST be data.db for publish snapshot
RESEARCH_DIR = DATA_DIR / "research"

RUNS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

# V7: workflow store (sidecar JSON per run)
_wf_store = None  # initialised after imports complete

def _get_wf_store() -> Optional['WorkflowStore']:
    global _wf_store
    if _wf_store is None:
        try:
            from mediahub.workflow.store import WorkflowStore as _WS
            _wf_store = _WS(RUNS_DIR)
        except ImportError:
            pass
    return _wf_store


# ---------------------------------------------------------------------
# In-process run registry (active progress) + persisted run metadata.
# ---------------------------------------------------------------------

# Both dicts are in-memory progress trackers — the source of truth for
# runs is the SQLite `runs` table + `runs_v4/<id>.json`; for Turn-Into
# jobs it's the pack file on disk. The dicts keep transient state (live
# log lines, in-flight status) and must NOT grow unbounded — Render
# free-tier is 512 MB and a slow leak here is one of the things that
# causes the ~6-minute container restarts the user reported in the
# gunicorn logs. Bound both with FIFO eviction.
_active_runs: dict[str, dict] = {}     # run_id -> {status, log[], profile, error}
_turn_into_jobs: dict[str, dict] = {}  # job_id -> {status, pack, error}
_active_lock = threading.Lock()
# In-process registry of running pipeline uploads. Bounded LRU so a
# leaking worker can't accumulate run dicts on Render's 512MB starter
# plan. The /api/runs/<id>/status endpoint falls back to the SQLite row
# when an entry has been evicted, so the user only loses in-memory
# progress-log streaming, never run completion.
_MAX_LOG_LINES = 200
_active_runs: BoundedCache = BoundedCache(max_size=64)
# Turn-Into job tracker. The "pack" payload is stripped at completion
# time (the pack is already persisted to disk by save_pack), so each
# entry stays small.
_turn_into_jobs: BoundedCache = BoundedCache(max_size=32)
# RLock so callers holding _active_lock can re-enter BoundedCache's
# own lock without deadlock.
_active_lock = threading.RLock()

# When either dict exceeds the threshold, the oldest finished entries
# are pruned to bring it back to the target. "Finished" = status in
# (done, error). Running rows are never evicted while in flight.
_ACTIVE_RUNS_LIMIT = 60
_ACTIVE_RUNS_TARGET = 40
_TURN_INTO_LIMIT = 30
_TURN_INTO_TARGET = 20
# Bound each run's log to the last N lines. A long pipeline emits ~20
# messages but a bug could spam thousands — cap defensively.
_RUN_LOG_LIMIT = 200


def _maybe_evict_active_runs() -> None:
    """Best-effort FIFO eviction of finished entries in _active_runs.

    Must be called with _active_lock held. Idempotent — no-op when
    the dict is under the threshold.
    """
    if len(_active_runs) <= _ACTIVE_RUNS_LIMIT:
        return
    # Oldest first. Use the started_at ISO string as the sort key.
    finished_ordered = sorted(
        (
            (rid, info)
            for rid, info in _active_runs.items()
            if info.get("status") in ("done", "error")
        ),
        key=lambda kv: kv[1].get("started_at", ""),
    )
    to_remove = max(0, len(_active_runs) - _ACTIVE_RUNS_TARGET)
    for rid, _ in finished_ordered[:to_remove]:
        _active_runs.pop(rid, None)


def _maybe_evict_turn_into_jobs() -> None:
    """Best-effort FIFO eviction of finished Turn-Into jobs. Must hold
    _active_lock."""
    if len(_turn_into_jobs) <= _TURN_INTO_LIMIT:
        return
    finished = [
        jid for jid, info in _turn_into_jobs.items()
        if info.get("status") in ("done", "error")
    ]
    to_remove = max(0, len(_turn_into_jobs) - _TURN_INTO_TARGET)
    for jid in finished[:to_remove]:
        _turn_into_jobs.pop(jid, None)


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    conn = _db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            finished_at TEXT,
            status TEXT,             -- queued | running | done | error
            profile_id TEXT,
            meet_name TEXT,
            our_swims INTEGER,
            n_cards INTEGER,
            n_queue INTEGER,
            error TEXT,
            file_name TEXT
        );
    """)
    conn.commit()
    conn.close()


_init_db()


def _prune_orphaned_runs():
    """Remove rows from `runs` whose JSON file no longer exists on disk.

    The published sandbox is ephemeral, so when we redeploy the database may
    survive while the runs/<id>.json files are gone. Without this prune the
    home page lists dozens of broken /review/<id> links.
    """
    try:
        conn = _db()
        rows = conn.execute("SELECT id FROM runs").fetchall()
        stale = []
        for r in rows:
            run_id = r["id"] if hasattr(r, "keys") else r[0]
            json_path = RUNS_DIR / f"{run_id}.json"
            if not json_path.exists():
                stale.append(run_id)
        if stale:
            conn.executemany("DELETE FROM runs WHERE id = ?", [(s,) for s in stale])
            conn.commit()
        conn.close()
    except Exception:
        pass


_prune_orphaned_runs()
# V8.2: seed_default_profiles is a no-op since the profiles UI was removed.
seed_default_profiles()


# ---------------------------------------------------------------------
# V6 PB audit serialisation helper
# ---------------------------------------------------------------------

def _serialise_pb_audit(pb_audit) -> Optional[dict]:
    """Serialise a V6 RunPBAudit to a JSON-safe dict.
    Returns None if pb_audit is None or serialisation fails.
    """
    if pb_audit is None:
        return None
    try:
        from swim_content_pb.audit import run_audit_to_dict
        return run_audit_to_dict(pb_audit)
    except Exception:
        return None


def _deserialise_pb_audit(data: dict) -> Optional[dict]:
    """Return the pb_audit dict as-is (already deserialised from JSON)."""
    return data or None


# ---------------------------------------------------------------------
# Run persistence helpers
# ---------------------------------------------------------------------

def _persist_run(run: PipelineRunV4, file_name: str) -> None:
    """Persist a finished run to runs_v4/<id>.json + DB row."""
    payload = {
        "run_id": run.run_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "profile_id": run.profile_id,
        "profile_display": run.profile_display,
        "file_name": file_name,
        "meet": run.canonical_meet.to_dict() if run.canonical_meet else None,
        "dispatch_log": run.dispatch_log.to_dict() if run.dispatch_log else None,
        "parse_warnings": run.parse_warnings,
        "parsed_swim_count": run.parsed_swim_count,
        "our_swim_count": run.our_swim_count,
        "other_swim_count": run.other_swim_count,
        "n_swimmers_ours": run.n_swimmers_ours,
        "pb_fetch_ok": run.pb_fetch_ok,
        "pb_fetch_failed": run.pb_fetch_failed,
        "pb_fetch_errors": run.pb_fetch_errors,
        "detector_summary": run.detector_summary,
        "self_check": run.self_check,
        "standards_meta": run.standards_meta,
        "cards": [c.to_dict() for c in run.cards],
        "trust": run.trust.to_dict() if run.trust else None,
        "ground_truth_report": run.ground_truth_report,
        "recognition_report": run.recognition_report,
        "recognition_error": run.recognition_error,
        "progress_log": run.progress_log,
        "error": run.error,
        # V6 PB audit (optional &mdash; None when fetch_pbs=False)
        "pb_audit": _serialise_pb_audit(getattr(run, "pb_audit", None)),
    }
    out = RUNS_DIR / f"{run.run_id}.json"
    out.write_text(json.dumps(payload, indent=2, default=str))

    n_cards = len(run.cards)
    n_queue = sum(1 for c in run.cards if c.bucket == "queue")
    meet_name = run.canonical_meet.name if run.canonical_meet else "(unknown)"
    status = "error" if run.error else "done"
    conn = _db()
    conn.execute(
        """INSERT OR REPLACE INTO runs
           (id, created_at, finished_at, status, profile_id, meet_name,
            our_swims, n_cards, n_queue, error, file_name)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (run.run_id, run.started_at, run.finished_at, status,
         run.profile_id, meet_name, run.our_swim_count, n_cards, n_queue,
         run.error, file_name),
    )
    conn.commit()
    conn.close()


def _load_run(run_id: str) -> Optional[dict]:
    p = RUNS_DIR / f"{run_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _run_state(run_id: str) -> str:
    """Return one of ``unknown`` | ``in_progress`` | ``done``.

    "unknown" = no DB row and no JSON file. "in_progress" = DB row says
    queued/running OR an entry exists in the in-memory _active_runs dict.
    "done" = JSON file is on disk.

    Used by routes that depend on _load_run to render a friendly
    "still processing" page instead of a misleading 404 while the
    background worker is still running.
    """
    # JSON file present &rarr; run is fully persisted.
    if (RUNS_DIR / f"{run_id}.json").exists():
        return "done"
    # In-memory active dict &rarr; worker thread is alive in THIS process.
    # copy_value takes BoundedCache's own lock and returns a snapshot,
    # so we don't hold a lock across the downstream status check.
    active = _active_runs.copy_value(run_id)
    if active:
        status = (active.get("status") or "").lower()
        if status in ("queued", "running"):
            return "in_progress"
        if status == "error":
            return "done"  # error is "finished" &mdash; caller can read it from DB
    # Fall back to DB row (handles process restart between worker death
    # and persistence &mdash; rare, but possible).
    try:
        conn = _db()
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
    except Exception:
        return "unknown"
    if not row:
        return "unknown"
    status = (row["status"] or "").lower()
    if status in ("queued", "running"):
        return "in_progress"
    return "done"


def _in_progress_page(run_id: str, return_url_endpoint: str = "review") -> str:
    """Return a friendly HTML page that auto-refreshes every 4 seconds."""
    try:
        retry_url = url_for(return_url_endpoint, run_id=run_id)
    except Exception:
        retry_url = ""
    status_url = url_for("api_status", run_id=run_id)
    return f"""
<div style="text-align:center;padding:64px 24px">
  <div class="mh-spinner" style="margin:0 auto 24px"></div>
  <h1 style="margin-bottom:10px">Still processing your run</h1>
  <p class="dim" style="max-width:480px;margin:0 auto 24px">
    The pipeline is reading the file, finding your athletes, and drafting
    captions. This usually takes 20&ndash;60 seconds. We&rsquo;ll auto-refresh
    when it&rsquo;s ready.
  </p>
  <a class="btn secondary" href="{retry_url or status_url}">Refresh now</a>
</div>
<script>
  setTimeout(function() {{ location.reload(); }}, 4000);
</script>
"""


def _delete_run(run_id: str) -> bool:
    p = RUNS_DIR / f"{run_id}.json"
    existed = p.exists()
    if existed:
        p.unlink()
    conn = _db()
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()
    return existed


# ---------------------------------------------------------------------
# Schedule (Buffer) modal &mdash; shared between classic + grouped pack pages
# ---------------------------------------------------------------------

def _schedule_modal_html() -> str:
    """Return the hidden Buffer schedule modal markup.

    The modal is populated by mhScheduleOpen() with channel checkboxes
    fetched from /api/buffer/channels. When the token is missing the
    fetch returns 401 and the open-handler shows an alert directing the
    user to contact their administrator, then closes the dialog.
    """
    return """
<div id="mh-sched-modal" class="no-print"
     style="display:none;position:fixed;inset:0;z-index:9999;background:rgba(8,12,20,0.72);
            align-items:center;justify-content:center;padding:20px"
     onclick="if(event.target===this) mhScheduleClose()">
  <div role="dialog" aria-modal="true" aria-labelledby="mh-sched-title"
       style="background:var(--panel,#10141d);border:1px solid var(--border,#252a36);
              border-radius:12px;max-width:560px;width:100%;max-height:90vh;
              overflow:auto;padding:22px;color:var(--ink,#e9eef5)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h2 id="mh-sched-title" style="margin:0;font-size:18px">Schedule with Buffer</h2>
      <button class="btn secondary" style="font-size:14px;padding:4px 10px"
              onclick="mhScheduleClose()" aria-label="Close">&times;</button>
    </div>
    <div id="mh-sched-error" style="display:none;color:#ff8a99;margin-bottom:10px"></div>
    <div id="mh-sched-channels-wrap" style="margin-bottom:12px">
      <div style="font-weight:600;margin-bottom:6px">Channels</div>
      <div id="mh-sched-channels" style="display:flex;flex-direction:column;gap:6px;
           max-height:180px;overflow:auto;border:1px solid var(--border,#252a36);
           border-radius:8px;padding:8px">
        <p class="muted" style="margin:0">Loading channels&hellip;</p>
      </div>
    </div>
    <div style="margin-bottom:12px">
      <label for="mh-sched-caption" style="font-weight:600;display:block;margin-bottom:4px">Caption</label>
      <textarea id="mh-sched-caption" rows="6"
        style="width:100%;padding:8px;border:1px solid var(--border,#252a36);
               border-radius:8px;background:rgba(255,255,255,0.04);
               color:inherit;font-family:inherit;resize:vertical"></textarea>
    </div>
    <div style="margin-bottom:12px">
      <label for="mh-sched-when" style="font-weight:600;display:block;margin-bottom:4px">
        Schedule for <span class="muted" style="font-weight:400">(leave blank for next queue slot)</span>
      </label>
      <input id="mh-sched-when" type="datetime-local"
             style="padding:8px;border:1px solid var(--border,#252a36);border-radius:8px;
                    background:rgba(255,255,255,0.04);color:inherit;font-family:inherit"/>
    </div>
    <input type="hidden" id="mh-sched-media-url"/>
    <input type="hidden" id="mh-sched-run-id"/>
    <input type="hidden" id="mh-sched-card-id"/>
    <input type="hidden" id="mh-sched-pill-id"/>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:6px">
      <button class="btn secondary" onclick="mhScheduleClose()">Cancel</button>
      <button id="mh-sched-send" class="btn" onclick="mhScheduleSend()">Send to Buffer</button>
    </div>
  </div>
</div>
"""


def _schedule_modal_js() -> str:
    """Return the JS that drives the Buffer schedule modal.

    Pulls channels from /api/buffer/channels (401 or not-connected
    surfaces a "contact administrator" alert and closes the modal —
    Buffer credentials are env-var configured at deploy time, no
    in-app redirect to a settings page exists), POSTs to
    /api/runs/<id>/card/<cid>/schedule, and preserves the user's
    edited caption when Buffer returns an error.
    """
    return """
<script>
(function(){
  var API_BASE = window._API_BASE || '';

  function fmtDt(d) {
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
      + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function localToIso(local) {
    if (!local) return '';
    var d = new Date(local);
    if (isNaN(d.getTime())) return '';
    return d.toISOString();
  }

  function pickActiveCaption(cardEl) {
    if (!cardEl) return '';
    var activePanel = cardEl.querySelector('.tone-panel:not([style*="display:none"]) textarea');
    if (activePanel && activePanel.value && activePanel.value.trim()) return activePanel.value.trim();
    var firstPanel = cardEl.querySelector('.tone-panel textarea');
    if (firstPanel && firstPanel.value && firstPanel.value.trim()) return firstPanel.value.trim();
    var ta = cardEl.querySelector('textarea[id^="cap-text-"], textarea[id^="cap-"]');
    if (ta && ta.value) return ta.value.trim();
    var fallback = cardEl.textContent || '';
    return fallback.trim().slice(0, 480);
  }

  function pickMediaUrl(cardEl) {
    if (!cardEl) return '';
    var img = cardEl.querySelector('img[src]');
    if (img && img.getAttribute('src')) {
      var src = img.getAttribute('src');
      if (/^https?:/i.test(src)) return src;
      try { return new URL(src, window.location.href).toString(); }
      catch (e) { return ''; }
    }
    return '';
  }

  window.mhScheduleOpen = function(runId, cardId, cardElId) {
    var modal = document.getElementById('mh-sched-modal');
    if (!modal) return;
    var cardEl = document.getElementById(cardElId);
    document.getElementById('mh-sched-run-id').value = runId || '';
    document.getElementById('mh-sched-card-id').value = cardId || '';
    document.getElementById('mh-sched-pill-id').value = cardElId || '';
    document.getElementById('mh-sched-caption').value = pickActiveCaption(cardEl);
    document.getElementById('mh-sched-when').value = '';
    document.getElementById('mh-sched-media-url').value = pickMediaUrl(cardEl);
    var err = document.getElementById('mh-sched-error');
    err.style.display = 'none'; err.textContent = '';

    var chWrap = document.getElementById('mh-sched-channels');
    chWrap.innerHTML = '<p class="muted" style="margin:0">Loading channels&hellip;</p>';

    fetch(API_BASE + '/api/buffer/channels', {cache:'no-store'}).then(function(r){
      return r.json().then(function(j){ return {status:r.status, body:j}; });
    }).then(function(o){
      if (o.status === 401 || !o.body.connected) {
        // Per-profile Buffer: show the inline "Connect your Buffer
        // account" form right inside the modal — paste a personal
        // access token and we save it on this org's profile. Also
        // offer the no-Buffer download alternative so clubs without
        // Buffer aren't blocked from getting their content out.
        var runIdForDl = document.getElementById('mh-sched-run-id').value;
        var cardIdForDl = document.getElementById('mh-sched-card-id').value;
        var capForDl = encodeURIComponent(
          document.getElementById('mh-sched-caption').value || ''
        );
        var dlUrl = API_BASE + '/api/runs/' + encodeURIComponent(runIdForDl)
          + '/card/' + encodeURIComponent(cardIdForDl)
          + '/download?caption=' + capForDl;
        chWrap.innerHTML =
          '<div style="font-size:13px;line-height:1.5;margin-bottom:10px">'
          + ((o.body && o.body.message) || 'Buffer is not connected for this organisation.')
          + '</div>'
          + '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:8px">'
          +   '<label for="mh-buf-token" style="font-size:12px;font-weight:600">Buffer access token</label>'
          +   '<input id="mh-buf-token" type="password" '
          +     'placeholder="1/..." autocomplete="off" '
          +     'style="padding:8px;border:1px solid var(--border,#252a36);'
          +     'border-radius:6px;background:rgba(255,255,255,0.04);color:inherit;font-family:inherit"/>'
          +   '<button id="mh-buf-connect" class="btn" style="font-size:13px;padding:6px 12px;align-self:flex-start"'
          +     ' onclick="mhConnectBufferFromModal()">Connect Buffer for this org</button>'
          +   '<a href="https://publish.buffer.com/account/apps" target="_blank" rel="noopener" '
          +     'style="font-size:11px;color:var(--accent)">Where do I get a Buffer access token? &rarr;</a>'
          + '</div>'
          + '<div style="border-top:1px solid var(--border,#252a36);padding-top:10px;margin-top:10px">'
          +   '<div style="font-size:12px;color:var(--muted,#7a8597);margin-bottom:6px">No Buffer? Download the post for manual sharing:</div>'
          +   '<a class="btn secondary" style="font-size:13px;padding:6px 12px" href="'
          +     dlUrl + '">Download caption + visual (.zip)</a>'
          + '</div>';
        modal.style.display = 'flex';
        return;
      }
      if (o.status >= 400) {
        chWrap.innerHTML = '<p style="color:#ff8a99;margin:0">' +
          ((o.body && o.body.message) || ('Buffer error ' + o.status)) + '</p>';
        modal.style.display = 'flex';
        return;
      }
      var channels = (o.body && o.body.channels) || [];
      if (!channels.length) {
        chWrap.innerHTML = '<p class="muted" style="margin:0">No channels connected to this Buffer account.</p>';
      } else {
        chWrap.innerHTML = '';
        channels.forEach(function(c, i){
          var lbl = document.createElement('label');
          lbl.style.display = 'flex';
          lbl.style.alignItems = 'center';
          lbl.style.gap = '8px';
          lbl.style.cursor = 'pointer';
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.value = c.id;
          cb.dataset.mhChannel = '1';
          cb.checked = !!c.default || (i === 0 && channels.length === 1);
          var name = c.formatted_username || c.service_username || c.id;
          var service = c.service ? ' (' + c.service + ')' : '';
          lbl.appendChild(cb);
          var span = document.createElement('span');
          span.textContent = name + service;
          lbl.appendChild(span);
          chWrap.appendChild(lbl);
        });
      }
      modal.style.display = 'flex';
    }).catch(function(e){
      chWrap.innerHTML = '<p style="color:#ff8a99;margin:0">Network error: ' + (e && e.message || e) + '</p>';
      modal.style.display = 'flex';
    });
  };

  window.mhScheduleClose = function() {
    var modal = document.getElementById('mh-sched-modal');
    if (modal) modal.style.display = 'none';
  };

  window.mhScheduleSend = function() {
    var runId  = document.getElementById('mh-sched-run-id').value;
    var cardId = document.getElementById('mh-sched-card-id').value;
    var pillId = document.getElementById('mh-sched-pill-id').value;
    var caption = (document.getElementById('mh-sched-caption').value || '').trim();
    var whenLocal = document.getElementById('mh-sched-when').value;
    var mediaUrl = document.getElementById('mh-sched-media-url').value;
    var err = document.getElementById('mh-sched-error');
    err.style.display = 'none'; err.textContent = '';

    var cbs = document.querySelectorAll('#mh-sched-channels input[data-mh-channel]:checked');
    var ids = Array.prototype.map.call(cbs, function(cb){ return cb.value; });
    if (!ids.length) { err.style.display = 'block'; err.textContent = 'Pick at least one channel.'; return; }
    if (!caption) { err.style.display = 'block'; err.textContent = 'Caption is required.'; return; }

    var btn = document.getElementById('mh-sched-send');
    var orig = btn.textContent;
    btn.disabled = true; btn.textContent = 'Sending&hellip;';

    fetch(API_BASE + '/api/runs/' + encodeURIComponent(runId)
            + '/card/' + encodeURIComponent(cardId) + '/schedule', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        channel_ids: ids,
        caption: caption,
        scheduled_at: localToIso(whenLocal) || null,
        media_url: mediaUrl || null
      })
    }).then(function(r){
      return r.json().then(function(j){ return {status:r.status, body:j}; });
    }).then(function(o){
      btn.disabled = false; btn.textContent = orig;
      if (o.body && typeof o.body.caption === 'string') {
        document.getElementById('mh-sched-caption').value = o.body.caption;
      }
      if (o.status >= 200 && o.status < 300 && o.body && o.body.ok) {
        var pill = document.querySelector('[data-schedule-pill="' + pillId + '"]');
        if (pill) {
          pill.style.display = '';
          pill.textContent = 'scheduled';
          pill.classList.remove('bad'); pill.classList.add('good');
        }
        var warn = o.body.warning ? (' Warning: ' + o.body.warning) : '';
        if (window.MH && typeof window.MH.toast === 'function') {
          window.MH.toast('Scheduled to Buffer.' + warn, warn ? 'info' : 'success');
        } else {
          alert('Scheduled to Buffer.' + warn);
        }
        mhScheduleClose();
      } else {
        var msg = (o.body && (o.body.message || o.body.error)) || ('HTTP ' + o.status);
        err.style.display = 'block'; err.textContent = msg;
        var pill = document.querySelector('[data-schedule-pill="' + pillId + '"]');
        if (pill) {
          pill.style.display = '';
          pill.textContent = 'failed';
          pill.classList.remove('good'); pill.classList.add('bad');
        }
      }
    }).catch(function(e){
      btn.disabled = false; btn.textContent = orig;
      err.style.display = 'block';
      err.textContent = 'Network error: ' + (e && e.message || e);
    });
  };

  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') {
      var m = document.getElementById('mh-sched-modal');
      if (m && m.style.display !== 'none') mhScheduleClose();
    }
  });
})();
</script>
"""


# ---------------------------------------------------------------------
# Background pipeline worker
# ---------------------------------------------------------------------

def _start_run(file_bytes: bytes, file_name: str,
               profile_id: Optional[str], use_pb_cache: bool,
               fetch_pbs: bool, club_filter: Optional[str] = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    with _active_lock:
        _active_runs[run_id] = {
            "status": "queued",
            "log": ["Run queued"],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "file_name": file_name,
        }
        # Evict completed older runs to keep the dict bounded.
        _maybe_evict_active_runs()
    conn = _db()
    conn.execute(
        """INSERT INTO runs (id, created_at, status, file_name, profile_id)
           VALUES (?,?,?,?,?)""",
        (run_id, _active_runs[run_id]["started_at"], "queued",
         file_name, profile_id or ""),
    )
    conn.commit()
    conn.close()

    def _worker():
        with _active_lock:
            _active_runs[run_id]["status"] = "running"

        def cb(msg: str):
            with _active_lock:
                log_list = _active_runs[run_id]["log"]
                log_list.append(msg)
                # Cap each run's progress log so a buggy progress
                # callback can't grow the in-memory list to thousands
                # of entries × hundreds of bytes.
                if len(log_list) > _RUN_LOG_LIMIT:
                    # Keep the first 5 (queue/start markers — useful
                    # for diagnosis) and the most recent N-5.
                    keep_tail = _RUN_LOG_LIMIT - 5
                    _active_runs[run_id]["log"] = (
                        log_list[:5] + log_list[-keep_tail:]
                    )
                entry = _active_runs.get(run_id)
                if entry is None:
                    return
                log_list = entry.setdefault("log", [])
                log_list.append(msg)
                if len(log_list) > _MAX_LOG_LINES:
                    drop = len(log_list) - _MAX_LOG_LINES
                    del log_list[:drop]
                    log_list[0] = f"[truncated earlier {drop} log lines]"

        try:
            run = run_pipeline_v4(
                file_bytes=file_bytes, filename=file_name,
                profile_id=profile_id, use_pb_cache=use_pb_cache,
                fetch_pbs=fetch_pbs, progress_cb=cb, run_id=run_id,
                club_filter=club_filter,
            )
            _persist_run(run, file_name)
            with _active_lock:
                _active_runs[run_id]["status"] = "error" if run.error else "done"
                if run.error:
                    _active_runs[run_id]["error"] = run.error
        except Exception as e:
            import traceback
            traceback.print_exc()
            with _active_lock:
                _active_runs[run_id]["status"] = "error"
                _active_runs[run_id]["error"] = str(e)
            conn = _db()
            conn.execute("UPDATE runs SET status='error', error=? WHERE id=?",
                         (str(e), run_id))
            conn.commit(); conn.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return run_id


# ---------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&display=swap');

:root {
  /* Surfaces — warmer, deeper, less corporate-blue */
  --bg:       #08091A;
  --bg-soft:  #0F1029;
  --panel:    #141532;
  --panel2:   #1B1D44;
  --panel-h:  #232556;
  --border:   rgba(255,255,255,0.07);
  --border-h: rgba(168,85,247,0.30);

  /* Text */
  --ink:       #F2F4FD;
  --ink-dim:   #98A1C0;
  --ink-muted: #5F6790;

  /* Accent — bold cyan→violet gradient pair */
  --accent:    #22D3EE;
  --accent-h:  #67E8F9;
  --accent2:   #A855F7;
  --accent2-h: #C084FC;
  --accent3:   #F472B6;
  --grad-hot:  linear-gradient(135deg, #22D3EE 0%, #A855F7 55%, #F472B6 100%);
  --grad-cool: linear-gradient(135deg, #22D3EE 0%, #6366F1 100%);
  --grad-warm: linear-gradient(135deg, #A855F7 0%, #F472B6 100%);

  /* Semantic */
  --good: #22C55E;
  --warn: #F59E0B;
  --bad:  #F43F5E;
  --info: #22D3EE;

  /* Misc */
  --radius:    18px;
  --radius-sm: 12px;
  --shadow:    0 1px 0 rgba(255,255,255,0.04), 0 12px 40px rgba(0,0,0,0.45);
  --shadow-h:  0 1px 0 rgba(255,255,255,0.06), 0 24px 60px rgba(168,85,247,0.18);
  --transition: 180ms cubic-bezier(0.4,0,0.2,1);
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
               Roboto, Helvetica, Arial, sans-serif;
  background:
    radial-gradient(1200px 600px at 12% -10%, rgba(168,85,247,0.18), transparent 60%),
    radial-gradient(900px 500px at 90% -20%, rgba(34,211,238,0.14), transparent 65%),
    radial-gradient(700px 700px at 50% 110%, rgba(244,114,182,0.08), transparent 65%),
    var(--bg);
  background-attachment: fixed;
  color: var(--ink);
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; transition: color var(--transition); }
a:hover { color: var(--accent-h); text-decoration: none; }

/* TOPNAV */
header.topnav {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 0 28px;
  height: 56px;
  border-bottom: 1px solid var(--border);
  background: rgba(11,18,32,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 100;
}
header.topnav .brand {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.01em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 9px;
  margin-right: 28px;
  text-decoration: none;
  flex-shrink: 0;
}
header.topnav .brand svg { color: var(--accent); flex-shrink: 0; }
header.topnav nav { display: flex; align-items: center; gap: 2px; flex: 1; }
header.topnav nav a {
  color: var(--ink-dim);
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  transition: background var(--transition), color var(--transition);
  white-space: nowrap;
}
header.topnav nav a:hover {
  background: rgba(255,255,255,0.05);
  color: var(--ink);
  text-decoration: none;
}
header.topnav nav a.active {
  color: var(--accent);
  background: rgba(34,211,238,0.08);
  border-bottom: 2px solid var(--accent);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  padding-bottom: 4px;
}
#backend-pill {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border);
  color: var(--ink-muted);
  text-decoration: none;
  transition: border-color var(--transition);
  flex-shrink: 0;
}
#backend-pill:hover { border-color: rgba(255,255,255,0.12); text-decoration: none; }
#backend-pill-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--ink-muted);
  flex-shrink: 0;
  transition: background 0.3s;
}

/* MAIN */
main.wrap { max-width: 1200px; margin: 0 auto; padding: 36px 28px 96px; }

/* HEADINGS */
h1 { font-size: 28px; font-weight: 800; letter-spacing: -0.02em; margin: 0 0 8px; color: var(--ink); }
h2 { font-size: 17px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 10px; color: var(--ink); }
h3 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); margin: 20px 0 10px; }

/* CARDS */
.card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 20px; box-shadow: var(--shadow); }
.card h2 { margin: 0 0 10px; }
.card p { color: var(--ink-dim); margin: 0 0 12px; }
.card p:last-child { margin-bottom: 0; }

/* BUTTONS */
.btn {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--accent); color: #081820;
  border: 0; padding: 9px 18px; font-size: 14px; font-weight: 600;
  border-radius: var(--radius-sm); cursor: pointer;
  transition: background var(--transition), transform var(--transition), box-shadow var(--transition);
  font-family: inherit; text-decoration: none; letter-spacing: -0.01em;
}
.btn:hover {
  background: var(--accent-h); color: #081820;
  transform: translateY(-1px); box-shadow: 0 4px 16px rgba(34,211,238,0.2);
  text-decoration: none;
}
.btn:active { transform: translateY(0); }
.btn.secondary { background: transparent; color: var(--ink-dim); border: 1px solid rgba(255,255,255,0.1); }
.btn.secondary:hover { background: rgba(255,255,255,0.05); color: var(--ink); border-color: rgba(255,255,255,0.18); box-shadow: none; }
.btn.danger { background: transparent; color: var(--bad); border: 1px solid rgba(244,63,94,0.3); }
.btn.danger:hover { background: rgba(244,63,94,0.08); border-color: rgba(244,63,94,0.5); box-shadow: none; }

/* LAYOUT */
.row { display: flex; gap: 18px; flex-wrap: wrap; }
.row > * { flex: 1; min-width: 240px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; }
@media (max-width: 860px) {
  .grid-2, .grid-3 { grid-template-columns: 1fr; }
  .row { flex-direction: column; }
}
.divider { height: 1px; background: var(--border); margin: 20px 0; }
.muted { color: var(--ink-muted); }
.dim   { color: var(--ink-dim); }
.empty { padding: 56px 24px; text-align: center; color: var(--ink-muted); font-size: 14px; }

/* TABLES */
table { width: 100%; border-collapse: collapse; font-size: 14px; }
table th { text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); border-bottom: 1px solid var(--border); }
table td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
table tbody tr:nth-child(odd) { background: rgba(255,255,255,0.015); }
table tbody tr:hover { background: rgba(255,255,255,0.03); }

/* TAGS */
.tag { display: inline-flex; align-items: center; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: 0.03em; background: rgba(255,255,255,0.06); color: var(--ink-dim); border: 1px solid var(--border); }
.tag.good { background: rgba(34,197,94,0.12); color: var(--good); border-color: rgba(34,197,94,0.25); }
.tag.warn { background: rgba(245,158,11,0.12); color: var(--warn); border-color: rgba(245,158,11,0.25); }
.tag.bad  { background: rgba(244,63,94,0.12);  color: var(--bad);  border-color: rgba(244,63,94,0.25); }
.tag.info { background: rgba(34,211,238,0.10); color: var(--info); border-color: rgba(34,211,238,0.25); }

/* FORMS */
label { display: block; margin: 14px 0 5px; color: var(--ink-muted); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; }
input[type=text], input[type=file], textarea, select {
  background: rgba(255,255,255,0.03); color: var(--ink);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--radius-sm); padding: 10px 14px;
  font-size: 14px; font-family: inherit; width: 100%;
  transition: border-color var(--transition), box-shadow var(--transition);
  appearance: none;
}
input[type=text]:focus, textarea:focus, select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(34,211,238,0.18);
}
input[type=checkbox] { width: auto; margin-right: 8px; accent-color: var(--accent); }
textarea { min-height: 120px; resize: vertical; }
select { cursor: pointer; }

/* STATS */
.stat-block { display: flex; gap: 12px; flex-wrap: wrap; }
.stat { background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; min-width: 110px; }
.stat .l { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--ink-muted); margin-bottom: 4px; }
.stat .v { font-size: 32px; font-weight: 800; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; color: var(--ink); line-height: 1; }

/* KV */
.kv { display: grid; grid-template-columns: 180px 1fr; gap: 6px 16px; font-size: 14px; }
.kv .k { color: var(--ink-muted); font-size: 12px; font-weight: 500; }

/* PROGRESS LOG */
.progress-log {
  background: rgba(0,0,0,0.3); color: #9EB3C8;
  border: 1px solid var(--border); border-radius: 10px; padding: 16px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: 12px; white-space: pre-wrap; max-height: 360px; overflow-y: auto; line-height: 1.7;
}

/* CODE */
code, pre { font-family: ui-monospace, 'SF Mono', Menlo, monospace; background: rgba(255,255,255,0.05); padding: 2px 7px; border-radius: 5px; font-size: 12.5px; color: var(--accent); }
pre { padding: 16px; overflow-x: auto; color: var(--ink-dim); border: 1px solid var(--border); border-radius: 10px; }
pre code { background: none; padding: 0; color: inherit; }

/* === Animations === */
@keyframes mh-spin { to { transform: rotate(360deg); } }
@keyframes mh-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
@keyframes mh-fade-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes mh-shimmer { 0% { background-position: -1000px 0; } 100% { background-position: 1000px 0; } }
@keyframes mh-slide-in { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: translateX(0); } }
@keyframes mh-aurora { 0% { transform: translate(0,0) rotate(0deg); } 50% { transform: translate(-30px,40px) rotate(180deg); } 100% { transform: translate(0,0) rotate(360deg); } }

/* Page entry */
main.wrap { animation: mh-fade-in 0.35s ease-out; position: relative; z-index: 1; }
main.wrap > .card { animation: mh-fade-in 0.4s ease-out backwards; }
main.wrap > .card:nth-of-type(1) { animation-delay: 0.05s; }
main.wrap > .card:nth-of-type(2) { animation-delay: 0.10s; }
main.wrap > .card:nth-of-type(3) { animation-delay: 0.15s; }
main.wrap > .card:nth-of-type(4) { animation-delay: 0.20s; }
main.wrap > .card:nth-of-type(5) { animation-delay: 0.25s; }

/* Background accent &mdash; subtle aurora */
body::before {
  content: ''; position: fixed; top: -240px; right: -240px;
  width: 640px; height: 640px;
  background: radial-gradient(circle, rgba(34,211,238,0.06) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
  animation: mh-aurora 28s ease-in-out infinite;
}
body::after {
  content: ''; position: fixed; bottom: -320px; left: -240px;
  width: 720px; height: 720px;
  background: radial-gradient(circle, rgba(124,58,237,0.05) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
  animation: mh-aurora 36s ease-in-out infinite reverse;
}

/* Card hover */
.card { transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease; }
a.card, .card[data-interactive] { cursor: pointer; }
a.card:hover, .card[data-interactive]:hover {
  transform: translateY(-2px);
  border-color: rgba(34,211,238,0.3);
  box-shadow: 0 12px 36px rgba(0,0,0,0.5), 0 0 0 1px rgba(34,211,238,0.15);
}

/* Loading overlay */
#mh-loader {
  position: fixed; inset: 0;
  background: rgba(11,18,32,0.78);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  z-index: 9999;
  display: none; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.25s ease;
}
#mh-loader.show { display: flex; opacity: 1; }
.mh-loader-inner {
  display: flex; flex-direction: column; align-items: center; gap: 22px;
  padding: 36px 48px;
  animation: mh-fade-in 0.4s ease-out;
}
.mh-spinner {
  width: 72px; height: 72px;
  border-radius: 50%;
  background: conic-gradient(from 0deg, transparent 0deg, rgba(34,211,238,0.15) 90deg, var(--accent) 270deg, transparent 360deg);
  -webkit-mask: radial-gradient(circle at center, transparent 26px, black 28px);
  mask: radial-gradient(circle at center, transparent 26px, black 28px);
  animation: mh-spin 1s linear infinite;
  position: relative;
  box-shadow: 0 0 40px rgba(34,211,238,0.25);
}
.mh-spinner::after {
  content: ''; position: absolute; inset: 10px;
  border-radius: 50%;
  background: radial-gradient(circle at center, rgba(34,211,238,0.18), transparent 70%);
  animation: mh-pulse 1.4s ease-in-out infinite;
}
.mh-loader-text {
  font-size: 15px; color: var(--ink); font-weight: 600;
  letter-spacing: -0.01em; text-align: center;
}
.mh-loader-sub {
  font-size: 13px; color: var(--ink-dim);
  max-width: 360px; text-align: center;
  animation: mh-pulse 2.4s ease-in-out infinite;
}

/* Toast */
#mh-toast-container {
  position: fixed; top: 72px; right: 20px;
  z-index: 10000;
  display: flex; flex-direction: column; gap: 10px;
  pointer-events: none; max-width: 380px;
}
.mh-toast {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; color: var(--ink);
  font-size: 14px; line-height: 1.45;
  box-shadow: 0 12px 36px rgba(0,0,0,0.5);
  pointer-events: auto;
  animation: mh-slide-in 0.32s cubic-bezier(0.34, 1.2, 0.64, 1);
  display: flex; align-items: flex-start; gap: 12px;
  min-width: 280px;
}
.mh-toast.success { border-color: rgba(34,197,94,0.45); }
.mh-toast.error   { border-color: rgba(244,63,94,0.45); }
.mh-toast.info    { border-color: rgba(34,211,238,0.45); }
.mh-toast .mh-toast-icon { width: 18px; height: 18px; flex-shrink: 0; margin-top: 1px; }
.mh-toast.success .mh-toast-icon { color: var(--good); }
.mh-toast.error   .mh-toast-icon { color: var(--bad); }
.mh-toast.info    .mh-toast-icon { color: var(--info); }
.mh-toast-close {
  background: none; border: 0; color: var(--ink-muted); cursor: pointer;
  padding: 0; margin-left: 4px; font-size: 18px; line-height: 1;
  transition: color var(--transition);
}
.mh-toast-close:hover { color: var(--ink); }

/* Button loading state */
.btn.loading { pointer-events: none; opacity: 0.72; position: relative; padding-right: 38px; }
.btn.loading::after {
  content: ''; position: absolute; right: 14px; top: 50%;
  width: 14px; height: 14px; margin-top: -7px;
  border: 2px solid currentColor; border-right-color: transparent;
  border-radius: 50%; animation: mh-spin 0.6s linear infinite;
}

/* Skeleton */
.skeleton {
  background: linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 100%);
  background-size: 1000px 100%;
  animation: mh-shimmer 1.6s linear infinite;
  border-radius: 8px;
}

/* Content card (AI-generated stub output) */
.mh-content-card {
  background: linear-gradient(180deg, rgba(34,211,238,0.04), rgba(34,211,238,0.01));
  border: 1px solid rgba(34,211,238,0.15);
  border-radius: var(--radius);
  padding: 22px;
  margin-bottom: 16px;
  position: relative;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.mh-content-card:hover { border-color: rgba(34,211,238,0.35); transform: translateY(-1px); }
.mh-content-card .mh-card-platform {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent); margin-bottom: 10px;
}
.mh-content-card .mh-card-caption {
  font-size: 15px; line-height: 1.6; color: var(--ink);
  white-space: pre-wrap; word-wrap: break-word;
}
.mh-content-card .mh-card-tags {
  margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;
}
.mh-content-card .mh-card-tag {
  font-size: 12px; color: var(--accent);
  background: rgba(34,211,238,0.08);
  border: 1px solid rgba(34,211,238,0.2);
  border-radius: 6px; padding: 3px 8px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
.mh-content-card .mh-card-confidence {
  position: absolute; top: 22px; right: 22px;
  font-size: 11px; color: var(--ink-muted);
  font-variant-numeric: tabular-nums;
}
.mh-card-actions {
  margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;
  padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);
}
.mh-card-actions button {
  background: transparent; border: 1px solid rgba(255,255,255,0.1);
  color: var(--ink-dim); font-size: 12px; padding: 5px 11px;
  border-radius: 6px; cursor: pointer; font-family: inherit;
  transition: all var(--transition);
}
.mh-card-actions button:hover { color: var(--ink); border-color: rgba(255,255,255,0.2); }
.mh-card-actions button.primary { color: var(--accent); border-color: rgba(34,211,238,0.3); }
.mh-card-actions button.primary:hover { background: rgba(34,211,238,0.08); border-color: var(--accent); }

/* Disabled card / button visual state */
[aria-disabled="true"], .is-disabled {
  opacity: 0.45;
  cursor: not-allowed !important;
  pointer-events: none;
  filter: grayscale(0.3);
}
[aria-disabled="true"]:hover, .is-disabled:hover {
  transform: none !important; box-shadow: none !important;
}

/* === Upload pipeline progress UI === */
.mh-stages {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin: 18px 0 22px;
}
.mh-stage {
  flex: 1; min-width: 130px;
  background: rgba(255,255,255,0.03);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  position: relative;
  transition: border-color 0.25s ease, background 0.25s ease, color 0.25s ease;
}
.mh-stage .mh-stage-label {
  font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.07em;
  color: var(--ink-muted); margin-bottom: 4px;
}
.mh-stage .mh-stage-text {
  font-size: 13px; color: var(--ink-dim);
  line-height: 1.4;
}
.mh-stage[data-state="done"] {
  border-color: rgba(34,197,94,0.4);
  background: rgba(34,197,94,0.05);
}
.mh-stage[data-state="done"] .mh-stage-label { color: var(--good); }
.mh-stage[data-state="active"] {
  border-color: rgba(34,211,238,0.55);
  background: rgba(34,211,238,0.06);
  box-shadow: 0 0 24px rgba(34,211,238,0.18);
}
.mh-stage[data-state="active"] .mh-stage-label { color: var(--accent); }
.mh-stage[data-state="active"]::after {
  content: ''; position: absolute; top: 10px; right: 10px;
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent);
  animation: mh-pulse 1.1s ease-in-out infinite;
  box-shadow: 0 0 12px var(--accent);
}
.mh-stage[data-state="error"] {
  border-color: rgba(244,63,94,0.5);
  background: rgba(244,63,94,0.06);
}
.mh-stage[data-state="error"] .mh-stage-label { color: var(--bad); }

.mh-progress-bar {
  position: relative; height: 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 999px; overflow: hidden;
  margin: 14px 0 6px;
}
.mh-progress-bar > span {
  position: absolute; top: 0; left: 0; bottom: 0;
  background: linear-gradient(90deg, var(--accent) 0%, #7c3aed 100%);
  border-radius: 999px;
  transition: width 0.4s ease;
  width: 0;
}
.mh-progress-bar.indeterminate > span {
  width: 30% !important;
  animation: mh-progress-slide 1.6s cubic-bezier(0.4,0,0.2,1) infinite;
}
@keyframes mh-progress-slide {
  0%   { transform: translateX(-110%); }
  100% { transform: translateX(440%); }
}

/* === Mobile responsive &mdash; nav + spacing === */
@media (max-width: 720px) {
  main.wrap { padding: 24px 16px 80px; }
  h1 { font-size: 22px; }
  h2 { font-size: 15px; }
  header.topnav { padding: 0 12px; height: auto; flex-wrap: wrap; gap: 6px; }
  header.topnav .brand { margin-right: 10px; }
  header.topnav nav {
    width: 100%; gap: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    padding-bottom: 6px;
  }
  header.topnav nav::-webkit-scrollbar { display: none; }
  header.topnav nav a {
    padding: 5px 10px; font-size: 13px;
    flex-shrink: 0;
  }
  #backend-pill { margin-left: auto; flex-shrink: 0; }
  .card { padding: 18px 16px; }
  .stat .v { font-size: 26px; }
  table { font-size: 12.5px; }
  table th, table td { padding: 8px 10px; }
  .kv { grid-template-columns: 1fr; gap: 2px 8px; }
  .kv .k { margin-top: 8px; }
  .mh-card-confidence { position: static !important; display: block; margin-bottom: 8px; }
  .mh-toast { min-width: 0; }
  #mh-toast-container { left: 12px; right: 12px; max-width: none; top: 60px; }
}
@media (max-width: 480px) {
  .row { gap: 12px; }
  .grid-2, .grid-3 { gap: 12px; }
  .stat-block { gap: 8px; }
  .stat { padding: 10px 12px; min-width: 0; flex: 1; }
}
/* Force inputs/selects to never overflow their container, even with inline max-widths */
input[type=text], input[type=file], textarea, select { max-width: 100%; }

/* === Hero (Holo-style) === */
.mh-hero {
  text-align: center;
  padding: 56px 24px 32px;
  position: relative;
  margin-bottom: 32px;
}
.mh-hero-eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 999px;
  background: rgba(34,211,238,0.08);
  border: 1px solid rgba(34,211,238,0.2);
  font-size: 12px; font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.02em;
  margin-bottom: 22px;
  animation: mh-fade-in 0.6s ease-out;
}
.mh-hero-eyebrow .mh-pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--good);
  box-shadow: 0 0 8px rgba(34,197,94,0.6);
  animation: mh-pulse 1.6s ease-in-out infinite;
}
.mh-hero h1 {
  font-size: clamp(34px, 6vw, 60px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.05;
  margin: 0 0 18px;
  max-width: 820px; margin-left: auto; margin-right: auto;
}
.mh-hero h1 .mh-gradient-text {
  background: linear-gradient(135deg, var(--accent) 0%, #7c3aed 60%, #f43f5e 100%);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
  -webkit-text-fill-color: transparent;
}
.mh-hero .mh-hero-sub {
  font-size: clamp(15px, 1.6vw, 18px);
  color: var(--ink-dim);
  max-width: 640px; margin: 0 auto 28px;
  line-height: 1.55;
}
.mh-hero-ctas {
  display: flex; gap: 12px; justify-content: center; flex-wrap: wrap;
  margin-bottom: 22px;
}
.mh-hero-ctas .btn {
  font-size: 15px; padding: 12px 22px;
}
.mh-hero-trust {
  display: flex; align-items: center; justify-content: center;
  gap: 18px; flex-wrap: wrap;
  font-size: 12px; color: var(--ink-muted);
  margin-top: 8px;
}
.mh-hero-trust > * { display: inline-flex; align-items: center; gap: 6px; }
.mh-hero-trust svg { width: 13px; height: 13px; }

/* Section heading */
.mh-section-eyebrow {
  display: block; text-align: center;
  font-size: 12px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.12em;
  color: var(--accent);
  margin: 36px 0 8px;
}
.mh-section-title {
  font-size: clamp(22px, 3vw, 30px);
  font-weight: 700;
  letter-spacing: -0.02em;
  text-align: center;
  margin: 0 0 32px;
  max-width: 720px; margin-left: auto; margin-right: auto;
  line-height: 1.2;
}

/* === Numbered step cards (How it works) === */
.mh-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px;
  margin-bottom: 48px;
}
.mh-step {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px 22px;
  position: relative;
  transition: border-color 0.25s ease, transform 0.25s ease;
}
.mh-step:hover {
  border-color: rgba(34,211,238,0.4);
  transform: translateY(-2px);
}
.mh-step-num {
  display: inline-flex;
  align-items: center; justify-content: center;
  width: 32px; height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(34,211,238,0.18), rgba(124,58,237,0.18));
  border: 1px solid rgba(34,211,238,0.35);
  color: var(--accent);
  font-weight: 800; font-size: 14px;
  margin-bottom: 14px;
}
.mh-step h3 {
  font-size: 16px; font-weight: 700; color: var(--ink);
  letter-spacing: -0.01em; margin: 0 0 8px;
  text-transform: none;
}
.mh-step p {
  font-size: 13.5px; color: var(--ink-dim);
  line-height: 1.55; margin: 0;
}

/* === Hero (rebuilt home page) === */
.mh-hero {
  position: relative;
  padding: 56px 32px 48px;
  margin-bottom: 40px;
  border-radius: 24px;
  background:
    radial-gradient(900px 320px at 18% 20%, rgba(168,85,247,0.18), transparent 60%),
    radial-gradient(700px 280px at 88% 80%, rgba(34,211,238,0.20), transparent 65%),
    linear-gradient(135deg, rgba(20,21,50,0.85), rgba(15,16,41,0.95));
  border: 1px solid rgba(168,85,247,0.20);
  box-shadow: var(--shadow-h);
  overflow: hidden;
}
.mh-hero::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px; right: -1px; bottom: -1px;
  border-radius: 24px;
  background: linear-gradient(135deg, rgba(34,211,238,0.45), rgba(168,85,247,0.30), rgba(244,114,182,0.30)) border-box;
  -webkit-mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor; mask-composite: exclude;
  padding: 1px;
  pointer-events: none;
  opacity: 0.6;
}
.mh-hero-eyebrow {
  font-family: 'Sora', 'Inter', sans-serif;
  font-size: 11px; font-weight: 700;
  letter-spacing: 0.20em; text-transform: uppercase;
  color: var(--accent);
  display: inline-block;
  padding: 5px 10px;
  border: 1px solid rgba(34,211,238,0.30);
  border-radius: 999px;
  margin-bottom: 18px;
  background: rgba(34,211,238,0.06);
}
.mh-hero h1 {
  font-family: 'Sora', 'Inter', sans-serif;
  font-size: clamp(34px, 5.5vw, 60px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.04;
  margin: 0 0 18px;
  max-width: 760px;
}
.mh-hero h1 .grad {
  background: var(--grad-hot);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
  display: inline-block;
}
.mh-hero p.lede {
  font-size: 17px;
  color: var(--ink-dim);
  margin: 0 0 32px;
  max-width: 620px;
  line-height: 1.55;
}
.mh-hero-actions {
  display: flex; gap: 14px; flex-wrap: wrap; align-items: center;
}
.mh-cta-primary,
.mh-cta-secondary {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 14px 22px;
  border-radius: 12px;
  font-weight: 700;
  font-size: 14px;
  text-decoration: none;
  border: 1px solid transparent;
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
  cursor: pointer;
}
.mh-cta-primary {
  background: var(--grad-hot);
  color: #08091A;
  box-shadow: 0 8px 28px rgba(168,85,247,0.35), inset 0 1px 0 rgba(255,255,255,0.25);
}
.mh-cta-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 36px rgba(168,85,247,0.50), inset 0 1px 0 rgba(255,255,255,0.3);
  color: #08091A;
}
.mh-cta-secondary {
  background: rgba(255,255,255,0.04);
  color: var(--ink);
  border-color: rgba(255,255,255,0.10);
}
.mh-cta-secondary:hover {
  background: rgba(255,255,255,0.08);
  border-color: var(--accent);
  color: var(--ink);
  transform: translateY(-1px);
}
.mh-hero-meta {
  margin-top: 18px;
  font-size: 13px;
  color: var(--ink-muted);
  display: flex; gap: 14px; flex-wrap: wrap;
}
.mh-hero-meta .dot { color: var(--ink-muted); }
.mh-hero-meta b { color: var(--ink-dim); font-weight: 600; }

/* === Sign-in profile cards === */
.mh-profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}
.mh-profile-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 22px;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.02), transparent 60%),
    var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: transform var(--transition), border-color var(--transition), box-shadow var(--transition);
  text-decoration: none;
  color: inherit;
  min-height: 180px;
}
.mh-profile-card:hover {
  transform: translateY(-3px);
  border-color: var(--border-h);
  box-shadow: var(--shadow-h);
}
.mh-profile-card .logo {
  width: 56px; height: 56px;
  border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 14px;
  font-family: 'Sora', sans-serif;
  font-weight: 800; font-size: 22px;
  color: #fff;
  background: var(--grad-hot);
  overflow: hidden;
}
.mh-profile-card .logo img {
  width: 100%; height: 100%; object-fit: cover;
}
.mh-profile-card .display-name {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--ink);
  margin-bottom: 4px;
}
.mh-profile-card .meta-line {
  font-size: 12px;
  color: var(--ink-muted);
  display: flex; gap: 8px; flex-wrap: wrap;
  margin-bottom: 14px;
}
.mh-profile-card .meta-line .pill {
  padding: 2px 8px;
  background: rgba(34,211,238,0.10);
  border: 1px solid rgba(34,211,238,0.20);
  border-radius: 999px;
  color: var(--accent);
  font-weight: 600;
}
.mh-profile-card .actions {
  margin-top: auto;
  display: flex; gap: 8px; flex-wrap: wrap;
}
.mh-profile-card .actions .btn-sign-in {
  flex: 1;
  text-align: center;
  padding: 8px 12px;
  background: var(--grad-cool);
  color: #08091A;
  border: none;
  border-radius: 10px;
  font-weight: 700;
  font-size: 12px;
  text-decoration: none;
  cursor: pointer;
}
.mh-profile-card .actions .btn-delete {
  padding: 8px 12px;
  background: rgba(244,63,94,0.08);
  border: 1px solid rgba(244,63,94,0.20);
  color: #FCA5A5;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.mh-profile-card .actions .btn-delete:hover {
  background: rgba(244,63,94,0.18);
  border-color: rgba(244,63,94,0.40);
}

/* === New org "+" tile === */
.mh-new-profile {
  display: flex;
  align-items: center; justify-content: center;
  min-height: 180px;
  background:
    repeating-linear-gradient(45deg, rgba(168,85,247,0.04) 0 12px, transparent 12px 24px),
    var(--panel);
  border: 1.5px dashed rgba(168,85,247,0.40);
  border-radius: var(--radius);
  color: var(--ink-dim);
  text-decoration: none;
  font-weight: 600;
  text-align: center;
  transition: var(--transition);
}
.mh-new-profile:hover {
  background:
    repeating-linear-gradient(45deg, rgba(168,85,247,0.08) 0 12px, transparent 12px 24px),
    var(--panel-h);
  border-color: var(--accent2);
  color: var(--ink);
}
.mh-new-profile .plus {
  font-size: 28px;
  margin-bottom: 6px;
  color: var(--accent2);
  font-weight: 800;
}

/* === Template gallery cards === */
.mh-template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 40px;
}
.mh-template {
  display: flex; flex-direction: column;
  gap: 10px;
  padding: 20px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-decoration: none;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.mh-template::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, rgba(34,211,238,0.06) 0%, transparent 60%);
  opacity: 0; transition: opacity 0.25s ease;
  pointer-events: none;
}
.mh-template:hover {
  border-color: rgba(34,211,238,0.4);
  transform: translateY(-2px);
  text-decoration: none;
}
.mh-template:hover::before { opacity: 1; }
.mh-template-icon {
  width: 38px; height: 38px;
  border-radius: 10px;
  background: rgba(34,211,238,0.1);
  border: 1px solid rgba(34,211,238,0.25);
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--accent); flex-shrink: 0;
  margin-bottom: 4px;
}
.mh-template-icon svg { width: 22px; height: 22px; }
.mh-template h3 {
  font-size: 15px; font-weight: 700; color: var(--ink);
  letter-spacing: -0.01em; margin: 0;
  text-transform: none;
}
.mh-template p {
  font-size: 13px; color: var(--ink-dim);
  line-height: 1.5; margin: 0 0 10px;
  flex: 1;
}
.mh-template-cta {
  font-size: 13px; font-weight: 600;
  color: var(--accent);
  display: inline-flex; align-items: center; gap: 6px;
  margin-top: auto;
}

/* === Provider badge on home === */
.mh-provider-badge {
  display: inline-flex; align-items: center; gap: 10px;
  padding: 10px 16px;
  background: rgba(34,197,94,0.06);
  border: 1px solid rgba(34,197,94,0.25);
  border-radius: 12px;
  font-size: 13px;
  margin-top: 8px;
}
.mh-provider-badge.warn {
  background: rgba(245,158,11,0.06);
  border-color: rgba(245,158,11,0.3);
  color: var(--ink);
}
.mh-provider-badge.warn strong { color: var(--warn); }
.mh-provider-badge .mh-provider-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--good);
}
.mh-provider-badge.warn .mh-provider-dot { background: var(--warn); }

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
"""


def _render_markdown(text: str) -> str:
    """Tiny, dependency-free markdown subset for the research page."""
    import html as _html
    import re as _re

    def _inline(s: str) -> str:
        s = _html.escape(s)
        s = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                    lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', s)
        s = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = _re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    table_rows: list[list[str]] = []

    def flush_table():
        if not table_rows:
            return
        head, *rest = table_rows
        rest = [r for r in rest if not all(_re.fullmatch(r":?-+:?", c.strip() or "-") for c in r)]
        out.append('<div style="overflow-x:auto"><table>')
        out.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead>")
        out.append("<tbody>")
        for r in rest:
            out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
        out.append("</tbody></table></div>")
        table_rows.clear()

    in_list = False
    for raw in lines:
        ln = raw.rstrip()
        if ln.startswith("```"):
            if in_code:
                out.append("</code></pre>")
            else:
                out.append('<pre><code>')
            in_code = not in_code
            continue
        if in_code:
            out.append(_html.escape(ln))
            continue
        if ln.startswith("|") and ln.endswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            table_rows.append(cells)
            continue
        if table_rows:
            flush_table()
        m = _re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            if in_list: out.append("</ul>"); in_list = False
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue
        if ln.startswith("- ") or ln.startswith("* "):
            if not in_list:
                out.append('<ul style="margin-top:6px">'); in_list = True
            out.append(f"<li>{_inline(ln[2:])}</li>")
            continue
        if in_list and not ln.strip():
            out.append("</ul>"); in_list = False
            continue
        if not ln.strip():
            continue
        out.append(f"<p>{_inline(ln)}</p>")

    if table_rows:
        flush_table()
    if in_code:
        out.append("</code></pre>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _layout(title: str, body: str, active: str = "home") -> str:
    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{{ title }} &mdash; MediaHub</title>
<style>{{ css | safe }}</style>
<script>
  // Detect deployed prefix (e.g. "/port/5000") so XHRs from inline JS use the right base.
  (function(){
    var path = window.location.pathname || '/';
    var m = path.match(/^(\\/port\\/\\d+)/);
    window._API_BASE = m ? m[1] : '';
  })();
</script>
</head>
<body>
<div id="mh-loader" aria-live="polite" aria-busy="true">
  <div class="mh-loader-inner">
    <div class="mh-spinner"></div>
    <div class="mh-loader-text">Working on it</div>
    <div class="mh-loader-sub">This usually takes a few seconds</div>
  </div>
</div>
<div id="mh-toast-container"></div>
<header class="topnav">
  <div class="brand">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2 12c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
      <path d="M2 17c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
      <path d="M2 7c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2 2-2 4-2"/>
    </svg>
    MediaHub
  </div>
  <nav>
    <a href="{{ url_for('home') }}" class="{{ 'active' if active=='home' else '' }}">Home</a>
    <a href="{{ url_for('add_input_page') }}" class="{{ 'active' if active=='add_input' else '' }}">Add Input</a>
    <a href="{{ url_for('make_page') }}" class="{{ 'active' if active=='create' else '' }}">Create</a>
    <a href="{{ url_for('activity_page') }}" class="{{ 'active' if active=='activity' else '' }}">Activity</a>
    <a href="{{ url_for('organisation_page') }}" class="{{ 'active' if active=='organisation' else '' }}">Organisation</a>
    <a href="{{ url_for('media_library_page') }}" class="{{ 'active' if active=='media' else '' }}">Media library</a>
    <a href="{{ url_for('privacy_page') }}" class="{{ 'active' if active=='privacy' else '' }}">Privacy</a>
    <a href="{{ url_for('status_page') }}" class="{{ 'active' if active=='status' else '' }}">Status</a>
    <a href="{{ url_for('sign_in_page') }}" class="{{ 'active' if active=='signin' else '' }}">Sign in</a>
    <a id="backend-pill" href="{{ health_url }}" target="_blank" rel="noopener"
       title="Backend status (click for full health JSON)">
      <span id="backend-pill-dot"></span>
      <span id="backend-pill-text">checking&hellip;</span>
    </a>
  </nav>
</header>
<main class="wrap">
{{ body | safe }}
</main>
<script>
(function(){
  var HEALTH_URL = {{ health_url|tojson }};
  function check(){
    fetch(HEALTH_URL,{cache:'no-store'}).then(r=>r.json().then(j=>({s:r.status,j:j}))).then(o=>{
      var ok = o.s === 200 && o.j && o.j.ok;
      var dot = document.getElementById('backend-pill-dot');
      var txt = document.getElementById('backend-pill-text');
      if(!dot||!txt) return;
      dot.style.background = ok ? '#2cc97f' : '#ff5d6c';
      txt.textContent = ok ? 'online' : 'offline';
    }).catch(function(){
      var dot = document.getElementById('backend-pill-dot');
      var txt = document.getElementById('backend-pill-text');
      if(!dot||!txt) return;
      dot.style.background = '#ff5d6c'; txt.textContent='offline';
    });
  }
  check(); setInterval(check, 30000);
})();
</script>
<script>
/* === MediaHub UI Framework: loader + toast + form binding === */
(function(){
  var MH = window.MH = window.MH || {};
  var loaderEl = document.getElementById('mh-loader');
  var loaderHideTimer = null;

  MH.showLoader = function(text, sub) {
    if (!loaderEl) return;
    if (loaderHideTimer) { clearTimeout(loaderHideTimer); loaderHideTimer = null; }
    if (text) loaderEl.querySelector('.mh-loader-text').textContent = text;
    if (sub !== undefined) loaderEl.querySelector('.mh-loader-sub').textContent = sub;
    loaderEl.classList.add('show');
  };
  MH.hideLoader = function() {
    if (!loaderEl) return;
    loaderEl.classList.remove('show');
  };

  var toastContainer = document.getElementById('mh-toast-container');
  var ICONS = {
    success: '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    error:   '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    info:    '<svg class="mh-toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };
  MH.toast = function(message, type, ms) {
    if (!toastContainer) return;
    type = type || 'info';
    var t = document.createElement('div');
    t.className = 'mh-toast ' + type;
    t.setAttribute('role', type === 'error' ? 'alert' : 'status');
    t.innerHTML = (ICONS[type] || ICONS.info) +
      '<div style="flex:1;min-width:0">' + message + '</div>' +
      '<button class="mh-toast-close" aria-label="Dismiss">&times;</button>';
    toastContainer.appendChild(t);
    var close = function(){
      t.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
      t.style.opacity = '0'; t.style.transform = 'translateX(16px)';
      setTimeout(function(){ if (t.parentNode) t.remove(); }, 220);
    };
    t.querySelector('.mh-toast-close').addEventListener('click', close);
    setTimeout(close, ms || (type === 'error' ? 7000 : 4500));
  };

  function bindForms() {
    document.querySelectorAll('form').forEach(function(form){
      if (form.dataset.mhBound === '1') return;
      form.dataset.mhBound = '1';
      if (form.dataset.noLoader === '1') return;
      form.addEventListener('submit', function(){
        var method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method === 'get') return;
        var btn = form.querySelector('button[type=submit], input[type=submit]');
        if (btn && !btn.classList.contains('loading')) {
          btn.classList.add('loading');
        }
        var msg = form.dataset.loaderText || 'Working on it';
        var sub = form.dataset.loaderSub || 'This usually takes a few seconds';
        MH.showLoader(msg, sub);
      });
    });
  }
  if (document.readyState !== 'loading') bindForms();
  else document.addEventListener('DOMContentLoaded', bindForms);

  // Re-bind after dynamic content (useful for SPA-like fragments)
  MH.bindForms = bindForms;

  // Wrap fetch for explicit MH usage
  MH.fetch = function(url, options) {
    MH.showLoader();
    return fetch(url, options).then(function(r){
      MH.hideLoader();
      if (!r.ok) MH.toast('Request failed (' + r.status + ')', 'error');
      return r;
    }).catch(function(err){
      MH.hideLoader();
      MH.toast('Network error: ' + (err && err.message || 'unknown'), 'error');
      throw err;
    });
  };

  // Phase 1.4 — "Use in next caption". Re-runs the caption LLM with
  // Multi-tenant Buffer connect — called from the inline form that
  // the schedule modal renders when /api/buffer/channels returns 401.
  // POSTs the pasted access token to /api/organisation/connect-buffer
  // which validates against Buffer and persists on the active org's
  // ClubProfile. On success, the modal silently retries the channel
  // listing so the user lands in the normal schedule flow.
  window.mhConnectBufferFromModal = function() {
    var API_BASE = window._API_BASE || '';
    var input = document.getElementById('mh-buf-token');
    var btn = document.getElementById('mh-buf-connect');
    if (!input || !btn) return;
    var token = (input.value || '').trim();
    if (!token) {
      input.focus();
      return;
    }
    var origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Connecting…';
    fetch(API_BASE + '/api/organisation/connect-buffer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({buffer_access_token: token}),
    }).then(function(r){
      return r.json().then(function(j){ return {status: r.status, body: j}; });
    }).then(function(o){
      btn.disabled = false;
      btn.textContent = origLabel;
      if (o.status >= 200 && o.status < 300 && o.body && o.body.ok) {
        // Token saved. Re-run the channel listing — it'll succeed now.
        var runId = document.getElementById('mh-sched-run-id').value;
        var cardId = document.getElementById('mh-sched-card-id').value;
        var pillId = document.getElementById('mh-sched-pill-id').value;
        if (typeof window.mhScheduleOpen === 'function') {
          window.mhScheduleOpen(runId, cardId, pillId);
        }
        return;
      }
      var msg = (o.body && (o.body.message || o.body.error)) || ('HTTP ' + o.status);
      var err = document.getElementById('mh-sched-error');
      if (err) {
        err.style.display = 'block';
        err.textContent = msg;
      } else if (window.MH && typeof window.MH.toast === 'function') {
        window.MH.toast(msg, 'error');
      } else {
        alert(msg);
      }
    }).catch(function(e){
      btn.disabled = false;
      btn.textContent = origLabel;
      alert('Network error: ' + (e && e.message || e));
    });
  };

  // the visible explainer text injected as a required content
  // instruction. The result lands in a small panel below the
  // explainer (panel_id), preserving the user's reading flow rather
  // than dumping into a modal.
  window.mhUseWhyInCaption = function(btn, captionUrl, panelId) {
    var panel = document.getElementById(panelId);
    var origLabel = btn.textContent;
    btn.disabled = true; btn.textContent = 'Generating…';
    if (panel) {
      panel.style.display = 'block';
      panel.textContent = 'Asking the AI to weave the reasoning into a fresh caption…';
    }
    var url = captionUrl + (captionUrl.indexOf('?') === -1 ? '?' : '&') + 'include_why=1&tone=ai&n_variants=1';
    fetch(url, {method: 'POST', cache: 'no-store'}).then(function(r){
      return r.json().then(function(j){ return {status: r.status, body: j}; });
    }).then(function(o){
      btn.disabled = false; btn.textContent = origLabel;
      if (!panel) return;
      var caption = (o.body && o.body.caption) || '';
      if (o.body && o.body.error === 'no_key') {
        panel.innerHTML = '<strong style="color:#f59e0b">AI is in heuristic mode.</strong> '
          + '<span>Contact your administrator to enable AI.</span>';
        return;
      }
      if (caption) {
        panel.innerHTML = '<div style="font-weight:600;color:#A78BFA;font-size:11px;'
          + 'text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">'
          + 'Caption with reasoning woven in</div>'
          + '<div style="margin-bottom:8px">' + caption.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</div>'
          + '<button class="btn secondary" type="button" style="font-size:11px;padding:4px 10px" '
          + 'onclick="navigator.clipboard.writeText(this.parentElement.querySelector(\'div:nth-child(2)\').textContent);'
          + 'this.textContent=\'Copied\\u2009\\u2713\'">Copy</button>';
      } else {
        panel.innerHTML = '<strong style="color:#ff8a99">Generation failed.</strong> '
          + ((o.body && (o.body.message || o.body.error)) || ('HTTP ' + o.status));
      }
    }).catch(function(e){
      btn.disabled = false; btn.textContent = origLabel;
      if (panel) panel.innerHTML = '<strong style="color:#ff8a99">Network error.</strong> '
        + (e && e.message || e);
    });
  };

  // Server-flashed messages: any element with data-mh-flash gets shown then removed.
  document.querySelectorAll('[data-mh-flash]').forEach(function(el){
    MH.toast(el.getAttribute('data-mh-message') || el.textContent || '',
             el.getAttribute('data-mh-type') || 'info');
    el.remove();
  });

  // Hide loader when navigating back via bfcache (Safari/Firefox)
  window.addEventListener('pageshow', function(e){
    if (e.persisted) MH.hideLoader();
  });
})();
</script>
</body>
</html>
""", title=title, css=BASE_CSS, body=body, active=active,
               health_url=url_for("healthz"))


# ---------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024   # 50 MB
    app.url_map.strict_slashes = False

    # Persistent SECRET_KEY &mdash; survives restarts and redeploys.
    # Priority: env var > persisted file > generated + saved.
    _secret = os.environ.get("SECRET_KEY", "")
    if not _secret:
        _persistent_path = DATA_DIR / ".secret_key"
        if _persistent_path.exists():
            try:
                _secret = _persistent_path.read_text().strip()
            except OSError:
                pass
        if not _secret:
            _secret = os.urandom(32).hex()
            try:
                _persistent_path.write_text(_secret)
            except OSError:
                pass  # writable fallback not available; sessions won't survive restart
    app.config["SECRET_KEY"] = _secret

    # Apply SCRIPT_NAME middleware so url_for generates prefixed URLs when
    # running behind a reverse-proxy that mounts the app at a sub-path
    # (e.g. the pplx.app dev environment serves us under /port/5000/...).
    # Default is empty so production deployments — including Render —
    # generate clean root-relative URLs. Set SCRIPT_NAME=/port/5000 in
    # dev to restore the old behaviour.
    _script_name = os.environ.get("SCRIPT_NAME", "").rstrip("/")
    if _script_name:
        _real_wsgi = app.wsgi_app

        def _script_name_middleware(environ, start_response):
            environ["SCRIPT_NAME"] = _script_name
            path_info = environ.get("PATH_INFO", "")
            if path_info.startswith(_script_name):
                environ["PATH_INFO"] = path_info[len(_script_name):] or "/"
            return _real_wsgi(environ, start_response)

        app.wsgi_app = _script_name_middleware  # type: ignore[assignment]

    # ---- Active organisation: session memory + first-run gate ----------
    #
    # The AI engine cannot produce on-brand content without knowing who
    # the organisation is. Until that's set up we block content-production
    # routes and steer the user to /organisation/setup. The active profile
    # id is cached in the Flask session so the user doesn't have to
    # re-select it every time — and the profile itself lives on disk
    # (DATA_DIR/club_profiles/<id>.json) so it survives container
    # restarts.

    # Routes that are always reachable even when no organisation is set up.
    _SETUP_EXEMPT_ENDPOINTS = frozenset({
        "home",
        "organisation_page",
        "organisation_setup",
        "organisation_setup_capture",
        "organisation_set_active",
        # Phase 1.5 — the profile-picker page must be reachable without
        # an active org (it's how the user PICKS one). Same for the POST
        # endpoints that switch / delete.
        "sign_in_page",
        "sign_in_post",
        "sign_in_delete",
        # /settings now redirects to / so doesn't actually need exempting,
        # but we keep the endpoint name in the allow-list so a directly-
        # hit /settings URL doesn't get caught by the gate before reaching
        # the redirect.
        "settings_page",
        "healthz",
        "healthz_deps",
        "healthz_memory",
        # /health is the deep dep-checking probe; it must also be
        # reachable without an active org (and outside the API prefix
        # allowlist below — it returns HTML/JSON, not JSON-only).
        "health",
        # Phase 1.5 — public status page, JSON twin, and operator usage
        # dashboard must be reachable without an active org. The first
        # two are public trust signals; the last is operator-only by
        # virtue of living under /healthz/* alongside /healthz/deps.
        "status_page",
        "api_status_json",
        "healthz_usage",
        "static",
    })
    # API endpoints that should return a JSON 409 instead of redirecting.
    _SETUP_EXEMPT_API_PREFIXES = (
        "/api/llm",
        "/api/health",
        "/api/organisation",
    )

    def _active_profile_id() -> Optional[str]:
        """Return the currently-selected organisation id, or None."""
        # 1. Explicit session pin (set when the user saves an org).
        pid = session.get("active_profile_id")
        if pid:
            prof = load_profile(pid)
            if prof:
                return prof.profile_id
            # Stale pin — drop it and fall through.
            session.pop("active_profile_id", None)
        # 2. Fall back to the most-recent profile on disk so a returning
        #    user on a new session still finds their org.
        profs = list_profiles()
        if not profs:
            return None
        # list_profiles() sorts alphabetically; prefer the file with the
        # most recent mtime so "last edited" wins.
        try:
            from .club_profile import _profiles_dir
            d = _profiles_dir()
            best = max(profs, key=lambda p: (d / f"{p.profile_id}.json").stat().st_mtime)
        except Exception:
            best = profs[0]
        session["active_profile_id"] = best.profile_id
        return best.profile_id

    def _active_profile() -> Optional[ClubProfile]:
        pid = _active_profile_id()
        return load_profile(pid) if pid else None

    # Expose the helpers as app-level functions so other routes can reach
    # them without re-implementing the lookup. (Routes defined later in
    # create_app() close over these via the enclosing scope.)
    app.active_profile_id = _active_profile_id  # type: ignore[attr-defined]
    app.active_profile = _active_profile        # type: ignore[attr-defined]

    @app.before_request
    def _gate_until_org_ready():
        # Tests bypass the gate by default — they assert specific
        # behaviour of downstream routes and shouldn't have to seed a
        # profile. Tests that exercise the gate set TESTING=False on
        # the app explicitly (see test_org_setup_gate.py).
        if app.config.get("TESTING") and not app.config.get("ENFORCE_ORG_GATE"):
            return None
        ep = request.endpoint or ""
        # Always allow static, the home page, settings, health, and the
        # organisation routes themselves.
        if ep in _SETUP_EXEMPT_ENDPOINTS:
            return None
        path = request.path or ""
        # JSON-style endpoints get a 409 instead of a redirect so the
        # browser fetch() call can show a friendly inline error.
        is_api = path.startswith("/api/")
        if is_api and any(path.startswith(p) for p in _SETUP_EXEMPT_API_PREFIXES):
            return None
        prof = _active_profile()
        if prof is not None and prof.is_ready():
            return None
        if is_api:
            return (
                jsonify({
                    "ok": False,
                    "error": "organisation_not_ready",
                    "message": (
                        "Set up your organisation before producing content. "
                        "MediaHub needs to know who you are first."
                    ),
                    "setup_url": url_for("organisation_setup"),
                }),
                409,
            )
        # Browser request — redirect to the first-run flow.
        return redirect(url_for("organisation_setup"))

    # ---- HOME ----------------------------------------------------------
    @app.route("/")
    def home():
        """Rebuilt home page (Phase 1.5 polish).

        Two-button hero — "Create organisation" + "Sign in to existing" —
        plus the established four-step explainer. When an org is already
        pinned, the hero swaps in a "Continue as <name>" CTA pointing at
        Add Input, with the sign-in / create paths still accessible below
        so the user can switch tenants without rummaging through nav.
        """
        prof = _active_profile()
        existing = list_profiles()
        n_orgs = len(existing)

        # Compute a small run-count for the hero meta line so the page
        # doesn't feel hollow once the user has activity.
        n_runs = 0
        try:
            conn = _db()
            n_runs = int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
            conn.close()
        except Exception:
            pass

        # --- Hero ----------------------------------------------------------
        if prof and prof.is_ready():
            # Returning user with a pinned org. Lead with "continue" + give
            # secondary routes to sign-out / create another.
            hero_h1 = (
                f'<span class="grad">{_h(prof.display_name)}</span><br>'
                'is set up &mdash; let&rsquo;s make something.'
            )
            hero_lede = (
                'Your brand voice, palette, and logo are loaded. Captions, '
                'graphics, and motion videos will arrive on-brand. Anything '
                'you generate goes through your approval before it leaves '
                'this deployment.'
            )
            hero_actions = (
                f'<a class="mh-cta-primary" href="{url_for("add_input_page")}">'
                'Create new content &rarr;</a>'
                f'<a class="mh-cta-secondary" href="{url_for("sign_in_page")}">'
                'Switch organisation</a>'
                f'<a class="mh-cta-secondary" href="{url_for("organisation_page")}">'
                'Edit profile</a>'
            )
            eyebrow = 'Pinned organisation'
        else:
            # Fresh visit (or signed-out). Two equally-weighted CTAs.
            hero_h1 = (
                'Turn results into <span class="grad">on-brand</span><br>'
                'content in minutes.'
            )
            hero_lede = (
                'MediaHub reads your club website, social profiles, and brand '
                'guidelines, then writes captions, builds graphics, and renders '
                'motion videos in your voice. Set up once. Reuse forever. '
                'Nothing posts without you.'
            )
            if n_orgs > 0:
                hero_actions = (
                    f'<a class="mh-cta-primary" href="{url_for("sign_in_page")}">'
                    f'Sign in &rarr;</a>'
                    f'<a class="mh-cta-secondary" href="{url_for("organisation_setup")}">'
                    'Create new organisation</a>'
                )
            else:
                hero_actions = (
                    f'<a class="mh-cta-primary" href="{url_for("organisation_setup")}">'
                    'Create your first organisation &rarr;</a>'
                    f'<a class="mh-cta-secondary" href="{url_for("status_page")}">'
                    'See deployment status</a>'
                )
            eyebrow = 'Sport content automation'

        # Meta line under the CTAs — honest counts, no fake numbers.
        meta_parts = []
        if n_orgs:
            meta_parts.append(
                f'<span><b>{n_orgs}</b> {"organisation" if n_orgs == 1 else "organisations"}</span>'
            )
        if n_runs:
            meta_parts.append(
                f'<span><b>{n_runs}</b> total {"run" if n_runs == 1 else "runs"}</span>'
            )
        if prof and prof.brand_capture_status in ("ok", "ok_heuristic"):
            meta_parts.append('<span>Brand voice <b>captured</b></span>')
        meta_html = ""
        if meta_parts:
            sep = '<span class="dot">&middot;</span>'
            meta_html = '<div class="mh-hero-meta">' + sep.join(meta_parts) + '</div>'

        hero_html = (
            '<section class="mh-hero">'
            f'<span class="mh-hero-eyebrow">{_h(eyebrow)}</span>'
            f'<h1>{hero_h1}</h1>'
            f'<p class="lede">{_h(hero_lede)}</p>'
            f'<div class="mh-hero-actions">{hero_actions}</div>'
            f'{meta_html}'
            '</section>'
        )

        # --- Four-step explainer (kept; still useful first-touch context) ---
        steps_html = (
            '<div class="mh-section-eyebrow">How it works</div>'
            '<h2 class="mh-section-title">From results to ready-to-post content, end to end</h2>'
            '<div class="mh-steps">'
            '<div class="mh-step"><div class="mh-step-num">1</div><h3>Add an input</h3>'
            '<p>Upload a Hytek results file, paste a sponsor brief, or describe a moment in your own words. Any sport. Any club.</p></div>'
            '<div class="mh-step"><div class="mh-step-num">2</div><h3>We detect the moments</h3>'
            '<p>The engine spots PBs, medals, first-times, comebacks and standout swims, then ranks them by content-worthiness.</p></div>'
            '<div class="mh-step"><div class="mh-step-num">3</div><h3>On-brand drafts appear</h3>'
            "<p>Captions are written in your club&rsquo;s voice, using your tone, sponsor rules, and example posts you&rsquo;ve shared.</p></div>"
            '<div class="mh-step"><div class="mh-step-num">4</div><h3>Approve and post</h3>'
            '<p>You review, edit, approve. Nothing goes out without you. Export as text, copy to Stories, or download a pack.</p></div>'
            '</div>'
        )

        return _layout("Home", hero_html + steps_html, active="home")

    # ---- ACTIVITY &mdash; recent runs scoped to the active organisation ----
    @app.route("/activity")
    def activity_page():
        prof = _active_profile()
        # The gate ensures we only land here with a ready profile; the
        # extra guard keeps the page honest if invoked under TESTING mode.
        if prof is None:
            return redirect(url_for("organisation_setup"))

        conn = _db()
        rows = conn.execute(
            "SELECT id, created_at, finished_at, status, profile_id, "
            "meet_name, our_swims, n_cards, n_queue, error, file_name "
            "FROM runs WHERE profile_id = ? "
            "ORDER BY created_at DESC LIMIT 100",
            (prof.profile_id,),
        ).fetchall()
        conn.close()

        # Phase 1.3 — Recent posting activity. Last 20 Buffer attempts for
        # this organisation. Fail-soft: if the log module isn't available
        # or the DB lookup errors, the rest of the page still renders.
        try:
            from mediahub.publishing import posting_log as _plog
            recent_attempts = _plog.recent_attempts(prof.profile_id, limit=20)
        except Exception:
            recent_attempts = []

        # Per-run schedule summary — pulled from the workflow store on
        # demand. Bounded by len(rows) ≤ 100 so the cost is fine.
        summaries: dict[str, dict] = {}
        try:
            ws = _get_wf_store()
        except Exception:
            ws = None
        if ws is not None:
            try:
                from mediahub.workflow.status import ScheduleStatus
            except Exception:
                ScheduleStatus = None
            for r in rows:
                run_id = r["id"]
                summary = {"scheduled": 0, "published": 0, "failed": 0}
                try:
                    states = ws.load(run_id) or {}
                    for cs in states.values():
                        s = getattr(cs, "schedule_status", None)
                        val = s.value if hasattr(s, "value") else (s or "queued")
                        if val == "scheduled":
                            summary["scheduled"] += 1
                        elif val == "published":
                            summary["published"] += 1
                        elif val == "failed":
                            summary["failed"] += 1
                except Exception:
                    pass
                summaries[run_id] = summary

        if not rows:
            empty_body = (
                f'<h1 style="margin-bottom:6px">Activity</h1>'
                f'<p class="dim" style="margin-bottom:24px">Runs for '
                f'<b>{_h(prof.display_name)}</b>.</p>'
                '<div class="card empty">No runs yet for this organisation. '
                f'<a href="{url_for("add_input_page")}">Create your first piece of content &rarr;</a>'
                '</div>'
            )
            return _layout("Activity", empty_body, active="activity")

        def _schedule_summary_html(rid: str) -> str:
            s = summaries.get(rid) or {}
            if not (s.get("scheduled") or s.get("published") or s.get("failed")):
                return '<span class="muted" style="font-size:11px">&mdash;</span>'
            parts = []
            if s.get("scheduled"):
                parts.append(f'<span class="tag info" style="font-size:11px">'
                             f'{s["scheduled"]} scheduled</span>')
            if s.get("published"):
                parts.append(f'<span class="tag good" style="font-size:11px">'
                             f'{s["published"]} published</span>')
            if s.get("failed"):
                parts.append(f'<span class="tag bad" style="font-size:11px">'
                             f'{s["failed"]} failed</span>')
            return " ".join(parts)

        rows_html = ""
        n_errored = 0
        for r in rows:
            badge = {"done": "good", "running": "info", "queued": "info",
                     "error": "bad"}.get(r["status"], "")
            review_href = url_for('review', run_id=r['id'])
            delete_href = url_for('privacy_delete_run', run_id=r['id'])
            rows_html += (
                f'<tr><td><a href="{review_href}">{_h(r["meet_name"] or r["file_name"] or r["id"])}</a></td>'
                f'<td><span class="tag {badge}">{_h(r["status"])}</span></td>'
                f'<td>{_h(r["our_swims"] or 0)}</td>'
                f'<td>{_h(r["n_queue"] or 0)} / {_h(r["n_cards"] or 0)}</td>'
                f'<td>{_schedule_summary_html(r["id"])}</td>'
                f'<td class="muted">{_h((r["created_at"] or "")[:19])}</td>'
                f'<td><form method="post" action="{delete_href}" '
                f'style="display:inline" data-no-loader="1" onsubmit="return confirm(\'Delete this run? This cannot be undone.\')">'
                f'<button class="btn danger" type="submit" '
                f'style="font-size:11px;padding:4px 10px">Delete</button>'
                f'</form></td></tr>'
            )
            # Phase 1.5 — "Why did this run fail?" surfacing. Errored runs
            # get a second row with the persisted error message so an
            # operator (or pilot club) can see what went wrong without
            # clicking through to the broken review page.
            if r["status"] == "error" and r["error"]:
                n_errored += 1
                err_text = str(r["error"])
                # Trim absurdly long stack traces — keep the first ~600 chars.
                truncated = err_text[:600] + ("…" if len(err_text) > 600 else "")
                rows_html += (
                    '<tr class="run-error-row">'
                    '<td colspan="7" style="padding:6px 14px 14px 14px;'
                    'background:rgba(255,93,108,0.06);border-left:3px solid #ff5d6c">'
                    '<details>'
                    '<summary style="cursor:pointer;font-size:13px;font-weight:600;'
                    'color:#ffbcc3">Why did this run fail?</summary>'
                    '<pre style="margin:8px 0 0;padding:10px 12px;'
                    'background:rgba(0,0,0,0.25);border-radius:6px;'
                    'font-size:12px;white-space:pre-wrap;word-break:break-word">'
                    f'{_h(truncated)}</pre>'
                    '</details>'
                    '</td></tr>'
                )

        # Recent posting activity panel — bottom-of-page, collapsed by
        # default when empty; expanded when there's something to see so
        # failures aren't hidden behind a click.
        posting_panel_html = ""
        if recent_attempts:
            attempts_rows = ""
            for a in recent_attempts:
                status = a.get("status") or ""
                kind = a.get("error_kind") or ""
                if status == "ok":
                    badge_html = '<span class="tag good" style="font-size:11px">ok</span>'
                else:
                    label = kind or "failed"
                    badge_html = f'<span class="tag bad" style="font-size:11px">{_h(label)}</span>'
                excerpt = (a.get("caption_excerpt") or "")[:120]
                when = (a.get("attempted_at") or "")[:19]
                channel = a.get("channel_name") or a.get("channel_id") or "&mdash;"
                err = a.get("error_message") or ""
                attempts_rows += (
                    f'<tr><td class="muted" style="font-size:12px">{_h(when)}</td>'
                    f'<td style="font-size:12px">{_h(channel)}</td>'
                    f'<td>{badge_html}</td>'
                    f'<td style="font-size:12px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{_h(excerpt)}">{_h(excerpt)}</td>'
                    f'<td style="font-size:12px;color:#ff8a99" title="{_h(err)}">{_h(err[:80])}</td>'
                    f'</tr>'
                )
            posting_panel_html = (
                '<h2 style="margin-top:30px;margin-bottom:6px;font-size:18px">'
                'Recent posting activity</h2>'
                '<p class="dim" style="margin-bottom:14px;font-size:13px">'
                f'Last {len(recent_attempts)} Buffer attempts for this organisation. '
                'Failures stay listed here so you can see what went wrong without '
                'digging through individual runs.</p>'
                '<div class="card"><table>'
                '<thead><tr><th>When</th><th>Channel</th><th>Status</th>'
                '<th>Caption excerpt</th><th>Error</th></tr></thead>'
                f'<tbody>{attempts_rows}</tbody>'
                '</table></div>'
            )

        # Phase 1.5 — surface the number of failed runs at the top of the
        # page so an operator triaging issues sees the scope before reading
        # individual rows.
        failure_callout = ""
        if n_errored:
            label = "1 run failed" if n_errored == 1 else f"{n_errored} runs failed"
            failure_callout = (
                '<div class="card" style="padding:12px 18px;margin-bottom:20px;'
                'background:rgba(255,93,108,0.06);border-left:3px solid #ff5d6c">'
                f'<b>{_h(label)}</b> in the last 100 runs. '
                'Expand <i>Why did this run fail?</i> on each row below to '
                'see the pipeline error.</div>'
            )

        body = (
            f'<h1 style="margin-bottom:6px">Activity</h1>'
            f'<p class="dim" style="margin-bottom:24px">Recent runs for '
            f'<b>{_h(prof.display_name)}</b>.</p>'
            f'{failure_callout}'
            '<div class="card"><table>'
            '<thead><tr><th>Input</th><th>Status</th>'
            '<th>Matched</th><th>Queue / Total</th><th>Schedule</th>'
            '<th>Started</th><th></th></tr></thead>'
            f'<tbody>{rows_html}</tbody>'
            '</table></div>'
            f'{posting_panel_html}'
        )
        return _layout("Activity", body, active="activity")


    # ---- UPLOAD --------------------------------------------------------
    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        # V8.2 issue 3: every upload now goes through /upload/configure.
        # The upload form has only the file input + submit. Branding is
        # collected on the configure step, after we've parsed the file.
        if request.method == "POST":
            f = request.files.get("file")
            if not f or not f.filename:
                return _layout("Upload", '<div class="card"><p class="tag bad">No file selected.</p></div>', active="add_input")
            data = f.read()
            if not data:
                return _layout("Upload", '<div class="card"><p class="tag bad">Uploaded file was empty.</p></div>', active="add_input")

            temp_run_id = uuid.uuid4().hex[:12]
            tmp_dir = RUNS_DIR / temp_run_id
            tmp_dir.mkdir(parents=True, exist_ok=True)
            (tmp_dir / "input.bin").write_bytes(data)
            meta = {
                "filename": f.filename,
                "profile_id": None,
                "use_cache": True,
                "fetch_pbs": True,
                "display_name": "",
            }
            # Light parse: extract clubs from the file. Only clubs that
            # actually appear in this meet are listed on configure.
            try:
                from mediahub.interpreter import interpret_document
                interpreted = interpret_document(data, hint=None)
                clubs: list[str] = []
                seen: set[str] = set()
                for ev in interpreted.events:
                    for sw in ev.swims:
                        c = (sw.club or "").strip()
                        if c and c.lower() not in seen:
                            seen.add(c.lower())
                            clubs.append(c)
                meta["clubs"] = sorted(clubs, key=str.lower)
                meta["meet_name"] = interpreted.meet_name or ""
                meta["n_events"] = len(interpreted.events)
                meta["file_byte_size"] = len(data)
            except Exception as exc:
                meta["clubs"] = []
                meta["parse_error"] = str(exc)
                meta["file_byte_size"] = len(data)
            (tmp_dir / "upload_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            return redirect(url_for("upload_configure", run_id=temp_run_id))

        body = f"""
<h1>Upload meet file</h1>
<div class="card">
  <form method="post" enctype="multipart/form-data">
    <label>Meet results file</label>
    <input type="file" name="file" accept=".hy3,.zip,.pdf" required />
    <p class="dim" style="margin-top:4px;font-size:12px">Accepted: Hytek Meet Manager .hy3 or .zip export, or a Sportsystems PDF results file.</p>
    <p class="dim" style="margin-top:6px;font-size:12px">
      You'll choose your club, upload your logo, and add photos on the next step &mdash; after we read your file.
    </p>
    <div style="margin-top:18px"><button class="btn" type="submit">Continue &rarr;</button></div>
  </form>
</div>
"""
        return _layout("Upload", body, active="add_input")

    # ---- UPLOAD CONFIGURE (V8.1 issue 6: two-step; V8.2 issue 6: photos) ---
    def _render_configure(run_id: str, meta: dict, *, error: str = "",
                          selected_club: str = "") -> str:
        clubs = meta.get("clubs") or []
        meet_name = meta.get("meet_name") or ""
        parse_err = meta.get("parse_error") or ""

        # No clubs detected \u2192 render a polished error state, NOT a broken form.
        # Differentiate three common causes so the user knows what to fix:
        #   1. file is too small / unreadable (likely a broken download)
        #   2. file parsed OK but contains no events (probably an entry
        #      list or meet preview, not a results file)
        #   3. file parsed and has events but no clubs (rare; format quirk)
        if not clubs:
            upload_url = url_for("upload")
            byte_size = int(meta.get("file_byte_size") or 0)
            n_events = int(meta.get("n_events") or 0)

            if byte_size < 2048:
                headline = "That file doesn't look like a meet results file"
                explain = (
                    f'<p>The file <code>{_h(meta.get("filename") or "(unknown)")}</code> '
                    f'is only {byte_size} bytes &mdash; far too small to be a real '
                    'meet results file. The most common cause is a broken download '
                    '(an HTML "404 Not Found" page saved as a PDF, or a partial save).</p>'
                    '<p class="dim" style="font-size:13px;margin-top:8px">'
                    'Try downloading the file again from the source and re-uploading. '
                    'A real Hytek PDF or HY3 is usually 100 KB or larger.</p>'
                )
            elif n_events == 0:
                headline = "That file looks like a meet preview, not results"
                explain = (
                    f'<p>The file <code>{_h(meta.get("filename") or "(unknown)")}</code> '
                    'parsed OK but doesn\'t contain any events with results.</p>'
                    '<p class="dim" style="font-size:13px;margin-top:8px">'
                    'This usually means you uploaded an entry list, a heat sheet, or '
                    'meet conditions document. Wait until the meet finishes and the '
                    'organisers publish the actual results file.</p>'
                )
            else:
                headline = "We couldn't read clubs from that file"
                explain = (
                    f'<p>The file <code>{_h(meta.get("filename") or "(unknown)")}</code> '
                    f'has {n_events} events but no club information we can filter on. '
                    'This is rare and usually means the file is from a meet management '
                    'system MediaHub doesn\'t yet support.</p>'
                )
            err_explain = (
                f'<p class="dim" style="margin-bottom:12px;font-size:13px">'
                f'Parser error: <code>{_h(parse_err)}</code></p>'
                if parse_err else ""
            )
            body = f"""
<h1>{_h(headline)}</h1>
<div class="card">
  {explain}
  {err_explain}
  <p class="dim" style="font-size:13px;margin-top:14px">Supported formats: Hytek Meet Manager <code>.hy3</code>, a <code>.zip</code> containing one, or a Sportsystems PDF results file.</p>
  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
    <a class="btn" href="{upload_url}">\u2190 Try another file</a>
    <a class="btn secondary" href="{url_for('add_input_page')}">Pick a different input type</a>
  </div>
</div>
"""
            return _layout("Couldn't read file", body, active="add_input")

        # V8.2 issue 4: ONLY clubs from this file are listed.
        opts = "".join(
            f'<option value="{_h(c)}"{" selected" if c == selected_club else ""}>{_h(c)}</option>'
            for c in clubs
        )
        err_html = (
            f'<p class="tag bad" style="margin-bottom:14px">{_h(error)}</p>' if error else ""
        )

        # Pre-fill the brand fields from the active organisation so the
        # user never re-enters logo / colours they already gave us at
        # /organisation/setup. Phase 1.5 consolidation: logos live on the
        # profile, not on individual runs. Colour pickers stay because
        # they're cheap per-run overrides for the rare case someone wants
        # a different palette for a sponsor-themed post.
        active_prof = _active_profile()
        prof_primary = "#0A2540"
        prof_secondary = "#101820"
        prof_accent = "#FFD86E"
        prof_logo_html = ""
        if active_prof is not None:
            prof_primary = (getattr(active_prof, "brand_primary", "") or prof_primary).strip()
            prof_secondary = (getattr(active_prof, "brand_secondary", "") or prof_secondary).strip()
            extracted = getattr(active_prof, "brand_palette_extracted", {}) or {}
            if isinstance(extracted, dict) and extracted.get("accent"):
                prof_accent = extracted["accent"]
            logo_url = (getattr(active_prof, "brand_logo_url", "") or "").strip()
            if logo_url:
                _logo_disp = logo_url[:80] + ("\u2026" if len(logo_url) > 80 else "")
                prof_logo_html = (
                    f'<p class="dim" style="margin:6px 0 0;font-size:12px">'
                    f'Logo: <code style="font-size:11px">'
                    f'{_h(_logo_disp)}</code></p>'
                )
            else:
                prof_logo_html = (
                    '<p class="dim" style="margin:6px 0 0;font-size:12px;color:#F59E0B">'
                    'No logo on your organisation profile. '
                    f'<a href="{url_for("organisation_page")}" '
                    'style="color:#F59E0B;text-decoration:underline">Add one</a> '
                    'so it flows through to every graphic.</p>'
                )

        body = f"""
<h1>Configure this run</h1>
<div class="card">
  <p class="dim">{_h(meet_name) or 'Meet uploaded.'} \u2014 {len(clubs)} clubs detected in this file.</p>
  {err_html}
  <form method="post" enctype="multipart/form-data" data-loader-text="Setting up your run" data-loader-sub="Saving config and starting the pipeline\u2026">
    <input type="hidden" name="run_id" value="{_h(run_id)}" />

    <label>Club to feature</label>
    <select name="club_filter" required>{opts}</select>
    <p class="dim" style="margin-top:4px;font-size:12px">Only clubs that actually appear in this meet are listed.</p>

    <fieldset style="margin-top:18px;border:1px solid var(--border);border-radius:8px;padding:14px 18px">
      <legend style="padding:0 8px;font-size:12px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.5px">Brand &mdash; loaded from your organisation</legend>
      <p class="dim" style="margin:0 0 10px;font-size:12px">
        These come from your <a href="{url_for("organisation_page")}" style="text-decoration:underline">organisation profile</a>.
        Change colours below for a one-off override, or update them once on your profile to apply everywhere.
      </p>
      {prof_logo_html}

      <div style="display:flex;gap:14px;align-items:flex-end;margin-top:12px;flex-wrap:wrap">
        <div><label style="display:block">Primary</label><input type="color" name="primary_colour" value="{_h(prof_primary)}" /></div>
        <div><label style="display:block">Secondary</label><input type="color" name="secondary_colour" value="{_h(prof_secondary)}" /></div>
        <div><label style="display:block">Accent</label><input type="color" name="accent_colour" value="{_h(prof_accent)}" /></div>
      </div>
    </fieldset>

    <fieldset style="margin-top:18px;border:1px solid var(--border);border-radius:8px;padding:14px 18px">
      <legend style="padding:0 8px;font-size:12px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.5px">Photos (optional)</legend>
      <label>Athlete portraits, action shots, venue images (multi-select)</label>
      <input type="file" name="club_photos" multiple accept="image/*" />
      <p class="dim" style="margin-top:4px;font-size:12px">Uploaded photos will be preferred for graphic generation in this run and saved to your media library.</p>
    </fieldset>

    <div style="margin-top:18px"><button class="btn" type="submit">Run pipeline \u2192</button></div>
  </form>
</div>
"""
        return _layout("Configure run", body, active="add_input")

    @app.route("/upload/configure", methods=["GET", "POST"])
    def upload_configure():
        run_id = request.values.get("run_id", "").strip()
        if not run_id:
            return _layout("Configure", '<div class="card"><p class="tag bad">Missing run_id.</p></div>', active="add_input")
        tmp_dir = RUNS_DIR / run_id
        meta_path = tmp_dir / "upload_meta.json"
        input_path = tmp_dir / "input.bin"
        if not (meta_path.exists() and input_path.exists()):
            return _layout("Configure", '<div class="card"><p class="tag bad">Upload session not found or expired.</p></div>', active="add_input")
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            meta = {}

        if request.method == "POST":
            club_filter = (request.form.get("club_filter") or "").strip() or None
            if not club_filter:
                return _layout("Configure", '<div class="card"><p class="tag bad">Pick a club to feature.</p></div>', active="add_input")

            # Phase 1.5 logo consolidation: logos now live on the active
            # organisation profile, not on individual runs. The configure
            # form no longer accepts a club_logo file; the per-run brand
            # kit pulls the logo from the active ClubProfile's
            # brand_logo_url and the colour pickers default to the
            # profile's saved colours (still per-run-overridable).
            active_prof_for_run = _active_profile()
            logo_bytes = None
            logo_filename = None
            primary_form = (request.form.get("primary_colour") or "").strip() or None
            secondary_form = (request.form.get("secondary_colour") or "").strip() or None
            accent_form = (request.form.get("accent_colour") or "").strip() or None
            use_logo_colours = False
            display_name_form = (request.form.get("display_name") or club_filter or "").strip()
            # We always have branding now (the profile guarantees it), so
            # the old "branding required" gate is removed. If somehow
            # neither the profile nor the form supplies colours, the
            # downstream renderer falls back to deterministic defaults.

            data = input_path.read_bytes()
            # Pin the run to the active organisation so it appears on
            # /activity for the right tenant. Falls back to the upload
            # meta only if it carries a profile_id (older flows); modern
            # flows always come through the org-gated /add-input page,
            # so the session pin is the authoritative source.
            profile_id = (
                meta.get("profile_id")
                or _active_profile_id()
                or None
            )
            use_cache = bool(meta.get("use_cache", True))
            fetch_pbs = bool(meta.get("fetch_pbs", True))
            filename = meta.get("filename") or "upload.bin"

            # Kick off the real run; reuse the temp run_id.
            new_run_id = _start_run(
                data, filename, profile_id, use_cache, fetch_pbs,
                club_filter=club_filter,
            )

            # Persist the brand kit (colours) for the new run id. The
            # logo is no longer per-run — it comes from the active
            # profile's brand_logo_url at render time (see
            # content_pack_visual/integration.py fallback). If the
            # profile has a logo, we fetch it once and seed the run's
            # brand kit with it so downstream layout code that expects
            # a local path doesn't trip.
            try:
                from .brand_kit_upload import process_upload as _bk_process
                profile_logo_bytes = None
                profile_logo_name = None
                if active_prof_for_run is not None:
                    url = (getattr(active_prof_for_run, "brand_logo_url", "") or "").strip()
                    if url and (url.startswith("http://") or url.startswith("https://")):
                        try:
                            import requests as _rq
                            r = _rq.get(url, timeout=10)
                            if r.ok and len(r.content) < 5_000_000:
                                profile_logo_bytes = r.content
                                # Derive a sensible filename from the URL
                                # path so the on-disk save uses the right
                                # extension. Default to .png if unknown.
                                from urllib.parse import urlparse
                                path = urlparse(url).path or ""
                                tail = path.rsplit("/", 1)[-1] or "logo.png"
                                if "." not in tail:
                                    tail += ".png"
                                profile_logo_name = tail
                        except Exception:
                            profile_logo_bytes = None
                _bk_process(
                    new_run_id,
                    logo_bytes=profile_logo_bytes,
                    logo_filename=profile_logo_name,
                    primary_form=primary_form,
                    secondary_form=secondary_form,
                    accent_form=accent_form,
                    use_logo_colours=False,
                    display_name=display_name_form,
                )
            except Exception:
                pass

            # V8.2 issue 6: per-run photo library. Save each uploaded photo
            # to runs_v4/<run_id>/media/ + a metadata sidecar, and persist
            # to the V8 media library with profile_id = the synthetic
            # "_run_<new_run_id>" id used by the renderer.
            try:
                photo_files = request.files.getlist("club_photos")
            except Exception:
                photo_files = []
            saved_photos: list[dict] = []
            if photo_files:
                from datetime import datetime
                import mimetypes as _mt
                media_dir = RUNS_DIR / new_run_id / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                run_profile_id = re.sub(
                    r"[^a-z0-9_-]", "-",
                    (club_filter or ("_run_" + new_run_id)).lower(),
                ).strip("-") or ("_run_" + new_run_id)
                for pf in photo_files:
                    if not pf or not pf.filename:
                        continue
                    try:
                        body_bytes = pf.read()
                        if not body_bytes:
                            continue
                        suffix = Path(pf.filename).suffix.lower() or ".jpg"
                        safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(pf.filename).stem)
                        dest = media_dir / f"{uuid.uuid4().hex[:8]}_{safe_stem}{suffix}"
                        dest.write_bytes(body_bytes)
                        meta_entry = {
                            "filename": pf.filename,
                            "path": str(dest),
                            "mime": _mt.guess_type(pf.filename)[0] or "",
                            "uploaded_at": datetime.utcnow().isoformat() + "Z",
                            "size": len(body_bytes),
                        }
                        saved_photos.append(meta_entry)
                        # Persist to V8 media library too, keyed by the run-scoped profile_id.
                        try:
                            from mediahub.media_library.store import get_store as _ml_get
                            from mediahub.media_library.models import MediaAsset as _MA
                            ml = _ml_get()
                            asset = _MA(
                                id="",
                                filename=pf.filename,
                                path=str(dest),
                                type="athlete_action",
                                profile_id=run_profile_id,
                                description_raw="User-uploaded photo (configure step)",
                                permission_status="approved_by_club",
                                approval_status="approved",
                                uploaded_at=meta_entry["uploaded_at"],
                            )
                            ml.save(asset)
                        except Exception:
                            pass
                    except Exception:
                        continue
                # Write a sidecar so the run dir is self-describing.
                try:
                    (media_dir / "manifest.json").write_text(
                        json.dumps({"photos": saved_photos}, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            return redirect(url_for("run_status", run_id=new_run_id))

        return _render_configure(run_id, meta)

    # ---- PROGRESS ------------------------------------------------------
    @app.route("/runs/<run_id>")
    def run_status(run_id):
        _status_url = url_for('api_status', run_id=run_id)
        _review_url = url_for('review', run_id=run_id)
        # Five named stages, mapped from log message substrings.
        # Each stage shows "queued" by default, becomes "active" when its
        # keyword first appears in the log, "done" when the next stage's
        # keyword appears (or the run finishes successfully).
        body = f"""
<h1>Run in progress</h1>
<p class="dim" style="margin-bottom:6px">Sit tight &mdash; we're parsing, ranking and drafting. This usually takes 20&ndash;60 seconds.</p>

<div class="card">
  <div class="mh-stages" id="mh-stages">
    <div class="mh-stage" data-stage="parse"    data-state="queued"><div class="mh-stage-label">1 &middot; Parse</div><div class="mh-stage-text">Reading the file</div></div>
    <div class="mh-stage" data-stage="filter"   data-state="queued"><div class="mh-stage-label">2 &middot; Filter</div><div class="mh-stage-text">Finding your athletes</div></div>
    <div class="mh-stage" data-stage="pb"       data-state="queued"><div class="mh-stage-label">3 &middot; Personal bests</div><div class="mh-stage-text">Checking historical times</div></div>
    <div class="mh-stage" data-stage="detect"   data-state="queued"><div class="mh-stage-label">4 &middot; Detect</div><div class="mh-stage-text">Spotting achievements</div></div>
    <div class="mh-stage" data-stage="generate" data-state="queued"><div class="mh-stage-label">5 &middot; Generate</div><div class="mh-stage-text">Drafting captions</div></div>
  </div>

  <div class="mh-progress-bar indeterminate"><span></span></div>
  <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--ink-muted);margin-top:4px">
    <span id="mh-current-stage">Starting&hellip;</span>
    <span id="mh-step-count">0 steps</span>
  </div>

  <details style="margin-top:18px">
    <summary style="cursor:pointer;color:var(--ink-dim);font-size:13px;user-select:none">Show technical log</summary>
    <div class="progress-log" id="log" style="margin-top:10px">Starting&hellip;</div>
  </details>

  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
    <a id="review-link" class="btn" style="display:none" href="{_review_url}">Open review queue &rarr;</a>
    <a id="home-link"   class="btn secondary" href="{url_for('home')}">View on home</a>
  </div>
</div>

<script>
(function() {{
  var STATUS_URL = {json.dumps(_status_url)};
  var REVIEW_URL = {json.dumps(_review_url)};
  var STAGES = ['parse','filter','pb','detect','generate'];
  // Keyword &rarr; stage. First match wins; we scan each log line.
  var STAGE_PATTERNS = [
    {{re: /interpret|bridg|parse/i,                stage: 'parse'}},
    {{re: /filter|club|swims for/i,                stage: 'filter'}},
    {{re: /PB|personal best|cache/i,               stage: 'pb'}},
    {{re: /detect|recogni|claim|achievement/i,     stage: 'detect'}},
    {{re: /caption|card|generat|render|content/i,  stage: 'generate'}}
  ];
  function detectStage(logLines) {{
    var idx = -1;
    for (var i = 0; i < logLines.length; i++) {{
      for (var k = 0; k < STAGE_PATTERNS.length; k++) {{
        if (STAGE_PATTERNS[k].re.test(logLines[i])) {{
          var s = STAGES.indexOf(STAGE_PATTERNS[k].stage);
          if (s > idx) idx = s;
        }}
      }}
    }}
    return idx;
  }}
  function applyStages(currentIdx, status) {{
    var stageEls = document.querySelectorAll('.mh-stage');
    stageEls.forEach(function(el, i) {{
      if (status === 'error') {{ el.setAttribute('data-state', i <= currentIdx ? 'error' : 'queued'); return; }}
      if (status === 'done')  {{ el.setAttribute('data-state', 'done'); return; }}
      if (i < currentIdx) el.setAttribute('data-state', 'done');
      else if (i === currentIdx) el.setAttribute('data-state', 'active');
      else el.setAttribute('data-state', 'queued');
    }});
    var bar = document.querySelector('.mh-progress-bar');
    if (status === 'done')  {{
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.width = '100%';
    }} else if (status === 'error') {{
      bar.classList.remove('indeterminate');
      bar.firstElementChild.style.background = 'linear-gradient(90deg, var(--bad), #fb7185)';
      bar.firstElementChild.style.width = '100%';
    }} else {{
      bar.classList.add('indeterminate');
    }}
    var labelEl = document.getElementById('mh-current-stage');
    if (status === 'error') labelEl.textContent = 'Run failed';
    else if (status === 'done') labelEl.textContent = 'Complete';
    else if (currentIdx < 0) labelEl.textContent = 'Starting&hellip;';
    else {{
      var labels = ['Reading the file&hellip;','Finding your athletes&hellip;','Checking personal bests&hellip;','Spotting achievements&hellip;','Drafting captions&hellip;'];
      labelEl.textContent = labels[currentIdx] || 'Working&hellip;';
    }}
  }}
  async function poll() {{
    try {{
      var r = await fetch(STATUS_URL, {{cache:'no-store'}});
      var j = await r.json();
      var log = j.log || [];
      var logEl = document.getElementById('log');
      logEl.textContent = log.join('\\n');
      logEl.scrollTop = logEl.scrollHeight;
      document.getElementById('mh-step-count').textContent = log.length + ' step' + (log.length === 1 ? '' : 's');
      var idx = detectStage(log);
      applyStages(idx, j.status);
      if (j.status === 'done') {{
        document.getElementById('review-link').style.display = 'inline-flex';
        if (window.MH) MH.toast('Run complete &mdash; opening review queue', 'success', 2500);
        setTimeout(function() {{ location.replace(REVIEW_URL); }}, 1200);
        return;
      }}
      if (j.status === 'error') {{
        logEl.textContent += '\\n\\nERROR: ' + (j.error || 'unknown');
        if (window.MH) MH.toast('Run failed: ' + (j.error || 'see log'), 'error', 8000);
        return;
      }}
    }} catch (e) {{}}
    setTimeout(poll, 800);
  }}
  poll();
}})();
</script>
"""
        return _layout("Run progress", body, active="add_input")

    @app.route("/api/runs/<run_id>/status")
    def api_status(run_id):
        active = _active_runs.copy_value(run_id)
        if active:
            return jsonify(active)
        # Fallback to persisted status
        conn = _db()
        row = conn.execute(
            "SELECT status, error FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"status": "unknown", "error": "Run not found"}), 404
        return jsonify({"status": row["status"], "error": row["error"], "log": []})

    # ---- REVIEW (V5 Recognition UI) ------------------------------------
    @app.route("/review/<run_id>")
    def review(run_id):
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        meet = data.get("meet") or {}
        cards = data.get("cards") or []
        trust = data.get("trust") or {}
        warnings = data.get("parse_warnings") or []
        sc = data.get("self_check") or {}
        ds = data.get("detector_summary") or {}
        dispatch_log = data.get("dispatch_log") or {}
        rr = data.get("recognition_report") or {}
        recognition_error = data.get("recognition_error") or ""

        # --- Header
        _gt_url = url_for('ground_truth', run_id=run_id)
        _export_url = url_for('api_export', run_id=run_id)
        _rec_json_url = url_for('api_recognition', run_id=run_id)
        _delete_url = url_for('privacy_delete_run', run_id=run_id)
        _status_url = url_for('api_status', run_id=run_id)
        _pack_url = url_for('content_pack', run_id=run_id)
        _reel_url = url_for('api_run_reel', run_id=run_id)
        _turn_into_api = url_for('api_turn_into', run_id=run_id)

        # Prior Turn-Into packs for this run (so the user can revisit them).
        try:
            from mediahub.turn_into import list_packs as _list_ti_packs
            _ti_packs = _list_ti_packs(run_id, base_dir=DATA_DIR / "turn_into_packs")
        except Exception:
            _ti_packs = []

        # --- V7: Workflow state
        _wf_summary = {}
        _wf_states = {}
        _wf_api_base = url_for('api_workflow_set', run_id=run_id, card_id='CARD_ID').replace('CARD_ID', '')
        ws = _get_wf_store()
        if ws is not None:
            _wf_summary = ws.summary(run_id)
            _wf_states = ws.load(run_id)

        # Workflow filter from query param
        _wf_filter = request.args.get('wf', '')   # '' | 'queue' | 'approved' | 'posted' 

        # --- Recognition summary band
        n_elite = rr.get('n_elite', 0)
        n_strong = rr.get('n_strong', 0)
        n_story = rr.get('n_story', 0)
        n_total = rr.get('n_achievements', 0)
        n_analysed = rr.get('n_swims_analysed', data.get('our_swim_count', 0))
        n_cards = len(cards)

        rec_stats_html = "".join([
            f'<div class="stat"><div class="l" style="color:#F59E0B">Elite</div><div class="v" style="color:#F59E0B">{n_elite}</div></div>',
            f'<div class="stat"><div class="l" style="color:#22D3EE">Strong</div><div class="v" style="color:#22D3EE">{n_strong}</div></div>',
            f'<div class="stat"><div class="l" style="color:#A78BFA">Story</div><div class="v" style="color:#A78BFA">{n_story}</div></div>',
            f'<div class="stat"><div class="l">Total achievements</div><div class="v">{n_total}</div></div>',
            f'<div class="stat"><div class="l">Swims analysed</div><div class="v">{n_analysed}</div></div>',
            f'<div class="stat"><div class="l">Cards</div><div class="v">{n_cards}</div></div>',
        ])

        # --- Meet context card
        mctx = rr.get('meet_context') or {}
        ctx_sources = mctx.get('research_sources') or []
        ctx_sources_html = ""
        if ctx_sources:
            ctx_sources_html = '<ul style="margin-top:6px;">'
            for s in ctx_sources[:5]:
                u = _h(s.get('url',''))
                n = _h(s.get('name', s.get('url','')))
                ctx_sources_html += f'<li><a href="{u}" target="_blank" rel="noopener">{n}</a></li>'
            ctx_sources_html += '</ul>'
        elif not mctx.get('research_available'):
            ctx_sources_html = '<p class="muted" style="font-size:12px">No external sources retrieved for this meet. Context derived from results file only.</p>'

        def ctx_badge(val):
            if val:
                return '<span class="tag good">yes</span>'
            return '<span class="tag">no</span>'

        meet_ctx_html = f"""
<div class="card">
  <h2>Meet context</h2>
  <div class="kv">
    <span class="k">Meet level</span><span><span class="tag info">{_h(mctx.get('meet_level','open'))}</span></span>
    <span class="k">Governing body</span><span>{_h(mctx.get('governing_body') or '—')}</span>
    <span class="k">Has finals</span><span>{ctx_badge(mctx.get('has_finals'))}</span>
    <span class="k">Has age groups</span><span>{ctx_badge(mctx.get('has_age_groups'))}</span>
    <span class="k">Age groups</span><span class="muted">{_h(', '.join(mctx.get('age_groups') or []) or '—')}</span>
    <span class="k">Research</span><span>{'<span class="tag good">available</span>' if mctx.get('research_available') else '<span class="tag warn">unavailable</span>'}</span>
  </div>
  {('<div style="margin-top:10px"><span class="k">Sources</span>' + ctx_sources_html + '</div>') if ctx_sources_html else ''}
</div>"""

        # --- Top achievements panel
        ranked_achs = rr.get('ranked_achievements') or []
        top_achs = ranked_achs[:10]

        def band_cls(band):
            return {
                'elite': 'warn',
                'strong': 'info',
                'story': '',
                'nice': '',
                'not_worthy': 'bad',
            }.get(band, '')

        ach_rows_html = ""
        for ra in top_achs:
            a = ra.get('achievement', {})
            band = ra.get('quality_band', 'nice')
            prio = ra.get('priority', 0.0)
            rank = ra.get('rank', 0)
            conf_label = a.get('confidence_label', 'medium')
            conf_cls = {'high': 'good', 'medium': 'warn', 'low': 'bad'}.get(conf_label, '')
            swimmer = _h(a.get('swimmer_name', ''))
            event = _h(a.get('event', ''))
            headline = _h(a.get('headline', ''))
            atype = _h(_humanise(a.get('type', '')))
            swim_id = _h(a.get('swim_id', ''))
            post_type = _h(ra.get('suggested_post_type', ''))
            prio_bar_pct = int(prio * 100)
            _trace_url = url_for('api_swim_trace', run_id=run_id, swim_id=a.get('swim_id','x'))

            # Evidence list
            ev_html = ""
            for ev in (a.get('evidence') or [])[:3]:
                ev_url = ev.get('source_url') or ''
                ev_src = _h(ev.get('source_name', ''))
                ev_stmt = _h(ev.get('statement', ''))
                if ev_url:
                    ev_html += f'<li><a href="{_h(ev_url)}" target="_blank" rel="noopener">{ev_src}</a>: {ev_stmt}</li>'
                else:
                    ev_html += f'<li><strong>{ev_src}</strong>: {ev_stmt}</li>'

            # Factor list
            factors_html = ""
            for f in (ra.get('factors') or [])[:6]:
                fname = _h(f.get('name',''))
                fval = f.get('value', 0.0)
                freason = _h(f.get('reason',''))
                factors_html += f'<tr><td style="font-size:12px">{fname}</td><td style="font-size:12px">{fval:.3f}</td><td style="font-size:12px;color:var(--ink-muted)">{freason}</td></tr>'

            _why_uuid = str(a.get('swim_id', f'top-{rank}')).replace(':', '_').replace(',', '_').replace('/', '_')
            why_html = _render_why_this_card(ra, card_uuid=f"top-{_why_uuid}", run_id=run_id)
            ach_rows_html += f"""
<div class="ach-row" data-type="{a.get('type','')}" data-conf="{conf_label}" data-swimmer="{a.get('swimmer_name','')}" data-event="{a.get('event','')}" data-band="{band}" data-post="{ra.get('suggested_post_type','')}">
  <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)">
    <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px;padding-top:2px">#{rank}</div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="tag {band_cls(band)}" style="font-size:10px">{band.upper()}</span>
        <span class="tag info" style="font-size:10px">{atype}</span>
        <span class="tag {conf_cls}" style="font-size:10px">conf: {conf_label}</span>
        <span class="tag" style="font-size:10px">{post_type}</span>
        <div style="flex:1;min-width:80px;max-width:160px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:{prio_bar_pct}%;background:var(--accent)"></div>
        </div>
        <span class="muted" style="font-size:11px">{prio:.2f}</span>
      </div>
      <div style="font-size:13px;font-weight:600;margin-bottom:2px">{swimmer} &middot; {event}</div>
      <div style="font-size:13px;color:var(--ink-dim)">{headline}</div>
      {why_html}
      <details style="margin-top:8px">
        <summary style="cursor:pointer;font-size:12px;color:var(--accent);user-select:none">Expand factors &amp; evidence</summary>
        <div style="margin-top:8px;font-size:12px">
          <div style="margin-bottom:6px"><strong>Ranking factors:</strong></div>
          <table style="font-size:12px;margin-bottom:10px"><thead><tr><th>Factor</th><th>Value</th><th>Reason</th></tr></thead><tbody>{factors_html}</tbody></table>
          <div style="margin-bottom:4px"><strong>Evidence:</strong></div>
          <ul style="margin:0;padding-left:18px">{ev_html or '<li class="muted">No evidence items</li>'}</ul>
          <div style="margin-top:8px"><a href="{_trace_url}" target="_blank" rel="noopener" style="font-size:12px">View full trace JSON &rarr;</a></div>
        </div>
      </details>
    </div>
  </div>
</div>"""

        if not ach_rows_html:
            if recognition_error:
                ach_rows_html = f'<div class="empty">Recognition engine error: {_h(recognition_error)}</div>'
            elif not rr:
                ach_rows_html = '<div class="empty">No recognition report available. Re-upload the file to generate achievements.</div>'
            else:
                ach_rows_html = '<div class="empty">No achievements detected.</div>'

        # --- Not generated panel
        swim_traces_raw = rr.get('swim_traces') or []
        no_ach_traces = [t for t in swim_traces_raw if t.get('achievement_count', 0) == 0]
        not_gen_rows = ""
        for t in no_ach_traces[:30]:
            not_gen_rows += (
                f'<tr data-swimmer="{t.get("swimmer_name","")}" data-event="{t.get("event","")}">'  
                f'<td>{_h(t.get("swimmer_name",""))}</td>'
                f'<td>{_h(t.get("event",""))}</td>'
                f'<td style="font-family:monospace">{_h(t.get("time_str",""))}</td>'
                f'<td style="font-size:12px;color:var(--ink-muted)">{_h(t.get("summary",""))}</td>'
                f'</tr>'
            )

        # --- Legacy V4 cards (collapsed)
        tcards = {t["card_id"]: t for t in trust.get("cards", [])}
        v4_rows = []
        for c in cards:
            t = tcards.get(c["card_id"], {})
            conf = t.get("confidence", "medium")
            safe = t.get("safe_to_post", "review")
            badge = {"high": "good", "medium": "warn", "low": "bad"}.get(conf, "")
            safe_badge = {"post": "good", "review": "warn", "hold": "bad"}.get(safe, "")
            sources_str = ", ".join(s.get("name", "") for s in (t.get("sources") or [])[:3])
            v4_rows.append(
                f'<tr><td><span class="tag info">{_h(_humanise(c.get("card_type", "")))}</span><br>'
                f'<strong>{_h((c.get("headline") or "")[:80])}</strong>'
                f'<div class="muted" style="font-size:12px">{_h((c.get("subhead") or "")[:120])}</div></td>'
                f'<td><span class="tag {badge}">{_h(conf)}</span></td>'
                f'<td><span class="tag {safe_badge}">{_h(safe)}</span></td>'
                f'<td><span class="tag">{_h(c.get("bucket", ""))}</span></td>'
                f'<td class="dim" style="font-size:12px">{_h((t.get("reason") or "")[:160])}<br>'
                f'<span class="muted">Sources: {_h(sources_str)}</span></td></tr>'
            )

        captions_html = ""
        for c in cards[:3]:
            cap = c.get("captions") or {}
            captions_html += (
                f'<div style="margin-bottom:12px;padding:12px;background:rgba(255,255,255,0.02);border-radius:10px;border:1px solid var(--border)">'
                f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px">{_h(_humanise(c.get("card_type", "")))}</div>'
                f'<strong style="font-size:13px">{_h(c.get("headline", ""))}</strong>'
                f'<div class="dim" style="margin-top:4px;font-size:12px">{_h(c.get("subhead", ""))}</div>'
                f'<div class="grid-3" style="margin-top:10px;gap:10px">'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Clean</div><div style="font-size:12px">{_h(cap.get("clean") or "—")}</div></div>'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Team</div><div style="font-size:12px">{_h(cap.get("team") or "—")}</div></div>'
                f'<div><div class="muted" style="font-size:10px;text-transform:uppercase;margin-bottom:4px">Hype</div><div style="font-size:12px">{_h(cap.get("hype") or "—")}</div></div>'
                f'</div></div>'
            )

        # Warnings
        warn_html = ""
        if warnings:
            items = []
            for w in warnings[:10]:
                cls = {"info": "info", "warn": "warn", "error": "bad"}.get(w.get("severity"), "")
                items.append(f'<li><span class="tag {cls}">{_h(w.get("severity",""))}</span> '
                             f'<strong>{_h(w.get("code",""))}</strong> &mdash; {_h(w.get("message",""))}</li>')
            warn_html = ('<div class="card"><h2>Parse notes</h2>'
                         '<p class="dim">Anything inferred or ambiguous in the source file is shown here.</p>'
                         f'<ul>{"".join(items)}</ul></div>')

        # --- V6 PB Audit panel
        pb_audit_data = data.get('pb_audit') or {}
        pb_audit_html = ""
        if pb_audit_data:
            _audit_url = url_for('pb_audit_page', run_id=run_id)
            _n_swimmers = pb_audit_data.get('swimmers_total', 0)
            _n_verified = pb_audit_data.get('swimmers_matched_verified', 0)
            _n_needs = pb_audit_data.get('swimmers_needs_verification', 0)
            _n_fetch_fail = pb_audit_data.get('swimmers_fetch_failed', 0)
            _n_decisions = pb_audit_data.get('pb_decisions_count', 0)
            _n_confirmed = pb_audit_data.get('pb_confirmed_count', 0)
            _n_official = pb_audit_data.get('pb_confirmed_official_count', 0)
            _n_matched = pb_audit_data.get('pb_matched_count', 0)
            _n_likely = pb_audit_data.get('pb_likely_count', 0)
            _n_not_pb = pb_audit_data.get('pb_not_pb_count', 0)
            _n_unverified = pb_audit_data.get('pb_unverified_count', 0)
            _n_suppressed = pb_audit_data.get('pb_suppressed_count', 0)
            _fetch_secs = pb_audit_data.get('fetch_total_seconds', 0)
            _cache_hits = pb_audit_data.get('cache_hits', 0)
            _cache_misses = pb_audit_data.get('cache_misses', 0)
            _budget_exceeded = pb_audit_data.get('fetch_budget_exceeded', False)

            # Needs-verification swimmers list
            _needs_verif_html = ""
            _needs_verif_swimmers = [
                sa for sa in (pb_audit_data.get('per_swimmer') or [])
                if (sa.get('identity') or {}).get('method') == 'needs_verification'
            ]
            if _needs_verif_swimmers:
                rows = ""
                for sa in _needs_verif_swimmers[:10]:
                    _sw_key = _h(sa.get('asa_id') or f"name:{sa.get('hy3_name','')}")
                    _hy3 = _h(sa.get('hy3_name', ''))
                    _sr = _h(sa.get('sr_name') or '—')
                    _asa = _h(sa.get('asa_id') or '?')
                    _verify_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=_sw_key)
                    rows += (
                        f'<div style="padding:8px 0;border-bottom:1px solid var(--border)">'
                        f'<a class="btn secondary" style="font-size:11px;padding:4px 8px;margin-right:8px" href="{_verify_url}">Verify</a>'
                        f'<strong>{_hy3}</strong> <span class="muted">(id {_asa})</span>'
                        f'<div class="muted" style="font-size:12px;margin-top:2px">SR returned: "{_sr}" &rarr; canonical mismatch</div>'
                        f'</div>'
                    )
                _needs_verif_html = (
                    f'<div class="divider"></div>'
                    f'<div><strong style="color:#F59E0B">&#x26A0; {_n_needs} swimmer{"s" if _n_needs != 1 else ""} need verification:</strong>'
                    f'{rows}</div>'
                )

            _budget_note = ' <span class="tag warn">budget exceeded</span>' if _budget_exceeded else ''
            pb_audit_html = f"""
<div class="card">
  <h2>PB Audit</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{_n_swimmers}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Verified</div><div class="v" style="color:#22D3EE">{_n_verified}</div></div>
    <div class="stat"><div class="l" style="color:#F59E0B">Needs verification</div><div class="v" style="color:#F59E0B">{_n_needs}</div></div>
    <div class="stat"><div class="l">Fetch failed</div><div class="v">{_n_fetch_fail}</div></div>
    <div class="stat"><div class="l">PB decisions</div><div class="v">{_n_decisions}</div></div>
    <div class="stat"><div class="l" style="color:#4ADE80">Confirmed PBs</div><div class="v" style="color:#4ADE80">{_n_confirmed}</div></div>
    <div class="stat" title="Time + date match SR all-time PB &mdash; strongest possible confirmation"><div class="l" style="color:#22D3EE">Official PBs</div><div class="v" style="color:#22D3EE">{_n_official}</div></div>
    <div class="stat"><div class="l">Likely PBs</div><div class="v">{_n_likely}</div></div>
    <div class="stat"><div class="l">Not PB</div><div class="v">{_n_not_pb}</div></div>
    <div class="stat"><div class="l">Unverified</div><div class="v">{_n_unverified}</div></div>
    <div class="stat"><div class="l">Suppressed</div><div class="v">{_n_suppressed}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{_fetch_secs:.1f}s{_budget_note}</div></div>
    <div class="stat"><div class="l">Cache hits/misses</div><div class="v">{_cache_hits}/{_cache_misses}</div></div>
  </div>
  {_needs_verif_html}
  <div class="divider"></div>
  <a class="btn secondary" href="{_audit_url}">Show all per-swimmer audits &#x25BE;</a>
</div>"""
        elif data.get('pb_fetch_ok') and data.get('pb_fetch_ok') > 0 and not data.get('pb_audit'):
            # Run did some PB fetching but produced no audit
            pb_audit_html = (
                '<div class="card"><p class="muted">'
                'PB fetching used legacy mode. Re-run to see the full audit.'
                '</p></div>'
            )

        # Sources panel
        all_sources = rr.get('all_sources') or []
        sources_rows = ""
        for s in all_sources[:20]:
            u = _h(s.get('url', ''))
            n = _h(s.get('name', s.get('url','')))
            uf = _h(s.get('used_for', ''))
            fa = _h((s.get('fetched_at') or '')[:16])
            sources_rows += f'<tr><td><a href="{u}" target="_blank" rel="noopener">{n}</a></td><td class="muted" style="font-size:12px">{uf}</td><td class="muted" style="font-size:12px">{fa}</td></tr>'

        if not sources_rows:
            sources_rows = '<tr><td colspan="3" class="muted">No external sources used (research unavailable or not yet run).</td></tr>'

        # Build filter dropdowns from unique values
        swimmers_set = sorted(set(ra.get('achievement',{}).get('swimmer_name','') for ra in ranked_achs if ra.get('achievement')))
        events_set = sorted(set(ra.get('achievement',{}).get('event','') for ra in ranked_achs if ra.get('achievement')))
        types_set = sorted(set(ra.get('achievement',{}).get('type','') for ra in ranked_achs if ra.get('achievement')))
        bands_set = ['elite','strong','story','nice','not_worthy']
        post_types_set = sorted(set(ra.get('suggested_post_type','') for ra in ranked_achs))

        def opts(items, label):
            o = f'<option value="">All {label}</option>'
            for item in items:
                o += f'<option value="{_h(item)}">{_h(item)}</option>'
            return o

        # --- V7: build workflow summary card and status pill helpers
        _wf_api_base_js = json.dumps(_wf_api_base)
        _wf_n_queue = _wf_summary.get("queue", 0)
        _wf_n_approved = _wf_summary.get("approved", 0)
        _wf_n_rejected = _wf_summary.get("rejected", 0)
        _wf_n_posted = _wf_summary.get("posted", 0)
        _wf_n_edited = _wf_summary.get("edited", 0)
        _wf_n_total = _wf_summary.get("total", 0)

        # Only show workflow card if there's any state or any achievements
        if _wf_summary or ranked_achs:
            _wf_filter_opts = ""
            _review_base = url_for("review", run_id=run_id)
            for _wf_opt in [("", "All"), ("queue", "Queue"), ("approved", "Approved"), ("posted", "Posted"), ("rejected", "Rejected")]:
                _wf_sel = "selected" if _wf_filter == _wf_opt[0] else ""
                _wf_opt_url = _review_base + (f"?wf={_wf_opt[0]}" if _wf_opt[0] else "")
                _wf_filter_opts += f'<option value="{_wf_opt_url}" {_wf_sel}>{_wf_opt[1]}</option>'
            # --- Turn-Into content pack card (top of content pack section) ---
            _ti_prior_html = ""
            if _ti_packs:
                rows = []
                for p in _ti_packs[:5]:
                    _pid = p.get("pack_id", "")
                    _gen = p.get("generated_at", "")
                    _n = p.get("n_artefacts", 0)
                    _skipped = p.get("n_skipped", 0)
                    try:
                        _view = url_for("turn_into_pack_view", run_id=run_id, pack_id=_pid)
                    except Exception:
                        _view = "#"
                    rows.append(
                        f'<li style="font-size:12px;margin-bottom:4px">'
                        f'<a href="{_view}">{_h(_gen)}</a> '
                        f'<span class="muted">&mdash; {_n} artefacts'
                        + (f", {_skipped} skipped" if _skipped else "")
                        + '</span></li>'
                    )
                _ti_prior_html = (
                    '<div style="margin-top:14px">'
                    '<div class="muted" style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">'
                    'Previously generated packs</div>'
                    f'<ul style="margin:0;padding-left:20px">{"".join(rows)}</ul>'
                    '</div>'
                )

            turn_into_card = f"""
<div class="card" id="turn-into-card" style="border-left:3px solid var(--accent)">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <div style="flex:1;min-width:240px">
      <h2 style="margin-bottom:6px">Content pack</h2>
      <p class="dim" style="margin:0;font-size:13px;max-width:540px">
        Turn this meet into a full pack of 7 derivative artefacts &mdash;
        recap, swimmer spotlights, X / LinkedIn thread, parent newsletter,
        sponsor thank-you, coach quote, and next-meet preview.
      </p>
    </div>
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <button id="ti-btn" class="btn" onclick="turnMeetIntoPack()" style="background:linear-gradient(135deg,#8B5CF6,#22D3EE);color:#fff;border:none">
        &#x2726; Turn meet into content pack
      </button>
      <a class="btn secondary" href="{_pack_url}" style="align-self:flex-end">View workflow pack &rarr;</a>
    </div>
  </div>
  <div id="ti-status" style="margin-top:10px;font-size:12px;color:var(--ink-muted);display:none"></div>
  {_ti_prior_html}
</div>
<script>
function turnMeetIntoPack() {{
  var btn = document.getElementById('ti-btn');
  var status = document.getElementById('ti-status');
  var origText = btn.textContent;
  var secs = 0;
  btn.disabled = true;
  btn.textContent = 'Generating…';
  status.style.display = '';
  status.textContent = 'Building artefacts — starting…';
  var ticker = setInterval(function() {{
    secs++;
    status.textContent = 'Building artefacts with live AI — ' + secs + 's elapsed…';
  }}, 1000);
  function _fail(msg) {{
    clearInterval(ticker);
    status.textContent = 'Failed: ' + msg;
    btn.disabled = false;
    btn.textContent = origText;
  }}
  function _poll(statusUrl) {{
    fetch(statusUrl).then(function(r) {{ return r.json(); }}).then(function(j) {{
      if (j.status === 'running') {{
        setTimeout(function() {{ _poll(statusUrl); }}, 2000);
      }} else if (j.status === 'done' && j.pack_url) {{
        clearInterval(ticker);
        status.textContent = 'Done — opening pack…';
        window.location.href = j.pack_url;
      }} else {{
        _fail(j.error || 'unknown error');
      }}
    }}).catch(function() {{ _fail('poll failed'); }});
  }}
  fetch({json.dumps(_turn_into_api)}, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ async: true }}),
  }}).then(function(r) {{ return r.json(); }})
    .then(function(j) {{
      if (j && j.status_url) {{
        setTimeout(function() {{ _poll(j.status_url); }}, 2000);
      }} else if (j && j.pack_url) {{
        clearInterval(ticker);
        status.textContent = 'Done — opening pack…';
        window.location.href = j.pack_url;
      }} else {{
        _fail(j && j.message ? j.message : 'unknown error');
      }}
    }})
    .catch(function() {{
      _fail('Network error. Please retry.');
    }});
}}
</script>"""

            workflow_summary_card = turn_into_card + f"""
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <div>
      <h2 style="margin-bottom:10px">Workflow</h2>
      <div class="stat-block">
        <div class="stat"><div class="l">Queue</div><div class="v">{_wf_n_queue or len(ranked_achs)}</div></div>
        <div class="stat"><div class="l" style="color:#22C55E">Approved</div><div class="v" style="color:#22C55E">{_wf_n_approved}</div></div>
        <div class="stat"><div class="l" style="color:#F43F5E">Rejected</div><div class="v" style="color:#F43F5E">{_wf_n_rejected}</div></div>
        <div class="stat"><div class="l" style="color:#22D3EE">Posted</div><div class="v" style="color:#22D3EE">{_wf_n_posted}</div></div>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
      <a class="btn" href="{_pack_url}" style="align-self:flex-end">View content pack &rarr;</a>
    </div>
  </div>
  <div style="margin-top:14px;display:flex;align-items:center;gap:10px">
    <span class="muted" style="font-size:12px">Filter:</span>
    <select style="width:auto;font-size:13px;padding:6px 10px" onchange="location.href=this.value">
      {_wf_filter_opts}
    </select>
  </div>
</div>"""
        else:
            workflow_summary_card = ""

        # --- V7: add status pills to achievement rows
        # Rebuild ach_rows_html with workflow status pills
        ach_rows_html_wf = ""
        for ra in ranked_achs:
            a = ra.get("achievement", {})
            band = ra.get("quality_band", "nice")
            prio = ra.get("priority", 0.0)
            rank = ra.get("rank", 0)
            conf_label = a.get("confidence_label", "medium")
            conf_cls = {"high": "good", "medium": "warn", "low": "bad"}.get(conf_label, "")
            swimmer = _h(a.get("swimmer_name", ""))
            event = _h(a.get("event", ""))
            headline = _h(a.get("headline", ""))
            atype = _h(_humanise(a.get("type", "")))
            post_type = _h(ra.get("suggested_post_type", ""))
            prio_bar_pct = int(prio * 100)
            _trace_url = url_for("api_swim_trace", run_id=run_id, swim_id=a.get("swim_id","x"))

            # V7: workflow state for this card
            card_id_raw = a.get("swim_id", "")
            card_id_safe = _h(card_id_raw)
            wf_state = _wf_states.get(card_id_raw)
            wf_status = wf_state.status.value if wf_state else "queue"

            # Skip if filtered
            if _wf_filter and wf_status != _wf_filter:
                continue

            band_cls = {"elite": "warn", "strong": "info", "story": "", "nice": "", "not_worthy": "bad"}.get(band, "")

            status_colours = {
                "queue": ("rgba(255,255,255,0.06)", "var(--ink-muted)"),
                "approved": ("rgba(34,197,94,0.15)", "#22C55E"),
                "rejected": ("rgba(244,63,94,0.15)", "#F43F5E"),
                "posted": ("rgba(34,211,238,0.15)", "var(--accent)"),
                "edited": ("rgba(245,158,11,0.15)", "var(--warn)"),
            }
            s_bg, s_fg = status_colours.get(wf_status, status_colours["queue"])

            # Evidence list
            ev_html = ""
            for ev in (a.get("evidence") or [])[:3]:
                ev_url = ev.get("source_url") or ""
                ev_src = _h(ev.get("source_name", ""))
                ev_stmt = _h(ev.get("statement", ""))
                if ev_url:
                    ev_html += f'<li><a href="{_h(ev_url)}" target="_blank" rel="noopener">{ev_src}</a>: {ev_stmt}</li>'
                else:
                    ev_html += f'<li><strong>{ev_src}</strong>: {ev_stmt}</li>'

            # Factor list
            factors_html = ""
            for f in (ra.get("factors") or [])[:7]:
                fname = _h(f.get("name",""))
                fval = f.get("value", 0.0)
                freason = _h(f.get("reason",""))
                factors_html += f'<tr><td style="font-size:12px">{fname}</td><td style="font-size:12px">{fval:.3f}</td><td style="font-size:12px;color:var(--ink-muted)">{freason}</td></tr>'

            # V8: Live caption tone toggle.
            # All tabs (AI, Warm, Hype, Precise) generate captions live via the
            # LLM. No pre-filled template text &mdash; clicking a tone tab always
            # triggers a fresh, unique generation. Results are cached per session
            # client-side; "&#x21BA; Regenerate" forces a new fetch.
            tone_tabs_html = ""

            card_uuid = card_id_raw.replace(":", "_").replace(",", "_")
            swim_id_safe = _h(card_id_raw)
            _caption_url = url_for("api_live_caption", run_id=run_id, swim_id=card_id_raw)

            tabs_html = ""
            panels_html = ""

            # Standard tones &mdash; always shown, always AI-generated on demand.
            # Order: AI (first, active) &rarr; Warm &rarr; Hype &rarr; Precise
            _STD_TONES = [
                ("ai",        "✦ AI", True,  "tone-tab-ai",
                 "rgba(139,92,246,0.15)", "#A78BFA",
                 "Live AI caption. Generates fresh each time."),
                ("warm-club", "Warm",    False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Warm & community — friendly, first-name, inclusive."),
                ("hype",      "Hype",    False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Energetic & hype — race-day language, high energy."),
                ("data-led",  "Precise", False, "",
                 "rgba(34,211,238,0.15)", "var(--accent)",
                 "Data-led — numbers first, sponsor-friendly, no fluff."),
            ]

            for t_key, t_label, is_active, extra_cls, active_bg, active_fg, title in _STD_TONES:
                init_bg = active_bg if is_active else "transparent"
                init_fg = active_fg if is_active else "var(--ink-dim)"
                active_attr = "active" if is_active else ""
                display = "" if is_active else "display:none"
                status_dot = (
                    '<span class="ai-status-dot" style="display:inline-block;width:7px;height:7px;'
                    'border-radius:50%;background:#ffae3b" aria-hidden="true"></span>'
                    if t_key == "ai" else ""
                )
                tabs_html += (
                    f'<button class="tone-tab {extra_cls} {active_attr}" '
                    f'data-card="{card_uuid}" data-tone="{t_key}" '
                    f'onclick="switchToneLive(this, {repr(_caption_url)}, {repr(card_uuid)})" '
                    f'title="{_h(title)}" '
                    f'style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);'
                    f'cursor:pointer;background:{init_bg};color:{init_fg};'
                    f'font-family:inherit;margin-right:4px;font-weight:{"600" if is_active else "400"};'
                    f'display:inline-flex;align-items:center;gap:5px">'
                    f'{status_dot}{_h(t_label)}</button>'
                )
                panels_html += (
                    f'<div class="tone-panel" data-tone="{t_key}" data-card="{card_uuid}" style="{display}">'
                    f'<div class="caption-text" style="font-size:12px;color:var(--ink);white-space:pre-wrap">'
                    f'<span class="caption-placeholder" style="color:var(--ink-muted);font-style:italic">'
                    f'Click to generate&hellip;</span></div>'
                    f'<textarea class="caption-textarea" style="display:none"></textarea>'
                    f'</div>'
                )

            # V8: Create-graphic API URL (lazy visual generation)
            _create_graphic_url = url_for("api_create_graphic", run_id=run_id, card_id=card_id_raw)
            _motion_url = url_for("api_card_motion", run_id=run_id, card_id=card_id_raw)
            tone_tabs_html = (
                f'<div class="tone-picker" data-caption-url="{_h(_caption_url)}" data-card="{card_uuid}" style="margin-top:10px;padding:12px;background:rgba(34,211,238,0.04);border:1px solid var(--border);border-radius:8px">'
                f'<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px;letter-spacing:0.5px">Caption tone</div>'
                f'<div style="margin-bottom:8px">{tabs_html}</div>'
                f'<div class="tone-panels" data-card="{card_uuid}">{panels_html}</div>'
                f'<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
                f'<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="copyActiveTone(this, \'{card_uuid}\')">Copy caption</button>'
                f'<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="regenerateCaption(this, {repr(_caption_url)}, \'{card_uuid}\')">&#x21BA; Regenerate caption</button>'
                f'<button class="btn" style="font-size:11px;padding:4px 10px;background:linear-gradient(135deg,#8B5CF6,#22D3EE);color:#fff;border:none" onclick="createGraphic(this, {repr(_create_graphic_url)}, \'{card_uuid}\')">&#x2726; Create graphic</button>'
                f'<button class="btn" style="font-size:11px;padding:4px 10px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none" onclick="generateMotion(this, {repr(_motion_url)}, \'{card_uuid}\')">&#x25B6; Generate motion</button>'
                f'<span class="caption-timestamp" style="font-size:10px;color:var(--ink-muted)"></span>'
                f'</div>'
                f'<div class="visual-panel" data-card="{card_uuid}" data-create-url="{_h(_create_graphic_url)}" style="display:none;margin-top:10px;padding:12px;background:rgba(139,92,246,0.04);border:1px solid var(--border);border-radius:8px"></div>'
                f'<div class="motion-panel" data-card="{card_uuid}" data-motion-url="{_h(_motion_url)}" style="display:none;margin-top:10px;padding:12px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>'
                f'</div>'
            )
            brand_cap_html = tone_tabs_html

            _wf_api_url = url_for("api_workflow_set", run_id=run_id, card_id=card_id_raw)

            # V9: "Why this card?" &mdash; plain-English, source-grounded reasoning.
            why_html = _render_why_this_card(ra, card_uuid=f"wf-{card_uuid}", run_id=run_id)

            ach_rows_html_wf += f"""
<div class="ach-row" data-type="{a.get("type","")}" data-conf="{conf_label}" data-swimmer="{a.get("swimmer_name","")}" data-event="{a.get("event","")}" data-band="{band}" data-post="{ra.get("suggested_post_type","")}" data-status="{wf_status}">
  <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 0;border-bottom:1px solid var(--border)">
    <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px;padding-top:2px">#{rank}</div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <span class="tag {band_cls}" style="font-size:10px">{band.upper()}</span>
        <span class="tag info" style="font-size:10px">{atype}</span>
        <span class="tag {conf_cls}" style="font-size:10px">conf: {conf_label}</span>
        <span class="tag" style="font-size:10px">{post_type}</span>
        <div style="flex:1;min-width:80px;max-width:160px;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:{prio_bar_pct}%;background:var(--accent)"></div>
        </div>
        <span class="muted" style="font-size:11px">{prio:.2f}</span>
        <!-- V7: Status pill -->
        <button class="wf-pill" data-run="{_h(run_id)}" data-card="{card_id_safe}" data-status="{wf_status}"
          style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:{s_bg};color:{s_fg};font-family:inherit;transition:opacity 150ms"
          title="Click: queue &rarr; approved &rarr; posted. Right-click for more options.">{wf_status}</button>
      </div>
      <div style="font-size:13px;font-weight:600;margin-bottom:2px">{swimmer} &middot; {event}</div>
      <div style="font-size:13px;color:var(--ink-dim)">{headline}</div>
      {why_html}
      {brand_cap_html}
      <details style="margin-top:8px">
        <summary style="cursor:pointer;font-size:12px;color:var(--accent);user-select:none">Edit caption &middot; view factors &amp; evidence</summary>
        <div style="margin-top:8px;font-size:12px">
          <div style="padding:12px;background:rgba(34,211,238,0.04);border:1px solid var(--border);border-radius:8px;margin-bottom:14px">
            <strong style="font-size:13px">Caption editor</strong>
            <span class="muted" style="font-size:11px;margin-left:6px">(warm-club tone &mdash; leave blank to use the default)</span>
            <div style="margin-top:10px">
              <label style="font-size:11px;margin-bottom:4px;display:block">Headline</label>
              <textarea class="cap-edit" data-key="warm-club_headline" style="min-height:48px;font-size:12px" placeholder="Override the headline&hellip;"></textarea>
              <label style="font-size:11px;margin-bottom:4px;display:block;margin-top:8px">Body</label>
              <textarea class="cap-edit" data-key="warm-club_body" style="min-height:64px;font-size:12px" placeholder="Override the body text&hellip;"></textarea>
            </div>
            <button class="btn" style="font-size:12px;padding:6px 14px;margin-top:10px"
              onclick="saveCaption(this, '{_h(run_id)}', '{card_id_safe}')">Save caption edits</button>
          </div>
          <details style="margin-top:6px">
            <summary style="cursor:pointer;font-size:12px;color:var(--ink-dim);user-select:none">Show ranking factors &amp; evidence</summary>
            <div style="margin-top:8px">
              <div style="margin-bottom:6px"><strong>Ranking factors:</strong></div>
              <table style="font-size:12px;margin-bottom:10px"><thead><tr><th>Factor</th><th>Value</th><th>Reason</th></tr></thead><tbody>{factors_html}</tbody></table>
              <div style="margin-bottom:4px"><strong>Evidence:</strong></div>
              <ul style="margin:0;padding-left:18px">{ev_html or '<li class="muted">No evidence items</li>'}</ul>
              <div style="margin-top:8px"><a href="{_trace_url}" target="_blank" rel="noopener" style="font-size:12px">View full trace JSON &rarr;</a></div>
            </div>
          </details>
        </div>
      </details>
    </div>
  </div>
</div>"""

        if not ach_rows_html_wf:
            if _wf_filter:
                ach_rows_html_wf = f'<div class="empty">No cards with status "{_h(_wf_filter)}".</div>'
            elif recognition_error:
                ach_rows_html_wf = f'<div class="empty">Recognition engine error: {_h(recognition_error)}</div>'
            elif not rr:
                ach_rows_html_wf = '<div class="empty">No recognition report available. Re-upload the file to generate achievements.</div>'
            else:
                ach_rows_html_wf = '<div class="empty">No achievements detected.</div>'

        body = f"""
<style>
.ach-row {{ transition: background 100ms; }}
.ach-row:hover {{ background: rgba(255,255,255,0.015); }}
.filters-bar {{ display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;padding:14px 16px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);position:sticky;top:56px;z-index:50; }}
.filters-bar select {{ width:auto;min-width:120px;font-size:13px;padding:6px 10px; }}
.ach-row.hidden {{ display:none; }}
@keyframes spin {{ from {{ transform:rotate(0deg) }} to {{ transform:rotate(360deg) }} }}
</style>

<h1>{_h(meet.get('name', '(unknown meet)'))}</h1>
<p class="dim">
  {_h(data.get('profile_display',''))} &middot;
  {_h(meet.get('start_date','?'))} &ndash; {_h(meet.get('end_date','?'))} &middot;
  {_h(meet.get('course',''))} &middot;
  {_h(meet.get('venue') or 'venue unknown')} &middot;
  source: {_h(dispatch_log.get('chosen_filename') or data.get('file_name',''))}
  ({_h(dispatch_log.get('chosen_adapter','?'))})
</p>

<div class="card">
  <h2>Recognition summary</h2>
  <div class="stat-block">{rec_stats_html}</div>
  <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
    <a class="btn secondary" href="{_export_url}">Download export</a>
    <form method="post" action="{_delete_url}" style="display:inline" onsubmit="return confirm('Delete this run permanently?')">
      <button class="btn danger" type="submit">Delete run</button>
    </form>
  </div>
  <details style="margin-top:12px">
    <summary style="font-size:12px;color:var(--ink-muted);cursor:pointer">Developer tools</summary>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
      <a class="btn secondary" href="{_rec_json_url}" target="_blank" rel="noopener" style="font-size:12px">Download recognition JSON</a>
      <a class="btn secondary" href="{_gt_url}" style="font-size:12px">Run ground-truth check</a>
    </div>
  </details>
</div>

{workflow_summary_card}

{meet_ctx_html}

{pb_audit_html}

{warn_html}

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:8px">
    <h2 style="margin:0">Top achievements</h2>
    <button class="btn" style="font-size:12px;padding:6px 14px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none"
            onclick="generateReel(this, {repr(_reel_url)})">&#x25B6; Generate reel from this meet</button>
  </div>
  <div id="reel-panel" style="display:none;margin-bottom:14px;padding:14px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>
  <div class="filters-bar">
    <select id="f-type" onchange="applyFilters()">{opts(types_set, 'types')}</select>
    <select id="f-conf" onchange="applyFilters()"><option value="">All confidence</option><option>high</option><option>medium</option><option>low</option></select>
    <select id="f-swimmer" onchange="applyFilters()">{opts(swimmers_set, 'swimmers')}</select>
    <select id="f-event" onchange="applyFilters()">{opts(events_set, 'events')}</select>
    <select id="f-band" onchange="applyFilters()">{opts(bands_set, 'bands')}</select>
    <select id="f-post" onchange="applyFilters()">{opts(post_types_set, 'post types')}</select>
    <button class="btn secondary" style="font-size:13px;padding:6px 12px" onclick="clearFilters()">Clear</button>
    <span id="f-count" class="muted" style="font-size:12px;align-self:center"></span>
  </div>
  <div id="ach-list">{ach_rows_html_wf}</div>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Legacy content cards <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(cards)} cards</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Card</th><th>Confidence</th><th>Safe to post</th><th>Bucket</th><th>Why</th></tr></thead>
        <tbody>{"".join(v4_rows) or '<tr><td colspan="5" class="muted">No cards generated.</td></tr>'}</tbody>
      </table>
      <div style="margin-top:14px">{captions_html or '<p class="muted">No captions.</p>'}</div>
    </div>
  </details>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Not generated <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(no_ach_traces)} swims with no achievements</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Swimmer</th><th>Event</th><th>Time</th><th>Why not generated</th></tr></thead>
        <tbody>{not_gen_rows or '<tr><td colspan="4" class="muted">All swims produced achievements, or no trace data available.</td></tr>'}</tbody>
      </table>
    </div>
  </details>
</div>

<div class="card">
  <details>
    <summary style="cursor:pointer;font-size:15px;font-weight:700;color:var(--ink)">Sources used <span class="muted" style="font-weight:400;font-size:13px">&mdash; {len(all_sources)} source(s)</span></summary>
    <div style="margin-top:14px">
      <table>
        <thead><tr><th>Source</th><th>Used for</th><th>Fetched</th></tr></thead>
        <tbody>{sources_rows}</tbody>
      </table>
    </div>
  </details>
</div>

<script>
function applyFilters() {{
  var fType = document.getElementById('f-type').value;
  var fConf = document.getElementById('f-conf').value;
  var fSwimmer = document.getElementById('f-swimmer').value;
  var fEvent = document.getElementById('f-event').value;
  var fBand = document.getElementById('f-band').value;
  var fPost = document.getElementById('f-post').value;
  var rows = document.querySelectorAll('#ach-list .ach-row');
  var shown = 0;
  rows.forEach(function(row) {{
    var match = true;
    if (fType && row.dataset.type !== fType) match = false;
    if (fConf && row.dataset.conf !== fConf) match = false;
    if (fSwimmer && row.dataset.swimmer !== fSwimmer) match = false;
    if (fEvent && row.dataset.event !== fEvent) match = false;
    if (fBand && row.dataset.band !== fBand) match = false;
    if (fPost && row.dataset.post !== fPost) match = false;
    row.classList.toggle('hidden', !match);
    if (match) shown++;
  }});
  var countEl = document.getElementById('f-count');
  if (countEl) countEl.textContent = shown + ' of ' + rows.length + ' shown';
}}
function clearFilters() {{
  ['f-type','f-conf','f-swimmer','f-event','f-band','f-post'].forEach(function(id) {{
    var el = document.getElementById(id);
    if (el) el.value = '';
  }});
  applyFilters();
}}
applyFilters();

// V7: Workflow pill cycling
// Click-cycle skips rejected/edited (uncommon paths). Right-click cycles back.
const WF_CYCLE = ['queue','approved','posted'];
const WF_COLOURS = {{
  queue:    ['rgba(255,255,255,0.06)','var(--ink-muted)'],
  approved: ['rgba(34,197,94,0.15)','#22C55E'],
  rejected: ['rgba(244,63,94,0.15)','#F43F5E'],
  posted:   ['rgba(34,211,238,0.15)','var(--accent)'],
  edited:   ['rgba(245,158,11,0.15)','var(--warn)'],
}};
const WF_API_BASE = {_wf_api_base_js};
function _wfApply(btn, next) {{
  var cur = btn.dataset.status || 'queue';
  var cardId = btn.dataset.card;
  btn.textContent = next;
  btn.dataset.status = next;
  var cols = WF_COLOURS[next] || WF_COLOURS.queue;
  btn.style.background = cols[0];
  btn.style.color = cols[1];
  var row = btn.closest('.ach-row');
  if (row) row.dataset.status = next;
  var url = WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_status',status:next}})}})
    .then(r=>r.json())
    .then(j=>{{ if(!j.ok){{btn.textContent=cur;btn.dataset.status=cur;}} }})
    .catch(()=>{{btn.textContent=cur;btn.dataset.status=cur;}});
}}

document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.wf-pill');
  if (!btn) return;
  var cur = btn.dataset.status || 'queue';
  // If currently rejected/edited (not in cycle), restart at approved
  var idx = WF_CYCLE.indexOf(cur);
  var next = idx === -1 ? 'approved' : WF_CYCLE[(idx + 1) % WF_CYCLE.length];
  _wfApply(btn, next);
}});

// Right-click cycles: queue &rarr; rejected (rare path)
document.addEventListener('contextmenu', function(e) {{
  var btn = e.target.closest('.wf-pill');
  if (!btn) return;
  e.preventDefault();
  var cur = btn.dataset.status || 'queue';
  var next = cur === 'rejected' ? 'queue' : 'rejected';
  _wfApply(btn, next);
}});


// V8: Live caption tone toggle + regenerate
// switchTone() kept for backwards compat (content pack, other pages).
function switchTone(btn) {{
  var cardId = btn.dataset.card;
  var newTone = btn.dataset.tone;
  document.querySelectorAll('.tone-tab[data-card="' + cardId + '"]').forEach(function(tab) {{
    var isActive = tab.dataset.tone === newTone;
    tab.classList.toggle('active', isActive);
    if (isActive) {{
      tab.style.background = tab.classList.contains('tone-tab-ai') ? 'rgba(139,92,246,0.15)' : 'rgba(34,211,238,0.15)';
      tab.style.color = tab.classList.contains('tone-tab-ai') ? '#A78BFA' : 'var(--accent)';
    }} else {{
      tab.style.background = 'transparent';
      tab.style.color = 'var(--ink-dim)';
    }}
  }});
  document.querySelectorAll('.tone-panel[data-card="' + cardId + '"]').forEach(function(panel) {{
    panel.style.display = panel.dataset.tone === newTone ? '' : 'none';
  }});
}}

// V8: switchToneLive &mdash; fetches caption from API on click.
// AI tab: always fetches fresh. Warm/Hype/Precise tabs: cached for the session.
// "&#x21BA; Regenerate" always forces a fresh fetch via regenerateCaption().
var _captionCache = {{}};
var _AI_TONE_KEYS = {{'ai': true}};  // other tones are cached after first gen

function switchToneLive(btn, captionUrl, cardId) {{
  var newTone = btn.dataset.tone;
  var isAiTone = !!_AI_TONE_KEYS[newTone];

  // Update tab styles
  document.querySelectorAll('.tone-tab[data-card="' + cardId + '"]').forEach(function(tab) {{
    var isActive = tab.dataset.tone === newTone;
    tab.classList.toggle('active', isActive);
    if (isActive) {{
      tab.style.background = tab.classList.contains('tone-tab-ai') ? 'rgba(139,92,246,0.15)' : 'rgba(34,211,238,0.15)';
      tab.style.color = tab.classList.contains('tone-tab-ai') ? '#A78BFA' : 'var(--accent)';
      tab.style.fontWeight = '600';
    }} else {{
      tab.style.background = 'transparent';
      tab.style.color = 'var(--ink-dim)';
      tab.style.fontWeight = '400';
    }}
  }});

  // Show active panel, hide others
  document.querySelectorAll('.tone-panel[data-card="' + cardId + '"]').forEach(function(panel) {{
    panel.style.display = panel.dataset.tone === newTone ? '' : 'none';
  }});

  var panel = document.querySelector('.tone-panel[data-tone="' + newTone + '"][data-card="' + cardId + '"]');
  if (!panel) {{ return; }}

  var cacheKey = cardId + '|' + newTone;

  // AI tab: always fetch fresh &mdash; never use cache.
  // Named tones (warm/hype/precise): use session cache after first generation.
  if (!isAiTone && _captionCache[cacheKey]) {{
    _renderCaption(panel, _captionCache[cacheKey]);
    return;
  }}

  // All panels start with a placeholder &mdash; fetch if placeholder still present
  // (or if AI tone, always fetch).
  var placeholder = panel.querySelector('.caption-placeholder');
  if (!isAiTone && !placeholder) {{
    return;  // already generated; cache hit handled above
  }}

  _fetchCaption(captionUrl, newTone, panel, cacheKey, isAiTone, cardId);
}}

function _fetchCaption(captionUrl, tone, panel, cacheKey, isAi, cardId) {{
  var captionDiv = panel.querySelector('.caption-text');
  var textarea = panel.querySelector('.caption-textarea');
  if (captionDiv) {{
    captionDiv.innerHTML = '<span style="color:var(--ink-muted);font-style:italic">Generating&hellip;<span class="spin" style="display:inline-block;margin-left:6px;animation:spin 0.8s linear infinite">&#x27F3;</span></span>';
  }}
  fetch(captionUrl + '?tone=' + encodeURIComponent(tone), {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(j) {{
      var text = j.caption || '';
      var ts = j.generated_at ? new Date(j.generated_at).toLocaleTimeString() : '';
      var fallbackNote = '';
      // Distinguish transient (rate-limit / network blip) from terminal
      // (no key configured). Transient errors must NOT flip the dot red
      // permanently — the AI itself is still set up correctly, the
      // request just needs a retry.
      var isTransient = (j.error === 'transient' || (j.live === true && !text));
      var isTerminal = (j.live === false && j.error !== 'transient');
      if (isTerminal) {{
        if (captionDiv) {{
          captionDiv.innerHTML = '<div style="padding:10px;border:1px dashed var(--border);border-radius:6px;background:rgba(255,174,59,0.06);color:var(--ink-muted)">'
            + '<div style="font-weight:600;color:var(--ink);margin-bottom:4px">&#x2726; AI captions are unavailable</div>'
            + '<div style="font-size:11px;line-height:1.5">' + (j.message || 'Contact your administrator to enable AI.') + '</div>'
            + '</div>';
        }}
        document.querySelectorAll('.ai-status-dot').forEach(function(d){{ d.style.background='#ff5d6c'; }});
        return;
      }}
      if (isTransient) {{
        if (captionDiv) {{
          captionDiv.innerHTML = '<div style="padding:10px;border:1px solid rgba(34,211,238,0.20);border-radius:6px;background:rgba(34,211,238,0.04)">'
            + '<div style="font-weight:600;color:var(--accent);margin-bottom:4px">&#x21BB; Briefly busy &mdash; try again</div>'
            + '<div style="font-size:11px;line-height:1.5;color:var(--ink-dim)">' + (j.message || 'Wait a few seconds and click regenerate again.') + '</div>'
            + '</div>';
        }}
        // Keep the dot green — provider is reachable, just throttled.
        return;
      }}
      if (j.fallback && j.fallback_voice) {{
        fallbackNote = '<div style="margin-top:4px;font-size:10px;color:var(--warn);padding:4px 8px;background:rgba(245,158,11,0.08);border-radius:4px">&#x26A0; AI generation unavailable, using ' + j.fallback_voice + '</div>';
      }}
      // Render the caption + a variant picker if we got multiple back.
      var variants = (j.variants && j.variants.length) ? j.variants : [text];
      var safeText = function(t){{ return (t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }};
      function _renderActive(idx) {{
        var active = variants[idx] || text;
        if (captionDiv) {{
          var pickerHtml = '';
          if (variants.length > 1) {{
            var pills = variants.map(function(_, i) {{
              var sel = (i === idx);
              return '<button type="button" class="cap-var-pill" data-idx="' + i + '" style="font-size:10px;padding:3px 9px;border-radius:999px;border:1px solid ' + (sel ? 'var(--accent)' : 'var(--border)') + ';background:' + (sel ? 'rgba(34,211,238,0.14)' : 'transparent') + ';color:' + (sel ? 'var(--accent)' : 'var(--ink-dim)') + ';cursor:pointer;font-family:inherit;margin-right:4px">v' + (i+1) + '</button>';
            }}).join('');
            pickerHtml = '<div style="display:flex;gap:4px;align-items:center;margin-bottom:6px"><span style="font-size:10px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:0.5px;margin-right:4px">Variants</span>' + pills + '</div>';
          }}
          captionDiv.innerHTML = pickerHtml + '<span style="white-space:pre-wrap">' + safeText(active) + '</span>' + fallbackNote;
          captionDiv.querySelectorAll('.cap-var-pill').forEach(function(btn) {{
            btn.addEventListener('click', function() {{ _renderActive(parseInt(btn.dataset.idx, 10) || 0); }});
          }});
        }}
        if (textarea) {{ textarea.value = active; }}
      }}
      _renderActive(0);
      // Update timestamp
      var picker = panel.closest('.tone-picker');
      if (picker) {{
        var tsEl = picker.querySelector('.caption-timestamp');
        if (tsEl && ts) tsEl.textContent = 'regenerated just now &middot; ' + ts;
      }}
      // Cache named-tone results for this session (not the AI tab &mdash; always fresh)
      if (!isAi) {{ _captionCache[cacheKey] = {{text: text, variants: variants}}; }}
    }})
    .catch(function(err) {{
      if (captionDiv) {{
        captionDiv.innerHTML = '<span style="color:var(--ink-muted);font-style:italic">Error generating caption. Please try again.</span>';
      }}
    }});
}}

function _renderCaption(panel, cached) {{
  var captionDiv = panel.querySelector('.caption-text');
  var textarea = panel.querySelector('.caption-textarea');
  if (captionDiv && cached.text) {{
    captionDiv.innerHTML = '<span style="white-space:pre-wrap">' + cached.text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</span>';
  }}
  if (textarea && cached.text) {{
    textarea.value = cached.text;
  }}
}}

function regenerateCaption(btn, captionUrl, cardId) {{
  // Find the active panel and force a fresh re-fetch (clears session cache).
  var activeToneTab = document.querySelector('.tone-tab.active[data-card="' + cardId + '"]');
  if (!activeToneTab) {{ return; }}
  var tone = activeToneTab.dataset.tone;
  var cacheKey = cardId + '|' + tone;
  delete _captionCache[cacheKey];  // force fresh generation
  var panel = document.querySelector('.tone-panel[data-tone="' + tone + '"][data-card="' + cardId + '"]');
  if (!panel) {{ return; }}
  var isAiTone = !!_AI_TONE_KEYS[tone];
  _fetchCaption(captionUrl, tone, panel, cacheKey, isAiTone, cardId);
}}

// V9: Copy "Why this card?" reasoning to clipboard (for sponsor reports etc.)
function copyWhyCard(btn, taId) {{
  var ta = document.getElementById(taId);
  if (!ta) {{ return; }}
  var text = ta.value || '';
  var orig = btn.textContent;
  var done = function(ok) {{
    btn.textContent = ok ? 'Copied!' : 'Copy failed';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function() {{ done(true); }}).catch(function() {{ fallback(); }});
  }} else {{
    fallback();
  }}
  function fallback() {{
    var t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.left = '-9999px';
    document.body.appendChild(t); t.focus(); t.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }}
    catch (e) {{ done(false); }}
    document.body.removeChild(t);
  }}
}}

function copyActiveTone(btn, cardId) {{
  // Find the active tone panel
  var activePanel = document.querySelector('.tone-panel[data-card="' + cardId + '"]:not([style*="none"])');
  if (!activePanel) {{
    activePanel = document.querySelector('.tone-panel[data-card="' + cardId + '"]');
  }}
  if (!activePanel) {{ return; }}
  // Get text from caption-textarea or caption-text
  var ta = activePanel.querySelector('.caption-textarea');
  var textEl = activePanel.querySelector('.caption-text');
  var text = (ta && ta.value) ? ta.value : (textEl ? textEl.textContent : '');
  // Also check old-style tone-text-ID elements
  if (!text) {{
    var activeTone = activePanel.dataset.tone;
    var oldTa = document.getElementById('tone-text-' + cardId + '-' + activeTone);
    if (oldTa) text = oldTa.value;
  }}
  if (!text) {{ return; }}
  navigator.clipboard.writeText(text).then(function() {{
    var orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }}).catch(function() {{
    var tempTa = document.createElement('textarea');
    tempTa.value = text;
    document.body.appendChild(tempTa);
    tempTa.select();
    document.execCommand('copy');
    document.body.removeChild(tempTa);
    var orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }});
}}

// V7: Caption save
function saveCaption(btn, runId, cardId) {{
  var container = btn.closest('div');
  var edits = {{}};
  container.querySelectorAll('.cap-edit').forEach(function(ta) {{
    if(ta.value.trim()) edits[ta.dataset.key] = ta.value.trim();
  }});
  if(!Object.keys(edits).length) return;
  var url = WF_API_BASE + encodeURIComponent(cardId);
  btn.textContent = 'Saving&hellip;';
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_edits',edits:edits}})}})
    .then(r=>r.json())
    .then(j=>{{
      btn.textContent = j.ok ? 'Saved!' : 'Error';
      // Reflect auto-bumped 'edited' status on the row's pill if backend set it
      if (j.ok && j.status) {{
        var row = btn.closest('.ach-row');
        if (row) {{
          var pill = row.querySelector('.wf-pill');
          if (pill && pill.dataset.status === 'queue') {{
            pill.textContent = j.status;
            pill.dataset.status = j.status;
            row.dataset.status = j.status;
            var cols = WF_COLOURS[j.status] || WF_COLOURS.queue;
            pill.style.background = cols[0];
            pill.style.color = cols[1];
          }}
        }}
      }}
      setTimeout(function(){{ btn.textContent = 'Save caption edits'; }}, 1800);
    }})
    .catch(()=>{{ btn.textContent = 'Error'; }});
}}

// V8: Lazy visual generation. Cached per (card, format) within session.
var _visualCache = {{}};
function createGraphic(btn, createUrl, cardId, fmt) {{
  fmt = fmt || 'feed_portrait';
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating&hellip;';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(139,92,246,0.3);border-top-color:#8B5CF6;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Generating graphic&hellip; this may take 5-15 seconds</div>';
  var cacheKey = cardId + '|' + fmt;
  if (_visualCache[cacheKey]) {{
    _renderVisualPanel(panel, _visualCache[cacheKey], cardId, createUrl);
    btn.disabled = false; btn.textContent = origLabel;
    return;
  }}
  fetch(createUrl, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{format: fmt}})}})
    .then(function(r) {{ return r.json().then(function(j){{ return {{ok: r.ok, body: j}}; }}); }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok || res.body.error) {{
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Error: ' + (res.body.error || 'render failed') + '</div>';
        return;
      }}
      _visualCache[cacheKey] = res.body;
      _renderVisualPanel(panel, res.body, cardId, createUrl);
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

// Escape a JS expression so it can safely live inside an HTML onclick="..." attribute.
// JSON.stringify produces a string with literal double quotes; those would close the HTML
// attribute prematurely. We replace inner " with the &quot; entity (the browser decodes
// them back to " before passing to the JS engine).
function _attrEsc(jsExpr) {{
  return '"' + jsExpr.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"';
}}

function _renderVisualPanel(panel, data, cardId, createUrl) {{
  var visuals = data.visuals || [];
  if (!visuals.length) {{
    panel.innerHTML = '<div style="padding:14px;color:var(--ink-muted);font-size:13px">No visuals generated. ' + ((data.errors && data.errors.length) ? 'Errors: ' + data.errors.join('; ') : '') + '</div>';
    return;
  }}
  var v = visuals[0];
  // Use absolute path that respects the deployed /port/5000 prefix; the backend prepends location.pathname's base via window._API_BASE.
  var apiBase = (window._API_BASE || '');
  var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(v.id) + '/png/' + encodeURIComponent(v.format_name || 'feed_portrait');
  var why = (data.brief && data.brief.why_this_design) || v.why_this_design || '';
  var layout = v.layout_template || (data.brief && data.brief.layout_template) || '';
  var formats = ['feed_portrait', 'feed_square', 'story_vertical'];
  var formatLabels = {{'feed_portrait':'Portrait', 'feed_square':'Square', 'story_vertical':'Story'}};
  var tabsHtml = formats.map(function(f) {{
    var active = (f === (v.format_name || 'feed_portrait'));
    return '<button class="vfmt-tab" data-fmt="' + f + '" onclick=' + _attrEsc('createGraphic(this, ' + JSON.stringify(createUrl) + ', ' + JSON.stringify(cardId) + ', ' + JSON.stringify(f) + ')') + ' style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);cursor:pointer;background:' + (active ? 'rgba(139,92,246,0.15)' : 'transparent') + ';color:' + (active ? '#A78BFA' : 'var(--ink-dim)') + ';font-family:inherit;margin-right:4px">' + formatLabels[f] + '</button>';
  }}).join('');
  panel.innerHTML =
    '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
      '<div style="flex:0 0 220px;max-width:240px">' +
        '<img src="' + imgUrl + '" alt="Generated graphic" style="width:100%;border-radius:6px;border:1px solid var(--border);background:#0a0a0a" />' +
      '</div>' +
      '<div style="flex:1;min-width:200px">' +
        '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Generated visual &middot; ' + (layout || 'auto') + '</div>' +
        (why ? '<div style="font-size:12px;color:var(--ink);margin-bottom:8px;line-height:1.4">' + why + '</div>' : '') +
        '<div style="margin-bottom:8px">' + tabsHtml + '</div>' +
        '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
          '<a class="btn secondary" href="' + imgUrl + '" download style="font-size:11px;padding:4px 10px">Download PNG</a>' +
          '<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick=' + _attrEsc('regenerateGraphic(this, ' + JSON.stringify(createUrl) + ', ' + JSON.stringify(cardId) + ')') + '>&#x21BA; Regenerate (3 variants)</button>' +
          '<button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick=' + _attrEsc('addGraphicToPack(this, ' + JSON.stringify(v.id) + ')') + '>+ Add to pack</button>' +
        '</div>' +
      '</div>' +
    '</div>';
}}

// Motion-graphic generation: lazy, cached server-side. Streams the resulting
// MP4 into an inline <video> on the card panel.
var _motionCache = {{}};
function generateMotion(btn, motionUrl, cardId) {{
  var panel = document.querySelector('.motion-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering motion&hellip;';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(249,115,22,0.3);border-top-color:#F97316;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Rendering motion graphic&hellip; cached renders return in ~5s, cold renders up to 90s.</div>';
  fetch(motionUrl, {{method:'POST'}})
    .then(function(r) {{
      if (r.ok && r.headers.get('content-type') && r.headers.get('content-type').indexOf('video') !== -1) {{
        return r.blob().then(function(b) {{ return {{ok:true, blob:b}}; }});
      }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        // Prefer user_message (clean operator-written copy) over detail
        // (raw stack trace). The backend Phase 1.5 mapping translates
        // known infra failures into actionable copy; falls back to detail
        // for anything unexpected.
        var msg = (res.body && (res.body.user_message || res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      _motionCache[cardId] = url;
      panel.innerHTML =
        '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 200px;max-width:220px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:200px">' +
            '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Motion &middot; 1080&times;1920 &middot; 6s</div>' +
            '<div style="font-size:12px;color:var(--ink);margin-bottom:8px;line-height:1.4">Branded story-format MP4 rendered via Remotion. Same brand colours, palette, and seed as the static card.</div>' +
            '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
              '<a class="btn secondary" href="' + url + '" download="motion-' + cardId + '.mp4" style="font-size:11px;padding:4px 10px">Download MP4</a>' +
            '</div>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

// Meet-reel generation: top-3 cards stitched into a 15-second reel.
function generateReel(btn, reelUrl) {{
  var panel = document.getElementById('reel-panel');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering reel&hellip;';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(249,115,22,0.3);border-top-color:#F97316;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Producing 15-second reel from the top 3 cards&hellip; cold renders may take up to 90s.</div>';
  fetch(reelUrl, {{method:'POST'}})
    .then(function(r) {{
      if (r.ok && r.headers.get('content-type') && r.headers.get('content-type').indexOf('video') !== -1) {{
        return r.blob().then(function(b) {{ return {{ok:true, blob:b}}; }});
      }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        var msg = (res.body && (res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Reel render error: ' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      panel.innerHTML =
        '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 240px;max-width:260px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:240px">' +
            '<div style="font-size:11px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:4px">Meet reel &middot; 1080&times;1920 &middot; 15s</div>' +
            '<div style="font-size:13px;color:var(--ink);margin-bottom:10px;line-height:1.4">Top-3 ranked moments stitched into a branded reel with smooth crossfades, club colours, and the meet headline.</div>' +
            '<div style="display:flex;gap:6px;flex-wrap:wrap">' +
              '<a class="btn secondary" href="' + url + '" download="meet-reel.mp4" style="font-size:12px;padding:4px 12px">Download MP4</a>' +
            '</div>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

function regenerateGraphic(btn, createUrl, cardId) {{
  // V8.1 issue 4: replace single-output regenerate with a 3-variant picker.
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  if (!panel) return;
  panel.style.display = '';
  // Derive the variants endpoint from the create-graphic URL.
  var variantsUrl = createUrl.replace(/\\/create-graphic$/, '/regenerate-variants');
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Generating 3 options&hellip;';
  panel.innerHTML = '<div style="padding:24px;text-align:center;color:var(--ink-muted);font-size:13px">' +
    '<div style="width:24px;height:24px;border:2px solid rgba(139,92,246,0.3);border-top-color:#8B5CF6;border-radius:50%;margin:0 auto 10px;animation:spin 600ms linear infinite"></div>' +
    'Producing 3 alternative designs in parallel&hellip; 10-30 seconds.</div>';
  fetch(variantsUrl, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:'{{}}'}})
    .then(function(r){{ return r.json().then(function(j){{ return {{ok:r.ok, body:j}}; }}); }})
    .then(function(res){{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok || res.body.error) {{
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Error: ' + (res.body.error || 'variants failed') + '</div>';
        return;
      }}
      _renderVariantPicker(panel, res.body.variants || [], cardId, createUrl);
    }})
    .catch(function(err){{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

function _renderVariantPicker(panel, variants, cardId, createUrl) {{
  if (!variants.length) {{
    panel.innerHTML = '<div style="padding:14px;color:var(--ink-muted);font-size:13px">No variants returned.</div>';
    return;
  }}
  var apiBase = (window._API_BASE || '');
  var tilesHtml = variants.map(function(vt) {{
    var v = vt.visual;
    if (!v) {{
      return '<div style="flex:1;min-width:160px;padding:14px;border:1px dashed var(--border);border-radius:8px;text-align:center;color:#F87171;font-size:12px">Variant ' + vt.seed + ' failed: ' + ((vt.errors||[]).join("; ") || 'unknown') + '</div>';
    }}
    var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(v.id) + '/png/' + encodeURIComponent(v.format_name || 'feed_portrait');
    var label = (vt.brief && vt.brief.layout_template) || v.layout_template || ('Variant ' + vt.seed);
    var hook = (vt.brief && vt.brief.primary_hook) || '';
    return (
      '<div class="variant-tile" style="flex:1;min-width:160px;background:rgba(139,92,246,0.04);border:1px solid var(--border);border-radius:8px;padding:8px">' +
        '<img src="' + imgUrl + '" alt="Variant ' + vt.seed + '" style="width:100%;border-radius:6px;background:#0a0a0a;display:block" />' +
        '<div style="font-size:10px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-top:6px">Option ' + vt.seed + ' &middot; ' + label + '</div>' +
        (hook ? '<div style="font-size:11px;color:var(--ink);margin-top:2px">' + hook + '</div>' : '') +
        '<button class="btn" data-pick-vid="' + v.id + '" data-pick-seed="' + vt.seed + '" data-pick-fmt="' + (v.format_name || 'feed_portrait') + '" style="margin-top:6px;width:100%;font-size:11px;padding:5px 0" onclick=' + _attrEsc('pickVariant(this, ' + JSON.stringify(cardId) + ', ' + JSON.stringify(createUrl) + ')') + '>Pick this one</button>' +
      '</div>'
    );
  }}).join('');
  panel.innerHTML =
    '<div style="font-size:11px;color:var(--ink-muted);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px">Choose a variant</div>' +
    '<div style="display:flex;gap:10px;flex-wrap:wrap">' + tilesHtml + '</div>';
}}

function pickVariant(btn, cardId, createUrl) {{
  var vid = btn.dataset.pickVid;
  var seed = btn.dataset.pickSeed;
  var fmt = btn.dataset.pickFmt || 'feed_portrait';
  var apiBase = (window._API_BASE || '');
  var imgUrl = apiBase + '/api/visual/' + encodeURIComponent(vid) + '/png/' + encodeURIComponent(fmt);
  // Persist the choice in workflow sidecar
  var url = WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{action:'set_edits', edits:{{picked_visual_id: vid, picked_variation_seed: seed}}}})}}).catch(function(){{}});
  // Promote to primary view
  var panel = document.querySelector('.visual-panel[data-card="' + cardId + '"]');
  var fakeData = {{
    visuals: [{{id: vid, format_name: fmt, layout_template: btn.parentElement.querySelector('div').textContent || ''}}],
    brief: {{}},
  }};
  _renderVisualPanel(panel, fakeData, cardId, createUrl);
}}

function addGraphicToPack(btn, visualId) {{
  // Visuals are already persisted on render; this just confirms inclusion.
  btn.textContent = '&#x2713; Added to pack';
  btn.disabled = true;
  setTimeout(function() {{ btn.textContent = '+ Add to pack'; btn.disabled = false; }}, 2000);
}}

// Poll LLM status on page load and every 30s afterwards. Self-healing:
// if a previous transient 429 painted the dot red, the next poll
// re-greens it once the rate-limit window has elapsed. Without this
// the user had to reload the page to recover from any blip.
(function pollLlmStatus(){{
  function _tick() {{
    try {{
      var url = (window._API_BASE || '') + '/api/settings/llm-status';
      fetch(url, {{cache:'no-store'}})
        .then(function(r){{ return r.json(); }})
        .then(function(j){{
          var dots = document.querySelectorAll('.ai-status-dot');
          var color = j.live ? '#2cc97f' : '#ff5d6c';
          var providerLabel = j.provider_label || 'AI key';
          var title = j.live
            ? ('Live AI enabled &mdash; provider: ' + providerLabel)
            : 'Live AI DISABLED &mdash; contact your administrator to enable AI captions.';
          dots.forEach(function(d){{
            d.style.background = color;
            var btn = d.closest('button');
            if (btn) btn.title = title;
          }});
        }})
        .catch(function(){{}});
    }} catch(e){{}}
  }}
  _tick();
  setInterval(_tick, 30000);
}})();
</script>
"""
        return _layout("Recognition", body, active="home")

    # ---- V5 API ROUTES -------------------------------------------------
    @app.route("/api/runs/<run_id>/recognition")
    def api_recognition(run_id):
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        rr = data.get("recognition_report")
        if rr is None:
            return jsonify({"error": "no recognition report", "recognition_error": data.get("recognition_error")}), 404
        return jsonify(rr)

    @app.route("/api/runs/<run_id>/swim/<swim_id>/trace")
    def api_swim_trace(run_id, swim_id):
        data = _load_run(run_id)
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


    # ---- V8 LIVE CAPTION ENDPOINT -----------------------------------

    @app.route("/api/runs/<run_id>/swim/<swim_id>/caption", methods=["POST"])
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
        data = _load_run(run_id)
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
            "swimmer_first": achievement.get("swimmer_name", "").split()[0] if achievement.get("swimmer_name") else "",
            "swimmer_last": " ".join(achievement.get("swimmer_name", "").split()[1:]) if achievement.get("swimmer_name") else "",
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
                _why = _build_card_explanation(matched_ra or {"achievement": achievement})
                _why_headline = (_why.get("headline") or "").strip()
                _why_bullets = _why.get("bullets") or []
                _why_bullets_text = (
                    "; ".join(b for b in _why_bullets if b)
                    if isinstance(_why_bullets, list) else ""
                )
                _is_fallback_headline = (
                    "unavailable" in _why_headline.lower()
                    or _why_headline.startswith("Generated for:")
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
                _club_prof = load_profile(_run_profile_id)
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
                club_profile_obj = load_profile(run_profile_id)
            except Exception:
                club_profile_obj = None

        now_iso = datetime.now(_tz.utc).isoformat()

        # V9: build the plain-English explanation once per request so every
        # response (live, fallback, error) carries it.
        explanation = _build_card_explanation(matched_ra or {"achievement": achievement})

        from mediahub.media_ai.llm import is_available as _llm_available
        from mediahub.web.ai_caption import (
            generate_caption_for_tone as _gen_tone,
            KNOWN_AI_TONES as _AI_TONES,
            ClaudeUnavailableError as _ClaudeUE,  # type: ignore[attr-defined]
        )

        if tone in _AI_TONES:
            # LIVE generation &mdash; fresh every call, nonce injected for uniqueness.
            # Works with Gemini (free) or Anthropic API key.
            if not _llm_available():
                return jsonify({
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
                }), 200
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
                n_variants = int(request.args.get("n_variants") or 1)
                n_variants = max(1, min(n_variants, 4))

                def _gen_one():
                    try:
                        return _gen_tone(
                            ach_dict, club_brand, tone=tone,
                            voice_profile=_run_voice_profile,
                            club_profile=club_profile_obj,
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

                if n_variants == 1:
                    variants = [_gen_one()]
                else:
                    with ThreadPoolExecutor(max_workers=n_variants) as pool:
                        variants = list(pool.map(lambda _: _gen_one(), range(n_variants)))
                # Drop None placeholders from failed variants.
                variants = [v for v in variants if v]
                # Deduplicate identical outputs (Gemini occasionally returns the
                # same caption twice on short prompts) while preserving order.
                seen = set()
                unique = []
                for v in variants:
                    if v and v not in seen:
                        seen.add(v)
                        unique.append(v)
                variants = unique or variants

                caption_text = variants[0] if variants else ""
                # If every variant failed (e.g. provider rate-limited),
                # distinguish that from "no key configured". The former
                # is transient — the user should be told to retry, not
                # told the deployment doesn't have AI.
                if not caption_text:
                    return jsonify({
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
                    }), 200
                return jsonify({
                    "caption": caption_text,
                    "variants": variants,
                    "n_variants": len(variants),
                    "tone": tone,
                    "live": True,
                    "generated_at": now_iso,
                    "fallback": False,
                    "fallback_voice": None,
                    "explanation": explanation,
                })
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
                    return jsonify({
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
                    }), 200
                return jsonify({
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
                }), 200
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
            return jsonify({
                "caption": caption_text,
                "tone": tone,
                "generated_at": now_iso,
                "fallback": False,
                "fallback_voice": None,
                "explanation": explanation,
            })

    # ---- V6 PB AUDIT ROUTES ----------------------------------------

    @app.route("/audit/<run_id>")
    def pb_audit_page(run_id):
        """Full PB audit page with per-swimmer drill-down."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        pb_audit = data.get("pb_audit") or {}
        if not pb_audit:
            return _layout("PB Audit",
                           '<div class="card"><p class="muted">No detailed PB audit for this run. '
                           'Re-run with PB fetching enabled.</p></div>', active="")
        per_swimmer = pb_audit.get("per_swimmer") or []
        _review_url = url_for("review", run_id=run_id)

        rows = ""
        for sa in per_swimmer:
            identity = sa.get("identity") or {}
            method = identity.get("method", "")
            method_cls = {
                "asa_id_verified": "good",
                "needs_verification": "warn",
                "asa_id_unverified": "",
                "no_id": "",
                "manual_override": "info",
            }.get(method, "")
            _sw_key = sa.get('asa_id') or f"name:{sa.get('hy3_name','')}"
            _verify_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=_sw_key)
            _ignore_url = url_for('pb_ignore', run_id=run_id, swimmer_key=_sw_key)
            n_dec = len(sa.get('pb_decisions') or [])
            n_conf = sum(1 for d in (sa.get('pb_decisions') or []) if d.get('status') == 'CONFIRMED_PB')
            rows += (
                f'<tr>'
                f'<td>{_h(sa.get("hy3_name",""))}</td>'
                f'<td class="muted">{_h(sa.get("asa_id") or "—")}</td>'
                f'<td>{_h(sa.get("sr_name") or "—")}</td>'
                f'<td><span class="tag {method_cls}">{_h(method)}</span></td>'
                f'<td>{n_dec}</td>'
                f'<td style="color:#4ADE80">{n_conf}</td>'
                f'<td>'
                f'<a class="btn secondary" style="font-size:11px;padding:3px 8px" href="{_verify_url}">Verify</a>'
                f' <form style="display:inline" method="post" action="{_ignore_url}">'
                f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" type="submit">Ignore PBs</button></form>'
                f'</td>'
                f'</tr>'
            )

        body = f"""
<h1>PB Audit &mdash; {_h(pb_audit.get('run_id', run_id))}</h1>
<p class="dim"><a href="{_review_url}">&larr; Back to review</a></p>
<div class="card">
  <div class="stat-block">
    <div class="stat"><div class="l">Swimmers</div><div class="v">{pb_audit.get('swimmers_total',0)}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Verified</div><div class="v" style="color:#22D3EE">{pb_audit.get('swimmers_matched_verified',0)}</div></div>
    <div class="stat"><div class="l" style="color:#F59E0B">Needs verification</div><div class="v" style="color:#F59E0B">{pb_audit.get('swimmers_needs_verification',0)}</div></div>
    <div class="stat"><div class="l">Confirmed PBs</div><div class="v" style="color:#4ADE80">{pb_audit.get('pb_confirmed_count',0)}</div></div>
    <div class="stat"><div class="l">Total decisions</div><div class="v">{pb_audit.get('pb_decisions_count',0)}</div></div>
    <div class="stat"><div class="l">Fetch time</div><div class="v">{pb_audit.get('fetch_total_seconds',0):.1f}s</div></div>
  </div>
</div>
<div class="card">
  <h2>Per-swimmer</h2>
  <table>
    <thead><tr>
      <th>HY3 Name</th><th>ASA ID</th><th>SR Name</th><th>Identity</th><th>Decisions</th><th>Confirmed</th><th>Actions</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""
        return _layout("PB Audit", body, active="")

    @app.route("/audit/<run_id>/verify/<path:swimmer_key>", methods=["GET", "POST"])
    def pb_verify_form(run_id, swimmer_key):
        """Form to enter correct ASA number for a needs-verification swimmer."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        _review_url = url_for("review", run_id=run_id)
        _audit_url = url_for("pb_audit_page", run_id=run_id)

        if request.method == "POST":
            new_asa = request.form.get("new_asa_id", "").strip()
            note = request.form.get("note", "").strip()
            if new_asa:
                from swim_content_pb.corrections import CorrectionsStore
                cs = CorrectionsStore()
                cs.set_override_asa_id(run_id, swimmer_key, new_asa, note=note)
            return redirect(_audit_url)

        _sw_key_h = _h(swimmer_key)
        _action_url = url_for('pb_verify_form', run_id=run_id, swimmer_key=swimmer_key)

        # Pull this swimmer's audit details so the user can see WHY this needs
        # verification &mdash; not just an opaque key.
        pb_audit = data.get("pb_audit") or {}
        per_sw = pb_audit.get("per_swimmer") or []
        target = None
        for sw in per_sw:
            if str(sw.get("asa_id") or "") == swimmer_key or sw.get("hy3_name", "").replace(",", "").replace(" ", "").lower() == swimmer_key.replace(",", "").replace(" ", "").lower():
                target = sw
                break

        context_html = ""
        if target:
            ident = target.get("identity") or {}
            hy3_name = _h(target.get("hy3_name") or "—")
            sr_name = _h(target.get("sr_name") or "— (no record returned)")
            method = _h(ident.get("method") or "—")
            method_pill = {"asa_id_verified": "good", "needs_verification": "warn",
                          "asa_id_unverified": "warn", "no_id": "bad",
                          "manual_override": "info"}.get(ident.get("method", ""), "")
            cur_asa = _h(target.get("asa_id") or "—")
            notes_list = ident.get("notes") or []
            notes_html = "".join(f"<li>{_h(n)}</li>" for n in notes_list) or "<li class='muted'>No notes</li>"
            context_html = f"""
<div class="card" style="margin-bottom:18px">
  <h2 style="font-size:16px;margin-bottom:14px">What we know about this swimmer</h2>
  <table style="width:100%;font-size:13px">
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">In your file (HY3)</td>
        <td><strong>{hy3_name}</strong></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">Currently linked ASA ID</td>
        <td><code>{cur_asa}</code></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">PB source returned</td>
        <td><strong>{sr_name}</strong></td></tr>
    <tr><td style="padding:6px 12px 6px 0;color:var(--ink-dim)">Match status</td>
        <td><span class="tag {method_pill}">{method}</span></td></tr>
  </table>
  <div style="margin-top:14px;font-size:12px;color:var(--ink-dim)">
    <strong>Why this matters:</strong>
    <ul style="margin:4px 0 0 20px">{notes_html}</ul>
  </div>
</div>"""
        else:
            context_html = f"""
<div class="card" style="margin-bottom:18px">
  <p class="muted">Swimmer key <code>{_sw_key_h}</code> wasn't found in this run's audit data. You can still set a manual override.</p>
</div>"""

        body = f"""
<h1>Verify swimmer identity</h1>
<p class="dim"><a href="{_audit_url}">&larr; Back to audit</a></p>
{context_html}
<div class="card">
  <h2 style="font-size:16px;margin-bottom:8px">Set the correct ASA member ID</h2>
  <p class="dim" style="font-size:13px">This override applies to this meet only. It won't affect other runs.
  If you save this, we'll re-fetch PBs for the corrected ID.</p>
  <form method="post" action="{_action_url}">
    <label>Correct ASA member ID</label>
    <input type="text" name="new_asa_id" placeholder="e.g. 1382076" pattern="[0-9]+" required />
    <label>Note (optional)</label>
    <input type="text" name="note" placeholder="Why this override (e.g. wrong number entered in HY3)" />
    <div style="margin-top:14px;display:flex;gap:10px">
      <button class="btn" type="submit">Save correction</button>
      <a class="btn secondary" href="{_audit_url}">Cancel</a>
    </div>
  </form>
</div>"""
        return _layout("Verify swimmer", body, active="")

    @app.route("/audit/<run_id>/ignore/<path:swimmer_key>", methods=["POST"])
    def pb_ignore(run_id, swimmer_key):
        """Mark 'ignore PBs for this swimmer in this meet'."""
        reason = request.form.get("reason", "User requested ignore")
        from swim_content_pb.corrections import CorrectionsStore
        cs = CorrectionsStore()
        cs.set_ignore_pb(run_id, swimmer_key, reason=reason)
        return redirect(url_for('pb_audit_page', run_id=run_id))

    @app.route("/audit/<run_id>/ground-truth", methods=["GET", "POST"])
    def pb_ground_truth(run_id):
        """Upload a CSV of expected outcomes and run the ground-truth harness."""
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404
        _audit_url = url_for('pb_audit_page', run_id=run_id)
        _action_url = url_for('pb_ground_truth', run_id=run_id)

        report_html = ""
        if request.method == "POST":
            f = request.files.get("csv_file")
            if f and f.filename:
                import tempfile
                from pathlib import Path as _Path
                from swim_content_pb.ground_truth import run_ground_truth
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                    f.save(tmp.name)
                    csv_path = _Path(tmp.name)
                try:
                    report = run_ground_truth(
                        run_id=run_id,
                        truth_csv_path=csv_path,
                        run_pb_audit_dict=data.get('pb_audit'),
                    )
                    report_html = (
                        f'<div class="card"><h2>Ground Truth Results</h2>'
                        f'<div class="stat-block">'
                        f'<div class="stat"><div class="l">Total entries</div><div class="v">{report.total_entries}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#4ADE80">True positives</div><div class="v" style="color:#4ADE80">{report.true_positives}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#F87171">False positives</div><div class="v" style="color:#F87171">{report.false_positives}</div></div>'
                        f'<div class="stat"><div class="l" style="color:#FBBF24">False negatives</div><div class="v" style="color:#FBBF24">{report.false_negatives}</div></div>'
                        f'<div class="stat"><div class="l">Precision</div><div class="v">{report.precision or "&mdash;"}</div></div>'
                        f'<div class="stat"><div class="l">Recall</div><div class="v">{report.recall or "&mdash;"}</div></div>'
                        f'<div class="stat"><div class="l">F1</div><div class="v">{report.f1 or "&mdash;"}</div></div>'
                        f'</div></div>'
                    )
                except Exception as e:
                    report_html = f'<div class="card"><p class="tag bad">Error: {_h(str(e))}</p></div>'
                finally:
                    try:
                        csv_path.unlink()
                    except Exception:
                        pass

        body = f"""
<h1>Ground Truth &mdash; PB Decisions</h1>
<p class="dim"><a href="{_audit_url}">&larr; Back to PB audit</a></p>
<div class="card">
  <p>Upload a CSV with columns: <code>swimmer_name, event_label, result_time, expected_pb, expected_prev_pb, expected_barrier_crossed, notes</code></p>
  <p><code>expected_pb</code>: yes | no | unknown</p>
  <form method="post" enctype="multipart/form-data" action="{_action_url}">
    <input type="file" name="csv_file" accept=".csv" required />
    <div style="margin-top:12px"><button class="btn" type="submit">Run ground truth</button></div>
  </form>
</div>
{report_html}"""
        return _layout("Ground Truth", body, active="")

    @app.route("/recognition/<run_id>")
    def recognition_page(run_id):
        """Standalone recognition page (redirect to review for now)."""
        return redirect(url_for('review', run_id=run_id))

    @app.route("/api/runs/<run_id>/cards")
    def api_cards(run_id):
        state = _run_state(run_id)
        if state == "in_progress":
            return jsonify({"error": "in_progress", "retry_after": 4}), 202
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data.get("cards", []))

    @app.route("/api/runs/<run_id>/trust")
    def api_trust(run_id):
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data.get("trust", {}))

    @app.route("/api/runs/<run_id>/export")
    def api_export(run_id):
        state = _run_state(run_id)
        if state == "in_progress":
            return jsonify({"error": "in_progress", "retry_after": 4}), 202
        data = _load_run(run_id)
        if not data:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    # ---- GROUND TRUTH --------------------------------------------------
    @app.route("/ground-truth/<run_id>", methods=["GET", "POST"])
    def ground_truth(run_id):
        data = _load_run(run_id)
        if not data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        rep_html = ""
        if request.method == "POST":
            text = request.form.get("moments", "")
            from .ground_truth import evaluate
            # Need ContentCard objects: re-hydrate basic shape from saved dicts
            class _Stub:
                pass
            cards = []
            for d in data.get("cards") or []:
                s = _Stub()
                s.card_id = d.get("card_id", "")
                s.headline = d.get("headline", "")
                s.swimmer_names = d.get("swimmer_names") or []
                s.bucket = d.get("bucket", "")
                claims = []
                for cl in d.get("claims") or []:
                    cs = _Stub()
                    cs.distance = cl.get("distance"); cs.stroke = cl.get("stroke")
                    claims.append(cs)
                s.claims = claims
                cards.append(s)
            rep = evaluate(text, cards)
            data["ground_truth_report"] = rep.to_dict()
            (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(data, indent=2, default=str))

            rows = ""
            for m in rep.matches:
                badge = "good" if m.get("matched_card") else "bad"
                rows += (f'<tr><td>{_h(m.get("moment",""))}</td>'
                         f'<td><span class="tag {badge}">'
                         f'{"matched" if m.get("matched_card") else "missed"}</span></td>'
                         f'<td>{_h(m.get("matched_headline") or "—")}</td>'
                         f'<td>{_h(m.get("score",""))}</td></tr>')
            rep_html = f"""
<div class="card">
  <h2>Result</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Precision</div><div class="v">{rep.precision*100:.0f}%</div></div>
    <div class="stat"><div class="l">Recall</div><div class="v">{rep.recall*100:.0f}%</div></div>
    <div class="stat"><div class="l">F1</div><div class="v">{rep.f1*100:.0f}%</div></div>
    <div class="stat"><div class="l">Matched</div><div class="v">{rep.n_matched_moments}/{rep.n_total_moments}</div></div>
  </div>
  <div class="divider"></div>
  <table>
    <thead><tr><th>Expected moment</th><th>Status</th><th>Best card match</th><th>Score</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="muted" style="margin-top:14px">{rep.notes}</p>
</div>
"""

        body = f"""
<h1>Ground-truth check</h1>
<p class="dim">Paste 5&ndash;15 expected highlights from this meet. We score how well MediaHub
surfaces them as content cards. One per line.</p>

<div class="card">
  <form method="post">
    <label>Expected moments (one per line)</label>
    <textarea name="moments" placeholder="Eva Davies 100m butterfly PB
Mathew Bradley 200m IM gold
Relay team broke club record"></textarea>
    <div style="margin-top:14px"><button class="btn" type="submit">Score</button></div>
  </form>
</div>
{rep_html}
"""
        return _layout("Ground truth", body, active="home")

    # ---- RESEARCH ------------------------------------------------------
    @app.route("/research")
    def research_page():
        # Try to render a research markdown if present
        md_path = RESEARCH_DIR / "parser_roadmap.md"
        if md_path.exists():
            content = md_path.read_text()
            html = _render_markdown(content)
        else:
            html = """
<h2>Adapter roadmap (interim)</h2>
<p>The research substream is collecting source-format coverage across UK and US meets.
   This page will populate when the roadmap document is written.</p>
<h3>Currently supported</h3>
<ul>
  <li><strong>HY3</strong> &mdash; Hytek Meet Manager (UK + US) &mdash; full parser with splits.</li>
</ul>
<h3>Planned next</h3>
<ul>
  <li>SDIF / CL2 &mdash; sibling format produced by Hytek and used by USA Swimming.</li>
  <li>Meet Mobile / SwimTopia exports (CSV).</li>
  <li>Public meet-result pages from external swim-results sites (HTML adapter).</li>
  <li>USA Swimming Times Search exports.</li>
</ul>
<p class="muted">Each new adapter must implement <code>can_parse()</code> and return the
   canonical Meet schema. No detector / caption code changes are needed.</p>
"""
        body = f'<h1>Research roadmap</h1><div class="card">{html}</div>'
        return _layout("Research", body, active="research")

    # ---- PRIVACY -------------------------------------------------------
    @app.route("/privacy")
    def privacy_page():
        conn = _db()
        n_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        conn.close()
        n_files = sum(1 for _ in RUNS_DIR.glob("*.json"))
        n_uploads = sum(1 for _ in UPLOADS_DIR.iterdir())
        cache_dir = DATA_DIR / ".cache" / "pb_lookup"
        legacy_cache = DATA_DIR / ".cache" / "swimmingresults"
        n_cache = (
            (sum(1 for _ in cache_dir.glob("*.json")) if cache_dir.exists() else 0)
            + (sum(1 for _ in legacy_cache.glob("*.json")) if legacy_cache.exists() else 0)
        )
        body = f"""
<h1>Privacy & data</h1>
<p class="dim">What this system stores, where, and how to delete it.</p>

<div class="card">
  <h2>Inventory</h2>
  <div class="stat-block">
    <div class="stat"><div class="l">Runs (DB)</div><div class="v">{n_runs}</div></div>
    <div class="stat"><div class="l">Run JSON files</div><div class="v">{n_files}</div></div>
    <div class="stat"><div class="l">Upload temp files</div><div class="v">{n_uploads}</div></div>
    <div class="stat"><div class="l">PB cache entries</div><div class="v">{n_cache}</div></div>
  </div>
</div>

<div class="card">
  <h2>What we store</h2>
  <ul>
    <li><strong>Run records</strong> &mdash; per upload: meet metadata, parsed swims, generated cards, captions, audit log. Deletable per run.</li>
    <li><strong>Club profiles</strong> &mdash; your roster + branding. Editable on the Profiles tab.</li>
    <li><strong>PB cache</strong> &mdash; local cache of public PB-lookup pages (the active source is chosen at runtime), keyed by member id. Clearable.</li>
    <li><strong>Database</strong> &mdash; small SQLite index <code>data.db</code> for the run list.</li>
  </ul>
  <p class="muted">No data is sent to third parties beyond fetching public PB-lookup pages from the configured PB source.</p>
</div>

<div class="card">
  <h2>Actions</h2>
  <form method="post" action="{url_for('privacy_cache_clear')}" style="display:inline" onsubmit="return confirm('Clear the PB cache?')">
    <button class="btn secondary" type="submit">Clear PB cache</button>
  </form>
  <p class="muted" style="margin-top:8px">To delete an individual run, open it from the home page and use the Delete run button.</p>
</div>
"""
        return _layout("Privacy", body, active="privacy")

    @app.route("/privacy/run/<run_id>/delete", methods=["POST"])
    def privacy_delete_run(run_id):
        _delete_run(run_id)
        return redirect(url_for("home"))

    @app.route("/privacy/cache/clear", methods=["POST"])
    def privacy_cache_clear():
        for d in [DATA_DIR / ".cache" / "pb_lookup", DATA_DIR / ".cache" / "swimmingresults"]:
            if d.exists():
                for f in d.glob("*.json"):
                    try: f.unlink()
                    except Exception: pass
        return redirect(url_for("privacy_page"))

    # ---- HEALTH --------------------------------------------------------
    APP_VERSION = "v4.0.0"

    def _health_payload():
        checks = {}
        # backend
        checks["backend"] = {"ok": True, "version": APP_VERSION}
        # db
        try:
            c = _db()
            c.execute("SELECT 1").fetchone()
            c.close()
            try:
                _db_display = str(DB_PATH.relative_to(DATA_DIR))
            except ValueError:
                _db_display = str(DB_PATH)
            checks["database"] = {"ok": True, "path": _db_display}
        except Exception as e:
            checks["database"] = {"ok": False, "error": str(e)}
        # writable dirs
        for label, p in [("uploads", UPLOADS_DIR), ("runs", RUNS_DIR),
                         ("pb_cache", DATA_DIR / ".cache" / "pb_lookup")]:
            try:
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".write_test"
                test.write_text("ok")
                test.unlink()
                # Display path relative to DATA_DIR when possible (production layout);
                # fall back to absolute path when RUNS_DIR / UPLOADS_DIR live outside
                # DATA_DIR (a valid configuration in local dev and tests).
                try:
                    display_path = str(p.relative_to(DATA_DIR))
                except ValueError:
                    display_path = str(p)
                checks[label] = {"ok": True, "path": display_path}
            except Exception as e:
                checks[label] = {"ok": False, "error": str(e)}
        # V8.2: profiles UI removed; health check no longer requires any profiles.
        try:
            profs = list_profiles()
            checks["profiles"] = {"ok": True, "count": len(profs),
                                  "ids": [p.profile_id for p in profs]}
        except Exception as e:
            checks["profiles"] = {"ok": True, "count": 0, "error": str(e)}
        ok_all = all(v.get("ok") for v in checks.values())
        return {
            "ok": ok_all,
            "version": APP_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
        }

    def _record_heartbeat_safe(source: str, ok: bool, started_at: float,
                               error: Optional[str] = None) -> None:
        """Best-effort heartbeat write — never raises into a health probe."""
        try:
            import time as _time
            from mediahub.observability import uptime as _uptime
            _uptime.record_heartbeat(
                ok=ok, source=source,
                response_ms=(_time.monotonic() - started_at) * 1000.0,
                error=error,
            )
        except Exception:
            pass

    @app.route("/health")
    def health():
        import time as _time
        started = _time.monotonic()
        payload = _health_payload()
        # Surface the deep health result into the heartbeat log so /status
        # can count real failures, not just "did the request answer".
        first_error: Optional[str] = None
        if not payload["ok"]:
            for name, check in (payload.get("checks") or {}).items():
                if not check.get("ok"):
                    first_error = f"{name}: {check.get('error', 'failed')}"
                    break
        _record_heartbeat_safe("health", payload["ok"], started, error=first_error)
        return jsonify(payload), (200 if payload["ok"] else 503)

    @app.route("/healthz")
    def healthz():
        # Cheap liveness probe (no disk/db work). We still record a
        # heartbeat row so external monitors and Render's own platform
        # probe contribute to /status's uptime number.
        import time as _time
        started = _time.monotonic()
        payload = {"ok": True, "version": APP_VERSION,
                   "ts": datetime.now(timezone.utc).isoformat()}
        _record_heartbeat_safe("healthz", True, started)
        return jsonify(payload)

    @app.route("/healthz/memory")
    def healthz_memory():
        """Report process memory usage + in-memory state size.

        Added Phase 1.5 as a diagnostic for the "gunicorn restarts
        every 6 minutes" pattern. If `rss_mb` climbs steadily across
        repeated polls, the process is leaking and Render's 512 MB
        ceiling will OOM-kill it. If `rss_mb` is stable and restarts
        still happen, the cause is somewhere else (auto-redeploy,
        platform action, etc.) and the user can stop blaming the app.
        """
        import resource
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is in KB; on macOS it's bytes. Render
        # is always Linux so KB is correct.
        rss_mb = rss_kb / 1024.0
        with _active_lock:
            active_n = len(_active_runs)
            active_running = sum(
                1 for v in _active_runs.values() if v.get("status") == "running"
            )
            ti_n = len(_turn_into_jobs)
        return jsonify({
            "ok": True,
            "rss_mb": round(rss_mb, 1),
            "rss_pct_of_512": round((rss_mb / 512.0) * 100.0, 1),
            "active_runs": active_n,
            "active_runs_running": active_running,
            "active_runs_limit": _ACTIVE_RUNS_LIMIT,
            "turn_into_jobs": ti_n,
            "turn_into_jobs_limit": _TURN_INTO_LIMIT,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

    @app.route("/healthz/deps")
    def healthz_deps():
        """Report whether image / motion rendering dependencies are available.

        Exposed at /healthz/deps (and read by /api/settings/llm-status
        for the captions-tab status dot) so operators can tell at a
        glance whether "Create graphic" and "Generate motion" buttons will
        succeed in the current deployment. Silent failures of these in
        production were the root of "images and videos aren't generating".
        """
        import shutil
        import subprocess
        deps: dict[str, dict] = {}
        # Playwright + chromium browser
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            try:
                with sync_playwright() as p:
                    browser_path = p.chromium.executable_path
                    chromium_ok = bool(browser_path and Path(browser_path).exists())
            except Exception as e:
                chromium_ok = False
                deps["playwright"] = {"available": True, "chromium": False,
                                      "error": str(e)[:200]}
            else:
                deps["playwright"] = {"available": True, "chromium": chromium_ok,
                                      "executable": browser_path or ""}
        except Exception as e:
            deps["playwright"] = {"available": False, "error": str(e)[:200]}
        # Node binary
        node_path = shutil.which("node")
        if node_path:
            try:
                v = subprocess.run([node_path, "--version"],
                                   capture_output=True, text=True, timeout=5)
                deps["node"] = {"available": True, "path": node_path,
                                "version": (v.stdout or "").strip()}
            except Exception as e:
                deps["node"] = {"available": True, "path": node_path,
                                "error": str(e)[:200]}
        else:
            deps["node"] = {"available": False}
        # Remotion node_modules
        remotion_dir = Path(__file__).resolve().parents[1] / "remotion"
        node_modules = remotion_dir / "node_modules" / "remotion"
        deps["remotion"] = {
            "available": node_modules.exists(),
            "dir": str(remotion_dir),
        }
        ok = (deps["playwright"].get("chromium") and deps["node"].get("available")
              and deps["remotion"].get("available"))
        return jsonify({"ok": bool(ok), "deps": deps})

    # ---- /status -------------------------------------------------------
    #
    # Phase 1.5 — public uptime / status page. No org gate, no auth,
    # because:
    #   1. It's a marketable trust signal — the dissertation flagged
    #      reliability as a real wedge against Ocoya / Predis.
    #   2. The data it surfaces is operational, not tenant-scoped: how
    #      many heartbeats arrived in the last 24h, when the last gap
    #      was, what the backend version is.
    #   3. It must be reachable when the org gate would otherwise
    #      redirect — a deploy with no organisations yet should still
    #      be able to prove it's alive.
    #
    # The numbers come from the SQLite uptime log; honest behaviour
    # when no data exists yet is to say so, not fake 100%.
    def _format_uptime_pct(stats: dict) -> str:
        if not stats.get("has_data"):
            return "&mdash;"
        pct = float(stats.get("uptime_pct") or 0.0) * 100.0
        if pct >= 99.995:
            return "100%"
        if pct >= 99.9:
            return f"{pct:.3f}%"
        if pct >= 95.0:
            return f"{pct:.2f}%"
        return f"{pct:.1f}%"

    def _humanize_duration(seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins} min"
        if seconds < 86400:
            hrs = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hrs}h {mins}m" if mins else f"{hrs}h"
        days = seconds // 86400
        hrs = (seconds % 86400) // 3600
        return f"{days}d {hrs}h" if hrs else f"{days}d"

    def _humanize_when(ts: Optional[str]) -> str:
        if not ts:
            return "&mdash;"
        try:
            parsed = ts
            if parsed.endswith("Z"):
                parsed = parsed[:-1] + "+00:00"
            from datetime import datetime as _dt
            then = _dt.fromisoformat(parsed)
            delta = datetime.now(timezone.utc) - then
            secs = int(delta.total_seconds())
            if secs < 0:
                return _h(ts[:19])
            if secs < 60:
                return f"{secs}s ago"
            if secs < 3600:
                return f"{secs // 60} min ago"
            if secs < 86400:
                return f"{secs // 3600}h ago"
            return f"{secs // 86400}d ago"
        except (ValueError, TypeError):
            return _h(ts[:19])

    @app.route("/status")
    def status_page():
        from mediahub.observability import uptime as _uptime

        # Pull three windows so the page reads "24h / 7d / 30d uptime"
        # straight off the database, with no aggregation in the view.
        s24 = _uptime.uptime_stats(window_hours=24)
        s7d = _uptime.uptime_stats(window_hours=24 * 7)
        s30 = _uptime.uptime_stats(window_hours=24 * 30)
        latest = _uptime.latest_heartbeat()
        gaps = _uptime.recent_gaps(window_hours=24 * 30, limit=5)

        # Current pill — green if last heartbeat < 5 min ago AND ok.
        pill_class = "muted"
        pill_label = "no data yet"
        pill_color = "#7a7a7a"
        if latest is not None:
            try:
                ts_raw = latest["ts"]
                if ts_raw.endswith("Z"):
                    ts_raw = ts_raw[:-1] + "+00:00"
                from datetime import datetime as _dt
                last_ts = _dt.fromisoformat(ts_raw)
                age_s = (datetime.now(timezone.utc) - last_ts).total_seconds()
            except (ValueError, TypeError):
                age_s = 99999
            if not latest.get("ok"):
                pill_label = "degraded"
                pill_color = "#ffaa3a"
            elif age_s <= 300:
                pill_label = "operational"
                pill_color = "#2cc97f"
            elif age_s <= 1800:
                pill_label = "stale (no heartbeat in 5–30 min)"
                pill_color = "#ffaa3a"
            else:
                pill_label = "unknown (last heartbeat > 30 min ago)"
                pill_color = "#ff5d6c"

        # Most recent gap → "Last incident" callout.
        last_incident_html = (
            '<p class="dim" style="margin:0">No incidents recorded in the last 30 days.</p>'
        )
        if gaps:
            top = gaps[0]
            duration = _humanize_duration(top["duration_seconds"])
            when = _humanize_when(top["to_ts"])
            last_incident_html = (
                f'<p style="margin:0"><b>Last incident:</b> {_h(when)} '
                f'(silent for {_h(duration)})</p>'
                f'<p class="dim" style="margin:4px 0 0;font-size:12px">'
                f'Detected from a gap in heartbeats between '
                f'{_h(top["from_ts"][:19])} and {_h(top["to_ts"][:19])} UTC.</p>'
            )

        # Build a compact incident table so operators can see the
        # five longest gaps without a separate /status/incidents page.
        if gaps:
            gap_rows = ""
            for g in gaps:
                gap_rows += (
                    f'<tr><td class="muted" style="font-size:12px">'
                    f'{_h(g["to_ts"][:19])} UTC</td>'
                    f'<td>{_h(_humanize_duration(g["duration_seconds"]))}</td>'
                    f'<td class="muted" style="font-size:12px">'
                    f'gap started {_h(g["from_ts"][:19])} UTC</td></tr>'
                )
            incidents_html = (
                '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
                'Recent incidents</h2>'
                '<p class="dim" style="margin-bottom:14px;font-size:13px">'
                'Gaps longer than 5 minutes between heartbeats. The 5-minute '
                'grace window matches the platform ping cadence.</p>'
                '<div class="card"><table>'
                '<thead><tr><th>Resolved</th><th>Duration</th><th>Window</th></tr></thead>'
                f'<tbody>{gap_rows}</tbody></table></div>'
            )
        else:
            incidents_html = ""

        # Pull APP_VERSION from the closure scope.
        version_label = APP_VERSION

        body = (
            '<h1 style="margin-bottom:6px">Status</h1>'
            '<p class="dim" style="margin-bottom:24px">Live operational health '
            'of this MediaHub deployment. Auto-refreshes every 60 seconds.</p>'

            '<div class="card" style="display:flex;align-items:center;gap:14px;'
            'padding:18px 22px;margin-bottom:20px">'
            f'<span style="display:inline-block;width:14px;height:14px;'
            f'border-radius:50%;background:{pill_color};flex:0 0 auto"></span>'
            f'<div style="flex:1"><div style="font-size:18px;font-weight:600">'
            f'Backend &mdash; {_h(pill_label)}</div>'
            f'<div class="dim" style="font-size:13px;margin-top:2px">'
            f'Version <code>{_h(version_label)}</code>'
            + (f' &middot; last heartbeat {_h(_humanize_when(latest["ts"]))} '
               f'({_h((latest.get("source") or "").lower())})'
               if latest else "")
            + '</div></div></div>'

            '<div class="card" style="padding:18px 22px;margin-bottom:20px">'
            '<table style="width:100%"><thead>'
            '<tr><th>Window</th><th>Uptime</th><th>Heartbeats</th>'
            '<th>Downtime</th></tr></thead><tbody>'
            f'<tr><td><b>24 hours</b></td>'
            f'<td>{_format_uptime_pct(s24)}</td>'
            f'<td>{_h(s24.get("samples", 0))}</td>'
            f'<td>{_h(_humanize_duration(s24.get("downtime_seconds", 0))) if s24.get("has_data") else "&mdash;"}</td></tr>'
            f'<tr><td><b>7 days</b></td>'
            f'<td>{_format_uptime_pct(s7d)}</td>'
            f'<td>{_h(s7d.get("samples", 0))}</td>'
            f'<td>{_h(_humanize_duration(s7d.get("downtime_seconds", 0))) if s7d.get("has_data") else "&mdash;"}</td></tr>'
            f'<tr><td><b>30 days</b></td>'
            f'<td>{_format_uptime_pct(s30)}</td>'
            f'<td>{_h(s30.get("samples", 0))}</td>'
            f'<td>{_h(_humanize_duration(s30.get("downtime_seconds", 0))) if s30.get("has_data") else "&mdash;"}</td></tr>'
            '</tbody></table></div>'

            f'<div class="card" style="padding:14px 22px;margin-bottom:20px">'
            f'{last_incident_html}</div>'

            f'{incidents_html}'

            '<p class="dim" style="margin-top:30px;font-size:12px">'
            'Uptime is derived from heartbeat density: each platform ping or '
            'health check inserts one row, and gaps over 5 minutes are counted '
            'as downtime. Raw data at '
            f'<a href="{url_for("api_status_json")}">/api/status</a>.</p>'
        )
        html = _layout("Status", body, active="status")
        resp = make_response(html)
        # Auto-refresh: the page is intentionally a low-traffic informational
        # surface; refreshing every 60s keeps the number live without
        # JavaScript polling.
        resp.headers["Refresh"] = "60"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/status")
    def api_status_json():
        """JSON shape of the public status page — for external monitors
        and dashboards that want the raw uptime numbers."""
        from mediahub.observability import uptime as _uptime
        return jsonify({
            "ok": True,
            "version": APP_VERSION,
            "latest_heartbeat": _uptime.latest_heartbeat(),
            "windows": {
                "24h":  _uptime.uptime_stats(window_hours=24),
                "7d":   _uptime.uptime_stats(window_hours=24 * 7),
                "30d":  _uptime.uptime_stats(window_hours=24 * 30),
            },
            "recent_gaps": _uptime.recent_gaps(window_hours=24 * 30, limit=10),
        })

    # ---- /healthz/usage ------------------------------------------------
    #
    # Operator-facing LLM usage dashboard. Lives under /healthz/* (same
    # trust boundary as /healthz/deps — an operations endpoint, not a
    # user-facing surface) so it's reachable without going through the
    # org-setup gate. Single-instance operators see their own usage;
    # there is no tenant aggregation because each MediaHub deployment
    # belongs to one operator.
    #
    # Surfaces:
    #   1. Today's LLM call count, broken down by provider.
    #   2. Rough USD cost estimate from public list pricing.
    #   3. Gemini free-tier headroom (1,500 req/day ceiling).
    #   4. Most recent LLM error message (so the operator can diagnose
    #      a quietly-failing provider without grepping logs).
    #   5. 7-day posting-log roll-up.
    @app.route("/healthz/usage")
    def healthz_usage():
        from mediahub.observability import llm_usage as _u
        today = _u.usage_for_window(window_hours=24)
        seven_d = _u.usage_for_window(window_hours=24 * 7)
        thirty_d = _u.daily_usage(days=30)
        last_err = _u.last_error()

        # Per-provider rows for the "Today" card.
        if today["by_provider"]:
            prov_rows = ""
            for b in today["by_provider"]:
                cost_disp = f"${b['est_cost_usd']:.4f}"
                if b["provider"] == "gemini" and b["est_cost_usd"] == 0:
                    cost_disp = "$0.00 (free tier)"
                prov_rows += (
                    f'<tr><td><b>{_h(b["provider"])}</b></td>'
                    f'<td>{_h(b["calls"])}</td>'
                    f'<td>{_h(b["ok"])}</td>'
                    f'<td>{_h(b["failed"])}</td>'
                    f'<td>{_h(b.get("tokens_in", 0))}</td>'
                    f'<td>{_h(b.get("tokens_out", 0))}</td>'
                    f'<td>{_h(cost_disp)}</td></tr>'
                )
            providers_html = (
                '<div class="card"><table style="width:100%">'
                '<thead><tr><th>Provider</th><th>Calls</th><th>OK</th>'
                '<th>Failed</th><th>Tokens in</th><th>Tokens out</th>'
                '<th>Est. cost</th></tr></thead>'
                f'<tbody>{prov_rows}</tbody></table></div>'
            )
        else:
            providers_html = (
                '<div class="card empty">No LLM calls in the last 24 hours.</div>'
            )

        # Gemini free-tier headroom callout.
        if today["gemini_free_tier_headroom"] is not None:
            from mediahub.observability.llm_usage import GEMINI_FREE_TIER_DAILY_REQ
            headroom = today["gemini_free_tier_headroom"]
            used = GEMINI_FREE_TIER_DAILY_REQ - headroom
            pct = (used / GEMINI_FREE_TIER_DAILY_REQ) * 100.0 if GEMINI_FREE_TIER_DAILY_REQ else 0
            bar_color = "#2cc97f"
            if pct > 80:
                bar_color = "#ffaa3a"
            if pct >= 100:
                bar_color = "#ff5d6c"
            headroom_html = (
                '<div class="card" style="padding:16px 22px;margin-bottom:18px">'
                '<div style="display:flex;justify-content:space-between;'
                'align-items:baseline;margin-bottom:6px">'
                f'<div><b>Gemini free-tier today</b> &mdash; '
                f'{_h(used)} / {GEMINI_FREE_TIER_DAILY_REQ} calls</div>'
                f'<div class="dim" style="font-size:12px">{_h(headroom)} remaining</div>'
                '</div>'
                '<div style="height:10px;background:rgba(255,255,255,0.08);'
                'border-radius:6px;overflow:hidden">'
                f'<div style="height:100%;width:{min(pct,100):.1f}%;'
                f'background:{bar_color}"></div></div>'
                '</div>'
            )
        else:
            headroom_html = ""

        # Most recent LLM error (if any) — surfaced front and centre.
        if last_err:
            err_html = (
                '<div class="card" style="padding:16px 22px;margin-bottom:18px;'
                'border-left:3px solid #ff5d6c">'
                f'<div style="font-weight:600;margin-bottom:4px">'
                f'Last LLM error &mdash; {_h(last_err.get("provider", "unknown"))}</div>'
                f'<div class="dim" style="font-size:12px;margin-bottom:6px">'
                f'{_h(last_err.get("ts", "")[:19])} UTC'
                + (f' &middot; {_h(last_err.get("error_kind"))}' if last_err.get("error_kind") else "")
                + '</div>'
                f'<code style="font-size:12px">'
                f'{_h(last_err.get("error_message", "")[:300])}</code>'
                '</div>'
            )
        else:
            err_html = ""

        # 7-day posting log roll-up.
        try:
            from mediahub.publishing import posting_log as _plog
            # We don't have a profile-scoped count here because /healthz/usage
            # is operator-facing across all tenants on this instance. For a
            # single-org deploy that's the right answer. For a future
            # multi-tenant deploy, expand into per-tenant rows.
            conn = sqlite3.connect(str(_plog.DB_PATH))
            cur = conn.execute(
                "SELECT status, COUNT(*) AS n FROM posting_attempts "
                "WHERE attempted_at >= datetime('now', '-7 days') "
                "GROUP BY status"
            )
            counts = {r[0]: int(r[1]) for r in cur.fetchall()}
            conn.close()
        except Exception:
            counts = {}
        post_ok = int(counts.get("ok", 0))
        post_fail = int(counts.get("failed", 0))
        post_total = post_ok + post_fail
        post_html = (
            '<div class="card" style="padding:16px 22px;margin-bottom:18px">'
            f'<div style="font-weight:600;margin-bottom:6px">'
            f'Publishing (7d) &mdash; {post_total} attempts</div>'
            f'<div style="display:flex;gap:18px;font-size:13px">'
            f'<span><span class="tag good" style="font-size:11px">{post_ok} ok</span></span>'
            f'<span><span class="tag bad" style="font-size:11px">{post_fail} failed</span></span>'
            '</div></div>'
        )

        # 30-day daily breakdown.
        if thirty_d:
            day_rows = ""
            for d in reversed(thirty_d):
                cost = f"${d['est_cost_usd']:.4f}" if d["est_cost_usd"] else "$0.00"
                day_rows += (
                    f'<tr><td class="muted" style="font-size:12px">{_h(d["date"])}</td>'
                    f'<td>{_h(d["calls"])}</td>'
                    f'<td>{_h(d["ok"])}</td>'
                    f'<td>{_h(d["failed"])}</td>'
                    f'<td>{_h(cost)}</td></tr>'
                )
            thirty_html = (
                '<h2 style="margin-top:30px;margin-bottom:6px;font-size:18px">'
                'Last 30 days</h2>'
                '<p class="dim" style="margin-bottom:14px;font-size:13px">'
                'Per-day LLM call counts. Estimated cost uses public list '
                'pricing &mdash; not a billing source of truth.</p>'
                '<div class="card"><table style="width:100%">'
                '<thead><tr><th>Date (UTC)</th><th>Calls</th><th>OK</th>'
                '<th>Failed</th><th>Est. cost</th></tr></thead>'
                f'<tbody>{day_rows}</tbody></table></div>'
            )
        else:
            thirty_html = ""

        # 7-day totals headline.
        seven_total = seven_d["total_calls"]
        seven_cost = seven_d["est_cost_usd_total"]
        body = (
            '<h1 style="margin-bottom:6px">Usage</h1>'
            '<p class="dim" style="margin-bottom:24px">Operator dashboard. '
            'LLM call counts, free-tier headroom, recent provider errors, '
            'and publishing roll-up for this MediaHub deployment.</p>'

            f'{err_html}'
            f'{headroom_html}'
            f'{post_html}'

            '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
            'Today (last 24h)</h2>'
            '<p class="dim" style="margin-bottom:14px;font-size:13px">'
            f'{_h(today["total_calls"])} calls &middot; '
            f'<b>${today["est_cost_usd_total"]:.4f}</b> estimated cost &middot; '
            f'{_h(today["failed_count"])} failed'
            '</p>'
            f'{providers_html}'

            '<h2 style="margin-top:28px;margin-bottom:6px;font-size:18px">'
            'Last 7 days</h2>'
            '<p class="dim" style="margin-bottom:14px;font-size:13px">'
            f'{_h(seven_total)} calls &middot; '
            f'<b>${seven_cost:.4f}</b> estimated cost.</p>'

            f'{thirty_html}'

            '<p class="dim" style="margin-top:30px;font-size:12px">'
            'Estimated cost is derived from published list pricing for each '
            'provider and is not a substitute for a real billing source. '
            'Gemini free tier (1,500 req/day on gemini-2.5-flash) is treated '
            'as $0; Anthropic input/output tokens use Sonnet midpoint rates.</p>'
        )
        return _layout("Usage", body, active="usage")
    #
    # The settings page used to collect operator credentials (AI API
    # keys, Buffer access token, cutout provider, LLM preference). All
    # of these are now exclusively env-var configured at deploy time —
    # see `.env.example` for the full list. The user-visible product
    # has zero configuration surface; the operator sets env vars on
    # their host once and never again.
    #
    # Old bookmarks redirect to home so they don't 404.
    @app.route("/settings")
    def settings_page():
        return redirect(url_for("home"))

    # ---- /api/settings/llm-status ----
    #
    # Kept as a stable read-only status endpoint so the captions UI
    # JavaScript can still colour the AI-tab dot. Operator config
    # happens at deploy time; this endpoint just reports "is AI live
    # right now or are we in heuristic mode".
    @app.route("/api/settings/llm-status")
    def api_llm_status():
        try:
            from mediahub.media_ai.llm import is_available as _llm_available, active_provider
        except Exception:
            return jsonify({"live": False, "provider": None, "provider_label": None})
        provider = active_provider()
        live = _llm_available()
        # Public, stable provider names — gemini (default/free) and
        # anthropic (paid, operator-set). Anything else returns None.
        public_provider = {
            "gemini-api":    "gemini",
            "anthropic-api": "anthropic",
        }.get(provider) if live else None
        provider_label = {
            "gemini-api":    "Google Gemini",
            "anthropic-api": "Anthropic (Claude)",
        }.get(provider) if live else None
        return jsonify({
            "live": live,
            "provider": public_provider,
            "provider_label": provider_label,
        })

    # ---- Buffer publishing -------------------------------------------
    #
    # Multi-tenant publishing model (post-rewrite):
    #
    #   1. **Per-profile Buffer token** — each ClubProfile carries its
    #      own optional `buffer_access_token`. Set via /api/organisation/
    #      connect-buffer (inline in the publishing flow, no settings
    #      page). This is the safe multi-tenant pattern: each club
    #      authenticates with their own Buffer account; content never
    #      flows through a shared account.
    #
    #   2. **Env-var fallback** — `BUFFER_ACCESS_TOKEN` env var is
    #      consulted only when the active profile has no token. This
    #      stays as a convenience for single-tenant self-hosted
    #      deployments where operator IS the user (one club running
    #      MediaHub on their own infra). It is NOT the multi-tenant
    #      story.
    #
    #   3. **No-Buffer path** — clubs that don't have Buffer can fall
    #      through to /api/runs/<run>/card/<id>/download which packages
    #      the caption + visual as a ZIP for manual posting.
    #
    # This resolver picks 1 → 2 in priority order. Returns "" when no
    # token is reachable for the active org; callers surface the
    # connect-or-download choice.
    def _resolve_buffer_token() -> str:
        prof = _active_profile()
        if prof is not None:
            tok = (getattr(prof, "buffer_access_token", "") or "").strip()
            if tok:
                return tok
        # Env fallback for single-tenant self-hosted operators.
        from mediahub.web.secrets_store import get_buffer_access_token
        return (get_buffer_access_token() or "").strip()

    @app.route("/api/buffer/channels")
    def api_buffer_channels():
        """List the user's connected Buffer channels.

        Returns 401 when neither the active profile nor the env var
        has a token, so the UI can show the inline Connect Buffer +
        Copy/Download alternative instead of opening the schedule modal.
        """
        from mediahub.publishing.buffer import (
            list_channels as _buf_list,
            BufferAuthError, BufferAPIError,
        )
        token = _resolve_buffer_token()
        if not token:
            return jsonify({
                "connected": False,
                "channels": [],
                "error": "no_token",
                "message": (
                    "Buffer isn't connected for this organisation. Paste "
                    "your Buffer access token to enable scheduling, or "
                    "use the download option to post manually."
                ),
                "connect_url": url_for("api_connect_buffer"),
            }), 401
        try:
            channels = _buf_list(token)
        except BufferAuthError as exc:
            return jsonify({
                "connected": False,
                "channels": [],
                "error": "auth",
                "message": str(exc),
            }), 401
        except BufferAPIError as exc:
            return jsonify({
                "connected": True,
                "channels": [],
                "error": "api",
                "message": str(exc),
            }), 502
        return jsonify({
            "connected": True,
            "channels": channels,
            "count": len(channels),
        })

    @app.route("/api/organisation/connect-buffer", methods=["POST"])
    def api_connect_buffer():
        """Save a Buffer access token onto the **active organisation**.

        This is the multi-tenant-safe Buffer connection path: each club
        pastes their own personal access token, which is persisted on
        their ClubProfile (not in a shared env var, not in a shared
        secrets file). Their content then flows through THEIR Buffer
        account, never a shared operator account.

        The token is validated by attempting a `list_channels` probe
        before saving — a token that Buffer rejects is not persisted,
        so the user gets immediate feedback rather than a silent fail
        at schedule time.

        POST body (form or JSON):
            { "buffer_access_token": "1/..." }

        Returns 200 on success with the connected channel count, or
        4xx on validation / auth failures.
        """
        prof = _active_profile()
        if prof is None:
            return jsonify({
                "ok": False,
                "error": "no_active_profile",
                "message": "Set up your organisation before connecting Buffer.",
            }), 409
        # Accept both form-data and JSON for browser-form + fetch use.
        token = ""
        if request.is_json:
            body = request.get_json(silent=True) or {}
            token = str(body.get("buffer_access_token") or "").strip()
        if not token:
            token = (request.form.get("buffer_access_token") or "").strip()
        if not token:
            return jsonify({
                "ok": False,
                "error": "missing_token",
                "message": "Paste your Buffer access token to connect.",
            }), 400
        if len(token) < 10:
            return jsonify({
                "ok": False,
                "error": "short_token",
                "message": "That doesn't look like a Buffer access token (too short).",
            }), 400

        # Validate by probing Buffer for the connected channels. If Buffer
        # rejects the token we never persist it.
        from mediahub.publishing.buffer import (
            list_channels as _buf_list,
            BufferAuthError, BufferAPIError,
        )
        try:
            channels = _buf_list(token)
        except BufferAuthError as exc:
            return jsonify({
                "ok": False,
                "error": "auth",
                "message": str(exc),
            }), 401
        except BufferAPIError as exc:
            return jsonify({
                "ok": False,
                "error": "api",
                "message": str(exc),
            }), 502

        # Persist on the profile.
        prof.buffer_access_token = token
        save_profile(prof)
        return jsonify({
            "ok": True,
            "channel_count": len(channels),
            "profile_id": prof.profile_id,
        })

    @app.route("/api/organisation/disconnect-buffer", methods=["POST"])
    def api_disconnect_buffer():
        """Clear the Buffer access token on the active organisation."""
        prof = _active_profile()
        if prof is None:
            return jsonify({"ok": False, "error": "no_active_profile"}), 409
        prof.buffer_access_token = ""
        save_profile(prof)
        return jsonify({"ok": True})

    @app.route(
        "/api/runs/<run_id>/card/<path:card_id>/download",
        methods=["GET"],
    )
    def api_card_download(run_id, card_id):
        """Download a card's caption + visual as a ZIP for manual posting.

        The Buffer-free path: clubs that don't have Buffer (or don't
        want to use it) can grab a ZIP containing the caption text
        and the generated visual, then post manually to whatever
        platform they like. This is the always-safe option — no
        third-party API touched, no TOS to violate, no scheduler
        dependency.
        """
        from flask import send_file
        import io
        import zipfile

        run_data = _load_run(run_id)
        if run_data is None:
            return jsonify({"error": "run_not_found"}), 404

        # Find the achievement / card.
        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        target = None
        for ra in ranked:
            ach = ra.get("achievement") or {}
            if ach.get("swim_id") == card_id or ra.get("id") == card_id:
                target = ra
                break
        if target is None:
            for c in (run_data.get("cards") or []):
                if c.get("swim_id") == card_id or c.get("id") == card_id:
                    target = {"achievement": c}
                    break
        if target is None:
            return jsonify({"error": "card_not_found"}), 404

        ach = target.get("achievement") or {}
        swimmer = (ach.get("swimmer_name") or "swimmer").strip()
        event = (ach.get("event") or "").strip()
        slug = re.sub(r"[^A-Za-z0-9]+", "-",
                      f"{swimmer} {event}").strip("-").lower() or "card"

        # Caption text from the caller (preferred — preserves edits)
        # or fall back to the achievement headline.
        caption = (request.args.get("caption") or
                   ach.get("headline") or
                   f"{swimmer} — {event}").strip()

        # Try to locate the rendered PNG for this card. Best-effort:
        # not every card has a generated visual yet.
        png_bytes: Optional[bytes] = None
        png_name = ""
        try:
            visuals = (target.get("visuals") or
                       (ach.get("visuals") if isinstance(ach, dict) else None) or [])
            for v in visuals:
                fp = v.get("file_path") or v.get("path") or ""
                if fp and Path(fp).exists():
                    png_bytes = Path(fp).read_bytes()
                    png_name = Path(fp).name
                    break
        except Exception:
            png_bytes = None

        # Build the ZIP in memory.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{slug}-caption.txt", caption)
            if png_bytes:
                zf.writestr(png_name or f"{slug}.png", png_bytes)
            zf.writestr("README.txt", (
                "MediaHub card export.\n\n"
                "- The .txt file contains the ready-to-post caption.\n"
                "- The .png (if present) is the branded visual; if not,\n"
                "  open the card in the content pack and click 'Create\n"
                "  graphic' first.\n\n"
                "Post the visual + caption to your chosen platform\n"
                "manually. No Buffer / third-party scheduler required.\n"
            ))
        buf.seek(0)
        return send_file(
            buf, mimetype="application/zip",
            as_attachment=True,
            download_name=f"{slug}.zip",
        )

    @app.route(
        "/api/runs/<run_id>/card/<path:card_id>/schedule",
        methods=["POST"],
    )
    def api_card_schedule(run_id, card_id):
        """Schedule a card to one or more Buffer channels.

        Body JSON:
            {
              "channel_ids":  ["...", ...],   # required, non-empty
              "scheduled_at": "2026-06-01T10:00:00Z" | null,
              "caption":      "the edited caption text",
              "media_url":    "https://..." | null
            }

        Returns 200 with the per-channel results on success, 4xx on bad
        input / missing token, 502 if Buffer rejects the call. The
        user's edited caption is echoed back in `caption` so the UI
        can preserve it even after a failure.
        """
        from mediahub.publishing.buffer import (
            schedule_post as _buf_schedule,
            BufferAuthError, BufferAPIError, BufferRateLimitError,
        )
        from mediahub.publishing import posting_log as _plog

        payload = request.get_json(silent=True) or {}
        channel_ids = payload.get("channel_ids") or []
        if not isinstance(channel_ids, list) or not channel_ids:
            return jsonify({
                "ok": False,
                "error": "no_channels",
                "message": "Pick at least one Buffer channel.",
                "caption": payload.get("caption", ""),
            }), 400

        caption = (payload.get("caption") or "").strip()
        if not caption:
            return jsonify({
                "ok": False,
                "error": "no_caption",
                "message": "Caption is required.",
                "caption": "",
            }), 400

        media_url = (payload.get("media_url") or "").strip()
        if media_url:
            # Defence-in-depth: only allow http/https URLs to be passed
            # through to Buffer. Anything else (file://, javascript:,
            # data:, internal ips by raw IP) is rejected up front so a
            # malicious or accidental relative-href can't reach the
            # upstream API.
            from urllib.parse import urlparse as _urlparse
            try:
                parsed = _urlparse(media_url)
            except Exception:
                parsed = None
            scheme_ok = bool(parsed) and parsed.scheme.lower() in ("http", "https")
            netloc_ok = bool(parsed) and bool((parsed.netloc or "").strip())
            if not (scheme_ok and netloc_ok):
                return jsonify({
                    "ok": False,
                    "error": "bad_media_url",
                    "message": "Media URL must be a full http/https URL.",
                    "caption": caption,
                }), 400
        media_urls = [media_url] if media_url else None

        scheduled_at_iso = (payload.get("scheduled_at") or "").strip()
        scheduled_at_dt: Optional[datetime] = None
        if scheduled_at_iso:
            try:
                normalised = scheduled_at_iso.replace("Z", "+00:00")
                scheduled_at_dt = datetime.fromisoformat(normalised)
                if scheduled_at_dt.tzinfo is None:
                    scheduled_at_dt = scheduled_at_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return jsonify({
                    "ok": False,
                    "error": "bad_time",
                    "message": "Scheduled time was not a valid ISO 8601 datetime.",
                    "caption": caption,
                }), 400

        token = _resolve_buffer_token()
        if not token:
            return jsonify({
                "ok": False,
                "error": "no_token",
                "message": (
                    "Buffer isn't connected for this organisation. Paste "
                    "your Buffer access token to enable scheduling, or "
                    "use the download option to post manually."
                ),
                "caption": caption,
                "connect_url": url_for("api_connect_buffer"),
            }), 401

        ws = _get_wf_store()
        results: list[dict] = []
        update_ids: list[str] = []
        failure: Optional[str] = None

        # Resolve profile_id so every posting-log row is scoped to the
        # right org. Prefer the run's stored profile_id; fall back to
        # the session-pinned active profile so logs aren't anonymous
        # when a run pre-dates the profile system.
        try:
            run_data = _load_run(run_id) or {}
        except Exception:
            run_data = {}
        profile_id_for_log = (
            run_data.get("profile_id")
            or (_active_profile_id() or "")
            # Sentinel so a scheduled-but-orphaned post still leaves an
            # audit trail in the posting log. Without this fallback, a
            # run with no profile_id silently no-ops the log row because
            # record_attempt rejects empty profile_id.
            or "_orphaned"
        )
        scheduled_at_iso_for_log = (
            scheduled_at_dt.isoformat() if scheduled_at_dt else None
        )

        # Pre-filter empty channel ids so they don't reach _buf_schedule
        # and produce a per-channel "channel id is required" failure.
        # Cast every value to str up front for a consistent shape.
        channel_ids = [str(c).strip() for c in channel_ids if str(c).strip()]

        for cid in channel_ids:
            try:
                res = _buf_schedule(
                    token=token,
                    channel_id=str(cid),
                    text=caption,
                    media_urls=media_urls,
                    scheduled_at=scheduled_at_dt,
                )
                results.append({
                    "channel_id": str(cid),
                    "ok": True,
                    "update_id": res.get("update_id", ""),
                })
                if res.get("update_id"):
                    update_ids.append(res["update_id"])
                _plog.record_attempt(
                    profile_id=profile_id_for_log,
                    run_id=run_id, card_id=card_id,
                    channel_id=str(cid),
                    status="ok",
                    update_id=res.get("update_id", ""),
                    caption=caption,
                    media_url=media_url or None,
                    scheduled_at=scheduled_at_iso_for_log,
                )
            except BufferAuthError as exc:
                failure = str(exc)
                results.append({
                    "channel_id": str(cid),
                    "ok": False,
                    "error": "auth",
                    "message": str(exc),
                })
                _plog.record_attempt(
                    profile_id=profile_id_for_log,
                    run_id=run_id, card_id=card_id,
                    channel_id=str(cid),
                    status="failed", error_kind="auth",
                    error_message=str(exc),
                    caption=caption,
                    media_url=media_url or None,
                    scheduled_at=scheduled_at_iso_for_log,
                )
                break  # Stop early &mdash; token is the same for every channel.
            except BufferRateLimitError as exc:
                # Rate-limit is per-account, not per-channel — once we
                # hit it for one channel we will hit it for every
                # subsequent one in the loop. Surface the retry hint
                # to the user and stop early.
                failure = str(exc)
                results.append({
                    "channel_id": str(cid),
                    "ok": False,
                    "error": "rate_limited",
                    "message": str(exc),
                    "retry_after": exc.retry_after,
                })
                _plog.record_attempt(
                    profile_id=profile_id_for_log,
                    run_id=run_id, card_id=card_id,
                    channel_id=str(cid),
                    status="failed", error_kind="rate_limited",
                    error_message=str(exc),
                    caption=caption,
                    media_url=media_url or None,
                    scheduled_at=scheduled_at_iso_for_log,
                )
                break
            except BufferAPIError as exc:
                failure = str(exc)
                results.append({
                    "channel_id": str(cid),
                    "ok": False,
                    "error": "api",
                    "message": str(exc),
                })
                _plog.record_attempt(
                    profile_id=profile_id_for_log,
                    run_id=run_id, card_id=card_id,
                    channel_id=str(cid),
                    status="failed", error_kind="api",
                    error_message=str(exc),
                    caption=caption,
                    media_url=media_url or None,
                    scheduled_at=scheduled_at_iso_for_log,
                )

        any_ok = any(r.get("ok") for r in results)
        try:
            from mediahub.workflow.status import ScheduleStatus
        except Exception:
            ScheduleStatus = None  # type: ignore

        if ws is not None and ScheduleStatus is not None:
            if any_ok and not failure:
                ws.set_schedule(
                    run_id, card_id,
                    schedule_status=ScheduleStatus.SCHEDULED,
                    buffer_update_id=";".join(update_ids) or None,
                    scheduled_at=scheduled_at_dt.isoformat() if scheduled_at_dt else None,
                    schedule_error=None,
                )
            elif any_ok and failure:
                # Partial success: at least one channel went through but
                # another failed. Record the success and surface the
                # failure to the user.
                ws.set_schedule(
                    run_id, card_id,
                    schedule_status=ScheduleStatus.SCHEDULED,
                    buffer_update_id=";".join(update_ids) or None,
                    scheduled_at=scheduled_at_dt.isoformat() if scheduled_at_dt else None,
                    schedule_error=failure,
                )
            else:
                ws.set_schedule(
                    run_id, card_id,
                    schedule_status=ScheduleStatus.FAILED,
                    buffer_update_id=None,
                    scheduled_at=None,
                    schedule_error=failure or "Scheduling failed.",
                )

        if not any_ok:
            return jsonify({
                "ok": False,
                "error": "buffer_failed",
                "message": failure or "Buffer rejected the request.",
                "results": results,
                "caption": caption,
            }), 502

        return jsonify({
            "ok": True,
            "schedule_status": "scheduled",
            "buffer_update_ids": update_ids,
            "scheduled_at": scheduled_at_dt.isoformat() if scheduled_at_dt else None,
            "results": results,
            "caption": caption,
            "warning": failure,  # non-empty if a partial failure occurred
        })

    # ------------------------------------------------------------------
    # Posting log — Phase 1.3 observability
    # ------------------------------------------------------------------
    #
    # JSON access to the same log surfaced on /activity. Useful for
    # tests and for any SPA-style UI that wants to poll for fresh
    # attempts without re-rendering the whole page. Scoped to the
    # active organisation, never returns a globally-mixed view.
    @app.route("/api/posting/log", methods=["GET"])
    def api_posting_log():
        from mediahub.publishing import posting_log as _plog
        prof = _active_profile()
        if prof is None:
            return jsonify({
                "ok": False,
                "error": "no_active_profile",
                "attempts": [],
            }), 409
        try:
            limit_raw = (request.args.get("limit") or "20").strip()
            limit = max(1, min(200, int(limit_raw)))
        except (TypeError, ValueError):
            limit = 20
        run_id = (request.args.get("run_id") or "").strip() or None
        card_id = (request.args.get("card_id") or "").strip() or None
        try:
            attempts = _plog.recent_attempts(
                prof.profile_id, limit=limit,
                run_id=run_id, card_id=card_id,
            )
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "log_unavailable",
                "message": str(exc),
                "attempts": [],
            }), 500
        return jsonify({
            "ok": True,
            "profile_id": prof.profile_id,
            "count": len(attempts),
            "attempts": attempts,
        })

    # ====================================================================
    # V7 NEW ROUTES
    # ====================================================================

    # ---- /make &mdash; content-type chooser ----------------------------------
    @app.route("/make")
    def make_page():
        try:
            from mediahub.club_platform.content_types import REGISTRY, ContentType
        except ImportError:
            return _layout("Create", '<div class="card"><p class="muted">club_platform package not available.</p></div>', active="create")

        tiles_html = ""
        for ct, meta in REGISTRY.items():
            # Defensive: a stale endpoint name in the content-type
            # registry must NEVER 500 the whole /make page. If url_for
            # raises BuildError (e.g. an endpoint was renamed and the
            # registry not updated), degrade to a disabled tile instead.
            try:
                route_url = url_for(meta.primary_route_endpoint)
                href_ok = True
            except Exception:
                log.warning(
                    "make_page: content type %r references unknown endpoint %r — "
                    "rendering as disabled tile",
                    ct, meta.primary_route_endpoint,
                )
                route_url = "#"
                href_ok = False
            if meta.is_implemented and href_ok:
                badge = '<span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:rgba(34,197,94,0.15);color:#22C55E;border:1px solid rgba(34,197,94,0.3)">ready</span>'
                action = f'href="{route_url}"'
                opacity = "1"
            else:
                badge = '<span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,0.06);color:var(--ink-muted);border:1px solid var(--border)">coming soon</span>'
                action = f'href="{route_url}"' if href_ok else 'href="#" onclick="return false"'
                opacity = "0.7"
            tiles_html += f"""
<a {action} class="make-tile" style="text-decoration:none;display:flex;flex-direction:column;gap:12px;padding:24px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);transition:border-color 150ms,box-shadow 150ms;opacity:{opacity}">
  <div style="color:var(--accent)">{meta.icon_svg}</div>
  <div style="display:flex;align-items:center;gap:10px">
    <div style="font-size:16px;font-weight:700;color:var(--ink)">{_h(meta.title)}</div>
    {badge}
  </div>
  <div style="font-size:13px;color:var(--ink-dim);line-height:1.5">{_h(meta.description)}</div>
  <div style="font-size:12px;color:var(--ink-muted);margin-top:auto">{_h(meta.input_contract[:120])}{"&hellip;" if len(meta.input_contract) > 120 else ""}</div>
</a>"""

        body = f"""
<style>
.make-tile:hover {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
</style>
<h1>What do you want to create?</h1>
<p class="dim" style="margin-bottom:28px">Choose a content type to get started.</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px">
  {tiles_html}
</div>
"""
        return _layout("Create", body, active="create")

    @app.route("/spotlight/<run_id>/<path:swimmer_key>/build", methods=["POST"])
    def spotlight_build(run_id, swimmer_key):
        """Take the achievements the user has *approved* on the spotlight
        page and turn them into a single composite post draft saved as a
        stub pack. Lets the user pick which moments go into the post by
        approving the relevant pills first."""
        try:
            from mediahub.club_platform.athlete_spotlight import build_spotlight_pack
            from mediahub.club_platform.stub_pack_store import save_pack
        except ImportError:
            return _layout("Spotlight",
                           '<div class="card"><p class="muted">club_platform not available.</p></div>',
                           active="create"), 501
        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found",
                           '<div class="empty">Run not found.</div>'), 404
        pack = build_spotlight_pack(run_data, swimmer_key)
        if not pack:
            return _layout("No data",
                           f'<div class="empty">No achievements for "{_h(swimmer_key)}".</div>'), 404

        wf_states = {}
        try:
            ws = _get_wf_store()
            if ws:
                wf_states = ws.load(run_id)
        except Exception:
            wf_states = {}

        # Filter to approved/posted; treat absence as not-selected.
        approved: list[dict] = []
        for ra in pack["ranked_achievements"]:
            a = ra.get("achievement", {})
            cid = a.get("swim_id") or f"sp:{a.get('type','')}:{a.get('event','')}"
            st = wf_states.get(cid)
            if st and getattr(getattr(st, "status", None), "value", "") in ("approved", "posted"):
                approved.append(ra)

        if not approved:
            # Fall through gracefully with a clear message — don't run the LLM
            # on an empty selection.
            body = (
                '<h1>Build spotlight post</h1>'
                '<div class="card"><p class="muted">No achievements approved yet. '
                'Click the pill on the achievements below to approve the ones '
                'you want to include, then come back here.</p>'
                f'<p><a class="btn secondary" href="{url_for("spotlight_view", run_id=run_id, swimmer_key=swimmer_key)}">&larr; Back to spotlight</a></p></div>'
            )
            return _layout("Build spotlight post", body, active="create"), 400

        # Hand the approved achievements to Claude so the model decides
        # how to weave them into one post. No hand-coded templating —
        # Claude gets the list of facts + brand context and writes the
        # composite draft. Falls back gracefully when Claude isn't
        # configured (single-shot generate with the same prompt).
        swimmer_name = pack["swimmer_name"]
        meet_name = pack["meet_name"]
        fact_list = []
        for ra in approved[:8]:
            a = ra.get("achievement", {})
            fact = {k: v for k, v in {
                "event":    a.get("event"),
                "time":     a.get("time"),
                "place":    a.get("place"),
                "headline": a.get("headline"),
                "type":     a.get("type"),
                "is_pb":    a.get("pb"),
            }.items() if v not in (None, "", [], {})}
            fact_list.append(fact)

        # English brief — no JSON envelope. Each approved moment is a
        # natural-language line the model can weave into prose.
        moment_lines: list[str] = []
        for f in fact_list:
            hl = (f.get("headline") or "").strip()
            ev = (f.get("event") or "").strip()
            tm = (f.get("time") or "").strip()
            pl = f.get("place")
            pb = "PB" if f.get("is_pb") else ""
            bits = [b for b in [ev, tm, (f"{pl}" if pl else ""), pb] if b]
            line = "; ".join(bits)
            if hl:
                line = f"{hl} ({line})" if line else hl
            if line:
                moment_lines.append(line)
        brief = (
            f"{swimmer_name} just had their day at {meet_name}. The reviewer "
            f"has hand-approved these moments for the spotlight post:\n"
            + "\n".join(f"- {l}" for l in moment_lines)
            + "\n\nWrite ONE single Instagram-ready caption: a hooky "
              "opener, a tight body weaving the approved moments together, "
              "and a closing line. Use the swimmer's first name. Don't "
              "invent facts. ~700 characters max. Output the caption only."
        )
        # Spotlight composite — pure AI, no template stitch. If the AI is
        # unavailable, render a clear "AI unavailable" page rather than
        # pretending to compose a post out of bullet points.
        from mediahub.ai_core import (
            ask, ProviderNotConfigured, ProviderError,
        )
        try:
            composed_caption = (ask(
                "You are MediaHub's spotlight-post writer. Output only the "
                "caption text, no preamble or markdown.",
                brief,
                max_tokens=600,
            ) or "").strip()
        except ProviderNotConfigured as e:
            err_html = (
                '<div class="card" style="border-color:rgba(244,63,94,0.4)">'
                '<h2 style="margin-top:0">AI features unavailable</h2>'
                f'<p>Spotlight posts require AI. {_h(str(e))}</p>'
                '<p class="muted">Contact your administrator to enable AI on '
                'this deployment.</p>'
                '</div>'
            )
            return _layout("Build spotlight post", err_html, active="create"), 503
        except ProviderError as e:
            err_html = (
                '<div class="card" style="border-color:rgba(244,63,94,0.4)">'
                '<h2 style="margin-top:0">AI provider error</h2>'
                f'<p>The AI provider couldn\'t finish the spotlight draft: '
                f'<code>{_h(str(e))}</code>.</p>'
                '<p class="muted">Try again in a moment (rate limits typically '
                'clear within seconds).</p>'
                '</div>'
            )
            return _layout("Build spotlight post", err_html, active="create"), 502
        if not composed_caption:
            err_html = (
                '<div class="card" style="border-color:rgba(244,63,94,0.4)">'
                '<h2 style="margin-top:0">AI returned no caption</h2>'
                '<p>The provider responded but produced an empty caption. '
                'Try regenerating.</p>'
                '</div>'
            )
            return _layout("Build spotlight post", err_html, active="create"), 502

        card = {
            "platform":   "Instagram",
            "caption":    composed_caption,
            "hashtags":   ["#spotlight", "#swimming"],
            "confidence": 0.9,
            "notes":      f"Composed from {len(approved)} approved achievement(s) for {swimmer_name}.",
            "status":     "queue",
        }
        saved = save_pack(
            "free_text",  # reuses the stub-pack list; tagged in form_data
            {"free_text":    f"Spotlight — {swimmer_name}",
             "source":       "athlete_spotlight",
             "swimmer_name": swimmer_name,
             "meet_name":    meet_name,
             "run_id":       run_id,
             "swimmer_key":  swimmer_key,
             "n_approved":   len(approved)},
            [card],
        )
        return redirect(url_for("stub_pack_view", pack_id=saved["pack_id"]))

    # ---- /spotlight &mdash; Athlete Spotlight landing ------------------------
    @app.route("/spotlight")
    def spotlight_landing():
        try:
            from mediahub.club_platform.athlete_spotlight import list_swimmers_in_run
        except ImportError:
            return _layout("Athlete Spotlight", '<div class="card"><p class="muted">club_platform not available.</p></div>', active="create")

        # List recent runs that have a recognition report
        conn = _db()
        recent_runs = conn.execute(
            "SELECT id, meet_name, file_name, created_at FROM runs WHERE status='done' ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        conn.close()

        run_id_param = request.args.get("run_id", "")

        # Empty state when no meets have been processed yet
        if not recent_runs:
            empty_body = f"""
<h1>Athlete Spotlight</h1>
<p class="dim">Generate a single-athlete content pack from a processed meet.</p>
<div class="card">
  <h2>No meets yet</h2>
  <p>You'll need to upload a meet results file before you can spotlight a swimmer.
  Once a meet is processed, every swimmer in your club will be available here.</p>
  <a class="btn" href="{url_for('upload')}" style="margin-top:14px">Upload a meet &rarr;</a>
</div>"""
            return _layout("Athlete Spotlight", empty_body, active="create")

        runs_opts = '<option value="">Select a meet&hellip;</option>'
        for r in recent_runs:
            sel = 'selected' if r["id"] == run_id_param else ''
            label = _h(r["meet_name"] or r["file_name"] or r["id"])
            runs_opts += f'<option value="{_h(r["id"])}" {sel}>{label}</option>'

        swimmers_html = ""
        if run_id_param:
            run_data = _load_run(run_id_param)
            if run_data:
                swimmers = list_swimmers_in_run(run_data)
                if swimmers:
                    _review_url = url_for("review", run_id=run_id_param)
                    swimmers_html = f'<div style="margin-top:20px"><h2>Swimmers in this meet <span class="muted" style="font-weight:400;font-size:13px">({len(swimmers)})</span></h2>'
                    swimmers_html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:12px">'
                    for sw in swimmers:
                        sp_url = url_for("spotlight_view", run_id=run_id_param, swimmer_key=sw["swimmer_key"])
                        swimmers_html += f"""
<a href="{sp_url}" style="display:flex;flex-direction:column;gap:6px;padding:14px;background:var(--panel2);border:1px solid var(--border);border-radius:var(--radius-sm);text-decoration:none;transition:border-color 150ms">
  <div style="font-size:14px;font-weight:600;color:var(--ink)">{_h(sw["swimmer_name"])}</div>
  <div style="font-size:12px;color:var(--ink-dim)">{sw["n_achievements"]} achievement{"s" if sw["n_achievements"] != 1 else ""}</div>
</a>"""
                    swimmers_html += '</div></div>'
                else:
                    swimmers_html = '<div class="card"><p class="muted">No achievements found for this run. The recognition report may not be available.</p></div>'

        change_js = url_for("spotlight_landing")
        body = f"""
<h1>Athlete Spotlight</h1>
<p class="dim">Pick a meet, then pick a swimmer to generate a single-athlete content pack.</p>

<div class="card">
  <h2>Choose a meet</h2>
  <form method="get" action="{url_for('spotlight_landing')}">
    <select name="run_id" onchange="this.form.submit()" style="max-width:480px">
      {runs_opts}
    </select>
    <noscript><button class="btn" type="submit" style="margin-top:10px">Load swimmers &rarr;</button></noscript>
  </form>
  {swimmers_html}
</div>
"""
        return _layout("Athlete Spotlight", body, active="create")

    # ---- /spotlight/<run_id>/<swimmer_key> &mdash; spotlight view -------------
    @app.route("/spotlight/<run_id>/<path:swimmer_key>")
    def spotlight_view(run_id, swimmer_key):
        try:
            from mediahub.club_platform.athlete_spotlight import build_spotlight_pack
        except ImportError:
            return _layout("Spotlight", '<div class="card"><p class="muted">club_platform not available.</p></div>', active="create"), 501

        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        pack = build_spotlight_pack(run_data, swimmer_key)
        if not pack:
            return _layout("No data", f'<div class="empty">No achievements found for swimmer key "{_h(swimmer_key)}" in this run.</div>'), 404

        _back_url = url_for("spotlight_landing") + f"?run_id={run_id}"
        _review_url = url_for("review", run_id=run_id)
        _pack_url = url_for("content_pack", run_id=run_id)
        _wf_api_base = url_for('api_workflow_set', run_id=run_id, card_id='CARD_ID').replace('CARD_ID', '')
        import json as _json
        _wf_api_base_js = _json.dumps(_wf_api_base)

        # Load workflow state for this run so spotlight cards reflect current status.
        wf_states = {}
        try:
            ws = _get_wf_store()
            if ws:
                wf_states = ws.load(run_id)
        except Exception:
            wf_states = {}

        # Render achievements with full workflow controls.
        WF_PILL_STYLES = {
            "queue":    ("rgba(255,255,255,0.06)", "var(--ink-muted)"),
            "approved": ("rgba(34,197,94,0.15)", "#22C55E"),
            "rejected": ("rgba(244,63,94,0.15)", "#F43F5E"),
            "posted":   ("rgba(34,211,238,0.15)", "var(--accent)"),
            "edited":   ("rgba(245,158,11,0.15)", "var(--warn)"),
        }

        rows_html = ""
        for ra in pack["ranked_achievements"]:
            a = ra.get("achievement", {})
            band = ra.get("quality_band", "nice")
            prio = ra.get("priority", 0.0)
            rank = ra.get("rank", 0)
            band_cls = {"elite": "warn", "strong": "info", "story": "", "nice": "", "not_worthy": "bad"}.get(band, "")
            headline = _h(a.get("headline", ""))
            angle = _h(_humanise(a.get("angle_hint", "") or ""))
            event = _h(a.get("event", ""))
            atype = _h(_humanise(a.get("type", "")))
            card_id_raw = a.get("swim_id") or f"sp:{a.get('type','')}:{a.get('event','')}"
            card_id_safe = _h(card_id_raw)

            # Workflow status
            wf = wf_states.get(card_id_raw)
            wf_status = wf.status.value if wf else "queue"
            s_bg, s_fg = WF_PILL_STYLES.get(wf_status, WF_PILL_STYLES["queue"])

            # Caption text for copy
            cap_text = headline
            if angle:
                cap_text = f"{headline}\\n\\n{angle}"
            cap_text_safe = cap_text.replace('"', '&quot;')

            rows_html += f"""
<div class="sp-row" data-card="{card_id_safe}" style="padding:14px 0;border-bottom:1px solid var(--border);display:flex;gap:14px;align-items:flex-start">
  <div style="min-width:28px;text-align:center;color:var(--ink-muted);font-size:13px">#{rank}</div>
  <div style="flex:1">
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap">
      <span class="tag {band_cls}" style="font-size:10px">{band.upper()}</span>
      <span class="tag info" style="font-size:10px">{atype}</span>
      <span class="muted" style="font-size:11px">{prio:.2f}</span>
      <button class="sp-pill wf-pill" data-run="{_h(run_id)}" data-card="{card_id_safe}" data-status="{wf_status}"
        style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:{s_bg};color:{s_fg};font-family:inherit"
        title="Click: queue &rarr; approved &rarr; posted. Right-click for more options.">{wf_status}</button>
    </div>
    <div style="font-size:14px;font-weight:600;color:var(--ink)">{event}</div>
    <div style="font-size:13px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
      <button class="btn secondary" style="font-size:11px;padding:4px 10px" onclick="copySpotlightCaption(this, '{card_id_safe}')">Copy caption</button>
      <span id="sp-cap-{card_id_safe}" style="display:none">{cap_text}</span>
    </div>
  </div>
</div>"""

        body = f"""
<p class="dim"><a href="{_back_url}">&larr; Back to swimmer list</a> &middot; <a href="{_review_url}">Full meet review</a></p>
<h1>Spotlight: {_h(pack["swimmer_name"])}</h1>
<p class="dim">{_h(pack["meet_name"])}</p>

<div class="card">
  <div class="stat-block">
    <div class="stat"><div class="l" style="color:#F59E0B">Elite</div><div class="v" style="color:#F59E0B">{pack["n_elite"]}</div></div>
    <div class="stat"><div class="l" style="color:#22D3EE">Strong</div><div class="v" style="color:#22D3EE">{pack["n_strong"]}</div></div>
    <div class="stat"><div class="l" style="color:#A78BFA">Story</div><div class="v" style="color:#A78BFA">{pack["n_story"]}</div></div>
    <div class="stat"><div class="l">Total</div><div class="v">{pack["n_achievements"]}</div></div>
  </div>
  <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
    <a class="btn secondary" href="{_pack_url}" style="font-size:13px">Open content pack &rarr;</a>
    <form method="post" action="{url_for('spotlight_build', run_id=run_id, swimmer_key=swimmer_key)}" style="display:inline">
      <button type="submit" class="btn" style="font-size:13px">Build spotlight post from approved cards &rarr;</button>
    </form>
    <span class="muted" style="font-size:12px">Approve the achievements below to choose which go into the post.</span>
  </div>
</div>

<div class="card">
  <h2>Achievements</h2>
  {rows_html or '<p class="muted">No achievements.</p>'}
</div>

<script>
const SP_WF_API_BASE = {_wf_api_base_js};
const SP_WF_CYCLE = ['queue','approved','posted'];
const SP_WF_COLOURS = {{
  queue:    ['rgba(255,255,255,0.06)','var(--ink-muted)'],
  approved: ['rgba(34,197,94,0.15)','#22C55E'],
  rejected: ['rgba(244,63,94,0.15)','#F43F5E'],
  posted:   ['rgba(34,211,238,0.15)','var(--accent)'],
  edited:   ['rgba(245,158,11,0.15)','var(--warn)'],
}};
function _spApply(btn, next) {{
  var cur = btn.dataset.status || 'queue';
  var cardId = btn.dataset.card;
  btn.textContent = next;
  btn.dataset.status = next;
  var cols = SP_WF_COLOURS[next] || SP_WF_COLOURS.queue;
  btn.style.background = cols[0];
  btn.style.color = cols[1];
  var url = SP_WF_API_BASE + encodeURIComponent(cardId);
  fetch(url, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:'set_status',status:next}})}})
    .then(r=>r.json())
    .then(j=>{{ if(!j.ok){{btn.textContent=cur;btn.dataset.status=cur;}} }})
    .catch(()=>{{btn.textContent=cur;btn.dataset.status=cur;}});
}}
document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.sp-pill');
  if (!btn) return;
  var cur = btn.dataset.status || 'queue';
  var idx = SP_WF_CYCLE.indexOf(cur);
  var next = idx === -1 ? 'approved' : SP_WF_CYCLE[(idx + 1) % SP_WF_CYCLE.length];
  _spApply(btn, next);
}});
document.addEventListener('contextmenu', function(e) {{
  var btn = e.target.closest('.sp-pill');
  if (!btn) return;
  e.preventDefault();
  var cur = btn.dataset.status || 'queue';
  _spApply(btn, cur === 'rejected' ? 'queue' : 'rejected');
}});
function copySpotlightCaption(btn, cardIdSafe) {{
  var span = document.getElementById('sp-cap-' + cardIdSafe);
  if (!span) {{ btn.textContent = 'Error'; return; }}
  var text = span.textContent.trim();
  var done = function(ok) {{
    btn.textContent = ok ? 'Copied!' : 'Copy failed';
    setTimeout(function(){{ btn.textContent = 'Copy caption'; }}, 1800);
  }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{done(true);}}).catch(function(){{fb();}});
  }} else {{
    fb();
  }}
  function fb() {{
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try {{ done(document.execCommand('copy')); }} catch (e) {{ done(false); }}
    document.body.removeChild(ta);
  }}
}}
</script>
"""
        return _layout(f"Spotlight: {pack['swimmer_name']}", body, active="create")

    # ---- Stub routes (now functional with real LLM + fallback) ---------
    _STUB_TYPE_BY_CLASS = {
        "WeekendPreviewStub": "weekend_preview",
        "SponsorPostStub":    "sponsor_post",
        "SessionUpdateStub":  "session_update",
        "FreeTextStub":       "free_text",
    }

    def _render_stub(stub_cls_name: str, route_endpoint: str, title: str,
                     active_tab: str = "add_input"):
        """Shared handler for stub routes. GET renders form, POST renders cards."""
        try:
            from mediahub.club_platform import stubs as _stubs_mod
        except Exception as exc:
            body = (
                '<div class="card"><h2>Temporarily unavailable</h2>'
                f'<p class="muted">Content engine failed to load: {_h(str(exc))}</p></div>'
            )
            return _layout(title, body, active=active_tab)

        StubCls = getattr(_stubs_mod, stub_cls_name, None)
        if StubCls is None:
            body = '<div class="card"><p class="muted">This content type is not available.</p></div>'
            return _layout(title, body, active=active_tab)

        stub = StubCls()
        if request.method == "POST":
            form_data = request.form.to_dict(flat=True)
            # Photo attachment (optional) — every stub form has this field.
            # Save to DATA_DIR/uploads/stub_attachments/<uuid>.<ext> and
            # record the relative path on form_data so the saved pack carries
            # the reference forward to downstream visual generators.
            photo = request.files.get("attached_photo")
            if photo and getattr(photo, "filename", ""):
                import uuid as _uuid
                ext = Path(photo.filename).suffix.lower() or ".jpg"
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    ext = ".jpg"
                att_dir = UPLOADS_DIR / "stub_attachments"
                att_dir.mkdir(parents=True, exist_ok=True)
                dest = att_dir / f"{_uuid.uuid4().hex[:16]}{ext}"
                try:
                    photo.save(str(dest))
                    form_data["attached_photo_path"] = str(dest)
                    form_data["attached_photo_filename"] = Path(photo.filename).name
                except Exception:
                    app.logger.exception("stub photo upload failed")
            generation_error = None
            try:
                cards_payload = stub.generate_cards(form_data)
            except Exception as e:
                app.logger.exception("stub generate_cards failed")
                cards_payload = {"cards": []}
                generation_error = str(e)
                # Show the actual error to the user — no silent fake card.
                from mediahub.ai_core import (
                    ProviderNotConfigured, ProviderError,
                )
                if isinstance(e, ProviderNotConfigured):
                    err_html = (
                        '<div class="card" style="border-color:rgba(244,63,94,0.4)">'
                        '<h2 style="margin-top:0">AI features unavailable</h2>'
                        f'<p>{_h(str(e))}</p>'
                        '<p class="muted">Contact your administrator to enable '
                        'AI on this deployment.</p>'
                        '</div>'
                    )
                    return _layout(title, err_html, active=active_tab)
                if isinstance(e, ProviderError):
                    err_html = (
                        '<div class="card" style="border-color:rgba(244,63,94,0.4)">'
                        '<h2 style="margin-top:0">AI provider error</h2>'
                        f'<p>{_h(str(e))}</p>'
                        '<p class="muted">Try again in a moment (rate limits '
                        'typically clear within seconds).</p>'
                        '</div>'
                    )
                    return _layout(title, err_html, active=active_tab)
            # Persist this pack so it survives refresh + is exportable.
            saved = None
            try:
                from mediahub.club_platform.stub_pack_store import save_pack
                saved = save_pack(
                    _STUB_TYPE_BY_CLASS.get(stub_cls_name, "other"),
                    form_data,
                    cards_payload.get("cards") or [],
                )
            except Exception:
                app.logger.exception("stub save_pack failed")
            back = url_for(route_endpoint)
            actions_url = url_for("stub_pack_view", pack_id=saved["pack_id"]) if saved else None
            # Wire the per-card approval pill when we have a saved pack_id.
            _pack_id = saved["pack_id"] if saved else None
            _status_api_base = None
            if _pack_id:
                _full = url_for("api_stub_pack_card_status",
                                pack_id=_pack_id, card_idx=999999)
                _status_api_base = _full.rsplit("/", 1)[0]
            body = _stubs_mod.render_cards_html(
                cards_payload, back, f"{title} — drafts",
                pack_id=_pack_id, status_api_base=_status_api_base,
            )
            if saved:
                _packs_url = url_for("stub_packs_list")
                body = body.replace(
                    f'<a class="btn secondary" href="{_h(back)}">&larr; Start over</a>',
                    (
                        f'<a class="btn" href="{_h(actions_url)}">View & export this pack &rarr;</a>'
                        f'<a class="btn secondary" href="{_h(back)}">&larr; Start over</a>'
                        f'<a class="btn secondary" href="{_h(_packs_url)}">All saved drafts</a>'
                    ),
                    1,
                )
            return _layout(title, body, active=active_tab)
        # GET &mdash; render form
        body = stub.render_stub_html()
        try:
            _packs_url = url_for("stub_packs_list")
            body += (
                f'<p style="margin-top:16px;display:flex;gap:14px;flex-wrap:wrap">'
                f'<a href="{_packs_url}">View your saved drafts &rarr;</a>'
                f'<a href="{url_for("make_page")}">&larr; Back to Make</a>'
                f'</p>'
            )
        except Exception:
            body += f'<p style="margin-top:16px"><a href="{url_for("make_page")}">&larr; Back to Make</a></p>'
        return _layout(title, body, active=active_tab)

    @app.route("/weekend-preview", methods=["GET", "POST"])
    def stub_weekend_preview():
        return _render_stub("WeekendPreviewStub", "stub_weekend_preview", "Event Preview")

    @app.route("/sponsor-post", methods=["GET", "POST"])
    def stub_sponsor_post():
        return _render_stub("SponsorPostStub", "stub_sponsor_post", "Sponsor Post")

    @app.route("/session-update", methods=["GET", "POST"])
    def stub_session_update():
        return _render_stub("SessionUpdateStub", "stub_session_update", "Session Update")

    @app.route("/free-text/quick", methods=["GET", "POST"])
    def stub_free_text_quick():
        # One-shot single-textarea form (legacy). Kept under /quick because
        # the primary /free-text experience is now the iterative chat.
        return _render_stub("FreeTextStub", "stub_free_text_quick", "Free Text (quick)")

    # ---- /free-text — Claude-driven chat brief builder -----------------------
    @app.route("/free-text", methods=["GET"])
    def free_text_chat_page():
        from mediahub.free_text_chat.session import list_sessions
        sessions = list_sessions(limit=20)
        rows_html = ""
        for it in sessions:
            view_url = url_for("free_text_chat_view", chat_id=it["chat_id"])
            ts = (it.get("updated_at") or "")[:19].replace("T", " ")
            badge = ('<span class="tag good" style="font-size:10px">brief accepted</span>'
                     if it.get("accepted") else
                     '<span class="tag" style="font-size:10px">draft</span>')
            rows_html += (
                f'<tr><td><a href="{view_url}">{_h(it.get("title") or "Untitled chat")}</a></td>'
                f'<td>{badge}</td>'
                f'<td>{it.get("n_messages", 0)}</td>'
                f'<td class="muted">{_h(ts)}</td></tr>'
            )
        new_url = url_for("free_text_chat_new")
        body = f"""
<h1>Free text — chat</h1>
<p class="dim" style="max-width:680px">
  Talk to Claude. Describe what you want to post, answer the assistant's
  questions, and approve the brief when it's right. The assistant
  researches the web on its own — names, venues, PBs, sponsor info — so
  the brief is grounded in evidence, not invented.
</p>

<form method="post" action="{new_url}" style="margin-top:14px">
  <button type="submit" class="btn">Start a new chat →</button>
</form>

<div class="card" style="margin-top:24px">
  <h2 style="margin-top:0">Past chats</h2>
  {('<table><thead><tr><th>Title</th><th>State</th><th>Messages</th>'
    '<th>Updated</th></tr></thead><tbody>' + rows_html + '</tbody></table>')
   if rows_html else '<p class="muted">No chats yet.</p>'}
</div>

<p style="margin-top:18px;font-size:12px;color:var(--ink-muted)">
  Prefer the one-shot form? <a href="{url_for('stub_free_text_quick')}">Use the legacy quick generator →</a>
</p>
"""
        return _layout("Free text — chat", body, active="add_input")

    @app.route("/free-text/chat/new", methods=["POST"])
    def free_text_chat_new():
        from mediahub.free_text_chat.session import create_session
        s = create_session()
        return redirect(url_for("free_text_chat_view", chat_id=s.chat_id))

    @app.route("/free-text/chat/<chat_id>", methods=["GET"])
    def free_text_chat_view(chat_id):
        from mediahub.free_text_chat.session import load_session
        s = load_session(chat_id)
        if not s:
            return _layout("Chat not found",
                           '<div class="empty">Chat not found.</div>',
                           active="add_input"), 404
        # Pre-render messages for the initial paint; JS keeps it live.
        msgs_html = ""
        for m in s.messages:
            if m.get("role") == "system_note":
                continue  # internal — not shown to user
            role = m.get("role", "")
            text = _h(m.get("content", "") or "")
            who = "You" if role == "user" else "Assistant"
            bg = ("rgba(34,211,238,0.06)" if role == "user"
                  else "rgba(139,92,246,0.06)")
            msgs_html += (
                f'<div class="chat-msg" data-role="{_h(role)}" '
                f'style="margin-bottom:10px;padding:10px 12px;background:{bg};'
                f'border-radius:8px;border:1px solid var(--border)">'
                f'<div style="font-size:10px;text-transform:uppercase;'
                f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:3px">{who}</div>'
                f'<div style="font-size:13px;color:var(--ink);white-space:pre-wrap;'
                f'line-height:1.45">{text}</div></div>'
            )
        # Pending brief card (if any)
        brief_html = ""
        if s.pending_brief and not s.accepted_brief:
            try:
                pretty = json.dumps(s.pending_brief, indent=2, ensure_ascii=False)
            except Exception:
                pretty = str(s.pending_brief)
            brief_html = f"""
<div id="pending-brief" class="card" style="margin-top:14px;border-color:rgba(74,222,128,0.35);background:rgba(74,222,128,0.04)">
  <div style="font-size:10px;text-transform:uppercase;color:#4ade80;letter-spacing:0.5px;margin-bottom:4px">Proposed brief</div>
  <pre style="font-size:12px;white-space:pre-wrap;margin:0">{_h(pretty)}</pre>
  <div style="margin-top:14px;display:flex;gap:10px">
    <form method="post" action="{url_for('free_text_chat_accept', chat_id=chat_id)}" style="display:inline">
      <button type="submit" class="btn" style="background:#4ade80;color:#000;border:none">Accept &amp; generate</button>
    </form>
    <form method="post" action="{url_for('free_text_chat_decline', chat_id=chat_id)}" style="display:inline">
      <button type="submit" class="btn secondary">Decline — keep refining</button>
    </form>
  </div>
</div>
"""
        accepted_html = ""
        if s.accepted_brief:
            generate_url = url_for("free_text_chat_generate", chat_id=chat_id)
            try:
                pretty_a = json.dumps(s.accepted_brief, indent=2, ensure_ascii=False)
            except Exception:
                pretty_a = str(s.accepted_brief)
            accepted_html = f"""
<div class="card" style="margin-top:14px;border-color:rgba(34,211,238,0.35);background:rgba(34,211,238,0.04)">
  <div style="font-size:10px;text-transform:uppercase;color:#22D3EE;letter-spacing:0.5px;margin-bottom:4px">Accepted brief</div>
  <pre style="font-size:12px;white-space:pre-wrap;margin:0">{_h(pretty_a)}</pre>
  <form method="post" action="{generate_url}" style="margin-top:12px">
    <button type="submit" class="btn">Generate content from this brief →</button>
  </form>
</div>
"""
        send_url = url_for("free_text_chat_send", chat_id=chat_id)
        title = _h(s.title or "New chat")
        body = f"""
<h1>{title}</h1>
<p class="dim"><a href="{url_for('free_text_chat_page')}">← All chats</a></p>

<div id="chat-log" style="margin-top:14px">
  {msgs_html or '<p class="muted">Start by telling the assistant what you want to post. It will ask questions, research the web, and propose a brief.</p>'}
</div>

{brief_html}
{accepted_html}

<form id="chat-form" method="post" action="{send_url}" style="margin-top:14px">
  <textarea name="message" placeholder="Tell the assistant what you want to post about…"
            style="width:100%;min-height:90px;padding:10px;font-size:13px" required></textarea>
  <div style="margin-top:8px;display:flex;gap:10px;align-items:center">
    <button type="submit" class="btn">Send</button>
    <span class="muted" style="font-size:11px">The assistant uses Claude with web research tools.</span>
  </div>
</form>
"""
        return _layout(s.title or "Chat", body, active="add_input")

    @app.route("/free-text/chat/<chat_id>/send", methods=["POST"])
    def free_text_chat_send(chat_id):
        from mediahub.free_text_chat.session import load_session, save_session
        from mediahub.free_text_chat.agent import next_assistant_turn
        s = load_session(chat_id)
        if not s:
            return _layout("Chat not found",
                           '<div class="empty">Chat not found.</div>',
                           active="add_input"), 404
        msg = (request.form.get("message") or "").strip()
        if msg:
            s.add_user_message(msg)
            save_session(s)
            try:
                next_assistant_turn(s)
            except Exception as e:
                s.add_assistant_message(f"Error: {e}", meta={"error": True})
                save_session(s)
        return redirect(url_for("free_text_chat_view", chat_id=chat_id))

    @app.route("/free-text/chat/<chat_id>/accept", methods=["POST"])
    def free_text_chat_accept(chat_id):
        from mediahub.free_text_chat.session import load_session, save_session
        s = load_session(chat_id)
        if not s:
            return redirect(url_for("free_text_chat_page"))
        if s.pending_brief:
            s.accepted_brief = s.pending_brief
            s.pending_brief = None
            s.messages.append({"role": "system_note",
                               "content": "[user accepted the brief]",
                               "ts": datetime.now(timezone.utc).isoformat()})
            save_session(s)
        return redirect(url_for("free_text_chat_view", chat_id=chat_id))

    @app.route("/free-text/chat/<chat_id>/decline", methods=["POST"])
    def free_text_chat_decline(chat_id):
        from mediahub.free_text_chat.session import load_session, save_session
        from mediahub.free_text_chat.agent import next_assistant_turn
        s = load_session(chat_id)
        if not s:
            return redirect(url_for("free_text_chat_page"))
        if s.pending_brief:
            s.pending_brief = None
            s.add_user_message(
                "I'm not happy with that brief yet. Ask me what's missing or "
                "propose a revised version."
            )
            save_session(s)
            try:
                next_assistant_turn(s)
            except Exception as e:
                s.add_assistant_message(f"Error: {e}", meta={"error": True})
                save_session(s)
        return redirect(url_for("free_text_chat_view", chat_id=chat_id))

    @app.route("/free-text/chat/<chat_id>/generate", methods=["POST"])
    def free_text_chat_generate(chat_id):
        """Turn an accepted brief into a saved stub-pack so the existing
        approval pills + export flow apply."""
        from mediahub.free_text_chat.session import load_session
        from mediahub.club_platform.stub_pack_store import save_pack
        s = load_session(chat_id)
        if not s or not s.accepted_brief:
            return redirect(url_for("free_text_chat_view", chat_id=chat_id))
        brief = s.accepted_brief
        card = {
            "platform":   brief.get("platform") or "Instagram",
            "caption":    "\n\n".join([
                p for p in [brief.get("headline", ""), brief.get("body", "")]
                if p
            ]).strip(),
            "hashtags":   brief.get("hashtags") or [],
            "confidence": 0.85,
            "notes":      brief.get("visual_concept", "") or "",
            "status":     "queue",
        }
        saved = save_pack(
            "free_text",
            {"free_text": s.title or "Chat brief",
             "source": "chat", "chat_id": chat_id},
            [card],
        )
        return redirect(url_for("stub_pack_view", pack_id=saved["pack_id"]))

    # ---- Saved stub packs &mdash; list + view + export -----------------------
    _STUB_TYPE_LABEL = {
        "free_text":        "Free Text",
        "weekend_preview":  "Event Preview",
        "sponsor_post":     "Sponsor Post",
        "session_update":   "Session Update",
    }

    @app.route("/drafts")
    def stub_packs_list():
        from mediahub.club_platform.stub_pack_store import list_packs
        items = list_packs(limit=100)
        if not items:
            body = f"""
<h1>Saved drafts</h1>
<p class="dim">Content packs you generate from Free Text, Event Preview, Sponsor Post and Session Update are saved here.</p>
<div class="card" style="text-align:center;padding:48px 28px">
  <div style="font-size:42px;margin-bottom:12px">&#x1F4DD;</div>
  <h2 style="margin-bottom:6px">No drafts yet</h2>
  <p class="dim" style="margin-bottom:18px">Generate your first content cards from the Add Input page.</p>
  <a class="btn" href="{url_for('add_input_page')}">Add input &rarr;</a>
</div>
"""
            return _layout("Saved drafts", body, active="add_input")

        rows_html = ""
        for it in items:
            view_url = url_for("stub_pack_view", pack_id=it["pack_id"])
            delete_url = url_for("stub_pack_delete", pack_id=it["pack_id"])
            label = _STUB_TYPE_LABEL.get(it["stub_type"], it["stub_type"])
            ts = (it.get("created_at") or "")[:19].replace("T", " ")
            rows_html += (
                f'<tr><td><a href="{view_url}">{_h(it["title"])}</a></td>'
                f'<td><span class="tag info">{_h(label)}</span></td>'
                f'<td>{it["n_cards"]}</td>'
                f'<td class="muted">{_h(ts)}</td>'
                f'<td><form method="post" action="{delete_url}" style="display:inline" '
                f'onsubmit="return confirm(\'Delete this draft?\')">'
                f'<button class="btn secondary" type="submit" style="font-size:11px;padding:4px 10px;color:var(--bad);border-color:rgba(244,63,94,0.3)">Delete</button>'
                f'</form></td></tr>'
            )

        body = f"""
<h1>Saved drafts</h1>
<p class="dim">{len(items)} pack{'s' if len(items)!=1 else ''} saved.</p>
<div class="card">
  <table>
    <thead><tr><th>Title</th><th>Type</th><th>Cards</th><th>Created</th><th></th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
<p style="margin-top:14px"><a class="btn secondary" href="{url_for('add_input_page')}">+ New draft</a></p>
"""
        return _layout("Saved drafts", body, active="add_input")

    @app.route("/drafts/<pack_id>")
    def stub_pack_view(pack_id):
        from mediahub.club_platform.stub_pack_store import load_pack
        from mediahub.club_platform.stubs import render_cards_html
        rec = load_pack(pack_id)
        if not rec:
            body = '<div class="empty">Draft not found.</div>'
            return _layout("Draft not found", body, active="add_input"), 404

        stub_type = rec.get("stub_type", "other")
        type_label = _STUB_TYPE_LABEL.get(stub_type, stub_type)
        # We pass back = saved-list so "Start over" goes somewhere sensible.
        back_url = url_for("stub_packs_list")
        _full_status_url = url_for(
            "api_stub_pack_card_status", pack_id=pack_id, card_idx=999999
        )
        _status_api_base = _full_status_url.rsplit("/", 1)[0]
        cards_html = render_cards_html(
            {"cards": rec.get("cards") or []},
            back_url,
            rec.get("title") or "Draft pack",
            pack_id=pack_id,
            status_api_base=_status_api_base,
        )
        # Replace the renderer's default footer to add export + regenerate.
        export_url = url_for("stub_pack_export", pack_id=pack_id)
        regenerate_url = url_for({
            "free_text":       "free_text_chat_page",
            "weekend_preview": "stub_weekend_preview",
            "sponsor_post":    "stub_sponsor_post",
            "session_update":  "stub_session_update",
        }.get(stub_type, "free_text_chat_page"))
        footer = (
            f'<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">'
            f'<a class="btn" href="{export_url}">Export as text</a>'
            f'<a class="btn secondary" href="{regenerate_url}">Generate new draft</a>'
            f'<a class="btn secondary" href="{back_url}">&larr; All drafts</a>'
            f'</div>'
        )
        # Prepend a context band showing the type + timestamp.
        ts = (rec.get("created_at") or "")[:19].replace("T", " ")
        header = (
            f'<p class="dim" style="margin-bottom:14px">'
            f'<span class="tag info">{_h(type_label)}</span> '
            f'<span style="margin-left:8px">Generated {_h(ts)}</span></p>'
        )
        # Replace the renderer's default action row
        cards_html = cards_html.replace(
            f'<div style="margin-top:24px;display:flex;gap:10px">'
            f'<a class="btn secondary" href="{_h(back_url)}">&larr; Start over</a>'
            f'</div>',
            footer,
            1,
        )
        body = header + cards_html
        return _layout(rec.get("title") or "Draft", body, active="add_input")

    @app.route("/drafts/<pack_id>/export.txt")
    def stub_pack_export(pack_id):
        from mediahub.club_platform.stub_pack_store import load_pack, export_pack_text
        rec = load_pack(pack_id)
        if not rec:
            return ("Pack not found", 404)
        text = export_pack_text(rec)
        return Response(
            text,
            mimetype="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{pack_id}.txt"',
            },
        )

    @app.route("/drafts/<pack_id>/delete", methods=["POST"])
    def stub_pack_delete(pack_id):
        from mediahub.club_platform.stub_pack_store import delete_pack
        delete_pack(pack_id)
        return redirect(url_for("stub_packs_list"))

    @app.route("/api/drafts/<pack_id>/card/<int:card_idx>/status",
               methods=["POST"])
    def api_stub_pack_card_status(pack_id, card_idx):
        """Approve/reject a single card inside a saved stub pack.

        Powers the inline status pill on Free Text / Event Preview / Sponsor
        Post / Session Update card lists. The pill cycles
        queue → approved → rejected and persists the state in the pack JSON
        so reviewers can come back to it across sessions.
        """
        from mediahub.club_platform.stub_pack_store import update_card_status
        status = (request.form.get("status") or "").strip().lower()
        rec = update_card_status(pack_id, card_idx, status)
        if not rec:
            return jsonify({"ok": False, "error": "invalid_request"}), 400
        cards = rec.get("cards") or []
        card = cards[card_idx] if 0 <= card_idx < len(cards) else {}
        return jsonify({
            "ok": True,
            "pack_id": pack_id,
            "card_idx": card_idx,
            "status": card.get("status", status),
        })

    # ---- /add-input &mdash; multi-input landing page --------------------------
    @app.route("/add-input")
    def add_input_page():
        _INPUT_TYPES = [
            {
                "title": "Meet Results",
                "description": "Upload results from any sport meet, gala, or competition. Ranked content cards with confidence scores.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>'
                    '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
                    '<path d="M4 22h16"/>'
                    '<path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
                    '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
                    '<path d="M18 2H6v7a6 6 0 0 0 12 0V2z"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "upload",
            },
            {
                "title": "Athlete Spotlight",
                "description": "Pick a member from a processed meet and get a single-person achievement pack.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<circle cx="12" cy="8" r="4"/>'
                    '<path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "spotlight_landing",
            },
            {
                "title": "Event Preview",
                "description": "Tease an upcoming event, fixture, or competition before it starts.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
                    '<line x1="16" y1="2" x2="16" y2="6"/>'
                    '<line x1="8" y1="2" x2="8" y2="6"/>'
                    '<line x1="3" y1="10" x2="21" y2="10"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_weekend_preview",
            },
            {
                "title": "Sponsor Post",
                "description": "Create brand-safe sponsor activation content with your partners.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_sponsor_post",
            },
            {
                "title": "Session Update",
                "description": "Share live updates from training or events as they happen.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
                    '<polyline points="14 2 14 8 20 8"/>'
                    '<line x1="16" y1="13" x2="8" y2="13"/>'
                    '<line x1="16" y1="17" x2="8" y2="17"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "stub_session_update",
            },
            {
                "title": "Free Text",
                "description": "Describe any moment in your own words and get content suggestions.",
                "icon": (
                    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" width="28" height="28">'
                    '<path d="M12 20h9"/>'
                    '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>'
                    '</svg>'
                ),
                "status": "live",
                "endpoint": "free_text_chat_page",
            },
        ]

        cards_html = ""
        for card in _INPUT_TYPES:
            is_live = card["status"] == "live"
            if is_live:
                badge = '<span class="tag good" style="font-size:11px">Live</span>'
                btn_label = "Start &rarr;"
            else:
                badge = '<span class="tag" style="font-size:11px">Coming soon</span>'
                btn_label = "Preview &rarr;"
            try:
                card_url = url_for(card["endpoint"])
                href_attr = f'href="{card_url}"'
            except Exception:
                href_attr = 'href="#" onclick="return false"'
            cards_html += f"""
<a {href_attr} class="input-type-card" style="text-decoration:none;display:flex;flex-direction:column;
   gap:14px;padding:24px;background:var(--panel);border:1px solid var(--border);
   border-radius:var(--radius);transition:border-color 150ms,box-shadow 150ms">
  <div style="color:var(--accent)">{card['icon']}</div>
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <div style="font-size:16px;font-weight:700;color:var(--ink)">{_h(card['title'])}</div>
    {badge}
  </div>
  <div style="font-size:13px;color:var(--ink-dim);line-height:1.5">{_h(card['description'])}</div>
  <div style="margin-top:auto">
    <span class="btn" style="font-size:13px;padding:7px 14px">{btn_label}</span>
  </div>
</a>"""

        body = f"""
<style>
.input-type-card:hover {{ border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }}
</style>
<h1>Add Input</h1>
<p class="dim" style="margin-bottom:28px">
  Choose the type of content you want to create. Each input type produces a different set of social-ready cards.
</p>
<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px">
  {cards_html}
</div>
"""
        return _layout("Add Input", body, active="add_input")

    # ---- /organisation &mdash; organisation DNA / club identity ---------------
    @app.route("/organisation", methods=["GET", "POST"])
    def organisation_page():
        _ORG_TYPES = [
            ("other", "Other / general"),
            ("swimming_club", "Swimming club"),
            ("athletics", "Athletics club"),
            ("football", "Football / rugby / team sport"),
            ("university_society", "University society or sports club"),
            ("corporate_team", "Corporate team"),
        ]
        _PLATFORMS = [
            ("instagram", "Instagram"),
            ("tiktok", "TikTok"),
            ("twitter", "Twitter / X"),
            ("facebook", "Facebook"),
            ("linkedin", "LinkedIn"),
        ]
        _TONES = [
            ("warm-club", "Warm &amp; community &mdash; conversational, member-facing, first-name use"),
            ("hype", "Energetic &amp; hype &mdash; race-day language, exclamation marks, high energy"),
            ("data-led", "Data-led &mdash; numbers-first, precise, sponsor-friendly"),
        ]

        saved_msg = ""
        capture_preview = ""      # rendered preview HTML when a capture has just run
        capture_error = ""        # rendered error banner when capture failed
        voice_preview = ""        # rendered preview HTML after voice analysis
        voice_error = ""          # rendered error banner when voice analysis failed
        # The capture/voice previews are kept in-memory only &mdash; the user must
        # click "Save organisation" to persist them (no silent writes).
        if request.method == "POST":
            action = (request.form.get("action") or "save").strip().lower()
            raw_id = (request.form.get("profile_id") or "default").strip().lower()
            profile_id = re.sub(r"[^a-z0-9_-]", "-", raw_id).strip("-") or "default"
            existing = load_profile(profile_id) or ClubProfile(
                profile_id=profile_id,
                display_name=request.form.get("display_name") or profile_id,
            )

            if action == "capture":
                # ---- Brand DNA capture from website URL ----
                target_url = (request.form.get("brand_source_url") or "").strip()
                if not target_url:
                    capture_error = (
                        '<p class="tag bad" style="margin-bottom:20px">'
                        'Enter a website URL to analyse.</p>'
                    )
                    profile = existing
                else:
                    try:
                        from mediahub.brand.dna_capture import capture_brand_dna
                        result = capture_brand_dna(target_url, force=False)
                    except Exception as e:
                        result = {"brand_capture_status": f"error: {e}"}
                    status = (result or {}).get("brand_capture_status", "")
                    if status in ("ok", "ok_heuristic"):
                        # Merge captured fields into the in-memory profile so
                        # the preview shows them, but DON'T save until the user
                        # clicks "Save organisation".
                        for k in (
                            "brand_voice_summary", "brand_keywords",
                            "brand_palette_extracted", "brand_logo_url",
                            "brand_typography_hint", "brand_phrases_to_avoid",
                            "brand_phrases_to_use", "brand_source_url",
                            "brand_captured_at", "brand_capture_status",
                        ):
                            if k in result:
                                setattr(existing, k, result[k])
                        # Adopt extracted palette into primary/secondary if
                        # the existing profile is still on the default colours.
                        pal = result.get("brand_palette_extracted") or {}
                        if pal.get("primary") and existing.brand_primary in (
                            "", "#0A2540", "#A30D2D",
                        ):
                            existing.brand_primary = pal["primary"]
                        if pal.get("secondary") and existing.brand_secondary in (
                            "", "#000000",
                        ):
                            existing.brand_secondary = pal["secondary"]
                        note = (
                            "Captured from website &mdash; review below and click "
                            "Save organisation to persist."
                            if status == "ok"
                            else "Captured from website (no LLM available, "
                                 "heuristic fallback). Edit and save."
                        )
                        capture_preview = (
                            f'<p class="tag info" style="margin-bottom:20px">'
                            f'{_h(note)}</p>'
                        )
                    else:
                        # Surface the failure clearly but keep the form usable.
                        reason = {
                            "missing_url": "No URL was provided.",
                            "fetch_failed": "Could not reach that URL &mdash; check it loads in a browser.",
                        }.get(status, f"Capture failed ({_h(status or 'unknown error')}).")
                        capture_error = (
                            f'<p class="tag bad" style="margin-bottom:20px">'
                            f'{_h(reason)}</p>'
                        )
                profile = existing

            elif action == "capture_socials":
                # ---- Brand DNA capture from website + social links ----
                target_url = (request.form.get("brand_source_url") or "").strip()
                social_links: dict[str, str] = {}
                for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
                    v = (request.form.get(f"social_{key}") or "").strip()
                    if v:
                        social_links[key] = v
                if not target_url and not social_links:
                    capture_error = (
                        '<p class="tag bad" style="margin-bottom:20px">'
                        'Enter a website URL or at least one social link to analyse.</p>'
                    )
                    profile = existing
                else:
                    try:
                        from mediahub.brand.social_dna import capture_from_socials
                        result = capture_from_socials(
                            social_links=social_links,
                            website_url=target_url,
                            force=False,
                        )
                    except Exception as e:
                        result = {"brand_capture_status": f"error: {e}"}
                    status = (result or {}).get("brand_capture_status", "")
                    if status in ("ok", "ok_heuristic"):
                        for k in (
                            "brand_voice_summary", "brand_keywords",
                            "brand_palette_extracted", "brand_logo_url",
                            "brand_typography_hint", "brand_phrases_to_avoid",
                            "brand_phrases_to_use", "brand_source_url",
                            "brand_captured_at", "brand_capture_status",
                        ):
                            if k in result:
                                setattr(existing, k, result[k])
                        vp = result.get("voice_profile") or {}
                        if isinstance(vp, dict) and vp:
                            existing.voice_profile = vp
                        existing.social_links = social_links
                        pal = result.get("brand_palette_extracted") or {}
                        if pal.get("primary") and existing.brand_primary in ("", "#0A2540", "#A30D2D"):
                            existing.brand_primary = pal["primary"]
                        if pal.get("secondary") and existing.brand_secondary in ("", "#000000"):
                            existing.brand_secondary = pal["secondary"]
                        note = (
                            "Re-analysed from website + socials &mdash; review below "
                            "and click Save organisation to persist."
                            if status == "ok"
                            else "Re-analysed (no LLM available, heuristic fallback). Edit and save."
                        )
                        capture_preview = (
                            f'<p class="tag info" style="margin-bottom:20px">'
                            f'{_h(note)}</p>'
                        )
                    else:
                        reason = {
                            "no_sources": "Add a website URL or at least one social link.",
                            "fetch_failed_all": (
                                "None of the links could be read &mdash; "
                                "they may be blocked or behind login. Try a "
                                "different combination or paste captions manually below."
                            ),
                        }.get(status, f"Capture failed ({_h(status or 'unknown error')}).")
                        capture_error = (
                            f'<p class="tag bad" style="margin-bottom:20px">'
                            f'{_h(reason)}</p>'
                        )
                profile = existing

            elif action == "analyse_voice":
                # ---- Voice imitation analysis ----
                raw_examples = (request.form.get("voice_examples") or "").strip()
                if not raw_examples:
                    voice_error = (
                        '<p class="tag bad" style="margin-bottom:20px">'
                        'Paste at least 3 captions (one per line) to analyse voice.</p>'
                    )
                    profile = existing
                else:
                    examples = [e.strip() for e in raw_examples.split("\n") if e.strip()]
                    if len(examples) < 2:
                        voice_error = (
                            '<p class="tag bad" style="margin-bottom:20px">'
                            'Paste at least 3 captions to get meaningful results.</p>'
                        )
                        profile = existing
                    else:
                        try:
                            from mediahub.brand.voice_imitation import analyse_examples as _analyse
                            vp = _analyse(examples)
                        except Exception as exc:
                            vp = {}
                            voice_error = (
                                f'<p class="tag bad" style="margin-bottom:20px">'
                                f'Analysis failed: {_h(str(exc))}</p>'
                            )
                        if vp:
                            existing.voice_examples = examples[:20]
                            existing.voice_profile = vp
                            voice_preview = (
                                '<p class="tag info" style="margin-bottom:20px">'
                                'Voice profile analysed &mdash; review below and click '
                                'Save organisation to persist.</p>'
                            )
                    profile = existing

            else:
                # ---- Save organisation ----
                existing.display_name = (request.form.get("display_name") or existing.display_name).strip()
                existing.short_name = (request.form.get("short_name") or "").strip()
                existing.org_type = (request.form.get("org_type") or "other").strip()
                existing.governing_body = (request.form.get("governing_body") or "").strip()
                existing.country = (request.form.get("country") or "").strip()
                codes_raw = request.form.get("club_codes") or ""
                existing.club_codes = [c.strip() for c in codes_raw.split(",") if c.strip()]
                existing.brand_primary = (request.form.get("brand_primary") or existing.brand_primary or "#0A2540").strip()
                existing.brand_secondary = (request.form.get("brand_secondary") or existing.brand_secondary or "#000000").strip()
                existing.tone = (request.form.get("tone") or "warm-club").strip()
                existing.caption_tone = existing.tone
                existing.platforms = [p.strip() for p in request.form.getlist("platforms") if p.strip()]
                existing.tone_notes = (request.form.get("tone_notes") or "").strip()
                raw_exemplars = (request.form.get("exemplar_captions") or "").strip()
                if raw_exemplars:
                    parts = [p.strip() for p in raw_exemplars.split("---") if p.strip()]
                    existing.exemplar_captions = parts[:5]
                else:
                    existing.exemplar_captions = []
                existing.sponsor_name = (request.form.get("sponsor_name") or "").strip()
                existing.sponsor_guidelines = (request.form.get("sponsor_guidelines") or "").strip()
                def _hidden_list(name: str) -> list[str]:
                    raw = (request.form.get(name) or "").strip()
                    if not raw:
                        return []
                    try:
                        v = json.loads(raw)
                        if isinstance(v, list):
                            return [str(x) for x in v]
                    except Exception:
                        return []
                    return []

                def _hidden_dict(name: str) -> dict:
                    raw = (request.form.get(name) or "").strip()
                    if not raw:
                        return {}
                    try:
                        v = json.loads(raw)
                        if isinstance(v, dict):
                            return v
                    except Exception:
                        return {}
                    return {}

                existing.brand_voice_summary = (request.form.get("brand_voice_summary") or "").strip()
                existing.brand_logo_url = (request.form.get("brand_logo_url") or "").strip()
                existing.brand_typography_hint = (request.form.get("brand_typography_hint") or "").strip()
                existing.brand_source_url = (request.form.get("brand_source_url_saved") or "").strip()
                existing.brand_captured_at = (request.form.get("brand_captured_at") or "").strip()
                existing.brand_capture_status = (request.form.get("brand_capture_status") or "").strip()
                existing.brand_keywords = _hidden_list("brand_keywords_json")
                existing.brand_phrases_to_use = _hidden_list("brand_phrases_to_use_json")
                existing.brand_phrases_to_avoid = _hidden_list("brand_phrases_to_avoid_json")
                existing.brand_palette_extracted = _hidden_dict("brand_palette_extracted_json")
                from mediahub.brand.voice_imitation import (
                    analyse_examples as _analyse_voice,
                    redact_pii as _redact_pii,
                )
                raw_voice_examples = (request.form.get("voice_examples") or "").strip()
                if raw_voice_examples:
                    voice_lines = [
                        _redact_pii(line.strip())
                        for line in raw_voice_examples.splitlines()
                        if line.strip()
                    ]
                    existing.voice_examples = voice_lines[:20]
                else:
                    existing.voice_examples = []
                vp_from_hidden = _hidden_dict("voice_profile_json")
                if vp_from_hidden:
                    existing.voice_profile = vp_from_hidden
                elif not existing.voice_examples:
                    existing.voice_profile = {}
                if request.form.get("analyse_voice") and existing.voice_examples:
                    existing.voice_profile = _analyse_voice(existing.voice_examples)
                    saved_msg = (
                        '<p class="tag good" style="margin-bottom:20px">'
                        'Voice profile analysed and saved.</p>'
                    )
                else:
                    saved_msg = (
                        '<p class="tag good" style="margin-bottom:20px">'
                        'Organisation saved.</p>'
                    )
                # Persist any social-link edits made on the full form.
                social_edits: dict[str, str] = {}
                for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
                    v = (request.form.get(f"social_{key}") or "").strip()
                    if v:
                        social_edits[key] = v
                if social_edits or (request.form.get("social_links_edited") == "1"):
                    existing.social_links = social_edits
                # Re-derive the AI operating profile whenever the user
                # edits the org. Single LLM call; consumers cache-read.
                try:
                    from mediahub.brand.derived import derive_operating_profile
                    existing.brand_operating_profile = derive_operating_profile(existing)
                except Exception:
                    existing.brand_operating_profile = {
                        "tone_prose": {}, "achievement_priorities": {},
                        "type_phrases": {}, "artefact_voice": {},
                        "status": "error",
                    }
                save_profile(existing)
                # Pin into session so the routing gate unlocks and so
                # the next session lands on the same org.
                session["active_profile_id"] = existing.profile_id
                profile = existing
        else:
            # GET: prefer the session-pinned profile; fall back to the
            # most-recent on disk, then to a blank one for the empty state.
            pid_pin = _active_profile_id()
            profile = (load_profile(pid_pin) if pid_pin else None)
            if profile is None:
                profiles = list_profiles()
                profile = profiles[0] if profiles else ClubProfile(profile_id="default", display_name="")

        # Build select/checkbox HTML helpers
        def _opt(val, label, selected):
            sel = " selected" if selected else ""
            return f'<option value="{_h(val)}"{sel}>{_h(label)}</option>'

        def _radio(name, val, label, checked):
            chk = " checked" if checked else ""
            return (f'<label style="display:block;margin-bottom:8px;cursor:pointer">'
                    f'<input type="radio" name="{_h(name)}" value="{_h(val)}"{chk} style="margin-right:6px">'
                    f'{label}</label>')

        def _cb(name, val, label, checked):
            chk = " checked" if checked else ""
            return (f'<label style="display:inline-flex;align-items:center;gap:6px;'
                    f'margin-right:16px;margin-bottom:8px;cursor:pointer">'
                    f'<input type="checkbox" name="{_h(name)}" value="{_h(val)}"{chk}>'
                    f'{_h(label)}</label>')

        org_type_opts = "".join(_opt(v, l, v == (profile.org_type or "other")) for v, l in _ORG_TYPES)
        tone_radios = "".join(_radio("tone", v, l, v == (profile.tone or "warm-club")) for v, l in _TONES)
        platform_cbs = "".join(_cb("platforms", v, l, v in (profile.platforms or [])) for v, l in _PLATFORMS)
        exemplars_text = "\n---\n".join(profile.exemplar_captions or [])
        voice_examples_text = "\n".join(profile.voice_examples or [])

        # Build the voice-profile summary panel so the user can see what
        # the engine learned the last time they ran "Analyse voice".
        vp = profile.voice_profile or {}
        if vp:
            def _list_chips(items):
                items = items or []
                if not items:
                    return '<span class="muted" style="font-size:12px">&mdash;</span>'
                return "".join(
                    f'<span style="display:inline-block;padding:2px 8px;'
                    f'margin:2px 4px 2px 0;border:1px solid var(--border);'
                    f'border-radius:999px;font-size:12px">{_h(s)}</span>'
                    for s in items
                )
            voice_profile_html = (
                f'<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--border);'
                f'border-radius:8px;background:var(--panel)">'
                f'<div style="font-size:12px;color:var(--ink-dim);margin-bottom:6px">'
                f'Voice profile (from {len(profile.voice_examples or [])} examples)</div>'
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;font-size:13px;margin-bottom:8px">'
                f'<div>Avg sentence length: <b>{_h(vp.get("sentence_length_avg", "—"))}</b> words</div>'
                f'<div>P90 sentence length: <b>{_h(vp.get("sentence_length_p90", "—"))}</b> words</div>'
                f'<div>Emojis / caption: <b>{_h(vp.get("emoji_rate_per_caption", "—"))}</b></div>'
                f'<div>Hashtags / caption: <b>{_h(vp.get("hashtag_count_avg", "—"))}</b></div>'
                f'<div>Swimmer address: <b>{_h(vp.get("preferred_swimmer_address", "first_name"))}</b></div>'
                f'</div>'
                f'<div style="font-size:12px;color:var(--ink-dim);margin-top:6px">Openers</div>'
                f'<div>{_list_chips(vp.get("characteristic_openers"))}</div>'
                f'<div style="font-size:12px;color:var(--ink-dim);margin-top:6px">Closers</div>'
                f'<div>{_list_chips(vp.get("characteristic_closers"))}</div>'
                f'<div style="font-size:12px;color:var(--ink-dim);margin-top:6px">Phrases to avoid</div>'
                f'<div>{_list_chips(vp.get("forbidden_phrases"))}</div>'
                f'</div>'
            )
        else:
            voice_profile_html = (
                '<p class="muted" style="font-size:12px;margin-top:8px">'
                'No voice profile yet &mdash; paste 5-20 past captions and click '
                '<b>Analyse voice</b>.</p>'
            )

        _input_style = "width:100%;max-width:480px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);font-size:14px"
        _ta_style = "width:100%;max-width:600px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--ink);font-family:inherit;font-size:14px"

        # ---- Brand DNA preview block (rendered when fields are populated) ----
        def _swatch(hexv: str) -> str:
            if not hexv:
                return ""
            return (
                f'<div title="{_h(hexv)}" style="display:inline-flex;align-items:center;'
                f'gap:6px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;'
                f'margin-right:6px;margin-bottom:6px;background:var(--panel)">'
                f'<span style="display:inline-block;width:18px;height:18px;border-radius:4px;'
                f'background:{_h(hexv)};border:1px solid rgba(255,255,255,0.15)"></span>'
                f'<code style="font-size:11px;color:var(--ink)">{_h(hexv)}</code></div>'
            )

        def _chip(text: str, tone: str = "neutral") -> str:
            colour = {
                "good": "var(--accent)",
                "warn": "#ffae3b",
                "bad": "#ff5d6c",
                "neutral": "var(--ink-dim)",
            }.get(tone, "var(--ink-dim)")
            return (
                f'<span style="display:inline-block;padding:2px 8px;margin:2px 4px 2px 0;'
                f'border:1px solid var(--border);border-radius:999px;font-size:11px;'
                f'color:{colour};background:rgba(255,255,255,0.02)">{_h(text)}</span>'
            )

        brand_preview_html = ""
        has_brand = bool(
            (profile.brand_voice_summary or "").strip()
            or profile.brand_keywords
            or profile.brand_palette_extracted
            or profile.brand_logo_url
            or profile.brand_phrases_to_use
            or profile.brand_phrases_to_avoid
        )
        if has_brand:
            pal = profile.brand_palette_extracted or {}
            swatches = "".join(_swatch(pal.get(k, "")) for k in ("primary", "secondary", "accent") if pal.get(k))
            keywords_html = "".join(_chip(k, "neutral") for k in (profile.brand_keywords or [])[:12])
            use_html = "".join(_chip(p, "good") for p in (profile.brand_phrases_to_use or [])[:5])
            avoid_html = "".join(_chip(p, "bad") for p in (profile.brand_phrases_to_avoid or [])[:5])
            logo_html = ""
            if profile.brand_logo_url:
                logo_html = (
                    f'<img src="{_h(profile.brand_logo_url)}" alt="Detected logo" '
                    f'style="max-height:60px;max-width:200px;background:var(--panel);'
                    f'padding:6px;border:1px solid var(--border);border-radius:6px"/>'
                )
            captured_meta = ""
            if profile.brand_captured_at or profile.brand_source_url:
                src = profile.brand_source_url or ""
                ts = profile.brand_captured_at or ""
                status = profile.brand_capture_status or ""
                captured_meta = (
                    f'<p style="font-size:11px;color:var(--ink-dim);margin-top:8px">'
                    f'Source: <a href="{_h(src)}" target="_blank" rel="noopener" '
                    f'style="color:var(--ink-dim)">{_h(src)}</a> &middot; '
                    f'captured {_h(ts)} &middot; status {_h(status)}'
                    f'</p>'
                )
            brand_preview_html = f"""
<div class="card" style="margin-bottom:20px;border:1px dashed var(--border);background:rgba(34,211,238,0.03)">
  <h3 style="margin-top:0;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Brand DNA preview</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Voice summary</div>
      <p style="margin:0;font-size:13px;color:var(--ink);line-height:1.5">{_h(profile.brand_voice_summary or '(no summary yet)')}</p>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Palette</div>
      <div>{swatches or '<span class="dim" style="font-size:12px">(none detected)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Typography hint</div>
      <p style="margin:0;font-size:13px;color:var(--ink)">{_h(profile.brand_typography_hint or '—')}</p>
    </div>
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Detected logo</div>
      <div>{logo_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Keywords</div>
      <div>{keywords_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Phrases to use</div>
      <div>{use_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-top:14px;margin-bottom:6px">Phrases to avoid</div>
      <div>{avoid_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
    </div>
  </div>
  {captured_meta}
</div>
"""

        # Hidden inputs that carry the captured brand fields through the
        # next form submission so a click on Save persists them.
        brand_hidden_inputs = (
            f'<input type="hidden" name="brand_voice_summary" value="{_h(profile.brand_voice_summary or "")}"/>'
            f'<input type="hidden" name="brand_logo_url" value="{_h(profile.brand_logo_url or "")}"/>'
            f'<input type="hidden" name="brand_typography_hint" value="{_h(profile.brand_typography_hint or "")}"/>'
            f'<input type="hidden" name="brand_source_url_saved" value="{_h(profile.brand_source_url or "")}"/>'
            f'<input type="hidden" name="brand_captured_at" value="{_h(profile.brand_captured_at or "")}"/>'
            f'<input type="hidden" name="brand_capture_status" value="{_h(profile.brand_capture_status or "")}"/>'
            f'<input type="hidden" name="brand_keywords_json" value="{_h(json.dumps(profile.brand_keywords or []))}"/>'
            f'<input type="hidden" name="brand_phrases_to_use_json" value="{_h(json.dumps(profile.brand_phrases_to_use or []))}"/>'
            f'<input type="hidden" name="brand_phrases_to_avoid_json" value="{_h(json.dumps(profile.brand_phrases_to_avoid or []))}"/>'
            f'<input type="hidden" name="brand_palette_extracted_json" value="{_h(json.dumps(profile.brand_palette_extracted or {}))}"/>'
            f'<input type="hidden" name="voice_profile_json" value="{_h(json.dumps(profile.voice_profile or {}))}"/>'
            f'<input type="hidden" name="voice_examples_json" value="{_h(json.dumps(profile.voice_examples or []))}"/>'
        )

        # ---- Voice profile preview block ----
        voice_profile_html = ""
        vp = profile.voice_profile or {}
        if vp:
            def _stat_row(label: str, val) -> str:
                return (
                    f'<div style="display:flex;justify-content:space-between;'
                    f'padding:4px 0;border-bottom:1px solid var(--border);font-size:13px">'
                    f'<span style="color:var(--ink-dim)">{_h(label)}</span>'
                    f'<strong style="color:var(--ink)">{_h(str(val))}</strong></div>'
                )

            openers_html = " ".join(_chip(o, "neutral") for o in (vp.get("characteristic_openers") or [])[:6])
            closers_html = " ".join(_chip(c, "neutral") for c in (vp.get("characteristic_closers") or [])[:4])
            forbidden_html = " ".join(_chip(f, "bad") for f in (vp.get("forbidden_phrases") or [])[:6])
            hashtags_html = " ".join(_chip(h, "neutral") for h in (vp.get("common_hashtags") or [])[:8])
            address = _h(vp.get("preferred_swimmer_address") or "first_name")
            cap_style = _h(vp.get("capitalisation_style") or "sentence")
            n_examples = len(profile.voice_examples or [])
            voice_profile_html = f"""
<div class="card" style="margin-bottom:20px;border:1px dashed var(--border);background:rgba(167,139,250,0.04)">
  <h3 style="margin-top:0;margin-bottom:12px;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Voice profile preview &middot; {n_examples} example{'s' if n_examples != 1 else ''}</h3>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start">
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:8px">Style metrics</div>
      {_stat_row('Avg sentence length (words)', vp.get('sentence_length_avg', 0))}
      {_stat_row('Sentence length p90', vp.get('sentence_length_p90', 0))}
      {_stat_row('Avg emoji per caption', vp.get('emoji_rate_per_caption', 0))}
      {_stat_row('Avg hashtags per caption', vp.get('hashtag_count_avg', 0))}
      {_stat_row('Capitalisation style', cap_style)}
      {_stat_row('Swimmer address', address)}
    </div>
    <div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Typical openers</div>
      <div style="margin-bottom:10px">{openers_html or '<span class="dim" style="font-size:12px">(none detected)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Typical closers</div>
      <div style="margin-bottom:10px">{closers_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Common hashtags</div>
      <div style="margin-bottom:10px">{hashtags_html or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
      <div style="font-weight:600;font-size:12px;color:var(--ink-dim);margin-bottom:6px">Phrases to avoid</div>
      <div>{forbidden_html or '<span class="dim" style="font-size:12px">(none identified)</span>'}</div>
    </div>
  </div>
</div>
"""

        voice_examples_text = "\n".join(profile.voice_examples or [])

        body = f"""
{saved_msg}{capture_preview}{capture_error}{voice_preview}{voice_error}
<h1>Organisation</h1>
<p class="dim" style="margin-bottom:24px">Tell MediaHub about your club, society or team so the AI can produce on-brand content.</p>

<div class="card" style="margin-bottom:20px;border:1px solid var(--accent);background:rgba(34,211,238,0.04)">
  <h2 style="margin-top:0">Re-analyse brand from website + social links</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">Paste your club's website URL and/or social profile links. MediaHub reads each link, extracts the palette, tone of voice, characteristic phrases and recent captions, and updates the brand profile below. AI-driven &mdash; no manual style guide needed.</p>
  <form method="POST">
    <input type="hidden" name="action" value="capture_socials"/>
    <input type="hidden" name="profile_id" value="{_h(profile.profile_id)}"/>
    <input type="hidden" name="display_name" value="{_h(profile.display_name)}"/>
    <div style="margin-bottom:10px">
      <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">Website</label>
      <input type="url" name="brand_source_url" value="{_h(profile.brand_source_url or '')}"
             placeholder="https://your-club.example" style="{_input_style};max-width:600px"/>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 18px;max-width:780px">
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">Instagram</label>
        <input type="url" name="social_instagram" value="{_h((profile.social_links or {}).get('instagram',''))}"
               placeholder="https://instagram.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">Facebook</label>
        <input type="url" name="social_facebook" value="{_h((profile.social_links or {}).get('facebook',''))}"
               placeholder="https://facebook.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">Twitter / X</label>
        <input type="url" name="social_twitter" value="{_h((profile.social_links or {}).get('twitter',''))}"
               placeholder="https://x.com/your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">TikTok</label>
        <input type="url" name="social_tiktok" value="{_h((profile.social_links or {}).get('tiktok',''))}"
               placeholder="https://tiktok.com/@your-club" style="{_input_style}"/>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">LinkedIn</label>
        <input type="url" name="social_linkedin" value="{_h((profile.social_links or {}).get('linkedin',''))}"
               placeholder="https://linkedin.com/company/your-club" style="{_input_style}"/>
      </div>
    </div>
    <div style="margin-top:10px">
      <button type="submit" class="btn">Re-analyse &rarr;</button>
      <span class="muted" style="margin-left:8px;font-size:12px">Takes 10&ndash;30 seconds.</span>
    </div>
  </form>
</div>

{brand_preview_html}

<div class="card" style="margin-bottom:20px;border:1px solid rgba(167,139,250,0.4);background:rgba(167,139,250,0.04)">
  <h2 style="margin-top:0">Analyse voice from past posts</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">Paste 5&ndash;20 recent captions (one per line). MediaHub measures sentence length, emoji density, hashtag style, and extracts opening/closing phrase patterns so generated captions sound like you.</p>
  <form method="POST">
    <input type="hidden" name="action" value="analyse_voice"/>
    <input type="hidden" name="profile_id" value="{_h(profile.profile_id)}"/>
    <input type="hidden" name="display_name" value="{_h(profile.display_name)}"/>
    <textarea name="voice_examples" rows="8"
              placeholder="Paste one caption per line&#10;e.g.&#10;Huge PB for the squad this weekend &mdash; 200 free goes sub-2 for the first time &#127946;&#10;What a meet! Five PBs and a county standard from our junior group. #swimming #clublife"
              style="{_ta_style};max-width:640px;display:block;margin-bottom:10px">{_h(voice_examples_text)}</textarea>
    <button type="submit" class="btn">Analyse voice &rarr;</button>
  </form>
</div>

{voice_profile_html}

<form method="POST">
<input type="hidden" name="action" value="save"/>
<input type="hidden" name="profile_id" value="{_h(profile.profile_id)}"/>
{brand_hidden_inputs}

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px 24px;max-width:700px">
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Organisation name</label>
      <input type="text" name="display_name" value="{_h(profile.display_name)}" placeholder="e.g. City Aquatics Club"
             style="{_input_style}" required/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Short name</label>
      <input type="text" name="short_name" value="{_h(profile.short_name)}" placeholder="e.g. City AC"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Organisation type</label>
      <select name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Governing body</label>
      <input type="text" name="governing_body" value="{_h(profile.governing_body)}" placeholder="e.g. Swim England, UKA"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Country</label>
      <input type="text" name="country" value="{_h(profile.country)}" placeholder="e.g. United Kingdom"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Result file codes</label>
      <input type="text" name="club_codes" value="{_h(', '.join(profile.club_codes or []))}"
             placeholder="e.g. CMA, COMA" style="{_input_style}"/>
      <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Comma-separated codes that identify your members in results files.</p>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Primary colour</label>
      <input type="color" name="brand_primary" value="{_h(profile.brand_primary or '#0A2540')}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Secondary colour</label>
      <input type="color" name="brand_secondary" value="{_h(profile.brand_secondary or '#000000')}"
             style="height:38px;width:80px;padding:2px;border:1px solid var(--border);border-radius:6px;cursor:pointer"/>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Voice &amp; Tone</h2>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:8px;font-size:14px">Caption tone</label>
    {tone_radios}
  </div>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:8px;font-size:14px">Active platforms</label>
    {platform_cbs}
  </div>
  <div style="margin-bottom:16px">
    <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Brand voice notes</label>
    <textarea name="tone_notes" rows="3" placeholder="Any guidelines, phrases you use, things to avoid..."
              style="{_ta_style}">{_h(profile.tone_notes or "")}</textarea>
  </div>
  <div>
    <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Example captions</label>
    <textarea name="exemplar_captions" rows="6"
              placeholder="Paste up to 5 past captions that represent your voice.&#10;Separate each one with --- on its own line."
              style="{_ta_style}">{_h(exemplars_text)}</textarea>
    <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">Separate captions with <code>---</code> on its own line. Up to 5 examples.</p>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Voice examples</h2>
  <p class="dim" style="margin-bottom:12px;font-size:13px">
    Paste 5&ndash;20 of your recent Instagram, Facebook or X captions &mdash; one per line.
    MediaHub will learn your sentence length, emoji and hashtag habits, opener
    and closer style, and how you refer to swimmers, then use that profile when
    generating live AI captions. Names are stripped before storage.
  </p>
  <div>
    <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Past captions (one per line)</label>
    <textarea name="voice_examples" rows="10"
              placeholder="Massive PB from [name] in the 200 free this morning&#10;Hard work pays off &mdash; proud of every swimmer in the pool tonight &#x1F3CA;&#10;..."
              style="{_ta_style}">{_h(voice_examples_text)}</textarea>
    <p style="font-size:12px;color:var(--ink-dim);margin-top:4px">
      One caption per line, up to 20. Real swimmer names will be replaced with
      <code>[NAME]</code> before saving.
    </p>
  </div>
  <div style="margin-top:12px">
    <button type="submit" name="analyse_voice" value="1" class="btn">Analyse voice</button>
    <span class="muted" style="font-size:12px;margin-left:8px">Re-runs the analyser on the captions above.</span>
  </div>
  {voice_profile_html}
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0">Sponsors</h2>
  <div style="display:grid;grid-template-columns:1fr;gap:16px;max-width:600px">
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Primary sponsor name</label>
      <input type="text" name="sponsor_name" value="{_h(profile.sponsor_name or '')}"
             placeholder="e.g. Acme Sports" style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-weight:600;margin-bottom:4px;font-size:14px">Sponsor guidelines</label>
      <textarea name="sponsor_guidelines" rows="3"
                placeholder="Hashtags to include, mentions required, things to avoid..."
                style="{_ta_style}">{_h(profile.sponsor_guidelines or "")}</textarea>
    </div>
  </div>
</div>

<div style="margin-top:8px">
  <button type="submit" class="btn">Save organisation</button>
</div>
</form>
"""
        return _layout("Organisation", body, active="organisation")

    # ---- /organisation/setup &mdash; first-run AI brand-DNA flow -----------
    #
    # Required before any content can be produced. Three sections on one
    # page: identity (name/type/country), sources (website + 5 social
    # links), and AI build (one click that hands everything to the LLM
    # and shows the result for confirmation). On save the org is pinned
    # ---- /sign-in -----------------------------------------------------
    #
    # Profile picker. No username, no password — we don't have a real
    # auth model and the deployment is operator-managed single-instance.
    # The page just lists every saved ClubProfile and lets the user
    # pick one to pin into their session, OR delete a profile they no
    # longer want, OR jump to /organisation/setup to create a fresh one.
    #
    # This is the *only* path to switch tenants once a profile is set
    # up; the home page links here, and the hero "Switch organisation"
    # button on the pinned-state hero links here too.
    @app.route("/sign-in", methods=["GET"])
    def sign_in_page():
        profiles = list_profiles()
        current_id = _active_profile_id() or ""

        # Friendly fallback when no profiles exist yet — send the user
        # straight to setup rather than render an empty picker.
        if not profiles:
            return redirect(url_for("organisation_setup"))

        def _initials(name: str) -> str:
            parts = [p for p in (name or "").strip().split() if p]
            if not parts:
                return "?"
            if len(parts) == 1:
                return parts[0][:2].upper()
            return (parts[0][0] + parts[-1][0]).upper()

        cards_html = ""
        for p in profiles:
            is_current = (p.profile_id == current_id)
            logo_html = ""
            logo_url = (getattr(p, "brand_logo_url", "") or "").strip()
            if logo_url and (logo_url.startswith("http://") or logo_url.startswith("https://")):
                logo_html = f'<img src="{_h(logo_url)}" alt="" />'
            else:
                logo_html = _h(_initials(p.display_name))

            ready = p.is_ready()
            captured = p.brand_capture_status in ("ok", "ok_heuristic")
            pill_html = ""
            if is_current:
                pill_html = (
                    '<span class="pill" style="background:rgba(34,197,94,0.10);'
                    'border-color:rgba(34,197,94,0.30);color:#22C55E">Active</span>'
                )
            if ready:
                pill_html += '<span class="pill">Brand ready</span>'
            elif captured:
                pill_html += (
                    '<span class="pill" style="background:rgba(245,158,11,0.10);'
                    'border-color:rgba(245,158,11,0.30);color:#F59E0B">'
                    'Partial</span>'
                )
            else:
                pill_html += (
                    '<span class="pill" style="background:rgba(255,255,255,0.06);'
                    'border-color:rgba(255,255,255,0.10);color:var(--ink-muted)">'
                    'Incomplete</span>'
                )

            sign_in_url = url_for("sign_in_post")
            delete_url = url_for("sign_in_delete")
            cards_html += (
                '<div class="mh-profile-card">'
                f'<div class="logo">{logo_html}</div>'
                f'<div class="display-name">{_h(p.display_name)}</div>'
                f'<div class="meta-line">{pill_html}</div>'
                '<div class="actions">'
                f'<form method="post" action="{sign_in_url}" style="flex:1;display:flex" data-loader-text="Switching organisation">'
                f'<input type="hidden" name="profile_id" value="{_h(p.profile_id)}">'
                f'<button type="submit" class="btn-sign-in">'
                f'{"Continue" if is_current else "Sign in"} &rarr;</button>'
                '</form>'
                f'<form method="post" action="{delete_url}" data-no-loader="1" '
                f'onsubmit="return confirm(\'Delete the &quot;{_h(p.display_name)}&quot; profile? '
                f'Its runs stay on disk but it disappears from this picker. This cannot be undone.\')">'
                f'<input type="hidden" name="profile_id" value="{_h(p.profile_id)}">'
                f'<button type="submit" class="btn-delete" title="Delete profile">&times;</button>'
                '</form>'
                '</div>'
                '</div>'
            )

        new_org_url = url_for("organisation_setup")
        cards_html += (
            f'<a class="mh-new-profile" href="{new_org_url}">'
            '<div><div class="plus">+</div>'
            'Create new organisation</div></a>'
        )

        body = (
            '<h1 style="margin-top:8px;font-family:Sora,Inter,sans-serif;'
            'font-size:32px;letter-spacing:-0.02em">Pick an organisation</h1>'
            '<p class="dim" style="margin-bottom:24px;font-size:14px">'
            f'{len(profiles)} saved {"profile" if len(profiles) == 1 else "profiles"} on this deployment. '
            'Picking one loads its brand voice, palette, logo, and history. '
            'Switch any time from the home page.'
            '</p>'
            f'<div class="mh-profile-grid">{cards_html}</div>'
        )
        return _layout("Sign in", body, active="signin")

    @app.route("/sign-in", methods=["POST"])
    def sign_in_post():
        """Pin the chosen profile into the session and redirect home."""
        pid = (request.form.get("profile_id") or "").strip()
        if not pid:
            return redirect(url_for("sign_in_page"))
        prof = load_profile(pid)
        if prof is None:
            return redirect(url_for("sign_in_page"))
        session["active_profile_id"] = prof.profile_id
        return redirect(url_for("home"))

    @app.route("/sign-in/delete", methods=["POST"])
    def sign_in_delete():
        """Delete the profile JSON from disk and clear the session pin
        if it was the active one. Runs (under DATA_DIR/runs_v4) are NOT
        removed — they're orphaned but recoverable.
        """
        pid = (request.form.get("profile_id") or "").strip()
        if not pid:
            return redirect(url_for("sign_in_page"))
        from .club_profile import _profiles_dir
        p = _profiles_dir() / f"{pid}.json"
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
        if _active_profile_id() == pid:
            session.pop("active_profile_id", None)
        return redirect(url_for("sign_in_page"))

    # into session so the user never sees this page again unless they
    # ask to re-run it.
    @app.route("/organisation/setup", methods=["GET"])
    def organisation_setup():
        prof = _active_profile()
        # Pre-fill from any existing profile so refreshing the page doesn't
        # wipe what the user just typed.
        pid = (prof.profile_id if prof else "")
        display_name = (prof.display_name if prof else "")
        org_type = (prof.org_type if prof else "other")
        country = (prof.country if prof else "")
        governing_body = (prof.governing_body if prof else "")
        website_url = (prof.brand_source_url if prof else "")
        social = dict(prof.social_links) if prof and prof.social_links else {}

        # --- Preview block (only when the AI has already run once) ---
        preview_html = ""
        if prof and prof.is_ready():
            kw_chips = "".join(
                f'<span style="display:inline-block;padding:3px 10px;'
                f'margin:2px 4px 2px 0;border:1px solid var(--border);'
                f'border-radius:999px;font-size:12px;color:var(--ink-dim)">'
                f'{_h(k)}</span>'
                for k in (prof.brand_keywords or [])[:10]
            )
            pal = prof.brand_palette_extracted or {}
            sw = "".join(
                f'<span title="{_h(pal[k])}" style="display:inline-block;'
                f'width:22px;height:22px;border-radius:4px;margin-right:6px;'
                f'background:{_h(pal[k])};border:1px solid rgba(255,255,255,0.15);'
                f'vertical-align:middle"></span>'
                for k in ("primary", "secondary", "accent") if pal.get(k)
            )
            preview_html = f"""
<div class="card" style="margin-bottom:24px;border:1px solid var(--accent);
     background:rgba(34,211,238,0.04)">
  <h3 style="margin-top:0;margin-bottom:8px">What MediaHub learned about {_h(prof.display_name)}</h3>
  <p style="font-size:14px;color:var(--ink);line-height:1.5;margin:0 0 10px 0">
    {_h(prof.brand_voice_summary or '(no voice summary yet — capture again from a richer source)')}</p>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:4px">Keywords</div>
  <div style="margin-bottom:10px">{kw_chips or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
  <div style="font-size:12px;color:var(--ink-dim);margin-bottom:4px">Palette</div>
  <div style="margin-bottom:10px">{sw or '<span class="dim" style="font-size:12px">(none)</span>'}</div>
  <p class="muted" style="font-size:12px;margin:8px 0 0 0">Source: {_h(prof.brand_source_url or '—')} &middot; captured {_h((prof.brand_captured_at or '')[:19])}</p>
  <div style="margin-top:14px">
    <a class="btn" href="{url_for('add_input_page')}">Looks right &mdash; start creating &rarr;</a>
    <span class="muted" style="margin-left:12px;font-size:12px">Or refine the inputs below and re-analyse.</span>
  </div>
</div>
"""

        _input_style = (
            "width:100%;padding:9px 11px;border:1px solid var(--border);"
            "border-radius:6px;background:var(--bg);color:var(--ink);"
            "font-size:14px;font-family:inherit"
        )

        # Social link inputs — one row per platform, all optional.
        _PLATFORMS = [
            ("instagram", "Instagram",  "https://instagram.com/your-club"),
            ("facebook",  "Facebook",   "https://facebook.com/your-club"),
            ("twitter",   "Twitter / X","https://x.com/your-club"),
            ("tiktok",    "TikTok",     "https://tiktok.com/@your-club"),
            ("linkedin",  "LinkedIn",   "https://linkedin.com/company/your-club"),
        ]
        # Existing guidelines status (when the user has already uploaded once)
        _gl_status_html = ""
        if prof and prof.brand_guidelines_filename:
            g = prof.brand_guidelines or {}
            summary = (g.get("summary") or "")[:280]
            attrs = ", ".join((g.get("voice_attributes") or [])[:6]) or "—"
            n_dos = len(g.get("tone_dos") or [])
            n_donts = len(g.get("tone_donts") or [])
            n_prohib = len(g.get("prohibited_words") or [])
            _gl_status_html = (
                '<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--border);'
                'border-radius:8px;background:rgba(44,201,127,0.05);font-size:12px;line-height:1.5">'
                f'<div style="font-weight:600;color:var(--ink)">Loaded: {_h(prof.brand_guidelines_filename)}</div>'
                f'<div class="muted" style="margin-top:2px">{_h(prof.brand_guidelines_uploaded_at[:19] if prof.brand_guidelines_uploaded_at else "")}'
                f' &middot; {_h(prof.brand_guidelines_status or "")} via {_h(prof.brand_guidelines_extractor or "")}</div>'
                + (f'<div style="margin-top:6px;color:var(--ink-dim)">{_h(summary)}</div>' if summary else "")
                + f'<div style="margin-top:6px;color:var(--ink-dim)">Voice attributes: {_h(attrs)} &middot; '
                f'{n_dos} do{"s" if n_dos != 1 else ""}, {n_donts} don\'t{"s" if n_donts != 1 else ""}, '
                f'{n_prohib} prohibited word{"s" if n_prohib != 1 else ""}.</div>'
                '<div class="muted" style="font-size:11px;margin-top:6px">Upload a new file to replace, or leave blank to keep this one.</div>'
                '</div>'
            )

        social_inputs = ""
        for key, label, placeholder in _PLATFORMS:
            val = social.get(key, "") or ""
            social_inputs += (
                f'<div style="margin-bottom:10px">'
                f'<label style="display:block;font-size:13px;color:var(--ink-dim);'
                f'margin-bottom:4px">{_h(label)} <span class="muted" style="font-size:11px">(optional)</span></label>'
                f'<input type="url" name="social_{key}" value="{_h(val)}" '
                f'placeholder="{_h(placeholder)}" style="{_input_style}"/>'
                f'</div>'
            )

        _ORG_TYPES = [
            ("other", "Other / general"),
            ("swimming_club", "Swimming club"),
            ("athletics", "Athletics club"),
            ("football", "Football / rugby / team sport"),
            ("university_society", "University society or sports club"),
            ("corporate_team", "Corporate team"),
        ]
        org_type_opts = "".join(
            f'<option value="{_h(v)}"{" selected" if v == org_type else ""}>{_h(l)}</option>'
            for v, l in _ORG_TYPES
        )

        capture_url = url_for("organisation_setup_capture")
        body = f"""
<div style="max-width:760px;margin:0 auto">
<div class="mh-section-eyebrow">Step 1 of 1 &middot; First-run setup</div>
<h1 style="margin-top:6px">Tell MediaHub about your organisation</h1>
<p class="dim" style="font-size:15px;line-height:1.5;margin-bottom:28px">
  The content engine learns who you are from your existing online
  presence &mdash; your website and social profiles. Paste whichever
  links you have and click <b>Build my brand</b>. The AI reads your
  posts, palette, tone of voice, and what you talk about, and uses
  that on every caption it writes. You can come back any time to
  re-run it.
</p>

{preview_html}

<form method="POST" action="{capture_url}" enctype="multipart/form-data">
<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Identity</h2>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 18px">
    <div>
      <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
        Organisation name <span style="color:var(--accent)">*</span>
      </label>
      <input type="text" name="display_name" required value="{_h(display_name)}"
             placeholder="e.g. City Aquatics Swimming Club"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
        Type
      </label>
      <select name="org_type" style="{_input_style}">{org_type_opts}</select>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
        Country
      </label>
      <input type="text" name="country" value="{_h(country)}"
             placeholder="e.g. United Kingdom"
             style="{_input_style}"/>
    </div>
    <div>
      <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
        Governing body <span class="muted" style="font-size:11px">(optional)</span>
      </label>
      <input type="text" name="governing_body" value="{_h(governing_body)}"
             placeholder="e.g. Swim England, UKA, BUCS"
             style="{_input_style}"/>
    </div>
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">Where can the AI read you?</h2>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:0 0 14px 0">
    All optional, but paste at least one. The AI reads each link, picks
    up your palette, tone of voice, characteristic phrases and the
    things you actually talk about, and uses that on every caption it
    writes &mdash; so you never have to explain "this is how we sound".
  </p>
  <div style="margin-bottom:14px">
    <label style="display:block;font-size:13px;color:var(--ink-dim);margin-bottom:4px">
      Club website
    </label>
    <input type="url" name="website_url" value="{_h(website_url)}"
           placeholder="https://your-club.example"
           style="{_input_style}"/>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0 18px">
    {social_inputs}
  </div>
</div>

<div class="card" style="margin-bottom:20px">
  <h2 style="margin-top:0;font-size:18px">
    Upload a document with your brand guidelines
    <span class="muted" style="font-size:12px;font-weight:400;margin-left:8px">(optional)</span>
  </h2>
  <p class="dim" style="font-size:13px;line-height:1.5;margin:0 0 14px 0">
    If your team already has a brand or style guide, drop it here. The
    AI reads PDF, Word (.docx), plain text, Markdown, HTML, RTF, or a
    ZIP of any of those, then extracts the voice rules, prohibited
    words, sponsor mention rules, and key messages so every piece of
    content the engine writes respects them. Up to 25 MB.
  </p>
  <input type="file" name="brand_guidelines_file"
         accept=".pdf,.docx,.txt,.md,.markdown,.rtf,.html,.htm,.zip,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,text/html,application/zip"
         style="font-size:13px"/>
  {_gl_status_html}
</div>

<div style="display:flex;align-items:center;gap:14px;margin-bottom:30px">
  <button type="submit" class="btn">Build my brand &rarr;</button>
  <span class="muted" style="font-size:12px">
    Takes 10&ndash;30 seconds. MediaHub analyses each link to learn your tone and style.
  </span>
</div>
</form>
</div>
"""
        return _layout("Set up your organisation", body, active="organisation")

    @app.route("/organisation/setup/capture", methods=["POST"])
    def organisation_setup_capture():
        """Run the AI ingestion on the submitted URLs, save the profile,
        pin it into session, and bounce back to the setup page so the
        user can see what was learned before they click through."""
        display_name = (request.form.get("display_name") or "").strip()
        if not display_name:
            # The HTML form already requires it, but defend in depth.
            return redirect(url_for("organisation_setup"))

        # Slug the org name into a stable, filesystem-safe profile id.
        # If the user already has an active profile, reuse its id so
        # we don't pile up duplicates when they re-run setup.
        existing = _active_profile()
        if existing and existing.display_name.strip().lower() == display_name.lower():
            profile_id = existing.profile_id
        else:
            raw = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
            profile_id = raw[:48] or "default"
            # Avoid clobbering a different org with the same slug.
            if load_profile(profile_id) and (not existing or existing.profile_id != profile_id):
                # Add a short suffix to keep the existing one intact.
                profile_id = f"{profile_id}-{uuid.uuid4().hex[:6]}"

        prof = load_profile(profile_id) or ClubProfile(
            profile_id=profile_id,
            display_name=display_name,
        )
        prof.display_name = display_name
        prof.org_type = (request.form.get("org_type") or "other").strip()
        prof.country = (request.form.get("country") or "").strip()
        prof.governing_body = (request.form.get("governing_body") or "").strip()

        website_url = (request.form.get("website_url") or "").strip()
        social_links: dict[str, str] = {}
        for key in ("instagram", "facebook", "twitter", "tiktok", "linkedin"):
            v = (request.form.get(f"social_{key}") or "").strip()
            if v:
                social_links[key] = v
        prof.social_links = social_links

        # ---- AI capture (handles its own errors, never raises) ----
        try:
            from mediahub.brand.social_dna import capture_from_socials
            result = capture_from_socials(
                social_links=social_links,
                website_url=website_url,
                force=False,
            )
        except Exception as e:
            result = {"brand_capture_status": f"error: {e}"}

        status = (result or {}).get("brand_capture_status", "")
        if status in ("ok", "ok_heuristic"):
            for k in (
                "brand_voice_summary", "brand_keywords",
                "brand_palette_extracted", "brand_logo_url",
                "brand_typography_hint", "brand_phrases_to_avoid",
                "brand_phrases_to_use", "brand_source_url",
                "brand_captured_at", "brand_capture_status",
            ):
                if k in result:
                    setattr(prof, k, result[k])
            vp = result.get("voice_profile") or {}
            if isinstance(vp, dict) and vp:
                prof.voice_profile = vp
            pal = result.get("brand_palette_extracted") or {}
            if pal.get("primary") and prof.brand_primary in ("", "#0A2540", "#A30D2D"):
                prof.brand_primary = pal["primary"]
            if pal.get("secondary") and prof.brand_secondary in ("", "#000000"):
                prof.brand_secondary = pal["secondary"]
        elif status == "no_sources":
            # User submitted no links at all — keep the identity fields
            # and let them try again. The gate will keep them here until
            # is_ready() returns True.
            pass
        else:
            # Any other status: still save what we have so we don't lose
            # the identity fields the user just typed.
            prof.brand_capture_status = status

        # ---- Optional brand-guidelines document upload ----
        # Additive: the AI consumes whatever file the user provided AND
        # the website/socials separately. If no file is attached, this
        # block is a no-op and any previously-uploaded guidelines stay
        # intact on the profile.
        upload = request.files.get("brand_guidelines_file")
        if upload and upload.filename:
            file_bytes = upload.read() or b""
            # Phase 1.5 — reject obvious binary uploads (PNG/JPG
            # screenshots, MP4, etc.) at the boundary so the binary
            # bytes never reach _heuristic_interpret. The downstream
            # guideline parser already has a magic-byte check but
            # surfacing it as a clean user-visible status here is
            # honest: we tell them "that file type isn't supported"
            # rather than silently store a garbage summary that
            # poisons every later caption.
            BINARY_MAGIC = (
                b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff",
                b"GIF87a", b"GIF89a", b"BM",
                b"\x00\x00\x01\x00", b"II*\x00", b"MM\x00*",
                b"\x7fELF", b"MZ",
            )
            ext = (upload.filename.rsplit(".", 1)[-1] or "").lower() if "." in upload.filename else ""
            IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "tiff",
                          "tif", "bmp", "ico", "heic", "heif", "avif"}
            looks_binary = (
                ext in IMAGE_EXTS
                or any(file_bytes.startswith(sig) for sig in BINARY_MAGIC)
            )
            if looks_binary:
                # Friendly status — don't pollute prof.brand_guidelines.
                prof.brand_guidelines_status = (
                    f"unsupported_binary: {upload.filename!r} looks like an "
                    "image / binary file. Brand guidelines must be a text "
                    "document (PDF, DOCX, TXT, RTF, MD)."
                )
                prof.brand_guidelines_filename = upload.filename
                prof.brand_guidelines_byte_size = len(file_bytes)
                # Clear any prior good guidelines? No — preserve them.
            elif file_bytes:
                try:
                    from mediahub.brand.guidelines import ingest_guidelines_file
                    g_payload = ingest_guidelines_file(upload.filename, file_bytes)
                except Exception as e:
                    g_payload = {
                        "brand_guidelines": {},
                        "brand_guidelines_raw_excerpt": "",
                        "brand_guidelines_filename": upload.filename,
                        "brand_guidelines_uploaded_at": "",
                        "brand_guidelines_status": f"error: {e}",
                        "brand_guidelines_extractor": "",
                        "brand_guidelines_byte_size": len(file_bytes),
                    }
                for k, v in g_payload.items():
                    setattr(prof, k, v)

        # ---- AI-derive operating profile from the assembled context ----
        # One LLM call here means zero LLM calls per page render. The
        # derived dict carries the org-specific tone prose, ranking
        # weights, type phrases and artefact intents that every content
        # tool consults via the lookup helpers in brand.derived.
        try:
            from mediahub.brand.derived import derive_operating_profile
            prof.brand_operating_profile = derive_operating_profile(prof)
        except Exception as e:
            # Never block save on a derivation failure — consumers
            # transparently fall back to the hardcoded defaults.
            prof.brand_operating_profile = {
                "tone_prose": {}, "achievement_priorities": {},
                "type_phrases": {}, "artefact_voice": {},
                "status": f"error: {e}",
            }

        save_profile(prof)
        session["active_profile_id"] = prof.profile_id
        return redirect(url_for("organisation_setup"))

    @app.route("/api/organisation/active", methods=["GET", "POST"])
    def organisation_set_active():
        """Read or change the currently-pinned organisation. POST takes
        ``profile_id`` and pins it into the session; GET returns the
        current pin as JSON."""
        if request.method == "POST":
            pid = (request.form.get("profile_id") or "").strip()
            if not pid and request.is_json:
                body = request.get_json(silent=True) or {}
                pid = str(body.get("profile_id") or "").strip()
            if not pid or not load_profile(pid):
                return jsonify({"ok": False, "error": "unknown_profile"}), 404
            session["active_profile_id"] = pid
            return jsonify({"ok": True, "profile_id": pid})
        pid = _active_profile_id()
        prof = _active_profile()
        return jsonify({
            "ok": True,
            "profile_id": pid,
            "display_name": (prof.display_name if prof else ""),
            "is_ready": bool(prof and prof.is_ready()),
        })

    # ---- /pack/<run_id> &mdash; content pack (V7.3 grouped is default; old approval-only at /pack/<run_id>/approved) ---
    @app.route("/pack/<run_id>")
    def content_pack(run_id):
        # V7.3: redirect to the grouped pack which shows engine recommendations
        # in 8 buckets (main_feed, stories, athlete_spotlights, weekend_recap,
        # weekend_in_numbers, internal_notes, needs_review, rejected).
        if _v73_ok and _build_grouped_pack is not None:
            return redirect(url_for("content_pack_grouped", run_id=run_id))
        # Pre-V7.3 fallback: legacy approval-based pack
        return content_pack_approved_only(run_id)

    def content_pack_approved_only(run_id):
        """Legacy V7 approval-only pack. Reachable via /pack/<run_id>/approved."""
        if _run_state(run_id) == "in_progress":
            return _layout("Still processing", _in_progress_page(run_id, "content_pack_approved_only"), active="home")
        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        profile_id = run_data.get("profile_id", "")
        try:
            from mediahub.workflow.pack import build_content_pack as _bcp
            approved = _bcp(run_id, profile_id, RUNS_DIR)
        except Exception as e:
            approved = []

        _review_url = url_for("review", run_id=run_id)
        _mark_all_url = url_for("api_workflow_mark_all_posted", run_id=run_id)
        meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))

        if not approved:
            body = f"""
<p class="dim"><a href="{_review_url}">&larr; Back to review</a></p>
<h1>Content Pack &mdash; {meet_name}</h1>
<div class="card empty">No approved cards yet. Go to <a href="{_review_url}">the review page</a> and approve some cards first.</div>
"""
            return _layout("Content Pack", body, active="home")

        cards_html = ""
        for card in approved:
            ach = card.get("achievement") or {}
            swimmer = _h(ach.get("swimmer_name", ""))
            event = _h(ach.get("event", ""))
            headline = _h(ach.get("headline", ""))
            active_cap = card.get("active_caption") or {}
            brand_captions = card.get("brand_captions") or {}
            cap_headline = _h(active_cap.get("headline", ""))
            cap_body = _h(active_cap.get("body", ""))
            cap_cta = _h(active_cap.get("cta", ""))
            card_id_raw = card.get("_card_id", ach.get("swim_id", ""))
            card_id = _h(card_id_raw)
            card_uuid = str(card_id_raw).replace(":", "_").replace(",", "_")
            wf = card.get("workflow") or {}
            scheduled = _h(card.get("scheduled_for", ""))

            # V7.4: Multi-tone picker for content pack
            if brand_captions:
                tone_labels = {"warm-club": "Warm club", "hype": "Hype", "data-led": "Data-led"}
                pk_tabs = ""
                pk_panels = ""
                for pi, (t_key, t_label) in enumerate(tone_labels.items()):
                    tc = brand_captions.get(t_key) or {}
                    is_active = pi == 0
                    display_style = "" if is_active else "display:none"
                    tc_hl = _h(tc.get("headline", ""))
                    tc_bd = _h(tc.get("body", ""))
                    tc_ct = _h(tc.get("cta", ""))
                    plain = f"{tc.get('headline','') or ''} {tc.get('body','') or ''} {tc.get('cta','') or ''}".strip()
                    pk_tabs += (
                        f'<button class="tone-tab {("active" if is_active else "")}" '
                        f'data-card="pc-{card_uuid}" data-tone="{t_key}" onclick="switchTone(this)" '
                        f'style="font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--border);cursor:pointer;'
                        f'background:{("rgba(34,211,238,0.15)" if is_active else "transparent")};'
                        f'color:{("var(--accent)" if is_active else "var(--ink-dim)")};font-family:inherit;margin-right:4px">'
                        f'{t_label}</button>'
                    )
                    pk_panels += (
                        f'<div class="tone-panel" data-tone="{t_key}" data-card="pc-{card_uuid}" style="{display_style}">'
                        f'<div style="font-size:14px;font-weight:700;margin-bottom:4px">{tc_hl}</div>'
                        f'<div style="font-size:13px;color:var(--ink-dim);margin-bottom:4px">{tc_bd}</div>'
                        f'<div style="font-size:12px;color:var(--accent)">{tc_ct}</div>'
                        f'<textarea id="tone-text-pc-{card_uuid}-{t_key}" style="display:none">{plain}</textarea>'
                        f'</div>'
                    )
                inner_html = (
                    f'<div style="margin-bottom:6px">{pk_tabs}</div>'
                    f'<div class="tone-panels" data-card="pc-{card_uuid}">{pk_panels}</div>'
                )
            else:
                inner_parts = []
                if cap_headline and cap_headline != "&mdash;":
                    inner_parts.append(f'<div style="font-size:14px;font-weight:700;margin-bottom:6px">{cap_headline}</div>')
                if cap_body and cap_body != "&mdash;":
                    inner_parts.append(f'<div style="font-size:13px;color:var(--ink-dim);margin-bottom:8px">{cap_body}</div>')
                if cap_cta and cap_cta != "&mdash;":
                    inner_parts.append(f'<div style="font-size:12px;color:var(--accent)">{cap_cta}</div>')
                inner_html = "".join(inner_parts)
            scheduled_html = (
                f"<span class=\"muted\" style=\"font-size:12px\">Scheduled: {scheduled}</span>"
                if scheduled else ""
            )

            # V7.3: build plain-text copy variants
            if _v73_ok and _build_caption_text:
                try:
                    cap_plain_only = _build_caption_text(card, mode="caption_only")
                    cap_plain_hash = _build_caption_text(card, mode="with_hashtags")
                    cap_plain_full = _build_caption_text(card, mode="full_brief")
                except Exception:
                    cap_plain_only = cap_plain_hash = cap_plain_full = ""
            else:
                _plain_raw = f"{active_cap.get('headline','')} {active_cap.get('body','')} {active_cap.get('cta','')}".strip()
                cap_plain_only = cap_plain_hash = cap_plain_full = _plain_raw

            # Schedule-state pill from workflow sidecar (queued|scheduled|published|failed).
            wf_dict = card.get("workflow") or {}
            sched_state = (wf_dict.get("schedule_status") or "queued").lower()
            sched_pill_class = {
                "scheduled": "good",
                "published": "good",
                "failed":    "bad",
            }.get(sched_state, "")
            sched_pill = (
                f'<span class="tag {sched_pill_class}" data-schedule-pill="pc-{card_uuid}" '
                f'style="font-size:11px;{"display:none" if sched_state == "queued" else ""}">{_h(sched_state)}</span>'
            )
            # V9: "Why this card?" &mdash; explanation for the approved card.
            why_html_pack = _render_why_this_card(card, card_uuid=f"pc-{card_uuid}", run_id=run_id)

            cards_html += f"""
<div class="card" id="pc-{card_id}" style="page-break-inside:avoid">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:12px">
    <div>
      <div style="font-size:13px;font-weight:700;color:var(--ink)">{swimmer} &middot; {event}</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
      {sched_pill}
      <span class="tag good" style="flex-shrink:0">approved</span>
    </div>
  </div>
  <div style="padding:14px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px">
    {inner_html}
  </div>
  <div class="no-print" style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
  {why_html_pack}
  <div style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyActiveTone(this, 'pc-{card_uuid}')">Copy caption</button>
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyCaption(this, 'cap-text-{card_id}-2')">Copy + hashtags</button>
    <button class="btn secondary" style="font-size:12px;padding:5px 12px" onclick="copyCaption(this, 'cap-text-{card_id}-3')">Copy full brief</button>
    <button class="btn" style="font-size:12px;padding:5px 12px"
      onclick="mhScheduleOpen({json.dumps(run_id)}, {json.dumps(str(card_id_raw))}, 'pc-{card_uuid}')"
      data-mh-schedule-btn>Schedule&hellip;</button>
    <textarea id="cap-text-{card_id}-1" style="display:none">{cap_plain_only}</textarea>
    <textarea id="cap-text-{card_id}-2" style="display:none">{cap_plain_hash}</textarea>
    <textarea id="cap-text-{card_id}-3" style="display:none">{cap_plain_full}</textarea>
    {scheduled_html}
  </div>
</div>"""

        body = f"""
<style>
@media print {{
  .no-print {{ display: none !important; }}
  body {{ background: white; color: black; }}
  .card {{ border: 1px solid #ccc; box-shadow: none; }}
}}
</style>
<div class="no-print">
  <p class="dim"><a href="{_review_url}">&larr; Back to review</a></p>
</div>

<h1>Content Pack &mdash; {meet_name}</h1>
<p class="dim">{len(approved)} approved card{"s" if len(approved) != 1 else ""} &middot; ready to post</p>

<div class="no-print" style="margin-bottom:20px;display:flex;gap:10px">
  <form method="post" action="{_mark_all_url}" onsubmit="return confirm('Mark all approved cards as posted?')">
    <button class="btn secondary" type="submit">Mark all posted</button>
  </form>
  <button class="btn secondary" onclick="window.print()">Print / Export PDF</button>
</div>

{cards_html}

{_schedule_modal_html()}

<script>
// Robust copy with execCommand fallback for browsers without clipboard API.
function copyCaption(btn, spanId) {{
  var span = document.getElementById(spanId);
  if (!span) {{ btn.textContent = 'Error'; return; }}
  var text = span.textContent.trim();
  var done = function(ok) {{ btn.textContent = ok ? 'Copied!' : 'Copy failed'; setTimeout(function(){{ btn.textContent = 'Copy caption'; }}, 1800); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{ done(true); }}).catch(function(){{ fallback(); }});
  }} else {{
    fallback();
  }}
  function fallback() {{
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }}
    catch (e) {{ done(false); }}
    document.body.removeChild(ta);
  }}
}}
// V9: Copy "Why this card?" reasoning (textarea-based).
function copyWhyCard(btn, taId) {{
  var ta = document.getElementById(taId);
  if (!ta) {{ return; }}
  var text = ta.value || '';
  var orig = btn.textContent;
  var done = function(ok) {{ btn.textContent = ok ? 'Copied!' : 'Copy failed'; setTimeout(function() {{ btn.textContent = orig; }}, 1500); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function() {{ done(true); }}).catch(function() {{ fb(); }});
  }} else {{ fb(); }}
  function fb() {{
    var t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.left = '-9999px';
    document.body.appendChild(t); t.focus(); t.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }} catch(e) {{ done(false); }}
    document.body.removeChild(t);
  }}
}}
</script>
{_schedule_modal_js()}
"""
        return _layout(f"Content Pack &mdash; {meet_name}", body, active="home")

    # ---- Workflow API --------------------------------------------------
    @app.route("/api/workflow/<run_id>/<card_id>", methods=["POST"])
    def api_workflow_set(run_id, card_id):
        """Set workflow status or edits for a card."""
        ws = _get_wf_store()
        if ws is None:
            return jsonify({"error": "workflow not available"}), 503

        payload = request.get_json(silent=True) or {}
        action = payload.get("action", "set_status")

        if action == "set_status":
            status_str = payload.get("status", "queue")
            try:
                status = CardStatus(status_str)
            except (ValueError, NameError):
                return jsonify({"error": f"invalid status: {status_str}"}), 400
            notes = payload.get("notes")
            ws.set_status(run_id, card_id, status, notes=notes)
            summary = ws.summary(run_id)
            return jsonify({"ok": True, "status": status_str, "summary": summary})

        if action == "set_edits":
            edits = payload.get("edits", {})
            ws.set_edits(run_id, card_id, edits)
            # Auto-bump status to 'edited' if currently in queue, so the user
            # sees that this card has been modified. Don't overwrite approved/posted.
            try:
                cur_state = ws.load(run_id).get(card_id)
                cur_status = cur_state.status if cur_state else CardStatus.QUEUE
                if cur_status == CardStatus.QUEUE:
                    ws.set_status(run_id, card_id, CardStatus.EDITED)
            except Exception:
                pass
            return jsonify({"ok": True, "status": "edited"})

        return jsonify({"error": "unknown action"}), 400

    @app.route("/api/workflow/<run_id>/mark-all-posted", methods=["POST"])
    def api_workflow_mark_all_posted(run_id):
        ws = _get_wf_store()
        if ws is None:
            return redirect(url_for("review", run_id=run_id))
        ws.mark_all_posted(run_id)
        return redirect(url_for("content_pack", run_id=run_id))

    # ---- Turn-Into: one meet &rarr; 7 derivative artefacts -------------------
    @app.route("/api/runs/<run_id>/turn-into", methods=["POST"])
    def api_turn_into(run_id):
        """Generate a Turn-Into pack (up to 7 artefacts) from this run.

        Body (JSON, all optional):
          { "deterministic": bool }   force heuristic mode (no LLM)
          { "async": bool }           run in background, return job_id (default: sync)

        With async=True, returns { job_id, status_url } immediately. Poll
        GET /api/runs/<run_id>/turn-into-status/<job_id> for result.
        """
        run_data = _load_run(run_id)
        if not run_data:
            return jsonify({"error": "run not found"}), 404

        profile_id = run_data.get("profile_id", "")
        profile = load_profile(profile_id) if profile_id else None
        if profile is None:
            profile = ClubProfile(
                profile_id=profile_id or "default",
                display_name=run_data.get("profile_display", "") or "Club",
            )

        payload = request.get_json(silent=True) or {}
        deterministic = bool(payload.get("deterministic", False))
        async_mode = bool(payload.get("async", False))

        def _do_generate(job_id: str) -> None:
            try:
                with app.test_request_context():
                    from mediahub.turn_into import turn_meet_into_pack, save_pack
                    pack = turn_meet_into_pack(run_data, profile, deterministic=deterministic)
                    save_pack(pack, run_id, base_dir=DATA_DIR / "turn_into_packs")
                    pack_url = url_for("turn_into_pack_view",
                                        run_id=run_id, pack_id=pack["pack_id"])
                _turn_into_jobs[job_id] = {
                    "status": "done",
                    # Pack is persisted to disk by save_pack() above; storing
                    # it here too just bloats RAM. The response builders at
                    # lines 9167 and 9182 already strip "pack", so dropping
                    # it from the dict is a no-op for callers.
                    "pack_id": pack["pack_id"],
                    "n_artefacts": len(pack.get("artefacts", [])),
                    "skipped": [s.get("type") for s in pack.get("skipped", [])],
                    "pack_url": pack_url,
                }
            except Exception as e:
                import traceback as _tb
                _turn_into_jobs[job_id] = {
                    "status": "error",
                    "error": str(e),
                    "trace": _tb.format_exc()[-500:],
                }

        import uuid as _uuid
        job_id = _uuid.uuid4().hex

        # Evict any old finished jobs before inserting a new one so the
        # dict can't grow unbounded over a long-running deploy.
        with _active_lock:
            _maybe_evict_turn_into_jobs()

        if async_mode:
            # Async: kick off background thread, return job_id immediately
            _turn_into_jobs[job_id] = {"status": "running"}
            t = threading.Thread(target=_do_generate, args=(job_id,), daemon=True)
            t.start()
            return jsonify({
                "ok": True,
                "job_id": job_id,
                "status": "running",
                "status_url": url_for("api_turn_into_status", run_id=run_id, job_id=job_id),
            })

        # Synchronous (default): block until pack is generated, return final payload
        _turn_into_jobs[job_id] = {"status": "running"}
        _do_generate(job_id)
        job = _turn_into_jobs[job_id]
        if job["status"] == "error":
            return jsonify({"error": "turn_into_failed", "message": job["error"]}), 500
        return jsonify({"ok": True, **{k: v for k, v in job.items() if k != "pack" and k != "status"}})

    @app.route("/api/runs/<run_id>/turn-into-status/<job_id>", methods=["GET"])
    def api_turn_into_status(run_id: str, job_id: str):
        """Poll Turn-Into job status. Returns { status: running|done|error, ... }."""
        job = _turn_into_jobs.get(job_id)
        if job is None:
            return jsonify({"status": "not_found", "error": "job not found"}), 404
        if job["status"] == "running":
            return jsonify({"status": "running"})
        if job["status"] == "error":
            return jsonify({"status": "error", "error": job.get("error", "unknown")}), 500
        return jsonify({
            "ok": True,
            "status": "done",
            **{k: v for k, v in job.items() if k not in ("pack", "status")},
        })

    @app.route("/api/runs/<run_id>/turn-into/<pack_id>/caption", methods=["POST"])
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
        from mediahub.turn_into import load_pack, save_pack
        base = DATA_DIR / "turn_into_packs"
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

    # ------------------------------------------------------------------
    # Newsletter export — Phase 1.2 (output surface)
    # ------------------------------------------------------------------
    #
    # The Turn-Into pipeline already produces a `parent_newsletter`
    # artefact, but it lives inside a generated pack and isn't usable
    # as an actual email body. This endpoint wraps the same builder
    # standalone, renders it through brand.newsletter_renderer, and
    # streams it in the requested format so the user can:
    #   - preview the email in a browser              (GET ?format=html)
    #   - copy the plaintext into Mailchimp / etc.    (GET ?format=text)
    #   - download a ZIP with both files              (GET ?format=zip)
    #
    # All formats use the org's brand colours + logo + display name
    # pulled from the active profile, so the rendered email is
    # on-brand without requiring an extra config step.
    @app.route("/api/runs/<run_id>/newsletter", methods=["GET"])
    def api_run_newsletter(run_id: str):
        fmt = (request.args.get("format") or "html").strip().lower()
        if fmt not in ("html", "text", "zip"):
            return jsonify({"error": "format must be html|text|zip"}), 400
        download = request.args.get("download") == "1"

        run_data = _load_run(run_id)
        if run_data is None:
            return jsonify({"error": "run_not_found"}), 404

        profile_id = run_data.get("profile_id") or ""
        profile = load_profile(profile_id) if profile_id else None
        # Fall back to the session-pinned active profile so a run with
        # no stored profile_id still renders with the user's branding.
        if profile is None:
            profile = _active_profile()

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
                meet_summary, ranked,
                profile=profile, voice_profile=voice_profile,
                brand_kit=brand_kit, deterministic=False,
            )
        except Exception as e:
            return jsonify({"error": f"newsletter_build_failed: {e}"}), 500

        from mediahub.brand.newsletter_renderer import (
            render_email_html, render_plaintext, render_zip,
            safe_filename_for,
        )
        slug = safe_filename_for(
            (run_data.get("meet") or {}).get("name") or run_id
        )

        if fmt == "text":
            body = render_plaintext(artefact)
            resp = Response(body, mimetype="text/plain; charset=utf-8")
            if download:
                resp.headers["Content-Disposition"] = (
                    f'attachment; filename="{slug}-newsletter.txt"'
                )
            return resp
        if fmt == "zip":
            body = render_zip(artefact, profile=profile, meet_summary=meet_summary,
                              base_name=f"{slug}-newsletter")
            resp = Response(body, mimetype="application/zip")
            resp.headers["Content-Disposition"] = (
                f'attachment; filename="{slug}-newsletter.zip"'
            )
            return resp
        # html (default)
        body = render_email_html(artefact, profile=profile, meet_summary=meet_summary)
        resp = Response(body, mimetype="text/html; charset=utf-8")
        if download:
            resp.headers["Content-Disposition"] = (
                f'attachment; filename="{slug}-newsletter.html"'
            )
        return resp

    @app.route("/runs/<run_id>/pack/<pack_id>")
    def turn_into_pack_view(run_id, pack_id):
        """Render a saved Turn-Into pack with the 7 artefacts."""
        from mediahub.turn_into import load_pack
        pack = load_pack(run_id, pack_id, base_dir=DATA_DIR / "turn_into_packs")
        if pack is None:
            return _layout("Not found",
                           '<div class="empty">Turn-Into pack not found.</div>'), 404

        _review_url = url_for("review", run_id=run_id)
        _api_url = url_for("api_turn_into", run_id=run_id)
        _edit_api = url_for("api_turn_into_edit_caption",
                            run_id=run_id, pack_id=pack_id)
        meet_name = _h(pack.get("meet_name", ""))
        gen_at = _h(pack.get("generated_at", ""))

        artefacts = pack.get("artefacts") or []
        skipped = pack.get("skipped") or []

        # --- Skipped notice band
        skipped_html = ""
        if skipped:
            items = "".join(
                f'<li><strong>{_h(s.get("type",""))}</strong>: '
                f'{_h(s.get("reason",""))}</li>'
                for s in skipped
            )
            skipped_html = (
                '<div class="card" style="border-color:var(--warn);background:rgba(245,158,11,0.04)">'
                '<h2 style="margin-top:0">Skipped artefacts</h2>'
                f'<ul style="margin:0">{items}</ul>'
                '</div>'
            )

        # --- Artefact cards
        cards_html = ""
        for art_idx, art in enumerate(artefacts):
            atype = art.get("type", "")
            title = _h(art.get("title", atype))
            captions = art.get("captions") or {}
            cards = art.get("cards") or []
            draft = art.get("draft_flag", "")
            html_block = art.get("html") or ""
            notes_list = art.get("notes") or []

            # Draft badge
            draft_html = ""
            if draft:
                draft_html = (
                    '<div style="margin-bottom:12px;padding:10px 14px;'
                    'background:rgba(245,158,11,0.12);border:1px solid var(--warn);'
                    f'border-radius:8px;font-weight:600;color:var(--warn)">{_h(draft)}</div>'
                )

            # Caption editor blocks &mdash; one per key
            caption_blocks = ""
            for cap_key, cap_val in captions.items():
                if cap_key == "x_thread" and isinstance(cap_val, list):
                    # Special-case: numbered thread of posts.
                    sub = ""
                    for ti, post in enumerate(cap_val):
                        post_chars = len(post or "")
                        cls = "good" if post_chars <= 280 else "bad"
                        sub += (
                            f'<div style="margin-bottom:10px">'
                            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">'
                            f'<span class="muted" style="font-size:11px">Post {ti+1}</span>'
                            f'<span class="tag {cls}" style="font-size:10px">{post_chars}/280</span>'
                            f'</div>'
                            f'<textarea class="ti-cap" data-artefact="{art_idx}" '
                            f'data-thread="{ti}" '
                            f'style="width:100%;min-height:60px;font-size:13px;'
                            f'padding:8px;border:1px solid var(--border);border-radius:6px;'
                            f'background:var(--bg);color:var(--ink);font-family:inherit">'
                            f'{_h(post)}</textarea>'
                            f'</div>'
                        )
                    caption_blocks += (
                        '<div style="margin-bottom:14px">'
                        f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                        f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:8px">X thread '
                        f'({len(cap_val)} posts, &le;280 chars each)</div>'
                        f'{sub}'
                        '</div>'
                    )
                    continue

                # Single string caption
                if not isinstance(cap_val, str):
                    continue
                key_label = cap_key.replace("_", " ").title()
                char_count = len(cap_val)
                # Show Instagram cap for ig caption.
                cap_limit_html = ""
                if cap_key == "instagram":
                    cls = "good" if char_count <= 2200 else "bad"
                    cap_limit_html = f'<span class="tag {cls}" style="font-size:10px;margin-left:8px">{char_count}/2200</span>'
                caption_blocks += (
                    '<div style="margin-bottom:14px">'
                    f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;'
                    f'color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">'
                    f'{_h(key_label)}{cap_limit_html}</div>'
                    f'<textarea class="ti-cap" data-artefact="{art_idx}" '
                    f'data-key="{_h(cap_key)}" '
                    f'style="width:100%;min-height:80px;font-size:13px;'
                    f'padding:10px;border:1px solid var(--border);border-radius:6px;'
                    f'background:var(--bg);color:var(--ink);font-family:inherit">'
                    f'{_h(cap_val)}</textarea>'
                    '</div>'
                )

            # Optional sub-cards strip (e.g. spotlight series)
            sub_cards_html = ""
            if cards and atype in ("swimmer_spotlight",):
                rows = ""
                for c in cards:
                    rows += (
                        '<div style="padding:10px;background:rgba(255,255,255,0.03);'
                        'border:1px solid var(--border);border-radius:8px;margin-bottom:8px">'
                        f'<div style="font-size:13px;font-weight:700">{_h(c.get("swimmer",""))} '
                        f'&middot; {_h(c.get("event",""))}</div>'
                        f'<div style="font-size:12px;color:var(--ink-dim);margin-top:4px">{_h(c.get("headline",""))}</div>'
                        '</div>'
                    )
                sub_cards_html = f'<div style="margin-bottom:12px">{rows}</div>'

            # Newsletter HTML preview
            html_preview_html = ""
            if html_block:
                # Display rendered HTML in a sandboxed-ish preview area.
                # The templates module HTML-escapes the body, so it's safe here.
                html_preview_html = (
                    '<details style="margin-top:8px">'
                    '<summary style="cursor:pointer;font-size:12px;color:var(--accent)">View HTML preview</summary>'
                    f'<div style="margin-top:10px;padding:14px;border:1px dashed var(--border);'
                    f'border-radius:8px;background:rgba(255,255,255,0.02)">{html_block}</div>'
                    '</details>'
                )

            notes_html = ""
            if notes_list:
                lis = "".join(f"<li>{_h(n)}</li>" for n in notes_list)
                notes_html = (
                    '<details style="margin-top:8px">'
                    '<summary style="cursor:pointer;font-size:12px;color:var(--ink-muted)">Why this artefact?</summary>'
                    f'<ul style="margin:8px 0 0 0;font-size:12px;color:var(--ink-dim)">{lis}</ul>'
                    '</details>'
                )

            cards_html += f"""
<div class="card ti-artefact" data-type="{_h(atype)}" data-artefact-index="{art_idx}" style="margin-bottom:18px">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">
    <h2 style="margin:0">{title}</h2>
    <span class="tag info" style="font-size:11px">{_h(atype)}</span>
  </div>
  {draft_html}
  {sub_cards_html}
  {caption_blocks}
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button class="btn" style="font-size:12px;padding:6px 14px"
            onclick="tiSaveArtefact({art_idx})">Save edits</button>
    <span class="ti-status" data-artefact="{art_idx}" style="font-size:11px;color:var(--ink-muted)"></span>
  </div>
  {html_preview_html}
  {notes_html}
</div>"""

        if not cards_html:
            cards_html = '<div class="empty">No artefacts generated.</div>'

        body = f"""
<p class="dim"><a href="{_review_url}">&larr; Back to review</a></p>
<h1>Turn-Into pack &mdash; {meet_name}</h1>
<p class="dim">{len(artefacts)} artefacts &middot; generated {gen_at}</p>

<div style="margin-bottom:16px;display:flex;gap:10px;flex-wrap:wrap">
  <button class="btn secondary" onclick="tiRegenerate()">&#x21BA; Regenerate pack</button>
</div>

{skipped_html}
{cards_html}

<script>
const TI_EDIT_API = {json.dumps(_edit_api)};
const TI_REGEN_API = {json.dumps(_api_url)};
const TI_REVIEW_URL = {json.dumps(_review_url)};

function tiSaveArtefact(idx) {{
  const root = document.querySelector('.ti-artefact[data-artefact-index="' + idx + '"]');
  if (!root) return;
  const status = root.querySelector('.ti-status');
  status.textContent = 'Saving&hellip;';
  const tas = root.querySelectorAll('textarea.ti-cap');
  const tasks = [];
  tas.forEach(function(ta) {{
    const payload = {{ artefact_index: idx, text: ta.value }};
    if (ta.dataset.thread !== undefined) {{
      payload.x_thread_index = parseInt(ta.dataset.thread, 10);
    }} else {{
      payload.caption_key = ta.dataset.key || 'default';
    }}
    tasks.push(fetch(TI_EDIT_API, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload),
    }}).then(r => r.json()));
  }});
  Promise.all(tasks).then(function(results) {{
    const ok = results.every(function(r) {{ return r && r.ok; }});
    status.textContent = ok ? 'Saved.' : 'Some edits failed.';
    setTimeout(function() {{ status.textContent = ''; }}, 2200);
  }}).catch(function() {{ status.textContent = 'Error saving.'; }});
}}

function tiRegenerate() {{
  if (!confirm('Generate a fresh Turn-Into pack? The current pack is preserved.')) return;
  fetch(TI_REGEN_API, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{}}),
  }}).then(r => r.json()).then(function(j) {{
    if (j && j.pack_url) {{
      window.location.href = j.pack_url;
    }} else {{
      alert('Regenerate failed: ' + (j && j.message ? j.message : 'unknown error'));
    }}
  }}).catch(function(err) {{
    alert('Regenerate failed.');
  }});
}}
</script>
"""
        return _layout(f"Turn-Into pack &mdash; {meet_name}", body, active="home")

    @app.route("/pack/<run_id>/grouped")
    def content_pack_grouped(run_id):
        """Grouped content pack page &mdash; 8 buckets."""
        state = _run_state(run_id)
        if state == "in_progress":
            return _layout("Still processing", _in_progress_page(run_id, "content_pack_grouped"), active="home")
        run_data = _load_run(run_id)
        if not run_data:
            return _layout("Not found", '<div class="empty">Run not found.</div>'), 404

        profile_id = run_data.get("profile_id", "")
        meet_name = _h(run_data.get("meet", {}).get("name", "") or run_data.get("profile_display", ""))
        _review_url = url_for("review", run_id=run_id)
        _pack_url = url_for("content_pack", run_id=run_id)
        _reel_url = url_for("api_run_reel", run_id=run_id)
        _newsletter_html_url = url_for("api_run_newsletter", run_id=run_id)
        _newsletter_text_url = _newsletter_html_url + "?format=text"
        _newsletter_zip_url = _newsletter_html_url + "?format=zip"

        if not _v73_ok or _build_grouped_pack is None:
            return redirect(_pack_url)

        try:
            grouped = _build_grouped_pack(run_data, profile_id)
        except Exception as e:
            grouped = {}
            import traceback
            traceback.print_exc()

        counts = grouped.get("_counts", {})

        def _section_html(title, items, icon="", empty_msg="None in this category."):
            n = len(items) if isinstance(items, list) else (1 if items else 0)
            items_list = [items] if isinstance(items, dict) else (items or [])
            section_id = title.lower().replace(" ", "_").replace("/", "")
            rows = ""
            for item in items_list:
                if not item:
                    continue
                ach = item.get("achievement") or item
                swimmer = _h(ach.get("swimmer_name") or item.get("swimmer_name") or "")
                evt = _h(ach.get("event") or item.get("event") or "")
                headline = _h(ach.get("headline") or item.get("headline") or "")
                angle = _h(_humanise(item.get("post_angle") or ""))
                s2p = item.get("safe_to_post") or {}
                s2p_level = s2p.get("level", "needs_review") if isinstance(s2p, dict) else "needs_review"
                s2p_reason = _h(s2p.get("reason", "") if isinstance(s2p, dict) else "")
                s2p_cls = {"safe": "good", "needs_review": "warn", "do_not_post": "bad"}.get(s2p_level, "")
                cap_only = _h(item.get("caption_only") or ach.get("headline") or "")
                cap_hash = _h(item.get("caption_with_hashtags") or "")
                cap_full = _h(item.get("caption_full_brief") or "")
                card_id_raw = ach.get("swim_id") or item.get("card_id") or ""
                card_id = _h(card_id_raw)
                card_uuid = str(card_id_raw).replace(":", "_").replace(",", "_")
                band = _h(item.get("quality_band") or "")
                prio = item.get("priority", 0)
                n_ach = item.get("n_achievements", 0)
                # Schedule state pill (queued|scheduled|published|failed).
                sched_state_raw = (item.get("schedule_status")
                                   or (item.get("workflow") or {}).get("schedule_status")
                                   or "queued")
                sched_state = str(sched_state_raw).lower()
                sched_pill_class = {
                    "scheduled": "good",
                    "published": "good",
                    "failed":    "bad",
                }.get(sched_state, "")
                sched_pill_html = (
                    f'<span class="tag {sched_pill_class}" data-schedule-pill="g-{card_uuid}" '
                    f'style="font-size:11px;{"display:none" if sched_state == "queued" else ""}">{_h(sched_state)}</span>'
                )
                schedule_btn = (
                    f'<button class="btn" style="font-size:12px;padding:4px 10px" data-mh-schedule-btn '
                    f'onclick="mhScheduleOpen({json.dumps(run_id)}, {json.dumps(str(card_id_raw))}, \'g-{card_uuid}\')">'
                    f'Schedule&hellip;</button>'
                ) if card_id_raw else ""
                # Per-card motion download — the endpoint renders (or
                # serves cached) MP4. New tab so the user lands on the
                # video preview rather than blocking the pack page.
                motion_btn = ""
                if card_id_raw:
                    _motion_url = url_for(
                        "api_card_motion", run_id=run_id, card_id=str(card_id_raw),
                    )
                    motion_btn = (
                        f'<a class="btn secondary" style="font-size:12px;padding:4px 10px" '
                        f'href="{_h(_motion_url)}" target="_blank" rel="noopener" '
                        f'title="Render a 6-second branded story-format MP4 for this card. '
                        f'First time can take 30-90s while Remotion runs.">'
                        f'&#x25B6; Motion video</a>'
                    )
                # Per-card sponsor variant — Phase 1.2 deliverable.
                # Sponsor-branded result-card graphic + sponsor-
                # acknowledging caption rendered in a single page.
                sponsor_btn = ""
                if card_id_raw:
                    _sponsor_url = url_for(
                        "sponsor_variant_view",
                        run_id=run_id, card_id=str(card_id_raw),
                    )
                    sponsor_btn = (
                        f'<a class="btn secondary" style="font-size:12px;padding:4px 10px" '
                        f'href="{_h(_sponsor_url)}" target="_blank" rel="noopener" '
                        f'title="Render a sponsor-branded variant: sponsor-tile graphic + '
                        f'sponsor-acknowledging caption for this card.">'
                        f'&#x2605; Sponsor variant</a>'
                    )
                _ra_for_why = {
                    "achievement": ach if isinstance(ach, dict) else (item.get("achievement") or {}),
                    "factors": item.get("factors") or (ach.get("factors") if isinstance(ach, dict) else None) or [],
                    "rank": item.get("rank"),
                }
                _why_uuid = (str(card_id) or section_id).replace(":", "_").replace(",", "_").replace("/", "_") or f"gp-{section_id}"
                why_html = _render_why_this_card(_ra_for_why, card_uuid=f"gp-{_why_uuid}", run_id=run_id)
                # Phase 1.4 — sortable confidence/priority. Stamp the band
                # + priority on the card div so a JS sort handler in the
                # section header can reorder without re-rendering.
                _band_rank = {"elite": 4, "great": 3, "good": 2, "standard": 1}.get(
                    (item.get("quality_band") or "").lower(), 0,
                )
                try:
                    _prio_num = float(item.get("priority", 0) or 0)
                except (TypeError, ValueError):
                    _prio_num = 0.0
                rows += f"""
<div class="card mh-pack-card" id="g-{card_uuid}"
     data-quality-band="{_h(item.get('quality_band') or '')}"
     data-band-rank="{_band_rank}"
     data-priority="{_prio_num:.4f}"
     style="margin-bottom:12px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap">
    <div style="flex:1">
      <div style="font-size:13px;font-weight:700">{swimmer}{(" &middot; " + evt) if evt else ""}</div>
      <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">{headline}</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
      {sched_pill_html}
      {f'<span class="tag">{angle}</span>' if angle else ""}
      <span class="tag {s2p_cls}" title="{s2p_reason}">{s2p_level}</span>
      {f'<span class="tag">{band}</span>' if band else ""}
    </div>
  </div>
  {why_html}
  <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-1')">Copy caption</button>
    <textarea id="cap-{card_id}-1" style="display:none">{cap_only}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-2')">Copy + hashtags</button>
    <textarea id="cap-{card_id}-2" style="display:none">{cap_hash}</textarea>
    <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'cap-{card_id}-3')">Copy full brief</button>
    <textarea id="cap-{card_id}-3" style="display:none">{cap_full}</textarea>
    {motion_btn}
    {sponsor_btn}
    {schedule_btn}
  </div>
</div>"""
            if not rows:
                rows = f'<p class="muted">{_h(empty_msg)}</p>'
            # Phase 1.4 — sort controls. Only render when there's
            # more than one card to sort.
            sort_controls = ""
            if isinstance(items_list, list) and len([x for x in items_list if x]) > 1:
                sort_controls = (
                    f'<span style="font-size:11px;display:flex;gap:4px;align-items:center;'
                    f'margin-right:8px">'
                    f'<span class="muted">Sort:</span>'
                    f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" '
                    f'onclick="event.preventDefault();event.stopPropagation();'
                    f'mhSortPackSection(this, \'band-rank\', \'desc\')">Confidence</button>'
                    f'<button class="btn secondary" style="font-size:11px;padding:3px 8px" '
                    f'onclick="event.preventDefault();event.stopPropagation();'
                    f'mhSortPackSection(this, \'priority\', \'desc\')">Priority</button>'
                    f'</span>'
                )
            return f"""
<details open data-mh-pack-section="{section_id}">
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>{icon} {_h(title)}</span>
    <span style="display:flex;align-items:center">{sort_controls}<span class="tag" style="font-size:12px">{n}</span></span>
  </summary>
  <div class="mh-pack-rows">{rows}</div>
</details>"""

        win = grouped.get("weekend_in_numbers")
        win_html = ""
        if win:
            stats = win.get("stats", [])
            stats_html = "".join(
                f'<div class="stat"><div class="l">{_h(s["label"])}</div><div class="v">{_h(s["value"])}</div></div>'
                for s in stats
            )
            highlights = win.get("highlights", [])
            hl_html = "".join(f'<li>{_h(h)}</li>' for h in highlights)
            cap_txt = _h(win.get("caption_text", ""))
            win_html = f"""
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none">Weekend in numbers</summary>
  <div class="card">
    <div class="stat-block">{stats_html}</div>
    {f'<ul style="margin-top:10px">'+ hl_html +'</ul>' if hl_html else ""}
    <div style="margin-top:10px;display:flex;gap:8px">
      <button class="btn secondary" style="font-size:12px;padding:4px 10px" onclick="copyText(this,'win-cap')">Copy caption</button>
      <textarea id="win-cap" style="display:none">{cap_txt}</textarea>
    </div>
  </div>
</details>"""

        # Build a thumbnail strip of generated visuals if any exist for this run
        visuals_strip = ""
        try:
            vdir = RUNS_DIR / run_id / "visuals"
            if vdir.is_dir():
                tiles = []
                for brief_dir in sorted(vdir.iterdir()):
                    if not brief_dir.is_dir():
                        continue
                    sidecar = brief_dir / "visual.json"
                    if not sidecar.exists():
                        continue
                    try:
                        v = json.loads(sidecar.read_text())
                    except Exception:
                        continue
                    vid = v.get("id", brief_dir.name)
                    fmt = v.get("format", "feed_portrait")
                    cap = (v.get("caption") or "").strip()[:140]
                    fmt_label = {"feed_square": "Square", "feed_portrait": "Portrait", "story": "Story", "reel_cover": "Reel cover"}.get(fmt, fmt)
                    tiles.append(f'''
<div class="card" style="padding:10px;display:flex;flex-direction:column;gap:8px;width:200px;flex:0 0 200px">
  <img src="{url_for('api_visual_png', vid=vid, format_name=fmt)}" alt="" style="width:100%;border-radius:6px;display:block" loading="lazy">
  <div style="font-size:11px;color:var(--ink-dim)">{_h(fmt_label)}</div>
  <div style="font-size:12px;line-height:1.3">{_h(cap)}</div>
  <a class="btn secondary" style="font-size:12px;padding:4px 10px" target="_blank" rel="noopener" href="{url_for('api_visual_png', vid=vid, format_name=fmt)}">Download PNG</a>
</div>''')
                if tiles:
                    _zip_url = url_for("content_pack_zip", run_id=run_id)
                    visuals_strip = f'''
<details open>
  <summary style="cursor:pointer;font-size:16px;font-weight:700;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:12px;list-style:none;display:flex;justify-content:space-between;align-items:center">
    <span>&#x1F3A8; Generated visuals <span class="tag" style="font-size:11px">{len(tiles)}</span></span>
    <a class="btn" style="font-size:12px;padding:6px 14px" href="{_zip_url}">Download all as ZIP</a>
  </summary>
  <div style="display:flex;gap:12px;overflow-x:auto;padding:8px 0 12px">{"".join(tiles)}</div>
</details>'''
        except Exception:
            visuals_strip = ""

        body = f"""
<p class="dim"><a href="{_review_url}">&larr; Back to review</a> &nbsp;|&nbsp; <a href="{_pack_url}">Classic pack view</a></p>
<h1>Content Pack (grouped) &mdash; {meet_name}</h1>

<div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <div style="font-size:13px;font-weight:700">Meet reel</div>
    <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Stitch the top 3 cards into a 15-second branded MP4 reel.</div>
  </div>
  <button class="btn" style="font-size:12px;padding:6px 14px;background:linear-gradient(135deg,#F97316,#EF4444);color:#fff;border:none"
          onclick="generateReelGrouped(this, {repr(_reel_url)})">&#x25B6; Generate reel from this meet</button>
</div>
<div id="reel-panel-grouped" style="display:none;margin-bottom:14px;padding:14px;background:rgba(249,115,22,0.04);border:1px solid var(--border);border-radius:8px"></div>

<div class="card" style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
  <div>
    <div style="font-size:13px;font-weight:700">Parent newsletter</div>
    <div style="font-size:12px;color:var(--ink-dim);margin-top:2px">Branded HTML email + plaintext fallback, ready to paste into Mailchimp / ConvertKit / your email client.</div>
  </div>
  <div style="display:flex;gap:6px;flex-wrap:wrap">
    <a class="btn secondary" style="font-size:12px;padding:6px 12px" href="{_h(_newsletter_html_url)}" target="_blank" rel="noopener">Preview HTML &rarr;</a>
    <a class="btn secondary" style="font-size:12px;padding:6px 12px" href="{_h(_newsletter_html_url)}?download=1">Download .html</a>
    <a class="btn secondary" style="font-size:12px;padding:6px 12px" href="{_h(_newsletter_text_url)}&download=1">Download .txt</a>
    <a class="btn" style="font-size:12px;padding:6px 12px" href="{_h(_newsletter_zip_url)}">Download .zip</a>
  </div>
</div>

{visuals_strip}

{_section_html("Main feed posts", grouped.get("main_feed", []), icon="&#x1F4CC;")}
{_section_html("Stories", grouped.get("stories", []), icon="&#x1F4D6;")}
{_section_html("Athlete spotlights", grouped.get("athlete_spotlights", []), icon="&#x1F31F;", empty_msg="No swimmers with 3+ achievements.")}
{win_html}
{_section_html("Internal notes / nice mentions", grouped.get("internal_notes", []), icon="&#x1F4DD;")}
{_section_html("Needs review", grouped.get("needs_review", []), icon="&#x26A0;")}
{_section_html("Rejected / not recommended", grouped.get("rejected", []), icon="&#x2715;")}

{_schedule_modal_html()}

<script>
function copyText(btn, taId) {{
  var ta = document.getElementById(taId);
  if (!ta) {{ btn.textContent = 'Error'; return; }}
  var text = ta.value;
  var origText = btn.textContent;
  var done = function(ok) {{ btn.textContent = ok ? 'Copied!' : 'Copy failed'; setTimeout(function(){{ btn.textContent = origText; }}, 1800); }};
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(function(){{ done(true); }}).catch(function(){{ fallback(); }});
  }} else {{ fallback(); }}
  function fallback() {{
    var t = document.createElement('textarea');
    t.value = text; t.style.position = 'fixed'; t.style.left = '-9999px';
    document.body.appendChild(t); t.focus(); t.select();
    try {{ var ok = document.execCommand('copy'); done(ok); }} catch(e) {{ done(false); }}
    document.body.removeChild(t);
  }}
}}
// V9: Copy "Why this card?" reasoning.
function copyWhyCard(btn, taId) {{ copyText(btn, taId); }}
function generateReelGrouped(btn, reelUrl) {{
  var panel = document.getElementById('reel-panel-grouped');
  if (!panel) return;
  panel.style.display = '';
  var origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rendering reel&hellip;';
  panel.innerHTML = '<div style="padding:20px;text-align:center;color:var(--ink-muted);font-size:13px">Producing 15-second reel from the top 3 cards&hellip; cold renders may take up to 90s.</div>';
  fetch(reelUrl, {{method:'POST'}})
    .then(function(r) {{
      var ct = r.headers.get('content-type') || '';
      if (r.ok && ct.indexOf('video') !== -1) {{ return r.blob().then(function(b){{ return {{ok:true, blob:b}}; }}); }}
      return r.json().then(function(j){{ return {{ok:false, body:j}}; }});
    }})
    .then(function(res) {{
      btn.disabled = false; btn.textContent = origLabel;
      if (!res.ok) {{
        var msg = (res.body && (res.body.detail || res.body.error)) || 'render failed';
        panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Reel render error: ' + msg + '</div>';
        return;
      }}
      var url = URL.createObjectURL(res.blob);
      panel.innerHTML =
        '<div style="display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap">' +
          '<div style="flex:0 0 220px;max-width:240px">' +
            '<video src="' + url + '" controls playsinline style="width:100%;border-radius:6px;border:1px solid var(--border);background:#000"></video>' +
          '</div>' +
          '<div style="flex:1;min-width:200px">' +
            '<div style="font-size:11px;text-transform:uppercase;color:var(--ink-muted);letter-spacing:0.5px;margin-bottom:6px">Meet reel &middot; 1080&times;1920 &middot; 15s</div>' +
            '<a class="btn secondary" href="' + url + '" download="meet-reel.mp4" style="font-size:12px;padding:4px 12px">Download MP4</a>' +
          '</div>' +
        '</div>';
    }})
    .catch(function(err) {{
      btn.disabled = false; btn.textContent = origLabel;
      panel.innerHTML = '<div style="padding:14px;color:#F87171;font-size:13px">Network error: ' + err + '</div>';
    }});
}}

// Phase 1.4 — sort the cards within one pack section by a data
// attribute on each .mh-pack-card. Toggles between desc / asc on
// repeat clicks of the same key. The DOM is reordered in place,
// avoiding any server round-trip.
window.mhSortPackSection = function(btn, key, defaultDir) {{
  var section = btn.closest('[data-mh-pack-section]');
  if (!section) return;
  var container = section.querySelector('.mh-pack-rows');
  if (!container) return;
  var cards = Array.prototype.slice.call(container.querySelectorAll('.mh-pack-card'));
  if (cards.length < 2) return;
  var prevKey = section.dataset.mhSortKey || '';
  var prevDir = section.dataset.mhSortDir || '';
  var dir = (prevKey === key && prevDir === defaultDir) ? (defaultDir === 'desc' ? 'asc' : 'desc') : defaultDir;
  var attr = 'data-' + key;
  cards.sort(function(a, b) {{
    var av = parseFloat(a.getAttribute(attr)) || 0;
    var bv = parseFloat(b.getAttribute(attr)) || 0;
    return dir === 'desc' ? (bv - av) : (av - bv);
  }});
  cards.forEach(function(c) {{ container.appendChild(c); }});
  section.dataset.mhSortKey = key;
  section.dataset.mhSortDir = dir;
  // Visual marker on the active sort button.
  var allBtns = section.querySelectorAll('button[onclick*="mhSortPackSection"]');
  Array.prototype.forEach.call(allBtns, function(b) {{
    b.style.background = (b === btn) ? 'rgba(34,211,238,0.18)' : '';
    b.style.color = (b === btn) ? 'var(--accent)' : '';
  }});
}};
</script>
{_schedule_modal_js()}
"""
        return _layout(f"Content Pack (grouped) &mdash; {meet_name}", body, active="home")

    # ===================================================================
    # V8: Media library + visuals
    # ===================================================================

    def _v8_brand_kit_for(profile_id: str, run_id: Optional[str] = None):
        # V8.2 Issue 5: per-run brand kit is the only source. Saved club profiles
        # are gone; we look up data/brand_kits/<run_id>.json keyed by run_id.
        rk: Dict[str, Any] = {}
        if run_id:
            try:
                run_kit_path = DATA_DIR / "data" / "brand_kits" / f"{run_id}.json"
                if run_kit_path.exists():
                    rk = json.loads(run_kit_path.read_text()) or {}
            except Exception:
                rk = {}
        display_name = (rk.get("display_name")
                        or profile_id.replace("_", " ").replace("-", " ").title())
        primary = rk.get("primary_colour") or "#0A2540"
        secondary = rk.get("secondary_colour") or "#000000"
        accent = rk.get("accent_colour") or "#FFD86E"
        logo_svg = rk.get("logo_svg") or None
        short_name = rk.get("short_name") or None
        try:
            from mediahub.brand.kit import BrandKit
            bk = BrandKit(profile_id=profile_id, display_name=display_name,
                          primary_colour=primary, secondary_colour=secondary,
                          accent_colour=accent, logo_svg=logo_svg,
                          short_name=short_name)
        except Exception:
            class _BK:
                pass
            bk = _BK()
            bk.profile_id = profile_id
            bk.display_name = display_name
            bk.primary_colour = primary
            bk.secondary_colour = secondary
            bk.accent_colour = accent
            bk.short_name = short_name or ""
            bk.logo_svg = logo_svg
        if rk.get("logo_path"):
            try:
                bk.logo_path = rk["logo_path"]  # type: ignore[attr-defined]
            except Exception:
                pass
        return bk

    @app.route("/media-library")
    def media_library_page():
        """Browse and upload reusable media assets."""
        if not _v8_ok:
            return _layout("Media library", '<div class="empty">V8 media engine unavailable.</div>'), 503
        from flask import request as _req
        profile_id = _req.args.get("profile_id")
        if not profile_id:
            # Pick the first available profile as a sensible default; if no
            # profiles exist, show an explicit empty state pointing at the
            # Organisation page instead of silently bouncing back to home.
            _profs = list_profiles()
            if not _profs:
                _org_url = url_for('organisation_page')
                _add_input_url = url_for('add_input_page')
                empty_body = f"""
<h1>Media library</h1>
<p class="dim">Store reusable photos for your organisation so they can be pulled into branded content cards.</p>
<div class="card" style="text-align:center;padding:48px 32px">
  <div style="font-size:48px;margin-bottom:16px">&#128247;</div>
  <h2 style="margin-bottom:8px">No organisation set up yet</h2>
  <p class="dim" style="margin-bottom:24px">The media library is scoped per organisation. Set up your organisation first, or add an input to auto-create one.</p>
  <a class="btn" href="{_org_url}">Set up organisation &rarr;</a>
  <a class="btn secondary" href="{_add_input_url}" style="margin-left:8px">Or add an input &rarr;</a>
</div>
"""
                return _layout("Media library", empty_body, active="media")
            profile_id = _profs[0].profile_id
        store = _v8_get_media_store()
        assets = store.list(profile_id=profile_id)
        rows_html = ""
        for a in assets[:200]:
            ad = a.to_dict() if hasattr(a, "to_dict") else a
            athlete_names = ", ".join(ad.get("linked_athlete_names") or [])
            _file_url = url_for('api_media_library_file', asset_id=ad.get('id', ''))
            rows_html += f"""
<tr>
  <td><img src=\"{_file_url}\" style=\"max-height:60px;border-radius:4px;\" /></td>
  <td>{ad.get('type','')}</td>
  <td>{athlete_names}</td>
  <td>{ad.get('linked_venue') or ad.get('linked_event') or ''}</td>
  <td>{ad.get('permission_status','')}</td>
  <td><code>{ad.get('id','')[:12]}</code></td>
</tr>"""
        body = f"""
<div class=\"card\">
  <h2>Media library &mdash; {profile_id}</h2>
  <p>Upload reusable photos. Each gets parsed for athlete/venue/event metadata.</p>
  <form method=\"POST\" action=\"{url_for('api_media_library_upload')}\" enctype=\"multipart/form-data\">
    <p><input type=\"file\" name=\"file\" accept=\"image/*\" required></p>
    <p>Description: <input type=\"text\" name=\"description\" placeholder=\"e.g. Eira Hughes at Welsh National Open\" style=\"width:60%\"></p>
    <p>Type: <select name=\"asset_type\">
      <option value=\"athlete_photo\">athlete_photo</option>
      <option value=\"venue\">venue</option>
      <option value=\"team\">team</option>
      <option value=\"action\">action</option>
      <option value=\"podium\">podium</option>
      <option value=\"logo\">logo</option>
    </select></p>
    <input type=\"hidden\" name=\"profile_id\" value=\"{profile_id}\">
    <button type=\"submit\" class=\"btn\">Upload photo</button>
  </form>
</div>
<div class=\"card\">
  <h3>{len(assets)} assets</h3>
  <table style=\"width:100%\">
    <thead><tr><th>Preview</th><th>Type</th><th>Athlete</th><th>Venue/Event</th><th>Permission</th><th>ID</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>
"""
        return _layout("Media library", body, active="media")

    @app.route("/api/media-library", methods=["POST"])
    def api_media_library_upload():
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        f = _req.files.get("file")
        if not f:
            return jsonify({"error": "no_file"}), 400
        profile_id = (_req.form.get("profile_id") or "").strip()
        if not profile_id:
            return jsonify({"error": "profile_id_required"}), 400
        description = _req.form.get("description", "").strip()
        asset_type = _req.form.get("asset_type", "athlete_photo").strip()

        # Save to disk
        upload_dir = UPLOADS_DIR / "media_library" / profile_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        import uuid as _uuid
        ext = Path(f.filename or "upload.jpg").suffix.lower() or ".jpg"
        dest = upload_dir / f"asset_{_uuid.uuid4().hex[:12]}{ext}"
        f.save(str(dest))

        # Parse metadata
        meta = _v8_parse_description(description) if description else {}
        store = _v8_get_media_store()
        from mediahub.media_library.models import MediaAsset
        athlete_names = list(meta.get("athletes") or [])
        asset = MediaAsset(
            id="",
            filename=Path(f.filename or dest.name).name,
            path=str(dest),
            type=asset_type,
            description_raw=description,
            description_parsed=meta,
            profile_id=profile_id,
            linked_athlete_names=athlete_names,
            linked_venue=meta.get("venue"),
            linked_event=meta.get("event"),
            tags=meta.get("tags") or [],
        )
        asset = store.save(asset)
        # AJAX callers get JSON; plain form submissions redirect back to the library.
        if (_req.headers.get("Accept", "").find("application/json") != -1
                or _req.headers.get("X-Requested-With") == "XMLHttpRequest"):
            return jsonify({"ok": True, "asset": asset.to_dict() if hasattr(asset, "to_dict") else asset})
        return redirect(url_for("media_library_page", profile_id=profile_id))

    @app.route("/api/media-library/file/<asset_id>")
    def api_media_library_file(asset_id: str):
        if not _v8_ok:
            return "", 503
        store = _v8_get_media_store()
        a = store.get(asset_id)
        if not a:
            return "", 404
        from flask import send_file
        try:
            return send_file(a.path)
        except Exception:
            return "", 404

    @app.route("/api/runs/<run_id>/cards/<card_id>/create-graphic", methods=["POST"])
    def api_create_graphic(run_id: str, card_id: str):
        """Render a visual for a single content item / recognition card."""
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        # Resolve run + card. Runs are stored as runs_v4/<run_id>.json;
        # also accept the legacy nested runs_v4/<run_id>/run.json layout.
        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
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
            for c in (run_data.get("cards") or []):
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
            "post_angle": ach.get("post_angle") or _req.json.get("post_angle") if _req.is_json else ach.get("post_angle"),
            "meet_name": (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", ""),
            "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
        }

        # V8.1: profile_id is optional. If the user used the two-step upload flow with
        # only a club_filter + per-run brand kit (no saved profile), derive a virtual
        # profile id from the club_filter so brand-kit + media-library lookups still work.
        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        # Slugify
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id)

        # Pull media library assets for this profile
        media_assets = []
        try:
            store = _v8_get_media_store()
            assets = store.list(profile_id=profile_id)
            media_assets = [a.to_dict() if hasattr(a, "to_dict") else a for a in assets]
        except Exception:
            pass

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

        # Variation seed. Default behaviour now: pick a UNIQUE per-card seed
        # so every card in a pack looks visibly different (different layout
        # family, palette permutation, headline phrasing) while still using
        # the club's own colours, logo, and photos.
        # Caller can override with ?variation_seed=N (explicit int).
        # Setting variation_seed=0 explicitly restores the legacy "identity"
        # render (no variation), useful for debugging / regression tests.
        seed_raw = _req.args.get("variation_seed")
        if seed_raw is None or seed_raw == "":
            try:
                from mediahub.creative_brief.generator import auto_variation_seed_for
                variation_seed = auto_variation_seed_for(
                    item.get("swim_id") or item.get("id") or card_id
                )
            except Exception:
                variation_seed = 1
        else:
            try:
                variation_seed = int(seed_raw)
            except (TypeError, ValueError):
                variation_seed = 0

        try:
            res = _v8_create_visual_for_item(
                item, brand_kit,
                profile_id=profile_id, run_id=run_id,
                media_assets=media_assets,
                formats=formats_kw,
                variation_seed=variation_seed,
            )
        except Exception as e:
            return jsonify({"error": f"render_failed: {e}"}), 500
        # V9: Attach the "Why this card?" explanation so JSON consumers can
        # render the same plain-English reasoning the UI shows.
        explanation = _build_card_explanation(target)
        # Include the seed in the response so the UI / debugging can see it.
        return jsonify({
            "ok": True,
            "variation_seed": variation_seed,
            "explanation": explanation,
            **res,
        })

    # ------------------------------------------------------------------
    # Sponsor variant — Phase 1.2 (output surface)
    # ------------------------------------------------------------------
    #
    # Per top-ranked card we can produce a sponsor-flavoured variant:
    #   • visual:  the existing graphic_renderer's `sponsor_branded`
    #              layout family, which is unlocked by passing
    #              sponsor_name through create_visual_for_item;
    #   • caption: a sponsor-acknowledging caption generated via
    #              brand.sponsor.generate_sponsor_caption, which goes
    #              through the regular caption pipeline so brand DNA
    #              + voice profile + guidelines all flow through, with
    #              an explicit "acknowledge sponsor X" requirement on
    #              top.
    # The page is a small server-rendered preview the user can copy
    # from (caption) and download from (visual PNG link via the
    # existing /api/visual/<vid>/png/... route).
    def _load_run_for_card(run_id: str, card_id: str):
        """Shared resolver for the per-card visual / sponsor routes."""
        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            rj = run_dir / "run.json"
            if rj.exists():
                try:
                    run_data = json.loads(rj.read_text())
                except Exception:
                    return None, None
        if run_data is None:
            return None, None
        rr = run_data.get("recognition_report") or {}
        for ra in (rr.get("ranked_achievements") or []):
            ach = ra.get("achievement") or {}
            if ach.get("swim_id") == card_id or ra.get("id") == card_id:
                return run_data, ra
        for c in (run_data.get("cards") or []):
            if c.get("swim_id") == card_id or c.get("id") == card_id:
                return run_data, {"achievement": c}
        return run_data, None

    @app.route("/runs/<run_id>/card/<card_id>/sponsor-variant")
    def sponsor_variant_view(run_id: str, card_id: str):
        """Server-rendered sponsor variant page for one card."""
        run_data, target = _load_run_for_card(run_id, card_id)
        if run_data is None:
            return _layout(
                "Not found",
                '<div class="empty">Run not found.</div>',
                active="home",
            ), 404
        if target is None:
            return _layout(
                "Not found",
                '<div class="empty">Card not found in this run.</div>',
                active="home",
            ), 404

        # Profile resolution: run's profile_id → session-pinned active.
        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or ""
        profile = load_profile(profile_id) if profile_id else None
        if profile is None:
            profile = _active_profile()
        sponsor_name = (getattr(profile, "sponsor_name", "") if profile else "").strip()
        if not sponsor_name:
            body = (
                f'<p class="dim"><a href="{url_for("content_pack_grouped", run_id=run_id)}">'
                f'&larr; Back to content pack</a></p>'
                '<h1>Sponsor variant unavailable</h1>'
                '<div class="card empty">'
                '<p>No sponsor is configured for this organisation.</p>'
                f'<p><a class="btn" href="{url_for("organisation_page")}">'
                'Add a sponsor name on the Organisation page &rarr;</a></p>'
                '</div>'
            )
            return _layout("Sponsor variant", body, active="home")

        ach = target.get("achievement") or {}
        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")

        # ---- 1. Render the sponsor-branded visual via the existing pipeline ----
        visual_html = ""
        visual_error = ""
        if _v8_ok and _v8_create_visual_for_item is not None:
            try:
                item = {
                    "id": ach.get("swim_id") or card_id,
                    "swim_id": ach.get("swim_id") or card_id,
                    "achievement": ach,
                    "post_angle": ach.get("post_angle"),
                    "meet_name": meet_name,
                    "safe_to_post": target.get("safe_to_post") or {"level": "safe"},
                }
                resolved_pid = profile_id or "_run_" + run_id
                resolved_pid = re.sub(r"[^a-z0-9_-]", "-", resolved_pid.lower()).strip("-") or ("_run_" + run_id)
                brand_kit = _v8_brand_kit_for(resolved_pid, run_id=run_id)
                media_assets = []
                try:
                    store = _v8_get_media_store()
                    assets = store.list(profile_id=resolved_pid)
                    media_assets = [a.to_dict() if hasattr(a, "to_dict") else a for a in assets]
                except Exception:
                    pass
                res = _v8_create_visual_for_item(
                    item, brand_kit,
                    profile_id=resolved_pid, run_id=run_id,
                    media_assets=media_assets,
                    sponsor_name=sponsor_name,
                    variation_seed=0,
                )
                visuals = res.get("visuals") or []
                if visuals:
                    v0 = visuals[0]
                    vid = v0.get("id") or v0.get("brief_id")
                    fmt = v0.get("format_name") or "feed_portrait"
                    if vid:
                        img_url = url_for(
                            "api_visual_png", vid=vid, format_name=fmt,
                        )
                        visual_html = (
                            f'<img src="{_h(img_url)}" alt="Sponsor-branded variant" '
                            f'style="max-width:100%;border-radius:10px;border:1px solid var(--border)"/>'
                        )
                    else:
                        visual_error = "Visual rendered but no asset id returned."
                else:
                    errs = res.get("errors") or []
                    visual_error = (
                        "Sponsor-branded visual could not be rendered: "
                        + (errs[0] if errs else "no visuals returned")
                    )
            except Exception as e:
                visual_error = f"render_failed: {e}"
        else:
            visual_error = "Visual pipeline unavailable in this environment."

        # ---- 2. Generate the sponsor-acknowledging caption ----
        caption_text = ""
        caption_error = ""
        caption_unavailable = False
        try:
            from mediahub.brand.sponsor import generate_sponsor_caption
            caption_text = generate_sponsor_caption(ach, profile=profile)
        except Exception as e:
            # Detect "no LLM provider configured" by class name rather than
            # importing ClaudeUnavailableError directly — keeps this surface
            # resilient if the exception module moves.
            if type(e).__name__ == "ClaudeUnavailableError":
                caption_unavailable = True
            else:
                caption_error = str(e)

        # ---- 3. Render the page ----
        _pack_url = url_for("content_pack_grouped", run_id=run_id)
        visual_block = visual_html if visual_html else (
            f'<div class="empty" style="text-align:left;padding:14px">'
            f'<strong style="color:var(--warn)">Visual not available.</strong>'
            f'<br><span class="muted" style="font-size:12px">{_h(visual_error)}</span>'
            '</div>'
        )
        if caption_text:
            caption_block = (
                f'<textarea readonly style="width:100%;min-height:140px;font-size:14px;'
                f'padding:12px;border:1px solid var(--border);border-radius:8px;'
                f'background:var(--bg);color:var(--ink);font-family:inherit">'
                f'{_h(caption_text)}</textarea>'
                f'<button class="btn" style="margin-top:8px;font-size:12px;padding:6px 14px" '
                f'onclick="navigator.clipboard.writeText(this.previousElementSibling.value);'
                f'this.textContent=\'Copied&hairsp;✓\'">Copy caption</button>'
            )
        elif caption_unavailable:
            caption_block = (
                '<div class="empty" style="text-align:left;padding:14px">'
                '<strong>AI captions are unavailable on this deployment.</strong>'
                '<br><span class="muted" style="font-size:13px">'
                'The sponsor-branded visual is still ready to download. '
                'Contact your administrator to enable AI captions.'
                '</span></div>'
            )
        else:
            caption_block = (
                f'<div class="empty" style="text-align:left;padding:14px">'
                f'<strong style="color:var(--warn)">Caption not available.</strong>'
                f'<br><span class="muted" style="font-size:12px">{_h(caption_error)}</span>'
                '</div>'
            )
        swimmer = _h(ach.get("swimmer_name") or "")
        event = _h(ach.get("event") or "")
        body = f"""
<p class="dim"><a href="{_pack_url}">&larr; Back to content pack</a></p>
<h1 style="margin-bottom:4px">Sponsor variant &mdash; {swimmer}{(' &middot; ' + event) if event else ''}</h1>
<p class="dim" style="margin-bottom:24px">Sponsor-branded result card + sponsor-acknowledging caption for <b>{_h(sponsor_name)}</b>. Generated on demand &mdash; refresh to regenerate.</p>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start">
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Sponsor-branded visual</h3>
    {visual_block}
  </div>
  <div class="card">
    <h3 style="margin-top:0;font-size:14px;text-transform:uppercase;letter-spacing:0.5px;color:var(--ink-dim)">Sponsor-acknowledging caption</h3>
    {caption_block}
  </div>
</div>
"""
        return _layout(f"Sponsor variant &mdash; {swimmer}", body, active="home")

    @app.route("/api/runs/<run_id>/cards/<card_id>/regenerate", methods=["POST"])
    def api_regenerate_graphic(run_id: str, card_id: str):
        """Same as create-graphic but explicit re-run for an existing card."""
        return api_create_graphic(run_id, card_id)

    @app.route("/api/runs/<run_id>/cards/<card_id>/regenerate-variants", methods=["POST"])
    def api_regenerate_variants(run_id: str, card_id: str):
        """V8.1 issue 4: produce 3 visibly-different design alternatives.

        Fires three renders with seeds 1, 2, 3 in parallel threads and
        returns ``{variants: [{visual, brief}, ...]}``.
        """
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503

        # Resolve run + card the same way create-graphic does.
        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
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
            for c in (run_data.get("cards") or []):
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
        brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id)

        media_assets = []
        try:
            store = _v8_get_media_store()
            assets = store.list(profile_id=profile_id)
            media_assets = [a.to_dict() if hasattr(a, "to_dict") else a for a in assets]
        except Exception:
            pass

        from concurrent.futures import ThreadPoolExecutor

        def _one(seed: int) -> dict:
            try:
                res = _v8_create_visual_for_item(
                    item, brand_kit,
                    profile_id=profile_id, run_id=run_id,
                    media_assets=media_assets,
                    variation_seed=seed,
                )
                visuals = res.get("visuals") or []
                # Pick the feed_portrait by default if present, else first.
                primary = next((v for v in visuals if v.get("format_name") == "feed_portrait"), visuals[0] if visuals else None)
                return {
                    "seed": seed,
                    "visual": primary,
                    "visuals": visuals,
                    "brief": res.get("brief"),
                    "errors": res.get("errors") or [],
                }
            except Exception as e:
                return {"seed": seed, "visual": None, "visuals": [], "brief": None, "errors": [str(e)]}

        seeds = [1, 2, 3]
        with ThreadPoolExecutor(max_workers=3) as ex:
            variants = list(ex.map(_one, seeds))
        return jsonify({"ok": True, "variants": variants})

    # ------------------------------------------------------------------
    # Motion-graphic + short-form video output (Remotion)
    # ------------------------------------------------------------------
    def _motion_error_payload(e: Exception) -> dict:
        """Translate a raw motion render exception into a user-friendly JSON
        payload. The frontend JS reads `user_message` for display and uses
        `kind` to decide whether to surface a retry button.

        Two known infra classes:
          * ``infra_missing`` — Remotion / Node module isn't installed on
            this deployment (Docker build skipped npm install, or running
            in a dev env without the node_modules). The user can't fix
            this themselves; the operator needs to redeploy.
          * ``timeout`` — render took longer than the configured cap.
            Usually transient; suggest a retry.
        Anything else falls through to ``internal``.
        """
        detail = str(e)
        low = detail.lower()
        if ("cannot find module" in low or "remotion not installed" in low
                or "module not found" in low or "modulenotfound" in low):
            return {
                "error": "render_failed",
                "kind": "infra_missing",
                "detail": detail,
                "user_message": (
                    "Motion video rendering isn't available on this "
                    "deployment. The operator needs to rebuild the "
                    "container so Remotion's Node modules are installed. "
                    "Static graphics and downloads still work in the "
                    "meantime."
                ),
            }
        if "timed out" in low or "timeout" in low:
            return {
                "error": "render_failed",
                "kind": "timeout",
                "detail": detail,
                "user_message": (
                    "Motion video rendering took too long and was cancelled. "
                    "Try again in a few seconds; cold renders sometimes "
                    "take up to 90 seconds."
                ),
            }
        return {
            "error": "render_failed",
            "kind": "internal",
            "detail": detail,
            "user_message": (
                "Motion video rendering failed. Try again, or use "
                "\"Create graphic\" to get a static visual instead."
            ),
        }

    @app.route("/api/runs/<run_id>/card/<card_id>/motion", methods=["POST", "GET"])
    def api_card_motion(run_id: str, card_id: str):
        """Render (or serve cached) MP4 story for a single card.

        Lazy: returns the cached file on cache hit; renders via Remotion on
        cache miss. Always serves the MP4 with the correct mime type so the
        UI can use <video src=&hellip;> or a direct download.
        """
        from flask import send_file
        try:
            from mediahub.visual import motion as _motion
        except Exception as e:
            return jsonify({"error": f"motion_module_unavailable: {e}"}), 503

        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
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
            for c in (run_data.get("cards") or []):
                if c.get("swim_id") == card_id or c.get("id") == card_id:
                    target = {"achievement": c}
                    break
        if target is None:
            return jsonify({"error": "card_not_found"}), 404

        ach = target.get("achievement") or {}
        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
        card_payload = {
            "id": ach.get("swim_id") or card_id,
            "swim_id": ach.get("swim_id") or card_id,
            "achievement": ach,
            "meet_name": meet_name,
        }

        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        try:
            brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id) if _v8_ok else None
        except Exception:
            brand_kit = None

        # Honour the same per-card variation seed as the static graphic, so
        # the motion render visually aligns with the still card.
        try:
            from mediahub.creative_brief.generator import auto_variation_seed_for
            variation_seed = auto_variation_seed_for(
                ach.get("swim_id") or card_id
            )
        except Exception:
            variation_seed = 1

        out_dir = RUNS_DIR / run_id / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{card_id}.mp4"

        try:
            mp4 = _motion.render_story_card(
                card_payload,
                brand_kit,
                out_path,
                variation_seed=variation_seed,
            )
        except RuntimeError as e:
            return jsonify(_motion_error_payload(e)), 500
        except Exception as e:
            return jsonify(_motion_error_payload(e)), 500

        if not Path(mp4).exists():
            return jsonify({
                "error": "render_failed",
                "kind": "internal",
                "detail": "mp4 missing after render",
                "user_message": (
                    "Motion video rendering didn't produce an output file. "
                    "This is usually a transient issue — try again in a few seconds."
                ),
            }), 500
        return send_file(str(mp4), mimetype="video/mp4", as_attachment=False,
                         download_name=f"{card_id}.mp4")

    @app.route("/api/runs/<run_id>/reel", methods=["POST", "GET"])
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

        run_data = _load_run(run_id)
        if run_data is None:
            run_dir = RUNS_DIR / run_id
            run_json = run_dir / "run.json"
            if run_json.exists():
                try:
                    run_data = json.loads(run_json.read_text())
                except Exception as e:
                    return jsonify({"error": f"run_load_failed: {e}"}), 500
            else:
                return jsonify({"error": "run_not_found"}), 404

        try:
            n = int(request.args.get("n", "3"))
        except (TypeError, ValueError):
            n = 3
        n = max(1, min(5, n))

        rr = run_data.get("recognition_report") or {}
        ranked = rr.get("ranked_achievements") or []
        # ranked_achievements is generally already sorted; sort defensively.
        ranked_sorted = sorted(
            ranked,
            key=lambda r: float(r.get("priority", 0.0) or 0.0),
            reverse=True,
        )
        top = ranked_sorted[:n]
        if not top:
            # Fall back to the cards array if no recognition report.
            top = [{"achievement": c} for c in (run_data.get("cards") or [])[:n]]
        if not top:
            return jsonify({"error": "no_cards_for_reel"}), 404

        meet_name = (run_data.get("meet") or {}).get("name") or run_data.get("meet_name", "")
        cards: list[dict] = []
        for ra in top:
            ach = ra.get("achievement") or {}
            cards.append({
                "id": ach.get("swim_id") or ra.get("id") or "",
                "swim_id": ach.get("swim_id") or "",
                "achievement": ach,
                "meet_name": meet_name,
            })

        profile_id = run_data.get("profile_id") or run_data.get("club_filter") or "_run_" + run_id
        profile_id = re.sub(r"[^a-z0-9_-]", "-", profile_id.lower()).strip("-") or ("_run_" + run_id)
        try:
            brand_kit = _v8_brand_kit_for(profile_id, run_id=run_id) if _v8_ok else None
        except Exception:
            brand_kit = None

        out_dir = RUNS_DIR / run_id / "motion"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"reel_{n}.mp4"

        try:
            mp4 = _motion.render_meet_reel(
                cards,
                brand_kit,
                out_path,
                meet_name=meet_name,
            )
        except RuntimeError as e:
            return jsonify(_motion_error_payload(e)), 500
        except Exception as e:
            return jsonify(_motion_error_payload(e)), 500

        if not Path(mp4).exists():
            return jsonify({
                "error": "render_failed",
                "kind": "internal",
                "detail": "mp4 missing after render",
                "user_message": (
                    "Reel rendering didn't produce an output file. "
                    "This is usually a transient issue — try again."
                ),
            }), 500
        return send_file(str(mp4), mimetype="video/mp4", as_attachment=False,
                         download_name=f"meet_reel_{run_id}.mp4")

    @app.route("/api/visual/<vid>")
    def api_visual_get(vid: str):
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            vdir = run_dir / "visuals"
            if not vdir.is_dir():
                continue
            for sub in vdir.iterdir():
                if not sub.is_dir():
                    continue
                sidecar = sub / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    payload = json.loads(sidecar.read_text())
                except Exception:
                    continue
                ids_map = payload.get("visual_ids") or {}
                if payload.get("id") == vid or vid in ids_map:
                    return jsonify(payload)
        return jsonify({"error": "not_found"}), 404

    _VALID_FORMAT_NAMES = {
        "feed_portrait", "feed_square", "feed_landscape",
        "story_portrait", "story_square",
        "twitter_landscape", "twitter_square",
        "print_a4", "print_letter",
    }

    @app.route("/api/visual/<vid>/png/<format_name>")
    def api_visual_png(vid: str, format_name: str):
        if format_name not in _VALID_FORMAT_NAMES:
            return "", 400
        if not _v8_ok:
            return "", 503
        from flask import send_file
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            vdir = run_dir / "visuals"
            if not vdir.is_dir():
                continue
            for brief_dir in vdir.iterdir():
                if not brief_dir.is_dir():
                    continue
                sidecar = brief_dir / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    payload = json.loads(sidecar.read_text())
                except Exception:
                    continue
                # Match either the primary id or any id in the visual_ids map
                ids_map = payload.get("visual_ids") or {}
                if payload.get("id") != vid and vid not in ids_map:
                    continue
                # Determine which format to serve. If vid matches a specific format-id, use that format; else use requested format_name.
                if vid in ids_map:
                    fmt = ids_map[vid]
                else:
                    fmt = format_name
                candidate = brief_dir / f"{fmt}.png"
                if candidate.exists():
                    return send_file(str(candidate), mimetype="image/png")
                # Fall back to the requested format_name
                fallback = brief_dir / f"{format_name}.png"
                if fallback.exists():
                    return send_file(str(fallback), mimetype="image/png")
        return "", 404

    @app.route("/api/runs/<run_id>/venue-search")
    def api_venue_search(run_id: str):
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import request as _req
        q = _req.args.get("q", "").strip()
        if not q:
            return jsonify({"results": []})
        try:
            results = _v8_search_venue(q, limit=8)
            return jsonify({"results": [r.__dict__ if hasattr(r, "__dict__") else r for r in results]})
        except Exception as e:
            return jsonify({"error": str(e), "results": []}), 500

    @app.route("/pack/<run_id>/zip")
    def content_pack_zip(run_id: str):
        """Bundle all generated visuals + captions for a run into a zip download.

        Folder structure (from V8 spec):
          /<run_id>/feed/...png
          /<run_id>/stories/...png
          /<run_id>/reel-covers/...png
          /<run_id>/captions/<visual_id>.txt
          /<run_id>/source-assets/...
          /<run_id>/approval-summary.json
        """
        if not _v8_ok:
            return jsonify({"error": "v8_unavailable"}), 503
        from flask import send_file
        import io, zipfile

        vdir = RUNS_DIR / run_id / "visuals"
        if not vdir.is_dir():
            return _layout(
                "No visuals",
                '<div class="empty">No graphics have been generated for this run yet. Open the recognition page and use "Create graphic" on cards to add some.</div>',
            ), 404

        buf = io.BytesIO()
        approval = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for brief_dir in sorted(vdir.iterdir()):
                if not brief_dir.is_dir():
                    continue
                sidecar = brief_dir / "visual.json"
                if not sidecar.exists():
                    continue
                try:
                    visual = json.loads(sidecar.read_text())
                except Exception:
                    continue
                vid = visual.get("id", brief_dir.name)
                fmt = (visual.get("format") or "").lower()
                if "story" in fmt:
                    sub = "stories"
                elif "reel" in fmt:
                    sub = "reel-covers"
                elif "carousel" in fmt:
                    sub = "carousels"
                else:
                    sub = "feed"
                # Add every PNG in the brief dir
                for png in brief_dir.glob("*.png"):
                    arcname = f"{run_id}/{sub}/{vid}__{png.stem}.png"
                    z.writestr(arcname, png.read_bytes())
                # Caption
                cap = visual.get("caption") or ""
                alt = visual.get("alt_text") or ""
                z.writestr(
                    f"{run_id}/captions/{vid}.txt",
                    f"CAPTION:\n{cap}\n\nALT TEXT:\n{alt}\n",
                )
                approval.append({
                    "id": vid,
                    "format": fmt,
                    "status": visual.get("status", "draft"),
                    "caption": cap,
                    "alt_text": alt,
                    "source_asset_ids": visual.get("source_asset_ids", []),
                    "created_at": visual.get("created_at"),
                })
            z.writestr(
                f"{run_id}/approval-summary.json",
                json.dumps({"run_id": run_id, "items": approval, "count": len(approval)}, indent=2),
            )

        buf.seek(0)
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"content-pack-{run_id}.zip",
            mimetype="application/zip",
        )

    # ---- Global error handlers &mdash; keep tracebacks out of the UI ---------
    @app.errorhandler(404)
    def _not_found_page(e):
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "path": request.path}), 404
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:72px;font-weight:800;letter-spacing:-0.04em;
              background:linear-gradient(135deg,var(--accent),#7c3aed);
              -webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:8px">404</div>
  <h1 style="margin-bottom:8px">Page not found</h1>
  <p class="dim" style="margin-bottom:24px">The page <code>{_h(request.path)}</code> doesn't exist.</p>
  <a class="btn" href="{url_for('home')}">&larr; Back to home</a>
</div>
"""
        return _layout("Not found", body, active="home"), 404

    @app.errorhandler(500)
    def _server_error_page(e):
        try:
            app.logger.exception("Unhandled server error")
        except Exception:
            pass
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "internal_error"}), 500
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:64px;margin-bottom:12px">&#x26A0;</div>
  <h1 style="margin-bottom:8px">Something went wrong</h1>
  <p class="dim" style="margin-bottom:24px;max-width:480px;margin-left:auto;margin-right:auto">
    The page failed to load. Refresh, or try a different action. Nothing you uploaded was lost.
  </p>
  <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
    <a class="btn" href="{url_for('home')}">&larr; Back to home</a>
    <a class="btn secondary" href="javascript:history.back()">Go back</a>
  </div>
</div>
"""
        return _layout("Error", body, active="home"), 500

    @app.errorhandler(413)
    def _payload_too_large(e):
        accepts = request.headers.get("Accept", "") if request else ""
        if "application/json" in accepts or request.path.startswith("/api/"):
            return jsonify({"error": "file_too_large", "max_mb": 50}), 413
        body = f"""
<div style="text-align:center;padding:64px 24px">
  <div style="font-size:64px;margin-bottom:12px">&#x1F4E6;</div>
  <h1 style="margin-bottom:8px">File too large</h1>
  <p class="dim" style="margin-bottom:24px">The upload exceeded 50 MB. Try compressing or trimming the file first.</p>
  <a class="btn" href="{url_for('home')}">&larr; Back to home</a>
</div>
"""
        return _layout("File too large", body, active="home"), 413

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
