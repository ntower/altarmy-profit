import { describe, expect, it } from 'vitest'
import type { FlowNode } from '../api/client'
import { NODE_WIDTH, buildFlow } from './flow'

const bought = (item_id: number, name: string, quantity: number, cost: number): FlowNode => ({
  item_id,
  name,
  quantity,
  cost,
  via: '',
  crafts: 0,
  made: 0,
  source: 'ah',
  inputs: [],
})

// Green Robe from 3 crafted Bolts of Linen (from 6 Linen) and 1 bought Coarse Thread.
const tree: FlowNode = {
  item_id: 3,
  name: 'Green Robe',
  quantity: 1,
  cost: 65,
  via: 'Green Robe',
  crafts: 1,
  made: 1,
  source: '',
  inputs: [
    {
      item_id: 5,
      name: 'Bolt of Linen',
      quantity: 3,
      cost: 60,
      via: 'Bolt of Linen',
      crafts: 3,
      made: 3,
      source: '',
      inputs: [bought(1, 'Linen Cloth', 6, 60)],
    },
    bought(2, 'Coarse Thread', 1, 5),
  ],
}

describe('buildFlow', () => {
  const flow = buildFlow({ tree, best_exit: 'ah', revenue: 500, profit: 435 })
  const byId = new Map(flow.nodes.map((n) => [n.id, n]))

  it('makes one node per tree item plus the sale', () => {
    expect(flow.nodes.map((n) => [n.id, n.type])).toEqual([
      ['r', 'item'],
      ['r.0', 'item'],
      ['r.0.0', 'item'],
      ['r.1', 'item'],
      ['sell', 'sell'],
    ])
    expect(byId.get('r.0')?.data).toMatchObject({ itemId: 5, quantity: 3, via: 'Bolt of Linen', crafts: 3 })
    expect(byId.get('r.1')?.data).toMatchObject({ itemId: 2, source: 'ah', isLeaf: true })
    expect(byId.get('sell')?.data).toMatchObject({ exit: 'ah', revenue: 500, profit: 435 })
  })

  it('points edges from each input to what it is used for, labelled with the quantity', () => {
    expect(flow.edges.map((e) => [e.source, e.target, e.label])).toEqual([
      ['r.0.0', 'r.0', '6x'],
      ['r.0', 'r', '3x'],
      ['r.1', 'r', '1x'],
      ['r', 'sell', '1x'],
    ])
  })

  it('lays out left to right: inputs before the crafts that use them', () => {
    for (const e of flow.edges) {
      const [source, target] = [byId.get(e.source), byId.get(e.target)]
      expect(source!.position.x + NODE_WIDTH).toBeLessThan(target!.position.x)
    }
    for (const n of flow.nodes) expect(n.position.x).toBeGreaterThanOrEqual(0)
    expect(flow.width).toBeGreaterThanOrEqual(4 * NODE_WIDTH)
    expect(flow.height).toBeGreaterThan(0)
  })
})
