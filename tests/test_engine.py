from wowprofit.engine import DisenchantRow, Item, Market, Recipe, Result, ah_net, recipes_for_professions

LINEN, THREAD, BOLT, GREEN, DUST = 1, 2, 3, 4, 5


def make_market(
    prices: dict[int, int],
    recipes: list[Recipe] | None = None,
    disenchant: list[DisenchantRow] | None = None,
) -> Market:
    items = {
        LINEN: Item(LINEN, "Linen Cloth"),
        THREAD: Item(THREAD, "Coarse Thread"),
        BOLT: Item(BOLT, "Bolt of Linen"),
        GREEN: Item(GREEN, "Green Robe", quality=2, item_level=20, class_id=4, sell_price=500),
        DUST: Item(DUST, "Strange Dust"),
    }
    recipes = (
        recipes
        if recipes is not None
        else [
            Recipe(10, "Green Robe", GREEN, 1, ((LINEN, 10), (THREAD, 1)), "Tailoring"),
        ]
    )
    return Market(items, recipes, prices, disenchant)


def must_evaluate(m: Market, recipe: Recipe) -> Result:
    res = m.evaluate(recipe)
    assert res is not None
    return res


def test_vendor_profit() -> None:
    m = make_market({LINEN: 20, THREAD: 100})
    res = must_evaluate(m, m.recipes[0])
    assert res.cost == 300
    assert res.best_exit == "vendor"
    assert res.profit == 200


def test_ah_net_of_cut_beats_vendor() -> None:
    m = make_market({LINEN: 20, THREAD: 100, GREEN: 1000})
    res = must_evaluate(m, m.recipes[0])
    assert res.best_exit == "ah"
    assert res.revenue == ah_net(1000) == 950


def test_disenchant_expected_value() -> None:
    de = [DisenchantRow(4, 2, 15, 25, DUST, 0.75, 1, 2)]  # 0.75 * 1.5 dust
    m = make_market({LINEN: 20, THREAD: 100, DUST: 1000}, disenchant=de)
    res = must_evaluate(m, m.recipes[0])
    assert res.best_exit == "disenchant"
    assert res.revenue == int(0.75 * 1.5 * ah_net(1000))


def test_disenchant_ignores_wrong_item_level() -> None:
    de = [DisenchantRow(4, 2, 30, 40, DUST, 1.0, 1, 1)]
    m = make_market({LINEN: 20, THREAD: 100, DUST: 400}, disenchant=de)
    assert must_evaluate(m, m.recipes[0]).best_exit == "vendor"


def test_missing_reagent_price_skips_recipe() -> None:
    m = make_market({LINEN: 20})  # no thread price
    assert m.evaluate(m.recipes[0]) is None


def test_chain_crafts_cheaper_intermediate() -> None:
    recipes = [
        Recipe(11, "Bolt of Linen", BOLT, 1, ((LINEN, 2),), "Tailoring"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Tailoring"),
    ]
    m = make_market({LINEN: 10, THREAD: 5, BOLT: 100}, recipes)
    res = must_evaluate(m, recipes[1])
    assert res.cost == 3 * 20 + 5  # crafting bolts (20) beats buying them (100)
    assert res.crafted_reagents == ["3x Bolt of Linen via Bolt of Linen"]


def test_chain_cycle_terminates() -> None:
    recipes = [
        Recipe(11, "A from B", LINEN, 1, ((THREAD, 1),)),
        Recipe(12, "B from A", THREAD, 1, ((LINEN, 1),)),
    ]
    m = make_market({}, recipes)
    assert m.reagent_cost(LINEN) is None


def test_rank_sorted_by_profit() -> None:
    recipes = [
        Recipe(10, "Cheap", GREEN, 1, ((LINEN, 1),), "Tailoring"),
        Recipe(11, "Mid", GREEN, 1, ((LINEN, 30),), "Tailoring"),
        Recipe(12, "Loser", GREEN, 1, ((LINEN, 60),), "Tailoring"),
    ]
    m = make_market({LINEN: 10}, recipes)
    ranked = m.rank()
    assert [r.recipe.name for r in ranked] == ["Cheap", "Mid"]  # Loser costs 600 vs 500 vendor


def test_recipes_for_professions_ignores_case() -> None:
    recipes = [
        Recipe(10, "Robe", GREEN, 1, ((LINEN, 1),), "Tailoring"),
        Recipe(11, "Bolt", BOLT, 1, ((LINEN, 2),), "Mining"),
        Recipe(12, "Other", DUST, 1, ((LINEN, 2),), "Enchanting"),
    ]
    got = recipes_for_professions(recipes, ["tailoring", "MINING"])
    assert [r.name for r in got] == ["Robe", "Bolt"]


def test_chain_only_subcrafts_through_selected_professions() -> None:
    recipes = [
        Recipe(11, "Smelt Bolt", BOLT, 1, ((LINEN, 2),), "Mining"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Blacksmithing"),
    ]
    prices = {LINEN: 10, THREAD: 5, BOLT: 100}

    smith_only = make_market(prices, recipes_for_professions(recipes, ["Blacksmithing"]))
    (res,) = smith_only.rank(min_profit=-(10**9))
    assert res.cost == 3 * 100 + 5  # must buy bolts
    assert res.crafted_reagents == []

    both = make_market(prices, recipes_for_professions(recipes, ["Blacksmithing", "Mining"]))
    res = must_evaluate(both, recipes[1])
    assert res.cost == 3 * 20 + 5
    assert res.crafted_reagents == ["3x Bolt of Linen via Smelt Bolt"]
