"""The database schema as SQLAlchemy Core tables, shared by SQLite (local mode, tests) and Postgres (hosted).

Alembic migrations (`migrations/`) create it; a test checks they match. All money is integer copper. Game
data and local state are keyed by `game_version`; prices by auction house, whose row carries the version.
Phase 3 adds a user id to the local-state tables (settings, characters, ah_blocked).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

PRICE_SOURCES = ("auctionator", "ahdb", "blizzard_api", "csv", "manual")
SNAPSHOT_STATUSES = ("accepted", "quarantined")


def _version(primary_key: bool = True) -> Column[str]:
    return Column(
        "game_version", String(16), ForeignKey("game_versions.id"), primary_key=primary_key, nullable=False
    )


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# --- game data -------------------------------------------------------------------------------------
game_versions = Table(
    "game_versions",
    metadata,
    Column("id", String(16), primary_key=True),  # versions.GameVersion.key: tbc | forever
    Column("wago_product", String(64), nullable=False),
    Column("build", String(32)),  # the DB2 build loaded; NULL before the first game data download
    Column("interface", Integer),  # client interface number, e.g. 20506
)

items = Table(
    "items",
    metadata,
    _version(),
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("quality", Integer, nullable=False, default=1),  # 0 poor, 1 common, 2 uncommon, 3 rare, 4 epic
    Column("item_level", Integer, nullable=False, default=0),
    Column("required_level", Integer, nullable=False, default=0),
    Column("class_id", Integer, nullable=False, default=0),  # 2 weapon, 4 armor, ...
    Column("subclass_id", Integer, nullable=False, default=0),
    Column("sell_price", Integer, nullable=False, default=0),  # vendor buys from you
    Column("buy_price", Integer, nullable=False, default=0),  # per buy_count units, if a vendor sells it
    Column("bonding", Integer, nullable=False, default=0),  # 1 on pickup, 2 on equip, 3 on use, 4 quest
    Column("inventory_type", Integer, nullable=False, default=0),  # equip slot: 5 chest, 13 one-hand, ...
    Column("item_delay", Integer, nullable=False, default=0),  # weapon speed, ms
    Column("container_slots", Integer, nullable=False, default=0),
    Column("subclass_name", Text),  # ItemSubClass display name, e.g. Cloth, Sword
    Column("required_skill", Text),  # skill line name, e.g. Engineering
    Column("required_skill_rank", Integer, nullable=False, default=0),
    Column("description", Text),  # flavor text
    Column("icon", Text),  # icon file name, lowercase, without extension
    Column("buy_count", Integer, nullable=False, default=1),  # vendors sell stacks of this many
    Column("stack_size", Integer, nullable=False, default=1),  # units per stack (one mail attachment)
    Index(None, "game_version", "name"),
)

recipes = Table(
    "recipes",
    metadata,
    _version(),
    Column("id", Integer, primary_key=True, autoincrement=False),  # SkillLineAbility.ID
    Column("spell_id", Integer, nullable=False),
    Column("name", Text, nullable=False),
    Column("skill_line", Integer, nullable=False),
    Column("skill_name", Text, nullable=False),
    Column("min_skill", Integer, nullable=False, default=0),
    Column("trivial_low", Integer, nullable=False, default=0),  # yellow -> green threshold
    Column("trivial_high", Integer, nullable=False, default=0),  # green -> grey threshold
    Column("output_item_id", Integer, nullable=False),
    Column("output_count", Integer, nullable=False, default=1),
)

recipe_reagents = Table(
    "recipe_reagents",
    metadata,
    _version(),
    Column("recipe_id", Integer, primary_key=True, autoincrement=False),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
    Column("count", Integer, nullable=False),
    Column(
        "slot", Integer, nullable=False
    ),  # position in SpellReagents (0..7): the order a recipe lists them
    ForeignKeyConstraint(
        ["game_version", "recipe_id"], ["recipes.game_version", "recipes.id"], ondelete="CASCADE"
    ),
)

# Disenchant results are server-side loot data, NOT in DB2. Seeded from data/<version>/disenchant.csv.
disenchant = Table(
    "disenchant",
    metadata,
    Column("id", Integer, primary_key=True),
    _version(primary_key=False),
    Column("item_class", Integer, nullable=False),
    Column("quality", Integer, nullable=False),
    Column("min_ilvl", Integer, nullable=False),
    Column("max_ilvl", Integer, nullable=False),
    Column("result_item_id", Integer, nullable=False),
    Column("chance", Float, nullable=False),  # 0..1 per disenchant
    Column("min_count", Integer, nullable=False),
    Column("max_count", Integer, nullable=False),
    Index(None, "game_version"),
)

# Which items vendors sell (unlimited stock) is server-side data, NOT in DB2. Seeded from
# data/<version>/vendor_items.csv; the price is items.buy_price / buy_count.
vendor_items = Table(
    "vendor_items",
    metadata,
    _version(),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
)

# --- local state (per user from Phase 3) -----------------------------------------------------------
settings = Table(
    "settings",
    metadata,
    _version(),
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

# Characters from the Alt Army addon's SavedVariables, replaced wholesale on every import.
characters = Table(
    "characters",
    metadata,
    Column("id", Integer, primary_key=True),
    _version(primary_key=False),
    Column("realm", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("faction", String(16), nullable=False),  # Horde | Alliance | "" (never scanned)
    Column("class_file", String(32), nullable=False),  # e.g. PALADIN
    Column("level", Integer, nullable=False),
    UniqueConstraint("game_version", "realm", "name"),
)

character_professions = Table(
    "character_professions",
    metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_name", String(64), primary_key=True),
    Column("rank", Integer, nullable=False),
    Column("max_rank", Integer, nullable=False),
)

character_recipes = Table(
    "character_recipes",
    metadata,
    Column("character_id", Integer, ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_name", String(64), primary_key=True),
    Column("spell_id", Integer, primary_key=True, autoincrement=False),  # matches recipes.spell_id
)

# Items the user never wants sold on the AH (only vendor or disenchant). Ingest leaves them alone.
ah_blocked = Table(
    "ah_blocked",
    metadata,
    _version(),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
    Column("added_at", DateTime(timezone=True), nullable=False),
)

# --- prices ----------------------------------------------------------------------------------------
# One auction house per (version, realm, faction); faction "" is an auction house both factions share.
auction_houses = Table(
    "auction_houses",
    metadata,
    Column("id", Integer, primary_key=True),
    _version(primary_key=False),
    Column("realm", String(64), nullable=False),  # "" for the unnamed auction house (no realm selected)
    Column("faction", String(16), nullable=False),
    Column("region", String(16)),  # informational: us, eu, test, ...
    UniqueConstraint("game_version", "realm", "faction"),
)

# Other names for an auction house: Auctionator's realm key, later addon realm names and Blizzard ids.
realm_aliases = Table(
    "realm_aliases",
    metadata,
    Column(
        "auction_house_id",
        Integer,
        ForeignKey("auction_houses.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("kind", String(16), primary_key=True),  # auctionator
    Column("value", String(128), primary_key=True),
    Index(None, "kind", "value"),
)

price_snapshots = Table(
    "price_snapshots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "auction_house_id",
        Integer,
        ForeignKey("auction_houses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("source", String(16), nullable=False),
    Column("uploader_uid", String(128)),  # who sent it; a users foreign key from Phase 3
    Column("scanned_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("item_count", Integer, nullable=False),  # items in the scan (observations hold only news)
    Column("status", String(16), nullable=False, default="accepted"),
    CheckConstraint(f"source IN ({_in(PRICE_SOURCES)})", name="source"),
    CheckConstraint(f"status IN ({_in(SNAPSHOT_STATUSES)})", name="status"),
)

# Prices a snapshot added: only items whose price or last-seen day moved. Pruned after ~90 days.
price_observations = Table(
    "price_observations",
    metadata,
    Column(
        "snapshot_id",
        Integer,
        ForeignKey("price_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
    Column("min_buyout", BigInteger, nullable=False),
    Column("quantity", Integer),
    Column("listings", Integer),
    Index(None, "item_id"),
)

# What the engine prices with: the newest observation per auction house and item.
price_current = Table(
    "price_current",
    metadata,
    Column(
        "auction_house_id",
        Integer,
        ForeignKey("auction_houses.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
    Column("price", BigInteger, nullable=False),
    Column("seen_at", DateTime(timezone=True), nullable=False),
    Column("snapshot_id", Integer, ForeignKey("price_snapshots.id"), nullable=False, index=True),
    Column("median_7d", BigInteger),  # filled by the Phase 6 merge job
    Column("avail_7d", Integer),
    Column("scans_7d", Integer),
)

# One row per auction house, item and day, for charts and stale checks.
price_daily = Table(
    "price_daily",
    metadata,
    Column(
        "auction_house_id",
        Integer,
        ForeignKey("auction_houses.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("item_id", Integer, nullable=False),
    Column("day", Date, nullable=False),
    Column("low", BigInteger, nullable=False),
    Column("median", BigInteger),  # filled by the Phase 6 aggregation
    Column("high", BigInteger, nullable=False),
    Column("available", Integer),  # most seen that day
    PrimaryKeyConstraint("auction_house_id", "item_id", "day"),
)
