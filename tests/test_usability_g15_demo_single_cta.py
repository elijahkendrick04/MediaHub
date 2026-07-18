"""G-15 — the demo preview must show one CTA, not a signup button plus a
near-identical claim button, to a signed-in visitor.

The demo footer rendered "Sign up — keep your preview →" unconditionally and
*also* rendered "Keep this preview in my workspace" when a profile was active, so
a signed-in user saw two near-identical CTAs (one leading to an account flow they
had already completed). The footer now shows the claim CTA when signed in and the
signup CTA only to anonymous visitors.

The demo page needs a temp demo run to render, so this guards the branch at the
source level.
"""

from __future__ import annotations

import pathlib
import re
from tests._helpers import web_surface_src

_SRC = web_surface_src()


def test_single_cta_chosen_by_auth_state():
    # One cta_html, chosen by whether a profile is active.
    # The handler lives on the carved surface, where module globals read as
    # W.<name> — accept either spelling of the auth-state branch.
    assert re.search(r"if (?:W\.)?_active_profile\(\) is not None:", _SRC)
    assert "try_demo_claim" in _SRC
    # The footer renders the single chosen CTA, not both buttons.
    assert "{cta_html}" in _SRC


def test_signup_button_no_longer_unconditional():
    # The old always-rendered signup button beside a separate claim_html is gone.
    assert "{claim_html}" not in _SRC
