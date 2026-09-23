import sqlite3
from pathlib import Path

import pytest

from wowprofit import auctionator, cli, ingest, prices


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
    assert parsed == {"Realm A": {1: 45, 2: 0x0A0D, 3: 0x2200, 4: 250}, "Realm B": {1: 7}}


def test_parse_rejects_file_without_price_database() -> None:
    with pytest.raises(ValueError, match="AUCTIONATOR_PRICE_DATABASE"):
        auctionator.parse_price_database(b"AUCTIONATOR_CONFIG = {\n}\n")


def test_import_auctionator(db2_paths: dict[str, Path], conn: sqlite3.Connection, tmp_path: Path) -> None:
    ingest.build_db(db2_paths, conn)
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"Only Realm": {"1": _entry(45), "999999": _entry(5)}}))
    realm, imported, unknown = prices.import_auctionator(conn, f)
    assert (realm, imported, unknown) == ("Only Realm", 2, 1)
    assert prices.load_prices(conn) == {1: 45, 999999: 5}
    assert conn.execute("SELECT source FROM prices WHERE item_id = 1").fetchone()["source"] == "auctionator"


def test_import_auctionator_needs_realm_when_ambiguous(conn: sqlite3.Connection, tmp_path: Path) -> None:
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"A": {"1": _entry(1)}, "B": {"1": _entry(2)}}))
    with pytest.raises(ValueError, match="A, B"):
        prices.import_auctionator(conn, f)
    assert prices.import_auctionator(conn, f, realm="B")[:2] == ("B", 1)
    assert prices.load_prices(conn) == {1: 2}


def test_cli_import_auctionator(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "Auctionator.lua"
    f.write_bytes(_saved_variables({"R": {"1": _entry(45)}}))
    dbfile = tmp_path / "t.db"
    cli.main(["--db", str(dbfile), "import-auctionator", str(f)])
    assert "Imported 1 prices from realm R" in capsys.readouterr().out
