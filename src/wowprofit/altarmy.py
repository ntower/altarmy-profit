"""Read characters, professions and learned recipes from the Alt Army addon's SavedVariables.

The file is account-wide (WTF/Account/<acct>/SavedVariables/AltArmy_TBC.lua). Characters live in
`AltArmyTBC_Data.Characters[realm][name]`; each profession has `rank`, `maxRank` and
`Recipes[recipeID] = {color, primaryRecipeID?, resultItemID?, name?}`.

Recipe ids are craft spell ids (they match `recipes.spell_id`). On TBC clients one recipe can be stored
under several alias keys that all share a `primaryRecipeID`; Enchanting rows only carry `color`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .luasv import LuaTable, LuaValue, parse_assignments


@dataclass(frozen=True)
class Profession:
    name: str
    rank: int
    max_rank: int
    recipe_ids: frozenset[int]


@dataclass(frozen=True)
class Character:
    realm: str
    name: str
    faction: str  # Horde | Alliance ("" if never scanned)
    class_file: str  # e.g. PALADIN
    level: int
    professions: tuple[Profession, ...]  # sorted by name

    @property
    def known_recipes(self) -> frozenset[int]:
        return frozenset().union(*(p.recipe_ids for p in self.professions))


@dataclass(frozen=True)
class Group:
    """The characters of one realm and faction: they share an auction house and can mail each other."""

    realm: str
    faction: str
    characters: tuple[Character, ...]


def groups(chars: Iterable[Character]) -> list[Group]:
    """Realm/faction groups sorted by realm then faction. Characters without a faction are left out."""
    by_key: dict[tuple[str, str], list[Character]] = {}
    for c in chars:
        if c.faction:
            by_key.setdefault((c.realm, c.faction), []).append(c)
    return [Group(realm, faction, tuple(cs)) for (realm, faction), cs in sorted(by_key.items())]


def crafters(chars: Iterable[Character]) -> dict[int, list[str]]:
    """Recipe id -> names of the characters who know it."""
    out: dict[int, list[str]] = {}
    for c in chars:
        for rid in sorted(c.known_recipes):
            out.setdefault(rid, []).append(c.name)
    return out


def parse_characters(data: bytes) -> list[Character]:
    """All characters in the file, sorted by realm then name."""
    root = parse_assignments(data).get("AltArmyTBC_Data")
    if not isinstance(root, dict):
        raise ValueError("no AltArmyTBC_Data in file (is this Alt Army's AltArmy_TBC.lua?)")
    chars: list[Character] = []
    for realm, by_name in _table(root.get("Characters")).items():
        for name, char in _table(by_name).items():
            c = _table(char)
            chars.append(
                Character(
                    realm=str(realm),
                    name=str(name),
                    faction=_str(c.get("faction")),
                    class_file=_str(c.get("classFile")),
                    level=_int(c.get("level")),
                    professions=tuple(
                        sorted(
                            (_profession(str(n), _table(p)) for n, p in _table(c.get("Professions")).items()),
                            key=lambda p: p.name,
                        )
                    ),
                )
            )
    return sorted(chars, key=lambda c: (c.realm, c.name))


def _profession(name: str, prof: LuaTable) -> Profession:
    ids = set()
    for key, row in _table(prof.get("Recipes")).items():
        primary = _table(row).get("primaryRecipeID")
        rid = primary if isinstance(primary, int) else key
        if isinstance(rid, int) and not isinstance(rid, bool):
            ids.add(rid)
    return Profession(name, _int(prof.get("rank")), _int(prof.get("maxRank")), frozenset(ids))


def _table(v: LuaValue) -> LuaTable:
    return v if isinstance(v, dict) else {}


def _str(v: LuaValue) -> str:
    return v if isinstance(v, str) else ""


def _int(v: LuaValue) -> int:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0
