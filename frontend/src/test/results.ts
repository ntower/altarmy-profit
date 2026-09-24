import type { FlowNode, RankResult } from '../api/client'

/** A bought reagent; with no `options`, buying it `source` is its only option. */
export const bought = (
  item_id: number,
  name: string,
  quantity: number,
  cost: number,
  source = 'ah',
  options: FlowNode['options'] = [{ key: source, cost, source, via: '', crafter: '' }],
): FlowNode => ({
  item_id,
  name,
  quantity,
  cost,
  via: '',
  crafts: 0,
  made: 0,
  source,
  crafter: '',
  mail_to: '',
  postage: 0,
  options,
  option: source,
  inputs: [],
})

/** Green Robe: 10 linen (AH) + 1 thread (vendor, or 1s 50c on the AH), sold to a vendor for 200 profit
 * (or 175 on the AH). */
export const robeResult: RankResult = {
  recipe_id: 100,
  recipe: 'Green Robe',
  profession: 'Tailoring',
  crafters: ['Tailor Guy'],
  crafter: 'Tailor Guy',
  output_item_id: 3,
  output_name: 'Green Robe',
  output_count: 1,
  cost: 300,
  revenue: 500,
  profit: 200,
  roi: 2 / 3,
  best_exit: 'vendor',
  postage: 0,
  mail_to: '',
  exits: [
    { kind: 'vendor', value: 500, materials: [], postage: 0, mail_to: '' },
    { kind: 'ah', value: 475, materials: [], postage: 0, mail_to: '' },
  ],
  reagents: [
    { item_id: 1, count: 10 },
    { item_id: 2, count: 1 },
  ],
  steps: [
    { action: 'buy', item_id: 1, name: 'Linen Cloth', quantity: 10, value: -200, via: 'ah', who: '' },
    { action: 'buy', item_id: 2, name: 'Coarse Thread', quantity: 1, value: -100, via: 'vendor', who: '' },
    { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe', who: '' },
    { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 500, via: 'vendor', who: '' },
  ],
  tree: {
    item_id: 3,
    name: 'Green Robe',
    quantity: 1,
    cost: 300,
    via: 'Green Robe',
    crafts: 1,
    made: 1,
    source: '',
    crafter: '',
    mail_to: '',
    postage: 0,
    options: [],
    option: '',
    inputs: [
      bought(1, 'Linen Cloth', 10, 200),
      bought(2, 'Coarse Thread', 1, 100, 'vendor', [
        { key: 'vendor', cost: 100, source: 'vendor', via: '', crafter: '' },
        { key: 'ah', cost: 150, source: 'ah', via: '', crafter: '' },
      ]),
    ],
  },
  sell_options: [
    { kind: 'vendor', profit: 200 },
    { kind: 'ah', profit: 175 },
  ],
}
