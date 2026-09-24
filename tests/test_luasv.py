import pytest

from altarmy_profit import luasv


def test_parses_top_level_assignments_and_scalars() -> None:
    data = b'A = 1\nB = "two"\nC = true\nD = false\nE = nil\nF = -2.5\nG = 1e3\n'
    assert luasv.parse_assignments(data) == {
        "A": 1,
        "B": "two",
        "C": True,
        "D": False,
        "E": None,
        "F": -2.5,
        "G": 1000.0,
    }


def test_nested_tables_with_bracketed_named_and_positional_keys() -> None:
    data = b"""
X = {
["name"] = "Frell",
[-2] = { ["count"] = 5, },
[33260] = { ["primaryRecipeID"] = 33284, },
plain = 3,
{ 4387, 1 },
{ 4382, 2 },
}
"""
    assert luasv.parse_assignments(data)["X"] == {
        "name": "Frell",
        -2: {"count": 5},
        33260: {"primaryRecipeID": 33284},
        "plain": 3,
        1: {1: 4387, 2: 1},
        2: {1: 4382, 2: 2},
    }


def test_positional_nils_take_a_slot() -> None:
    data = b'T = {\n{ ["itemID"] = 1, },\nnil,\nnil,\n{ ["itemID"] = 4, },\n}\n'
    assert luasv.parse_assignments(data)["T"] == {1: {"itemID": 1}, 4: {"itemID": 4}}


def test_string_escapes_and_utf8() -> None:
    data = 'S = "a\\"b\\\\c\\nd\\065 café |cffffffff"\n'.encode()
    assert luasv.parse_assignments(data)["S"] == 'a"b\\c\ndA café |cffffffff'


def test_semicolon_separators_and_comments() -> None:
    data = b'-- saved by the game\nT = { 1; 2; ["k"] = "v" } -- trailing\n'
    assert luasv.parse_assignments(data)["T"] == {1: 1, 2: 2, "k": "v"}


@pytest.mark.parametrize("bad", [b"T = {", b"T = { [1] 2 }", b"= 1", b"T = @"])
def test_syntax_errors_raise_value_error(bad: bytes) -> None:
    with pytest.raises(ValueError):
        luasv.parse_assignments(bad)


def test_deep_nesting_is_rejected_not_a_crash() -> None:
    deep = b"X = " + b"{" * 5000 + b"}" * 5000
    with pytest.raises(ValueError, match="nested too deeply"):
        luasv.parse_assignments(deep)
    ok = b"X = " + b"{" * 50 + b"}" * 50
    assert isinstance(luasv.parse_assignments(ok)["X"], dict)  # real files nest a handful of levels
