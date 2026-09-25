from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Connection, select

from altarmy_profit import merge, prices, schema, store
from altarmy_profit.auctionator import DayStats, ItemPrice
from altarmy_profit.prices import Observation

from .conftest import FOREVER

TODAY = date(2026, 9, 24)
NOON = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def daily_medians(conn: Connection, ah: int, item_id: int) -> dict[date, int | None]:
    pd = schema.price_daily
    rows = conn.execute(
        select(pd.c.day, pd.c.median).where(pd.c.auction_house_id == ah, pd.c.item_id == item_id)
    )
    return {r.day: r.median for r in rows}


def seven_day(conn: Connection, ah: int, item_id: int) -> tuple[int | None, int | None, int | None]:
    pc = schema.price_current
    row = conn.execute(
        select(pc.c.median_7d, pc.c.avail_7d, pc.c.scans_7d).where(
            pc.c.auction_house_id == ah, pc.c.item_id == item_id
        )
    ).one()
    return row.median_7d, row.avail_7d, row.scans_7d


def test_median() -> None:
    assert merge.median([5]) == 5
    assert merge.median([1, 9, 3]) == 3
    assert merge.median([100, 201]) == 150  # rounded down to whole copper


def test_daily_median_uses_the_days_scans_within_low_and_high(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.record_daily(conn, ah, {1: ItemPrice(100, {TODAY: DayStats(200, 100, 5)})})
    for hour, price in ((9, 170), (10, 180), (11, 900)):
        at = NOON.replace(hour=hour)
        prices.record_snapshot(conn, ah, "auctionator", at, [Observation(1, price, at)])
    merge.merge_auction_house(conn, ah, TODAY)
    # of low 100, high 200 and the scans 170, 180 and 900 (clamped to 200)
    assert daily_medians(conn, ah, 1) == {TODAY: 180}


def test_seven_day_columns_use_the_items_latest_seven_days_with_data(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    days = {
        TODAY - timedelta(days=40): DayStats(9000, 9000, 1),  # before the lookback
        TODAY - timedelta(days=20): DayStats(9000, 9000, 1),  # an eighth, older day
        # scanned every few days, as one player does
        **{
            TODAY - timedelta(days=n): DayStats(p, p, 4)
            for n, p in ((18, 100), (15, 105), (12, 110), (9, 120))
        },
        TODAY - timedelta(days=6): DayStats(110, 110, 8),
        TODAY - timedelta(days=3): DayStats(130, 130, 5),
        TODAY: DayStats(3_330_000, 3_330_000, 1),  # a lone overpriced listing
    }
    prices.record_daily(conn, ah, {1: ItemPrice(3_330_000, days)})
    prices.record_snapshot(conn, ah, "auctionator", NOON, [Observation(1, 3_330_000, NOON)])
    assert merge.merge_auction_house(conn, ah, TODAY) is True
    # of 100, 105, 110, 120, 110, 130 and 3,330,000; availability of 4, 4, 4, 4, 8, 5, 1
    assert seven_day(conn, ah, 1) == (110, 4, 7)


def test_items_without_recent_days_get_no_seven_day_values(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    old = TODAY - timedelta(days=30)
    prices.record_daily(conn, ah, {1: ItemPrice(50, {old: DayStats(50, 50, 2)})})
    prices.record_snapshot(conn, ah, "manual", NOON, [Observation(1, 50, NOON)])
    merge.merge_auction_house(conn, ah, TODAY)
    assert seven_day(conn, ah, 1) == (None, None, None)


def test_merge_bumps_the_price_version_only_when_something_changed(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.record_daily(conn, ah, {1: ItemPrice(100, {TODAY: DayStats(100, 100, 1)})})
    prices.record_snapshot(conn, ah, "auctionator", NOON, [Observation(1, 100, NOON)])
    before = store.market_stamp(conn, FOREVER, ah)
    assert merge.merge_auction_house(conn, ah, TODAY) is True
    after = store.market_stamp(conn, FOREVER, ah)
    assert after != before
    assert merge.merge_auction_house(conn, ah, TODAY) is False
    assert store.market_stamp(conn, FOREVER, ah) == after


def test_merge_covers_every_auction_house_of_the_version(conn: Connection) -> None:
    a = prices.auction_house(conn, FOREVER, "A", "")
    b = prices.auction_house(conn, FOREVER, "B", "")
    tbc = prices.auction_house(conn, "tbc", "C", "")
    for ah in (a, b, tbc):
        prices.record_daily(conn, ah, {1: ItemPrice(100, {TODAY: DayStats(100, 100, 1)})})
        prices.record_snapshot(conn, ah, "auctionator", NOON, [Observation(1, 100, NOON)])
    assert merge.merge(conn, FOREVER, today=TODAY) == {a: True, b: True}
    assert seven_day(conn, tbc, 1) == (None, None, None)


def test_quarantined_snapshots_do_not_count(conn: Connection) -> None:
    ah = prices.unnamed_auction_house(conn, FOREVER)
    prices.record_daily(conn, ah, {1: ItemPrice(100, {TODAY: DayStats(200, 100, 1)})})
    at = NOON.replace(hour=9)
    prices.record_snapshot(conn, ah, "auctionator", at, [Observation(1, 150, at)])
    snap = schema.price_snapshots
    bad: int = conn.execute(
        snap.insert()
        .values(
            auction_house_id=ah,
            source="auctionator",
            scanned_at=NOON,
            received_at=NOON,
            item_count=1,
            status="quarantined",
        )
        .returning(snap.c.id)
    ).scalar_one()
    conn.execute(schema.price_observations.insert().values(snapshot_id=bad, item_id=1, min_buyout=200))
    merge.merge_auction_house(conn, ah, TODAY)
    assert daily_medians(conn, ah, 1) == {TODAY: 150}  # of 100, 200 and 150 only
