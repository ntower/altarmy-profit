/** Game-data lookups for item tooltips. Codes follow the client's DB2 enums (ItemSparse, Item). */

import type { ItemInfo } from '../api/client'

/** In-game item quality colours, indexed by quality (0 poor .. 7 heirloom). */
export const QUALITY_COLORS = [
  '#9d9d9d',
  '#ffffff',
  '#1eff00',
  '#0070dd',
  '#a335ee',
  '#ff8000',
  '#e6cc80',
  '#00ccff',
] as const

/** Equip slot names by InventoryType, as the tooltip's left-hand slot line shows them. */
export const INVENTORY_TYPES: Readonly<Record<number, string>> = {
  1: 'Head',
  2: 'Neck',
  3: 'Shoulder',
  4: 'Shirt',
  5: 'Chest',
  6: 'Waist',
  7: 'Legs',
  8: 'Feet',
  9: 'Wrist',
  10: 'Hands',
  11: 'Finger',
  12: 'Trinket',
  13: 'One-Hand',
  14: 'Off Hand',
  15: 'Ranged',
  16: 'Back',
  17: 'Two-Hand',
  19: 'Tabard',
  20: 'Chest',
  21: 'Main Hand',
  22: 'Off Hand',
  23: 'Held In Off-hand',
  24: 'Projectile',
  25: 'Thrown',
  26: 'Ranged',
  28: 'Relic',
}

const ITEM_CLASS = { container: 1, weapon: 2, armor: 4, quiver: 11 } as const

const BINDINGS: Readonly<Record<number, string>> = {
  1: 'Binds when picked up',
  2: 'Binds when equipped',
  3: 'Binds when used',
  4: 'Quest Item',
}

export const bindingText = (bonding: number): string | undefined => BINDINGS[bonding]

/** Icon image on Wowhead's CDN; `small` is 18px, `medium` 36px, `large` 56px. */
export function iconUrl(icon: string, size: 'small' | 'medium' | 'large'): string {
  return `https://wow.zamimg.com/images/wow/icons/${size}/${icon}.jpg`
}

/** Copper split into the coins a tooltip shows; zero denominations are dropped (0 shows as 0 copper). */
export function splitMoney(copper: number): { unit: 'gold' | 'silver' | 'copper'; amount: number }[] {
  const parts = [
    { unit: 'gold' as const, amount: Math.floor(copper / 10000) },
    { unit: 'silver' as const, amount: Math.floor(copper / 100) % 100 },
    { unit: 'copper' as const, amount: copper % 100 },
  ].filter((p) => p.amount > 0)
  return parts.length ? parts : [{ unit: 'copper', amount: 0 }]
}

/** The slot line: left "Chest", right "Cloth". Undefined for items that are not equipment or bags. */
export function slotLine(item: ItemInfo): { left: string; right?: string } | undefined {
  if (item.class_id === ITEM_CLASS.container || item.class_id === ITEM_CLASS.quiver) {
    if (!item.container_slots) return undefined
    return { left: `${item.container_slots} Slot ${item.subclass_name ?? 'Bag'}` }
  }
  const slot = INVENTORY_TYPES[item.inventory_type]
  if (!slot) return undefined
  const showSubclass =
    (item.class_id === ITEM_CLASS.weapon || item.class_id === ITEM_CLASS.armor) &&
    item.inventory_type !== 16 && // cloaks are all Cloth; the game shows just "Back"
    item.subclass_name !== 'Miscellaneous'
  return { left: slot, right: showSubclass ? (item.subclass_name ?? undefined) : undefined }
}

/** Weapon speed as the tooltip shows it ("Speed 2.50"), or undefined. */
export const speedText = (item: ItemInfo): string | undefined =>
  item.class_id === ITEM_CLASS.weapon && item.item_delay > 0
    ? `Speed ${(item.item_delay / 1000).toFixed(2)}`
    : undefined
