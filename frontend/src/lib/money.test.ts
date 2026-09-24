import { describe, expect, it } from 'vitest'
import { formatMoney, formatRoi, goldToCopper } from './money'

describe('formatMoney', () => {
  it('matches engine.format_money', () => {
    expect(formatMoney(0)).toBe('0g 00s 00c')
    expect(formatMoney(200)).toBe('0g 02s 00c')
    expect(formatMoney(123456)).toBe('12g 34s 56c')
    expect(formatMoney(-10203)).toBe('-1g 02s 03c')
  })
})

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
