"""Event Preview redesign — minimal inputs, AI event understanding,
AI-vs-manual ones to watch.

The form now takes: event name (required), optional event website link,
optional meet-pack upload, and a ones-to-watch choice — AI (reads the
entries link/file) or manual (typed list). The brief the content engine
receives must carry whatever sources were provided and instruct the
model to ground the preview in them, naming only athletes that appear
in real entries.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mediahub.club_platform.stubs import WeekendPreviewStub  # noqa: E402


def _brief(**form):
    return WeekendPreviewStub().generate_brief(form)


class TestEventPreviewBrief:
    def test_minimal_form_is_enough(self):
        b = _brief(meet_name="County Championships")
        assert "County Championships" in b
        assert "work out what this event actually IS" in b
        assert "never guess" in b

    def test_site_and_pack_text_flow_into_brief(self):
        b = _brief(
            meet_name="County Championships",
            event_site_text="Held 15-16 Feb at the Coventry 50m pool. Licensed L2.",
            event_pack_text="Warm-up 8:00, start 9:00. Entry standard times apply.",
        )
        assert "event's website says" in b
        assert "Coventry 50m pool" in b
        assert "uploaded event pack" in b
        assert "Warm-up 8:00" in b

    def test_ai_watch_mode_uses_entries_and_club(self):
        b = _brief(
            meet_name="County Championships",
            watch_mode="ai",
            entries_text="Eira Hughes 100 Free 59.80\nTom Davies 50 Back 31.00",
            club_name="Harbour City SC",
        )
        assert "Accepted entries" in b
        assert "Eira Hughes" in b
        assert "for Harbour City SC" in b
        assert "ONLY athletes who actually appear" in b

    def test_manual_watch_mode_uses_typed_athletes(self):
        b = _brief(
            meet_name="County Championships",
            watch_mode="manual",
            athletes="Sam Jones — 200 Free\nAlex Smith — 100 Back",
        )
        assert "provided by the user" in b
        assert "Sam Jones" in b
        assert "Accepted entries" not in b

    def test_ai_mode_without_entries_falls_back_to_typed_list(self):
        # The user picked AI but supplied no entries source; a typed list
        # (if any) still flows through rather than silently vanishing.
        b = _brief(
            meet_name="County Championships",
            watch_mode="ai",
            athletes="Sam Jones — 200 Free",
        )
        assert "Sam Jones" in b

    def test_form_offers_both_watch_modes_and_uploads(self):
        html = WeekendPreviewStub().render_form_html()
        assert 'name="watch_mode" value="ai"' in html
        assert 'name="watch_mode" value="manual"' in html
        assert 'name="event_website_url"' in html
        assert 'name="event_pack"' in html
        assert 'name="entries_url"' in html
        assert 'name="entries_file"' in html
        assert 'enctype="multipart/form-data"' in html


class TestEventPreviewInputGuard:
    """An empty submission must be rejected before it reaches the model —
    with nothing to ground on, a preview would be a guess. (Audit C1.)"""

    def test_empty_or_whitespace_form_is_not_meaningful(self):
        s = WeekendPreviewStub()
        assert s.has_meaningful_input({}) is False
        assert s.has_meaningful_input({"meet_name": "   "}) is False
        # Angles alone (a modifier, not a subject) is not enough to ground on.
        assert s.has_meaningful_input({"angles": "first meet of the season"}) is False
        # A website/entries URL that failed to fetch leaves no extracted text.
        assert s.has_meaningful_input({"event_website_url": "https://x"}) is False

    def test_any_real_source_is_meaningful(self):
        s = WeekendPreviewStub()
        assert s.has_meaningful_input({"meet_name": "County Championships"}) is True
        assert s.has_meaningful_input({"entries_text": "Eira Hughes 100 Free 59.80"}) is True
        assert s.has_meaningful_input({"event_pack_text": "Warm-up 8:00, start 9:00"}) is True
        assert s.has_meaningful_input({"event_site_text": "Held at Coventry 50m pool"}) is True
        assert s.has_meaningful_input({"athletes": "Sam Jones — 200 Free"}) is True

    def test_free_text_user_fields_are_capped_in_the_brief(self):
        # A huge paste into the typed fields must not balloon the prompt or
        # the persisted pack. (Audit: unbounded user fields.)
        s = WeekendPreviewStub()
        brief = s.generate_brief(
            {
                "meet_name": "M" * 5000,
                "angles": "A" * 50000,
                "athletes": "\n".join(f"Athlete {i}" for i in range(500)),
            }
        )
        assert "M" * 301 not in brief
        assert "A" * 3001 not in brief
        assert brief.count("Athlete ") <= 50


class TestEventPreviewFormAccessibility:
    """Every input carries an id and a label points at it, so screen readers
    announce the field when it takes focus. (Audit C3.)"""

    def test_every_field_has_label_association(self):
        html = WeekendPreviewStub().render_form_html()
        for fid in (
            "pv-meet-name",
            "pv-event-website",
            "pv-event-pack",
            "pv-entries-url",
            "pv-entries-file",
            "pv-athletes",
            "pv-angles",
        ):
            assert f'id="{fid}"' in html, f"missing input id {fid}"
            assert f'for="{fid}"' in html, f"missing label for {fid}"


class TestEventPreviewCopy:
    """The 'What you'll need' contract must describe the redesigned form
    (event name + website/pack + entries), not the superseded one. (Audit C2.)"""

    def test_input_contract_is_current(self):
        from mediahub.club_platform.content_types import REGISTRY, ContentType

        meta = REGISTRY[ContentType.EVENT_PREVIEW]
        ic = meta.input_contract.lower()
        assert "coming next" not in ic
        assert "entries" in ic
        # Copy we own uses plain hyphens, never em/en dashes.
        assert "—" not in meta.input_contract
        assert "–" not in meta.input_contract
        for step in meta.how_it_works.steps:
            assert "—" not in step and "–" not in step


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Boot the app with an active profile and a stubbed content engine so a
    POST never makes a real provider call. Mirrors tests/test_content_intro."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    from mediahub.web import web as webmod

    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    # The app is a module-level singleton; a sibling test may have left
    # ENFORCE_CSRF set. Pin it off here (reverted after the test) so these
    # form posts are not spuriously 403'd regardless of run order.
    monkeypatch.setitem(app.config, "ENFORCE_CSRF", False)

    import mediahub.content_engine as ce

    calls: list[dict] = []

    def _fake_generate_content(*, content_type, brief, requirements, recent_cards=None, n_cards=3):
        calls.append({"brief": brief, "content_type": content_type})
        return {"cards": [{"platform": "Instagram", "caption": "draft", "hashtags": []}]}

    monkeypatch.setattr(ce, "generate_content", _fake_generate_content)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="otter-sc", display_name="Otter SC"))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "otter-sc"})
        c._engine_calls = calls  # type: ignore[attr-defined]
        yield c


class TestEventPreviewRoute:
    """The POST route enforces the input guard end to end. (Audit C1.)"""

    def test_empty_post_is_rejected_without_calling_the_engine(self, client):
        r = client.post("/weekend-preview", data={})
        assert r.status_code == 400
        assert client._engine_calls == []
        assert b"Add something to preview" in r.data

    def test_named_event_generates_cards(self, client):
        r = client.post("/weekend-preview", data={"meet_name": "County Championships"})
        assert r.status_code == 200
        assert len(client._engine_calls) == 1
        assert "County Championships" in client._engine_calls[0]["brief"]


class TestApprovalPillCsrf:
    """The approval pill must survive production CSRF enforcement. It posts
    JSON (CSRF-exempt by content-type); a multipart post would be 403'd and
    the approval silently lost. (Audit C5 — P1.)"""

    def test_pill_js_posts_json_not_multipart(self):
        from mediahub.club_platform.stubs import render_cards_html

        html = render_cards_html(
            {"cards": [{"platform": "Instagram", "caption": "c", "status": "queue"}]},
            "/weekend-preview",
            "T",
            pack_id="abc123",
            status_api_base="/api/drafts/abc123/card",
        )
        assert "application/json" in html
        assert "JSON.stringify({status: status})" in html
        # Regression guard: must not revert to a token-less multipart post.
        assert "new FormData(); fd.append('status'" not in html
        assert "__CSRF_TOKEN__" not in html

    def test_status_route_persists_json_under_enforced_csrf(self, tmp_path, monkeypatch):
        import json as _json

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
        from mediahub.web import web as webmod

        monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
        app = webmod.app
        app.config["TESTING"] = True
        monkeypatch.setitem(app.config, "ENFORCE_CSRF", True)  # production-like (auto-reverted)

        from mediahub.web.club_profile import ClubProfile, save_profile

        save_profile(ClubProfile(profile_id="otter-sc", display_name="Otter SC"))
        from mediahub.club_platform.stub_pack_store import save_pack, load_pack

        rec = save_pack(
            "event_preview",
            {"meet_name": "County"},
            [{"platform": "Instagram", "caption": "c", "status": "queue"}],
            profile_id="otter-sc",
        )
        pid = rec["pack_id"]
        url = f"/api/drafts/{pid}/card/0/status"
        with app.test_client() as c:
            c.get("/weekend-preview")  # seed the session CSRF token
            c.post("/api/organisation/active", data={"profile_id": "otter-sc"})
            # multipart with no token is rejected by the CSRF layer
            r_form = c.post(url, data={"status": "approved"}, content_type="multipart/form-data")
            assert r_form.status_code == 403
            # JSON is exempt by content-type and persists
            r_json = c.post(
                url, data=_json.dumps({"status": "approved"}), content_type="application/json"
            )
            assert r_json.status_code == 200
            assert r_json.get_json()["status"] == "approved"
        assert (load_pack(pid)["cards"][0]["status"]) == "approved"


# LENEX with two clubs (Rival SC first in document order, Otter SC second) —
# the active org is "Otter SC" (see the client fixture), so the club-first
# ordering must lift Otter's entrant above Rival's in the brief. (Audit F8.)
_LENEX_2CLUB = (
    b'<?xml version="1.0"?>'
    b'<LENEX version="3.0"><MEETS><MEET name="County Champs" course="LCM"><CLUBS>'
    b'<CLUB name="Rival SC"><ATHLETES><ATHLETE firstname="Tom" lastname="Rival" gender="M">'
    b'<ENTRIES><ENTRY eventid="1" entrytime="00:59.80"/></ENTRIES></ATHLETE></ATHLETES></CLUB>'
    b'<CLUB name="Otter SC"><ATHLETES><ATHLETE firstname="Eira" lastname="Hughes" gender="F">'
    b'<ENTRIES><ENTRY eventid="1" entrytime="01:01.20"/></ENTRIES></ATHLETE></ATHLETES></CLUB>'
    b"</CLUBS></MEET></MEETS></LENEX>"
)


class TestEventPreviewCaveatFixes:
    """Second-pass audit: fixes for the caveats logged by the first pass."""

    # F10 — the create page must carry a single <h1> (the hero's); the stub
    # body no longer emits its own.
    def test_no_duplicate_h1_on_form(self):
        assert "<h1>" not in WeekendPreviewStub().render_stub_html()

    # F12 — the ones-to-watch toggle is pure CSS (:has), so it degrades
    # without JavaScript rather than trapping the manual panel behind an
    # inline display:none only a script can undo.
    def test_watch_toggle_is_css_and_degrades_without_js(self):
        html = WeekendPreviewStub().render_form_html()
        assert ":has(" in html
        assert "pv-watch-group" in html
        assert 'id="pv-watch-manual" style="display:none"' not in html
        assert "mhPvWatchMode" not in html

    # F15 — Event Preview copy uses plain hyphens, no em/en dashes.
    def test_form_copy_uses_plain_hyphens(self):
        html = WeekendPreviewStub().render_form_html()
        assert "—" not in html and "–" not in html

    # F8 — the brief keeps a generous slice of the entries text.
    def test_brief_entries_cap_is_generous(self):
        b = WeekendPreviewStub().generate_brief(
            {"meet_name": "M", "watch_mode": "ai", "entries_text": "Z" * 12000}
        )
        assert b.count("Z") == 9000

    # F8 — the active club's entrants are ordered first so they survive
    # truncation on a big multi-club meet.
    def test_active_club_entries_ordered_first(self, client):
        import io

        client.post(
            "/weekend-preview",
            data={
                "meet_name": "County",
                "watch_mode": "ai",
                "entries_file": (io.BytesIO(_LENEX_2CLUB), "entries.lef"),
            },
            content_type="multipart/form-data",
        )
        brief = client._engine_calls[-1]["brief"]
        assert "Eira Hughes" in brief and "Tom Rival" in brief
        assert brief.index("Eira Hughes") < brief.index("Tom Rival")

    # F7 — an entries URL that is a PDF (the common psych-sheet case) is
    # routed through the document extractor, not reduced to HTML noise.
    def test_entries_url_pdf_routed_through_extractor(self, client, monkeypatch):
        import mediahub.brand.guidelines as gl
        import mediahub.web_research.safe_fetch as sf

        monkeypatch.setattr(
            sf, "safe_fetch_bytes", lambda u, **k: ("application/pdf", b"%PDF-1.4 x")
        )
        monkeypatch.setattr(
            gl, "extract_text", lambda fn, b: {"status": "ok", "text": "PDF ENTRIES Eira Hughes"}
        )
        client.post(
            "/weekend-preview",
            data={
                "meet_name": "County",
                "watch_mode": "ai",
                "entries_url": "https://x.example/psych.pdf",
            },
        )
        assert "PDF ENTRIES Eira Hughes" in client._engine_calls[-1]["brief"]

    # F7 — an HTML entries page still works: tags/scripts stripped.
    def test_entries_url_html_sanitized(self, client, monkeypatch):
        import mediahub.web_research.safe_fetch as sf

        monkeypatch.setattr(
            sf,
            "safe_fetch_bytes",
            lambda u, **k: ("text/html", b"<b>Eira Hughes 100 Free</b><script>evil()</script>"),
        )
        client.post(
            "/weekend-preview",
            data={"meet_name": "County", "watch_mode": "ai", "entries_url": "https://x.example/e"},
        )
        b = client._engine_calls[-1]["brief"]
        assert "Eira Hughes 100 Free" in b
        assert "<script>" not in b and "evil" not in b

    # F9 — a provided source we could not read is called out on the results
    # page rather than silently dropped.
    def test_unread_source_notice(self, client, monkeypatch):
        import mediahub.web_research.safe_fetch as sf

        monkeypatch.setattr(sf, "safe_fetch_bytes", lambda u, **k: None)
        r = client.post(
            "/weekend-preview",
            data={"meet_name": "County Champs", "event_website_url": "https://dead.example/x"},
        )
        assert r.status_code == 200
        assert b"event website link" in r.data
        assert b"couldn" in r.data.lower()

    # F11 — a non-provider engine failure returns an honest 5xx and persists
    # no empty pack (was: HTTP 200 + a saved empty pack).
    def test_generic_engine_error_returns_502_and_saves_no_pack(self, client, monkeypatch):
        import mediahub.content_engine as ce
        from mediahub.club_platform import stub_pack_store as sps

        def _boom(**k):
            raise ValueError("bad model json")

        monkeypatch.setattr(ce, "generate_content", _boom)
        before = len(sps.list_packs(limit=999))
        r = client.post("/weekend-preview", data={"meet_name": "County"})
        assert r.status_code == 502
        assert len(sps.list_packs(limit=999)) == before

    # F13 — the photo attachment must decode as a real image before it is
    # stored; arbitrary bytes named .jpg are rejected.
    def test_photo_upload_rejects_non_image(self, client):
        import io

        from mediahub.web import web as webmod

        att = webmod.UPLOADS_DIR / "stub_attachments"
        before = len(list(att.glob("*"))) if att.exists() else 0
        client.post(
            "/weekend-preview",
            data={"meet_name": "County", "attached_photo": (io.BytesIO(b"not an image"), "x.jpg")},
            content_type="multipart/form-data",
        )
        after = len(list(att.glob("*"))) if att.exists() else 0
        assert after == before

    def test_photo_upload_accepts_real_image(self, client):
        import io

        from PIL import Image

        from mediahub.web import web as webmod

        att = webmod.UPLOADS_DIR / "stub_attachments"
        before = len(list(att.glob("*"))) if att.exists() else 0
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
        buf.seek(0)
        client.post(
            "/weekend-preview",
            data={"meet_name": "County", "attached_photo": (buf, "ok.png")},
            content_type="multipart/form-data",
        )
        after = len(list(att.glob("*"))) if att.exists() else 0
        assert after == before + 1

    # F14 — the parse-entries helper bounds its work on a large upload.
    def test_parse_entries_bounds_large_text(self, client):
        import io

        big = ("Sam Jones 100 Free 55.0\n" * 200000).encode()
        r = client.post(
            "/api/event-preview/parse-entries",
            data={"file": (io.BytesIO(big), "e.txt")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 200
        assert len(r.get_json()["entries_text"]) <= 20000
