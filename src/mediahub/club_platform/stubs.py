"""
Stub content types — refactored onto the ai_core (Claude / ChatGPT /
Gemini) reasoning layer.

The four stubs (Weekend Preview, Sponsor Post, Session Update, Free
Text) all funnel through one helper, ``_generate_cards_via_llm``, which:

  * Takes an English brief built from the user's form input.
  * Calls ai_core.ask_with_tools with a single tool, `submit_card`,
    that the model uses to emit each card (platform, caption,
    hashtags, notes). No JSON envelopes in the prompt, no parsing
    JSON out of free-text replies — the model speaks via the tool.
  * Surfaces honest errors when no provider is configured or the call
    fails. No hardcoded heuristic template fallback any more.

Classes:
  WeekendPreviewStub, SponsorPostStub, SessionUpdateStub, FreeTextStub
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .content_types import ContentType, ContentTypeMeta, REGISTRY  # noqa: F401


def _h(s: Any) -> str:
    return html.escape(str(s or ""))


_PHOTO_INPUT_HTML = (
    '<div style="margin-bottom:14px;padding:12px;background:rgba(34,211,238,0.05);'
    'border:1px dashed var(--border);border-radius:6px">'
    '<label style="display:block;margin-bottom:6px;font-weight:600">'
    'Attach a photo (optional)</label>'
    '<input type="file" name="attached_photo" accept="image/*" '
    'style="font-size:13px"/>'
    '<p class="muted" style="font-size:11px;margin:6px 0 0 0">'
    "We'll use this photo when generating the visual for this post. "
    'Leave blank to use a library photo or no photo.</p></div>'
)


@dataclass
class ContentCard:
    """One generated content card — a single platform-ready post draft."""
    platform: str = "Instagram"
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    confidence: float = 0.6
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "platform":   self.platform,
            "caption":    self.caption,
            "hashtags":   self.hashtags,
            "confidence": self.confidence,
            "notes":      self.notes,
        }


# ---------------------------------------------------------------------------
# Shared generator — every stub funnels through this
# ---------------------------------------------------------------------------

_SUBMIT_CARD_TOOL = [{
    "name": "submit_card",
    "description": (
        "Emit one social-media card for this brief. Call this 2-4 times, "
        "once per platform you want to cover. Each call produces one "
        "draft the user will review."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "platform": {"type": "string",
                         "description": "Instagram | Stories | Twitter | Facebook | LinkedIn | TikTok"},
            "caption":  {"type": "string",
                         "description": "The caption body, 1-4 short lines."},
            "hashtags": {"type": "array", "items": {"type": "string"},
                         "description": "2-6 hashtags, no leading #."},
            "notes":    {"type": "string",
                         "description": "One-line rationale for this card."},
        },
        "required": ["platform", "caption"],
    },
}]


def _load_brand_context() -> dict:
    """Best-effort load of the ACTIVE ClubProfile for brand voice grounding.

    Resolves through ``current_app.active_profile`` (set on the Flask app
    in ``web.create_app`` so every route shares the same definition of
    "which org am I"). Falls back to the most-recently-edited profile on
    disk only when there is no Flask request context — e.g. background
    jobs or unit tests. Using ``list_profiles()[0]`` used to mix up
    different orgs' tone + sponsor rules on multi-tenant installs.
    """
    try:
        from mediahub.web.club_profile import list_profiles, load_profile  # type: ignore
    except Exception:
        return {}
    prof = None
    try:
        from flask import current_app
        get_active = getattr(current_app, "active_profile", None)
        if get_active:
            prof = get_active()
    except Exception:
        prof = None
    if prof is None:
        try:
            profiles = list_profiles()
            if not profiles:
                return {}
            best_pid = None
            try:
                from mediahub.web.club_profile import _profiles_dir  # type: ignore
                d = _profiles_dir()
                best = max(
                    profiles,
                    key=lambda p: (d / f"{getattr(p, 'profile_id', '')}.json").stat().st_mtime,
                )
                best_pid = getattr(best, "profile_id", None)
            except Exception:
                first = profiles[0]
                best_pid = (
                    first.get("profile_id") if isinstance(first, dict)
                    else getattr(first, "profile_id", None)
                )
            if not best_pid:
                return {}
            prof = load_profile(best_pid)
        except Exception:
            prof = None
    if not prof:
        return {}
    try:
        # Effective palette (manual override > AI extracted). Stub
        # captions need to know the actual brand colour so language
        # like "wear the navy" or "lean into the gold" is grounded.
        from mediahub.brand.palette import effective_palette
        eff = effective_palette(
            manual=getattr(prof, "brand_palette_manual", {}) or {},
            extracted=getattr(prof, "brand_palette_extracted", {}) or {},
        )
    except Exception:
        eff = {}
    return {
        "name":          getattr(prof, "display_name", "") or "",
        "short_name":    getattr(prof, "short_name", "") or "",
        "org_type":      getattr(prof, "org_type", "") or "",
        "tone":          getattr(prof, "tone", "") or "",
        "tone_notes":    getattr(prof, "tone_notes", "") or "",
        "exemplars":     getattr(prof, "exemplar_captions", []) or [],
        "sponsor_name":  getattr(prof, "sponsor_name", "") or "",
        "sponsor_rules": getattr(prof, "sponsor_guidelines", "") or "",
        "voice_summary": (getattr(prof, "brand_voice_summary", "") or "")[:600],
        "keywords":      list(getattr(prof, "brand_keywords", []) or [])[:8],
        "phrases_to_use":   list(getattr(prof, "brand_phrases_to_use", []) or [])[:6],
        "phrases_to_avoid": list(getattr(prof, "brand_phrases_to_avoid", []) or [])[:6],
        "palette":       eff,
    }


def _system_prompt(extra_context: str) -> str:
    """English-only system prompt: voice, brand, and the rule about
    using the submit_card tool. No JSON envelope contracts."""
    brand = _load_brand_context()
    try:
        from mediahub.ai_core import narrate_brand
        brand_prose = narrate_brand(brand)
    except Exception:
        brand_prose = ""
    base = (
        "You are MediaHub's content engine for sports clubs, societies, "
        "teams and organisations. You generate short, human-sounding "
        "social captions grounded only in the user's input. Never invent "
        "facts, names, times, places, or achievements not provided. If "
        "the input is thin, write shorter cards rather than padding.\n\n"
        "Emit each card by calling the `submit_card` tool. Produce 2-4 "
        "cards covering different platforms (Instagram + Stories + "
        "Twitter is a good default). Captions: 1-4 short lines, ~280 "
        "characters. Hashtags: 2-6. After your last card, write nothing "
        "— the tool calls are the answer."
    )
    if brand_prose:
        base = base + "\n\nBrand voice:\n" + brand_prose

    # Surface the confirmed brand palette + name so captions can
    # reference the organisation's colours naturally ("wear the
    # navy", "lean into the gold") and use the organisation's
    # actual name instead of generic "the club".
    name = (brand.get("name") or "").strip()
    palette = brand.get("palette") or {}
    palette_bits = []
    for slot in ("primary", "secondary", "accent", "fourth"):
        v = palette.get(slot)
        if isinstance(v, str) and v.startswith("#"):
            palette_bits.append(f"{slot} {v}")
    keywords = [k for k in (brand.get("keywords") or []) if k]
    use_phrases = [p for p in (brand.get("phrases_to_use") or []) if p]
    avoid_phrases = [p for p in (brand.get("phrases_to_avoid") or []) if p]
    brand_facts_lines = []
    if name:
        brand_facts_lines.append(f"Organisation name: {name}")
    if palette_bits:
        brand_facts_lines.append("Confirmed brand palette: " + ", ".join(palette_bits))
    if keywords:
        brand_facts_lines.append("Brand keywords: " + ", ".join(keywords))
    if use_phrases:
        brand_facts_lines.append("Phrases to use: " + "; ".join(use_phrases))
    if avoid_phrases:
        brand_facts_lines.append("Phrases to avoid: " + "; ".join(avoid_phrases))
    if brand_facts_lines:
        base = base + "\n\nBrand facts:\n" + "\n".join(brand_facts_lines)

    if extra_context:
        base = base + "\n\nThis brief is:\n" + extra_context
    return base


def _generate_cards_via_llm(brief_prose: str, extra_context: str) -> dict:
    """Run a single ask_with_tools call and return {"cards": [...]}.

    Raises ai_core.ProviderNotConfigured / ProviderError so callers can
    surface the actual reason to the user — no silent template
    fallback any more.
    """
    from mediahub.ai_core import ask_with_tools

    cards: list[dict] = []

    def _tool(name, inp):
        if name != "submit_card":
            return json.dumps({"error": f"unknown tool: {name}"})
        platform = (inp.get("platform") or "Instagram").strip()
        caption = (inp.get("caption") or "").strip()
        hashtags = inp.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [h.strip() for h in hashtags.split() if h.strip()]
        notes = (inp.get("notes") or "").strip()
        if not caption:
            return json.dumps({"ok": False, "reason": "empty caption — skipped"})
        cards.append({
            "platform":   platform,
            "caption":    caption,
            "hashtags":   [str(h).lstrip("#").strip() for h in list(hashtags)[:6] if str(h).strip()],
            "confidence": 0.8,
            "notes":      notes,
        })
        return json.dumps({"ok": True, "received": len(cards)})

    ask_with_tools(
        system=_system_prompt(extra_context),
        user=brief_prose,
        tools=_SUBMIT_CARD_TOOL,
        on_tool_call=_tool,
        max_tokens=1500,
        max_rounds=6,
    )
    return {"cards": cards}


def _split_lines(raw: str) -> list[str]:
    return [l.strip() for l in (raw or "").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Stub base class
# ---------------------------------------------------------------------------

class _StubContentType:
    _type: ContentType

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return REGISTRY[cls._type]

    @classmethod
    def is_ready(cls) -> bool:
        return True

    def render_stub_html(self) -> str:
        """Wrap the per-stub form HTML with a photo-upload widget and the
        multipart enctype the upload needs."""
        meta = self.get_meta()
        form_html = self.render_form_html()
        form_html = form_html.replace(
            '<form method="POST"',
            '<form method="POST" enctype="multipart/form-data"',
            1,
        )
        injected = False
        for marker in (
            '<button type="submit" class="btn">Generate content cards →</button>',
            '<button type="submit" class="btn">Generate preview cards →</button>',
            '<button type="submit" class="btn">Generate sponsor cards →</button>',
            '<button type="submit" class="btn">Generate live update →</button>',
        ):
            if marker in form_html:
                form_html = form_html.replace(
                    marker, _PHOTO_INPUT_HTML + marker, 1
                )
                injected = True
                break
        if not injected:
            form_html = form_html.replace(
                "</form>", _PHOTO_INPUT_HTML + "</form>", 1
            )
        return f"""
<h1>{_h(meta.title)}</h1>
<p class="dim">{_h(meta.description)}</p>

<div class="card">
  <h2>What you'll need</h2>
  <p style="font-size:14px;color:var(--ink-dim);line-height:1.6">{_h(meta.input_contract)}</p>
</div>

{form_html}
"""

    def render_form_html(self) -> str:
        raise NotImplementedError

    def generate_brief(self, form_data: dict) -> str:
        raise NotImplementedError

    def generate_cards(self, form_data: dict) -> dict:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ready=True>"


# ---------------------------------------------------------------------------
# Weekend / Event Preview
# ---------------------------------------------------------------------------

class WeekendPreviewStub(_StubContentType):
    _type = ContentType.WEEKEND_PREVIEW

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Tell us about the event</h2>
  <p class="dim" style="font-size:13px">We'll generate platform-ready preview captions you can edit and post.</p>
  <form method="POST" data-loader-text="Drafting preview captions" data-loader-sub="Calling the content engine…" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label>Event name</label>
      <input type="text" name="meet_name" placeholder="e.g. County Championships" required/>
    </div>
    <div style="margin-bottom:14px">
      <label>Date and venue</label>
      <input type="text" name="date_venue" placeholder="e.g. 15–16 Feb, Coventry"/>
    </div>
    <div style="margin-bottom:14px">
      <label>Athletes to watch (one per line)</label>
      <textarea name="athletes" rows="4" placeholder="Sam Jones — 200 Free&#10;Alex Smith — 100 Back"></textarea>
    </div>
    <div style="margin-bottom:14px">
      <label>Key angles or story hooks (optional)</label>
      <textarea name="angles" rows="3" placeholder="First open meet of the season, three swimmers chasing qualifying times"></textarea>
    </div>
    <button type="submit" class="btn">Generate preview cards →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        meet = form_data.get("meet_name", "the upcoming event").strip()
        date_venue = form_data.get("date_venue", "").strip()
        athletes = _split_lines(form_data.get("athletes", ""))
        angles = form_data.get("angles", "").strip()
        parts = [f"Event preview brief — {meet}"]
        if date_venue:
            parts.append(f"Held at {date_venue}.")
        if athletes:
            parts.append("Athletes to watch: " + "; ".join(athletes) + ".")
        if angles:
            parts.append(f"Story angles: {angles}")
        return "\n".join(parts)

    def generate_cards(self, form_data: dict) -> dict:
        return _generate_cards_via_llm(
            brief_prose=self.generate_brief(form_data),
            extra_context=(
                "an EVENT PREVIEW. Tease what's coming, build "
                "anticipation, no results yet. Stay factual; only use "
                "names and events explicitly given."
            ),
        )


# ---------------------------------------------------------------------------
# Free Text
# ---------------------------------------------------------------------------

class FreeTextStub(_StubContentType):
    _type = ContentType.FREE_TEXT

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Describe the moment</h2>
  <p class="dim" style="font-size:13px">Type or paste anything — a result, a training session, a milestone. We'll structure it into platform-ready cards.</p>
  <form method="POST" data-loader-text="Reading your moment" data-loader-sub="Drafting captions across platforms…" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label>Your notes (anything goes)</label>
      <textarea name="free_text" rows="7" required
                placeholder="e.g. Last Saturday at the County Champs, Alex broke the club record in 100m backstroke by 0.4 seconds and got a standing ovation from the whole team…"></textarea>
    </div>
    <button type="submit" class="btn">Generate content cards →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        text = (form_data.get("free_text") or "").strip()
        if not text:
            return "(no text provided)"
        return f"User-supplied moment:\n\n{text[:2400]}"

    def generate_cards(self, form_data: dict) -> dict:
        text = (form_data.get("free_text") or "").strip()
        if not text:
            return {"cards": []}
        return _generate_cards_via_llm(
            brief_prose=self.generate_brief(form_data),
            extra_context=(
                "a FREE-TEXT moment. The user's description is the only "
                "source of truth — do not invent specifics. If a fact "
                "isn't in the notes, leave it out. Identify the strongest "
                "2-3 angles and pick the platform per angle."
            ),
        )


# ---------------------------------------------------------------------------
# Sponsor Post
# ---------------------------------------------------------------------------

class SponsorPostStub(_StubContentType):
    _type = ContentType.SPONSOR_POST

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Sponsor activation details</h2>
  <p class="dim" style="font-size:13px">We'll draft sponsor-safe captions you can review before posting.</p>
  <form method="POST" data-loader-text="Drafting sponsor captions" data-loader-sub="Applying brand rules and tone…" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label>Sponsor name</label>
      <input type="text" name="sponsor_name" placeholder="e.g. Acme Sports" required/>
    </div>
    <div style="margin-bottom:14px">
      <label>Event or moment</label>
      <input type="text" name="meet_name" placeholder="e.g. County Championships, Feb 2025"/>
    </div>
    <div style="margin-bottom:14px">
      <label>Key achievement to highlight</label>
      <input type="text" name="achievement" placeholder="e.g. Sam Jones set a club record in the 200 Free"/>
    </div>
    <div style="margin-bottom:14px">
      <label>Brand guidelines or restrictions (optional)</label>
      <textarea name="guidelines" rows="3" placeholder="e.g. Always use sponsor hashtag #AcmeSports, avoid competitor mentions"></textarea>
    </div>
    <button type="submit" class="btn">Generate sponsor cards →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        sponsor = form_data.get("sponsor_name", "the sponsor").strip()
        meet = form_data.get("meet_name", "").strip()
        achievement = form_data.get("achievement", "").strip()
        guidelines = form_data.get("guidelines", "").strip()
        parts = [f"Sponsor activation brief: partner {sponsor}."]
        if meet:
            parts.append(f"Event: {meet}.")
        if achievement:
            parts.append(f"Key moment to highlight: {achievement}.")
        if guidelines:
            parts.append(f"Brand guidelines: {guidelines}")
        return "\n".join(parts)

    def generate_cards(self, form_data: dict) -> dict:
        return _generate_cards_via_llm(
            brief_prose=self.generate_brief(form_data),
            extra_context=(
                "a SPONSOR POST. Respect every brand guideline. Never "
                "imply the sponsor caused the achievement — they support, "
                "the athletes perform. Make sponsor mentions feel natural, "
                "not forced."
            ),
        )


# ---------------------------------------------------------------------------
# Session Update (live)
# ---------------------------------------------------------------------------

class SessionUpdateStub(_StubContentType):
    _type = ContentType.SESSION_UPDATE

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>What's happening right now</h2>
  <p class="dim" style="font-size:13px">For live or mid-event updates — get short, share-now captions.</p>
  <form method="POST" data-loader-text="Drafting live update" data-loader-sub="Keeping it short and punchy…" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label>Event name</label>
      <input type="text" name="meet_name" placeholder="e.g. County Champs Day 1" required/>
    </div>
    <div style="margin-bottom:14px">
      <label>Early results or moments so far (one per line)</label>
      <textarea name="moments" rows="5" placeholder="Sam Jones — PB in 100 Free, 53.2&#10;Heat 3 of 200 Back — Alex Smith leads on time" required></textarea>
    </div>
    <div style="margin-bottom:14px">
      <label>Session (optional)</label>
      <input type="text" name="session" placeholder="e.g. Morning session, heats"/>
    </div>
    <button type="submit" class="btn">Generate live update →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        meet = form_data.get("meet_name", "the event").strip()
        moments = _split_lines(form_data.get("moments", ""))
        session = form_data.get("session", "").strip()
        parts = [f"Live session update from {meet}."]
        if session:
            parts.append(f"Session: {session}.")
        if moments:
            parts.append("Moments so far:\n  - " + "\n  - ".join(moments))
        return "\n".join(parts)

    def generate_cards(self, form_data: dict) -> dict:
        return _generate_cards_via_llm(
            brief_prose=self.generate_brief(form_data),
            extra_context=(
                "a LIVE SESSION UPDATE. Short, share-now energy. Stay "
                "factual — only mention swimmers and times explicitly "
                "provided. Stories should feel real-time."
            ),
        )


# ---------------------------------------------------------------------------
# Renderer — turns the cards into UI
# ---------------------------------------------------------------------------

def _platform_icon(platform: str) -> str:
    p = (platform or "").lower()
    if "instagram" in p or "feed" in p:
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>'
                '<path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>'
                '<line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>')
    if "stor" in p:
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="12" cy="12" r="10"/>'
                '<polyline points="12 6 12 12 16 14"/></svg>')
    if "tiktok" in p:
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M9 12a4 4 0 1 0 4 4V4a5 5 0 0 0 5 5"/></svg>')
    if "twitter" in p or "x " in p or p == "x":
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<line x1="4" y1="4" x2="20" y2="20"/><line x1="20" y1="4" x2="4" y2="20"/></svg>')
    if "facebook" in p:
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>')
    if "linkedin" in p:
        return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6z"/>'
                '<rect x="2" y="9" width="4" height="12"/>'
                '<circle cx="4" cy="4" r="2"/></svg>')
    return ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<circle cx="12" cy="12" r="10"/></svg>')


_PILL_STYLE = {
    "queue":    ("rgba(255,174,59,0.18)", "#ffae3b", "queue"),
    "approved": ("rgba(74,222,128,0.18)", "#4ade80", "approved"),
    "rejected": ("rgba(244,63,94,0.18)",  "#f43f5e", "rejected"),
}


def render_cards_html(
    cards_payload: dict,
    back_url: str,
    title: str,
    pack_id: Optional[str] = None,
    status_api_base: Optional[str] = None,
    graphic_api_base: Optional[str] = None,
) -> str:
    cards = (cards_payload or {}).get("cards") or []
    if not cards:
        return (
            f'<h1>{_h(title)}</h1>'
            '<div class="card"><p class="muted">No cards generated — '
            'contact your administrator to make sure a provider is configured, '
            'and try again with a bit more detail.</p>'
            f'<p style="margin-top:12px"><a class="btn secondary" href="{_h(back_url)}">← Try again</a></p></div>'
        )

    cards_html = ""
    show_pill = bool(pack_id and status_api_base)
    for idx, card in enumerate(cards):
        platform   = str(card.get("platform", "Post") or "Post")
        caption    = str(card.get("caption", "") or "").strip()
        hashtags   = card.get("hashtags") or []
        confidence = card.get("confidence", 0.6)
        notes      = str(card.get("notes", "") or "").strip()
        status     = str(card.get("status") or "queue").lower()
        if status not in _PILL_STYLE:
            status = "queue"

        try:
            conf_pct = max(0, min(100, int(round(float(confidence) * 100))))
        except (TypeError, ValueError):
            conf_pct = 60

        tag_chips = ""
        for tag in hashtags[:8]:
            t = str(tag).strip().lstrip('#')
            if t:
                tag_chips += f'<span class="mh-card-tag">#{_h(t)}</span>'

        # Embed the caption literal inside a single-quoted ``onclick`` HTML
        # attribute. ``json.dumps`` escapes ``"`` and ``\`` but leaves ``'``
        # as a literal apostrophe — and a caption like ``Let's go!`` would
        # then close the attribute mid-string, breaking Copy caption for any
        # caption Gemini happens to write with an apostrophe. ``html.escape``
        # with ``quote=True`` rewrites ``'`` → ``&#x27;`` (which the browser
        # un-escapes back to ``'`` inside the JS double-quoted string),
        # and leaves the JSON's ``\"`` and newline escapes intact.
        caption_for_copy = html.escape(json.dumps(caption), quote=True)
        notes_html = (
            f'<div style="margin-top:10px;font-size:12px;color:var(--ink-muted)">'
            f'<em>{_h(notes)}</em></div>' if notes else ''
        )

        pill_html = ""
        if show_pill:
            bg, fg, label = _PILL_STYLE[status]
            pill_url = f"{status_api_base}/{idx}/status"
            pill_html = (
                f'<button type="button" class="stub-wf-pill" data-pack="{_h(pack_id)}" '
                f'data-idx="{idx}" data-status="{_h(status)}" data-url="{_h(pill_url)}" '
                f'style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;'
                f'font-size:11px;font-weight:600;background:{bg};color:{fg};'
                f'font-family:inherit;margin-left:8px"'
                f' title="Click: queue → approved → rejected → queue. Right-click to reset.">'
                f'{_h(label)}</button>'
            )

        # "Create graphic" affordance — only when the page wired a graphic API
        # base (the saved-pack flows do; the unsaved one-shot render doesn't).
        # The button + panel reuse window.mhCreateGraphic (injected by the
        # calling page via _VISUAL_PANEL_JS); cardId namespaces the panel by
        # pack + index so multiple cards on one page don't collide.
        graphic_button = ""
        visual_panel = ""
        if graphic_api_base and pack_id:
            g_card_id = f"{pack_id}-{idx}"
            g_url = f"{graphic_api_base}/{idx}/create-graphic"
            graphic_button = (
                f'<button type="button" class="secondary" '
                f"onclick=\"mhCreateGraphic(this, '{_h(g_url)}', '{_h(g_card_id)}')\" "
                f'style="font-size:13px">&#x2726; Create graphic</button>'
            )
            visual_panel = (
                f'<div class="visual-panel" data-card="{_h(g_card_id)}" '
                f'style="display:none;margin-top:10px;padding:12px;'
                f'background:rgba(212,255,58,0.04);border:1px solid var(--border);'
                f'border-radius:8px"></div>'
            )

        cards_html += f"""
<div class="mh-content-card" data-interactive data-card-status="{_h(status)}">
  <div class="mh-card-confidence" title="Model confidence">{conf_pct}% conf{pill_html}</div>
  <div class="mh-card-platform">{_platform_icon(platform)} {_h(platform)}</div>
  <div class="mh-card-caption">{_h(caption)}</div>
  {f'<div class="mh-card-tags">{tag_chips}</div>' if tag_chips else ''}
  {notes_html}
  <div class="mh-card-actions">
    <button type="button" class="primary" onclick='(function(b){{
      var c = {caption_for_copy};
      if (navigator.clipboard) {{
        navigator.clipboard.writeText(c).then(function(){{ window.MH && MH.toast("Caption copied", "success"); }});
      }} else {{ window.MH && MH.toast("Clipboard not available", "error"); }}
    }})(this)'>Copy caption</button>
    {graphic_button}
  </div>
  {visual_panel}
</div>"""

    pill_js = ""
    if show_pill:
        pill_js = """
<script>
(function(){
  var NEXT = {queue:'approved', approved:'rejected', rejected:'queue'};
  var STYLE = {
    queue:    ['rgba(255,174,59,0.18)','#ffae3b'],
    approved: ['rgba(74,222,128,0.18)','#4ade80'],
    rejected: ['rgba(244,63,94,0.18)','#f43f5e']
  };
  function apply(btn, status){
    var s = STYLE[status] || STYLE.queue;
    btn.style.background = s[0]; btn.style.color = s[1];
    btn.dataset.status = status; btn.textContent = status;
    var card = btn.closest('[data-card-status]');
    if (card) card.dataset.cardStatus = status;
  }
  function send(btn, status){
    var prev = btn.dataset.status;
    apply(btn, status);
    var fd = new FormData(); fd.append('status', status);
    fetch(btn.dataset.url, {method:'POST', body:fd, credentials:'same-origin'})
      .then(function(r){ if(!r.ok) throw 0; return r.json(); })
      .then(function(j){ if(j && j.status) apply(btn, j.status); })
      .catch(function(){ apply(btn, prev); window.MH && MH.toast('Could not save status','error'); });
  }
  document.addEventListener('click', function(e){
    var btn = e.target.closest('.stub-wf-pill'); if (!btn) return;
    e.preventDefault();
    send(btn, NEXT[btn.dataset.status] || 'approved');
  });
  document.addEventListener('contextmenu', function(e){
    var btn = e.target.closest('.stub-wf-pill'); if (!btn) return;
    e.preventDefault();
    send(btn, 'queue');
  });
})();
</script>
"""

    return (
        f'<h1>{_h(title)}</h1>'
        f'<p class="dim" style="margin-bottom:20px">{len(cards)} draft '
        f'{"card" if len(cards) == 1 else "cards"} generated. Review, edit, approve, and post.</p>'
        f'{cards_html}'
        f'{pill_js}'
        f'<div style="margin-top:24px;display:flex;gap:10px">'
        f'<a class="btn secondary" href="{_h(back_url)}">← Start over</a>'
        f'</div>'
    )
