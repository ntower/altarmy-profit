# Roadmap ideas

Where `altarmy-profit` could go beyond a per-recipe profit ranker. Written after a review of the
engine, service, web UI and the [Alt Army](../../altarmy_tbc) addon's data stores on 2026-09-24.
Shipped behaviour is described in [README.md](../README.md); this file is about what is not built.

## Where it stands

The engine is a solid per-recipe optimizer: multi-character costing with mailing, chains up to three
deep, editable plans in the flow chart, and vendor / AH / disenchant exits. Its two big limits:

1. **It prices from a single min-buyout snapshot.** Profit assumes you buy and sell unlimited units at
   today's lowest listing, with no deposit, undercutting or unsold risk.
2. **It knows nothing about what your characters own.** Alt Army records bags, bank, mail and owned
   auctions, but the app only reads professions and learned recipes.

Both are fixable with data that is already collected.

## Suggested order

| # | Theme | Why first |
|---|-------|-----------|
| 1 | Inventory-aware costing | Data already in `AltArmy_TBC.lua`; turns "profitable in theory" into "craftable now" |
| 2 | Price history and realistic sell price | Biggest accuracy gain; Auctionator already stores the fields |
| 3 | Craft queue, shopping list, addon round trip | Turns rankings into a plan the addon can execute |
| 4 | Non-crafting arbitrage | Disenchant shuffle and vendor flips reuse the existing exit model |
| 5 | Cooldown board and dashboard | Reliable daily gold; ties the views together |
| 6 | vmangos-backed game data | Trustworthy disenchant rates, recipe sources, skill-up planning |

At Forever's launch scans will be thin and prices volatile, so the history and confidence work pays
off earlier than the planning features.

## 1. Use the data Alt Army already has

### Inventory-aware costing

- Read each character's containers, bank, mail and owned auctions from `AltArmyTBC_Data.Characters`
  (`Containers`, `Mails`/`MailCache`, auctions) in `altarmy.py`; store them per character.
- Pass stock into `engine.Market` so a reagent a character holds costs nothing to buy, or its AH value
  as opportunity cost (a toggle). Buy steps then show only the shortfall.
- New views this enables: "craftable now without buying", and a bank audit of items sitting on alts
  that are worth more crafted or sold than kept.

### Cooldown board

- Alt Army tracks profession cooldown expiry per character (`ProfCooldownExpiry`). Vanilla-based
  Forever has Arcanite transmute and Mooncloth as the main cooldown crafts.
- Show profit per cooldown, who is ready and when, and what to mail them. The engine already costs a
  craft at a given character, so this is mostly a filter and a schedule.

### Realized results

- The addon records each character's gold (`money`) and their owned auctions with sold status.
  Append both on every sync (never replace) to build gold history per character and account.
- Compare sold auctions against past recommendations: a feedback loop on which suggestions actually
  sell. Alt Army's roadmap lists gold history as unbuilt; the web app is a better home for it.

## 2. Fix the market model

### Keep price history

- `auctionator.parse_price_database` keeps only `m` (latest min buyout) and drops the per-day `h`,
  `l` and `a` fields (high, low, available). Parse them and store one row per item per scan day
  instead of replacing the `prices` table on every sync.
- Uses: per-item price charts in the tooltip, trend arrows in results, and a stale-price warning when
  an item has not been seen for days.

### Realistic sell price and depth

- Replace "current min buyout" with a trailing median or percentile as the sell price, subtract the
  deposit, and estimate sell chance from availability. Rank by expected value (profit x sell chance)
  with the optimistic figure shown alongside.
- Bound buy quantities by observed availability once plans cover more than one craft.
- Keep the engine pure: pass a `PriceStats` per item into `Market` rather than raw history.

## 3. From ranking to planning

### Craft queue and shopping list

- Let the user add results with a quantity. Merge steps across the queue into one list per
  character: AH buys, vendor buys, crafts in dependency order, mails and recipient.
  `Market.steps` already merges buys per character for a single craft.
- Persist the queue in SQLite so it survives restarts and syncs.

### Round trip to the addon

- Write the plan as a Lua data file into the addon folder (`AltArmy_TBC/PlanData.lua` or similar,
  listed in the `.toc`), the way TradeSkillMaster's desktop app does. The addon loads it on `/reload`.
- Alt Army already has stockpile mailing (`StockpilePlan`) and a mailbox-driven send flow; the plan
  can drive it and show an in-game checklist. Its roadmap item "craft queue and material planner"
  splits naturally as: web app plans, addon executes.

### Non-crafting arbitrage

- Add "buy on the AH" as a tree root instead of a recipe so the existing exits apply to bought items:
  the disenchant shuffle (buy greens, disenchant, sell materials), vendor flips (buy from a vendor,
  sell on the AH), and listings below vendor sell price.
- These need no new pricing data and reuse `exits_for` and the disenchant model as they stand.

## 4. Dashboard

- A home tab: gold per character, cooldowns ready, own auctions expiring, top opportunities, and
  freshness of the price and character data.
- Goal: the app is what you open before logging in, not a search you run occasionally.

## 5. Deeper game data

### Disenchant rates from vmangos

- `data/disenchant.csv` is hand-filled brackets. vmangos ships disenchant loot templates keyed from its
  item table, and `vmangos.py` already reads its vendor data. Generate the CSV the same way
  (`scripts/build_disenchant.py`) so disenchant values are trustworthy.

### Recipe acquisition ROI

- With unlearned recipes included the app says a recipe is profitable but not how to get it.
- vmangos trainer tables give trainer recipes and their cost; DB2 learn-spell effects link recipe items
  to craft spells, so AH-listed recipes can be priced from the same scan.
- Rank unlearned recipes by profit per craft (times expected volume) against acquisition cost:
  "which recipe should I go buy tonight". Overlaps Alt Army's "recipe gap intelligence" idea.

### Skill-up planner

- Trivial thresholds are ingested; `min_skill` is not usable yet (see README data notes).
- Given a character and a target skill, find the cheapest path priced from the user's AH, net of
  reselling the crafts. The trivial-only toggle is the first step toward this.

### Alt planning

- With professions, recipe coverage and inventory known, a coverage matrix could suggest which
  profession a new alt should take to fill gaps in the crafting chains.

## Constraints to keep

- `engine.py` stays pure: history, stock and stats are loaded in `store.py` and passed as dataclasses.
- Money stays integer copper end to end.
- Alt Army stays the only in-game collector; this app never needs its own addon.
