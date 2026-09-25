"""The database schema as SQLAlchemy Core tables, shared by SQLite (local mode, tests) and Postgres (hosted).

Alembic migrations (`migrations/`) create it; a test checks they match. All money is integer copper. Game
data is keyed by `game_version`; prices by auction house, whose row carries the version. User state
(settings, characters, AH blocks, the local file sync) is keyed by `user_uid` and `game_version`; local mode
has one user, `auth.LOCAL_USER` ("local").
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
TIERS = ("free", "linked")
UPLOAD_KINDS = ("altarmy", "auctionator")
UPLOAD_VIA = ("browser", "watcher")
UPLOAD_OUTCOMES = ("accepted", "rejected")
SNAPSHOT_STATUSES = ("accepted", "quarantined")


def _version(primary_key: bool = True) -> Column[str]:
    return Column(
        "game_version", String(16), ForeignKey("game_versions.id"), primary_key=primary_key, nullable=False
    )


def _owner(primary_key: bool = True) -> Column[str]:
    return Column(
        "user_uid",
        String(128),
        ForeignKey("users.uid", ondelete="CASCADE"),
        primary_key=primary_key,
        nullable=False,
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

# --- users and their state ------------------------------------------------------------------------
# Firebase uids (hosted mode) or "local". The tier is the one the user's last token carried.
users = Table(
    "users",
    metadata,
    Column("uid", String(128), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("linked_at", DateTime(timezone=True)),  # first seen with a linked (non-anonymous) account
    Column("tier", String(16), nullable=False),
    Column("trust_score", Float, nullable=False, default=1.0, server_default="1"),  # used from Phase 6
    CheckConstraint(f"tier IN ({_in(TIERS)})", name="tier"),
)

user_settings = Table(
    "user_settings",
    metadata,
    _owner(),
    _version(),
    Column("selected_realm", Text),  # whose characters count, with selected_faction; NULL: the largest group
    Column("selected_faction", String(16)),
    # bumped whenever the user's characters or prices were re-imported, so the front end refetches
    Column("data_version", Integer, nullable=False, default=0, server_default="0"),
)

# Local mode's addon file sync: which SavedVariables files it reads and when they last changed.
local_sync = Table(
    "local_sync",
    metadata,
    _owner(),
    _version(),
    Column("altarmy_path", Text),
    Column("altarmy_mtime", BigInteger),  # ns
    Column("altarmy_synced", DateTime(timezone=True)),
    Column("auctionator_path", Text),
    Column("auctionator_mtime", BigInteger),
    Column(
        "auctionator_synced", DateTime(timezone=True)
    ),  # set even when the scan had no prices for the realm
    Column("auctionator_realm", Text),  # Auctionator's key for the selection; "" if it has none
    Column("auctionator_for", Text),  # the selection the prices were recorded for: realm, a tab, faction
)

# Characters from the Alt Army addon's SavedVariables, replaced wholesale on every import.
characters = Table(
    "characters",
    metadata,
    Column("id", Integer, primary_key=True),
    _owner(primary_key=False),
    _version(primary_key=False),
    Column("realm", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("faction", String(16), nullable=False),  # Horde | Alliance | "" (never scanned)
    Column("class_file", String(32), nullable=False),  # e.g. PALADIN
    Column("level", Integer, nullable=False),
    UniqueConstraint("user_uid", "game_version", "realm", "name"),
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
    _owner(),
    _version(),
    Column("item_id", Integer, primary_key=True, autoincrement=False),
    Column("added_at", DateTime(timezone=True), nullable=False),
)

# Every addon file a user uploaded (the file itself is never stored), for their history and rate limit.
uploads = Table(
    "uploads",
    metadata,
    Column("id", Integer, primary_key=True),
    _owner(primary_key=False),
    _version(primary_key=False),
    Column("kind", String(16), nullable=False),
    Column("via", String(16), nullable=False),
    Column("size", Integer, nullable=False),  # bytes, decompressed
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("detail", Text, nullable=False),  # what it imported, or why it was rejected
    CheckConstraint(f"kind IN ({_in(UPLOAD_KINDS)})", name="kind"),
    CheckConstraint(f"via IN ({_in(UPLOAD_VIA)})", name="via"),
    CheckConstraint(f"outcome IN ({_in(UPLOAD_OUTCOMES)})", name="outcome"),
    Index(None, "user_uid", "received_at"),
)

# Keys the CLI watcher uploads with. Only a hash is kept; the key is shown once when it is made.
api_keys = Table(
    "api_keys",
    metadata,
    Column("id", Integer, primary_key=True),
    _owner(primary_key=False),
    Column("key_hash", String(64), nullable=False, unique=True),  # SHA-256 hex
    Column("prefix", String(16), nullable=False),  # the key's start, to tell keys apart
    Column("label", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
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
    # bumped by each merge that changed price_current's 7-day columns, so cached markets notice
    Column("price_version", Integer, nullable=False, default=0, server_default="0"),
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
    # who sent it (a users.uid). No foreign key: adding one makes SQLite rebuild this table, whose drop
    # would cascade into price_observations.
    Column("uploader_uid", String(128)),
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
