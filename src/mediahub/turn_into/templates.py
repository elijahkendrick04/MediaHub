"""
turn_into/templates.py — eight artefact builders.

Each builder consumes:
  - ``meet_summary``: small dict {name, start_date, course, venue, profile_display}
  - ``top_achievements``: list of RankedAchievement dicts (already ranked)
  - ``profile``: ClubProfile
  - ``voice_profile``: VoiceProfile (used for sign_off + name style)
  - ``brand_kit``: BrandKit (used for club display name)
  - ``deterministic``: if True, never call the LLM — use heuristic copy

Each returns a single artefact dict shaped like::

    {
      "type": "<artefact-key>",
      "title": "Human-readable title",
      "captions": {
        "default": "...",
        "instagram": "...",  # only when relevant (≤2,200 chars)
        "x_thread":  [post1, post2, ...],  # only for data_thread
        "linkedin":  "...",  # only where relevant
      },
      "cards": [ { swimmer, event, headline, body } ... ],
      "html": "...",  # only for parent_newsletter
      "draft_flag": "DRAFT — review with coach before publishing",
        # only for coach_quote
      "notes": [...],  # explainability notes
    }

Builders MUST stay tolerant: missing fields produce a sensible fallback, not
a crash.
"""

from __future__ import annotations

from typing import Optional


# --- Tone-system prompt fragments ---------------------------------------
#
# These are tone-cues we append to the LLM system prompt so the artefact
# language matches the loaded club voice. We do NOT introduce new tones;
# we reuse the existing tone keys ("warm-club", "hype", "data-led") and
# layer per-artefact intent on top.

_ARTEFACT_INTENTS: dict[str, str] = {
    "meet_recap": (
        "Write a single short feed caption (~280 chars) summarising the "
        "whole meet from the club's voice. Lead with the strongest moment. "
        "Never invent numbers."
    ),
    "swimmer_spotlight": (
        "Write a single short feed caption (~280 chars) celebrating ONE "
        "named swimmer's standout swim. Use their first name. Do not invent."
    ),
    "data_thread_post": (
        "Write one numbered post for a data-led thread on X/Twitter. "
        "Strict ≤280 character cap. One fact per post, no filler, numbers "
        "first. Return only the post text, no 'Post 1:' prefix."
    ),
    "linkedin_long": (
        "Write a single longer LinkedIn-style summary of this meet, "
        "around 120-200 words. Professional, sponsor-friendly, lead with "
        "the headline result, finish with a brief acknowledgement."
    ),
    "instagram_long": (
        "Write a single Instagram caption (≤2,200 characters) celebrating "
        "the meet. Warm, club voice, 2-4 short paragraphs, no hashtag "
        "spam — at most 4 hashtags at the end."
    ),
    "parent_newsletter": (
        "Write a parent-friendly newsletter paragraph (~200 words). Plain, "
        "warm, free of jargon. Mention 2-3 names at most. End with a "
        "single sentence about what is coming next if known."
    ),
    "newsletter_subject": (
        "Write an email subject line (max 55 characters) and a preheader "
        "line (max 90 characters) for this parent-newsletter update. "
        "Specific and warm, never clickbait. No emoji in the subject."
    ),
    "club_report": (
        "Write a long-form club website report of this meet — roughly "
        "350-450 words across 4-6 short paragraphs. Open with the headline "
        "story of the weekend, work through the standout swims with their "
        "real names, events and times, give the wider squad a paragraph, "
        "and close with a short look ahead. Plain prose in the club's "
        "voice, third person — no markdown headings, no bullet lists. "
        "Use ONLY the facts provided; never invent a swimmer, time, "
        "placing or quote."
    ),
    "sponsor_thank_you": (
        "Write a single short post (~280 chars) thanking the sponsor by "
        "name for supporting this meet. Specific, sincere, not gushing."
    ),
    "coach_quote": (
        "Draft ONE coach-style quote (~2 sentences) that the head coach "
        "could plausibly say about this meet, grounded only in the "
        "achievement facts given. Mark clearly that it is a draft."
    ),
    "next_meet_preview": (
        "Write a short teaser (~200 chars) for the upcoming meet. Lead with "
        "the meet name and date if given, and build anticipation with "
        "specifics (who's competing, what's at stake) — not generic hype, "
        "and no invented data."
    ),
}


# --- Helpers ------------------------------------------------------------


def _ach_payload(ra: dict) -> dict:
    """Flatten a RankedAchievement into the payload our LLM expects.

    Mirrors :func:`mediahub.web.web.api_live_caption`'s shape so the LLM
    sees a consistent contract."""
    a = ra.get("achievement") or {}
    swimmer_name = a.get("swimmer_name", "") or ""
    parts = swimmer_name.split(" ", 1)
    rf = a.get("raw_facts") or {}
    return {
        "swimmer_first": parts[0] if parts else "",
        "swimmer_last": parts[1] if len(parts) > 1 else "",
        "swimmer_name": swimmer_name,
        "event": a.get("event", ""),
        "time": rf.get("time_str") or a.get("time", ""),
        "pb": bool(a.get("pb")) or a.get("type", "").startswith("pb"),
        "type": a.get("type", ""),
        "headline": a.get("headline", ""),
        "place": rf.get("place") or a.get("place", ""),
    }


def _club_brand(meet_summary: dict, brand_kit, profile, voice_profile) -> dict:
    """Build the `club_brand` payload for ai_caption.generate_caption_for_tone."""
    short = ""
    display = ""
    try:
        short = (brand_kit.short_name or "") if brand_kit else ""
        display = (brand_kit.display_name or "") if brand_kit else ""
    except Exception:
        pass
    return {
        "club_name": display or (profile.display_name if profile else "") or "",
        "club_short": short or (profile.short_name if profile else "") or "",
        "meet_name": meet_summary.get("name", ""),
        "tone": (voice_profile.tone if voice_profile else "") or "warm-club",
        "name_style": (voice_profile.name_style if voice_profile else "first_name"),
        "sign_off": (voice_profile.sign_off if voice_profile else "") or "",
        "sponsor_name": (profile.sponsor_name if profile else "") or "",
    }


def _ach_line(d: dict) -> str:
    """Render one flattened achievement payload (the dict shape returned
    by :func:`_ach_payload`) as a single readable English clause, for use
    inside an aggregate-artefact brief."""
    if not isinstance(d, dict):
        return ""
    name = (d.get("swimmer_name") or "").strip()
    event = (d.get("event") or "").strip()
    time = (d.get("time") or "").strip()
    headline = (d.get("headline") or "").strip()
    place = d.get("place")

    if event and time:
        ev = f"{event} in {time}"
    elif event:
        ev = event
    elif time:
        ev = time
    else:
        ev = ""
    core = f"{name} — {ev}" if (name and ev) else (name or ev)

    extras: list[str] = []
    try:
        p = int(place) if place not in (None, "") else None
    except (TypeError, ValueError):
        p = None
    if p:
        ord_suffix = {1: "st", 2: "nd", 3: "rd"}.get(p, "th")
        extras.append(f"{p}{ord_suffix} place")
    if d.get("pb"):
        extras.append("a personal best")
    if extras:
        core = f"{core} ({', '.join(extras)})" if core else ", ".join(extras)
    if headline and headline.lower() not in core.lower():
        core = f"{core} — {headline}" if core else headline
    return core.strip(" —")


def _narrate_brief(payload: dict) -> str:
    """Turn an aggregate artefact payload (keyed by ``kind``) into a single
    English paragraph for the caption model. Returns ``""`` for unknown
    kinds so the caller falls back to the single-swim narration path."""
    kind = (payload.get("kind") or "").strip()
    meet = (payload.get("meet") or "").strip() or "the meet"

    def _lines(key: str) -> list[str]:
        return [ln for ln in (_ach_line(x) for x in (payload.get(key) or [])) if ln]

    if kind == "meet_recap":
        course = (payload.get("course") or "").strip()
        heads = _lines("headliners")
        s = f"Write a feed recap of {meet}"
        if course:
            s += f" ({course})"
        s += "."
        if heads:
            s += " The standout performances were: " + "; ".join(heads) + "."
        else:
            s += " No individual standouts were flagged — keep it about the squad as a whole."
        return s
    if kind == "thread_intro":
        try:
            n = int(payload.get("n_top") or 0)
        except (TypeError, ValueError):
            n = 0
        s = f"This is the opening post of a data-led thread about {meet}."
        if n:
            s += f" There are {n} ranked moments to tease in the posts that follow."
        return s
    if kind == "thread_linkedin":
        highs = _lines("highlights")
        s = f"Summarise {meet} for a LinkedIn audience."
        if highs:
            s += " Key results: " + "; ".join(highs) + "."
        return s
    if kind == "newsletter":
        club = (payload.get("club") or "").strip()
        heads = _lines("headliners")
        s = f"Write a parent-and-supporter newsletter update about {meet}"
        if club:
            s += f" for {club}"
        s += "."
        if heads:
            s += " Headline swims to mention: " + "; ".join(heads) + "."
        return s
    if kind == "club_report":
        club = (payload.get("club") or "").strip()
        course = (payload.get("course") or "").strip()
        venue = (payload.get("venue") or "").strip()
        dates = (payload.get("dates") or "").strip()
        heads = _lines("headliners")
        s = f"Write the club website report of {meet}"
        if club:
            s += f" for {club}"
        bits = [b for b in (venue, course, dates) if b]
        if bits:
            s += f" ({', '.join(bits)})"
        s += "."
        if heads:
            s += " The verified results to work from: " + "; ".join(heads) + "."
        else:
            s += " No individual standouts were flagged — write it about the squad as a whole."
        s += " These are the only verified facts — the report must not go beyond them."
        return s
    if kind == "sponsor_thank_you":
        sponsor = (payload.get("sponsor") or "").strip() or "our sponsor"
        guide = (payload.get("sponsor_guidelines") or "").strip()
        s = f"Thank the sponsor {sponsor} for supporting {meet}."
        if guide:
            s += f" Sponsor guidelines to respect: {guide}"
        return s
    if kind == "coach_quote":
        highs = _lines("highlights")
        s = f"Draft a single coach-style quote reflecting on {meet}."
        if highs:
            s += " Performances the coach can refer to: " + "; ".join(highs) + "."
        else:
            s += " No specific standouts were flagged — keep it about squad effort and progress."
        return s
    if kind == "next_meet_preview":
        nm = payload.get("next_meet") or {}
        nm_name = (nm.get("name") or "").strip()
        nm_date = (nm.get("date") or "").strip()
        prev = (payload.get("previous_meet") or "").strip()
        s = "Write a short teaser for the upcoming meet"
        if nm_name:
            s += f" {nm_name}"
        if nm_date:
            s += f" ({nm_date})"
        s += "."
        if prev:
            s += f" It follows on from {prev}."
        return s
    return ""


def _note_source(meta: Optional[dict], source: str, error: str = "") -> None:
    """Record where a text came from (``ai`` | ``fallback`` | ``deterministic``).

    ``meta`` is an optional caller-owned dict; ``error`` carries the exception
    class name on a fallback so the pack can say *why* the copy is templated."""
    if meta is None:
        return
    meta["source"] = source
    if error:
        meta["error"] = error


def _pack_source(metas: list[dict]) -> tuple[str, Optional[str]]:
    """Aggregate per-text sources → (artefact ``source``, optional honesty note).

    An artefact is ``fallback`` when any of its texts silently dropped to the
    deterministic template after an LLM failure — the review UI badges those so
    template copy is never indistinguishable from AI-written copy."""
    fb = [m for m in metas if m.get("source") == "fallback"]
    if fb:
        errs = sorted({str(m.get("error") or "") for m in fb} - {""})
        detail = f" (LLM failure: {', '.join(errs)})" if errs else ""
        return "fallback", (
            f"{len(fb)} of {len(metas)} texts used the deterministic template "
            f"fallback{detail} — not AI-written."
        )
    if metas and all(m.get("source") == "ai" for m in metas):
        return "ai", None
    return "deterministic", None


def _gen_caption(
    payload: dict,
    club_brand: dict,
    *,
    tone: str,
    intent_key: str,
    deterministic: bool,
    fallback_text: str,
    profile=None,
    meta: Optional[dict] = None,
) -> str:
    """Generate one caption via the existing primitive, or return fallback.

    The function is deliberately defensive — any exception falls back to
    the deterministic text, so the pipeline never crashes if the LLM is
    flaky. ``meta`` (when given) records the outcome via :func:`_note_source`
    so a fallback is visible in the pack, never silent.

    The artefact intent is resolved through ``brand.derived`` so a
    derived operating profile can override the hardcoded default with
    org-specific creative direction. Falls back to the hardcoded
    default when no derived intent exists.
    """
    if deterministic:
        _note_source(meta, "deterministic")
        return fallback_text
    try:
        from mediahub.web.ai_caption import generate_caption_for_tone
    except Exception as e:
        _note_source(meta, "fallback", type(e).__name__)
        return fallback_text
    default_intent = _ARTEFACT_INTENTS.get(intent_key, "")
    try:
        from mediahub.brand.derived import artefact_intent_for

        intent = artefact_intent_for(profile, intent_key, default_intent)
    except Exception:
        intent = default_intent
    enriched = dict(payload)
    # Tag the payload with the artefact key + intent so the caption
    # pipeline can (a) inject the AI-derived creative intent into the
    # system prompt, and (b) look up the platform format rules for
    # this artefact via brand.derived.platform_format_for.
    enriched["_artefact_key"] = intent_key
    if intent:
        enriched["_artefact_intent"] = intent
    # Aggregate artefacts (meet recap, thread intro/LinkedIn, newsletter,
    # sponsor thank-you, coach quote, next-meet preview) describe a whole
    # meet, not one swim. narrate_achievement only understands a single
    # swim, so it returned empty prose for these — which made
    # generate_caption_for_tone raise and silently drop the artefact to
    # the heuristic fallback, i.e. NOT AI-written. Narrate the brief here
    # and feed it through the model's brief_prose channel so these
    # artefacts are genuinely AI-made. Single-swim payloads carry no
    # "kind" and keep the narrate_achievement path untouched.
    brief_prose = _narrate_brief(payload) if payload.get("kind") else None
    try:
        text = generate_caption_for_tone(
            enriched,
            club_brand,
            tone=tone,
            club_profile=profile,
            brief_prose=brief_prose,
        )
    except Exception as e:
        _note_source(meta, "fallback", type(e).__name__)
        return fallback_text
    text = (text or "").strip()
    if not text:
        _note_source(meta, "fallback", "EmptyCompletion")
        return fallback_text
    _note_source(meta, "ai")
    return text


def _gen_longform(
    payload: dict,
    club_brand: dict,
    *,
    tone: str,
    intent_key: str,
    deterministic: bool,
    fallback_text: str,
    profile=None,
    max_tokens: int = 1400,
    meta: Optional[dict] = None,
) -> str:
    """Generate one long-form artefact body via the cloud LLM, or fallback.

    ``generate_caption_for_tone`` is capped at caption length (400 tokens),
    so artefacts that need real word count (the club website report) go
    straight to ``media_ai.generate`` with the same brand briefing the
    caption path uses. Defensive like :func:`_gen_caption` — any failure
    returns the deterministic fallback (recorded in ``meta``) so the pack
    never crashes but a templated body is never silent.
    """
    if deterministic:
        _note_source(meta, "deterministic")
        return fallback_text
    default_intent = _ARTEFACT_INTENTS.get(intent_key, "")
    try:
        from mediahub.brand.derived import artefact_intent_for

        intent = artefact_intent_for(profile, intent_key, default_intent)
    except Exception:
        intent = default_intent

    system_parts = [
        "You write long-form editorial copy for a sports club, in the club's voice.",
        intent,
        f"Voice register: {tone}.",
        "Use ONLY the facts in the brief. Never invent a swimmer, a time, a "
        "placing or a quote. Output only the finished copy — no headings, "
        "no markdown, no preamble.",
    ]
    # Same cliché guardrail the caption path applies — the long-form artefacts
    # (club report, newsletter) build their own prompt and never went through
    # _compose_caption_prompt, so name the banned AI tells explicitly here too.
    # One shared source of truth in ai_core.prompt_guard.
    try:
        from mediahub.ai_core.prompt_guard import CAPTION_AI_TELL_INSTRUCTION

        system_parts.append(CAPTION_AI_TELL_INSTRUCTION)
    except Exception:
        pass
    if profile is not None:
        try:
            from mediahub.brand.context import brand_context_for_llm

            brand_prose = brand_context_for_llm(profile)
            if brand_prose:
                system_parts.insert(0, brand_prose)
        except Exception:
            pass
    sponsor = (club_brand.get("sponsor_name") or "").strip()
    if sponsor:
        system_parts.append(
            f"The club's sponsor is {sponsor} — a brief, natural mention is welcome."
        )

    brief = _narrate_brief(payload) or fallback_text
    try:
        from mediahub.media_ai.llm import generate

        text = generate(
            brief, system="\n\n".join(p for p in system_parts if p), max_tokens=max_tokens
        )
    except Exception as e:
        _note_source(meta, "fallback", type(e).__name__)
        return fallback_text
    text = (text or "").strip()
    if not text:
        _note_source(meta, "fallback", "EmptyCompletion")
        return fallback_text
    _note_source(meta, "ai")
    return text


def _format_name(voice_profile, swimmer_first: str, swimmer_last: str) -> str:
    """Use the voice profile's name_style if available, else first name."""
    if voice_profile is None:
        return swimmer_first or swimmer_last or "the swimmer"
    try:
        return voice_profile.get_name(swimmer_first, swimmer_last)
    except Exception:
        return swimmer_first or swimmer_last or "the swimmer"


def _apply_sign_off(voice_profile, text: str) -> str:
    if not voice_profile:
        return text
    try:
        return voice_profile.apply_sign_off(text)
    except Exception:
        return text


def _top_swimmers(top_achievements: list[dict], n: int) -> list[dict]:
    """Pick the top N distinct swimmers by best priority."""
    seen: dict[str, dict] = {}
    for ra in top_achievements:
        a = ra.get("achievement") or {}
        key = a.get("swimmer_id") or a.get("swimmer_name") or ""
        if not key:
            continue
        if key in seen:
            continue
        seen[key] = ra
        if len(seen) >= n:
            break
    return list(seen.values())


# --- 1. Meet recap ------------------------------------------------------


def build_meet_recap(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> dict:
    """One feed-format card + caption summarising the whole meet."""
    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    top = top_achievements[:1]
    headline_ach = top[0] if top else None

    if headline_ach:
        a = headline_ach.get("achievement") or {}
        head_swimmer = a.get("swimmer_name", "the team")
        head_event = a.get("event", "")
        head_headline = a.get("headline", "")
        fallback_default = (
            f"{meet_summary.get('name', 'Meet')} recap: "
            f"{head_swimmer}{' on the ' + head_event if head_event else ''} led the way. "
            f"{head_headline}".strip()
        )[:280]
    else:
        fallback_default = (
            f"{meet_summary.get('name', 'A great meet')} — proud of every swim. "
            f"Full recap incoming."
        )[:280]

    payload = {
        "kind": "meet_recap",
        "meet": meet_summary.get("name", ""),
        "course": meet_summary.get("course", ""),
        "headliners": [_ach_payload(ra) for ra in top_achievements[:5]],
    }
    meta_default: dict = {}
    default_caption = _gen_caption(
        payload,
        club_brand,
        tone=tone,
        intent_key="meet_recap",
        deterministic=deterministic,
        fallback_text=fallback_default,
        profile=profile,
        meta=meta_default,
    )
    default_caption = _apply_sign_off(voice_profile, default_caption)

    # Instagram variant — longer, slightly different framing.
    fallback_ig = (
        f"{meet_summary.get('name', 'The meet')} is in the books.\n\n"
        f"{fallback_default}\n\n"
        f"Proud of everyone who raced. More results in the comments."
    )
    meta_ig: dict = {}
    ig_caption = _gen_caption(
        payload,
        club_brand,
        tone=tone,
        intent_key="instagram_long",
        deterministic=deterministic,
        fallback_text=fallback_ig,
        profile=profile,
        meta=meta_ig,
    )
    ig_caption = _apply_sign_off(voice_profile, ig_caption)
    if len(ig_caption) > 2200:
        ig_caption = ig_caption[:2197] + "..."

    card = {
        "swimmer": (headline_ach.get("achievement", {}) if headline_ach else {}).get(
            "swimmer_name", ""
        ),
        "event": (headline_ach.get("achievement", {}) if headline_ach else {}).get("event", ""),
        "headline": (headline_ach.get("achievement", {}) if headline_ach else {}).get(
            "headline", meet_summary.get("name", "")
        ),
        "body": (headline_ach.get("achievement", {}) if headline_ach else {}).get("headline", ""),
    }

    source, source_note = _pack_source([meta_default, meta_ig])
    notes = [
        "Built from top achievement: "
        + (
            (headline_ach.get("achievement", {}) if headline_ach else {}).get(
                "headline", "no achievement available"
            )
        )
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "meet_recap",
        "title": f"Meet recap — {meet_summary.get('name', 'Meet')}",
        "source": source,
        "captions": {
            "default": default_caption,
            "instagram": ig_caption,
        },
        "cards": [card],
        "notes": notes,
    }


# --- 2. Swimmer spotlight series ----------------------------------------


def build_swimmer_spotlights(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
    max_swimmers: int = 3,
) -> dict:
    """One card per top-3 distinct swimmer in the meet."""
    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    picks = _top_swimmers(top_achievements, max_swimmers)

    cards: list[dict] = []
    captions: dict[str, str] = {}
    notes: list[str] = []
    gen_metas: list[dict] = []

    for idx, ra in enumerate(picks, start=1):
        a = ra.get("achievement") or {}
        payload = _ach_payload(ra)
        display_name = _format_name(
            voice_profile, payload["swimmer_first"], payload["swimmer_last"]
        )
        fallback = (
            f"Spotlight: {display_name} — {payload.get('event', '')} "
            f"{('(' + payload['time'] + ')') if payload.get('time') else ''} "
            f"{payload.get('headline', '')}"
        ).strip()[:280]
        gen_meta: dict = {}
        caption = _gen_caption(
            payload,
            club_brand,
            tone=tone,
            intent_key="swimmer_spotlight",
            deterministic=deterministic,
            fallback_text=fallback,
            profile=profile,
            meta=gen_meta,
        )
        gen_metas.append(gen_meta)
        caption = _apply_sign_off(voice_profile, caption)
        key = f"swimmer_{idx}"
        captions[key] = caption
        cards.append(
            {
                "rank": idx,
                "swimmer": a.get("swimmer_name", display_name),
                "event": a.get("event", ""),
                "headline": a.get("headline", ""),
                "body": caption,
            }
        )
        notes.append(
            f"Spotlight #{idx}: {a.get('swimmer_name','')} · "
            f"priority {ra.get('priority', 0.0):.2f}"
        )

    if not cards:
        notes.append("No swimmers available to spotlight from this meet.")

    source, source_note = _pack_source(gen_metas)
    if source_note:
        notes.append(source_note)

    return {
        "type": "swimmer_spotlight",
        "title": "Swimmer spotlight series",
        "source": source,
        "captions": captions,
        "cards": cards,
        "notes": notes,
    }


# --- 3. Data-led thread (3-5 posts for X / one long for LinkedIn) -------


def build_data_thread(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> dict:
    """3-5 numbered posts (X) plus a single longer LinkedIn variant."""
    tone = "data-led"  # the thread artefact is always data-led
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    # Pick up to 4 distinct top achievements (so total posts = 1 intro + up
    # to 4 = max 5).
    intros = top_achievements[:4]
    n_posts = max(3, min(5, 1 + len(intros)))  # always 3-5

    posts: list[str] = []
    gen_metas: list[dict] = []

    # Post 1 — intro / header
    intro_fallback = (
        f"{meet_summary.get('name', 'Meet')} by the numbers — "
        f"{len(top_achievements)} ranked moments. Thread ↓"
    )[:280]
    intro_meta: dict = {}
    intro = _gen_caption(
        {
            "kind": "thread_intro",
            "meet": meet_summary.get("name", ""),
            "n_top": len(top_achievements),
        },
        club_brand,
        tone=tone,
        intent_key="data_thread_post",
        deterministic=deterministic,
        fallback_text=intro_fallback,
        profile=profile,
        meta=intro_meta,
    )
    gen_metas.append(intro_meta)
    posts.append(_truncate(intro, 280))

    for i, ra in enumerate(intros, start=2):
        payload = _ach_payload(ra)
        a = ra.get("achievement") or {}
        fb = (
            f"{i-1}/ {payload['swimmer_name']} · {payload['event']} · "
            f"{payload.get('time','')} — {payload.get('headline','')}".strip()
        )
        post_meta: dict = {}
        post = _gen_caption(
            payload,
            club_brand,
            tone=tone,
            intent_key="data_thread_post",
            deterministic=deterministic,
            fallback_text=fb,
            profile=profile,
            meta=post_meta,
        )
        gen_metas.append(post_meta)
        # Always prepend numbering so threading is unambiguous even when LLM
        # forgets it.
        post = _ensure_numbered(post, i - 1)
        posts.append(_truncate(post, 280))
        if len(posts) >= n_posts:
            break

    # Backfill if we don't have at least 3 (small meet, only 1 ach).
    while len(posts) < 3:
        posts.append(
            _truncate(
                f"{len(posts)}/ Full results coming. — {meet_summary.get('name', '')}".strip(),
                280,
            )
        )

    # LinkedIn — single longer post.
    li_fallback = (
        f"{meet_summary.get('name', 'Our latest meet')} — a quick recap.\n\n"
        + "\n".join(f"• {p}" for p in posts[1:])
        + "\n\nThanks to everyone who raced and supported the club."
    )
    li_meta: dict = {}
    li_caption = _gen_caption(
        {
            "kind": "thread_linkedin",
            "meet": meet_summary.get("name", ""),
            "highlights": [_ach_payload(ra) for ra in intros],
        },
        club_brand,
        tone=tone,
        intent_key="linkedin_long",
        deterministic=deterministic,
        fallback_text=li_fallback,
        profile=profile,
        meta=li_meta,
    )
    gen_metas.append(li_meta)

    source, source_note = _pack_source(gen_metas)
    notes = [
        f"Generated {len(posts)} X-thread posts (≤280 chars each).",
        f"LinkedIn variant: {len(li_caption)} chars.",
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "data_thread",
        "title": "Data-led thread (X / LinkedIn)",
        "source": source,
        "captions": {
            "x_thread": posts,
            "linkedin": li_caption,
            "default": posts[0],
        },
        "cards": [
            {"index": i, "post": p, "char_count": len(p)} for i, p in enumerate(posts, start=1)
        ],
        "notes": notes,
    }


# --- 4. Parent newsletter section ---------------------------------------


def build_parent_newsletter(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> dict:
    """HTML + plain-text section for a parent-newsletter mail-out."""
    tone = "warm-club"  # newsletter always reads warm regardless of brand tone
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    headliners = top_achievements[:3]
    bullets = []
    for ra in headliners:
        a = ra.get("achievement") or {}
        line = f"{a.get('swimmer_name','')} — {a.get('event','')}: {a.get('headline','')}".strip(
            " —:"
        )
        if line:
            bullets.append(line)

    meet_name = meet_summary.get("name", "the recent meet")
    fallback_plain = (
        f"Dear parents and supporters,\n\n"
        f"A quick update from {meet_name}. "
        + (("Standout moments included: " + "; ".join(bullets) + ". ") if bullets else "")
        + "Thank you to everyone who travelled, cheered, and supported the swimmers. "
        + "Please reach out if you'd like more detail on individual swims."
    )
    plain_meta: dict = {}
    plain = _gen_caption(
        {
            "kind": "newsletter",
            "meet": meet_name,
            "headliners": [_ach_payload(ra) for ra in headliners],
            "club": club_brand.get("club_name", ""),
        },
        club_brand,
        tone=tone,
        intent_key="parent_newsletter",
        deterministic=deterministic,
        fallback_text=fallback_plain,
        profile=profile,
        meta=plain_meta,
    )
    plain = _apply_sign_off(voice_profile, plain)

    # Convert plain → simple HTML (paragraphs by double-newline).
    paras = [p.strip() for p in plain.split("\n\n") if p.strip()]
    html_body = "\n".join(f"<p>{_esc(p)}</p>" for p in paras)
    html = (
        f'<section class="mh-newsletter">'
        f"<h2>{_esc(meet_name)} — meet update</h2>\n"
        f"{html_body}\n"
        f"</section>"
    )

    # Email-ready envelope: a subject line + preheader so the section can be
    # sent as-is, not just pasted into a longer mail-out.
    club_name = club_brand.get("club_name", "") or "Club"
    fb_subject = _truncate(f"{club_name} at {meet_name} — meet update", 55)
    fb_preheader = _truncate(plain.split(". ")[0].strip(), 90)
    subject, preheader = fb_subject, fb_preheader
    subject_meta: dict = {"source": "deterministic"}
    if not deterministic:
        try:
            from mediahub.media_ai.llm import generate_json

            d = generate_json(
                f"Newsletter text:\n{plain}\n\nMeet: {meet_name}. Club: {club_name}.",
                system=_ARTEFACT_INTENTS["newsletter_subject"]
                + ' Respond with JSON: {"subject": "...", "preheader": "..."}.',
                max_tokens=120,
            )
            subject = _truncate(str(d.get("subject") or "").strip() or fb_subject, 60)
            preheader = _truncate(str(d.get("preheader") or "").strip() or fb_preheader, 100)
            _note_source(subject_meta, "ai")
        except Exception as e:
            subject, preheader = fb_subject, fb_preheader
            _note_source(subject_meta, "fallback", type(e).__name__)

    source, source_note = _pack_source([plain_meta, subject_meta])
    notes = [
        f"Plain-text word count: ~{len(plain.split())} words.",
        f"Mentions {len(bullets)} headline swimmers.",
        "Email-ready: subject (≤60 chars) and preheader (≤100 chars) included.",
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "parent_newsletter",
        "title": f"Parent newsletter — {meet_name}",
        "source": source,
        "captions": {
            "subject": subject,
            "preheader": preheader,
            "default": plain,
            "plain_text": plain,
        },
        "cards": [{"swimmer": "", "event": "", "headline": meet_name, "body": plain}],
        "html": html,
        "notes": notes,
    }


# --- 4b. Club website report (long-form) ---------------------------------


def build_club_report(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> dict:
    """Long-form meet report for the club website or programme notes.

    The long-form sibling of the feed recap: ~350-450 words of plain prose
    grounded only in the ranked results, ready to paste into the club's
    news page. Generated via :func:`_gen_longform` (the caption primitive
    is capped at caption length).
    """
    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)
    meet_name = meet_summary.get("name", "the recent meet")
    club_name = club_brand.get("club_name", "") or "The club"
    venue = (meet_summary.get("venue") or "").strip()
    start_date = (meet_summary.get("start_date") or "").strip()
    end_date = (meet_summary.get("end_date") or "").strip()
    dates = " to ".join(d for d in (start_date, end_date) if d) if end_date else start_date

    headliners = top_achievements[:8]
    facts = [ln for ln in (_ach_line(_ach_payload(ra)) for ra in headliners) if ln]

    opening = f"{club_name} swimmers were in action at {meet_name}"
    if venue:
        opening += f" at {venue}"
    if start_date:
        opening += f" on {start_date}"
    opening += "."
    fallback_paras = [opening]
    if facts:
        fallback_paras.append("The standout swims: " + "; ".join(facts) + ".")
    fallback_paras.append(
        "Every swimmer who raced contributed to the meet — thank you to the "
        "coaches, officials and families who made the weekend happen."
    )
    fallback_report = "\n\n".join(fallback_paras)

    report_meta: dict = {}
    report = _gen_longform(
        {
            "kind": "club_report",
            "meet": meet_name,
            "club": club_brand.get("club_name", ""),
            "course": meet_summary.get("course", ""),
            "venue": venue,
            "dates": dates,
            "headliners": [_ach_payload(ra) for ra in headliners],
        },
        club_brand,
        tone=tone,
        intent_key="club_report",
        deterministic=deterministic,
        fallback_text=fallback_report,
        profile=profile,
        meta=report_meta,
    )

    paras = [p.strip() for p in report.split("\n\n") if p.strip()]
    html_body = "\n".join(f"<p>{_esc(p)}</p>" for p in paras)
    html = (
        f'<article class="mh-club-report">'
        f"<h2>{_esc(meet_name)} — club report</h2>\n"
        f"{html_body}\n"
        f"</article>"
    )

    source, source_note = _pack_source([report_meta])
    notes = [
        f"Word count: ~{len(report.split())} words.",
        f"Grounded in {len(facts)} ranked results — no invented facts.",
        "Long-form copy for the club website news page or programme notes.",
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "club_report",
        "title": f"Club website report — {meet_name}",
        "source": source,
        "captions": {"default": report},
        "cards": [],
        "html": html,
        "notes": notes,
    }


# --- 5. Sponsor thank-you -----------------------------------------------


def build_sponsor_thank_you(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> Optional[dict]:
    """Single sponsor thank-you post — only if sponsor_name is set."""
    sponsor = (profile.sponsor_name if profile else "").strip() if profile else ""
    if not sponsor:
        return None

    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    meet_name = meet_summary.get("name", "the meet")
    fallback = (
        f"Huge thank you to {sponsor} for backing us at {meet_name}. "
        f"Your support makes weekends like this possible."
    )[:280]
    gen_meta: dict = {}
    caption = _gen_caption(
        {
            "kind": "sponsor_thank_you",
            "meet": meet_name,
            "sponsor": sponsor,
            "sponsor_guidelines": (profile.sponsor_guidelines if profile else "") or "",
        },
        club_brand,
        tone=tone,
        intent_key="sponsor_thank_you",
        deterministic=deterministic,
        fallback_text=fallback,
        profile=profile,
        meta=gen_meta,
    )
    caption = _apply_sign_off(voice_profile, caption)

    source, source_note = _pack_source([gen_meta])
    notes = [f"Sponsor: {sponsor}"]
    if source_note:
        notes.append(source_note)

    return {
        "type": "sponsor_thank_you",
        "title": f"Sponsor thank-you — {sponsor}",
        "source": source,
        "captions": {"default": caption},
        "cards": [
            {"swimmer": "", "event": "", "headline": f"Thank you, {sponsor}", "body": caption}
        ],
        "notes": notes,
    }


# --- 6. Coach quote (DRAFT) --------------------------------------------


def build_coach_quote(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> dict:
    """Single coach-style quote, clearly flagged as a draft."""
    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    top = top_achievements[:3]
    achs_payload = [_ach_payload(ra) for ra in top]
    meet_name = meet_summary.get("name", "the meet")

    if top:
        a0 = top[0].get("achievement") or {}
        fallback_quote = (
            f"\"Really proud of the squad this weekend at {meet_name}. "
            f"{a0.get('swimmer_name','One of the swimmers')} in particular — "
            f"{a0.get('headline','a brilliant swim')}. "
            f"More to come.\" — Head Coach"
        )
    else:
        fallback_quote = (
            f'"Solid weekend at {meet_name}. Plenty to build on — '
            f'the squad keeps doing the work." — Head Coach'
        )

    gen_meta: dict = {}
    quote = _gen_caption(
        {
            "kind": "coach_quote",
            "meet": meet_name,
            "highlights": achs_payload,
        },
        club_brand,
        tone=tone,
        intent_key="coach_quote",
        deterministic=deterministic,
        fallback_text=fallback_quote,
        profile=profile,
        meta=gen_meta,
    )

    flag = "DRAFT — review with coach before publishing"
    caption = f"[{flag}]\n\n{quote}"

    source, source_note = _pack_source([gen_meta])
    notes = [
        "This quote is synthesised from the meet narrative and is NOT a real coach statement.",
        "Get coach sign-off before publishing.",
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "coach_quote",
        "title": "Coach quote (DRAFT)",
        "source": source,
        "captions": {"default": caption, "quote_only": quote},
        "cards": [
            {
                "swimmer": "Head Coach",
                "event": "",
                "headline": "Coach quote (draft)",
                "body": quote,
            }
        ],
        "draft_flag": flag,
        "notes": notes,
    }


# --- 7. Next-meet preview -----------------------------------------------


def _next_meet_from_profile(profile) -> Optional[dict]:
    """Return {name,date} dict for the profile's next meet, or None.

    ClubProfile doesn't have a first-class "next_meet" field yet, so we
    look in a few tolerated places: explicit ``next_meet`` dict (added by
    future versions), and the freeform ``notes`` field for a line that
    starts with ``next meet:``.
    """
    if profile is None:
        return None
    # 1. Explicit dict attribute (future-proof).
    nm = getattr(profile, "next_meet", None)
    if isinstance(nm, dict) and nm.get("name"):
        return {"name": str(nm.get("name", "")).strip(), "date": str(nm.get("date", "")).strip()}
    # 2. Parse a "Next meet: <name> — <date>" line from notes / tone_notes.
    for text_field in ("notes", "tone_notes"):
        text = getattr(profile, text_field, "") or ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("next meet:"):
                rest = stripped.split(":", 1)[1].strip()
                if not rest:
                    continue
                # Split on em-dash, en-dash, or " - " for the date.
                for sep in (" — ", " – ", " - "):
                    if sep in rest:
                        nm_name, nm_date = rest.split(sep, 1)
                        return {"name": nm_name.strip(), "date": nm_date.strip()}
                return {"name": rest, "date": ""}
    return None


def build_next_meet_preview(
    meet_summary: dict,
    top_achievements: list[dict],
    profile,
    voice_profile,
    brand_kit,
    deterministic: bool = False,
) -> Optional[dict]:
    """Teaser caption for the next meet — or None if no info present."""
    nm = _next_meet_from_profile(profile)
    if not nm or not nm.get("name"):
        return None

    tone = (voice_profile.tone if voice_profile else "") or "warm-club"
    club_brand = _club_brand(meet_summary, brand_kit, profile, voice_profile)

    fallback = (
        f"Up next: {nm['name']}"
        + (f" ({nm['date']})" if nm.get("date") else "")
        + ". Eyes forward — see you on the blocks."
    )[:280]
    gen_meta: dict = {}
    caption = _gen_caption(
        {
            "kind": "next_meet_preview",
            "next_meet": nm,
            "previous_meet": meet_summary.get("name", ""),
        },
        club_brand,
        tone=tone,
        intent_key="next_meet_preview",
        deterministic=deterministic,
        fallback_text=fallback,
        profile=profile,
        meta=gen_meta,
    )
    caption = _apply_sign_off(voice_profile, caption)

    source, source_note = _pack_source([gen_meta])
    notes = [
        f"Next meet: {nm.get('name','')}" + (f" — {nm.get('date','')}" if nm.get("date") else "")
    ]
    if source_note:
        notes.append(source_note)

    return {
        "type": "next_meet_preview",
        "title": f"Next-meet preview — {nm['name']}",
        "source": source,
        "captions": {"default": caption},
        "cards": [
            {
                "swimmer": "",
                "event": nm.get("name", ""),
                "headline": f"Next up: {nm.get('name','')}",
                "body": caption,
            }
        ],
        "notes": notes,
    }


# --- Small text helpers -------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_numbered(text: str, n: int) -> str:
    text = (text or "").strip()
    if text.startswith(f"{n}/") or text.startswith(f"{n}.") or text.startswith(f"{n})"):
        return text
    return f"{n}/ {text}"


def _esc(text: str) -> str:
    """Minimal HTML escape — newsletter HTML lives outside Jinja so we
    can't rely on autoescape. We deliberately don't pull in Markup() here
    because we want this to be a leaf module with no Flask dependency."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = [
    "build_meet_recap",
    "build_swimmer_spotlights",
    "build_data_thread",
    "build_parent_newsletter",
    "build_club_report",
    "build_sponsor_thank_you",
    "build_coach_quote",
    "build_next_meet_preview",
]
