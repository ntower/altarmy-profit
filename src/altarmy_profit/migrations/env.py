"""Alembic environment: migrates the connection `db.upgrade` passes in, or the configured URL (the
`sqlalchemy.url` option, else `db.default_url()`: `DATABASE_URL` or data/altarmy-profit.sqlite)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from altarmy_profit import db, schema


def _run(conn: Connection) -> None:
    context.configure(
        connection=conn,
        target_metadata=schema.metadata,
        render_as_batch=conn.dialect.name == "sqlite",  # SQLite can't ALTER most things: copy tables
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def main() -> None:
    conn = context.config.attributes.get("connection")
    if conn is not None:
        _run(conn)
        return
    database = db.Database(context.config.get_main_option("sqlalchemy.url") or db.default_url())
    with database.engine.begin() as conn:
        _run(conn)


main()
