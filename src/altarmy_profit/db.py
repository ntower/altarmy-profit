"""The database: an engine factory over SQLite (local mode, tests) or Postgres (hosted), plus small helpers.

Queries use SQLAlchemy Core against the tables in `schema.py`; Alembic (`migrations/`) keeps the schema
current. Functions taking a `Connection` never commit: the caller owns the transaction (`Database.begin`).
All money values are integer copper.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, Table, create_engine, event, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url

from . import schema, versions

DEFAULT_DB = Path("data/altarmy-profit.sqlite")


def sqlite_url(path: Path | str) -> str:
    return f"sqlite:///{Path(path).as_posix()}"


def default_url(db: Path | str | None = None) -> str:
    """`DATABASE_URL` if set, else the SQLite file `db` (default data/altarmy-profit.sqlite)."""
    if db is not None:
        return sqlite_url(db)
    return os.environ.get("DATABASE_URL") or sqlite_url(DEFAULT_DB)


def utcnow() -> datetime:
    return datetime.now(UTC)


def utc(dt: datetime) -> datetime:
    """`dt` as an aware UTC datetime (SQLite hands timestamps back naive)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def timestamp_text(dt: datetime | None) -> str | None:
    """UTC as "YYYY-MM-DD HH:MM:SS", the format the API has always sent."""
    return None if dt is None else utc(dt).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """One engine per process, created on first use; the schema is migrated to the newest revision then.

    Share one instance across threads and open a connection per request (`begin` or `connect`).
    """

    def __init__(self, url: str) -> None:
        self.url = make_url(url)
        self._engine: Engine | None = None
        self._lock = threading.Lock()
        self._ready = False

    @property
    def is_sqlite(self) -> bool:
        return self.url.get_backend_name() == "sqlite"

    @property
    def display_url(self) -> str:
        """The SQLite file, or the URL without its password."""
        if self.is_sqlite:
            return self.url.database or ":memory:"
        return self.url.render_as_string(hide_password=True)

    @property
    def engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                self._engine = self._create_engine()
            return self._engine

    def _create_engine(self) -> Engine:
        if not self.is_sqlite:
            return create_engine(self.url, pool_pre_ping=True)
        if self.url.database:
            Path(self.url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(self.url, connect_args={"timeout": 30})

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: object) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return engine

    def ensure_schema(self) -> None:
        """Migrate to the newest revision and register the game versions and the local user (once per
        instance)."""
        if self._ready:
            return
        engine = self.engine
        with self._lock:
            if self._ready:
                return
            with engine.begin() as conn:
                upgrade(conn)
                register_versions(conn)
                register_local_user(conn)
            self._ready = True

    def connect(self) -> Connection:
        self.ensure_schema()
        return self.engine.connect()

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """A connection in a transaction, committed on success."""
        self.ensure_schema()
        with self.engine.begin() as conn:
            yield conn

    def dispose(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
                self._engine = None


def alembic_config(conn: Connection | None = None) -> Any:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", "altarmy_profit:migrations")
    if conn is not None:
        cfg.attributes["connection"] = conn
    return cfg


def upgrade(conn: Connection, revision: str = "head") -> None:
    from alembic import command

    command.upgrade(alembic_config(conn), revision)


def register_versions(conn: Connection) -> None:
    """A `game_versions` row for every known version (the build is left as ingest set it)."""
    rows = [
        {"id": v.key, "wago_product": v.wago_product, "interface": v.interface}
        for v in versions.VERSIONS.values()
    ]
    upsert(conn, schema.game_versions, rows, ["id"])


LOCAL_UID = "local"  # auth.LOCAL_USER.uid: local mode's one user, who owns what the CLI and sync store


def register_local_user(conn: Connection) -> None:
    """The local user's row (linked tier), which revision 0002 also creates for the data it moves."""
    now = utcnow()
    row = {"uid": LOCAL_UID, "created_at": now, "linked_at": now, "tier": "linked"}
    upsert(conn, schema.users, [row], ["uid"], update=[])


def upsert(
    conn: Connection,
    table: Table,
    rows: Sequence[Mapping[str, object]],
    keys: Sequence[str],
    update: Sequence[str] | None = None,
    where: Any = None,
) -> None:
    """Insert `rows`, updating `update` (default: every non-key column given) where `keys` collide.

    An empty `update` ignores collisions. `where` limits which existing rows are updated; refer to the
    incoming row as `excluded(table)`."""
    if not rows:
        return
    insert = sqlite.insert if conn.dialect.name == "sqlite" else postgresql.insert
    stmt = insert(table)
    cols = [c for c in rows[0] if c not in keys] if update is None else list(update)
    if cols:
        stmt = stmt.on_conflict_do_update(
            index_elements=list(keys), set_={c: stmt.excluded[c] for c in cols}, where=where
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(keys))
    conn.execute(stmt, [dict(r) for r in rows])


def get_build(conn: Connection, game_version: str) -> str | None:
    t = schema.game_versions
    build = conn.execute(select(t.c.build).where(t.c.id == game_version)).scalar_one_or_none()
    return None if build is None else str(build)


def set_build(conn: Connection, game_version: str, build: str) -> None:
    t = schema.game_versions
    conn.execute(t.update().where(t.c.id == game_version).values(build=build))


COUNTED_TABLES = ("items", "recipes", "disenchant", "vendor_items")


def count_rows(conn: Connection, table: str, game_version: str) -> int:
    """Rows of one version in a game-data table."""
    if table not in COUNTED_TABLES:
        raise ValueError(f"not a countable table: {table}")
    t = schema.metadata.tables[table]
    return int(
        conn.execute(select(func.count()).select_from(t).where(t.c.game_version == game_version)).scalar_one()
    )
