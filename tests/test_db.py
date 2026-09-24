from pathlib import Path

from wowprofit import db


def test_init_schema_adds_new_item_columns_to_an_old_database(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, quality INTEGER NOT NULL DEFAULT 1,"
        " item_level INTEGER NOT NULL DEFAULT 0, required_level INTEGER NOT NULL DEFAULT 0,"
        " class_id INTEGER NOT NULL DEFAULT 0, subclass_id INTEGER NOT NULL DEFAULT 0,"
        " sell_price INTEGER NOT NULL DEFAULT 0, buy_price INTEGER NOT NULL DEFAULT 0,"
        " bonding INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT INTO items (id, name) VALUES (1, 'Linen Cloth')")
    conn.commit()

    db.init_schema(conn)
    db.init_schema(conn)  # idempotent

    row = conn.execute("SELECT * FROM items").fetchone()
    assert row["name"] == "Linen Cloth"
    assert (row["inventory_type"], row["item_delay"], row["icon"], row["description"]) == (0, 0, None, None)
    conn.close()
