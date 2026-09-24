import { describe, expect, it } from 'vitest'
import { choose } from './choices'

describe('choose', () => {
  it('sets the pick and drops picks inside that branch only', () => {
    const before = { 'r.0': 'craft:20', 'r.0.0': 'ah', 'r.0.10': 'vendor', 'r.1': 'ah', sell: 'vendor' }
    expect(choose(before, 'r.0', 'ah')).toEqual({ 'r.0': 'ah', 'r.1': 'ah', sell: 'vendor' })
    expect(choose(before, 'r.0.1', 'ah')).toEqual({ ...before, 'r.0.1': 'ah' })
    expect(choose({}, 'sell', 'disenchant')).toEqual({ sell: 'disenchant' })
  })
})
