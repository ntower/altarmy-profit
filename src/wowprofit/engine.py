"""Pure profit engine: no I/O. All money is integer copper."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

AH_CUT = 0.05  # auction house cut taken from the sale price (deposit ignored)
MAIL_POSTAGE = 30  # copper per attached item
MAX_CHAIN_DEPTH = 3
DISENCHANTABLE_CLASSES = (2, 4)  # weapon, armor
DISENCHANTABLE_QUALITIES = (2, 3, 4)
ALL_EXITS = frozenset({"vendor", "ah", "disenchant"})  # ways to sell a craft (Exit.kind)
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
    stack_size: int = 1  # units per stack: one mail attachment


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
class Crafter:
    """One character who may craft or disenchant: their (profession, rank) pairs and learned craft spells."""

    name: str
    professions: tuple[tuple[str, int], ...]
    known_spells: frozenset[int]

    def has(self, profession: str) -> bool:
        return any(p.lower() == profession.lower() for p, _ in self.professions)

    @property
    def enchanting(self) -> int:
        """Enchanting skill; 0 if they don't have it."""
        return max((r for p, r in self.professions if p.lower() == "enchanting"), default=0)


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
    postage: int = 0  # copper per item to mail it to the character who can use this exit
    mail_to: str = ""  # that character; "" if the crafter can use it themselves


@dataclass(frozen=True)
class Step:
    """One instruction in a recipe's shopping/crafting/selling sequence."""

    action: str  # buy | craft | mail | sell
    item_id: int
    name: str
    quantity: int
    value: int = 0  # copper for the whole step: negative when buying or mailing, positive when selling
    via: str = ""  # buy: vendor | ah; craft: recipe name; mail: recipient; sell: vendor | ah | disenchant
    who: str = ""  # the character doing it; "" if no characters are known


@dataclass(frozen=True)
class Option:
    """One way to get a node's items: buy them (`key` vendor | ah) or craft them (`key` craft:<recipe id>)."""

    key: str
    cost: int  # copper for the node's quantity this way, with postage (its own subtree at its cheapest)
    source: str = ""  # vendor | ah if bought
    via: str = ""  # recipe name if crafted
    crafter: str = ""  # who crafts it: the cheapest character for that recipe


@dataclass(frozen=True)
class SellOption:
    """One way to sell a craft and the best profit it gives."""

    kind: str  # vendor | ah | disenchant
    profit: int


@dataclass(frozen=True)
class Node:
    """One item in a craft's reagent tree: bought (no inputs) or crafted from its inputs, possibly by
    another character who then mails it on."""

    item_id: int
    name: str
    quantity: int  # units this branch needs
    cost: int  # copper spent on them: quantity x price if bought, sum of inputs if crafted; plus postage
    via: str = ""  # recipe name if crafted
    crafts: int = 0  # recipe runs if crafted: whole batches, so `made` may exceed `quantity`
    made: int = 0  # units those crafts produce
    inputs: tuple[Node, ...] = ()
    source: str = ""  # vendor | ah if bought
    crafter: str = ""  # who buys or crafts it; "" if no characters are known
    mail_to: str = ""  # who it is mailed to (the parent's crafter); "" if not mailed
    postage: int = 0  # copper for that mail, included in cost
    # every way to get these items, cheapest first; empty for the recipe's own craft
    options: tuple[Option, ...] = field(default=(), compare=False)
    option: str = field(default="", compare=False)  # the key of the option taken; "" for the recipe's craft


@dataclass
class Result:
    recipe: Recipe
    cost: int  # per craft: reagents plus postage
    revenue: int  # per craft (best exit x output_count)
    best_exit: str
    tree: Node  # the recipe's craft, with its reagents as inputs
    exits: list[Exit] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)  # buy reagents, craft (sub-crafts first), mail, sell
    postage: int = 0  # per craft: mailing the output to whoever sells it (included in cost)
    mail_to: str = ""  # who the output is mailed to; "" if the crafter sells it
    crafter: str = ""  # who does the final craft; "" if no characters are known
    sell_options: list[SellOption] = field(default_factory=list)  # each exit's best profit, best first

    @property
    def profit(self) -> int:
        return self.revenue - self.cost

    @property
    def roi(self) -> float:
        return self.profit / self.cost if self.cost else 0.0


@dataclass(frozen=True)
class Filters:
    """Inclusive bounds on a result's cost and profit (copper) and ROI (0.5 = 50%); None is unbounded."""

    min_cost: int | None = None
    max_cost: int | None = None
    min_profit: int | None = None
    max_profit: int | None = None
    min_roi: float | None = None
    max_roi: float | None = None

    def accepts(self, r: Result) -> bool:
        def within(value: float, lo: float | None, hi: float | None) -> bool:
            return (lo is None or value >= lo) and (hi is None or value <= hi)

        return (
            within(r.cost, self.min_cost, self.max_cost)
            and within(r.profit, self.min_profit, self.max_profit)
            and within(r.roi, self.min_roi, self.max_roi)
        )


Memo = dict[tuple[int, int, str, int, frozenset[int]], Node | None]
# The user's picks by tree path ("r" is the recipe's craft, "r.0" its first reagent, "r.0.1" that one's
# second reagent, "sell" the exit): an Option key, or an exit kind for "sell". Unknown keys are ignored.
Choices = Mapping[str, str]
ROOT = "r"
SELL = "sell"


def _touches(choices: Choices, path: str) -> bool:
    """Whether any choice is at `path` or below it."""
    return any(k == path or k.startswith(path + ".") for k in choices)


def _option(key: str, node: Node) -> Option:
    if node.via:
        return Option(key, node.cost, via=node.via, crafter=node.crafter)
    return Option(key, node.cost, source=node.source)


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
        *,
        crafters: Sequence[Crafter] = (),
        include_unlearned: bool = False,
        exits: frozenset[str] = ALL_EXITS,
    ):
        """`crafters` are the characters who craft and disenchant, mailing items between them; without
        them one unnamed character does everything. `include_unlearned` lets anyone with a recipe's
        profession craft it when nobody has learned it. Crafts are only sold via `exits`."""
        self.items = items
        self.recipes = recipes
        self.prices = prices
        self.disenchant = disenchant or []
        self.ah_cut = ah_cut
        self.crafters = crafters
        self.include_unlearned = include_unlearned
        self.exits = exits
        self._by_output: dict[int, list[Recipe]] = {}
        for r in recipes:
            self._by_output.setdefault(r.output_item_id, []).append(r)
        self._who_crafts = {r.id: self._crafter_names(r) for r in recipes}

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

    def _disenchanter(self, who: str) -> tuple[str, int] | None:
        """Who disenchants what `who` crafted and the postage per item to get it to them.

        ("", 0) if `who` enchants (or no characters are known), the best other enchanter and
        MAIL_POSTAGE otherwise, None if nobody enchants.
        """
        if not self.crafters or any(c.name == who and c.enchanting for c in self.crafters):
            return "", 0
        enchanters = [c for c in self.crafters if c.enchanting]
        if not enchanters:
            return None
        best = min(enchanters, key=lambda c: (-c.enchanting, c.name))
        return best.name, MAIL_POSTAGE

    def _exits_at(self, exits: list[Exit], who: str) -> list[Exit]:
        """`exits` for an item `who` holds: disenchanting charged postage or dropped per `_disenchanter`."""
        out = []
        for e in exits:
            if e.kind == "disenchant":
                de = self._disenchanter(who)
                if de is None:
                    continue
                e = replace(e, mail_to=de[0], postage=de[1])
            out.append(e)
        return out

    def postage(self, item_id: int, qty: int) -> int:
        """Copper to mail `qty` units: one attachment per stack."""
        item = self.items.get(item_id)
        stack = max(1, item.stack_size) if item else 1
        return MAIL_POSTAGE * -(-qty // stack)

    # --- buying / chains ---------------------------------------------------------------
    def _crafter_names(self, recipe: Recipe) -> list[str]:
        if not self.crafters:
            return [""]  # one unnamed character who does everything
        return [c.name for c in crafters_of(recipe, self.crafters, self.include_unlearned)]

    def _who(self, recipe: Recipe) -> list[str]:
        """Who can craft `recipe`."""
        got = self._who_crafts.get(recipe.id)
        return got if got is not None else self._crafter_names(recipe)

    def _name(self, item_id: int) -> str:
        return self.items[item_id].name if item_id in self.items else str(item_id)

    def _obtain(
        self,
        item_id: int,
        qty: int,
        at: str,
        depth: int,
        seen: frozenset[int],
        memo: Memo,
        path: str = ROOT,
        choices: Choices | None = None,
    ) -> Node | None:
        """The cheapest way for `at` to hold `qty` units, or the one `choices` picks at `path`: buy them
        (vendor or AH), or craft them in whole batches (themselves, or another character who mails them
        over). Ties prefer the vendor, then the AH, then crafting. The node lists every option."""
        choices = choices or {}
        key = (item_id, qty, at, depth, seen)
        # A subtree's cheapest plan doesn't depend on where it sits, unless the user changed something in it.
        chosen = _touches(choices, path)
        if not chosen and key in memo:
            return memo[key]
        name = self._name(item_id)
        candidates: list[tuple[str, Node]] = []
        item = self.items.get(item_id)
        if item is not None and item.vendor_price is not None:
            candidates.append(
                ("vendor", Node(item_id, name, qty, qty * item.vendor_price, source="vendor", crafter=at))
            )
        if item_id in self.prices:
            candidates.append(
                ("ah", Node(item_id, name, qty, qty * self.prices[item_id], source="ah", crafter=at))
            )
        if depth < MAX_CHAIN_DEPTH and item_id not in seen:
            for r in self._by_output.get(item_id, []):
                runs = -(-qty // r.output_count)
                crafted: list[Node] = []
                for who in sorted(self._who(r), key=lambda w: w != at):
                    node = self._craft(r, qty, runs, who, depth + 1, seen | {item_id}, memo, path, choices)
                    if node is not None and who != at:
                        p = self.postage(item_id, qty)
                        node = replace(node, cost=node.cost + p, mail_to=at, postage=p)
                    if node is not None:
                        crafted.append(node)
                if crafted:
                    candidates.append((f"craft:{r.id}", min(crafted, key=lambda n: n.cost)))
        best: Node | None = None
        if candidates:
            ranked = sorted(candidates, key=lambda c: c[1].cost)  # stable: ties keep the preference order
            taken, picked = next((c for c in ranked if c[0] == choices.get(path)), ranked[0])
            best = replace(picked, options=tuple(_option(k, n) for k, n in ranked), option=taken)
        if not chosen:
            memo[key] = best
        return best

    def _craft(
        self,
        recipe: Recipe,
        qty: int,
        runs: int,
        who: str,
        depth: int,
        seen: frozenset[int],
        memo: Memo,
        path: str = ROOT,
        choices: Choices | None = None,
    ) -> Node | None:
        """`runs` crafts of `recipe` by `who` (the node at `path`), getting each reagent the cheapest way
        or as `choices` says; None if one can't be had."""
        inputs = []
        for i, (item_id, count) in enumerate(recipe.reagents):
            got = self._obtain(item_id, count * runs, who, depth, seen, memo, f"{path}.{i}", choices)
            if got is None:
                return None
            inputs.append(got)
        item_id = recipe.output_item_id
        cost = sum(n.cost for n in inputs)
        made = recipe.output_count * runs
        return Node(
            item_id, self._name(item_id), qty, cost, recipe.name, runs, made, tuple(inputs), crafter=who
        )

    @staticmethod
    def steps(tree: Node, sell_via: str, revenue: int, mail_to: str = "", postage: int = 0) -> list[Step]:
        """Instructions for a craft tree: buy every bought reagent (merged per item and character),
        craft intermediates before what uses them, mailing each to the character who needs it, craft,
        mail the output to `mail_to` if set (`postage` in total), then sell. Sub-crafts are whole
        crafts, so a multi-output intermediate may leave spares."""
        buys: dict[tuple[str, int, str, str], Step] = {}
        crafts: dict[tuple[str, int, str, str], Step] = {}  # craft and mail steps, in walk order

        def add(steps: dict[tuple[str, int, str, str], Step], step: Step) -> None:
            key = (step.action, step.item_id, step.who, step.via)
            had = steps.get(key)
            steps[key] = (
                replace(step, quantity=step.quantity + had.quantity, value=step.value + had.value)
                if had
                else step
            )

        def walk(node: Node) -> None:
            if not node.via:
                add(
                    buys,
                    Step(
                        "buy", node.item_id, node.name, node.quantity, -node.cost, node.source, node.crafter
                    ),
                )
                return
            for n in node.inputs:
                walk(n)
            add(crafts, Step("craft", node.item_id, node.name, node.made, via=node.via, who=node.crafter))
            if node.mail_to:
                add(
                    crafts,
                    Step(
                        "mail",
                        node.item_id,
                        node.name,
                        node.quantity,
                        -node.postage,
                        node.mail_to,
                        node.crafter,
                    ),
                )

        for n in tree.inputs:
            walk(n)
        who = tree.crafter
        return [
            *buys.values(),
            *crafts.values(),
            Step("craft", tree.item_id, tree.name, tree.made, via=tree.via, who=who),
            *([Step("mail", tree.item_id, tree.name, tree.made, -postage, mail_to, who)] if mail_to else []),
            Step("sell", tree.item_id, tree.name, tree.made, revenue, sell_via, mail_to or who),
        ]

    # --- evaluation --------------------------------------------------------------------
    def evaluate(self, recipe: Recipe, choices: Choices | None = None) -> Result | None:
        """The most profitable way to craft and sell `recipe`: over who crafts it, how each reagent
        is had (and mailed), and the exit. `choices` fixes some of those (see `Choices`)."""
        choices = choices or {}
        exits = [e for e in self.exits_for(recipe.output_item_id) if e.kind in self.exits]
        if not exits:
            return None
        memo: Memo = {}
        by_exit: dict[str, Result] = {}  # the most profitable result for each way of selling
        for who in self._who(recipe):
            tree = self._craft(recipe, recipe.output_count, 1, who, 0, frozenset(), memo, ROOT, choices)
            here = self._exits_at(exits, who)
            if tree is None or not here:
                continue
            mail = self.postage(recipe.output_item_id, tree.made)
            for exit in here:
                postage = mail if exit.postage else 0
                revenue = exit.value * recipe.output_count
                had = by_exit.get(exit.kind)
                if had is not None and revenue - tree.cost - postage <= had.profit:
                    continue  # ties keep the earlier crafter
                steps = self.steps(tree, exit.kind, revenue, exit.mail_to, postage)
                by_exit[exit.kind] = Result(
                    recipe,
                    tree.cost + postage,
                    revenue,
                    exit.kind,
                    tree,
                    here,
                    steps,
                    postage,
                    exit.mail_to,
                    who,
                )
        if not by_exit:
            return None
        # stable sort over the exits' order (vendor, ah, disenchant): ties keep the earlier, unmailed one
        ranked = sorted(by_exit.values(), key=lambda r: -r.profit)
        picked = by_exit.get(choices.get(SELL, ""), ranked[0])
        picked.sell_options = [SellOption(r.best_exit, r.profit) for r in ranked]
        return picked

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


def crafters_of(recipe: Recipe, crafters: Iterable[Crafter], include_unlearned: bool) -> list[Crafter]:
    """Who can craft `recipe`: those who learned it, or with `include_unlearned` and nobody having
    learned it, everyone with its profession (as in `recipes_for_characters`)."""
    crafters = list(crafters)
    known = [c for c in crafters if recipe.spell_id in c.known_spells]
    if known or not include_unlearned:
        return known
    return [c for c in crafters if c.has(recipe.skill_name)]


def format_money(copper: int) -> str:
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    return f"{sign}{copper // 10000}g {copper // 100 % 100:02d}s {copper % 100:02d}c"
