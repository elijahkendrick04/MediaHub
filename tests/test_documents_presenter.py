"""Document engine (roadmap 1.15) — build 4: deck view-model + presenter sessions."""

from __future__ import annotations

import pytest

from mediahub.documents import deck, presenter
from mediahub.documents import models as m
from mediahub.documents.models import DocumentSpec, Section


def _deck():
    return DocumentSpec(
        title="AGM 2026",
        kind="deck",
        geometry="slide_16_9",
        sections=[
            Section(layout="cover", blocks=[m.heading("AGM 2026", 1)], notes="Welcome everyone."),
            Section(
                blocks=[m.heading("The year", 2), m.bullet_list(["a", "b"])], notes="Talk numbers."
            ),
            Section(layout="closing", blocks=[m.heading("Thanks", 1)]),
        ],
    )


# ---------------------------------------------------------------------------
# deck view-model
# ---------------------------------------------------------------------------


def test_spec_version_stable_and_changes_on_edit():
    d1 = _deck()
    v1 = deck.spec_version(d1)
    assert v1 == deck.spec_version(DocumentSpec.from_dict(d1.to_dict()))  # stable
    d2 = DocumentSpec.from_dict(d1.to_dict())
    d2.sections.append(Section(blocks=[m.heading("Extra", 2)]))
    assert deck.spec_version(d2) != v1  # content changed → version changed


def test_deck_view_outline_with_notes():
    view = deck.deck_view(_deck())
    assert view["total"] == 3
    assert view["kind"] == "deck"
    assert view["slides"][0]["title"] == "AGM 2026"
    assert view["slides"][0]["notes"] == "Welcome everyone."
    assert view["slides"][1]["title"] == "The year"
    assert view["slides"][2]["title"] == "Thanks"  # falls back to first heading


# ---------------------------------------------------------------------------
# presenter sessions
# ---------------------------------------------------------------------------


def test_create_session_has_code_and_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="club-1", spec_version="v1")
    assert s.current == 0
    assert s.total_slides == 3
    assert len(s.pairing_code) == 6
    assert s.pairing_code.isupper()
    # round-trips from disk
    again = presenter.get_session(s.session_id)
    assert again is not None and again.doc_id == "doc1"


def test_get_by_pairing_code(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="club-1")
    found = presenter.get_by_pairing_code(s.pairing_code.lower())  # case-insensitive
    assert found is not None and found.session_id == s.session_id
    assert presenter.get_by_pairing_code("ZZZZZZ") is None


def test_actions_navigate_and_clamp(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="club-1")
    sid = s.session_id

    assert presenter.apply_action(sid, "next").current == 1
    assert presenter.apply_action(sid, "next").current == 2
    assert presenter.apply_action(sid, "next").current == 2  # clamped at last
    assert presenter.apply_action(sid, "prev").current == 1
    assert presenter.apply_action(sid, "goto", 0).current == 0
    assert presenter.apply_action(sid, "prev").current == 0  # clamped at first
    assert presenter.apply_action(sid, "goto", 99).current == 2  # clamped to total-1


def test_blackout_and_autoplay_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sid = presenter.create_session("doc1", 3, owner="club-1").session_id
    assert presenter.apply_action(sid, "blackout").blackout is True
    assert presenter.apply_action(sid, "blackout").blackout is False
    assert presenter.apply_action(sid, "blackout", True).blackout is True
    assert presenter.apply_action(sid, "autoplay", True).autoplay is True


def test_manual_nav_takes_control_from_autoplay(tmp_path, monkeypatch):
    """D-11: while autoplaying, a manual next/prev/goto hands control back to the
    presenter (autoplay off) so the audience follows the driver, not the loop."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    sid = presenter.create_session("doc1", 3, owner="club-1").session_id

    assert presenter.apply_action(sid, "autoplay", True).autoplay is True
    s = presenter.apply_action(sid, "next")
    assert s.current == 1 and s.autoplay is False  # next stopped the loop

    presenter.apply_action(sid, "autoplay", True)
    assert presenter.apply_action(sid, "prev").autoplay is False  # prev too

    presenter.apply_action(sid, "autoplay", True)
    g = presenter.apply_action(sid, "goto", 2)
    assert g.current == 2 and g.autoplay is False  # goto too

    # blackout / timer_reset do NOT stop autoplay (they're not navigation)
    presenter.apply_action(sid, "autoplay", True)
    assert presenter.apply_action(sid, "blackout").autoplay is True


def test_end_session_then_pairing_lookup_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="club-1")
    presenter.apply_action(s.session_id, "end")
    # ended sessions are not reachable by pairing code (can't be re-driven)
    assert presenter.get_by_pairing_code(s.pairing_code) is None


def test_public_state_does_not_leak_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="secret-club")
    state = s.public_state()
    assert "owner" not in state
    assert state["current"] == 0 and state["total"] == 3


def test_update_spec_bumps_version_and_clamps(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 5, owner="club-1", spec_version="v1")
    presenter.apply_action(s.session_id, "goto", 4)
    updated = presenter.update_spec(s.session_id, total_slides=2, spec_version="v2")
    assert updated.spec_version == "v2"
    assert updated.total_slides == 2
    assert updated.current == 1  # clamped into the new, shorter deck


def test_unique_codes_among_live_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    codes = {presenter.create_session("d", 2, owner="c").pairing_code for _ in range(8)}
    assert len(codes) == 8  # no collisions among concurrently-live sessions


def test_expiry_and_purge(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    s = presenter.create_session("doc1", 3, owner="club-1")
    # jump past the TTL
    monkeypatch.setattr(presenter, "_now", lambda: s.updated_at + presenter.SESSION_TTL_SECONDS + 1)
    assert presenter.get_session(s.session_id) is None  # expired → gone
    assert presenter.purge_expired() >= 0
