"""G1.12 — Multi-line hero & split-result fitting.

Two layers under test:

* the deterministic autofit primitives that wrap/balance a compound surname or
  a split-time result across lines (``balance_lines`` / ``fit_balanced`` /
  ``fit_balanced_px`` in ``graphic_renderer.autofit``); and
* the renderer wiring that feeds them into the v2 *hero* archetypes — the
  surname slot of ``mega_surname_bleed`` / ``minimal_type_poster`` /
  ``split_diagonal_hero`` and the big-numeral slot of ``big_number_dominant`` /
  ``cornerstone_numeral`` — while leaving every other archetype, and every
  ordinary single-line value, byte-identical.

Box convention mirrors ``test_autofit.py``: a very tall box isolates the width
constraint; a short box exercises the height / line-count constraint.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import autofit as af
from mediahub.media_requirements.evaluator import EvaluationResult

TALL = 100_000  # never binds — isolates the width constraint

COMPOUND_HYPHEN = "WOLAJIMI-ABUBAKARI"  # one token, breaks only at the hyphen
COMPOUND_SPACED = "VAN DER BERG"  # three words, breaks at the spaces
SPLIT_RESULT = "1:45.23 / 50.12"  # two splits, breaks at the slash


# --------------------------------------------------------------------------- #
# Independent "does this block fit?" oracle (re-derived from the primitives, so
# the invariant checks don't lean on fit_balanced's own internals).
# --------------------------------------------------------------------------- #
def _block_fits(lines, size, box_w, box_h, *, font_family, weight, line_height):
    if not lines:
        return True
    if len(lines) * size * line_height > box_h + 1e-6:
        return False
    return all(
        af.measure_line_px(ln, size, font_family=font_family, weight=weight) <= box_w + 1e-6
        for ln in lines
    )


def _widest_em(lines, *, font_family, weight):
    return max(af.em_width(ln, font_family=font_family, weight=weight) for ln in lines)


# --------------------------------------------------------------------------- #
# balance_lines — tokenisation + balancing
# --------------------------------------------------------------------------- #
def test_balance_hyphen_keeps_the_hyphen_on_the_left_line():
    # A double-barrelled surname breaks AT the hyphen, which stays on the upper
    # line (real hyphenation signals the word continues), and rejoins exactly.
    lines = af.balance_lines(COMPOUND_HYPHEN, n_lines=2, font_family="Anton")
    assert lines == ["WOLAJIMI-", "ABUBAKARI"]
    assert "".join(lines) == COMPOUND_HYPHEN  # hyphen preserved, nothing dropped


def test_balance_spaced_surname_drops_the_space_at_the_break():
    lines = af.balance_lines(COMPOUND_SPACED, n_lines=2, font_family="Anton")
    assert len(lines) == 2
    # the space separator vanishes at the wrap; words rejoin to the original
    assert " ".join(lines).split() == COMPOUND_SPACED.split()
    assert "  " not in " ".join(lines)


def test_balance_split_result_drops_the_slash_at_the_break():
    lines = af.balance_lines(SPLIT_RESULT, n_lines=2, font_family="JetBrains Mono", mode="split")
    assert lines == ["1:45.23", "50.12"]  # clean stacked splits, no dangling slash


def test_balance_split_handles_bare_and_padded_slashes():
    assert af.balance_lines("49.81/50.12", n_lines=2, mode="split") == ["49.81", "50.12"]
    assert af.balance_lines("49.81  /  50.12", n_lines=2, mode="split") == ["49.81", "50.12"]


def test_balance_minimises_the_widest_line():
    # Greedy first-line packing would put "VAN DER" up top regardless; the
    # balancer must choose the split with the smallest widest line. We assert
    # the chosen widest line is no wider than any other contiguous 2-partition.
    units = af._hero_units(COMPOUND_SPACED, "name")

    def measure(a, b):
        return af.em_width(af._join_units(units[a:b]), font_family="Anton", weight=400)

    chosen = af.balance_lines(COMPOUND_SPACED, n_lines=2, font_family="Anton")
    chosen_widest = _widest_em(chosen, font_family="Anton", weight=400)
    n = len(units)
    for cut in range(1, n):
        alt_widest = max(measure(0, cut), measure(cut, n))
        assert chosen_widest <= alt_widest + 1e-9


def test_balance_unbreakable_token_stays_one_line():
    assert af.balance_lines("ANDERSON", n_lines=2, font_family="Anton") == ["ANDERSON"]


def test_balance_caps_lines_at_the_break_count():
    # Two parts can never make three lines.
    assert af.balance_lines("SMITH-JONES", n_lines=3, font_family="Anton") == ["SMITH-", "JONES"]


def test_balance_n_lines_one_is_the_whole_string():
    assert af.balance_lines(COMPOUND_SPACED, n_lines=1) == [COMPOUND_SPACED]


def test_balance_empty_is_no_lines():
    assert af.balance_lines("", n_lines=2) == []
    assert af.balance_lines("   ", n_lines=2) == []


def test_balance_is_deterministic():
    a = af.balance_lines("MAXIMILIANUS-FEATHERSTONEHAUGH", n_lines=2, font_family="Anton")
    b = af.balance_lines("MAXIMILIANUS-FEATHERSTONEHAUGH", n_lines=2, font_family="Anton")
    assert a == b


# --------------------------------------------------------------------------- #
# fit_balanced — sizing
# --------------------------------------------------------------------------- #
def test_one_line_path_matches_the_single_line_fitter_exactly():
    # The renderer's hero slots historically sized single-line via _fit_one_line_px.
    # fit_balanced with max_lines=1 (line_height=1.0) MUST reproduce it, so simple
    # names/results stay byte-identical.
    from mediahub.graphic_renderer.render import _fit_one_line_px

    for text in ("LI", "HUGHES", "VANDERSLOOTCHAMBERLAIN", "2:08.41"):
        single = _fit_one_line_px(
            text, 1080 * 0.86, 1350 * 0.18, font_family="Anton", weight=400, min_px=44, max_px=132
        )
        balanced = af.fit_balanced_px(
            text,
            1080 * 0.86,
            1350 * 0.18,
            max_lines=1,
            font_family="Anton",
            weight=400,
            min_px=44,
            max_px=132,
            line_height=1.0,
        )
        assert balanced == single, text


def test_two_lines_never_smaller_than_one_line():
    for text in (COMPOUND_HYPHEN, COMPOUND_SPACED, "ANDERSON", SPLIT_RESULT):
        mode = "split" if "/" in text else "name"
        one = af.fit_balanced_px(text, 600, 400, max_lines=1, font_family="Anton", mode=mode)
        two = af.fit_balanced_px(text, 600, 400, max_lines=2, font_family="Anton", mode=mode)
        assert two >= one, text


def test_compound_surname_fits_larger_balanced_than_single_line():
    # The headline guarantee: a name too wide for one line at the cap gets a
    # genuinely bigger size by balancing across two lines (and still fits).
    box_w, box_h = 1080 * 0.86, 1350 * 0.18
    one, _ = af.fit_balanced(
        COMPOUND_HYPHEN, box_w, box_h, max_lines=1, font_family="Anton", weight=400,
        min_px=44, max_px=240,
    )
    two, lines = af.fit_balanced(
        COMPOUND_HYPHEN, box_w, box_h, max_lines=2, font_family="Anton", weight=400,
        min_px=44, max_px=240,
    )
    assert two > one
    assert len(lines) == 2
    assert _block_fits(lines, two, box_w, box_h, font_family="Anton", weight=400, line_height=1.0)


def test_returned_layout_actually_fits():
    cases = [
        (COMPOUND_HYPHEN, "name", "Anton", 400, 700, 360, 1.0),
        (COMPOUND_SPACED, "name", "Anton", 400, 520, 300, 1.1),
        (SPLIT_RESULT, "split", "JetBrains Mono", 700, 900, 420, 1.0),
        ("49.81 / 50.12 / 51.04", "split", "JetBrains Mono", 700, 800, 500, 1.05),
    ]
    for text, mode, fam, weight, bw, bh, lh in cases:
        size, lines = af.fit_balanced(
            text, bw, bh, max_lines=3, font_family=fam, weight=weight,
            min_px=8, max_px=400, line_height=lh, mode=mode,
        )
        assert lines
        if size > 8:  # above the floor the result must genuinely fit
            assert _block_fits(lines, size, bw, bh, font_family=fam, weight=weight, line_height=lh)


def test_ties_prefer_fewer_lines():
    # A short name that fits one line at the cap must NOT be split needlessly.
    size, lines = af.fit_balanced(
        COMPOUND_SPACED, 100_000, 100_000, max_lines=2, font_family="Anton", weight=400, max_px=200
    )
    assert lines == [COMPOUND_SPACED]
    assert size == 200  # hits the cap on one line


def test_more_lines_relax_the_width_bound():
    # A wide box but a SHORT height forces more lines to shrink (height-bound);
    # a narrow box but TALL height lets balancing win on width.
    narrow_tall = af.fit_balanced_px(
        COMPOUND_HYPHEN, 360, TALL, max_lines=2, font_family="Anton", weight=400, max_px=3000
    )
    one_line = af.fit_balanced_px(
        COMPOUND_HYPHEN, 360, TALL, max_lines=1, font_family="Anton", weight=400, max_px=3000
    )
    assert narrow_tall > one_line  # the second line buys width head-room


def test_unbreakable_token_two_lines_equals_one_line():
    a = af.fit_balanced_px("ANDERSON", 500, 400, max_lines=1, font_family="Anton")
    b = af.fit_balanced_px("ANDERSON", 500, 400, max_lines=2, font_family="Anton")
    assert a == b  # nothing to break -> identical


def test_empty_text_returns_max_and_no_lines():
    size, lines = af.fit_balanced("", 100, 100, max_px=240)
    assert (size, lines) == (240, [])


def test_larger_line_height_never_fits_larger():
    tight = af.fit_balanced_px(
        COMPOUND_SPACED, 300, 400, max_lines=2, font_family="Anton", line_height=1.0, max_px=400
    )
    loose = af.fit_balanced_px(
        COMPOUND_SPACED, 300, 400, max_lines=2, font_family="Anton", line_height=2.0, max_px=400
    )
    assert loose <= tight


def test_result_within_bounds():
    for mx in (10, 60, 240):
        size = af.fit_balanced_px(COMPOUND_HYPHEN, 500, 300, min_px=10, max_px=mx, font_family="Anton")
        assert 10 <= size <= mx


def test_fit_balanced_is_deterministic():
    a = af.fit_balanced(COMPOUND_HYPHEN, 480, 260, max_lines=2, font_family="Anton", weight=400)
    b = af.fit_balanced(COMPOUND_HYPHEN, 480, 260, max_lines=2, font_family="Anton", weight=400)
    assert a == b


@pytest.mark.parametrize(
    "kwargs",
    [
        {"box_w": 0, "box_h": 100},
        {"box_w": 100, "box_h": -5},
        {"box_w": 100, "box_h": 100, "min_px": 0},
        {"box_w": 100, "box_h": 100, "min_px": 50, "max_px": 20},
    ],
)
def test_invalid_geometry_raises(kwargs):
    with pytest.raises(ValueError):
        af.fit_balanced("x", **kwargs)


def test_fit_balanced_px_matches_fit_balanced_size():
    size, _ = af.fit_balanced(COMPOUND_HYPHEN, 480, 260, font_family="Anton")
    assert af.fit_balanced_px(COMPOUND_HYPHEN, 480, 260, font_family="Anton") == size


# --------------------------------------------------------------------------- #
# Renderer wiring — the v2 hero slots
# --------------------------------------------------------------------------- #
def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _eval():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief(*, swimmer, result, archetype):
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": swimmer,
            "event_name": "200m Freestyle",
            "result_time": result,
        },
    }
    brief = gen_brief(
        item, _eval(), _brand(), profile_id="test", meet_name="Manchester Open", variation_seed=0
    )
    brief.layout_template = archetype  # force the archetype under test
    return brief


def _render_html(monkeypatch, brief):
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    with tempfile.TemporaryDirectory() as d:
        R.render_brief(brief, output_dir=d, size=(1080, 1350))
    # A5 (Canva gap analysis) wraps intra-numeric separators in kern cells;
    # strip them so this file's string assertions keep testing LINE layout
    # (the balancer), which is what G1.12 is about — not the kern markup.
    import re as _re

    return _re.sub(r'<span class="mh-sep">([.:])</span>', r"\1", captured["html"])


def _var_px(html, var):
    m = re.search(rf"{re.escape(var)}:(\d+)px", html)
    assert m, f"{var} not found"
    return int(m.group(1))


SURNAME_HEROES = {
    "mega_surname_bleed": "--mh-fit-mega-name-px",
    "minimal_type_poster": "--mh-fit-mega-name-px",
    "split_diagonal_hero": "--mh-fit-surname-px",
}
RESULT_HEROES = ("big_number_dominant", "cornerstone_numeral")


@pytest.mark.parametrize("archetype,var", SURNAME_HEROES.items())
def test_compound_surname_wraps_balanced_on_hero_archetypes(monkeypatch, archetype, var):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = _render_html(
        monkeypatch, _brief(swimmer="Aleksandra Wolajimi-Abubakari", result="2:08.41", archetype=archetype)
    )
    # surname is balanced across two lines, hyphen kept on the upper line…
    assert "WOLAJIMI-<br>ABUBAKARI" in html
    # …and the two halves rejoin to the original surname (nothing dropped).
    surname_block = re.search(r"WOLAJIMI-<br>ABUBAKARI", html).group(0)
    assert surname_block.replace("<br>", "") == "WOLAJIMI-ABUBAKARI"
    assert "{{" not in html and "}}" not in html


@pytest.mark.parametrize("archetype,var", SURNAME_HEROES.items())
def test_simple_surname_is_single_line_on_hero_archetypes(monkeypatch, archetype, var):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    short = _render_html(monkeypatch, _brief(swimmer="Mia Cox", result="2:08.41", archetype=archetype))
    long = _render_html(
        monkeypatch,
        _brief(swimmer="Aleksandra Wolajimi-Abubakari", result="2:08.41", archetype=archetype),
    )
    # a short surname is NOT split, keeps the layout's full cap, and is larger
    # than the wrapped long surname (which had to come down to gain a 2nd line)
    assert "COX<br>" not in short and ">COX<" in short
    assert _var_px(long, var) < _var_px(short, var)


@pytest.mark.parametrize("archetype", RESULT_HEROES)
def test_split_result_stacks_on_result_hero_archetypes(monkeypatch, archetype):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    split = _render_html(monkeypatch, _brief(swimmer="Mia Cox", result=SPLIT_RESULT, archetype=archetype))
    normal = _render_html(monkeypatch, _brief(swimmer="Mia Cox", result="2:08.41", archetype=archetype))
    # the split stacks cleanly (no dangling slash) and is sized FAR bigger than
    # the same string crammed onto one line would be
    assert "1:45.23<br>50.12" in split
    assert "2:08.41<br>" not in normal  # an ordinary time is left on one line
    one_line = af.fit_balanced_px(
        SPLIT_RESULT, 1080 * 0.92, 1350 * 0.34, max_lines=1,
        font_family="JetBrains Mono", weight=700, min_px=72, max_px=300, mode="split",
    )
    assert _var_px(split, "--mh-fit-mega-result-px") > one_line


def test_non_hero_archetype_keeps_surname_and_result_single_line(monkeypatch):
    # The multi-line behaviour is opt-in per hero archetype; a compact archetype
    # like index_card must be byte-identical (no injected <br>) so its tight
    # fixed-size slots don't overflow vertically.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = _render_html(
        monkeypatch,
        _brief(swimmer="Aleksandra Wolajimi-Abubakari", result=SPLIT_RESULT, archetype="index_card"),
    )
    assert "WOLAJIMI-ABUBAKARI" in html  # the full surname, on one line
    assert "WOLAJIMI-<br>" not in html
    assert "1:45.23 / 50.12" in html  # the result string, untouched
    assert "1:45.23<br>" not in html


def test_split_result_on_a_surname_hero_is_left_single_line(monkeypatch):
    # split_diagonal_hero is a SURNAME hero, not a result hero — its small result
    # slot must not start stacking splits.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = _render_html(
        monkeypatch, _brief(swimmer="Mia Cox", result=SPLIT_RESULT, archetype="split_diagonal_hero")
    )
    assert "1:45.23 / 50.12" in html
    assert "1:45.23<br>50.12" not in html


def test_wrapped_surname_genuinely_fits_its_box(monkeypatch):
    # End-to-end: the fitted size the renderer injected must let BOTH balanced
    # lines fit the hero box width (no overflow), measured by the same maths.
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    html = _render_html(
        monkeypatch,
        _brief(swimmer="Aleksandra Wolajimi-Abubakari", result="2:08.41", archetype="mega_surname_bleed"),
    )
    px = _var_px(html, "--mh-fit-mega-name-px")
    for line in ("WOLAJIMI-", "ABUBAKARI"):
        w = af.measure_line_px(line, px, font_family="Anton", weight=400)
        assert w <= 1080 * 0.92 + 1, f"{line} overflows at {px}px"
