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

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

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
