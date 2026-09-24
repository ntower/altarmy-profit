"""Download wago.tools DB2 CSVs and load one game version's items and recipes into the database."""

from __future__ import annotations

import csv
import json
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Connection, delete

from . import db, schema

LATEST_URL = "https://wago.tools/api/builds/latest"
TABLES = [
    "Item",
    "ItemSparse",
    "ItemSubClass",
    "ManifestInterfaceData",
    "SkillLine",
    "SkillLineAbility",
    "SpellName",
    "SpellEffect",
    "SpellReagents",
]
EFFECT_CREATE_ITEM = 24
MAX_REAGENTS = 8


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "altarmy-profit/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data: bytes = resp.read()
    return data


def parse_latest_build(payload: bytes, product: str) -> str:
    """Pick `product`'s version out of wago.tools' /api/builds/latest JSON."""
    builds = json.loads(payload)
    if product not in builds:
        raise ValueError(f"no {product} build in wago.tools' latest builds")
    return str(builds[product]["version"])


def latest_build(product: str) -> str:
    """The newest build of a wago.tools product (versions.GameVersion.wago_product)."""
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


def _icon_names(path: Path) -> dict[int, str]:
    """Icon FileDataID -> icon name as Wowhead's CDN spells it (lowercase, no .blp)."""
    return {
        _int(r["ID"]): r["FileName"].lower().removesuffix(".blp")
        for r in _rows(path)
        if r["FilePath"].lower().startswith("interface\\icons")
    }


def output_count(effect: dict[str, str]) -> int:
    """Items one cast of a CreateItem SpellEffect row makes (random counts averaged), at least 1.

    Forever's builds carry the count in `EffectBasePointsF`. TBC's leave that 0 and use the older encoding:
    `EffectBasePoints` plus a roll of 1..`EffectDieSides` (Thorium Grenade: 2 + 1 = 3).
    """
    as_float = round(float(effect.get("EffectBasePointsF") or 0))
    if as_float > 0:
        return as_float
    base, sides = _int(effect.get("EffectBasePoints")), _int(effect.get("EffectDieSides"))
    return max(1, base + (1 + sides) // 2 if sides > 0 else base)


ITEM_INSERT_COLUMNS = (
    "game_version",
    "id",
    "name",
    "quality",
    "item_level",
    "required_level",
    "class_id",
    "subclass_id",
    "sell_price",
    "buy_price",
    "bonding",
    "inventory_type",
    "item_delay",
    "container_slots",
    "subclass_name",
    "required_skill",
    "required_skill_rank",
    "description",
    "icon",
    "buy_count",
    "stack_size",
)


GAME_DATA_TABLES = (
    schema.recipe_reagents,
    schema.recipes,
    schema.items,
    schema.disenchant,
    schema.vendor_items,
)


def build_db(
    paths: dict[str, Path],
    conn: Connection,
    game_version: str,
    disenchant_csv: Path | None = None,
    vendor_csv: Path | None = None,
) -> dict[str, int]:
    """Rebuild one version's items/recipes/recipe_reagents/disenchant/vendor_items; prices, characters
    and other versions are left alone."""
    for table in GAME_DATA_TABLES:
        conn.execute(delete(table).where(table.c.game_version == game_version))

    skill_names = {_int(r["ID"]): r["DisplayName_lang"] for r in _rows(paths["SkillLine"])}
    subclass_names = {
        (_int(r["ClassID"]), _int(r["SubClassID"])): r["DisplayName_lang"]
        for r in _rows(paths["ItemSubClass"])
    }
    icons = _icon_names(paths["ManifestInterfaceData"])
    classes = {
        _int(r["ID"]): (_int(r["ClassID"]), _int(r["SubclassID"]), _int(r["IconFileDataID"]))
        for r in _rows(paths["Item"])
    }
    items = []
    for r in _rows(paths["ItemSparse"]):
        iid = _int(r["ID"])
        cls, sub, icon = classes.get(iid, (0, 0, 0))
        items.append(
            (
                game_version,
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
                _int(r["InventoryType"]),
                _int(r["ItemDelay"]),
                _int(r["ContainerSlots"]),
                subclass_names.get((cls, sub)),
                skill_names.get(_int(r["RequiredSkill"])),
                _int(r["RequiredSkillRank"]),
                r["Description_lang"] or None,
                icons.get(icon),
                max(1, _int(r.get("VendorStackCount"), 1)),
                max(1, _int(r.get("Stackable"), 1)),
            )
        )
    conn.execute(schema.items.insert(), [dict(zip(ITEM_INSERT_COLUMNS, i, strict=True)) for i in items])

    spell_names = {_int(r["ID"]): r["Name_lang"] for r in _rows(paths["SpellName"])}

    # spell -> (output item, count); first CreateItem effect wins
    outputs: dict[int, tuple[int, int]] = {}
    for r in _rows(paths["SpellEffect"]):
        if _int(r["Effect"]) == EFFECT_CREATE_ITEM and _int(r["EffectItemType"]) > 0:
            spell = _int(r["SpellID"])
            if spell not in outputs:
                outputs[spell] = (
                    _int(r["EffectItemType"]),
                    output_count(r),
                )

    reagents: dict[int, list[tuple[int, int]]] = {}
    for r in _rows(paths["SpellReagents"]):
        lst = [(_int(r[f"Reagent_{i}"]), _int(r[f"ReagentCount_{i}"])) for i in range(MAX_REAGENTS)]
        lst = [(i, c) for i, c in lst if i > 0 and c > 0]
        if lst:
            reagents[_int(r["SpellID"])] = lst

    known_items = {i[1] for i in items}
    recipes: dict[int, dict[str, object]] = {}
    recipe_reagents: dict[tuple[int, int], dict[str, object]] = {}
    for r in _rows(paths["SkillLineAbility"]):
        spell = _int(r["Spell"])
        line = _int(r["SkillLine"])
        if spell not in outputs or spell not in reagents or line not in skill_names:
            continue
        out_item, out_count = outputs[spell]
        if out_item not in known_items:
            continue
        rid = _int(r["ID"])
        recipes[rid] = {  # a later row with the same id replaces an earlier one
            "game_version": game_version,
            "id": rid,
            "spell_id": spell,
            "name": spell_names.get(spell, f"Spell {spell}"),
            "skill_line": line,
            "skill_name": skill_names[line],
            "min_skill": _int(r["MinSkillLineRank"]),
            "trivial_low": _int(r["TrivialSkillLineRankLow"]),
            "trivial_high": _int(r["TrivialSkillLineRankHigh"]),
            "output_item_id": out_item,
            "output_count": out_count,
        }
        for k in [k for k in recipe_reagents if k[0] == rid]:
            del recipe_reagents[k]
        for slot, (i, c) in enumerate(reagents[spell]):
            recipe_reagents[rid, i] = {
                "game_version": game_version,
                "recipe_id": rid,
                "item_id": i,
                "count": c,
                "slot": slot,
            }
    n_recipes = len(recipes)
    if recipes:
        conn.execute(schema.recipes.insert(), list(recipes.values()))
    if recipe_reagents:
        conn.execute(schema.recipe_reagents.insert(), list(recipe_reagents.values()))

    de_rows = []
    if disenchant_csv and disenchant_csv.exists():
        de_rows = [
            {
                "game_version": game_version,
                "item_class": _int(r["item_class"]),
                "quality": _int(r["quality"]),
                "min_ilvl": _int(r["min_ilvl"]),
                "max_ilvl": _int(r["max_ilvl"]),
                "result_item_id": _int(r["result_item_id"]),
                "chance": float(r["chance"]),
                "min_count": _int(r["min_count"]),
                "max_count": _int(r["max_count"]),
            }
            for r in _rows(disenchant_csv)
        ]
        if de_rows:
            conn.execute(schema.disenchant.insert(), de_rows)
    n_de = len(de_rows)

    n_vendor = 0
    if vendor_csv and vendor_csv.exists():
        vendor_ids = [_int(r["item_id"]) for r in _rows(vendor_csv)]
        rows = [{"game_version": game_version, "item_id": i} for i in dict.fromkeys(vendor_ids)]
        db.upsert(conn, schema.vendor_items, rows, ["game_version", "item_id"])
        n_vendor = len(vendor_ids)

    return {"items": len(items), "recipes": n_recipes, "disenchant_rows": n_de, "vendor_items": n_vendor}


def update(
    conn: Connection,
    game_version: str,
    build: str,
    cache_dir: Path,
    disenchant_csv: Path | None = None,
    vendor_csv: Path | None = None,
) -> dict[str, int]:
    """Download `build` (cached per build) and rebuild the version's game data from it, keeping prices."""
    stats = build_db(download_all(build, cache_dir), conn, game_version, disenchant_csv, vendor_csv)
    db.set_build(conn, game_version, build)
    return stats
