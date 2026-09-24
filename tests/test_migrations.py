"""The Alembic migrations build exactly `schema.metadata`, and can be undone."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from altarmy_profit import db, schema


def test_migrations_match_the_schema(database: db.Database) -> None:
    with database.engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        assert compare_metadata(ctx, schema.metadata) == []


def test_downgrade_to_base_and_back(database: db.Database) -> None:
    with database.engine.begin() as conn:
        command.downgrade(db.alembic_config(conn), "base")
        assert set(inspect(conn).get_table_names()) <= {"alembic_version"}
        db.upgrade(conn)
        db.register_versions(conn)
        assert set(schema.metadata.tables) <= set(inspect(conn).get_table_names())
