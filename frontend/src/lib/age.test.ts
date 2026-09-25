import { describe, expect, it } from 'vitest'
import { age } from './age'

describe('age', () => {
  const now = new Date('2026-09-24T12:00:00Z')

  it('rounds down to minutes, hours or days', () => {
    expect(age('2026-09-24 11:59:40', now)).toBe('just now')
    expect(age('2026-09-24 11:55:00', now)).toBe('5 min ago')
    expect(age('2026-09-24 09:00:00', now)).toBe('3 h ago')
    expect(age('2026-09-22 11:00:00', now)).toBe('2 days ago')
  })

  it('shows what it cannot read as it is', () => {
    expect(age('garbage', now)).toBe('garbage')
  })
})
