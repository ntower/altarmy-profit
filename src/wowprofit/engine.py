"""Pure profit engine: no I/O. All money is integer copper."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field, replace

AH_CUT = 0.05  # auction house cut taken from the sale price (deposit ignored)
MAX_CHAIN_DEPTH = 3
DISENCHANTABLE_CLASSES = (2, 4)  # weapon, armor
DISENCHANTABLE_QUALITIES = (2, 3, 4)
# Real professions offered in the UI; the DB also holds junk skill lines (test, class, etc.).
PROFESSIONS = (
    "Alchemy",
    "Blacksmithing",
    "Cooking",
    "Enchanting",
    "Engineering",
    "First Aid",
    "Fishing",
    "Herbalism",
    "Leatherworking",
    "Mining",
    "Poisons",
    "Skinning",
    "Tailoring",
)


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    quality: int = 1
    item_level: int = 0
    class_id: int = 0
    sell_price: int = 0
    vendor_price: int | None = None  # copper per unit if a vendor sells it (unlimited stock)


@dataclass(frozen=True)
class Recipe:
    id: int
    name: str
    output_item_id: int
    output_count: int = 1
    reagents: tuple[tuple[int, int], ...] = ()  # (item_id, count)
    skill_name: str = ""
    min_skill: int = 0
    spell_id: int = 0  # the craft spell; Alt Army's recipe ids


@dataclass(frozen=True)
class DisenchantRow:
    item_class: int
    quality: int
    min_ilvl: int
    max_ilvl: int
    result_item_id: int
    chance: float
    min_count: int
    max_count: int


@dataclass(frozen=True)
class Material:
    """One possible disenchant result for an item."""

    item_id: int
    name: str
    chance: float
    min_count: int
    max_count: int
    value: int | None  # expected net AH copper per disenchant (chance x average count); None if unpriced


@dataclass
class Exit:
    kind: str  # vendor | ah | disenchant
    value: int  # copper per item, after cuts
    materials: tuple[Material, ...] = ()  # disenchant only: what it yields


@dataclass(frozen=True)
class Step:
    """One instruction in a recipe's shopping/crafting/selling sequence."""

    action: str  # buy | craft | sell
    item_id: int
    name: str
    quantity: int
    value: int = 0  # copper for the whole step: negative when buying, positive when selling
    via: str = ""  # buy: vendor | ah; craft: recipe name; sell: vendor | ah | disenchant


@dataclass(frozen=True)
class Node:
    """One item in a craft's reagent tree: bought (no inputs) or crafted from its inputs."""

    item_id: int
    name: str
    quantity: int  # units this branch needs
    cost: int  # copper spent on them: quantity x price if bought, sum of inputs if crafted
    via: str = ""  # recipe name if crafted
    crafts: int = 0  # recipe runs if crafted: whole batches, so `made` may exceed `quantity`
    made: int = 0  # units those crafts produce
    inputs: tuple[Node, ...] = ()
    source: str = ""  # vendor | ah if bought


@dataclass
class Result:
    recipe: Recipe
    cost: int  # per craft
    revenue: int  # per craft (best exit x output_count)
    best_exit: str
    tree: Node  # the recipe's craft, with its reagents as inputs
    exits: list[Exit] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)  # buy reagents, craft (sub-crafts first), sell

    @property
    def profit(self) -> int:
        return self.revenue - self.cost

    @property
    def roi(self) -> float:
        return self.profit / self.cost if self.cost else 0.0


def ah_net(price: int, cut: float = AH_CUT) -> int:
    return int(price * (1 - cut))


class Market:
    def __init__(
        self,
        items: dict[int, Item],
        recipes: list[Recipe],
        prices: dict[int, int],
        disenchant: list[DisenchantRow] | None = None,
        ah_cut: float = AH_CUT,
    ):
        self.items = items
        self.recipes = recipes
        self.prices = prices
        self.disenchant = disenchant or []
        self.ah_cut = ah_cut
        self._by_output: dict[int, list[Recipe]] = {}
        for r in recipes:
            self._by_output.setdefault(r.output_item_id, []).append(r)

    # --- selling ---------------------------------------------------------------------
    def _disenchant_rows(self, item: Item) -> list[DisenchantRow]:
        if item.class_id not in DISENCHANTABLE_CLASSES or item.quality not in DISENCHANTABLE_QUALITIES:
            return []
        return [
            d
            for d in self.disenchant
            if d.item_class == item.class_id
            and d.quality == item.quality
            and d.min_ilvl <= item.item_level <= d.max_ilvl
        ]

    def _expected(self, d: DisenchantRow) -> float | None:
        """Expected net AH copper from one disenchant row; None if its result is unpriced."""
        price = self.prices.get(d.result_item_id)
        return (
            None if price is None else d.chance * (d.min_count + d.max_count) / 2 * ah_net(price, self.ah_cut)
        )

    def disenchant_materials(self, item: Item) -> list[Material]:
        """What disenchanting one item can yield; empty if it can't be disenchanted."""
        out = []
        for d in self._disenchant_rows(item):
            value = self._expected(d)
            name = self._name(d.result_item_id)
            out.append(
                Material(
                    d.result_item_id,
                    name,
                    d.chance,
                    d.min_count,
                    d.max_count,
                    None if value is None else int(value),
                )
            )
        return out

    def disenchant_value(self, item: Item) -> int | None:
        """Expected net AH value of disenchanting one item; None if not applicable/unpriced."""
        total = sum(v for d in self._disenchant_rows(item) if (v := self._expected(d)) is not None)
        return int(total) if total else None

    def exits_for(self, item_id: int) -> list[Exit]:
        item = self.items.get(item_id)
        if item is None:
            return []
        out: list[Exit] = []
        if item.sell_price > 0:
            out.append(Exit("vendor", item.sell_price))
        if item_id in self.prices:
            out.append(Exit("ah", ah_net(self.prices[item_id], self.ah_cut)))
        de = self.disenchant_value(item)
        if de:
            out.append(Exit("disenchant", de, tuple(self.disenchant_materials(item))))
        return out

    # --- buying / chains ---------------------------------------------------------------
    def buy_price(self, item_id: int) -> tuple[int, str] | None:
        """Cheapest place to buy one unit: (copper, "vendor" | "ah"). Ties go to the vendor, whose
        supply is unlimited."""
        options: list[tuple[int, str]] = []
        item = self.items.get(item_id)
        if item is not None and item.vendor_price is not None:
            options.append((item.vendor_price, "vendor"))
        if item_id in self.prices:
            options.append((self.prices[item_id], "ah"))
        return min(options, key=lambda o: o[0]) if options else None

    def reagent_cost(
        self, item_id: int, depth: int = 0, seen: frozenset[int] = frozenset()
    ) -> tuple[int, Recipe | None] | None:
        """Cheapest way to obtain one unit: buy it (recipe None), or craft it from other priced reagents."""
        options: list[tuple[int, Recipe | None]] = []
        bought = self.buy_price(item_id)
        if bought is not None:
            options.append((bought[0], None))
        if depth < MAX_CHAIN_DEPTH and item_id not in seen:
            for r in self._by_output.get(item_id, []):
                got = self._recipe_cost(r, depth + 1, seen | {item_id})
                if got is not None:
                    options.append((got // r.output_count, r))
        return min(options, key=lambda o: o[0]) if options else None  # ties prefer buying

    def _recipe_cost(self, recipe: Recipe, depth: int, seen: frozenset[int]) -> int | None:
        total = 0
        for item_id, count in recipe.reagents:
            got = self.reagent_cost(item_id, depth, seen)
            if got is None:
                return None
            total += got[0] * count
        return total

    def _name(self, item_id: int) -> str:
        return self.items[item_id].name if item_id in self.items else str(item_id)

    def tree(self, recipe: Recipe) -> Node:
        """One craft of `recipe` as a tree, following the same choices as its cost: each reagent is
        bought, or crafted in whole batches from its own reagents."""

        def need(item_id: int, qty: int, depth: int, seen: frozenset[int]) -> Node:
            got = self.reagent_cost(item_id, depth, seen)
            assert got is not None  # evaluate() already costed the whole tree
            via = got[1]
            if via is None:
                bought = self.buy_price(item_id)
                assert bought is not None
                return Node(item_id, self._name(item_id), qty, qty * bought[0], source=bought[1])
            runs = -(-qty // via.output_count)
            inputs = tuple(need(i, count * runs, depth + 1, seen | {item_id}) for i, count in via.reagents)
            return self._craft(item_id, qty, via, runs, inputs)

        inputs = tuple(need(i, count, 0, frozenset()) for i, count in recipe.reagents)
        return self._craft(recipe.output_item_id, recipe.output_count, recipe, 1, inputs)

    def _craft(self, item_id: int, qty: int, recipe: Recipe, runs: int, inputs: tuple[Node, ...]) -> Node:
        cost = sum(n.cost for n in inputs)
        return Node(
            item_id, self._name(item_id), qty, cost, recipe.name, runs, recipe.output_count * runs, inputs
        )

    @staticmethod
    def steps(tree: Node, sell_via: str, revenue: int) -> list[Step]:
        """Instructions for a craft tree: buy every bought reagent (merged per item), craft
        intermediates before what uses them, then sell. Sub-crafts are whole crafts, so a
        multi-output intermediate may leave spares."""
        buys: dict[int, Node] = {}
        crafts: dict[int, Node] = {}

        def walk(node: Node) -> None:
            if not node.via:
                had = buys.get(node.item_id)
                buys[node.item_id] = replace(
                    node,
                    quantity=node.quantity + (had.quantity if had else 0),
                    cost=node.cost + (had.cost if had else 0),
                )
                return
            for n in node.inputs:
                walk(n)
            had = crafts.get(node.item_id)
            crafts[node.item_id] = replace(node, made=node.made + (had.made if had else 0))

        for n in tree.inputs:
            walk(n)
        return [
            *(Step("buy", n.item_id, n.name, n.quantity, -n.cost, n.source) for n in buys.values()),
            *(Step("craft", n.item_id, n.name, n.made, via=n.via) for n in crafts.values()),
            Step("craft", tree.item_id, tree.name, tree.made, via=tree.via),
            Step("sell", tree.item_id, tree.name, tree.made, revenue, via=sell_via),
        ]

    # --- evaluation --------------------------------------------------------------------
    def evaluate(self, recipe: Recipe) -> Result | None:
        cost = self._recipe_cost(recipe, 0, frozenset())
        if cost is None:
            return None
        exits = self.exits_for(recipe.output_item_id)
        if not exits:
            return None
        best = max(exits, key=lambda e: e.value)
        revenue = best.value * recipe.output_count
        tree = self.tree(recipe)
        return Result(recipe, cost, revenue, best.kind, tree, exits, self.steps(tree, best.kind, revenue))

    def rank(self, min_profit: int = 0, skill_name: str | None = None) -> list[Result]:
        results = []
        for r in self.recipes:
            if skill_name and r.skill_name.lower() != skill_name.lower():
                continue
            res = self.evaluate(r)
            if res and res.profit >= min_profit:
                results.append(res)
        return sorted(results, key=lambda x: x.profit, reverse=True)


def recipes_for_professions(recipes: Iterable[Recipe], professions: Iterable[str]) -> list[Recipe]:
    """Recipes from the given professions (case-insensitive). A Market built from these only chains
    through recipes you can craft."""
    wanted = {p.lower() for p in professions}
    return [r for r in recipes if r.skill_name.lower() in wanted]


def recipes_for_characters(
    recipes: Iterable[Recipe],
    known_spells: Collection[int],
    professions: Iterable[str],
    include_unlearned: bool,
) -> list[Recipe]:
    """Recipes the characters have learned, or with `include_unlearned` every recipe of their professions.

    A Market built from these sub-crafts through any of the characters' recipes, whoever knows them.
    """
    wanted = {p.lower() for p in professions} if include_unlearned else set()
    return [r for r in recipes if r.spell_id in known_spells or r.skill_name.lower() in wanted]


def format_money(copper: int) -> str:
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    return f"{sign}{copper // 10000}g {copper // 100 % 100:02d}s {copper % 100:02d}c"
