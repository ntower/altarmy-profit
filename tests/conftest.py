"""Shared fixtures: a tiny fake DB2 CSV set shaped like the wago.tools exports."""

import csv
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from wowprofit import db


def write_csv(path: Path, header: list[str], rows: list[dict[str, object]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, restval=0)
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def db2_paths(tmp_path: Path) -> dict[str, Path]:
    """Items: 1 Linen Cloth, 2 Coarse Thread, 3 Green Robe. One Tailoring recipe (10 linen + 1 thread)."""
    reagent_cols = [f"Reagent_{i}" for i in range(8)] + [f"ReagentCount_{i}" for i in range(8)]
    return {
        "Item": write_csv(
            tmp_path / "Item.csv",
            ["ID", "ClassID", "SubclassID"],
            [{"ID": 1, "ClassID": 7}, {"ID": 2, "ClassID": 7}, {"ID": 3, "ClassID": 4, "SubclassID": 1}],
        ),
        "ItemSparse": write_csv(
            tmp_path / "ItemSparse.csv",
            [
                "ID",
                "Display_lang",
                "OverallQualityID",
                "ItemLevel",
                "RequiredLevel",
                "SellPrice",
                "BuyPrice",
                "Bonding",
            ],
            [
                {"ID": 1, "Display_lang": "Linen Cloth", "OverallQualityID": 1, "SellPrice": 13},
                {"ID": 2, "Display_lang": "Coarse Thread", "OverallQualityID": 1, "SellPrice": 10},
                {
                    "ID": 3,
                    "Display_lang": "Green Robe",
                    "OverallQualityID": 2,
                    "ItemLevel": 20,
                    "SellPrice": 500,
                },
            ],
        ),
        "SkillLine": write_csv(
            tmp_path / "SkillLine.csv",
            ["ID", "DisplayName_lang"],
            [{"ID": 197, "DisplayName_lang": "Tailoring"}],
        ),
        "SkillLineAbility": write_csv(
            tmp_path / "SkillLineAbility.csv",
            [
                "ID",
                "SkillLine",
                "Spell",
                "MinSkillLineRank",
                "TrivialSkillLineRankLow",
                "TrivialSkillLineRankHigh",
            ],
            [
                {"ID": 100, "SkillLine": 197, "Spell": 900, "MinSkillLineRank": 25},
                # no reagents/effect -> must be skipped
                {"ID": 101, "SkillLine": 197, "Spell": 901},
                # not a known skill line -> must be skipped
                {"ID": 102, "SkillLine": 999, "Spell": 900},
            ],
        ),
        "SpellName": write_csv(
            tmp_path / "SpellName.csv", ["ID", "Name_lang"], [{"ID": 900, "Name_lang": "Green Robe"}]
        ),
        "SpellEffect": write_csv(
            tmp_path / "SpellEffect.csv",
            ["ID", "Effect", "EffectItemType", "EffectBasePointsF", "SpellID"],
            [
                {"ID": 1, "Effect": 24, "EffectItemType": 3, "EffectBasePointsF": 1.0, "SpellID": 900},
                {"ID": 2, "Effect": 6, "EffectItemType": 0, "EffectBasePointsF": 0, "SpellID": 901},
            ],
        ),
        "SpellReagents": write_csv(
            tmp_path / "SpellReagents.csv",
            ["ID", "SpellID", *reagent_cols],
            [
                {
                    "ID": 1,
                    "SpellID": 900,
                    "Reagent_0": 1,
                    "Reagent_1": 2,
                    "ReagentCount_0": 10,
                    "ReagentCount_1": 1,
                }
            ],
        ),
    }


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    c = db.connect(tmp_path / "test.db")
    db.init_schema(c)
    yield c
    c.close()
