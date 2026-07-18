"""Finding #21 — the three documented web feature flags are real gates.

The deep review suspected `_club_platform_ok` and `_v73_ok` were near-vestigial
and could be removed. Inspection shows all three are legitimate optional-feature
capability probes with live consumers, so they must stay:

* ``_v73_ok`` is True iff the v7.3 grouped-pack / voice imports succeeded. It
  gates the ``/pack/<id>/grouped`` route AND is read by
  ``tests/test_card_reactions.py`` as a capability gate. Its route guard keeps
  the invariant ``_v73_ok -> _build_grouped_pack is not None``.
* ``_club_platform_ok`` is True iff the ``club_platform`` modules import; it
  guards a UI link so a degraded build never renders a link into a route that
  would 500.
* ``_v8_ok`` is the V8 media-engine gate.

This is a characterization test: it documents that the flags exist as booleans
and that the ``_v73_ok`` invariant holds, so a future "cleanup" that drops or
weakens them fails loudly.
"""

import importlib

import mediahub.web.web as wm


def test_all_three_feature_flags_are_booleans():
    for name in ("_club_platform_ok", "_v73_ok", "_v8_ok"):
        assert hasattr(wm, name), f"{name} must remain a defined feature flag"
        assert isinstance(getattr(wm, name), bool), f"{name} must be a bool gate"


def test_v73_flag_matches_grouped_pack_availability():
    # The route guard `if not _v73_ok or _build_grouped_pack is None:` relies on
    # this equivalence; if the flag is True the builder symbol must be bound.
    if wm._v73_ok:
        assert wm._build_grouped_pack is not None
    else:
        assert wm._build_grouped_pack is None


def test_club_platform_flag_matches_module_availability():
    # The flag probes importability of the club_platform surface it guards.
    expected = all(
        importlib.util.find_spec(m) is not None
        for m in (
            "mediahub.club_platform.content_types",
            "mediahub.club_platform.athlete_spotlight",
            "mediahub.club_platform.stubs",
        )
    )
    assert wm._club_platform_ok is expected
