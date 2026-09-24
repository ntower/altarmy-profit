import pytest

from altarmy_profit import altarmy
from altarmy_profit.altarmy import Character, Profession

# Trimmed from a real AltArmy_TBC.lua (addon 2.1.1): no indentation, one statement per global.
ALTARMY_SV = b"""
AltArmyTBC_Options = {
["showMinimap"] = true,
}
AltArmyTBC_Data = {
["RecipeReagents"] = {
[900] = {
{
1,
10,
},
},
},
["Characters"] = {
["Classic Beta PvE"] = {
["Tailor Guy"] = {
["name"] = "Tailor Guy",
["realm"] = "Classic Beta PvE",
["faction"] = "Horde",
["classFile"] = "MAGE",
["level"] = 20,
["Containers"] = {
{
["items"] = {
{
["itemID"] = 1,
["count"] = 20,
},
nil,
{
["itemID"] = 2,
["count"] = 5,
},
},
},
},
["Professions"] = {
["Tailoring"] = {
["isPrimary"] = true,
["Recipes"] = {
[900] = {
["color"] = 1,
["primaryRecipeID"] = 900,
["name"] = "Green Robe",
["resultItemID"] = 3,
},
},
["maxRank"] = 75,
["rank"] = 50,
},
["Cooking"] = {
["isSecondary"] = true,
["Recipes"] = {
},
["maxRank"] = 75,
["rank"] = 1,
},
},
},
["Ally Alt"] = {
["name"] = "Ally Alt",
["faction"] = "Alliance",
["classFile"] = "PRIEST",
["level"] = 10,
["Professions"] = {
["Enchanting"] = {
["isPrimary"] = true,
["Recipes"] = {
[7418] = {
["color"] = 4,
},
},
["maxRank"] = 75,
["rank"] = 12,
},
},
},
},
["Dreamscythe"] = {
["Frell"] = {
["name"] = "Frell",
["faction"] = "Horde",
["classFile"] = "WARLOCK",
["level"] = 70,
["Professions"] = {
["Cooking"] = {
["Recipes"] = {
[33260] = {
["color"] = 4,
["primaryRecipeID"] = 33284,
["resultItemID"] = 27655,
},
[33284] = {
["color"] = 4,
["primaryRecipeID"] = 33284,
["resultItemID"] = 27655,
},
},
["maxRank"] = 375,
["rank"] = 370,
},
},
},
["Newbie"] = {
["faction"] = "Horde",
},
},
},
}
AltArmyTBC_GuildData = {
}
"""


def test_parse_characters() -> None:
    chars = altarmy.parse_characters(ALTARMY_SV)
    assert [(c.realm, c.name) for c in chars] == [
        ("Classic Beta PvE", "Ally Alt"),
        ("Classic Beta PvE", "Tailor Guy"),
        ("Dreamscythe", "Frell"),
        ("Dreamscythe", "Newbie"),
    ]
    ally, tailor, frell, newbie = chars
    assert tailor == Character(
        realm="Classic Beta PvE",
        name="Tailor Guy",
        faction="Horde",
        class_file="MAGE",
        level=20,
        professions=(
            Profession("Cooking", rank=1, max_rank=75, recipe_ids=frozenset()),
            Profession("Tailoring", rank=50, max_rank=75, recipe_ids=frozenset({900})),
        ),
    )
    # Enchanting craft rows only carry a color: the key is the recipe id.
    assert ally.professions == (Profession("Enchanting", 12, 75, frozenset({7418})),)
    # TBC alias keys collapse onto primaryRecipeID.
    assert frell.professions == (Profession("Cooking", 370, 375, frozenset({33284})),)
    # A character that was never fully scanned still shows up, without professions.
    assert newbie == Character("Dreamscythe", "Newbie", "Horde", "", 0, ())


def test_known_recipes_unions_professions() -> None:
    (tailor,) = [c for c in altarmy.parse_characters(ALTARMY_SV) if c.name == "Tailor Guy"]
    assert tailor.known_recipes == frozenset({900})


def test_groups_by_realm_and_faction() -> None:
    got = [(g.realm, g.faction, [c.name for c in g.characters]) for g in altarmy.groups(chars())]
    assert got == [
        ("Classic Beta PvE", "Alliance", ["Ally Alt"]),
        ("Classic Beta PvE", "Horde", ["Tailor Guy"]),
        ("Dreamscythe", "Horde", ["Frell", "Newbie"]),
    ]


def test_crafters() -> None:
    assert altarmy.crafters(chars()) == {900: ["Tailor Guy"], 7418: ["Ally Alt"], 33284: ["Frell"]}


def chars() -> list[Character]:
    return altarmy.parse_characters(ALTARMY_SV)


def test_rejects_other_files() -> None:
    with pytest.raises(ValueError, match="AltArmyTBC_Data"):
        altarmy.parse_characters(b"AUCTIONATOR_PRICE_DATABASE = {}\n")
