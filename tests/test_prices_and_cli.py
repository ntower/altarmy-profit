from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Connection, func, select

from altarmy_profit import cli, db, ingest, prices, schema, store, versions
from altarmy_profit.auctionator import DayStats, ItemPrice
from altarmy_profit.prices import Observation

from .conftest import FOREVER, SV_DIR, set_prices, write_csv

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def count(conn: Connection, table: str) -> int:
    return int(conn.execute(select(func.count()).select_from(schema.metadata.tables[table])).scalar_one())


def test_import_csv_by_id_and_name(db2_paths: dict[str, Path], conn: Connection, tmp_path: Path) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    ingest.build_db(db2_paths, conn, "tbc")
    f = write_csv(
        tmp_path / "prices.csv",
        ["item_id", "name", "price"],
        [
            {"item_id": 1, "price": 45},
            {"item_id": "", "name": "coarse thread", "price": 120},  # case-insensitive
            {"item_id": "", "name": "Nonexistent Item", "price": 9},
        ],
    )
    ah = prices.unnamed_auction_house(conn, FOREVER)
    imported, unresolved = prices.import_csv(conn, FOREVER, ah, f)
    assert imported == 2
    assert unresolved == ["Nonexistent Item"]
    assert prices.load_current(conn, ah) == {1: 45, 2: 120}
    snap = schema.price_snapshots
    assert conn.execute(select(snap.c.source, snap.c.item_count)).all() == [("csv", 2)]


def test_set_price_records_manual_snapshots(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.set_price(conn, ah, 1, 10)
    prices.set_price(conn, ah, 1, 20)
    assert prices.load_current(conn, ah) == {1: 20}
    assert count(conn, "price_snapshots") == 2
    assert count(conn, "price_observations") == 2
    assert prices.last_import(conn, ah) is None  # no Auctionator scan
    assert prices.last_import(conn, ah, "manual") is not None
    assert prices.count_current(conn, ah) == 1
    assert (prices.count_current(conn, None), prices.load_current(conn, None)) == (0, {})


def test_snapshots_only_record_news(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    scan = [Observation(1, 100, T0, 5), Observation(2, 50, T0)]
    assert prices.record_snapshot(conn, ah, "auctionator", T0, scan) == 2
    assert prices.record_snapshot(conn, ah, "auctionator", T0 + timedelta(hours=1), scan) == 0  # same scan
    assert count(conn, "price_snapshots") == 2  # both arrivals are on record
    assert count(conn, "price_observations") == 2

    later = T0 + timedelta(hours=2)
    moved = [Observation(1, 90, later), Observation(2, 50, T0)]  # item 1 got cheaper, 2 unchanged
    assert prices.record_snapshot(conn, ah, "auctionator", later, moved) == 1
    next_day = T0 + timedelta(days=1)
    assert prices.record_snapshot(conn, ah, "auctionator", next_day, [Observation(2, 50, next_day)]) == 1
    assert prices.load_current(conn, ah) == {1: 90, 2: 50}

    older = [Observation(1, 999, T0 - timedelta(days=3))]  # an old upload never beats a newer price
    assert prices.record_snapshot(conn, ah, "auctionator", T0 - timedelta(days=3), older) == 0
    assert prices.load_current(conn, ah) == {1: 90, 2: 50}
    pc = schema.price_current
    seen: datetime = conn.execute(select(pc.c.seen_at).where(pc.c.item_id == 2)).scalar_one()
    assert db.utc(seen) == next_day


def test_manual_price_holds_until_a_newer_scan(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.record_snapshot(conn, ah, "auctionator", T0, [Observation(1, 100, T0)])
    prices.set_price(conn, ah, 1, 70)  # now: after the scan
    assert prices.load_current(conn, ah) == {1: 70}
    prices.record_snapshot(conn, ah, "auctionator", T0, [Observation(1, 100, T0)])  # the same old scan again
    assert prices.load_current(conn, ah) == {1: 70}
    fresh = db.utcnow() + timedelta(days=1)
    prices.record_snapshot(conn, ah, "auctionator", fresh, [Observation(1, 80, fresh)])
    assert prices.load_current(conn, ah) == {1: 80}


def test_auctionator_observations_use_each_items_last_day() -> None:
    scan = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    today = scan.astimezone().date()
    earlier = today - timedelta(days=3)
    got = prices.auctionator_observations(
        {
            1: ItemPrice(100, {today: DayStats(120, 100, 7), earlier: DayStats(90, 90, 2)}),
            2: ItemPrice(50, {earlier: DayStats(60, 50, 4)}),
            3: ItemPrice(10),  # no history left
        },
        scan,
    )
    assert got == [
        Observation(1, 100, scan, 7),
        Observation(2, 50, datetime.combine(earlier, datetime.min.time(), UTC), 4),
        Observation(3, 10, scan, None),
    ]


def test_record_daily_backfills_then_updates_from_the_newest_day(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    d1, d2, d3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)
    first = {1: ItemPrice(100, {d1: DayStats(120, 100, 7), d2: DayStats(110, 105, 3)})}
    assert prices.record_daily(conn, ah, first) == 2
    # Auctionator later rewrites d1 (ignored: before the newest stored day), d2 (moved on) and adds d3
    second = {1: ItemPrice(90, {d1: DayStats(1, 1, 1), d2: DayStats(115, 95, 4), d3: DayStats(90, 90, None)})}
    assert prices.record_daily(conn, ah, second) == 2
    assert prices.daily(conn, ah, 1) == [(d1, 100, 120, 7), (d2, 95, 115, 4), (d3, 90, 90, None)]


def test_record_daily_pools_uploaders_days(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    d = date(2026, 9, 2)
    prices.record_daily(conn, ah, {1: ItemPrice(100, {d: DayStats(120, 100, 7)})})
    prices.record_daily(conn, ah, {1: ItemPrice(90, {d: DayStats(110, 90, 3)})})  # another uploader
    assert prices.daily(conn, ah, 1) == [(d, 90, 120, 7)]
    prices.record_daily(conn, ah, {1: ItemPrice(100, {d: DayStats(120, 100, 7)})})  # sent again
    assert prices.daily(conn, ah, 1) == [(d, 90, 120, 7)]


def fresh(prices_by_item: dict[int, int], at: datetime = T0) -> list[Observation]:
    return [Observation(i, p, at) for i, p in prices_by_item.items()]


def test_screen_needs_enough_comparable_items() -> None:
    baseline = dict.fromkeys(range(19), 100)
    wild = fresh(dict.fromkeys(range(19), 10000))
    assert prices.screen(wild, baseline, T0, trust=1.0) is None
    stale = fresh(dict.fromkeys(range(40), 10000), at=T0 - timedelta(days=2))  # not seen on the scan day
    assert prices.screen(stale, dict.fromkeys(range(40), 100), T0, trust=1.0) is None


def test_screen_quarantines_when_many_prices_are_wild() -> None:
    baseline = dict.fromkeys(range(100), 100)
    scan = dict.fromkeys(range(100), 100)
    assert prices.screen(fresh(scan), baseline, T0, trust=1.0) is False
    for i in range(20):  # 20% more than 4x off: fine for a trusted uploader, not for a distrusted one
        scan[i] = 401 if i % 2 else 24
    assert prices.screen(fresh(scan), baseline, T0, trust=1.0) is False
    assert prices.screen(fresh(scan), baseline, T0, trust=0.25) is True
    for i in range(40):
        scan[i] = 10_000
    assert prices.screen(fresh(scan), baseline, T0, trust=1.0) is True


def test_screened_auctionator_scan_is_quarantined(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    day = T0.astimezone().date()
    history = {
        i: ItemPrice(100, {day - timedelta(days=n): DayStats(100, 100, 5) for n in range(1, 4)})
        for i in range(1, 31)
    }
    earlier = T0 - timedelta(days=1)
    prices.record_auctionator(conn, ah, history, earlier)
    pc = schema.price_current
    conn.execute(pc.update().values(median_7d=100, scans_7d=3))  # as the merge job would
    scaled = {i: ItemPrice(10_000, {day: DayStats(10_000, 10_000, 5)}) for i in range(1, 31)}

    got = prices.record_auctionator(conn, ah, scaled, T0, uploader_uid="u1", trust=1.0)
    assert got == prices.Recorded(moved=0, quarantined=True, screened=True)
    snap = schema.price_snapshots
    assert conn.execute(select(snap.c.status).order_by(snap.c.id)).scalars().all() == [
        "accepted",
        "quarantined",
    ]
    assert set(prices.load_current(conn, ah).values()) == {100}  # nothing moved
    assert prices.daily(conn, ah, 1)[-1][0] == day - timedelta(days=1)  # no daily rows either

    unscreened = prices.record_auctionator(conn, ah, scaled, T0)  # the local sync is not screened
    assert unscreened == prices.Recorded(moved=30)


def test_load_prices_sells_at_the_lower_of_now_and_the_median(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.record_snapshot(
        conn,
        ah,
        "auctionator",
        T0,
        [Observation(1, 3_330_000, T0), Observation(2, 80, T0), Observation(3, 5, T0)],
    )
    prices.set_price(conn, ah, 4, 500)
    pc = schema.price_current
    for item_id, median in ((1, 4900), (2, 100), (4, 50)):
        conn.execute(pc.update().where(pc.c.item_id == item_id).values(median_7d=median))
    buy, sell = prices.load_buy_and_sell(conn, ah)
    assert buy == {1: 3_330_000, 2: 80, 3: 5, 4: 500}
    # a lone overpriced listing sells at the median; below it, at the price; no median, the price; a price
    # set by hand is used as it is
    assert sell == {1: 4900, 2: 80, 3: 5, 4: 500}
    assert prices.load_buy_and_sell(conn, None) == ({}, {})


def test_prune_keeps_what_price_current_points_at(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    old = T0 - timedelta(days=100)
    prices.record_snapshot(conn, ah, "auctionator", old, [Observation(1, 10, old), Observation(2, 20, old)])
    prices.record_snapshot(conn, ah, "auctionator", old, [Observation(3, 30, old)])
    prices.record_snapshot(conn, ah, "auctionator", T0, [Observation(1, 11, T0), Observation(3, 31, T0)])
    prices.prune(conn, now=T0)
    snap = schema.price_snapshots
    assert conn.execute(select(func.count()).select_from(snap)).scalar_one() == 2  # item 2's old one stays
    assert count(conn, "price_observations") == 2  # only the fresh snapshot's
    assert prices.load_current(conn, ah) == {1: 11, 2: 20, 3: 31}


def test_auction_houses_split_or_shared(conn: Connection) -> None:
    shared = prices.auctionator_auction_house(conn, FOREVER, "ClassicBetaPvE", "Classic Beta PvE", "Horde")
    assert prices.find_auction_house(conn, FOREVER, "Classic Beta PvE", "Alliance") == shared
    split = prices.auctionator_auction_house(conn, "tbc", "Dreamscythe Horde", "Dreamscythe", "Horde")
    assert prices.find_auction_house(conn, "tbc", "Dreamscythe", "Horde") == split
    assert prices.find_auction_house(conn, "tbc", "Dreamscythe", "Alliance") is None
    assert prices.find_auction_house(conn, FOREVER, "Dreamscythe", "Horde") is None  # per version
    assert prices.auction_house_for_auctionator_key(conn, "tbc", "Dreamscythe Horde") == split  # an alias
    assert prices.auctionator_auction_house(conn, FOREVER, "ClassicBetaPvE", "Classic Beta PvE", "") == shared
    assert count(conn, "realm_aliases") == 2


def test_load_market_ranks_end_to_end(db2_paths: dict[str, Path], conn: Connection) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    ah = set_prices(conn, {1: 20, 2: 100})  # linen, thread
    market = store.load_market(conn, FOREVER, ah)
    (result,) = market.rank()
    assert result.cost == 300
    assert result.profit == 200  # vendors for 500
    assert result.best_exit == "vendor"


def test_find_auctionator_files(tmp_path: Path) -> None:
    sv = tmp_path / "_classic_beta_" / "WTF" / "Account" / "ME" / "SavedVariables"
    sv.mkdir(parents=True)
    (sv / "Auctionator.lua").write_text("")
    (sv / "Other.lua").write_text("")
    assert prices.find_auctionator_files([tmp_path, tmp_path / "missing"]) == [sv / "Auctionator.lua"]


def test_find_altarmy_files(wow_root: Path) -> None:
    assert prices.find_altarmy_files([wow_root]) == [wow_root / SV_DIR / "AltArmy_TBC.lua"]


def test_cli_import_altarmy_and_rank_by_realm(
    db2_paths: dict[str, Path], tmp_path: Path, wow_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dbfile = str(tmp_path / "cli.sqlite")
    database = db.Database(db.sqlite_url(dbfile))
    with database.begin() as conn:
        ingest.build_db(db2_paths, conn, FOREVER)
        set_prices(conn, {1: 20, 2: 100})
    database.dispose()
    cli.main(["--db", dbfile, "import-altarmy", str(wow_root / SV_DIR / "AltArmy_TBC.lua")])
    assert "Classic Beta PvE (Horde): Tailor Guy" in capsys.readouterr().out

    cli.main(["--db", dbfile, "rank", "--realm", "Dreamscythe", "--faction", "Horde"])
    assert "No profitable recipes" in capsys.readouterr().out
    cli.main(["--db", dbfile, "rank", "--realm", "Classic Beta PvE", "--faction", "Horde"])
    out = capsys.readouterr().out
    assert "Characters: Tailor Guy" in out
    assert "Green Robe" in out
    cli.main(["--db", dbfile, "rank"])  # remembers the realm and faction
    assert "Green Robe" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="both"):
        cli.main(["--db", dbfile, "rank", "--realm", "Dreamscythe"])


def test_cli_prices_go_to_the_selected_auction_house(
    tmp_path: Path, wow_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dbfile = str(tmp_path / "cli.sqlite")
    cli.main(["--db", dbfile, "set-price", "1", "45"])  # no characters: the unnamed auction house
    cli.main(["--db", dbfile, "import-altarmy", str(wow_root / SV_DIR / "AltArmy_TBC.lua")])
    with pytest.raises(SystemExit, match="No auction house known for Dreamscythe"):
        cli.main(["--db", dbfile, "set-price", "1", "50"])
    f = write_csv(tmp_path / "p.csv", ["item_id", "price"], [{"item_id": 2, "price": 7}])
    with pytest.raises(SystemExit, match="No auction house known"):
        cli.main(["--db", dbfile, "import-prices", str(f)])
    auctionator = str(wow_root / SV_DIR / "Auctionator.lua")
    cli.main(["--db", dbfile, "import-auctionator", auctionator, "--realm", "Dreamscythe Horde"])
    cli.main(["--db", dbfile, "set-price", "1", "50"])
    cli.main(["--db", dbfile, "import-prices", str(f)])
    database = db.Database(db.sqlite_url(dbfile))
    with database.begin() as conn:
        unnamed = prices.find_auction_house(conn, FOREVER, "", "")
        horde = prices.find_auction_house(conn, FOREVER, "Dreamscythe", "Horde")
        assert (prices.load_current(conn, unnamed), prices.load_current(conn, horde)) == (
            {1: 45},
            {1: 50, 2: 7},
        )
    database.dispose()


def test_ui_serves_api_with_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn
    from fastapi import FastAPI

    calls: list[tuple[object, str, int]] = []

    def fake_run(app: object, host: str, port: int) -> None:
        calls.append((app, host, port))

    monkeypatch.setattr(uvicorn, "run", fake_run)
    cli.main(["--db", str(tmp_path / "x.sqlite"), "ui", "--port", "9123", "--no-browser"])
    ((app, host, port),) = calls
    assert isinstance(app, FastAPI)
    assert (host, port) == ("127.0.0.1", 9123)


def test_cli_imports_old_version_files_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from altarmy_profit import legacy

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    old = legacy.version_file("tbc", Path("data"))
    old.parent.mkdir()
    conn = legacy.connect(old)
    legacy.init_schema(conn)
    conn.execute("INSERT INTO meta VALUES ('build', '2.5.6.1')")
    conn.commit()
    conn.close()
    cli.main(["set-price", "1", "45"])
    assert "Imported data" in capsys.readouterr().out
    cli.main(["set-price", "1", "45"])
    assert "Imported" not in capsys.readouterr().out
    assert Path("data/altarmy-profit.sqlite").is_file()
    assert Path("data/altarmy-profit-tbc.db.imported").is_file()


def test_cli_ingest_uses_the_game_versions_build_and_product(
    db2_paths: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builds: list[str] = []

    def download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        builds.append(build)
        return db2_paths

    monkeypatch.setattr(ingest, "download_all", download_all)
    monkeypatch.setattr(ingest, "latest_build", lambda product: {"wow_anniversary": "2.5.7.1"}[product])
    dbfile = str(tmp_path / "t.sqlite")
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest"])
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest", "--build", "latest"])
    assert builds == [versions.VERSIONS["tbc"].default_build, "2.5.7.1"]
    assert "Ingested TBC Anniversary build 2.5.7.1" in capsys.readouterr().out
    database = db.Database(db.sqlite_url(dbfile))
    with database.begin() as conn:
        assert (db.get_build(conn, "tbc"), db.get_build(conn, FOREVER)) == ("2.5.7.1", None)
    database.dispose()


def test_cli_skips_old_version_files_with_a_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Hosted jobs set DATABASE_URL: the legacy import (local SQLite files) must never run there."""
    from altarmy_profit import legacy

    monkeypatch.chdir(tmp_path)
    old = legacy.version_file("tbc", Path("data"))
    old.parent.mkdir()
    conn = legacy.connect(old)
    legacy.init_schema(conn)
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_URL", db.sqlite_url(tmp_path / "hosted.sqlite"))
    cli.main(["set-price", "1", "45"])
    assert "Imported" not in capsys.readouterr().out
    assert old.is_file()


def test_cli_migrate_prune_and_merge(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dbfile = str(tmp_path / "m.sqlite")
    cli.main(["--db", dbfile, "migrate"])
    assert "Database at revision" in capsys.readouterr().out
    cli.main(["--db", dbfile, "set-price", "1", "45"])
    cli.main(["--db", dbfile, "prune"])
    assert "Pruned" in capsys.readouterr().out
    cli.main(["--db", dbfile, "merge"])
    assert "Merged 1 auction houses of every game version (0 changed); 1 price observations stored." in (
        capsys.readouterr().out
    )


def test_cli_ingest_only_if_new_skips_a_loaded_build(
    db2_paths: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    builds: list[str] = []

    def download_all(build: str, cache_dir: Path) -> dict[str, Path]:
        builds.append(build)
        return db2_paths

    monkeypatch.setattr(ingest, "download_all", download_all)
    monkeypatch.setattr(ingest, "latest_build", lambda product: "2.5.7.1")
    dbfile = str(tmp_path / "t.sqlite")
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest", "--only-if-new"])
    assert "Ingested TBC Anniversary build 2.5.7.1" in capsys.readouterr().out
    cli.main(["--game-version", "tbc", "--db", dbfile, "ingest", "--only-if-new"])
    assert "already loaded" in capsys.readouterr().out
    assert builds == ["2.5.7.1"]
