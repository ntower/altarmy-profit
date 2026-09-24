import type { ItemInfo } from '../api/client'

/** An ItemInfo with every field empty, for tests to override. */
export function makeItem(overrides: Partial<ItemInfo> & Pick<ItemInfo, 'id' | 'name'>): ItemInfo {
  return {
    quality: 1,
    class_id: 0,
    subclass_name: null,
    inventory_type: 0,
    bonding: 0,
    item_delay: 0,
    container_slots: 0,
    required_level: 0,
    required_skill: null,
    required_skill_rank: 0,
    description: null,
    sell_price: 0,
    icon: null,
    ah_price: null,
    ...overrides,
  }
}

export const linen = makeItem({ id: 1, name: 'Linen Cloth', sell_price: 13, ah_price: 20 })
export const thread = makeItem({ id: 2, name: 'Coarse Thread', sell_price: 10 })
export const robe = makeItem({
  id: 3,
  name: 'Green Robe',
  quality: 2,
  class_id: 4,
  subclass_name: 'Cloth',
  inventory_type: 20,
  bonding: 2,
  required_level: 12,
  required_skill: 'Tailoring',
  required_skill_rank: 50,
  description: 'Soft and green.',
  sell_price: 216,
  icon: 'inv_chest_cloth_39',
})
