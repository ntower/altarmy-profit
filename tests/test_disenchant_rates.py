"""Parsing Auctionator's disenchant bracket table."""

import pytest

from altarmy_profit import disenchant_rates
from altarmy_profit.engine import DisenchantRow, Item, Market

# Trimmed from Auctionator's Source_Classic/Enchant/DisenchantingProbabilities.lua: same layout, comments
# included (commented rows use another format and must be skipped).
TABLE = """
Auctionator.Constants.DisenchantingProbability = {
  [ Enum.ItemClass.Armor ] = {
    [ Enum.ItemQuality.Good ] = {
      -- { 5, 15, 80, { 1, 2 }, MATS.STRANGE_DUST, 20, { 1, 2 }, MATS.LESSER_MAGIC },
      {5,15,40,1,10940,40,2,10940,10,1,10938,10,2,10938},
      {66,80,25,1,22445,25,2,22445,25,3,22445,7.3333333333333,1,22447,7.3333333333333,2,22447,7.3333333333333,3,22447,3,1,22448},
      {381,390,85,2.5,74249,15,1,74250},
    },
    [ Enum.ItemQuality.Epic ] = {
      {105,164,33.3,1,22450,66.6,2,22450},
      {165,280,100,1,34057},
    }
  },
  [ Enum.ItemClass.Weapon ] = {
    [ Enum.ItemQuality.Rare ] = {
      {100,120,99.5,1,22449,0.5,1,22450},
      {285,285,28,1,52555,0,4,52555},
    },
  }
}
"""


def test_parse_tags_rows_with_their_section() -> None:
    rows = list(disenchant_rates.parse(TABLE))
    assert [(r.item_class, r.quality, r.min_ilvl, r.max_ilvl) for r in rows] == [
        (4, 2, 5, 15),
        (4, 2, 66, 80),
        (4, 2, 381, 390),
        (4, 4, 105, 164),
        (4, 4, 165, 280),
        (2, 3, 100, 120),
        (2, 3, 285, 285),
    ]
    assert rows[0].outcomes == ((40, 1, 10940), (40, 2, 10940), (10, 1, 10938), (10, 2, 10938))


def test_to_rows_keeps_tbc_brackets_one_row_per_count() -> None:
    rows = disenchant_rates.to_rows(list(disenchant_rates.parse(TABLE)), disenchant_rates.TBC_MAX_ILVL)
    assert {(r.min_ilvl, r.max_ilvl) for r in rows} == {(5, 15), (66, 80), (105, 164), (100, 120)}
    assert DisenchantRow(4, 2, 66, 80, 22445, 0.25, 3, 3) in rows
    assert DisenchantRow(4, 4, 105, 164, 22450, 0.666, 2, 2) in rows
    assert sum(r.chance for r in rows if r.min_ilvl == 66) == pytest.approx(1.0, abs=1e-5)


def test_rows_value_like_the_bracket_they_came_from() -> None:
    """Split per count, the 5-15 bracket expects 1.2 Strange Dust and 0.3 Lesser Magic Essence."""
    rows = disenchant_rates.to_rows(list(disenchant_rates.parse(TABLE)), disenchant_rates.TBC_MAX_ILVL)
    robe = Item(1, "Robe", quality=2, item_level=10, class_id=4)
    market = Market({1: robe}, [], {10940: 100, 10938: 1000}, rows, ah_cut=0.0)
    assert market.disenchant_value(robe) == 120 + 300


def test_to_rows_rejects_fractional_counts_it_keeps() -> None:
    with pytest.raises(ValueError, match="fractional count 2.5"):
        disenchant_rates.to_rows(list(disenchant_rates.parse(TABLE)), 400)
