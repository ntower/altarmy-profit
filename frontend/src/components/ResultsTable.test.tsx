import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RankResult } from '../api/client'
import { linen, robe as robeItem, thread } from '../test/items'
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
  reagents: [
    { item_id: 1, count: 10 },
    { item_id: 2, count: 1 },
  ],
  steps: [
    { action: 'buy', item_id: 1, name: 'Linen Cloth', quantity: 10, value: -200, via: '' },
    { action: 'buy', item_id: 2, name: 'Coarse Thread', quantity: 1, value: -100, via: '' },
    { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe' },
    { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 500, via: 'vendor' },
  ],
}

const items = { '1': linen, '2': thread, '3': robeItem }

/** A list item or table cell whose whole text is `text` (item names inside are separate elements). */
const line = (text: string) =>
  screen.getByText((_, el) => (el?.tagName === 'LI' || el?.tagName === 'TD') && el.textContent === text)

describe('ResultsTable', () => {
  it('formats money, ROI and output', () => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    expect(screen.getByText('0g 02s 00c')).toBeInTheDocument()
    expect(screen.getByText('67%')).toBeInTheDocument()
    expect(line('1x Green Robe')).toBeInTheDocument()
    expect(screen.getByText('0g 03s 00c')).toBeInTheDocument()
    expect(screen.queryByText(/Purchase/)).not.toBeInTheDocument()
  })

  it('expands a row into step-by-step instructions', async () => {
    const disenchanted: RankResult = {
      ...robe,
      recipe_id: 101,
      best_exit: 'disenchant',
      steps: [
        { action: 'buy', item_id: 4, name: 'Medium Hide', quantity: 2, value: -12648, via: '' },
        { action: 'craft', item_id: 5, name: 'Cured Medium Hide', quantity: 2, value: 0, via: 'Cure' },
        { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe' },
        { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 75988, via: 'disenchant' },
      ],
    }
    renderWithProviders(<ResultsTable results={[robe, disenchanted]} items={items} />)
    const [first, second] = screen.getAllByRole('button', { name: 'Details for Green Robe' })

    await userEvent.click(first)
    expect(first).toHaveAttribute('aria-expanded', 'true')
    expect(line('Purchase 10x Linen Cloth on the AH (-0g 02s 00c)')).toBeInTheDocument()
    expect(line('Craft 1x Green Robe')).toBeInTheDocument()
    expect(line('Sell 1x Green Robe to a vendor (+0g 05s 00c)')).toBeInTheDocument()

    await userEvent.click(second)
    expect(line('Purchase 2x Medium Hide on the AH (-1g 26s 48c)')).toBeInTheDocument()
    expect(line('Craft 2x Cured Medium Hide')).toBeInTheDocument()
    expect(line('Disenchant Green Robe')).toBeInTheDocument()
    expect(screen.getByText('Sell materials (+7g 59s 88c)')).toBeInTheDocument()
  })

  it('shows the item tooltip on the output and the recipe tooltip on the recipe', async () => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    const [recipe, output] = screen.getAllByText('Green Robe')
    await userEvent.hover(output)
    expect(await screen.findByText('Binds when equipped')).toBeInTheDocument()
    await userEvent.unhover(output)

    await userEvent.hover(recipe)
    expect(await screen.findByText('Reagents: Linen Cloth (10), Coarse Thread')).toBeInTheDocument()
  })

  it('links step items to their tooltips', async () => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    await userEvent.hover(screen.getByText('Linen Cloth'))
    expect(await screen.findByText((_, el) => el?.textContent === 'Auction: 20')).toBeInTheDocument()
  })
})
