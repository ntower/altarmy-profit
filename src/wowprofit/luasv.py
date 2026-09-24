"""Parse WoW SavedVariables files: a series of `Name = <Lua value>` statements written by the client.

Only what the client writes is supported: tables, double-quoted strings, numbers, booleans, nil and
`--` line comments. Tables become dicts; positional entries get keys 1, 2, ... and a positional `nil`
still takes its slot (sparse arrays are written that way).
"""

from __future__ import annotations

import re
from typing import TypeAlias

LuaKey: TypeAlias = str | int | float | bool
LuaTable: TypeAlias = dict[LuaKey, "LuaValue"]
LuaValue: TypeAlias = str | int | float | bool | None | LuaTable

_ESCAPES = {b"n": 10, b"r": 13, b"t": 9, b"a": 7, b"b": 8, b"f": 12, b"v": 11, b"\n": 10}
_SKIP = re.compile(rb"(?:\s+|--[^\n]*)*")
_NAME = re.compile(rb"[A-Za-z_]\w*")
_NUMBER = re.compile(rb"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_ASSIGN = re.compile(rb"\s*=(?!=)")


def parse_assignments(data: bytes) -> dict[str, LuaValue]:
    """Return {global name: value} for every top-level assignment in the file."""
    p = _Parser(data)
    out: dict[str, LuaValue] = {}
    while p.peek():
        m = _NAME.match(data, p.pos)
        if not m:
            raise p.error("expected a global name")
        p.pos = m.end()
        p.expect(b"=")
        out[m.group().decode()] = p.value()
    return out


def lua_string(text: bytes, pos: int) -> tuple[bytes, int]:
    """Decode the quoted Lua string starting at `pos`; returns (bytes, position after closing quote)."""
    assert text[pos : pos + 1] == b'"'
    pos += 1
    out = bytearray()
    while True:
        c = text[pos]
        if c == 0x22:
            return bytes(out), pos + 1
        if c != 0x5C:
            out.append(c)
            pos += 1
            continue
        nxt = text[pos + 1 : pos + 2]
        if nxt.isdigit():
            digits = re.match(rb"\d{1,3}", text[pos + 1 : pos + 4])
            assert digits
            out.append(int(digits.group()))
            pos += 1 + len(digits.group())
        else:
            out.append(_ESCAPES.get(nxt, nxt[0]))
            pos += 2


class _Parser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def error(self, what: str) -> ValueError:
        return ValueError(f"Lua syntax error at byte {self.pos}: {what}")

    def peek(self) -> bytes:
        """Skip whitespace and comments; return the next byte (b"" at the end)."""
        m = _SKIP.match(self.data, self.pos)
        assert m
        self.pos = m.end()
        return self.data[self.pos : self.pos + 1]

    def expect(self, token: bytes) -> None:
        if self.peek() != token:
            raise self.error(f"expected {token.decode()!r}")
        self.pos += 1

    def value(self) -> LuaValue:
        c = self.peek()
        if c == b"{":
            return self.table()
        if c == b'"':
            try:
                s, self.pos = lua_string(self.data, self.pos)
            except IndexError:
                raise self.error("unterminated string") from None
            return s.decode("utf-8", "replace")
        if m := _NUMBER.match(self.data, self.pos):
            self.pos = m.end()
            return _number(m.group())
        if m := _NAME.match(self.data, self.pos):
            literals: dict[bytes, LuaValue] = {b"true": True, b"false": False, b"nil": None}
            if m.group() in literals:
                self.pos = m.end()
                return literals[m.group()]
        raise self.error("expected a value")

    def table(self) -> LuaTable:
        self.pos += 1  # "{"
        out: LuaTable = {}
        n = 0
        while (c := self.peek()) != b"}":
            if c == b"[":
                self.pos += 1
                key = self.value()
                if key is None or isinstance(key, dict):
                    raise self.error("bad table key")
                self.expect(b"]")
                self.expect(b"=")
                out[key] = self.value()
            elif (m := _NAME.match(self.data, self.pos)) and _ASSIGN.match(self.data, m.end()):
                self.pos = m.end()
                self.expect(b"=")
                out[m.group().decode()] = self.value()
            else:
                n += 1
                v = self.value()
                if v is not None:
                    out[n] = v
            if self.peek() in (b",", b";"):
                self.pos += 1
            elif self.peek() != b"}":
                raise self.error("expected ',' or '}'")
        self.pos += 1
        return out


def _number(text: bytes) -> int | float:
    sign = -1 if text.startswith(b"-") else 1
    digits = text.lstrip(b"-")
    if digits[:2].lower() == b"0x":
        return sign * int(digits, 16)
    if any(ch in digits for ch in b".eE"):
        return float(text)
    return int(text)
