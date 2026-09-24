"""Pure profit engine: no I/O. All money is integer copper."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class Recipe:
    id: int
    name: str
    output_item_id: int
    output_count: int = 1
    reagents: tuple[tuple[int, int], ...] = ()  # (item_id, count)
    skill_name: str = ""
    min_skill: int = 0


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


@dataclass
class Exit:
    kind: str  # vendor | ah | disenchant
    value: int  # copper per item, after cuts


@dataclass(frozen=True)
class Step:
    """One instruction in a recipe's shopping/crafting/selling sequence."""

    action: str  # buy | craft | sell
    item_id: int
    name: str
    quantity: int
    value: int = 0  # copper for the whole step: negative when buying, positive when selling
    via: str = ""  # craft: recipe name; sell: vendor | ah | disenchant


@dataclass
class Result:
    recipe: Recipe
    cost: int  # per craft
    revenue: int  # per craft (best exit x output_count)
    best_exit: str
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
    def disenchant_value(self, item: Item) -> int | None:
        """Expected net AH value of disenchanting one item; None if not applicable/unpriced."""
        if item.class_id not in DISENCHANTABLE_CLASSES or item.quality not in DISENCHANTABLE_QUALITIES:
            return None
        rows = [
            d
            for d in self.disenchant
            if d.item_class == item.class_id
            and d.quality == item.quality
            and d.min_ilvl <= item.item_level <= d.max_ilvl
        ]
        total = 0.0
        for d in rows:
            price = self.prices.get(d.result_item_id)
            if price is None:
                continue
            total += d.chance * (d.min_count + d.max_count) / 2 * ah_net(price, self.ah_cut)
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
            out.append(Exit("disenchant", de))
        return out

    # --- buying / chains ---------------------------------------------------------------
    def reagent_cost(
        self, item_id: int, depth: int = 0, seen: frozenset[int] = frozenset()
    ) -> tuple[int, Recipe | None] | None:
        """Cheapest way to obtain one unit: buy it (recipe None), or craft it from other priced reagents."""
        options: list[tuple[int, Recipe | None]] = []
        if item_id in self.prices:
            options.append((self.prices[item_id], None))
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

    def steps(self, recipe: Recipe, sell_via: str, revenue: int) -> list[Step]:
        """Instructions for one craft of `recipe`, following the same choices as its cost: buy every
        bought reagent (merged per item), craft intermediates before what uses them, then sell.
        Sub-crafts are whole crafts, so a multi-output intermediate may leave spares."""
        buys: dict[int, int] = {}
        crafts: dict[int, tuple[Recipe, int]] = {}  # output item -> (recipe, crafts)

        def need(item_id: int, qty: int, depth: int, seen: frozenset[int]) -> None:
            got = self.reagent_cost(item_id, depth, seen)
            assert got is not None  # evaluate() already costed the whole tree
            via = got[1]
            if via is None:
                buys[item_id] = buys.get(item_id, 0) + qty
                return
            runs = -(-qty // via.output_count)
            for sub_id, count in via.reagents:
                need(sub_id, count * runs, depth + 1, seen | {item_id})
            crafts[item_id] = (via, crafts.get(item_id, (via, 0))[1] + runs)

        for item_id, count in recipe.reagents:
            need(item_id, count, 0, frozenset())
        out_id, out = recipe.output_item_id, self._name(recipe.output_item_id)
        return [
            *(Step("buy", i, self._name(i), q, -q * self.prices[i]) for i, q in buys.items()),
            *(
                Step("craft", i, self._name(i), r.output_count * n, via=r.name)
                for i, (r, n) in crafts.items()
            ),
            Step("craft", out_id, out, recipe.output_count, via=recipe.name),
            Step("sell", out_id, out, recipe.output_count, revenue, via=sell_via),
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
        return Result(recipe, cost, revenue, best.kind, exits, self.steps(recipe, best.kind, revenue))

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


def format_money(copper: int) -> str:
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    return f"{sign}{copper // 10000}g {copper // 100 % 100:02d}s {copper % 100:02d}c"
