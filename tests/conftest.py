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
    """Items: 1 Linen Cloth, 2 Coarse Thread, 3 Green Robe. One Tailoring recipe (10 linen + 1 thread).

    The robe carries tooltip data: a chest (robe) slot, Cloth subclass, BoE, level/skill requirements,
    flavor text and an icon.
    """
    reagent_cols = [f"Reagent_{i}" for i in range(8)] + [f"ReagentCount_{i}" for i in range(8)]
    return {
        "Item": write_csv(
            tmp_path / "Item.csv",
            ["ID", "ClassID", "SubclassID", "IconFileDataID"],
            [
                {"ID": 1, "ClassID": 7, "IconFileDataID": 501},
                {"ID": 2, "ClassID": 7, "IconFileDataID": 999},  # not in the manifest -> no icon
                {"ID": 3, "ClassID": 4, "SubclassID": 1, "IconFileDataID": 500},
            ],
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
                "InventoryType",
                "ItemDelay",
                "ContainerSlots",
                "RequiredSkill",
                "RequiredSkillRank",
                "Description_lang",
            ],
            [
                {
                    "ID": 1,
                    "Display_lang": "Linen Cloth",
                    "OverallQualityID": 1,
                    "SellPrice": 13,
                    "Description_lang": "",
                },
                {
                    "ID": 2,
                    "Display_lang": "Coarse Thread",
                    "OverallQualityID": 1,
                    "SellPrice": 10,
                    "Description_lang": "",
                },
                {
                    "ID": 3,
                    "Display_lang": "Green Robe",
                    "OverallQualityID": 2,
                    "ItemLevel": 20,
                    "RequiredLevel": 12,
                    "SellPrice": 500,
                    "Bonding": 2,
                    "InventoryType": 20,
                    "RequiredSkill": 197,
                    "RequiredSkillRank": 50,
                    "Description_lang": "Soft and green.",
                },
            ],
        ),
        "ItemSubClass": write_csv(
            tmp_path / "ItemSubClass.csv",
            ["DisplayName_lang", "ID", "ClassID", "SubClassID"],
            [
                {"DisplayName_lang": "Miscellaneous", "ID": 19, "ClassID": 4, "SubClassID": 0},
                {"DisplayName_lang": "Cloth", "ID": 20, "ClassID": 4, "SubClassID": 1},
            ],
        ),
        "ManifestInterfaceData": write_csv(
            tmp_path / "ManifestInterfaceData.csv",
            ["ID", "FilePath", "FileName"],
            [
                {"ID": 500, "FilePath": "Interface\\ICONS\\", "FileName": "INV_Chest_Cloth_39.blp"},
                {"ID": 501, "FilePath": "Interface\\ICONS\\", "FileName": "INV_Fabric_Linen_01.blp"},
                {"ID": 502, "FilePath": "Interface\\AbilitiesFrame\\", "FileName": "UI-Panel.blp"},
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
