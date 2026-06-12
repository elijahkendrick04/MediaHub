"""tests/test_followup_audits.py — second-round audits for M2-M5.

After the first round of work I missed four items the user explicitly
asked for. Each missed item has a creation subtask + 5 audits in this
file. Followed by 3 independent verification subtasks at the bottom.

  M2. "Where can AI read you" section must be visually optional.
  M3. Logo cap should reflect "as many as the club likes".
  M4. Logo formats should accept "whatever format the club likes".
  M5. Per-link AI status + re-read-now control surfaced in the UI.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web.club_profile import ClubProfile, save_profile, load_profile  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def iso_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client(iso_root, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from mediahub.brand import link_handlers

    monkeypatch.setattr(
        link_handlers,
        "process_links",
        lambda **kw: {"any_real": False, "state": {}, "merged_dna": {}},
    )
    from mediahub.web.web import create_app

    app = create_app()
    return app.test_client()


def _seed_profile(profile_id="audit", **kw) -> ClubProfile:
    prof = ClubProfile(
        profile_id=profile_id, display_name=kw.pop("display_name", "Audit Org"), **kw
    )
    save_profile(prof)
    return prof


# ---------------------------------------------------------------------------
# M2 — "Where can AI read you" is visually optional
# ---------------------------------------------------------------------------


class TestM2OptionalSection:
    def test_section_is_collapsible_details_element(self, client):
        body = client.get("/organisation/setup").get_data(as_text=True)
        # The section is wrapped in <details>, not a plain <div>
        assert '<details class="card mh-optional-section"' in body

    def test_section_summary_carries_optional_chip(self, client):
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Optional" in body
        # The summary contains the heading text
        assert "Where can the AI read you?" in body

    def test_section_opens_by_default_so_users_dont_miss_it(self, client):
        """First-run users should see the inputs even though the
        section is optional. The <details> tag defaults to open."""
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Match either standalone "open" attribute or open + style
        import re

        opening_tag = re.search(
            r'<details class="card mh-optional-section"[^>]*>',
            body,
        )
        assert opening_tag is not None
        assert " open" in opening_tag.group(0)

    def test_section_explicitly_says_skip_if_you_want(self, client):
        """The section's prose has to make optionality unmistakable —
        otherwise users feel they must fill it in."""
        body = client.get("/organisation/setup").get_data(as_text=True)
        assert "Skip this section entirely" in body

    def test_collapsing_section_doesnt_break_form_submission(self, client, iso_root, monkeypatch):
        """Audit safety net: a user who collapses the section without
        filling anything in should still be able to submit the rest of
        the form. <details> doesn't strip its contained inputs from
        the POST body — verify by submitting with no link data."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        resp = client.post(
            "/organisation/setup/capture",
            data={
                "accept_dpa": "1",
                "confirm_lawful_basis": "1",
                "display_name": "No Links Org",
                "country": "France",
            },
        )
        assert resp.status_code in (302, 303)
        prof = load_profile("no-links-org")
        assert prof is not None
        assert prof.country == "France"
        # No social links recorded
        assert prof.social_links == {}


# ---------------------------------------------------------------------------
# M3 — "As many logos as the club likes"
# ---------------------------------------------------------------------------


class TestM3LogoCap:
    def test_cap_is_far_above_realistic_use(self):
        from mediahub.brand.logos import MAX_LOGOS_PER_PROFILE

        # Per the user's "as many as you like" directive, the cap is
        # only there to stop pathological automation. Anything below
        # ~100 would feel constraining.
        assert MAX_LOGOS_PER_PROFILE >= 100

    def test_store_logo_accepts_well_beyond_the_old_cap(self, iso_root):
        from mediahub.brand import logos as _logos

        existing = [{"logo_id": f"x{i}"} for i in range(30)]
        # Old cap was 25; new cap must accept 30 cleanly
        meta = _logos.store_logo(
            profile_id="bulk",
            filename="logo.png",
            file_bytes=b"\x89PNG\r\n\x1a\n" + b"x" * 50,
            existing_logos=existing,
        )
        assert meta["logo_id"]

    def test_signup_page_messaging_no_longer_advertises_a_hard_limit(self, client):
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Old text said "Up to 25 files · 20 MB each"; new text says
        # "As many as you have · up to 50 MB each". The "25 MB" hit
        # for the brand-guidelines uploader is unrelated, so we check
        # for the specific old logo-cap copy.
        assert "As many as you have" in body
        assert "Up to 25 files" not in body
        assert "20 MB each" not in body

    def test_per_file_size_cap_increased_for_design_files(self):
        from mediahub.brand.logos import MAX_LOGO_BYTES

        # Native design-tool files (PSD, INDD) can easily run 30-40 MB.
        # The old 20 MB cap was too low.
        assert MAX_LOGO_BYTES >= 40 * 1024 * 1024

    def test_cap_still_protects_against_pathological_input(self, iso_root):
        """The cap isn't gone, it's just generous. Verify the upper
        bound still raises — otherwise a buggy script could fill disk."""
        from mediahub.brand import logos as _logos

        existing = [{"logo_id": f"x{i}"} for i in range(_logos.MAX_LOGOS_PER_PROFILE)]
        with pytest.raises(ValueError):
            _logos.store_logo(
                profile_id="bulk",
                filename="logo.png",
                file_bytes=b"\x89PNG\r\n\x1a\n" + b"x" * 50,
                existing_logos=existing,
            )


# ---------------------------------------------------------------------------
# M4 — "Whatever format the club likes"
# ---------------------------------------------------------------------------


class TestM4LogoFormats:
    @pytest.mark.parametrize(
        "ext",
        [
            "bmp",
            "heic",
            "heif",
            "avif",
            "ico",
            "jxl",
            "psd",
            "indd",
            "sketch",
            "fig",
            "xd",
            "afdesign",
            "afphoto",
            "cdr",
            "exr",
            "dng",
        ],
    )
    def test_new_format_extensions_are_accepted(self, iso_root, ext):
        from mediahub.brand import logos as _logos

        assert ext in _logos.ALLOWED_EXTENSIONS, (
            f"format .{ext} should be accepted per 'whatever format' brief"
        )
        meta = _logos.store_logo(
            profile_id="formats",
            filename=f"variant.{ext}",
            file_bytes=b"dummy content",
        )
        assert meta["original_filename"].endswith(f".{ext}")

    def test_unsupported_executable_still_rejected(self, iso_root):
        """The expansion is for *design* formats. Executables, scripts,
        archives must still be rejected — they aren't logos."""
        from mediahub.brand import logos as _logos

        for ext in ("exe", "dll", "sh", "py", "zip", "tar"):
            assert ext not in _logos.ALLOWED_EXTENSIONS
        with pytest.raises(ValueError):
            _logos.store_logo(profile_id="x", filename="hack.exe", file_bytes=b"MZ")

    def test_accept_attribute_advertises_design_tool_formats(self, client):
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Spot-check that the file input's accept= advertises the new
        # formats so the OS file picker filters correctly on macOS / Win.
        for token in (".psd", ".indd", ".sketch", ".fig", ".xd", ".heic", ".avif", ".bmp", ".ico"):
            assert token in body, f"accept= missing {token!r}"

    def test_helper_text_mentions_the_design_formats(self, client):
        """Audit the user-facing copy — a logo dropper looking at the
        zone needs to know more than "PNG/JPG" is accepted."""
        body = client.get("/organisation/setup").get_data(as_text=True)
        # Mentions at least Photoshop, InDesign, Sketch, Figma, XD
        for fmt_word in ("PSD", "INDD", "Sketch", "Figma", "XD"):
            assert fmt_word in body, f"helper text missing {fmt_word}"

    def test_format_count_significantly_expanded(self):
        from mediahub.brand.logos import ALLOWED_EXTENSIONS

        # Old set had 11 entries; new set should be at least double.
        assert len(ALLOWED_EXTENSIONS) >= 22


# ---------------------------------------------------------------------------
# M5 — Per-link AI status + re-read-now control
# ---------------------------------------------------------------------------


class TestM5StatusAndReread:
    def test_idle_chip_shown_for_unfilled_platforms(self, client):
        """A fresh user with no link data sees an Idle chip per row so
        they understand what the chip is for once they fill the field."""
        body = client.get("/organisation/setup").get_data(as_text=True)
        # The first paint has no captured state — all chips show Idle.
        # We see at least one Idle chip (no fields populated yet).
        # The chip text appears literally in the rendered HTML.
        assert "Idle" in body

    def test_learned_chip_replaces_idle_after_capture(self, iso_root, client):
        from mediahub.brand import link_handlers, social_dna

        prof = _seed_profile(
            profile_id="m5",
            social_links={"instagram": "https://instagram.com/x"},
            link_capture_state={
                "instagram": {
                    "url": "https://instagram.com/x",
                    "status": "real_content",
                    "playbook_age": 0,
                    "regenerated": False,
                    "voice_digest": "demo",
                }
            },
        )
        with client as c:
            with c.session_transaction() as sess:
                sess["active_profile_id"] = "m5"
                sess["login_seen_at"] = int(time.time())
            body = c.get("/organisation/setup").get_data(as_text=True)
        assert "Learned" in body

    def test_blocked_state_renders_distinct_chip(self, iso_root, client):
        _seed_profile(
            profile_id="m5b",
            social_links={"facebook": "https://facebook.com/x"},
            link_capture_state={
                "facebook": {
                    "url": "https://facebook.com/x",
                    "status": "hard_blocked",
                    "playbook_age": 0,
                    "regenerated": False,
                    "voice_digest": "",
                }
            },
        )
        with client as c:
            with c.session_transaction() as sess:
                sess["active_profile_id"] = "m5b"
                sess["login_seen_at"] = int(time.time())
            body = c.get("/organisation/setup").get_data(as_text=True)
        assert "Blocked" in body

    def test_reread_endpoint_exists_and_updates_state(self, iso_root, monkeypatch):
        """The "Re-read" button must POST to a real endpoint that
        actually re-runs the link pipeline and updates the captured
        state on the profile."""
        from mediahub.brand import link_handlers
        from mediahub.brand.link_handlers import instagram as ig_handler

        called = {"n": 0}

        def fake_process(url):
            called["n"] += 1
            return {
                "platform": "instagram",
                "url": url,
                "status": "real_content",
                "playbook_age": 0,
                "regenerated": True,
                "dna": {"voice_summary": "Fresh voice."},
            }

        monkeypatch.setattr(ig_handler, "process", fake_process)

        _seed_profile(
            profile_id="m5c",
            social_links={"instagram": "https://instagram.com/x"},
            link_capture_state={
                "instagram": {
                    "status": "hard_blocked",
                    "url": "https://instagram.com/x",
                    "playbook_age": 0,
                    "regenerated": False,
                    "voice_digest": "",
                }
            },
        )
        from mediahub.web.web import create_app

        app = create_app()
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["active_profile_id"] = "m5c"
                sess["login_seen_at"] = int(time.time())
            r = c.post("/organisation/setup/reread/instagram")
            assert r.status_code in (302, 303)

        assert called["n"] == 1
        prof = load_profile("m5c")
        assert prof.link_capture_state["instagram"]["status"] == "real_content"
        assert prof.link_capture_state["instagram"]["voice_digest"] == "Fresh voice."

    def test_reread_endpoint_no_op_without_active_profile(self, iso_root):
        """Audit safety: re-read must redirect cleanly when there's no
        session profile (anyone hitting the URL directly)."""
        from mediahub.web.web import create_app

        app = create_app()
        with app.test_client() as c:
            r = c.post("/organisation/setup/reread/instagram")
            assert r.status_code in (302, 303)
            assert r.headers["Location"].endswith("/organisation/setup")


# ---------------------------------------------------------------------------
# Verification subtasks — 3 independent end-to-end confirmations
# ---------------------------------------------------------------------------


class TestV1FullSignupFlow:
    """V1 — full smoke test from blank profile to next-page."""

    def test_render_capture_reread_persist_next_page(self, iso_root, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        from mediahub.brand import link_handlers
        from mediahub.brand.link_handlers import instagram as ig

        # Stub out the heavy pipeline so we test orchestration only.
        monkeypatch.setattr(
            link_handlers,
            "process_links",
            lambda **kw: {
                "any_real": True,
                "state": {
                    "website": {
                        "url": kw.get("website_url", ""),
                        "status": "real_content",
                        "playbook_age": 0,
                        "regenerated": True,
                        "voice_digest": "Demo voice.",
                    }
                },
                "merged_dna": {
                    "voice_summary": "Inclusive grassroots club.",
                    "keywords": ["inclusive"],
                    "phrases_to_use": [],
                    "phrases_to_avoid": [],
                    "palette_mentions": ["#0066cc"],
                    "typography_hint": "sans",
                    "sponsor_mentions": [],
                    "hashtag_patterns": [],
                },
            },
        )
        monkeypatch.setattr(
            ig,
            "process",
            lambda url: {
                "platform": "instagram",
                "url": url,
                "status": "real_content",
                "playbook_age": 0,
                "regenerated": True,
                "dna": {"voice_summary": "IG voice."},
            },
        )

        from mediahub.web.web import create_app

        app = create_app()
        with app.test_client() as c:
            # 1. GET signup
            r1 = c.get("/organisation/setup")
            assert r1.status_code == 200

            # 2. POST capture with the full form
            r2 = c.post(
                "/organisation/setup/capture",
                data={
                    "accept_dpa": "1",
                    "confirm_lawful_basis": "1",
                    "display_name": "Verify Club",
                    "org_type": "swimming_club",
                    "country": "United Kingdom",
                    "website_url": "https://verify.example",
                    "social_instagram": "https://instagram.com/verify",
                },
            )
            assert r2.status_code in (302, 303)

            # 3. Re-read the instagram link
            r3 = c.post("/organisation/setup/reread/instagram")
            assert r3.status_code in (302, 303)

            # 4. Profile carries everything
            prof = load_profile("verify-club")
            assert prof is not None
            assert prof.display_name == "Verify Club"
            assert prof.country == "United Kingdom"
            assert prof.org_type == "swimming_club"
            assert "instagram" in prof.link_capture_state
            assert prof.link_capture_state["instagram"]["status"] == "real_content"

            # 5. Next page renders for this active profile.
            # /add-input is a redirect alias to /make (the "Add Input"
            # tab was merged into "Create"); follow redirects so this
            # check survives the alias.
            r5 = c.get("/add-input", follow_redirects=True)
            assert r5.status_code == 200


class TestV2BrandContextSurfacesEverything:
    """V2 — every persisted field reaches the AI when next-page calls
    brand_context_for_llm. This is the audit the user emphasised: the
    info recorded on the signup page must be *interpreted by the
    embedded AI* on subsequent pages."""

    def test_full_profile_drives_complete_system_prompt(self, iso_root):
        from mediahub.brand.context import brand_context_for_llm

        prof = ClubProfile(
            profile_id="v2",
            display_name="V2 Verification Club",
            short_name="V2VC",
            org_type="swimming_club",
            country="France",
            governing_body="FFN",
            sponsor_name="V2 Sponsor",
            brand_voice_summary="A spirited grassroots squad.",
            brand_keywords=["grassroots", "spirit"],
            brand_phrases_to_use=["lap by lap"],
            brand_phrases_to_avoid=["elite only"],
            brand_palette_extracted={"primary": "#0066cc"},
            voice_profile={"sentence_length_avg": 18.0, "emoji_rate_per_caption": 0.5},
            brand_guidelines={"summary": "Be warm and direct.", "tone_dos": ["be specific"]},
            brand_guidelines_mandatory_rules=[
                "ALWAYS include the hashtag #V2Tag in every caption.",
            ],
            brand_logos=[
                {
                    "logo_id": "a",
                    "original_filename": "x.svg",
                    "label": "Primary wordmark",
                    "mime": "image/svg+xml",
                    "ai_description": "V2 wordmark for light backgrounds.",
                }
            ],
            link_capture_state={
                "website": {
                    "status": "real_content",
                    "url": "https://v2.example",
                    "playbook_age": 0,
                    "regenerated": False,
                    "voice_digest": "demo",
                }
            },
        )
        save_profile(prof)
        loaded = load_profile("v2")
        ctx = brand_context_for_llm(loaded)

        # Every field that affects voice must appear verbatim
        markers = [
            "V2 Verification Club",
            "V2VC",
            "swimming club",
            "France",
            "FFN",
            "V2 Sponsor",
            "spirited grassroots squad",
            "grassroots",
            "spirit",
            "lap by lap",
            "elite only",
            "Be warm and direct",
            "be specific",
            "ALWAYS include the hashtag #V2Tag in every caption.",
        ]
        for m in markers:
            assert m in ctx, f"V2 field carrying {m!r} missing from system prompt"
        # Logo inventory is opt-in (excluded from text/caption prompts to stop
        # raw logo file names leaking into copy — see test_caption_no_logo_leak);
        # asset-pickers request it explicitly, and then the logo surfaces.
        ctx_logos = brand_context_for_llm(loaded, include_logos=True)
        for m in ("Primary wordmark", "V2 wordmark for light backgrounds"):
            assert m in ctx_logos, f"V2 logo field {m!r} missing under include_logos=True"

        # Non-negotiable rules lead, recheck trails
        assert ctx.startswith("=== NON-NEGOTIABLE RULES")
        assert "re-read the NON-NEGOTIABLE RULES" in ctx[-400:]


class TestV3LegacyBackwardCompat:
    """V3 — a profile written before M2-M5 must still load and render
    correctly. No silent breakage when the JSON has none of the new
    fields and the new templates expect them."""

    def test_pre_round2_profile_still_loads_and_renders(self, iso_root):
        import json
        from mediahub.web.web import create_app

        # Profile with the old field set only — no link_capture_state,
        # no brand_logos, no mandatory rules.
        legacy = {
            "profile_id": "legacy-pre-round2",
            "display_name": "Legacy Club",
            "country": "Spain",
            "social_links": {
                "instagram": "https://instagram.com/legacy",
            },
        }
        p = iso_root / "club_profiles" / "legacy-pre-round2.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(legacy))

        app = create_app()
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["active_profile_id"] = "legacy-pre-round2"
                sess["login_seen_at"] = int(time.time())
            r = c.get("/organisation/setup")
            assert r.status_code == 200
            body = r.get_data(as_text=True)
            # Identity field pre-fills
            assert "Legacy Club" in body
            assert "Spain" in body
            # Social link pre-fills
            assert "https://instagram.com/legacy" in body
            # Status chip falls back to Idle (no captured state on the legacy profile)
            assert "Idle" in body
