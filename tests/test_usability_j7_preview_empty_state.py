"""J-7 — the channel-preview empty state must offer a way out.

A draft with no cards rendered just "This draft has no cards to preview yet." with
no link — a dead end — while the ad-variants page's identical case linked back to
the draft to "Add or regenerate cards". The preview empty state now mirrors that
pattern and links back to the draft.
"""

from __future__ import annotations

import pathlib

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_preview_empty_state_links_back_to_draft():
    # The bare dead-end paragraph is gone…
    assert '<p class="dim">This draft has no cards to preview yet.</p>' not in _SRC
    # …replaced by a version that links back to add/regenerate cards.
    assert "This draft has no cards to preview yet. " in _SRC
    assert "Add or regenerate cards</a> first.</p>" in _SRC


def test_preview_link_targets_the_draft():
    # The escape link points at the draft (stub_pack_view), like ad-variants.
    assert _SRC.count('url_for("stub_pack_view", pack_id=pack_id)') >= 2
