import { describe, expect, it } from 'vitest'
import { formatRoi, goldToCopper } from './money'

describe('goldToCopper', () => {
  it('rounds to whole copper', () => {
    expect(goldToCopper(1.5)).toBe(15000)
    expect(goldToCopper(0.00016)).toBe(2)
  })
})

describe('formatRoi', () => {
  it('shows a whole percentage', () => {
    expect(formatRoi(2 / 3)).toBe('67%')
    expect(formatRoi(0)).toBe('0%')
  })
})
