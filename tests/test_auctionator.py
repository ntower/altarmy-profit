import contextlib
import random
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Connection, select

from altarmy_profit import altarmy, auctionator, cli, ingest, prices, schema
from altarmy_profit.auctionator import DayStats, ItemPrice

from .test_altarmy import ALTARMY_SV

FOREVER = "forever"  # (conftest imports this module, so it can't import conftest's)


def _cbor_head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    if n < 0x100:
        return bytes([major << 5 | 24, n])
    if n < 0x10000:
        return bytes([major << 5 | 25]) + n.to_bytes(2, "big")
    return bytes([major << 5 | 26]) + n.to_bytes(4, "big")


def _cbor(v: object) -> bytes:
    """Just enough CBOR encoding to mimic Auctionator (keys are byte strings, like the addon writes)."""
    if isinstance(v, int):
        return _cbor_head(0, v)
    if isinstance(v, str):
        b = v.encode()
        return _cbor_head(2, len(b)) + b
    if isinstance(v, list):
        return _cbor_head(4, len(v)) + b"".join(_cbor(x) for x in v)
    assert isinstance(v, dict)
    return _cbor_head(5, len(v)) + b"".join(_cbor(k) + _cbor(x) for k, x in v.items())


def _lua_escape(b: bytes) -> bytes:
    out = bytearray()
    for c in b:
        if c == 0x22:
            out += b'\\"'
        elif c == 0x5C:
            out += b"\\\\"
        elif c == 0x0A:
            out += b"\\n"
        elif c == 0x0D:
            out += b"\\r"
        elif c == 0:
            out += b"\\000"
        else:
            out.append(c)
    return bytes(out)


def _saved_variables(realms: dict[str, dict[str, object]]) -> bytes:
    lines = [b"", b"AUCTIONATOR_CONFIG = {", b'["x"] = "y",', b"}", b"AUCTIONATOR_PRICE_DATABASE = {"]
    lines.append(b'["__dbversion"] = 8,')
    for realm, data in realms.items():
        lines.append(b'["' + realm.encode() + b'"] = "' + _lua_escape(_cbor(data)) + b'",')
    lines += [b"}", b"AUCTIONATOR_POSTING_HISTORY = {", b"}", b""]
    return b"\n".join(lines)


def _entry(price: int) -> dict[str, object]:
    return {"a": {"2457": 3}, "l": [], "h": {"2457": price}, "m": price}


def test_parse_price_database_handles_escapes_and_key_kinds() -> None:
    realm = {
        "version": 1,
        "1": _entry(45),
        "2": _entry(0x0A0D),  # bytes that Lua escapes as \n and \r
        "3": _entry(0x2200),  # a quote and a NUL
        "g:4:0:0": _entry(300),  # gear keyed with item level: counts as item 4
        "g:4:60:0": _entry(250),  # cheapest variant wins
        "p:39": _entry(999),  # battle pet: ignored
    }
    parsed = auctionator.parse_price_database(
        _saved_variables({"Realm A": realm, "Realm B": {"1": _entry(7)}})
    )
    buyouts = {realm: auctionator.min_buyouts(items) for realm, items in parsed.items()}
    assert buyouts == {"Realm A": {1: 45, 2: 0x0A0D, 3: 0x2200, 4: 250}, "Realm B": {1: 7}}


def test_parse_keeps_the_daily_history() -> None:
    realm: dict[str, object] = {
        # day 2457 = 2026-09-23: seen at 900 then 700 (l only holds a low below h); 2458: once, 800
        "1": {"a": {"2457": 12, "2458": 5}, "l": {"2457": 700}, "h": {"2457": 900, "2458": 800}, "m": 800},
        "2": {"l": [], "h": {"1866": 40}, "m": 40},  # no "a": databases from before December 2020
        "3": {"a": [], "l": [], "h": [], "m": 55},  # no history left (Auctionator prunes old days)
        # gear variants: cheapest m; per day the highest high, lowest low and the summed availability
        "g:4:0:0": {"a": {"2458": 1}, "l": [], "h": {"2458": 300}, "m": 300},
        "g:4:60:0": {"a": {"2458": 2}, "l": {"2458": 200}, "h": {"2458": 260}, "m": 250},
    }
    got = auctionator.parse_price_database(_saved_variables({"R": realm}))["R"]
    assert got[1] == ItemPrice(
        800, {date(2026, 9, 23): DayStats(900, 700, 12), date(2026, 9, 24): DayStats(800, 800, 5)}
    )
    assert got[1].last_seen == date(2026, 9, 24)
    assert got[2] == ItemPrice(40, {date(2025, 2, 9): DayStats(40, 40, None)})
    assert (got[3], got[3].last_seen) == (ItemPrice(55), None)
    assert got[4] == ItemPrice(250, {date(2026, 9, 24): DayStats(300, 200, 3)})


def test_parse_rejects_file_without_price_database() -> None:
    with pytest.raises(ValueError, match="AUCTIONATOR_PRICE_DATABASE"):
        auctionator.parse_price_database(b"AUCTIONATOR_CONFIG = {\n}\n")


def test_import_auctionator(db2_paths: dict[str, Path], conn: Connection, tmp_path: Path) -> None:
    ingest.build_db(db2_paths, conn, FOREVER)
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"Only Realm": {"1": _entry(45), "999999": _entry(5)}}))
    realm, imported, unknown = prices.import_auctionator(conn, FOREVER, f)
    assert (realm, imported, unknown) == ("Only Realm", 2, 1)
    ah = prices.auction_house_for_auctionator_key(conn, FOREVER, "Only Realm")
    assert prices.load_current(conn, ah) == {1: 45, 999999: 5}
    snap = schema.price_snapshots
    assert conn.execute(select(snap.c.source, snap.c.item_count)).all() == [("auctionator", 2)]
    assert prices.daily(conn, ah, 1) == [(date(2026, 9, 23), 45, 45, 3)]


def test_import_auctionator_needs_realm_when_ambiguous(conn: Connection, tmp_path: Path) -> None:
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"A Horde": {"1": _entry(1)}, "B": {"1": _entry(2)}}))
    with pytest.raises(ValueError, match="A Horde, B"):
        prices.import_auctionator(conn, FOREVER, f)
    assert prices.import_auctionator(conn, FOREVER, f, realm="B")[:2] == ("B", 1)
    assert prices.import_auctionator(conn, FOREVER, f, realm="A Horde")[:2] == ("A Horde", 1)
    b = prices.find_auction_house(conn, FOREVER, "B", "Alliance")  # shared: no faction in the key
    a = prices.find_auction_house(conn, FOREVER, "A", "Horde")  # split by faction
    assert b is not None and a is not None
    assert prices.find_auction_house(conn, FOREVER, "A", "Alliance") is None
    assert (prices.load_current(conn, b), prices.load_current(conn, a)) == ({1: 2}, {1: 1})


def test_cli_import_auctionator(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"R": {"1": _entry(45)}}))
    dbfile = tmp_path / "t.sqlite"
    cli.main(["--db", str(dbfile), "import-auctionator", str(f)])
    assert "Imported 1 prices from realm R" in capsys.readouterr().out


@pytest.mark.parametrize(
    "blob",
    [
        bytes([0x81]) * 5000 + b"\x00",  # arrays nested 5000 deep
        _cbor({"1": _entry(5)})[:-3],  # truncated
        bytes([0xA1, 0x01, 0xF8]),  # a simple value Auctionator never writes
    ],
    ids=["deep", "truncated", "unknown-simple"],
)
def test_malformed_cbor_is_a_value_error(blob: bytes) -> None:
    text = b'AUCTIONATOR_PRICE_DATABASE = {\n["Realm"] = "' + _lua_escape(blob) + b'",\n}\n'
    with pytest.raises(ValueError):
        auctionator.parse_price_database(text)


def test_truncated_lua_table_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        auctionator.parse_price_database(b'AUCTIONATOR_PRICE_DATABASE = {\n["Realm')


def _mangled(seeds: list[bytes], rng: random.Random) -> bytes:
    b = bytearray(rng.choice(seeds))
    if rng.random() < 0.4:
        return bytes(b[: rng.randrange(len(b))])
    for _ in range(rng.randrange(1, 8)):
        b[rng.randrange(len(b))] = rng.randrange(256)
    return bytes(b)


def test_mangled_files_only_raise_value_error() -> None:
    """Uploads are untrusted: whatever the bytes, parsing either succeeds or raises ValueError (a 400)."""
    rng = random.Random(1)
    prices = [_saved_variables({"R": {"1": _entry(5), "g:2:3": _entry(7)}, "S": {"4": {"m": 1}}})]
    for _ in range(1500):
        with contextlib.suppress(ValueError):
            auctionator.parse_price_database(_mangled(prices, rng))
        with contextlib.suppress(ValueError):
            altarmy.parse_characters(_mangled([ALTARMY_SV], rng))
