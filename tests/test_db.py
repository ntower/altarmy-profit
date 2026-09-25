from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Connection, inspect, select

from altarmy_profit import db, schema

from .conftest import FOREVER


def test_the_local_user_is_registered(conn: Connection) -> None:
    u = schema.users
    assert [tuple(r) for r in conn.execute(select(u.c.uid, u.c.tier))] == [(db.LOCAL_UID, "linked")]


def test_game_versions_are_registered_and_hold_the_build(conn: Connection) -> None:
    rows = conn.execute(select(schema.game_versions).order_by(schema.game_versions.c.id)).all()
    assert [(r.id, r.wago_product, r.interface, r.build) for r in rows] == [
        ("forever", "wow_classic_beta", 16001, None),
        ("tbc", "wow_anniversary", 20506, None),
    ]
    db.set_build(conn, "tbc", "2.5.6.1")
    assert (db.get_build(conn, "tbc"), db.get_build(conn, FOREVER)) == ("2.5.6.1", None)


def test_upsert_updates_ignores_or_filters(conn: Connection) -> None:
    t = schema.vendor_items
    keys = ["game_version", "item_id"]
    db.upsert(conn, t, [{"game_version": FOREVER, "item_id": 1}], keys)  # nothing to update: ignored
    db.upsert(
        conn, t, [{"game_version": FOREVER, "item_id": 1}, {"game_version": FOREVER, "item_id": 2}], keys
    )
    db.upsert(conn, t, [], keys)
    assert sorted(conn.execute(select(t.c.item_id)).scalars()) == [1, 2]

    s = schema.user_settings
    skeys = ["user_uid", "game_version"]
    row = {"user_uid": db.LOCAL_UID, "game_version": FOREVER}
    db.upsert(conn, s, [{**row, "data_version": 5}], skeys)
    db.upsert(conn, s, [{**row, "data_version": 3}], skeys, where=s.c.data_version < 4)
    assert conn.execute(select(s.c.data_version)).scalar_one() == 5  # the where clause kept the stored row
    db.upsert(conn, s, [{**row, "data_version": 7}], skeys, where=s.c.data_version < 6)
    assert conn.execute(select(s.c.data_version)).scalar_one() == 7


def test_count_rows(conn: Connection) -> None:
    assert db.count_rows(conn, "items", FOREVER) == 0
    with pytest.raises(ValueError, match="countable"):
        db.count_rows(conn, "characters", FOREVER)  # per user: store.count_characters


def test_timestamps() -> None:
    naive = datetime(2026, 9, 24, 20, 53, 16, 123)
    assert db.utc(naive) == naive.replace(tzinfo=UTC)
    east = datetime(2026, 9, 24, 22, 0, tzinfo=timezone(timedelta(hours=2)))
    assert db.utc(east) == datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
    assert db.timestamp_text(naive) == "2026-09-24 20:53:16"
    assert db.timestamp_text(None) is None


def test_urls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.default_url() == "sqlite:///data/altarmy-profit.sqlite"
    assert db.default_url(tmp_path / "x.sqlite") == f"sqlite:///{(tmp_path / 'x.sqlite').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://me:secret@db.example/prices")
    assert db.default_url() == "postgresql+psycopg://me:secret@db.example/prices"
    hosted = db.Database(db.default_url())
    assert not hosted.is_sqlite
    assert "secret" not in hosted.display_url
    local = db.Database(db.sqlite_url(tmp_path / "x.sqlite"))
    assert local.display_url.endswith("x.sqlite")
    assert not (tmp_path / "x.sqlite").exists()  # nothing touched until first use


def test_a_database_that_does_not_migrate_leaves_the_schema_alone(tmp_path: Path) -> None:
    """Hosted instances don't migrate: the per-deploy migrate job does (`altarmy-profit migrate`)."""
    database = db.Database(db.sqlite_url(tmp_path / "x.sqlite"), migrate=False)
    with database.begin() as conn:
        assert inspect(conn).get_table_names() == []
    database.dispose()


def test_pool_size_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert db.pool_options() == {}
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    assert db.pool_options() == {"pool_size": 3, "max_overflow": 2}
