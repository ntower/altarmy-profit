"""Game versions: lookup, data files and addon folders."""

from pathlib import Path

import pytest

from altarmy_profit import engine, prices, versions
from altarmy_profit.engine import Item, Market, Recipe
from altarmy_profit.versions import VERSIONS


def test_get_and_build_versions() -> None:
    assert versions.get("tbc").wago_product == "wow_anniversary"
    assert versions.get("forever").wago_product == "wow_classic_beta"
    with pytest.raises(ValueError, match="forever, tbc"):
        versions.get("retail")
    assert versions.version_of_build("2.5.6.69795") == "tbc"
    assert versions.version_of_build("1.60.1.69977") == "forever"
    assert versions.version_of_build("") == "forever"


def test_each_version_has_its_own_files() -> None:
    tbc, forever = VERSIONS["tbc"], VERSIONS["forever"]
    assert tbc.disenchant_csv == Path("data/tbc/disenchant.csv")
    assert forever.vendor_csv == Path("data/forever/vendor_items.csv")
    assert tbc.flavor_folders == ("_anniversary_",)
    assert forever.flavor_folders == ("_classic_beta_",)
    assert (tbc.interface, forever.interface) == (20506, 16001)


def test_find_files_only_in_the_versions_flavor_folders(tmp_path: Path) -> None:
    found = {}
    for flavor in ("_anniversary_", "_classic_beta_"):
        sv = tmp_path / flavor / "WTF" / "Account" / "ME" / "SavedVariables"
        sv.mkdir(parents=True)
        (sv / "AltArmy_TBC.lua").write_text("")
        (sv / "Auctionator.lua").write_text("")
        found[flavor] = sv
    tbc = VERSIONS["tbc"].flavor_folders
    assert prices.find_altarmy_files([tmp_path], tbc) == [found["_anniversary_"] / "AltArmy_TBC.lua"]
    assert prices.find_auctionator_files([tmp_path], ("_classic_beta_",)) == [
        found["_classic_beta_"] / "Auctionator.lua"
    ]
    assert len(prices.find_altarmy_files([tmp_path])) == 2  # no flavors: every install folder


def test_market_charges_the_versions_postage() -> None:
    items = {1: Item(1, "Linen Cloth", stack_size=20), 2: Item(2, "Bolt", sell_price=100)}
    bolt = Recipe(1, "Bolt", 2, 1, ((1, 45),), "Tailoring")
    assert Market(items, [bolt], {1: 1}).postage(1, 45) == 3 * engine.MAIL_POSTAGE  # three stacks
    assert Market(items, [bolt], {1: 1}, mail_postage=50).postage(1, 45) == 150
