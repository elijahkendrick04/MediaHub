"""
Stub content types — placeholder ContentType subclasses that render a
real HTML page with an interactive draft-brief form so clubs can start
drafting right now while the full pipeline is being built.

Classes:
  WeekendPreviewStub
  SponsorPostStub
  SessionUpdateStub
  FreeTextStub
"""
from __future__ import annotations

import html
from typing import Any

from .content_types import ContentType, ContentTypeMeta, REGISTRY  # noqa: F401


def _h(s: Any) -> str:
    return html.escape(str(s or ""))


class _StubContentType:
    """Base for all stub content types."""

    _type: ContentType

    @classmethod
    def get_meta(cls) -> ContentTypeMeta:
        return REGISTRY[cls._type]

    @classmethod
    def is_ready(cls) -> bool:
        return False

    def render_stub_html(self) -> str:
        """Return a full HTML fragment (body only) with the draft-brief form."""
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
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} ready=False>"


class WeekendPreviewStub(_StubContentType):
    _type = ContentType.WEEKEND_PREVIEW

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Draft a weekend preview brief</h2>
  <p class="dim" style="font-size:13px">Fill in what you know and we'll draft a brief you can copy and edit.</p>
  <form method="POST" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Meet name</label>
      <input type="text" name="meet_name" placeholder="e.g. County Championships" required
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Date and venue</label>
      <input type="text" name="date_venue" placeholder="e.g. 15–16 Feb, Coventry"
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Athletes to watch (one per line)</label>
      <textarea name="athletes" rows="4" placeholder="e.g. Sam Jones — 200 Free&#10;Alex Smith — 100 Back"
                style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:inherit"></textarea>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Key angles or story hooks (optional)</label>
      <textarea name="angles" rows="3" placeholder="e.g. First open meet of the season, three swimmers chasing qualifying times"
                style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:inherit"></textarea>
    </div>
    <button type="submit" class="btn">Generate draft brief →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        meet = _h(form_data.get("meet_name", "the upcoming meet"))
        date_venue = _h(form_data.get("date_venue", ""))
        athletes_raw = form_data.get("athletes", "").strip()
        angles_raw = form_data.get("angles", "").strip()

        athlete_lines = [l.strip() for l in athletes_raw.splitlines() if l.strip()]
        if athlete_lines:
            athlete_block = "\n".join(f"• {_h(a)}" for a in athlete_lines)
        else:
            athlete_block = "• [add athletes here]"

        location_line = f" at {date_venue}" if date_venue else ""

        angles_block = ""
        if angles_raw:
            angles_block = f"\n\nKey angles:\n{_h(angles_raw)}"

        return (
            f"Weekend Preview brief — {meet}\n"
            f"{'=' * 60}\n\n"
            f"📍 {meet}{location_line}\n\n"
            f"Athletes to watch:\n{athlete_block}"
            f"{angles_block}\n\n"
            f"---\n"
            f"This is a draft brief. Edit the athlete list and angles before posting.\n"
            f"Once the full Weekend Preview pipeline is live, upload an entry list\n"
            f"to get ranked, source-grounded preview cards automatically."
        )


class FreeTextStub(_StubContentType):
    _type = ContentType.FREE_TEXT

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Describe your moment</h2>
  <p class="dim" style="font-size:13px">Type or paste anything — a result, a training session, an event, a milestone.
     We'll structure it into a content brief.</p>
  <form method="POST" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Your notes (anything goes)</label>
      <textarea name="free_text" rows="7" required
                placeholder="e.g. Last Saturday at the County Champs, Alex broke the club record in 100m backstroke by 0.4 seconds and got a standing ovation from the whole team..."
                style="width:100%;max-width:600px;padding:10px;border:1px solid var(--border);border-radius:6px;font-family:inherit"></textarea>
    </div>
    <button type="submit" class="btn">Generate draft brief →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        text = (form_data.get("free_text") or "").strip()
        if not text:
            return "No text provided."
        preview = _h(text[:1200])
        return (
            f"Free Text brief\n"
            f"{'=' * 60}\n\n"
            f"Your notes:\n{preview}\n\n"
            f"---\n"
            f"Full AI content generation from free text is coming soon.\n"
            f"Use the notes above as a starting brief for your captions."
        )


class SponsorPostStub(_StubContentType):
    _type = ContentType.SPONSOR_POST

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Draft a sponsor post brief</h2>
  <p class="dim" style="font-size:13px">Fill in the sponsor details and highlight — we'll draft a caption brief.</p>
  <form method="POST" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Sponsor name</label>
      <input type="text" name="sponsor_name" placeholder="e.g. Acme Sports" required
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Meet or event</label>
      <input type="text" name="meet_name" placeholder="e.g. County Championships, Feb 2025"
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Key achievement to highlight</label>
      <input type="text" name="achievement" placeholder="e.g. Sam Jones set a club record in the 200 Free"
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Brand guidelines or restrictions (optional)</label>
      <textarea name="guidelines" rows="3" placeholder="e.g. Always use sponsor hashtag #AcmeSports, avoid competitor mentions"
                style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:inherit"></textarea>
    </div>
    <button type="submit" class="btn">Generate draft brief →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        sponsor = _h(form_data.get("sponsor_name", "[Sponsor]"))
        meet = _h(form_data.get("meet_name", "the meet"))
        achievement = _h(form_data.get("achievement", ""))
        guidelines = _h(form_data.get("guidelines", "").strip())

        achievement_line = f"\n\nHighlight: {achievement}" if achievement else "\n\nHighlight: [add achievement here]"
        guidelines_section = f"\n\nBrand guidelines:\n{guidelines}" if guidelines else ""

        return (
            f"Sponsor Post brief — {sponsor} x {meet}\n"
            f"{'=' * 60}\n\n"
            f"Partner: {sponsor}\n"
            f"Event: {meet}"
            f"{achievement_line}"
            f"{guidelines_section}\n\n"
            f"Draft caption:\n"
            f"Big performances at {meet}, powered by {sponsor}. "
            f"[Add specific achievement and athlete name here.] "
            f"Proud to be supported by {sponsor}. 🏊\n\n"
            f"---\n"
            f"This is a starting brief — edit before posting.\n"
            f"Once the full Sponsor Post pipeline is live, pick a processed meet\n"
            f"and we'll generate sponsor-safe, data-led captions automatically."
        )


class SessionUpdateStub(_StubContentType):
    _type = ContentType.SESSION_UPDATE

    def render_form_html(self) -> str:
        return """
<div class="card">
  <h2>Draft a session update brief</h2>
  <p class="dim" style="font-size:13px">Paste in what's happened so far — we'll structure it into a short update brief.</p>
  <form method="POST" style="margin-top:16px">
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Meet name</label>
      <input type="text" name="meet_name" placeholder="e.g. County Champs Day 1" required
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Early results or moments so far (one per line)</label>
      <textarea name="moments" rows="5" placeholder="e.g. Sam Jones — PB in 100 Free, 53.2&#10;Heat 3 of 200 Back — Alex Smith leads on time"
                style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px;font-family:inherit" required></textarea>
    </div>
    <div style="margin-bottom:14px">
      <label style="display:block;font-weight:600;margin-bottom:4px">Session (optional)</label>
      <input type="text" name="session" placeholder="e.g. Morning session, heats"
             style="width:100%;max-width:480px;padding:8px;border:1px solid var(--border);border-radius:6px"/>
    </div>
    <button type="submit" class="btn">Generate draft update →</button>
  </form>
</div>"""

    def generate_brief(self, form_data: dict) -> str:
        meet = _h(form_data.get("meet_name", "the meet"))
        moments_raw = form_data.get("moments", "").strip()
        session = _h(form_data.get("session", "").strip())

        moment_lines = [l.strip() for l in moments_raw.splitlines() if l.strip()]
        if moment_lines:
            moment_block = "\n".join(f"• {_h(m)}" for m in moment_lines)
        else:
            moment_block = "• [no moments entered]"

        session_line = f" — {session}" if session else ""

        return (
            f"Session Update brief — {meet}{session_line}\n"
            f"{'=' * 60}\n\n"
            f"🏊 Live from {meet}{session_line}\n\n"
            f"Early highlights:\n{moment_block}\n\n"
            f"Draft Stories caption:\n"
            f"Day in progress at {meet}! Here's what's happened so far 👇\n"
            f"[Pull 1–2 lines from the highlights above]\n\n"
            f"---\n"
            f"This is a draft brief — edit before posting.\n"
            f"Once the full Session Update pipeline is live, upload a partial\n"
            f"results file and we'll generate live-coverage cards automatically."
        )
