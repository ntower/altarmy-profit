"""Uploaded addon files: characters replace the uploader's, prices pool per auction house."""

import gzip
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select

from altarmy_profit import prices, schema, service, store, uploads, users
from altarmy_profit.auth import User

from .conftest import FOREVER, ME
from .test_altarmy import ALTARMY_SV
from .test_auctionator import _entry, _saved_variables

NOW = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
OTHER = "other-user"


@pytest.fixture
def other(conn: Connection) -> str:
    users.ensure_user(conn, User(OTHER, "free"))
    return OTHER


def scan(realms: dict[str, dict[str, object]]) -> bytes:
    return _saved_variables(realms)


def test_altarmy_upload_replaces_only_the_uploaders_characters(conn: Connection, other: str) -> None:
    store.save_characters(conn, other, FOREVER, store.load_characters(conn, ME, FOREVER))  # nothing yet
    got = uploads.ingest(conn, ME, FOREVER, "altarmy", ALTARMY_SV, None, now=NOW)
    assert got.characters == 4
    assert got.groups == (
        ("Classic Beta PvE", "Alliance", 1),
        ("Classic Beta PvE", "Horde", 1),
        ("Dreamscythe", "Horde", 2),
    )
    assert "4 characters" in got.detail
    assert store.count_characters(conn, ME, FOREVER) == 4
    assert store.count_characters(conn, other, FOREVER) == 0
    assert service.data_version(conn, ME, FOREVER) == 1


def test_auctionator_upload_records_every_realm_named_like_the_characters(conn: Connection) -> None:
    uploads.ingest(conn, ME, FOREVER, "altarmy", ALTARMY_SV, None, now=NOW)
    data = scan({"ClassicBetaPvE": {"1": _entry(20)}, "Dreamscythe Horde": {"1": _entry(5)}, "Empty": {}})
    got = uploads.ingest(conn, ME, FOREVER, "auctionator", data, NOW - timedelta(hours=1), now=NOW)
    names = [(r.key, r.realm, r.faction, r.items) for r in got.realms]
    assert names == [
        ("ClassicBetaPvE", "Classic Beta PvE", "", 1),  # Forever's shared auction house
        ("Dreamscythe Horde", "Dreamscythe", "Horde", 1),
    ]
    assert len(got.auction_house_ids) == 2
    assert prices.find_auction_house(conn, FOREVER, "Empty", "") is None  # realms without prices are skipped
    assert prices.load_current(conn, service.selected_auction_house(conn, ME, FOREVER)) == {1: 5}
    snap = schema.price_snapshots
    assert set(conn.execute(select(snap.c.uploader_uid)).scalars()) == {ME}
    assert service.data_version(conn, ME, FOREVER) == 2


def test_prices_before_characters_still_price_them(conn: Connection) -> None:
    uploads.ingest(
        conn, ME, FOREVER, "auctionator", scan({"ClassicBetaPvE": {"1": _entry(20)}}), None, now=NOW
    )
    uploads.ingest(conn, ME, FOREVER, "altarmy", ALTARMY_SV, None, now=NOW)
    service.select(conn, ME, FOREVER, "Classic Beta PvE", "Horde")
    ah = service.selected_auction_house(conn, ME, FOREVER)
    assert ah is not None and prices.load_current(conn, ah) == {1: 20}  # found through the alias
    # a later scan lands on the same auction house, not a second one named like the characters
    uploads.ingest(
        conn, ME, FOREVER, "auctionator", scan({"ClassicBetaPvE": {"1": _entry(25)}}), None, now=NOW
    )
    assert prices.load_current(conn, ah) == {1: 25}
    assert len(prices.auction_houses(conn, FOREVER)) == 1


def test_uploads_pool_and_the_newest_scan_wins(conn: Connection, other: str) -> None:
    def latest(price: int) -> bytes:  # no day history: seen at the file's scan time
        return scan({"Dreamscythe Horde": {"1": {"m": price}}})

    uploads.ingest(conn, ME, FOREVER, "auctionator", latest(5), NOW - timedelta(hours=2), now=NOW)
    uploads.ingest(conn, other, FOREVER, "auctionator", latest(9), NOW - timedelta(hours=1), now=NOW)
    ah = prices.find_auction_house(conn, FOREVER, "Dreamscythe", "Horde")
    assert prices.load_current(conn, ah) == {1: 9}  # another user's newer scan
    uploads.ingest(conn, ME, FOREVER, "auctionator", latest(7), NOW - timedelta(hours=3), now=NOW)
    assert prices.load_current(conn, ah) == {1: 9}  # an older file doesn't win


def test_a_wildly_off_scan_is_quarantined_and_costs_trust(conn: Connection, other: str) -> None:
    def latest(price: int) -> bytes:
        return scan({"Dreamscythe Horde": {str(i): {"m": price} for i in range(1, 31)}})

    uploads.ingest(conn, ME, FOREVER, "auctionator", latest(100), NOW - timedelta(hours=2), now=NOW)
    ah = prices.find_auction_house(conn, FOREVER, "Dreamscythe", "Horde")
    pc = schema.price_current
    conn.execute(pc.update().values(median_7d=100, scans_7d=5))  # as the merge job would

    got = uploads.ingest(
        conn, other, FOREVER, "auctionator", latest(10_000), NOW - timedelta(hours=1), now=NOW
    )
    (realm,) = got.realms
    assert realm.quarantined and realm.moved == 0
    assert got.detail == "Dreamscythe Horde: 30 prices not used: they differ widely from recent scans"
    assert set(prices.load_current(conn, ah).values()) == {100}
    assert users.trust(conn, other) == 0.5

    got = uploads.ingest(conn, ME, FOREVER, "auctionator", latest(110), NOW, now=NOW)
    assert not got.realms[0].quarantined
    assert users.trust(conn, ME) == 1.0  # capped


def test_trust_halves_on_quarantine_and_recovers(conn: Connection, other: str) -> None:
    assert users.trust(conn, other) == 1.0
    assert users.adjust_trust(conn, other, quarantined=True) == 0.5
    assert users.adjust_trust(conn, other, quarantined=True) == 0.25
    assert users.adjust_trust(conn, other, quarantined=False) == pytest.approx(0.35)
    assert users.trust(conn, "nobody") == 1.0


def test_scan_time_is_clamped() -> None:
    assert uploads.scan_time(None, NOW) == NOW
    assert uploads.scan_time(NOW + timedelta(days=1), NOW) == NOW
    assert uploads.scan_time(NOW - timedelta(days=90), NOW) == NOW - uploads.SCAN_WINDOW
    assert uploads.scan_time(NOW - timedelta(hours=1), NOW) == NOW - timedelta(hours=1)


def test_bad_files_raise_value_error(conn: Connection) -> None:
    with pytest.raises(ValueError, match="AltArmyTBC_Data"):
        uploads.ingest(conn, ME, FOREVER, "altarmy", b"Foo = {}", None, now=NOW)
    with pytest.raises(ValueError, match="AUCTIONATOR_PRICE_DATABASE"):
        uploads.ingest(conn, ME, FOREVER, "auctionator", ALTARMY_SV, None, now=NOW)


def test_history_and_rate_limit(conn: Connection) -> None:
    for i in range(uploads.RATE_LIMIT):
        uploads.check_rate(conn, ME, now=NOW)
        uploads.record_upload(conn, ME, FOREVER, "altarmy", "browser", 10, "accepted", f"#{i}", now=NOW)
    with pytest.raises(uploads.RateLimited):
        uploads.check_rate(conn, ME, now=NOW)
    uploads.check_rate(conn, ME, now=NOW + timedelta(hours=1, seconds=1))  # an hour later
    recent = uploads.recent(conn, ME)
    assert len(recent) == 20 and recent[0].detail.startswith("#")
    assert uploads.recent(conn, "local-nobody") == []


def test_decompress_limits_the_size() -> None:
    assert uploads.decompress(gzip.compress(b"x" * 100), 1000) == b"x" * 100
    assert uploads.decompress(b"plain", 1000) == b"plain"
    with pytest.raises(uploads.TooLarge):
        uploads.decompress(gzip.compress(b"x" * 5000), 1000)
    with pytest.raises(uploads.TooLarge):
        uploads.decompress(b"y" * 5000, 1000)
    with pytest.raises(ValueError, match="gzip"):
        uploads.decompress(b"\x1f\x8b" + b"not gzip", 1000)
