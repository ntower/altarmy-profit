"""Load database rows into the engine's plain dataclasses, and store characters and AH blocks."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path

from sqlalchemy import Connection, delete, select

from . import db, prices, schema
from .altarmy import Character, Profession
from .engine import AH_CUT, MAIL_POSTAGE, DisenchantRow, Item, Market, Recipe

CACHE_DIR = Path("cache")
IN_CHUNK = 900  # ids per IN (...) query, under SQLite's bound-parameter limit


@dataclass(frozen=True)
class ItemDetails:
    """What an item tooltip shows. Not needed by the engine, so it is not part of engine.Item."""

    id: int
    name: str
    quality: int
    class_id: int
    subclass_name: str | None
    inventory_type: int
    bonding: int
    item_delay: int  # ms
    container_slots: int
    required_level: int
    required_skill: str | None
    required_skill_rank: int
    description: str | None
    sell_price: int
    icon: str | None


def load_market(
    conn: Connection,
    game_version: str,
    auction_house_id: int | None,
    *,
    ah_cut: float = AH_CUT,
    mail_postage: int = MAIL_POSTAGE,
) -> Market:
    """One version's game data priced by an auction house's current prices (None: no prices), with the
    version's AH cut and postage per attachment."""
    i, v = schema.items, schema.vendor_items
    sold = (
        select(v.c.item_id)
        .where(v.c.game_version == game_version, v.c.item_id == i.c.id)
        .exists()
        .label("sold")
    )
    items = {
        r.id: Item(
            r.id,
            r.name,
            r.quality,
            r.item_level,
            r.class_id,
            r.sell_price,
            -(-r.buy_price // r.buy_count) if r.sold and r.buy_price > 0 else None,
            r.stack_size,
        )
        for r in conn.execute(select(i, sold).where(i.c.game_version == game_version))
    }
    rr = schema.recipe_reagents
    reagents: dict[int, list[tuple[int, int]]] = {}
    for recipe_id, item_id, count in conn.execute(
        select(rr.c.recipe_id, rr.c.item_id, rr.c.count)
        .where(rr.c.game_version == game_version)
        .order_by(rr.c.recipe_id, rr.c.slot)
    ):
        reagents.setdefault(recipe_id, []).append((item_id, count))
    rt = schema.recipes
    recipes = [
        Recipe(
            r.id,
            r.name,
            r.output_item_id,
            r.output_count,
            tuple(reagents.get(r.id, ())),
            r.skill_name,
            r.min_skill,
            r.spell_id,
            r.trivial_low,
            r.trivial_high,
        )
        for r in conn.execute(select(rt).where(rt.c.game_version == game_version).order_by(rt.c.id))
    ]
    d = schema.disenchant
    de = [
        DisenchantRow(
            r.item_class,
            r.quality,
            r.min_ilvl,
            r.max_ilvl,
            r.result_item_id,
            r.chance,
            r.min_count,
            r.max_count,
        )
        for r in conn.execute(select(d).where(d.c.game_version == game_version).order_by(d.c.id))
    ]
    current = prices.load_current(conn, auction_house_id)
    return Market(items, recipes, current, de, ah_cut, mail_postage=mail_postage)


def load_item_details(conn: Connection, game_version: str, ids: Iterable[int]) -> dict[int, ItemDetails]:
    """Tooltip details for the given item ids; unknown ids are left out."""
    wanted = sorted(set(ids))
    t = schema.items
    columns = [t.c[f.name] for f in fields(ItemDetails)]
    out: dict[int, ItemDetails] = {}
    for start in range(0, len(wanted), IN_CHUNK):
        chunk = wanted[start : start + IN_CHUNK]
        query = select(*columns).where(t.c.game_version == game_version, t.c.id.in_(chunk))
        for r in conn.execute(query):
            out[r.id] = ItemDetails(*r)
    return out


def save_characters(conn: Connection, game_version: str, chars: Sequence[Character]) -> None:
    """Replace the version's stored characters with `chars` (Alt Army's file is the source of truth)."""
    c = schema.characters
    conn.execute(delete(c).where(c.c.game_version == game_version))  # professions and recipes cascade
    for ch in chars:
        char_id: int = conn.execute(
            c.insert()
            .values(
                game_version=game_version,
                realm=ch.realm,
                name=ch.name,
                faction=ch.faction,
                class_file=ch.class_file,
                level=ch.level,
            )
            .returning(c.c.id)
        ).scalar_one()
        for p in ch.professions:
            conn.execute(
                schema.character_professions.insert().values(
                    character_id=char_id, skill_name=p.name, rank=p.rank, max_rank=p.max_rank
                )
            )
            if p.recipe_ids:
                conn.execute(
                    schema.character_recipes.insert(),
                    [
                        {"character_id": char_id, "skill_name": p.name, "spell_id": spell}
                        for spell in sorted(p.recipe_ids)
                    ],
                )


def load_characters(conn: Connection, game_version: str) -> list[Character]:
    """The version's characters sorted by realm then name, professions sorted by name."""
    c, cp, cr = schema.characters, schema.character_professions, schema.character_recipes
    mine = select(c.c.id).where(c.c.game_version == game_version)
    recipes: dict[tuple[int, str], set[int]] = {}
    for r in conn.execute(select(cr).where(cr.c.character_id.in_(mine))):
        recipes.setdefault((r.character_id, r.skill_name), set()).add(r.spell_id)
    profs: dict[int, list[Profession]] = {}
    for r in conn.execute(select(cp).where(cp.c.character_id.in_(mine)).order_by(cp.c.skill_name)):
        key = (r.character_id, r.skill_name)
        profs.setdefault(r.character_id, []).append(
            Profession(r.skill_name, r.rank, r.max_rank, frozenset(recipes.get(key, ())))
        )
    return [
        Character(r.realm, r.name, r.faction, r.class_file, r.level, tuple(profs.get(r.id, ())))
        for r in conn.execute(select(c).where(c.c.game_version == game_version).order_by(c.c.realm, c.c.name))
    ]


def load_ah_blocked(conn: Connection, game_version: str) -> list[tuple[int, str]]:
    """Items never to sell on the AH as (item id, when added as UTC text), newest first."""
    t = schema.ah_blocked
    rows = conn.execute(
        select(t.c.item_id, t.c.added_at)
        .where(t.c.game_version == game_version)
        .order_by(t.c.added_at.desc(), t.c.item_id)
    )
    return [(r.item_id, db.timestamp_text(r.added_at) or "") for r in rows]


def set_ah_blocked(conn: Connection, game_version: str, item_id: int, blocked: bool) -> None:
    """Never sell `item_id` on the AH, or allow it again."""
    t = schema.ah_blocked
    if blocked:
        row = {"game_version": game_version, "item_id": item_id, "added_at": db.utcnow()}
        db.upsert(conn, t, [row], ["game_version", "item_id"], update=[])
    else:
        conn.execute(delete(t).where(t.c.game_version == game_version, t.c.item_id == item_id))
