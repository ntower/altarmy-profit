"""Parse Auctionator's account-wide SavedVariables (WTF/Account/<acct>/SavedVariables/Auctionator.lua).

`AUCTIONATOR_PRICE_DATABASE` maps realm name -> a Lua string holding CBOR (db version 8+). The
decoded map is item key -> {m = latest minimum buyout in copper, h/l/a = per-day fields}. Per day
(Auctionator's `DatabaseMixin:SetPrice`): h is the highest minimum buyout seen, l the lowest (stored only when
below h), a the most available. Days count from 2020-01-01 in the player's local time; Auctionator drops
days older than its price history setting.
Item keys are "<itemID>" for most items and "g:<itemID>:<ilvl>..." for gear; pets ("p:...") and gear with
random suffixes ("gr:...") are skipped.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import date, timedelta

from .luasv import lua_string

_TABLE = b"AUCTIONATOR_PRICE_DATABASE = {"
_ESCAPES = {b"n": 10, b"r": 13, b"t": 9, b"a": 7, b"b": 8, b"f": 12, b"v": 11, b"\n": 10}
_ITEM_KEY = re.compile(r"(?:g:)?(\d+)(?::.*)?")
DAY_ZERO = date(2020, 1, 1)


@dataclass(frozen=True)
class DayStats:
    """One day of an item's price history, in copper."""

    high: int  # highest minimum buyout seen that day
    low: int  # lowest minimum buyout seen that day
    available: int | None  # most units up at once; None in databases older than December 2020


@dataclass(frozen=True)
class ItemPrice:
    min_buyout: int  # the latest minimum buyout, copper
    days: dict[date, DayStats] = field(default_factory=dict)

    @property
    def last_seen(self) -> date | None:
        """The newest day with history (Auctionator's `m` is from then)."""
        return max(self.days, default=None)


def parse_price_database(text: bytes) -> dict[str, dict[int, ItemPrice]]:
    """Return {realm: {item_id: ItemPrice}} from the raw SavedVariables bytes."""
    start = text.find(_TABLE)
    if start < 0:
        raise ValueError("no AUCTIONATOR_PRICE_DATABASE in file (is this the account-wide Auctionator.lua?)")
    realms: dict[str, dict[int, ItemPrice]] = {}
    for key, blob in _table_strings(text, start + len(_TABLE)):
        data, _ = _cbor(blob, 0)
        if isinstance(data, dict):
            realms[key] = _item_prices(data)
    return realms


def min_buyouts(item_prices: dict[int, ItemPrice]) -> dict[int, int]:
    return {i: p.min_buyout for i, p in item_prices.items()}


def _item_prices(data: dict[object, object]) -> dict[int, ItemPrice]:
    """Gear variants of one item merge: the cheapest latest buyout, and per day the highest high, lowest
    low and summed availability."""
    out: dict[int, ItemPrice] = {}
    for key, entry in data.items():
        m = _ITEM_KEY.fullmatch(str(key))
        if not m or not isinstance(entry, dict) or not isinstance(entry.get("m"), int):
            continue
        item_id = int(m.group(1))
        price = ItemPrice(entry["m"], _days(entry))
        prev = out.get(item_id)
        out[item_id] = price if prev is None else _merge(prev, price)
    return out


def _merge(a: ItemPrice, b: ItemPrice) -> ItemPrice:
    days = dict(a.days)
    for day, s in b.days.items():
        o = days.get(day)
        days[day] = (
            s
            if o is None
            else DayStats(
                max(o.high, s.high),
                min(o.low, s.low),
                None
                if o.available is None and s.available is None
                else (o.available or 0) + (s.available or 0),
            )
        )
    return ItemPrice(min(a.min_buyout, b.min_buyout), days)


def _day_map(value: object) -> dict[int, int]:
    """A per-day field: a map of day number (string or int) -> integer; an empty Lua table decodes as []."""
    if not isinstance(value, dict):
        return {}
    out: dict[int, int] = {}
    for k, v in value.items():
        try:
            day = int(str(k))
        except ValueError:
            continue
        if isinstance(v, int | float):
            out[day] = int(v)
    return out


def _days(entry: dict[object, object]) -> dict[date, DayStats]:
    high, low, available = _day_map(entry.get("h")), _day_map(entry.get("l")), _day_map(entry.get("a"))
    return {
        DAY_ZERO + timedelta(days=day): DayStats(h, min(h, low.get(day, h)), available.get(day))
        for day, h in sorted(high.items())
    }


def _table_strings(text: bytes, pos: int) -> list[tuple[str, bytes]]:
    """Walk `["key"] = value,` entries of a flat Lua table, keeping only string values."""
    entries: list[tuple[str, bytes]] = []
    while True:
        while text[pos] in b" \t\r\n":
            pos += 1
        if text[pos : pos + 1] == b"}":
            return entries
        if text[pos : pos + 1] != b"[":
            raise ValueError(f"unexpected Lua syntax at byte {pos}")
        key, pos = lua_string(text, pos + 1)
        pos = text.index(b"=", pos) + 1
        while text[pos] in b" \t":
            pos += 1
        if text[pos : pos + 1] == b'"':
            value, pos = lua_string(text, pos)
            entries.append((key.decode("utf-8", "replace"), value))
        else:  # number or nested table from an older db version: skip the line
            pos = text.index(b"\n", pos)
        if text[pos : pos + 1] == b",":
            pos += 1


def _cbor(b: bytes, i: int) -> tuple[object, int]:
    """Minimal CBOR decoder (definite lengths only), enough for Auctionator's serializer."""
    major, info = b[i] >> 5, b[i] & 31
    i += 1
    if major == 7:
        if info == 25:
            return struct.unpack(">e", b[i : i + 2])[0], i + 2
        if info == 26:
            return struct.unpack(">f", b[i : i + 4])[0], i + 4
        if info == 27:
            return struct.unpack(">d", b[i : i + 8])[0], i + 8
        return {20: False, 21: True, 22: None, 23: None}[info], i
    if info < 24:
        n = info
    elif info <= 27:
        size = 1 << (info - 24)
        n = int.from_bytes(b[i : i + size], "big")
        i += size
    else:
        raise ValueError(f"unsupported CBOR length encoding {info} at byte {i - 1}")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        return b[i : i + n].decode("utf-8", "replace"), i + n
    if major == 4:
        items = []
        for _ in range(n):
            v, i = _cbor(b, i)
            items.append(v)
        return items, i
    if major == 5:
        d: dict[object, object] = {}
        for _ in range(n):
            k, i = _cbor(b, i)
            d[k], i = _cbor(b, i)
        return d, i
    if major == 6:  # tag: ignore it, return the tagged value
        return _cbor(b, i)
    raise ValueError(f"unsupported CBOR major type {major}")
