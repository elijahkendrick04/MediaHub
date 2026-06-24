"""bulk per-language fan-out (1.24) — one item per (card × language)."""

from __future__ import annotations

import json
from pathlib import Path

from mediahub.bulk.generate import GenContext, GenOutput, bulk_generate, plan_bulk
from mediahub.bulk.models import BulkItem


def _seed_run(runs_dir: Path, run_id="run-1", profile_id="club-x", n=2) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    ranked = [
        {
            "rank": i,
            "achievement": {
                "swim_id": f"s{i}",
                "swimmer_name": f"Swimmer {i}",
                "event": "100m Freestyle",
                "headline": "NEW PB",
                "time": "1:01.0",
            },
        }
        for i in range(1, n + 1)
    ]
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Champs"},
        "recognition_report": {"ranked_achievements": ranked},
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")


class TestPlanFanOut:
    def test_no_languages_is_one_item_per_card(self, tmp_path):
        _seed_run(tmp_path, n=3)
        job = plan_bulk("club-x", "run-1", "certificate", runs_dir=tmp_path)
        assert len(job.items) == 3
        assert all(i.language == "" for i in job.items)

    def test_languages_fan_out_per_card(self, tmp_path):
        _seed_run(tmp_path, n=2)
        job = plan_bulk("club-x", "run-1", "certificate", runs_dir=tmp_path, languages=["cy", "fr"])
        assert len(job.items) == 4
        langs = [i.language for i in job.items]
        assert langs == ["cy", "fr", "cy", "fr"]  # per card, in language order
        # the label notes the language
        assert any("· cy" in i.label for i in job.items)

    def test_case_and_region_variants_collapse_to_one_base(self, tmp_path):
        _seed_run(tmp_path, n=1)
        job = plan_bulk(
            "club-x",
            "run-1",
            "certificate",
            runs_dir=tmp_path,
            languages=["CY", "cy", "cy-GB", "fr"],
        )
        # CY/cy/cy-GB are one language ("cy"); fr is separate → 2 items, not 4.
        assert [i.language for i in job.items] == ["cy", "fr"]

    def test_english_any_region_collapses_to_default(self, tmp_path):
        _seed_run(tmp_path, n=1)
        job = plan_bulk(
            "club-x", "run-1", "certificate", runs_dir=tmp_path, languages=["EN", "en-US"]
        )
        # English (the source) is the default no-op item, never an en→en translation.
        assert [i.language for i in job.items] == [""]

    def test_blank_and_duplicate_languages_collapse(self, tmp_path):
        _seed_run(tmp_path, n=1)
        job = plan_bulk(
            "club-x", "run-1", "certificate", runs_dir=tmp_path, languages=["cy", "cy", "", "fr"]
        )
        # "cy", "" and "fr" survive (dup cy collapsed), in order.
        assert [i.language for i in job.items] == ["cy", "", "fr"]

    def test_cap_bounds_total_items_not_cards(self, tmp_path):
        _seed_run(tmp_path, n=5)
        job = plan_bulk(
            "club-x", "run-1", "certificate", runs_dir=tmp_path, languages=["cy", "fr"], cap=3
        )
        # 5 cards × 2 langs = 10 planned, capped to 3 total.
        assert len(job.items) == 3


class TestRunThreadsLanguage:
    def test_generator_receives_each_items_language(self, tmp_path):
        _seed_run(tmp_path, n=2)
        seen: list[str] = []

        def fake_gen(ctx: GenContext) -> GenOutput:
            seen.append(ctx.language)
            return GenOutput(True, path=str(ctx.out_dir / f"art-{ctx.card_id}-{ctx.language}.txt"))

        job = bulk_generate(
            "club-x",
            "run-1",
            "certificate",
            runs_dir=tmp_path,
            languages=["cy", "fr"],
            generator=fake_gen,
            save=False,
        )
        assert sorted(seen) == ["cy", "cy", "fr", "fr"]
        # distinct artifact path per (card, language) — no overwrite collision.
        paths = {i.output_path for i in job.items if i.output_path}
        assert len(paths) == 4


class TestItemSerialisation:
    def test_language_round_trips(self):
        item = BulkItem(item_id="x", card_id="s1", language="cy")
        assert item.to_dict()["language"] == "cy"
        assert BulkItem.from_dict(item.to_dict()).language == "cy"

    def test_back_compat_item_without_language(self):
        old = {"item_id": "x", "card_id": "s1", "label": "L", "status": "queued"}
        assert BulkItem.from_dict(old).language == ""
