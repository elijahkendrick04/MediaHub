"""workflow store — 1.24 translated-variant persistence on a card.

A translated variant rides with the card so approving the card approves the
language pair. These pin the storage contract + back-compat with pre-1.24
sidecars.
"""

from __future__ import annotations

from mediahub.workflow.status import CardStatus, CardWorkflowState
from mediahub.workflow.store import WorkflowStore

RUN = "run-1"
CARD = "swim-001"


def _variant(lang="cy", caption="Nofio gwych!"):
    return {
        "language": lang,
        "language_base": lang.split("-")[0],
        "language_label": "Cymraeg",
        "rtl": False,
        "script": "latin",
        "regional_only": False,
        "slots": {"caption": caption},
        "provider": "gemini-api",
        "warnings": [],
    }


class TestSetTranslation:
    def test_stores_variant_under_language_key(self, tmp_path):
        ws = WorkflowStore(tmp_path)
        ws.set_translation(RUN, CARD, "cy", _variant())
        states = ws.load(RUN)
        assert CARD in states
        tr = states[CARD].translations
        assert tr and "cy" in tr
        assert tr["cy"]["slots"]["caption"] == "Nofio gwych!"

    def test_retranslate_overwrites_same_language_keeps_others(self, tmp_path):
        ws = WorkflowStore(tmp_path)
        ws.set_translation(RUN, CARD, "cy", _variant("cy", "first"))
        ws.set_translation(RUN, CARD, "fr", _variant("fr", "français"))
        ws.set_translation(RUN, CARD, "cy", _variant("cy", "second"))
        tr = ws.load(RUN)[CARD].translations
        assert tr["cy"]["slots"]["caption"] == "second"
        assert tr["fr"]["slots"]["caption"] == "français"

    def test_translation_does_not_change_status(self, tmp_path):
        ws = WorkflowStore(tmp_path)
        # Card starts implicitly QUEUE; translating must not bump it to EDITED.
        ws.set_translation(RUN, CARD, "cy", _variant())
        assert ws.load(RUN)[CARD].status == CardStatus.QUEUE

    def test_translation_preserves_existing_edits_and_status(self, tmp_path):
        ws = WorkflowStore(tmp_path)
        ws.set_status(RUN, CARD, CardStatus.APPROVED)
        ws.set_edits(RUN, CARD, {"warm-club_headline": "Hi"})
        ws.set_translation(RUN, CARD, "cy", _variant())
        st = ws.load(RUN)[CARD]
        assert st.status == CardStatus.APPROVED
        assert st.edited_captions == {"warm-club_headline": "Hi"}
        assert st.translations["cy"]["slots"]["caption"] == "Nofio gwych!"

    def test_blank_language_is_ignored(self, tmp_path):
        ws = WorkflowStore(tmp_path)
        ws.set_translation(RUN, CARD, "", _variant())
        assert ws.load(RUN) == {}


class TestStateRoundTrip:
    def test_to_from_dict_carries_translations(self):
        st = CardWorkflowState(card_id=CARD, translations={"cy": _variant()})
        d = st.to_dict()
        assert d["translations"]["cy"]["language"] == "cy"
        back = CardWorkflowState.from_dict(d)
        assert back.translations == st.translations

    def test_back_compat_old_sidecar_without_translations(self):
        # A pre-1.24 sidecar row has no 'translations' key.
        old = {
            "card_id": CARD,
            "status": "approved",
            "edited_captions": None,
            "notes": None,
            "posted_at": None,
            "last_changed_at": "2026-01-01T00:00:00Z",
        }
        st = CardWorkflowState.from_dict(old)
        assert st.translations is None
        assert st.status == CardStatus.APPROVED

    def test_translations_present_in_content_pack_workflow_dict(self, tmp_path):
        # build_content_pack copies workflow.to_dict() onto the card, so the
        # variant rides into export with no pack.py change.
        ws = WorkflowStore(tmp_path)
        ws.set_status(RUN, CARD, CardStatus.APPROVED)
        ws.set_translation(RUN, CARD, "cy", _variant())
        wf_dict = ws.load(RUN)[CARD].to_dict()
        assert wf_dict["translations"]["cy"]["slots"]["caption"] == "Nofio gwych!"
