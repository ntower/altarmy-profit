from wowprofit.engine import (
    DisenchantRow,
    Item,
    Market,
    Material,
    Node,
    Recipe,
    Result,
    Step,
    ah_net,
    recipes_for_characters,
    recipes_for_professions,
)

LINEN, THREAD, BOLT, GREEN, DUST = 1, 2, 3, 4, 5


def make_market(
    prices: dict[int, int],
    recipes: list[Recipe] | None = None,
    disenchant: list[DisenchantRow] | None = None,
    thread_vendor_price: int | None = None,
) -> Market:
    items = {
        LINEN: Item(LINEN, "Linen Cloth"),
        THREAD: Item(THREAD, "Coarse Thread", vendor_price=thread_vendor_price),
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
    assert res.steps[-1] == Step("sell", GREEN, "Green Robe", 1, res.revenue, via="disenchant")


def test_disenchant_exit_lists_expected_materials() -> None:
    de = [
        DisenchantRow(4, 2, 15, 25, DUST, 0.75, 1, 2),
        DisenchantRow(4, 2, 15, 25, THREAD, 0.25, 1, 1),  # unpriced: listed, but worth nothing
    ]
    m = make_market({LINEN: 20, DUST: 1000}, [], disenchant=de)
    (exit,) = [e for e in m.exits_for(GREEN) if e.kind == "disenchant"]
    assert exit.materials == (
        Material(DUST, "Strange Dust", 0.75, 1, 2, int(0.75 * 1.5 * ah_net(1000))),
        Material(THREAD, "Coarse Thread", 0.25, 1, 1, None),
    )
    assert exit.value == int(0.75 * 1.5 * ah_net(1000))
    assert all(e.materials == () for e in m.exits_for(GREEN) if e.kind != "disenchant")


def test_disenchant_ignores_wrong_item_level() -> None:
    de = [DisenchantRow(4, 2, 30, 40, DUST, 1.0, 1, 1)]
    m = make_market({LINEN: 20, THREAD: 100, DUST: 400}, disenchant=de)
    assert must_evaluate(m, m.recipes[0]).best_exit == "vendor"


def test_vendor_sold_reagent_needs_no_ah_price() -> None:
    m = make_market({LINEN: 20}, thread_vendor_price=10)
    res = must_evaluate(m, m.recipes[0])
    assert res.cost == 210
    assert res.steps[1] == Step("buy", THREAD, "Coarse Thread", 1, -10, via="vendor")
    assert res.tree.inputs[1].source == "vendor"


def test_buys_reagent_from_cheaper_of_vendor_and_ah() -> None:
    cheaper_ah = make_market({LINEN: 20, THREAD: 5}, thread_vendor_price=10)
    assert must_evaluate(cheaper_ah, cheaper_ah.recipes[0]).steps[1].via == "ah"
    cheaper_vendor = make_market({LINEN: 20, THREAD: 50}, thread_vendor_price=10)
    res = must_evaluate(cheaper_vendor, cheaper_vendor.recipes[0])
    assert (res.cost, res.steps[1].via) == (210, "vendor")
    tie = make_market({LINEN: 20, THREAD: 10}, thread_vendor_price=10)
    assert must_evaluate(tie, tie.recipes[0]).steps[1].via == "vendor"  # unlimited supply, no AH trip


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
    assert res.steps == [
        Step("buy", LINEN, "Linen Cloth", 6, -60, via="ah"),
        Step("buy", THREAD, "Coarse Thread", 1, -5, via="ah"),
        Step("craft", BOLT, "Bolt of Linen", 3, via="Bolt of Linen"),
        Step("craft", GREEN, "Green Robe", 1, via="Green Robe"),
        Step("sell", GREEN, "Green Robe", 1, 500, via="vendor"),
    ]


def test_steps_craft_whole_batches_of_multi_output_reagents() -> None:
    recipes = [
        Recipe(11, "Bolts x2", BOLT, 2, ((LINEN, 2),), "Tailoring"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Tailoring"),
    ]
    m = make_market({LINEN: 10, THREAD: 5}, recipes)
    steps = must_evaluate(m, recipes[1]).steps
    assert steps[0] == Step("buy", LINEN, "Linen Cloth", 4, -40, via="ah")  # two crafts of 2 bolts
    assert steps[2] == Step("craft", BOLT, "Bolt of Linen", 4, via="Bolts x2")


def test_steps_merge_repeated_reagents() -> None:
    recipes = [
        Recipe(11, "Bolt of Linen", BOLT, 1, ((LINEN, 2),), "Tailoring"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 1), (LINEN, 3)), "Tailoring"),
    ]
    m = make_market({LINEN: 10}, recipes)
    assert must_evaluate(m, recipes[1]).steps[0] == Step("buy", LINEN, "Linen Cloth", 5, -50, via="ah")


def test_tree_links_reagents_to_the_crafts_that_use_them() -> None:
    recipes = [
        Recipe(11, "Bolt of Linen", BOLT, 1, ((LINEN, 2),), "Tailoring"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Tailoring"),
    ]
    m = make_market({LINEN: 10, THREAD: 5, BOLT: 100}, recipes)
    assert must_evaluate(m, recipes[1]).tree == Node(
        GREEN,
        "Green Robe",
        1,
        65,
        via="Green Robe",
        crafts=1,
        made=1,
        inputs=(
            Node(
                BOLT,
                "Bolt of Linen",
                3,
                60,
                via="Bolt of Linen",
                crafts=3,
                made=3,
                inputs=(Node(LINEN, "Linen Cloth", 6, 60, source="ah"),),
            ),
            Node(THREAD, "Coarse Thread", 1, 5, source="ah"),
        ),
    )


def test_tree_crafts_whole_batches_of_multi_output_reagents() -> None:
    recipes = [
        Recipe(11, "Bolts x2", BOLT, 2, ((LINEN, 2),), "Tailoring"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Tailoring"),
    ]
    m = make_market({LINEN: 10, THREAD: 5}, recipes)
    bolt = must_evaluate(m, recipes[1]).tree.inputs[0]
    assert (bolt.quantity, bolt.crafts, bolt.made, bolt.cost) == (3, 2, 4, 40)
    assert bolt.inputs == (Node(LINEN, "Linen Cloth", 4, 40, source="ah"),)


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


def test_recipes_for_characters_known_or_whole_professions() -> None:
    recipes = [
        Recipe(10, "Robe", GREEN, 1, ((LINEN, 1),), "Tailoring", spell_id=900),
        Recipe(11, "Bolt", BOLT, 1, ((LINEN, 2),), "Tailoring", spell_id=901),
        Recipe(12, "Dust", DUST, 1, ((LINEN, 2),), "Enchanting", spell_id=902),
    ]
    known = [r.name for r in recipes_for_characters(recipes, {900}, {"Tailoring"}, include_unlearned=False)]
    assert known == ["Robe"]
    every = recipes_for_characters(recipes, {900}, {"tailoring"}, include_unlearned=True)
    assert [r.name for r in every] == ["Robe", "Bolt"]


def test_chain_subcrafts_through_an_alts_known_recipe() -> None:
    recipes = [
        Recipe(11, "Smelt Bolt", BOLT, 1, ((LINEN, 2),), "Mining", spell_id=1),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Blacksmithing", spell_id=2),
    ]
    prices = {LINEN: 10, THREAD: 5, BOLT: 100}
    market = make_market(prices, recipes_for_characters(recipes, {1, 2}, set(), include_unlearned=False))
    assert must_evaluate(market, recipes[1]).cost == 3 * 20 + 5


def test_chain_only_subcrafts_through_selected_professions() -> None:
    recipes = [
        Recipe(11, "Smelt Bolt", BOLT, 1, ((LINEN, 2),), "Mining"),
        Recipe(12, "Green Robe", GREEN, 1, ((BOLT, 3), (THREAD, 1)), "Blacksmithing"),
    ]
    prices = {LINEN: 10, THREAD: 5, BOLT: 100}

    smith_only = make_market(prices, recipes_for_professions(recipes, ["Blacksmithing"]))
    (res,) = smith_only.rank(min_profit=-(10**9))
    assert res.cost == 3 * 100 + 5  # must buy bolts
    assert [s.action for s in res.steps] == ["buy", "buy", "craft", "sell"]

    both = make_market(prices, recipes_for_professions(recipes, ["Blacksmithing", "Mining"]))
    res = must_evaluate(both, recipes[1])
    assert res.cost == 3 * 20 + 5
    assert Step("craft", BOLT, "Bolt of Linen", 3, via="Smelt Bolt") in res.steps
