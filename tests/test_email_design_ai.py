"""Email & newsletter composer (roadmap 1.17) — build 2: the AI editorial pass.

The AI only writes the intro/subject/preheader, fact-grounded, and honest-errors
with no provider. The newsletter's body is the real approved cards.
"""

from __future__ import annotations

from datetime import date

import pytest

import mediahub.media_ai.llm as llm
from mediahub.email_design.draft import draft_editorial, generate_newsletter
from mediahub.email_design.grounding import NewsletterFacts


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    return tmp_path


def _facts():
    return NewsletterFacts(
        club_name="Otters SC",
        period="June 2026",
        date_start="2026-06-01",
        date_end="2026-06-30",
        stats=[{"value": "12", "label": "PBs"}, {"value": "3", "label": "Medals"}],
        recaps=[{"title": "Maya — PB", "body": "x", "card_ref": "r/c", "href": "", "image_url": ""}],
    )


def test_draft_editorial_honest_errors_without_provider(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    with pytest.raises(llm.ClaudeUnavailableError):
        draft_editorial(_facts(), "monthly_roundup")


def test_draft_editorial_keeps_grounded_drops_ungrounded(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    # intro is grounded (12, 3, 2026 all allowed); subject invents "50"
    fake = {
        "intro": "A superb June 2026 — 12 PBs and 3 medals for the squad.",
        "subject": "Otters smash 50 records",  # 50 is NOT in the facts → dropped
        "preheader": "Your June 2026 update",
    }
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: dict(fake))
    out = draft_editorial(_facts(), "monthly_roundup")
    assert "12 PBs and 3 medals" in out["intro"]
    assert "subject" not in out  # ungrounded number dropped the subject
    assert out["preheader"] == "Your June 2026 update"


def test_draft_editorial_provider_failure_is_honest(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "generate_json", _boom)
    with pytest.raises(llm.ClaudeUnavailableError):
        draft_editorial(_facts(), "monthly_roundup")


def test_numbers_grounded_requires_exact_matches():
    from mediahub.email_design.draft import _numbers_grounded

    # near-miss floats must not pass (no ±0.6 window, no int truncation)
    assert not _numbers_grounded("we saw 3.9 medals", {3.0})
    # integer display of a float stat still passes
    assert _numbers_grounded("12 PBs this month", {12.0})
    # a fabricated time must not pass against nearby stats
    assert not _numbers_grounded("Maya swam 1:02.45", {1.0, 2.0, 3.0, 12.0})


def test_draft_editorial_unparseable_reply_is_honest_error(monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    # generate_json returns its ``fallback`` object when the provider answered
    # but produced unparseable JSON — that must surface, not silently downgrade
    monkeypatch.setattr(llm, "generate_json", lambda *a, **k: k.get("fallback"))
    with pytest.raises(llm.ClaudeUnavailableError, match="unparseable"):
        draft_editorial(_facts(), "monthly_roundup")


def test_generate_newsletter_without_ai_needs_no_provider(monkeypatch, tmp_path):
    # with_ai=False → deterministic intro, no provider required, no error
    monkeypatch.setattr(llm, "is_available", lambda: False)
    spec = generate_newsletter(
        "club-a",
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        newsletter_format="monthly_roundup",
        with_ai=False,
        profile={"display_name": "Otters SC"},
        runs_dir=tmp_path / "runs_v4",
        now=date(2026, 6, 22),
    )
    assert spec.newsletter_format == "monthly_roundup"
    assert spec.title and spec.sections


def test_generate_newsletter_with_ai_and_no_provider_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    with pytest.raises(llm.ClaudeUnavailableError):
        generate_newsletter(
            "club-a",
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
            with_ai=True,
            profile={"display_name": "Otters SC"},
            runs_dir=tmp_path / "runs_v4",
            now=date(2026, 6, 22),
        )


def test_generate_newsletter_with_ai_uses_drafted_intro(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_json",
        lambda *a, **k: {"intro": "A quiet but proud month.", "subject": "June", "preheader": "Hello"},
    )
    spec = generate_newsletter(
        "club-a",
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
        with_ai=True,
        profile={"display_name": "Otters SC"},
        runs_dir=tmp_path / "runs_v4",
        now=date(2026, 6, 22),
    )
    blob = " ".join(str(b.props) for s in spec.sections for b in s.blocks)
    assert "A quiet but proud month." in blob
    assert spec.subject == "June"
