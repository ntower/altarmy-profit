"""Disenchant brackets from Auctionator's `Source_Classic/Enchant/DisenchantingProbabilities.lua`.

Disenchant results are server-side loot data, not in DB2. Auctionator ships a table per item class (armor,
weapon) and quality (uncommon, rare, epic): rows of `{min ilvl, max ilvl, pct, count, item, pct, count,
item, ...}`, one triple per possible (count, material). `scripts/build_disenchant.py` turns them into
`data/<version>/disenchant.csv` rows with `min_count == max_count`, which the engine values the same way.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .engine import DisenchantRow

# Enum.ItemClass / Enum.ItemQuality names as Auctionator writes them -> DB2 ids.
ITEM_CLASSES = {"Weapon": 2, "Armor": 4}
QUALITIES = {"Good": 2, "Rare": 3, "Epic": 4}
TBC_MAX_ILVL = 164  # Sunwell's top epics

_SECTION = re.compile(r"\[\s*Enum\.(ItemClass|ItemQuality)\.(\w+)\s*\]")
_ROW = re.compile(r"^\s*\{([\d.,\s]+)\}")


@dataclass(frozen=True)
class ParsedRow:
    item_class: int
    quality: int
    min_ilvl: int
    max_ilvl: int
    outcomes: tuple[tuple[float, float, int], ...]  # (percent, count, material item id)


def parse(text: str) -> Iterator[ParsedRow]:
    """Every uncommented bracket row, tagged with the class and quality section it sits in."""
    item_class = quality = 0
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        for kind, name in _SECTION.findall(line):
            if kind == "ItemClass":
                item_class = ITEM_CLASSES.get(name, 0)
            else:
                quality = QUALITIES.get(name, 0)
        m = _ROW.match(line)
        if not m or not item_class or not quality:
            continue
        nums = [float(n) for n in m.group(1).split(",") if n.strip()]
        lo, hi, rest = nums[0], nums[1], nums[2:]
        if len(rest) % 3:
            raise ValueError(f"bracket {lo:g}-{hi:g}: {len(rest)} numbers after the item levels, not triples")
        outcomes = tuple((rest[i], rest[i + 1], int(rest[i + 2])) for i in range(0, len(rest), 3))
        yield ParsedRow(item_class, quality, int(lo), int(hi), outcomes)


def to_rows(parsed: Iterator[ParsedRow] | list[ParsedRow], max_ilvl: int) -> list[DisenchantRow]:
    """DisenchantRows for brackets starting at or below `max_ilvl`; zero-chance outcomes are dropped.

    Counts must be whole numbers there (later expansions' brackets average fractional counts)."""
    out = []
    for r in parsed:
        if r.min_ilvl > max_ilvl:
            continue
        for pct, count, item in r.outcomes:
            if pct <= 0:
                continue
            if not count.is_integer():
                raise ValueError(f"bracket {r.min_ilvl}-{r.max_ilvl}: fractional count {count:g}")
            n = int(count)
            out.append(
                DisenchantRow(
                    r.item_class, r.quality, r.min_ilvl, r.max_ilvl, item, round(pct / 100, 6), n, n
                )
            )
    return out


def auctionator_table(addon_dir: Path) -> Path:
    return addon_dir / "Source_Classic" / "Enchant" / "DisenchantingProbabilities.lua"
