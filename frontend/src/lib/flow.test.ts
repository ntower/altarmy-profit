import { describe, expect, it } from 'vitest'
import type { FlowNode } from '../api/client'
import { bought } from '../test/results'
import { NAMED_NODE_HEIGHT, NODE_HEIGHT, NODE_WIDTH, buildFlow } from './flow'

const boltOptions: FlowNode['options'] = [
  { key: 'craft:11', cost: 60, source: '', via: 'Bolt of Linen', crafter: '' },
  { key: 'ah', cost: 300, source: 'ah', via: '', crafter: '' },
]

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
  crafter: '',
  mail_to: '',
  postage: 0,
  options: [],
  option: '',
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
      crafter: '',
      mail_to: '',
      postage: 0,
      options: boltOptions,
      option: 'craft:11',
      inputs: [bought(1, 'Linen Cloth', 6, 60)],
    },
    bought(2, 'Coarse Thread', 1, 5),
  ],
}

describe('buildFlow', () => {
  const sellOptions = [
    { kind: 'ah', profit: 435 },
    { kind: 'vendor', profit: 100 },
  ]
  const sale = { best_exit: 'ah', revenue: 500, profit: 435, postage: 0, mail_to: '', sell_options: sellOptions }
  const flow = buildFlow({ tree, ...sale })
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

  it('gives item nodes their path and options, and the sale its exits', () => {
    expect(byId.get('r')?.data).toMatchObject({ path: 'r', options: [], option: '' })
    expect(byId.get('r.0')?.data).toMatchObject({ path: 'r.0', options: boltOptions, option: 'craft:11', holder: '' })
    expect(byId.get('r.0.0')?.data).toMatchObject({ path: 'r.0.0', option: 'ah' })
    expect(byId.get('sell')?.data).toMatchObject({ options: sellOptions })
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
    expect(flow.nodes.every((n) => n.height === NODE_HEIGHT)).toBe(true) // no character names
    expect(flow.width).toBeGreaterThanOrEqual(4 * NODE_WIDTH)
    expect(flow.height).toBeGreaterThan(0)
  })

  it('mails an intermediate crafted by another character to the one who uses it', () => {
    const [bolt, thread] = tree.inputs
    const split: FlowNode = {
      ...tree,
      crafter: 'Smithy',
      inputs: [{ ...bolt!, crafter: 'Weaver', mail_to: 'Smithy', postage: 30 }, thread!],
    }
    const flow = buildFlow({ ...sale, tree: split, profit: 405 })
    expect(flow.nodes.find((n) => n.id === 'r.0.mail')).toMatchObject({
      type: 'mail',
      data: { to: 'Smithy', postage: 30, quantity: 3 },
    })
    // Smithy holds the bolts in the end: another source would be bought by, or mailed to, Smithy
    expect(flow.nodes.find((n) => n.id === 'r.0')?.data).toMatchObject({ crafter: 'Weaver', holder: 'Smithy' })
    expect(flow.nodes.every((n) => n.height === NAMED_NODE_HEIGHT)).toBe(true)
    expect(flow.edges.map((e) => [e.source, e.target, e.label])).toEqual([
      ['r.0.0', 'r.0', '6x'],
      ['r.0', 'r.0.mail', '3x'],
      ['r.0.mail', 'r', '3x'],
      ['r.1', 'r', '1x'],
      ['r', 'sell', '1x'],
    ])
  })

  it('mails the output to an enchanter before the sale', () => {
    const mailed = buildFlow({
      ...sale,
      tree,
      best_exit: 'disenchant',
      revenue: 500,
      profit: 405,
      postage: 30,
      mail_to: 'Enchy',
    })
    expect(mailed.nodes.find((n) => n.id === 'sell')?.data).toMatchObject({ seller: 'Enchy' })
    expect(mailed.nodes.find((n) => n.id === 'r.mail')).toMatchObject({
      type: 'mail',
      data: { to: 'Enchy', postage: 30, quantity: 1 },
    })
    expect(mailed.edges.slice(-2).map((e) => [e.source, e.target, e.label])).toEqual([
      ['r', 'r.mail', '1x'],
      ['r.mail', 'sell', '1x'],
    ])
  })
})
