"""Phase W output-layer tests — W.9 magic links, W.11/W.13 caption bundle,
W.14 approval telemetry."""

from __future__ import annotations

import json

import pytest

from mediahub.observability.approval_telemetry import preference_summary, record_event
from mediahub.web import ai_caption
from mediahub.web.ai_caption import ClaudeUnavailableError, generate_caption_bundle
from mediahub.web.magic_links import (
    MagicLinkError,
    MagicLinkExpired,
    MagicLinkRevoked,
    mint_review_token,
    revoke_run_tokens,
    verify_review_token,
)

SECRET = "test-secret-key"
ORG = "testclub"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "data.db"


# ---------------------------------------------------------------------------
# W.9 — magic links
# ---------------------------------------------------------------------------


class TestMagicLinks:
    def test_mint_verify_roundtrip(self, db):
        token = mint_review_token(SECRET, "run123", ORG, db_path=db)
        out = verify_review_token(SECRET, token, db_path=db)
        assert out == {"run_id": "run123", "profile_id": ORG}

    def test_tampered_token_rejected(self, db):
        token = mint_review_token(SECRET, "run123", ORG, db_path=db)
        with pytest.raises(MagicLinkError):
            verify_review_token(SECRET, token[:-3] + "abc", db_path=db)

    def test_wrong_secret_rejected(self, db):
        token = mint_review_token(SECRET, "run123", ORG, db_path=db)
        with pytest.raises(MagicLinkError):
            verify_review_token("other-secret", token, db_path=db)

    def test_expiry_enforced(self, db):
        token = mint_review_token(SECRET, "run123", ORG, db_path=db)
        with pytest.raises(MagicLinkExpired):
            # Negative max-age: any token, however fresh, is past its window.
            verify_review_token(SECRET, token, max_age_hours=-1, db_path=db)

    def test_revocation_kills_existing_tokens(self, db):
        token = mint_review_token(SECRET, "run123", ORG, db_path=db)
        revoke_run_tokens("run123", db_path=db)
        with pytest.raises(MagicLinkRevoked):
            verify_review_token(SECRET, token, db_path=db)
        # A fresh token minted after revocation works.
        token2 = mint_review_token(SECRET, "run123", ORG, db_path=db)
        assert verify_review_token(SECRET, token2, db_path=db)["run_id"] == "run123"

    def test_revocation_is_per_run(self, db):
        t_other = mint_review_token(SECRET, "runOTHER", ORG, db_path=db)
        revoke_run_tokens("run123", db_path=db)
        assert verify_review_token(SECRET, t_other, db_path=db)["run_id"] == "runOTHER"

    def test_no_secret_refused(self, db):
        with pytest.raises(MagicLinkError):
            mint_review_token("", "run123", ORG, db_path=db)


# ---------------------------------------------------------------------------
# W.11 / W.13 — caption bundle (caption + alt text + translation, one call)
# ---------------------------------------------------------------------------

_ACH = {
    "swimmer_name": "Maya Patel",
    "event": "100m Freestyle",
    "headline": "PB for Maya Patel",
    "type": "pb_confirmed",
    "raw_facts": {"time": "1:05.32"},
}


class TestCaptionBundle:
    def _patch(self, monkeypatch, response: str):
        calls = []

        def fake_call(system, user, max_tokens=400, **kw):
            calls.append({"system": system, "user": user})
            return response

        monkeypatch.setattr(ai_caption, "call_claude", fake_call)
        return calls

    def test_single_call_returns_caption_and_alt(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            json.dumps(
                {
                    "caption": "Maya flies to 1:05.32!",
                    "alt_text": "Maya Patel, 100m Freestyle, 1:05.32 — a new PB.",
                }
            ),
        )
        out = generate_caption_bundle(_ACH)
        assert out["caption"] == "Maya flies to 1:05.32!"
        assert "1:05.32" in out["alt_text"]
        assert out["caption_secondary"] is None
        assert out["secondary_language"] is None
        assert len(calls) == 1  # caption + alt text ride ONE provider call
        assert "alt_text" in calls[0]["system"]

    def test_legacy_bilingual_value_still_means_english_plus_welsh(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            json.dumps(
                {
                    "caption": "A new PB!",
                    "alt_text": "alt",
                    "caption_secondary": "Record personol newydd!",
                }
            ),
        )
        out = generate_caption_bundle(_ACH, language="bilingual")
        assert out["caption_secondary"] == "Record personol newydd!"
        assert out["secondary_language"] == "cy"
        assert "caption_secondary" in calls[0]["system"]
        assert "Cymraeg" in calls[0]["system"]

    def test_bilingual_pair_value(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            json.dumps(
                {
                    "caption": "A new PB!",
                    "alt_text": "alt",
                    "caption_secondary": "Record personol newydd!",
                }
            ),
        )
        out = generate_caption_bundle(_ACH, language="en+cy")
        assert out["secondary_language"] == "cy"
        assert "Cymraeg" in calls[0]["system"]

    def test_bilingual_irish_contract(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            json.dumps({"caption": "A new PB!", "alt_text": "alt", "caption_secondary": "PB nua!"}),
        )
        out = generate_caption_bundle(_ACH, language="en+ga")
        assert out["caption_secondary"] == "PB nua!"
        assert out["secondary_language"] == "ga"
        assert "Irish" in calls[0]["system"]
        assert "Gaeilge" in calls[0]["system"]

    def test_bilingual_top10_contract(self, monkeypatch):
        calls = self._patch(
            monkeypatch,
            json.dumps({"caption": "A new PB!", "alt_text": "alt", "caption_secondary": "नया PB!"}),
        )
        out = generate_caption_bundle(_ACH, language="en+hi")
        assert out["secondary_language"] == "hi"
        assert "Hindi" in calls[0]["system"]

    def test_bilingual_without_translation_is_honest_error(self, monkeypatch):
        self._patch(monkeypatch, json.dumps({"caption": "x", "alt_text": "y"}))
        with pytest.raises(ClaudeUnavailableError):
            generate_caption_bundle(_ACH, language="bilingual")
        with pytest.raises(ClaudeUnavailableError):
            generate_caption_bundle(_ACH, language="en+ga")

    def test_welsh_only_instruction(self, monkeypatch):
        calls = self._patch(monkeypatch, json.dumps({"caption": "Cymraeg!", "alt_text": "alt"}))
        out = generate_caption_bundle(_ACH, language="cy")
        assert out["caption"] == "Cymraeg!"
        assert out["caption_secondary"] is None
        assert "Welsh" in calls[0]["system"]
        assert "dull rhydd" in calls[0]["system"]  # curated swim terms kept

    def test_irish_only_instruction(self, monkeypatch):
        calls = self._patch(monkeypatch, json.dumps({"caption": "Gaeilge!", "alt_text": "alt"}))
        out = generate_caption_bundle(_ACH, language="ga")
        assert out["caption"] == "Gaeilge!"
        assert "Irish" in calls[0]["system"]

    def test_language_derived_from_club_profile(self, monkeypatch):
        from mediahub.web.club_profile import ClubProfile

        calls = self._patch(monkeypatch, json.dumps({"caption": "Allez!", "alt_text": "alt"}))
        prof = ClubProfile(profile_id="t", display_name="Club T", language="fr")
        out = generate_caption_bundle(_ACH, club_profile=prof)
        assert out["caption"] == "Allez!"
        assert "French" in calls[0]["system"]

    def test_unknown_language_falls_back_to_english(self, monkeypatch):
        calls = self._patch(monkeypatch, json.dumps({"caption": "c", "alt_text": "a"}))
        out = generate_caption_bundle(_ACH, language="klingon")
        assert out["caption_secondary"] is None
        assert "caption_secondary" not in calls[0]["system"]

    def test_spurious_translation_ignored_in_monolingual_mode(self, monkeypatch):
        # A caption_secondary key the contract never asked for must not
        # leak a translation box into the review UI.
        self._patch(
            monkeypatch,
            json.dumps({"caption": "c", "alt_text": "a", "caption_secondary": "spurious"}),
        )
        out = generate_caption_bundle(_ACH, language="en")
        assert out["caption_secondary"] is None
        assert out["secondary_language"] is None

    def test_code_fences_tolerated(self, monkeypatch):
        self._patch(
            monkeypatch, "```json\n" + json.dumps({"caption": "c", "alt_text": "a"}) + "\n```"
        )
        assert generate_caption_bundle(_ACH)["caption"] == "c"

    def test_malformed_response_is_honest_error(self, monkeypatch):
        self._patch(monkeypatch, "Sure! Here's a caption: splashy times ahead")
        with pytest.raises(ClaudeUnavailableError):
            generate_caption_bundle(_ACH)

    def test_no_provider_propagates(self, monkeypatch):
        def boom(**kw):
            raise ClaudeUnavailableError("no provider configured")

        monkeypatch.setattr(ai_caption, "call_claude", lambda **kw: boom())
        with pytest.raises(ClaudeUnavailableError):
            generate_caption_bundle(_ACH)


# ---------------------------------------------------------------------------
# W.13 (generalised) — the workspace language threads through EVERY caption
# path, not just the bundle: plain regenerates, extra variants and platform
# adaptations all derive the language from the club profile.
# ---------------------------------------------------------------------------


class TestCaptionLanguageThreading:
    def _profile(self, language: str, **kw):
        from mediahub.web.club_profile import ClubProfile

        return ClubProfile(profile_id="t", display_name="Club T", language=language, **kw)

    def test_caption_only_path_honours_workspace_language(self, monkeypatch):
        captured = {}

        def fake_call(system, user, max_tokens=400, **kw):
            captured["system"] = system
            return "Llongyfarchiadau Maya!"

        monkeypatch.setattr(ai_caption, "call_claude", fake_call)
        out = ai_caption.generate_caption_for_tone(
            _ACH, tone="ai", club_profile=self._profile("cy")
        )
        assert out == "Llongyfarchiadau Maya!"
        assert "Welsh" in captured["system"]
        assert "Cymraeg" in captured["system"]

    def test_bilingual_workspace_keeps_english_primary(self, monkeypatch):
        captured = {}

        def fake_call(system, user, max_tokens=400, **kw):
            captured["system"] = system
            return "Well swum, Maya!"

        monkeypatch.setattr(ai_caption, "call_claude", fake_call)
        prof = self._profile("en+cy", country="United Kingdom")
        ai_caption.generate_caption_for_tone(_ACH, tone="ai", club_profile=prof)
        # Primary stays English: UK spelling guidance applies, no
        # write-in-Welsh instruction on the caption-only path.
        assert "British English" in captured["system"]
        assert "Cymraeg" not in captured["system"]

    def test_explicit_language_overrides_profile(self, monkeypatch):
        captured = {}

        def fake_call(system, user, max_tokens=400, **kw):
            captured["system"] = system
            return "¡Vamos Maya!"

        monkeypatch.setattr(ai_caption, "call_claude", fake_call)
        ai_caption.generate_caption_for_tone(
            _ACH, tone="ai", club_profile=self._profile("cy"), language="es"
        )
        assert "Spanish" in captured["system"]
        assert "Cymraeg" not in captured["system"]

    def test_platform_variants_stay_in_workspace_language(self, monkeypatch):
        systems = []

        def fake_call(system, user, max_tokens=400, **kw):
            systems.append(system)
            return "variante"

        monkeypatch.setattr(ai_caption, "call_claude", fake_call)
        out = ai_caption.generate_platform_variants(
            "Maya wins gold!",
            club_profile=self._profile("es"),
            platforms=["feed", "linkedin"],
        )
        assert set(out) == {"feed", "linkedin"}
        assert all("Spanish" in s and "Español" in s for s in systems)


# ---------------------------------------------------------------------------
# W.14 — approval telemetry
# ---------------------------------------------------------------------------


class TestApprovalTelemetry:
    def test_record_and_summary(self, db):
        for _ in range(3):
            record_event(
                ORG, "r1", "c1", "approved", post_angle="club_record", tone="warm-club", db_path=db
            )
        record_event(ORG, "r1", "c2", "rejected", post_angle="recap_mention", db_path=db)
        record_event(ORG, "r1", "c2", "rejected", post_angle="recap_mention", db_path=db)
        record_event(ORG, "r1", "c3", "rejected", post_angle="recap_mention", db_path=db)
        record_event(ORG, "r1", "c4", "edited", post_angle="club_record", db_path=db)

        summary = preference_summary(ORG, db_path=db)
        assert summary["total_events"] == 7
        by_angle = {a["post_angle"]: a for a in summary["angles"]}
        assert by_angle["club_record"]["approved"] == 3
        assert by_angle["club_record"]["approval_rate"] == 1.0
        assert by_angle["recap_mention"]["approval_rate"] == 0.0
        joined = " ".join(summary["reasons"])
        assert "club record" in joined and "100%" in joined
        assert "usually rejects recap mention" in joined

    def test_min_events_floor(self, db):
        record_event(ORG, "r1", "c1", "approved", post_angle="medal_gold", db_path=db)
        summary = preference_summary(ORG, db_path=db)
        assert summary["reasons"] == []  # one event is not a pattern

    def test_invalid_action_refused(self, db):
        assert not record_event(ORG, "r1", "c1", "liked", db_path=db)

    def test_org_isolation(self, db):
        record_event(ORG, "r1", "c1", "approved", post_angle="medal_gold", db_path=db)
        assert preference_summary("otherclub", db_path=db)["total_events"] == 0
