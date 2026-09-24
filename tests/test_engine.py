from collections.abc import Sequence

from wowprofit.engine import (
    ALL_EXITS,
    MAIL_POSTAGE,
    Crafter,
    DisenchantRow,
    Filters,
    Item,
    Market,
    Material,
    Node,
    Option,
    Recipe,
    Result,
    SellOption,
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
    crafters: Sequence[Crafter] = (),
    include_unlearned: bool = False,
    exits: frozenset[str] = ALL_EXITS,
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
    return Market(
        items,
        recipes,
        prices,
        disenchant,
        crafters=crafters,
        include_unlearned=include_unlearned,
        exits=exits,
    )


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
    assert m.evaluate(recipes[0]) is None


def test_rank_sorted_by_profit() -> None:
    recipes = [
        Recipe(10, "Cheap", GREEN, 1, ((LINEN, 1),), "Tailoring"),
        Recipe(11, "Mid", GREEN, 1, ((LINEN, 30),), "Tailoring"),
        Recipe(12, "Loser", GREEN, 1, ((LINEN, 60),), "Tailoring"),
    ]
    m = make_market({LINEN: 10}, recipes)
    ranked = m.rank()
    assert [r.recipe.name for r in ranked] == ["Cheap", "Mid"]  # Loser costs 600 vs 500 vendor


def test_only_allowed_exits_are_used() -> None:
    prices = {LINEN: 20, THREAD: 100, GREEN: 1000}
    assert must_evaluate(make_market(prices), ROBE).best_exit == "ah"
    res = must_evaluate(make_market(prices, exits=frozenset({"vendor"})), ROBE)
    assert (res.best_exit, res.revenue) == ("vendor", 500)
    assert [e.kind for e in res.exits] == ["vendor"]
    assert make_market(prices, exits=frozenset({"disenchant"})).evaluate(ROBE) is None


def test_filters_bounds_are_inclusive_and_optional() -> None:
    res = must_evaluate(make_market({LINEN: 20, THREAD: 100}), ROBE)  # cost 300, profit 200, roi 2/3
    assert Filters().accepts(res)
    assert Filters(min_cost=300, max_cost=300, min_profit=200, max_profit=200).accepts(res)
    assert not Filters(max_cost=299).accepts(res)
    assert not Filters(min_cost=301).accepts(res)
    assert not Filters(min_profit=201).accepts(res)
    assert not Filters(max_profit=199).accepts(res)
    assert Filters(min_roi=0.6, max_roi=0.7).accepts(res)
    assert not Filters(min_roi=0.7).accepts(res)
    assert not Filters(max_roi=0.6).accepts(res)


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


# --- mailing to an enchanter -----------------------------------------------------------------------
ROBE = Recipe(10, "Green Robe", GREEN, 1, ((LINEN, 10), (THREAD, 1)), "Tailoring", spell_id=900)
DE_ROWS = [DisenchantRow(4, 2, 15, 25, DUST, 1.0, 1, 1)]  # one dust
DE_PRICES = {LINEN: 20, THREAD: 100, DUST: 1000}  # dust nets 950, beating the 500c vendor price


def crafter(name: str, *professions: tuple[str, int], known: frozenset[int] = frozenset()) -> Crafter:
    return Crafter(name, professions, known)


TAILOR = crafter("Tailor", ("Tailoring", 50), known=frozenset({900}))


def de_market(
    *crafters: Crafter, include_unlearned: bool = False, prices: dict[int, int] = DE_PRICES
) -> Market:
    return make_market(
        prices, [ROBE], disenchant=DE_ROWS, crafters=crafters, include_unlearned=include_unlearned
    )


def test_disenchant_is_free_when_the_crafter_enchants() -> None:
    both = crafter("Both", ("Enchanting", 10), ("Tailoring", 50), known=frozenset({900}))
    res = must_evaluate(de_market(both), ROBE)
    assert (res.best_exit, res.cost, res.postage, res.mail_to) == ("disenchant", 300, 0, "")
    assert "mail" not in [s.action for s in res.steps]


def test_disenchant_is_free_when_any_crafter_enchants() -> None:
    both = crafter("Both", ("Enchanting", 10), ("Tailoring", 50), known=frozenset({900}))
    res = must_evaluate(de_market(TAILOR, both), ROBE)
    assert (res.postage, res.mail_to) == (0, "")


def test_disenchant_mails_to_the_best_enchanter() -> None:
    low = crafter("Aaron", ("Enchanting", 10))
    high = crafter("Zed", ("Enchanting", 90))
    res = must_evaluate(de_market(TAILOR, low, high), ROBE)
    assert (res.best_exit, res.mail_to, res.postage) == ("disenchant", "Zed", MAIL_POSTAGE)
    assert res.cost == 300 + MAIL_POSTAGE
    assert res.revenue == 950
    (de,) = [e for e in res.exits if e.kind == "disenchant"]
    assert (de.postage, de.mail_to) == (MAIL_POSTAGE, "Zed")
    assert [s.action for s in res.steps] == ["buy", "buy", "craft", "mail", "sell"]
    assert res.steps[3] == Step("mail", GREEN, "Green Robe", 1, -MAIL_POSTAGE, via="Zed", who="Tailor")


def test_disenchant_ties_between_enchanters_go_to_the_first_name() -> None:
    res = must_evaluate(
        de_market(TAILOR, crafter("Zed", ("Enchanting", 5)), crafter("Amy", ("Enchanting", 5))), ROBE
    )
    assert res.mail_to == "Amy"


def test_disenchant_is_dropped_without_an_enchanter() -> None:
    res = must_evaluate(de_market(TAILOR), ROBE)
    assert res.best_exit == "vendor"
    assert "disenchant" not in [e.kind for e in res.exits]


def test_postage_can_tip_the_best_exit_to_the_ah() -> None:
    # dust nets 950 by disenchanting, the robe nets 950 on the AH: postage makes the AH better
    prices = {**DE_PRICES, GREEN: 1000}
    res = must_evaluate(de_market(TAILOR, crafter("Enc", ("Enchanting", 1)), prices=prices), ROBE)
    assert (res.best_exit, res.postage, res.mail_to, res.cost) == ("ah", 0, "", 300)
    assert "mail" not in [s.action for s in res.steps]


def test_no_crafters_means_free_disenchanting() -> None:
    res = must_evaluate(de_market(), ROBE)
    assert (res.best_exit, res.postage, res.mail_to) == ("disenchant", 0, "")


def test_unlearned_recipe_can_be_crafted_by_anyone_with_the_profession() -> None:
    novice_tailor = crafter("Novice", ("Tailoring", 1))
    both = crafter("Both", ("Enchanting", 10), ("Tailoring", 1))
    assert must_evaluate(de_market(novice_tailor, both, include_unlearned=True), ROBE).postage == 0
    # someone knows it, so only they craft it
    res = must_evaluate(de_market(TAILOR, both, include_unlearned=True), ROBE)
    assert (res.postage, res.mail_to) == (MAIL_POSTAGE, "Both")


# --- mailing intermediates between crafters ---------------------------------------------------------
SCRAPS, LEATHER, MAUL, COPPER = 6, 7, 8, 9
CURE = Recipe(20, "Light Leather", LEATHER, 1, ((SCRAPS, 3),), "Leatherworking", spell_id=950)
MAUL_RECIPE = Recipe(
    21, "Heavy Copper Maul", MAUL, 1, ((LEATHER, 2), (COPPER, 1)), "Blacksmithing", spell_id=951
)
SMITHY = crafter("Smithy", ("Blacksmithing", 50), known=frozenset({951}))
LEATHERY = crafter("Leathery", ("Leatherworking", 50), known=frozenset({950}))
BOTH = crafter("Both", ("Blacksmithing", 50), ("Leatherworking", 50), known=frozenset({950, 951}))


def maul_market(*crafters: Crafter, leather_price: int = 100) -> Market:
    items = {
        SCRAPS: Item(SCRAPS, "Ruined Leather Scraps", stack_size=20),
        LEATHER: Item(LEATHER, "Light Leather", stack_size=20),
        MAUL: Item(MAUL, "Heavy Copper Maul", class_id=2, sell_price=1000),
        COPPER: Item(COPPER, "Copper Bar", stack_size=20),
    }
    prices = {SCRAPS: 5, LEATHER: leather_price, COPPER: 10}
    return Market(items, [CURE, MAUL_RECIPE], prices, crafters=crafters)


def test_intermediate_is_crafted_by_another_character_and_mailed() -> None:
    res = must_evaluate(maul_market(SMITHY, LEATHERY), MAUL_RECIPE)
    assert res.crafter == "Smithy"
    assert res.cost == 2 * 15 + MAIL_POSTAGE + 10  # scraps for 2 leather, one stack mailed, copper
    leather = res.tree.inputs[0]
    assert (leather.crafter, leather.mail_to, leather.postage) == ("Leathery", "Smithy", MAIL_POSTAGE)
    assert res.steps == [
        Step("buy", SCRAPS, "Ruined Leather Scraps", 6, -30, "ah", "Leathery"),
        Step("buy", COPPER, "Copper Bar", 1, -10, "ah", "Smithy"),
        Step("craft", LEATHER, "Light Leather", 2, via="Light Leather", who="Leathery"),
        Step("mail", LEATHER, "Light Leather", 2, -MAIL_POSTAGE, "Smithy", "Leathery"),
        Step("craft", MAUL, "Heavy Copper Maul", 1, via="Heavy Copper Maul", who="Smithy"),
        Step("sell", MAUL, "Heavy Copper Maul", 1, 1000, "vendor", "Smithy"),
    ]


def test_buys_the_intermediate_when_crafting_and_mailing_costs_more() -> None:
    res = must_evaluate(maul_market(SMITHY, LEATHERY, leather_price=20), MAUL_RECIPE)
    assert res.cost == 2 * 20 + 10  # 40 beats 30 of scraps + 30 postage
    assert res.tree.inputs[0] == Node(LEATHER, "Light Leather", 2, 40, source="ah", crafter="Smithy")
    assert "mail" not in [s.action for s in res.steps]


def test_one_character_with_both_professions_mails_nothing() -> None:
    res = must_evaluate(maul_market(BOTH), MAUL_RECIPE)
    assert (res.crafter, res.cost) == ("Both", 2 * 15 + 10)
    assert "mail" not in [s.action for s in res.steps]


def test_picks_the_final_crafter_who_needs_no_mail() -> None:
    res = must_evaluate(maul_market(SMITHY, BOTH), MAUL_RECIPE)
    assert (res.crafter, res.cost) == ("Both", 2 * 15 + 10)


def test_postage_is_per_stack() -> None:
    m = maul_market()
    assert (m.postage(LEATHER, 20), m.postage(LEATHER, 25), m.postage(MAUL, 2)) == (30, 60, 60)


def test_no_characters_means_no_postage_in_chains() -> None:
    res = must_evaluate(maul_market(), MAUL_RECIPE)
    assert (res.crafter, res.cost) == ("", 2 * 15 + 10)


# --- alternatives the user can switch to ------------------------------------------------------------
def test_nodes_list_their_options_cheapest_first() -> None:
    m = make_market({LINEN: 10, THREAD: 5}, thread_vendor_price=3)
    thread = must_evaluate(m, ROBE).tree.inputs[1]
    assert thread.options == (Option("vendor", 3, source="vendor"), Option("ah", 5, source="ah"))
    assert thread.option == "vendor"
    assert must_evaluate(m, ROBE).tree.options == ()  # the recipe's own craft has none


def test_craft_options_name_the_recipe_and_cheapest_crafter() -> None:
    res = must_evaluate(maul_market(SMITHY, LEATHERY), MAUL_RECIPE)
    assert res.tree.inputs[0].options == (
        Option("craft:20", 2 * 15 + MAIL_POSTAGE, via="Light Leather", crafter="Leathery"),
        Option("ah", 200, source="ah"),
    )


def test_choosing_to_craft_a_bought_reagent_adds_its_chain() -> None:
    m = maul_market(SMITHY, LEATHERY, leather_price=20)
    res = m.evaluate(MAUL_RECIPE, {"r.0": "craft:20"})
    assert res is not None
    leather = res.tree.inputs[0]
    assert (leather.via, leather.crafter, leather.mail_to) == ("Light Leather", "Leathery", "Smithy")
    assert (leather.option, leather.inputs[0].item_id) == ("craft:20", SCRAPS)
    assert res.cost == 2 * 15 + MAIL_POSTAGE + 10
    assert [s.action for s in res.steps] == ["buy", "buy", "craft", "mail", "craft", "sell"]


def test_choosing_to_buy_a_crafted_reagent_drops_its_chain() -> None:
    res = maul_market(SMITHY, LEATHERY).evaluate(MAUL_RECIPE, {"r.0": "ah"})
    assert res is not None
    assert res.tree.inputs[0] == Node(LEATHER, "Light Leather", 2, 200, source="ah", crafter="Smithy")
    assert res.cost == 200 + 10


def test_choices_below_a_choice_apply() -> None:
    m = maul_market(SMITHY, LEATHERY, leather_price=20)
    res = m.evaluate(MAUL_RECIPE, {"r.0": "craft:20", "r.0.0": "nonsense"})
    assert res is not None
    assert res.tree.inputs[0].inputs[0].source == "ah"  # an unknown key keeps the cheapest


def test_unknown_choices_are_ignored() -> None:
    m = maul_market(SMITHY, LEATHERY)
    assert m.evaluate(MAUL_RECIPE, {"r.0": "craft:999", "sell": "ah"}) == m.evaluate(MAUL_RECIPE)


def test_sell_options_rank_each_exit_by_its_best_profit() -> None:
    res = must_evaluate(de_market(TAILOR, crafter("Enc", ("Enchanting", 1))), ROBE)
    assert res.sell_options == [
        SellOption("disenchant", 950 - 300 - MAIL_POSTAGE),
        SellOption("vendor", 500 - 300),
    ]


def test_choosing_an_exit_sells_that_way() -> None:
    m = de_market(TAILOR, crafter("Enc", ("Enchanting", 1)))
    res = m.evaluate(ROBE, {"sell": "vendor"})
    assert res is not None
    assert (res.best_exit, res.profit, res.mail_to) == ("vendor", 200, "")
    assert res.sell_options == must_evaluate(m, ROBE).sell_options
