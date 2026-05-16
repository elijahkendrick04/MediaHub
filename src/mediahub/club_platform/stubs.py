"""
Stub content types — now powered by real LLM generation with heuristic fallback.

Each stub class provides:
  render_stub_html()    — form HTML
  generate_brief()      — legacy plain-text brief (back-compat)
  generate_cards()      — structured content cards (caption + variations + hashtags)

Classes:
  WeekendPreviewStub
  SponsorPostStub
  SessionUpdateStub
  FreeTextStub
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .content_types import ContentType, ContentTypeMeta, REGISTRY  # noqa: F401


def _h(s: Any) -> str:
    return html.escape(str(s or ""))


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
            "platform": self.platform,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "confidence": self.confidence,
            "notes": self.notes,
        }


def _try_llm_generate(prompt: str, system: str, fallback: dict) -> dict:
    """Try real LLM; fall back to a heuristic dict if unavailable or parse fails."""
    try:
        from mediahub.media_ai import llm  # type: ignore
    except Exception:
        return fallback
    try:
        if not llm.is_available():
            return fallback
        result = llm.generate_json(prompt, system=system, max_tokens=900, fallback=fallback)
        if not isinstance(result, dict) or "cards" not in result:
            return fallback
        cards = result.get("cards") or []
        if not isinstance(cards, list) or not cards:
            return fallback
        return result
    except Exception:
        return fallback


def _load_brand_context() -> dict:
    """Best-effort load of the first ClubProfile to ground LLM output in brand voice."""
    try:
        from mediahub.web.club_profile import list_profiles, load_profile  # type: ignore
    except Exception:
        return {}
    try:
        profiles = list_profiles()
        if not profiles:
            return {}
        first = profiles[0]
        pid = first.get("profile_id") if isinstance(first, dict) else getattr(first, "profile_id", None)
        if not pid:
            return {}
        prof = load_profile(pid)
        if not prof:
            return {}
        return {
            "name":           getattr(prof, "display_name", "") or "",
            "short_name":     getattr(prof, "short_name", "") or "",
            "org_type":       getattr(prof, "org_type", "") or "",
            "tone":           getattr(prof, "tone", "warm-club") or "warm-club",
            "tone_notes":     getattr(prof, "tone_notes", "") or "",
            "platforms":      getattr(prof, "platforms", []) or [],
            "exemplars":      getattr(prof, "exemplar_captions", []) or [],
            "sponsor_name":   getattr(prof, "sponsor_name", "") or "",
            "sponsor_rules":  getattr(prof, "sponsor_guidelines", "") or "",
        }
    except Exception:
        return {}


def _brand_system_prompt(extra: str = "") -> str:
    ctx = _load_brand_context()
    bits = [
        "You are MediaHub's content engine for sports clubs, societies, teams and organisations.",
        "Generate short, human-sounding social captions grounded only in the user's input.",
        "Never invent facts, names, times, places, or achievements that aren't in the input.",
        "If the input is thin, write shorter cards rather than padding with filler.",
    ]
    if ctx.get("name"):
        bits.append(f"Organisation: {ctx['name']}.")
    if ctx.get("tone"):
        tone_map = {
            "warm-club": "Warm, community, first-name use. Conversational.",
            "hype":      "Energetic, race-day language, allowed sparing exclamation marks.",
            "data-led":  "Numbers-first, precise, sponsor-friendly, fewer emojis.",
        }
        bits.append(f"Tone: {tone_map.get(ctx['tone'], ctx['tone'])}.")
    if ctx.get("tone_notes"):
        bits.append(f"Brand voice notes: {ctx['tone_notes']}")
    if ctx.get("exemplars"):
        bits.append("Example captions (style reference): " + " || ".join(ctx["exemplars"][:3]))
    if ctx.get("sponsor_name"):
        bits.append(f"Sponsor: {ctx['sponsor_name']}.")
    if ctx.get("sponsor_rules"):
        bits.append(f"Sponsor rules: {ctx['sponsor_rules']}")
    if extra:
        bits.append(extra)
    bits.append(
        'Return JSON: {"cards":[{"platform":"Instagram",'
        '"caption":"...","hashtags":["#a","#b"],"confidence":0.7,"notes":"why"},...]} '
        'with 2 to 4 cards. Captions must be 1–4 short lines. Hashtags 2–6 max.'
    )
    return "\n".join(bits)


def _fallback_cards(captions: list[tuple[str, str]], hashtags: list[str]) -> dict:
    """Build a cards dict from (platform, caption) tuples for offline fallback."""
    out = []
    for platform, caption in captions:
        out.append({
            "platform": platform,
            "caption": caption,
            "hashtags": hashtags[:5],
            "confidence": 0.55,
            "notes": "Generated by template fallback (no LLM available).",
        })
    return {"cards": out}


def _split_lines(raw: str) -> list[str]:
    return [l.strip() for l in (raw or "").splitlines() if l.strip()]


class _StubContentType:
    """Base for all stub content types."""

    _type: ContentType

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return REGISTRY[cls._type]

    @classmethod
    def is_ready(cls) -> bool:
        return True  # All stubs are now functional (with LLM fallback)

    def render_stub_html(self) -> str:
        """Return a full HTML fragment (body only) with the input form."""
        meta = self.get_meta()
        form_html = self.render_form_html()
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
        """Legacy plain-text brief — kept for backwards compatibility."""
        raise NotImplementedError

    def generate_cards(self, form_data: dict) -> dict:
        """Return structured cards: {"cards": [{platform, caption, hashtags, confidence, notes}, ...]}"""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ready=True>"


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
        meet = _h(form_data.get("meet_name", "the upcoming event"))
        date_venue = _h(form_data.get("date_venue", ""))
        athletes_raw = form_data.get("athletes", "").strip()
        angles_raw = form_data.get("angles", "").strip()
        athlete_lines = _split_lines(athletes_raw)
        athlete_block = "\n".join(f"• {_h(a)}" for a in athlete_lines) if athlete_lines else "• [add athletes here]"
        location_line = f" at {date_venue}" if date_venue else ""
        angles_block = f"\n\nKey angles:\n{_h(angles_raw)}" if angles_raw else ""
        return (
            f"Weekend Preview brief — {meet}\n{'=' * 60}\n\n"
            f"📍 {meet}{location_line}\n\n"
            f"Athletes to watch:\n{athlete_block}"
            f"{angles_block}\n"
        )

    def generate_cards(self, form_data: dict) -> dict:
        meet       = (form_data.get("meet_name") or "").strip()
        date_venue = (form_data.get("date_venue") or "").strip()
        athletes   = _split_lines(form_data.get("athletes", ""))
        angles     = (form_data.get("angles") or "").strip()

        athletes_block = "\n".join(f"- {a}" for a in athletes) if athletes else "(none specified)"
        prompt = (
            "Generate 3 social-media preview cards for an upcoming event.\n\n"
            f"Event: {meet or '(unspecified)'}\n"
            f"Date / venue: {date_venue or '(unspecified)'}\n"
            f"Athletes to watch:\n{athletes_block}\n"
            f"Story angles: {angles or '(none)'}\n\n"
            "Produce one Instagram feed caption, one Instagram Stories teaser, and one "
            "Twitter/X post. Each platform's caption should match its native tone."
        )
        system = _brand_system_prompt(
            "This is an EVENT PREVIEW — tease what's coming, build anticipation, "
            "no results yet. Stay factual; only use names/events explicitly given."
        )
        # Heuristic fallback
        teaser_athletes = ", ".join(a.split("—")[0].strip() for a in athletes[:3]) or "the squad"
        location = f" at {date_venue}" if date_venue else ""
        fallback = _fallback_cards([
            ("Instagram",
             f"🏊 {meet or 'Big weekend ahead'}{location}.\n\n"
             f"Watching {teaser_athletes} take to the water. "
             f"{('Big angle: ' + angles) if angles else 'Backing the squad all the way.'}\n\n"
             f"Cheer them on 💙"),
            ("Stories",
             f"⏰ {meet or 'Upcoming'}{location}\n\n"
             f"Athletes to watch:\n" +
             "\n".join(f"• {a}" for a in athletes[:5] or ['(add athletes)'])),
            ("Twitter",
             f"{meet or 'Event'}{location}. "
             f"Spotlighting {teaser_athletes}. "
             f"{angles[:120] if angles else 'Bring on the racing.'}"),
        ], ["#race", "#preview", "#squad"])
        return _try_llm_generate(prompt, system, fallback)


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
            return "No text provided."
        return f"Free Text brief\n{'=' * 60}\n\n{text[:1200]}\n"

    def generate_cards(self, form_data: dict) -> dict:
        text = (form_data.get("free_text") or "").strip()
        if not text:
            return _fallback_cards(
                [("Instagram", "Add some notes describing the moment to generate captions.")],
                [],
            )
        prompt = (
            "The user gave a short free-text description of a club/team moment. "
            "Identify the strongest 2–3 social-media angles and generate one card per angle. "
            "Pick the platform per angle (Instagram, Stories, Twitter, Facebook, LinkedIn). "
            "Stay strictly within the facts in the text.\n\n"
            f"User notes:\n\"\"\"\n{text[:2000]}\n\"\"\""
        )
        system = _brand_system_prompt(
            "This is a FREE-TEXT moment. The user's description is the only source of truth — "
            "do not invent specifics. If a fact isn't in the notes, leave it out."
        )
        # Heuristic fallback: try to pull a first sentence, then a generic Stories teaser.
        first_sentence = re.split(r"[.!?]\s+", text, maxsplit=1)[0]
        clip = (first_sentence[:180] + ("…" if len(first_sentence) > 180 else "")) if first_sentence else text[:160]
        fallback = _fallback_cards([
            ("Instagram",
             f"{clip}\n\nWhat a moment for the team 💙"),
            ("Stories",
             f"🎉 Big moment\n\n{clip}"),
            ("Twitter",
             clip[:240]),
        ], ["#proud", "#teamfirst"])
        return _try_llm_generate(prompt, system, fallback)


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
        sponsor = _h(form_data.get("sponsor_name", "[Sponsor]"))
        meet = _h(form_data.get("meet_name", "the event"))
        achievement = _h(form_data.get("achievement", ""))
        guidelines = _h(form_data.get("guidelines", "").strip())
        achievement_line = f"\nHighlight: {achievement}" if achievement else ""
        guidelines_block = f"\nBrand guidelines:\n{guidelines}" if guidelines else ""
        return (
            f"Sponsor Post brief — {sponsor} x {meet}\n{'=' * 60}\n\n"
            f"Partner: {sponsor}\nEvent: {meet}{achievement_line}{guidelines_block}\n"
        )

    def generate_cards(self, form_data: dict) -> dict:
        sponsor     = (form_data.get("sponsor_name") or "").strip()
        meet        = (form_data.get("meet_name") or "").strip()
        achievement = (form_data.get("achievement") or "").strip()
        guidelines  = (form_data.get("guidelines") or "").strip()

        prompt = (
            "Generate 3 sponsor-activation social cards: Instagram feed, Stories, Twitter.\n\n"
            f"Sponsor: {sponsor or '(unspecified)'}\n"
            f"Event: {meet or '(unspecified)'}\n"
            f"Key achievement: {achievement or '(unspecified)'}\n"
            f"Brand guidelines: {guidelines or '(none)'}\n\n"
            "Make sponsor mentions feel natural, not forced. Lead with the moment, partner with the sponsor."
        )
        system = _brand_system_prompt(
            "This is a SPONSOR POST. Respect all brand rules above. "
            "Never imply the sponsor caused the achievement — they support, the athletes perform."
        )
        # Heuristic fallback
        sponsor_disp = sponsor or "[Sponsor]"
        meet_part = f" at {meet}" if meet else ""
        achievement_part = f" {achievement}." if achievement else ""
        fallback = _fallback_cards([
            ("Instagram",
             f"Big moments{meet_part}, powered by our partners at {sponsor_disp}.{achievement_part}\n\n"
             f"Proud to be supported by {sponsor_disp} 🤝"),
            ("Stories",
             f"🤝 Powered by {sponsor_disp}\n\n{achievement or 'Highlights from the event'}"),
            ("Twitter",
             f"{achievement or 'A standout moment'}{meet_part}. "
             f"With thanks to our partners at {sponsor_disp}."),
        ], [f"#{sponsor.replace(' ', '')}" if sponsor else "#sponsored", "#partner"])
        return _try_llm_generate(prompt, system, fallback)


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
        meet = _h(form_data.get("meet_name", "the event"))
        moments_raw = form_data.get("moments", "").strip()
        session = _h(form_data.get("session", "").strip())
        moment_lines = _split_lines(moments_raw)
        moment_block = "\n".join(f"• {_h(m)}" for m in moment_lines) if moment_lines else "• [no moments]"
        session_line = f" — {session}" if session else ""
        return (
            f"Session Update brief — {meet}{session_line}\n{'=' * 60}\n\n"
            f"🏊 Live from {meet}{session_line}\n\nEarly highlights:\n{moment_block}\n"
        )

    def generate_cards(self, form_data: dict) -> dict:
        meet    = (form_data.get("meet_name") or "").strip()
        moments = _split_lines(form_data.get("moments", ""))
        session = (form_data.get("session") or "").strip()

        moments_block = "\n".join(f"- {m}" for m in moments) if moments else "(none)"
        prompt = (
            "Generate 2 short live-update social cards: Instagram Stories teaser, Twitter/X update.\n\n"
            f"Event: {meet or '(unspecified)'}\n"
            f"Session: {session or '(not specified)'}\n"
            f"Moments so far:\n{moments_block}\n\n"
            "Keep it urgent and current — this is mid-event. 1–2 short lines max. "
            "Pull only 1–2 highlights, not all of them."
        )
        system = _brand_system_prompt(
            "This is a LIVE / SESSION UPDATE. Write present-tense, urgent, share-now style."
        )
        # Heuristic fallback
        session_part = f" — {session}" if session else ""
        first_moment = moments[0] if moments else "Action under way"
        fallback = _fallback_cards([
            ("Stories",
             f"🔴 LIVE from {meet or 'the event'}{session_part}\n\n{first_moment}"),
            ("Twitter",
             f"Live from {meet or 'the event'}{session_part}: {first_moment[:200]}"),
        ], ["#live"])
        return _try_llm_generate(prompt, system, fallback)


# ---------------------------------------------------------------------------
# Renderer — used by web routes to display generated cards
# ---------------------------------------------------------------------------

def _platform_icon(platform: str) -> str:
    """Return a small SVG icon for the platform name."""
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
) -> str:
    """Render the structured cards payload as polished HTML.

    When ``pack_id`` and ``status_api_base`` are supplied, each card gets an
    Approve / Reject / Queue pill that POSTs to ``{status_api_base}/<idx>``
    so reviewers can sign off generated drafts inline. The endpoint URL is
    built by the caller so this module stays free of Flask url_for() coupling.
    """
    cards = (cards_payload or {}).get("cards") or []
    if not cards:
        return (
            f'<h1>{_h(title)}</h1>'
            '<div class="card"><p class="muted">No cards generated — try adding more detail.</p>'
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

        # Encode caption safely for the copy button JS payload
        caption_for_copy = json.dumps(caption)
        notes_html = (
            f'<div style="margin-top:10px;font-size:12px;color:var(--ink-muted)">'
            f'<em>{_h(notes)}</em></div>' if notes else ''
        )

        pill_html = ""
        if show_pill:
            bg, fg, label = _PILL_STYLE[status]
            pill_url = f"{status_api_base}/{idx}"
            pill_html = (
                f'<button type="button" class="stub-wf-pill" data-pack="{_h(pack_id)}" '
                f'data-idx="{idx}" data-status="{_h(status)}" data-url="{_h(pill_url)}" '
                f'style="border:none;cursor:pointer;padding:3px 10px;border-radius:999px;'
                f'font-size:11px;font-weight:600;background:{bg};color:{fg};'
                f'font-family:inherit;margin-left:8px"'
                f' title="Click: queue → approved → rejected → queue. Right-click to reset.">'
                f'{_h(label)}</button>'
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
  </div>
</div>"""

    pill_js = ""
    if show_pill:
        # One delegated handler. Click cycles queue → approved → rejected → queue.
        # Right-click resets to queue. Sends a POST with status= as form data;
        # the server returns {ok, status} JSON. On failure we revert visually.
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
