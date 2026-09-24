import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { shown } from '../test/utils'
import { Money } from './Money'

const coins = () => screen.getAllByTitle(/gold|silver|copper/).map((c) => [c.title, shown(c)])

describe('Money', () => {
  it('shows each non-zero denomination as an amount with its coin', () => {
    const { container } = render(<Money copper={123456} />)
    expect(shown(container)).toBe('12 34 56')
    expect(coins()).toEqual([
      ['gold', '12'],
      ['silver', '34'],
      ['copper', '56'],
    ])
  })

  it('keeps zero coins below the largest one, so amounts line up', () => {
    render(<Money copper={10003} />)
    expect(coins()).toEqual([
      ['gold', '1'],
      ['silver', '0'],
      ['copper', '3'],
    ])
  })

  it('shows zero as 0 copper', () => {
    const { container } = render(<Money copper={0} />)
    expect(shown(container)).toBe('0')
    expect(coins()).toEqual([['copper', '0']])
  })

  it('prefixes losses with - and, when signed, gains with +', () => {
    expect(shown(render(<Money copper={-250} />).container)).toBe('-2 50')
    expect(shown(render(<Money copper={250} signed />).container)).toBe('+2 50')
    expect(shown(render(<Money copper={0} signed />).container)).toBe('0')
  })

  it('pads single-digit silver and copper with a non-breaking space when padded', () => {
    expect(shown(render(<Money copper={10003} padded />).container)).toBe('1 _0 _3')
    expect(shown(render(<Money copper={1234567} padded />).container)).toBe('123 45')
  })

  it('shows a cost in red without a sign', () => {
    const { container } = render(<Money copper={250} cost />)
    expect(shown(container)).toBe('2 50')
    expect(container.firstElementChild).toHaveAttribute('data-cost')
  })
})
