"""Download wago.tools DB2 CSVs and load items/recipes into SQLite."""

from __future__ import annotations

import csv
import json
import sqlite3
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from . import db

DEFAULT_BUILD = "1.60.1.69913"
PRODUCT = "wow_classic_beta"  # WoW: Forever builds on wago.tools
LATEST_URL = "https://wago.tools/api/builds/latest"
TABLES = ["Item", "ItemSparse", "SkillLine", "SkillLineAbility", "SpellName", "SpellEffect", "SpellReagents"]
EFFECT_CREATE_ITEM = 24
MAX_REAGENTS = 8


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "wowprofit/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data: bytes = resp.read()
    return data


def parse_latest_build(payload: bytes, product: str = PRODUCT) -> str:
    """Pick `product`'s version out of wago.tools' /api/builds/latest JSON."""
    builds = json.loads(payload)
    if product not in builds:
        raise ValueError(f"no {product} build in wago.tools' latest builds")
    return str(builds[product]["version"])


def latest_build(product: str = PRODUCT) -> str:
    return parse_latest_build(_fetch(LATEST_URL), product)


def download(table: str, build: str, cache_dir: Path) -> Path:
    dest = cache_dir / build / f"{table}.csv"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_fetch(f"https://wago.tools/db2/{table}/csv?build={build}"))
    return dest


def download_all(build: str, cache_dir: Path) -> dict[str, Path]:
    return {t: download(t, build, cache_dir) for t in TABLES}


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(float(v)) if v not in (None, "") else default
    except ValueError:
        return default


def build_db(
    paths: dict[str, Path], conn: sqlite3.Connection, disenchant_csv: Path | None = None
) -> dict[str, int]:
    """Rebuild items/recipes/recipe_reagents/disenchant (prices are preserved)."""
    db.init_schema(conn)
    for t in ("items", "recipes", "recipe_reagents", "disenchant"):
        conn.execute(f"DELETE FROM {t}")

    classes = {_int(r["ID"]): (_int(r["ClassID"]), _int(r["SubclassID"])) for r in _rows(paths["Item"])}
    items = []
    for r in _rows(paths["ItemSparse"]):
        iid = _int(r["ID"])
        cls, sub = classes.get(iid, (0, 0))
        items.append(
            (
                iid,
                r["Display_lang"],
                _int(r["OverallQualityID"]),
                _int(r["ItemLevel"]),
                _int(r["RequiredLevel"]),
                cls,
                sub,
                _int(r["SellPrice"]),
                _int(r["BuyPrice"]),
                _int(r["Bonding"]),
            )
        )
    conn.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?)", items)

    skill_names = {_int(r["ID"]): r["DisplayName_lang"] for r in _rows(paths["SkillLine"])}
    spell_names = {_int(r["ID"]): r["Name_lang"] for r in _rows(paths["SpellName"])}

    # spell -> (output item, count); first CreateItem effect wins
    outputs: dict[int, tuple[int, int]] = {}
    for r in _rows(paths["SpellEffect"]):
        if _int(r["Effect"]) == EFFECT_CREATE_ITEM and _int(r["EffectItemType"]) > 0:
            spell = _int(r["SpellID"])
            if spell not in outputs:
                outputs[spell] = (
                    _int(r["EffectItemType"]),
                    max(1, round(float(r["EffectBasePointsF"] or 0))),
                )

    reagents: dict[int, list[tuple[int, int]]] = {}
    for r in _rows(paths["SpellReagents"]):
        lst = [(_int(r[f"Reagent_{i}"]), _int(r[f"ReagentCount_{i}"])) for i in range(MAX_REAGENTS)]
        lst = [(i, c) for i, c in lst if i > 0 and c > 0]
        if lst:
            reagents[_int(r["SpellID"])] = lst

    known_items = {i[0] for i in items}
    n_recipes = 0
    for r in _rows(paths["SkillLineAbility"]):
        spell = _int(r["Spell"])
        line = _int(r["SkillLine"])
        if spell not in outputs or spell not in reagents or line not in skill_names:
            continue
        out_item, out_count = outputs[spell]
        if out_item not in known_items:
            continue
        rid = _int(r["ID"])
        conn.execute(
            "INSERT OR REPLACE INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                rid,
                spell,
                spell_names.get(spell, f"Spell {spell}"),
                line,
                skill_names[line],
                _int(r["MinSkillLineRank"]),
                _int(r["TrivialSkillLineRankLow"]),
                _int(r["TrivialSkillLineRankHigh"]),
                out_item,
                out_count,
            ),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO recipe_reagents VALUES (?,?,?)", [(rid, i, c) for i, c in reagents[spell]]
        )
        n_recipes += 1

    n_de = 0
    if disenchant_csv and disenchant_csv.exists():
        for r in _rows(disenchant_csv):
            conn.execute(
                "INSERT INTO disenchant VALUES (?,?,?,?,?,?,?,?)",
                (
                    _int(r["item_class"]),
                    _int(r["quality"]),
                    _int(r["min_ilvl"]),
                    _int(r["max_ilvl"]),
                    _int(r["result_item_id"]),
                    float(r["chance"]),
                    _int(r["min_count"]),
                    _int(r["max_count"]),
                ),
            )
            n_de += 1

    conn.commit()
    return {"items": len(items), "recipes": n_recipes, "disenchant_rows": n_de}


def update(
    conn: sqlite3.Connection, build: str, cache_dir: Path, disenchant_csv: Path | None = None
) -> dict[str, int]:
    """Download `build` (cached per build) and rebuild the database from it, keeping prices."""
    stats = build_db(download_all(build, cache_dir), conn, disenchant_csv)
    db.set_meta(conn, "build", build)
    return stats
