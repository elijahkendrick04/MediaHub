"""Tier B §5.5 deterministic brand-compliance gate + Tier A legibility guard.

The gate (``quality.compliance``) scores the text/background pairs a v2 card
paints, using APCA. Two jobs here:

1. unit-check the gate distinguishes legible from illegible role assignments;
2. **guard Tier A**: every role set the renderer resolves (``_mh_role_vars``)
   must pass the gate — the regression test for the accent-legibility fix, now
   expressed through the same gate that will rank the Tier B director's pool.
"""

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.graphic_renderer.render import _mh_role_vars
from mediahub.quality import compliance


def test_is_legible_distinguishes_good_from_bad():
    assert compliance.is_legible("#C9A227", "#0E2A47")  # gold on navy reads
    assert not compliance.is_legible("#000000", "#A30D2D")  # black on dark red does not


def test_check_roles_passes_a_legible_assignment():
    roles = {
        "--mh-primary": "#0A2540",
        "--mh-surface": "#05121F",
        "--mh-accent": "#F2C14E",
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FFFFFF",
        "--mh-outline": "rgba(255,255,255,0.20)",  # non-hex, ignored
    }
    report = compliance.check_roles(roles)
    assert report.passes, report.failures
    assert 0.0 < report.score <= 1.0


def test_check_roles_flags_an_illegible_assignment():
    bad = {
        "--mh-primary": "#A30D2D",
        "--mh-surface": "#5A0A18",
        "--mh-accent": "#000000",  # black accent on dark red — unreadable kicker + chip
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FFFFFF",
    }
    report = compliance.check_roles(bad)
    assert not report.passes
    assert report.failures
    assert report.score < 1.0


# --- Tier A legibility regression guard: every resolved role set is compliant ---
@pytest.mark.parametrize(
    "primary,secondary,accent",
    [
        ("#0A2540", "#F2C14E", None),  # navy + gold (secondary becomes accent)
        ("#A30D2D", "#000000", None),  # red only — the accent-collapse case
        ("#0E5BFF", "#101820", None),  # blue + near-black secondary
        ("#1B7A3D", "#000000", "#FFD24A"),  # green + explicit gold accent
        ("#6A1B9A", "#000000", None),  # purple only
    ],
)
def test_resolved_roles_are_brand_compliant(primary, secondary, accent):
    kit = BrandKit(
        profile_id="x",
        display_name="X",
        primary_colour=primary,
        secondary_colour=secondary,
        short_name="X",
        accent_colour=accent,
    )
    report = compliance.check_roles(_mh_role_vars({}, kit))
    assert report.passes, f"{primary}/{secondary}/{accent} -> {report.failures} ({report.pairs})"
