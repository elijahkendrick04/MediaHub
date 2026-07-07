"""R1.13 — Custom reel stat chips.

The meet reel's cover stat chips became *configurable* and grew an honest stat
vocabulary beyond the original swims / PBs / medals: club & meet records, season
bests, relay wins, finals, and top splits. Every chip is still counted ONLY from
the real card facts the recognition layer produced (``achievementLabel``,
``eventName``, ``heroStat``) — never from a bare ``place`` number, never invented
— so the cover can never claim a result the meet did not contain.

Two layers of cover:

* **Source contracts** (always run) pin the configurable seam, the honest
  vocabulary, the byte-identical default, and the no-place-guessing rule the
  parity suite also guards.
* **Behavioural** tests transpile the real ``reelStats`` out of ``MeetReel.tsx``
  with the bundled TypeScript compiler and execute it on crafted card sets, so
  the honest counting, the config selection/cap/wording-override, and the
  count-up prefix/suffix are checked for real (skipped where Node or the
  TypeScript dep is absent).
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap

import pytest

from mediahub.visual import motion


def _reel_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()


# --------------------------------------------------------------------------- #
# Source contracts — the configurable seam + honest vocabulary (always run)
# --------------------------------------------------------------------------- #


def test_meet_reel_owns_the_stat_region():
    """R1.13's sole-owner surface lives in MeetReel.tsx, reusing the shared
    card schema (the data the chips read flows in on the card facts)."""
    src = _reel_src()
    assert "export function reelStats" in src
    assert "const StatChips" in src
    assert 'from "./StoryCard"' in src and "cardSchema" in src


def test_configurable_seam_is_declared():
    src = _reel_src()
    # An optional reel-stat config prop on the reel schema (omitted = default).
    assert "reelStatConfig" in src
    assert "reelStatConfigSchema" in src
    # The three configurable levers: which ids, how many, and the wording.
    for field in ("include:", "max:", "labels:"):
        assert field in src, field
    # A typed config the function accepts.
    assert "ReelStatConfig" in src
    assert "reelStats(safeCards, reelStatConfig)" in src


def test_default_set_is_the_legacy_three():
    """No config → byte-identical default cover: TOP-N SWIMS / PBS / MEDALS."""
    src = _reel_src()
    m = re.search(r"DEFAULT_STAT_IDS\s*=\s*\[([^\]]*)\]", src)
    assert m, "DEFAULT_STAT_IDS must be declared"
    ids = [s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip()]
    assert ids == ["swims", "pbs", "medals"]
    assert re.search(r"DEFAULT_MAX_CHIPS\s*=\s*3\b", src)


def test_honest_vocabulary_present():
    """The new honest stat ids the roadmap calls for are derivable."""
    src = _reel_src()
    fn = src.split("export function reelStats", 1)[1].split("\n}", 1)[0]
    for stat_id in ("records", "seasonBests", "relayWins", "finals", "topSplits"):
        assert stat_id in fn, stat_id
    # …and counted from real facts, not place numbers.
    assert "achievementLabel" in fn
    assert "eventName" in fn
    assert ".place" not in fn, "stat chips must never guess from a bare place"
    # relay wins require a relay event AND a won() signal from the label.
    assert "RELAY" in fn
    assert "won(" in fn


def test_statchips_counts_up_over_the_honest_value():
    src = _reel_src()
    # StatChips consumes the derived chip list and counts each value up.
    assert "chips: ReelStat[]" in src
    assert "Math.round(chip.value * p)" in src
    # Pluralisation is decided on the FINAL count (n), baked in before count-up.
    assert "n === 1" in src


# --------------------------------------------------------------------------- #
# Behavioural — transpile the real reelStats and run it (Node-gated)
# --------------------------------------------------------------------------- #

# Evaluates the genuine reelStats out of MeetReel.tsx: pulls the two config
# defaults + the function body (the same "\n}" boundary the parity suite uses),
# transpiles the self-contained snippet with the bundled tsc, and runs it.
_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const nodePath = require("path");
const tsxPath = process.argv[2];
const remotionDir = nodePath.resolve(nodePath.dirname(tsxPath), "..", "..");
const ts = require(nodePath.join(remotionDir, "node_modules", "typescript"));

const src = fs.readFileSync(tsxPath, "utf8");
const ids = src.match(/const DEFAULT_STAT_IDS = \[[^\]]*\];/)[0];
const max = src.match(/const DEFAULT_MAX_CHIPS = \d+;/)[0];
const after = src.split("export function reelStats")[1];
const fnBody = after.split("\n}")[0]; // up to the function's own terminal brace
const snippet =
  ids + "\n" + max + "\n" +
  "function reelStats" + fnBody + "\n}\n" +
  "module.exports = { reelStats };";

const js = ts.transpileModule(snippet, {
  compilerOptions: { module: "commonjs", target: "ES2019" },
}).outputText;

const ctx = { module: { exports: {} }, console };
ctx.exports = ctx.module.exports;
vm.runInNewContext(js, ctx);
const reelStats = ctx.module.exports.reelStats;

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (input += d));
process.stdin.on("end", () => {
  const cases = JSON.parse(input);
  const out = cases.map((c) => reelStats(c.cards || [], c.config));
  process.stdout.write(JSON.stringify(out));
});
"""


def _node_ready() -> bool:
    return (
        motion.node_available()
        and (motion.REMOTION_DIR / "node_modules" / "typescript").exists()
    )


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    if not _node_ready():
        pytest.skip("node + remotion typescript dep required for reelStats eval")
    path = tmp_path_factory.mktemp("reelstats") / "harness.cjs"
    path.write_text(textwrap.dedent(_HARNESS))
    return path


def _run(harness, cases: list[dict]) -> list[list[dict]]:
    tsx = motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx"
    proc = subprocess.run(
        ["node", str(harness), str(tsx)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, f"harness failed: {proc.stderr}"
    return json.loads(proc.stdout)


def _labels(chips: list[dict]) -> list[str]:
    """Full static chip label = prefix + final value + suffix."""
    return [f"{c['prefix']}{c['value']}{c['suffix']}" for c in chips]


def _card(label: str = "", event: str = "", hero: str = "", place: str = "") -> dict:
    return {
        "achievementLabel": label,
        "eventName": event,
        "heroStat": hero,
        "place": place,
    }


def test_default_is_byte_identical_three(harness):
    """The legacy default cover, unchanged: TOP-N SWIMS / PBS / MEDALS."""
    cards = [
        _card("NEW PB", "100 Free"),
        _card("SEASON BEST PB", "200 Free"),
        _card("GOLD MEDAL", "50 Fly"),
    ]
    [chips] = _run(harness, [{"cards": cards}])
    assert _labels(chips) == ["TOP 3 SWIMS", "2 PBS", "1 MEDAL"]
    # ids are stable for the renderer's keys.
    assert [c["id"] for c in chips] == ["swims", "pbs", "medals"]


def test_empty_cards_yield_no_chips(harness):
    [chips] = _run(harness, [{"cards": []}])
    assert chips == []


def test_singular_pluralisation_on_final_count(harness):
    [chips] = _run(harness, [{"cards": [_card("NEW PB", "100 Free")]}])
    # one swim, one PB → singular nouns, no medal chip (zero never shown).
    assert _labels(chips) == ["TOP 1 SWIM", "1 PB"]


def test_zero_value_chips_are_never_emitted(harness):
    """A reel with no medals must not show '0 MEDALS' even if asked for it."""
    cards = [_card("NEW PB", "100 Free")]
    [chips] = _run(harness, [{"cards": cards, "config": {"include": ["medals", "pbs"]}}])
    assert _labels(chips) == ["1 PB"]  # medals dropped (count 0)


def test_relay_wins_counted_from_label_not_place(harness):
    """Relay wins need a RELAY event AND a won() label — never a bare place."""
    cards = [
        _card("RELAY GOLD", "4x100 Free Relay"),       # win ✓
        _card("1ST", "4x50 Medley Relay"),             # win ✓ (1ST)
        _card("CHAMPIONS", "4x200 Free Relay"),        # win ✓ (champion)
        _card("SILVER", "4x100 Free Relay"),           # relay but not a win ✗
        _card("GOLD MEDAL", "100 Free"),               # win but NOT a relay ✗
        _card("STRONG SWIM", "4x100 Relay", place="1"),  # relay, place 1, but
        # the label is not a win → must NOT count (no place guessing)
    ]
    [chips] = _run(harness, [{"cards": cards, "config": {"include": ["relayWins"]}}])
    assert _labels(chips) == ["3 RELAY WINS"]


def test_relay_win_signal_vocabulary(harness):
    """Win signals are precise: WIN/WINS/WON/WINNER(S)/CHAMPIONS all count, but
    'CHAMPIONSHIP' (a meet name, not a result) must not be mistaken for a win."""
    cards = [
        _card("RELAY WIN", "4x100 Relay"),         # win ✓
        _card("WINS", "4x50 Relay"),               # win ✓
        _card("WON THE FINAL", "4x200 Relay"),     # win ✓
        _card("RELAY CHAMPIONS", "4x100 Relay"),   # win ✓
        _card("CHAMPIONSHIP RECORD", "4x100 Relay"),  # NOT a win (meet name) ✗
    ]
    [chips] = _run(harness, [{"cards": cards, "config": {"include": ["relayWins"]}}])
    assert _labels(chips) == ["4 RELAY WINS"]


def test_records_season_bests_finals_splits_are_honest(harness):
    cards = [
        _card("CLUB RECORD", "200 IM"),
        _card("MEET RECORD", "100 Back"),
        _card("SEASON BEST", "50 Free"),
        _card("SB", "100 Fly"),                       # word-boundary SB
        _card("A FINAL — 3RD", "200 Free Final"),     # final ✓
        _card("SEMIFINAL", "100 Free Semifinal"),     # NOT a final ✗
        _card("FASTEST SPLIT", "4x100 Relay", hero="23.4 split"),  # split ✓
    ]
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["records", "seasonBests", "finals", "topSplits"], "max": 9}}],
    )
    labels = _labels(chips)
    assert "2 RECORDS" in labels
    assert "2 SEASON BESTS" in labels
    assert "1 FINAL" in labels       # the semifinal is excluded
    assert "1 TOP SPLIT" in labels


def test_config_include_selects_and_orders(harness):
    cards = [
        _card("NEW PB", "100 Free"),
        _card("CLUB RECORD", "200 IM"),
        _card("RELAY GOLD", "4x100 Relay"),
    ]
    # An explicit order the default would never produce.
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["records", "relayWins", "swims"]}}],
    )
    assert [c["id"] for c in chips] == ["records", "relayWins", "swims"]
    assert _labels(chips) == ["1 RECORD", "1 RELAY WIN", "TOP 3 SWIMS"]


def test_config_max_caps_chip_count(harness):
    cards = [_card("NEW PB GOLD MEDAL CLUB RECORD", "100 Free")]
    # Many honest stats present, but max=2 keeps only the first two in order.
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["swims", "pbs", "medals", "records"], "max": 2}}],
    )
    assert [c["id"] for c in chips] == ["swims", "pbs"]


def test_max_zero_hides_all_chips(harness):
    cards = [_card("NEW PB", "100 Free"), _card("GOLD MEDAL", "50 Fly")]
    [chips] = _run(harness, [{"cards": cards, "config": {"max": 0}}])
    assert chips == []


def test_unknown_ids_are_ignored(harness):
    cards = [_card("NEW PB", "100 Free")]
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["not_a_stat", "pbs"]}}],
    )
    assert _labels(chips) == ["1 PB"]


def test_label_override_keeps_count_up_with_placeholder(harness):
    cards = [_card("NEW PB", "100 Free"), _card("NEW PB", "200 Free")]
    # {n} placeholder → number stays, words change.
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["pbs"], "labels": {"pbs": "{n} LIFETIME BESTS"}}}],
    )
    chip = chips[0]
    assert chip["value"] == 2
    assert f"{chip['prefix']}{chip['value']}{chip['suffix']}" == "2 LIFETIME BESTS"


def test_label_override_without_placeholder_prepends_the_count(harness):
    cards = [_card("GOLD MEDAL", "50 Fly")]
    [chips] = _run(
        harness,
        [{"cards": cards, "config": {"include": ["medals"], "labels": {"medals": "PODIUMS"}}}],
    )
    # No {n} given → the count is prepended so the chip still counts up honestly.
    assert _labels(chips) == ["1 PODIUMS"]
    assert chips[0]["value"] == 1


def test_default_cap_holds_even_with_richer_facts(harness):
    """Reels whose labels already carry records/relays keep the byte-identical
    three-chip default — the richer chips are opt-in, never a surprise change."""
    cards = [
        _card("NEW PB", "100 Free"),
        _card("GOLD MEDAL CLUB RECORD", "50 Fly"),
        _card("RELAY GOLD", "4x100 Relay"),
    ]
    [chips] = _run(harness, [{"cards": cards}])  # no config
    assert [c["id"] for c in chips] == ["swims", "pbs", "medals"]
    assert len(chips) == 3


# --------------------------------------------------------------------------- #
# Producer side — the config actually reaches the Remotion props + cache key
# --------------------------------------------------------------------------- #

BRAND = {
    "profile_id": "chips",
    "display_name": "Chips SC",
    "primary_colour": "#0E2A47",
    "secondary_colour": "#C9A227",
}


def _reel_card(i: int) -> dict:
    return {
        "id": f"swim-chip-{i}",
        "swim_id": f"swim-chip-{i}",
        "achievement": {
            "swim_id": f"swim-chip-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Chip Invitational",
    }


def _render_capture(tmp_path, monkeypatch, **kwargs):
    from pathlib import Path
    from unittest import mock

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured: dict = {}

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["props"] = props
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_meet_reel(
            [_reel_card(1), _reel_card(2)], BRAND, tmp_path / "out" / "reel.mp4", **kwargs
        )
    return captured


def test_normalise_reel_stat_config_validates_and_canonicalises():
    assert motion.normalise_reel_stat_config(None) is None
    assert motion.normalise_reel_stat_config({}) is None
    assert motion.normalise_reel_stat_config({"include": [], "labels": {}}) is None
    cfg = motion.normalise_reel_stat_config(
        {"include": ["records", "relayWins"], "max": 2, "labels": {"records": "{n} NEW RECORDS"}}
    )
    assert cfg == {
        "include": ["records", "relayWins"],
        "max": 2,
        "labels": {"records": "{n} NEW RECORDS"},
    }
    with pytest.raises(ValueError):
        motion.normalise_reel_stat_config({"include": ["podiums"]})  # unknown id
    with pytest.raises(ValueError):
        motion.normalise_reel_stat_config({"labels": {"podiums": "x"}})
    with pytest.raises(ValueError):
        motion.normalise_reel_stat_config({"max": "lots"})
    with pytest.raises(ValueError):
        motion.normalise_reel_stat_config({"max": -1})
    with pytest.raises(ValueError):
        motion.normalise_reel_stat_config("include=records")


def test_vocabulary_matches_the_tsx_counts_table():
    """REEL_STAT_IDS must be the exact keys of reelStats' counts record."""
    src = _reel_src()
    table = src.split("const counts: Record<string, number> = {", 1)[1].split("};", 1)[0]
    tsx_ids = set(re.findall(r"^\s*([A-Za-z]+):", table, re.M))
    assert tsx_ids == set(motion.REEL_STAT_IDS)


def test_stat_config_reaches_props_and_shifts_the_cache_key(tmp_path, monkeypatch):
    cfg = {"include": ["records", "pbs"], "max": 2}
    cap = _render_capture(tmp_path, monkeypatch, reel_stat_config=cfg)
    assert cap["props"]["reelStatConfig"] == {"include": ["records", "pbs"], "max": 2}
    keys_after_first = {p.stem for p in motion._cache_dir().glob("*.mp4")}
    # A different config renders (and caches) separately.
    _render_capture(tmp_path, monkeypatch, reel_stat_config={"max": 1})
    keys_after_second = {p.stem for p in motion._cache_dir().glob("*.mp4")}
    assert len(keys_after_second) == len(keys_after_first) + 1


def test_no_stat_config_keeps_props_and_cache_key_byte_identical(tmp_path, monkeypatch):
    cap = _render_capture(tmp_path, monkeypatch)
    assert "reelStatConfig" not in cap["props"], "an unconfigured reel must not carry the prop"
    keys = {p.stem for p in motion._cache_dir().glob("*.mp4")}
    # An explicit empty config is the same render — same key, cache hit.
    _render_capture(tmp_path, monkeypatch, reel_stat_config={})
    assert {p.stem for p in motion._cache_dir().glob("*.mp4")} == keys
