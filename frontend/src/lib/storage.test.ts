import { describe, expect, it } from 'vitest'
import { z } from 'zod'
import { parseStored } from './storage'

describe('parseStored', () => {
  const schema = z.array(z.string())

  it('returns valid stored values', () => {
    expect(parseStored(schema, '["Tailoring"]', [])).toEqual(['Tailoring'])
  })

  it('falls back on missing, unparsable or invalid values', () => {
    expect(parseStored(schema, undefined, ['x'])).toEqual(['x'])
    expect(parseStored(schema, 'not json', ['x'])).toEqual(['x'])
    expect(parseStored(schema, '[1, 2]', ['x'])).toEqual(['x'])
  })
})
