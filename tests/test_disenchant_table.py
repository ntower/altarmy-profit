"""Sanity checks on the shipped data/forever/disenchant.csv lookup table."""

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from altarmy_profit.engine import (
    DISENCHANTABLE_CLASSES,
    DISENCHANTABLE_QUALITIES,
    DisenchantRow,
    Item,
    Market,
)

TABLE = Path(__file__).resolve().parents[1] / "data" / "forever" / "disenchant.csv"

# Classic-era enchanting materials (dusts, essences, shards, Nexus Crystal).
KNOWN_MATS = {
    10938, 10939, 10940, 10978, 10998, 11082, 11083, 11084, 11134, 11135, 11137, 11138, 11139,
    11174, 11175, 11176, 11177, 11178, 14343, 14344, 16202, 16203, 16204, 20725,
}  # fmt: skip


def load_table() -> list[DisenchantRow]:
    with open(TABLE, newline="", encoding="utf-8") as f:
        return [
            DisenchantRow(
                int(r["item_class"]),
                int(r["quality"]),
                int(r["min_ilvl"]),
                int(r["max_ilvl"]),
                int(r["result_item_id"]),
                float(r["chance"]),
                int(r["min_count"]),
                int(r["max_count"]),
            )
            for r in csv.DictReader(f)
        ]


def test_rows_are_well_formed() -> None:
    rows = load_table()
    assert rows
    for d in rows:
        assert d.item_class in DISENCHANTABLE_CLASSES
        assert d.quality in DISENCHANTABLE_QUALITIES
        assert 0 < d.min_ilvl <= d.max_ilvl
        assert 0 < d.chance <= 1
        assert 1 <= d.min_count <= d.max_count
        assert d.result_item_id in KNOWN_MATS


def test_each_bracket_sums_to_one_and_brackets_do_not_overlap() -> None:
    brackets: dict[tuple[int, int], dict[tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))
    for d in load_table():
        brackets[(d.item_class, d.quality)][(d.min_ilvl, d.max_ilvl)] += d.chance
    for key, ranges in brackets.items():
        for rng, total in ranges.items():
            assert total == pytest.approx(1.0, abs=0.001), (key, rng)
        ordered = sorted(ranges)
        for (_, prev_hi), (lo, _) in zip(ordered, ordered[1:], strict=False):
            assert lo > prev_hi, (key, ordered)


def test_green_armor_expected_value() -> None:
    # ilvl 20 green armor: 75% 2-3 Strange Dust, 20% 1-2 Greater Magic Essence, 5% 1 Small Glimmering Shard.
    robe = Item(id=1, name="Green Robe", quality=2, item_level=20, class_id=4)
    market = Market({1: robe}, [], {10940: 100, 10939: 1000, 10978: 2000}, load_table(), ah_cut=0.0)
    assert market.disenchant_value(robe) == int(0.75 * 2.5 * 100 + 0.20 * 1.5 * 1000 + 0.05 * 2000)
