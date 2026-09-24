"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-24 15:13:56.045870
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_versions",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("wago_product", sa.String(length=64), nullable=False),
        sa.Column("build", sa.String(length=32), nullable=True),
        sa.Column("interface", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_versions")),
    )
    op.create_table(
        "ah_blocked",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_ah_blocked_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "item_id", name=op.f("pk_ah_blocked")),
    )
    op.create_table(
        "auction_houses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("realm", sa.String(length=64), nullable=False),
        sa.Column("faction", sa.String(length=16), nullable=False),
        sa.Column("region", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_auction_houses_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auction_houses")),
        sa.UniqueConstraint(
            "game_version", "realm", "faction", name=op.f("uq_auction_houses_game_version_realm_faction")
        ),
    )
    op.create_table(
        "characters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("faction", sa.String(length=16), nullable=False),
        sa.Column("class_file", sa.String(length=32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_characters_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
        sa.UniqueConstraint(
            "game_version", "realm", "name", name=op.f("uq_characters_game_version_realm_name")
        ),
    )
    op.create_table(
        "disenchant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("item_class", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("min_ilvl", sa.Integer(), nullable=False),
        sa.Column("max_ilvl", sa.Integer(), nullable=False),
        sa.Column("result_item_id", sa.Integer(), nullable=False),
        sa.Column("chance", sa.Float(), nullable=False),
        sa.Column("min_count", sa.Integer(), nullable=False),
        sa.Column("max_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_disenchant_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disenchant")),
    )
    with op.batch_alter_table("disenchant", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_disenchant_game_version"), ["game_version"], unique=False)

    op.create_table(
        "items",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("item_level", sa.Integer(), nullable=False),
        sa.Column("required_level", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("subclass_id", sa.Integer(), nullable=False),
        sa.Column("sell_price", sa.Integer(), nullable=False),
        sa.Column("buy_price", sa.Integer(), nullable=False),
        sa.Column("bonding", sa.Integer(), nullable=False),
        sa.Column("inventory_type", sa.Integer(), nullable=False),
        sa.Column("item_delay", sa.Integer(), nullable=False),
        sa.Column("container_slots", sa.Integer(), nullable=False),
        sa.Column("subclass_name", sa.Text(), nullable=True),
        sa.Column("required_skill", sa.Text(), nullable=True),
        sa.Column("required_skill_rank", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("buy_count", sa.Integer(), nullable=False),
        sa.Column("stack_size", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_items_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "id", name=op.f("pk_items")),
    )
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_items_game_version_name"), ["game_version", "name"], unique=False
        )

    op.create_table(
        "recipes",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("spell_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("skill_line", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("min_skill", sa.Integer(), nullable=False),
        sa.Column("trivial_low", sa.Integer(), nullable=False),
        sa.Column("trivial_high", sa.Integer(), nullable=False),
        sa.Column("output_item_id", sa.Integer(), nullable=False),
        sa.Column("output_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_recipes_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "id", name=op.f("pk_recipes")),
    )
    op.create_table(
        "settings",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_settings_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "key", name=op.f("pk_settings")),
    )
    op.create_table(
        "vendor_items",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_vendor_items_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "item_id", name=op.f("pk_vendor_items")),
    )
    op.create_table(
        "character_professions",
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.String(length=64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("max_rank", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            name=op.f("fk_character_professions_character_id_characters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("character_id", "skill_name", name=op.f("pk_character_professions")),
    )
    op.create_table(
        "character_recipes",
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.String(length=64), nullable=False),
        sa.Column("spell_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            name=op.f("fk_character_recipes_character_id_characters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("character_id", "skill_name", "spell_id", name=op.f("pk_character_recipes")),
    )
    op.create_table(
        "price_daily",
        sa.Column("auction_house_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("low", sa.BigInteger(), nullable=False),
        sa.Column("median", sa.BigInteger(), nullable=True),
        sa.Column("high", sa.BigInteger(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["auction_house_id"],
            ["auction_houses.id"],
            name=op.f("fk_price_daily_auction_house_id_auction_houses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("auction_house_id", "item_id", "day", name=op.f("pk_price_daily")),
    )
    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auction_house_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("uploader_uid", sa.String(length=128), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "source IN ('auctionator', 'ahdb', 'blizzard_api', 'csv', 'manual')",
            name=op.f("ck_price_snapshots_source"),
        ),
        sa.CheckConstraint("status IN ('accepted', 'quarantined')", name=op.f("ck_price_snapshots_status")),
        sa.ForeignKeyConstraint(
            ["auction_house_id"],
            ["auction_houses.id"],
            name=op.f("fk_price_snapshots_auction_house_id_auction_houses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_snapshots")),
    )
    with op.batch_alter_table("price_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_price_snapshots_auction_house_id"), ["auction_house_id"], unique=False
        )

    op.create_table(
        "realm_aliases",
        sa.Column("auction_house_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["auction_house_id"],
            ["auction_houses.id"],
            name=op.f("fk_realm_aliases_auction_house_id_auction_houses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("auction_house_id", "kind", "value", name=op.f("pk_realm_aliases")),
    )
    with op.batch_alter_table("realm_aliases", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_realm_aliases_kind_value"), ["kind", "value"], unique=False)

    op.create_table(
        "recipe_reagents",
        sa.Column("game_version", sa.String(length=16), nullable=False),
        sa.Column("recipe_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["game_version", "recipe_id"],
            ["recipes.game_version", "recipes.id"],
            name=op.f("fk_recipe_reagents_game_version_recipe_id_recipes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["game_version"], ["game_versions.id"], name=op.f("fk_recipe_reagents_game_version_game_versions")
        ),
        sa.PrimaryKeyConstraint("game_version", "recipe_id", "item_id", name=op.f("pk_recipe_reagents")),
    )
    op.create_table(
        "price_current",
        sa.Column("auction_house_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("median_7d", sa.BigInteger(), nullable=True),
        sa.Column("avail_7d", sa.Integer(), nullable=True),
        sa.Column("scans_7d", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["auction_house_id"],
            ["auction_houses.id"],
            name=op.f("fk_price_current_auction_house_id_auction_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["price_snapshots.id"], name=op.f("fk_price_current_snapshot_id_price_snapshots")
        ),
        sa.PrimaryKeyConstraint("auction_house_id", "item_id", name=op.f("pk_price_current")),
    )
    with op.batch_alter_table("price_current", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_price_current_snapshot_id"), ["snapshot_id"], unique=False)

    op.create_table(
        "price_observations",
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("min_buyout", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("listings", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["price_snapshots.id"],
            name=op.f("fk_price_observations_snapshot_id_price_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "item_id", name=op.f("pk_price_observations")),
    )
    with op.batch_alter_table("price_observations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_price_observations_item_id"), ["item_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("price_observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_observations_item_id"))

    op.drop_table("price_observations")
    with op.batch_alter_table("price_current", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_current_snapshot_id"))

    op.drop_table("price_current")
    op.drop_table("recipe_reagents")
    with op.batch_alter_table("realm_aliases", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_realm_aliases_kind_value"))

    op.drop_table("realm_aliases")
    with op.batch_alter_table("price_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_price_snapshots_auction_house_id"))

    op.drop_table("price_snapshots")
    op.drop_table("price_daily")
    op.drop_table("character_recipes")
    op.drop_table("character_professions")
    op.drop_table("vendor_items")
    op.drop_table("settings")
    op.drop_table("recipes")
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_items_game_version_name"))

    op.drop_table("items")
    with op.batch_alter_table("disenchant", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_disenchant_game_version"))

    op.drop_table("disenchant")
    op.drop_table("characters")
    op.drop_table("auction_houses")
    op.drop_table("ah_blocked")
    op.drop_table("game_versions")
