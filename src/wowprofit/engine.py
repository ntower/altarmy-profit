"""Pure profit engine: no I/O. All money is integer copper."""

from __future__ import annotations

from dataclasses import dataclass, field

AH_CUT = 0.05  # auction house cut taken from the sale price (deposit ignored)
MAX_CHAIN_DEPTH = 3
DISENCHANTABLE_CLASSES = (2, 4)  # weapon, armor
DISENCHANTABLE_QUALITIES = (2, 3, 4)


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


@dataclass
class Result:
    recipe: Recipe
    cost: int  # per craft
    revenue: int  # per craft (best exit x output_count)
    best_exit: str
    exits: list[Exit] = field(default_factory=list)
    crafted_reagents: list[str] = field(default_factory=list)  # sub-crafted reagents in the chain

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
    ) -> tuple[int, str] | None:
        """Cheapest way to obtain one unit: buy it, or craft it from other priced reagents."""
        options: list[tuple[int, str]] = []
        if item_id in self.prices:
            options.append((self.prices[item_id], "buy"))
        if depth < MAX_CHAIN_DEPTH and item_id not in seen:
            for r in self._by_output.get(item_id, []):
                got = self._recipe_cost(r, depth + 1, seen | {item_id})
                if got is not None:
                    options.append((got[0] // r.output_count, f"craft:{r.name}"))
        return min(options) if options else None

    def _recipe_cost(self, recipe: Recipe, depth: int, seen: frozenset[int]) -> tuple[int, list[str]] | None:
        total, crafted = 0, []
        for item_id, count in recipe.reagents:
            got = self.reagent_cost(item_id, depth, seen)
            if got is None:
                return None
            unit, how = got
            total += unit * count
            if how.startswith("craft:"):
                name = self.items[item_id].name if item_id in self.items else str(item_id)
                crafted.append(f"{count}x {name} via {how[6:]}")
        return total, crafted

    # --- evaluation --------------------------------------------------------------------
    def evaluate(self, recipe: Recipe) -> Result | None:
        cost = self._recipe_cost(recipe, 0, frozenset())
        if cost is None:
            return None
        exits = self.exits_for(recipe.output_item_id)
        if not exits:
            return None
        best = max(exits, key=lambda e: e.value)
        return Result(recipe, cost[0], best.value * recipe.output_count, best.kind, exits, cost[1])

    def rank(self, min_profit: int = 0, skill_name: str | None = None) -> list[Result]:
        results = []
        for r in self.recipes:
            if skill_name and r.skill_name.lower() != skill_name.lower():
                continue
            res = self.evaluate(r)
            if res and res.profit >= min_profit:
                results.append(res)
        return sorted(results, key=lambda x: x.profit, reverse=True)


def format_money(copper: int) -> str:
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    return f"{sign}{copper // 10000}g {copper // 100 % 100:02d}s {copper % 100:02d}c"
