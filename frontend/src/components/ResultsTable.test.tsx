import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RankResult } from '../api/client'
import { renderWithProviders } from '../test/utils'
import { ResultsTable } from './ResultsTable'

const robe: RankResult = {
  recipe_id: 100,
  recipe: 'Green Robe',
  profession: 'Tailoring',
  output_item_id: 3,
  output_name: 'Green Robe',
  output_count: 1,
  cost: 300,
  revenue: 500,
  profit: 200,
  roi: 2 / 3,
  best_exit: 'vendor',
  exits: [
    { kind: 'vendor', value: 500 },
    { kind: 'ah', value: 475 },
  ],
  chain: [],
}

describe('ResultsTable', () => {
  it('formats money, ROI and output', () => {
    renderWithProviders(<ResultsTable results={[robe]} />)
    expect(screen.getByText('0g 02s 00c')).toBeInTheDocument()
    expect(screen.getByText('67%')).toBeInTheDocument()
    expect(screen.getByText('1x Green Robe')).toBeInTheDocument()
    expect(screen.getByText('0g 03s 00c')).toBeInTheDocument()
    expect(screen.queryByText('buy all reagents')).not.toBeInTheDocument()
  })

  it('expands a row to show the chain and sell options', async () => {
    const chained = { ...robe, recipe_id: 101, chain: ['2x Bolt of Linen Cloth via Bolt of Linen Cloth'] }
    renderWithProviders(<ResultsTable results={[robe, chained]} />)
    const [first, second] = screen.getAllByRole('button', { name: 'Details for Green Robe' })

    await userEvent.click(first)
    expect(first).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('buy all reagents')).toBeInTheDocument()
    expect(screen.getByText('ah: 0g 04s 75c')).toBeInTheDocument()

    await userEvent.click(second)
    expect(screen.getByText('2x Bolt of Linen Cloth via Bolt of Linen Cloth')).toBeInTheDocument()
  })
})
