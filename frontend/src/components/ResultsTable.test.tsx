import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { FlowNode, RankResult } from '../api/client'
import { linen, robe as robeItem, thread } from '../test/items'
import { renderWithProviders } from '../test/utils'
import { ResultsTable } from './ResultsTable'

const bought = (item_id: number, name: string, quantity: number, cost: number, source = 'ah'): FlowNode => ({
  item_id,
  name,
  quantity,
  cost,
  via: '',
  crafts: 0,
  made: 0,
  source,
  inputs: [],
})

const robe: RankResult = {
  recipe_id: 100,
  recipe: 'Green Robe',
  profession: 'Tailoring',
  crafters: ['Tailor Guy'],
  output_item_id: 3,
  output_name: 'Green Robe',
  output_count: 1,
  cost: 300,
  revenue: 500,
  profit: 200,
  roi: 2 / 3,
  best_exit: 'vendor',
  exits: [
    { kind: 'vendor', value: 500, materials: [] },
    { kind: 'ah', value: 475, materials: [] },
  ],
  reagents: [
    { item_id: 1, count: 10 },
    { item_id: 2, count: 1 },
  ],
  steps: [
    { action: 'buy', item_id: 1, name: 'Linen Cloth', quantity: 10, value: -200, via: 'ah' },
    { action: 'buy', item_id: 2, name: 'Coarse Thread', quantity: 1, value: -100, via: 'vendor' },
    { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe' },
    { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 500, via: 'vendor' },
  ],
  tree: {
    item_id: 3,
    name: 'Green Robe',
    quantity: 1,
    cost: 300,
    via: 'Green Robe',
    crafts: 1,
    made: 1,
    source: '',
    inputs: [bought(1, 'Linen Cloth', 10, 200), bought(2, 'Coarse Thread', 1, 100, 'vendor')],
  },
}

const items = { '1': linen, '2': thread, '3': robeItem }

const disenchanted: RankResult = {
  ...robe,
  recipe_id: 101,
  best_exit: 'disenchant',
  revenue: 75988,
  exits: [
    { kind: 'vendor', value: 500, materials: [] },
    {
      kind: 'disenchant',
      value: 75988,
      materials: [
        { item_id: 1, name: 'Linen Cloth', chance: 0.75, min_count: 1, max_count: 2, value: 75988 },
        { item_id: 2, name: 'Coarse Thread', chance: 0.25, min_count: 1, max_count: 1, value: null },
      ],
    },
  ],
  steps: [
    { action: 'buy', item_id: 4, name: 'Medium Hide', quantity: 2, value: -12648, via: 'ah' },
    { action: 'craft', item_id: 5, name: 'Cured Medium Hide', quantity: 2, value: 0, via: 'Cure' },
    { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe' },
    { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 75988, via: 'disenchant' },
  ],
}

/** Checks the open disenchant tooltip lists both materials and the expected total. */
async function expectDisenchantTooltip() {
  const text = (t: string) => screen.findByText((_, el) => el?.textContent === t)
  expect(await text('Disenchanting Green Robe')).toBeInTheDocument()
  expect(await text('Linen Cloth ×1-2 (75%)')).toBeInTheDocument()
  expect(await text('Coarse Thread ×1 (25%)')).toBeInTheDocument()
  expect(await text('no price')).toBeInTheDocument()
  expect(await text('Expected: 7 59 88')).toBeInTheDocument()
}

/** A list item or table cell whose whole text is `text` (item names inside are separate elements). */
const line = (text: string) =>
  screen.getByText((_, el) => (el?.tagName === 'LI' || el?.tagName === 'TD') && el.textContent === text)

const showSteps = async (nth = 0) => await userEvent.click(screen.getAllByText('Steps')[nth])

describe('ResultsTable', () => {
  it('formats money, ROI and output', () => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    expect(screen.getByText('0g 02s 00c')).toBeInTheDocument()
    expect(screen.getByText('67%')).toBeInTheDocument()
    expect(line('1x Green Robe')).toBeInTheDocument()
    expect(screen.getByText('0g 03s 00c')).toBeInTheDocument()
    expect(screen.queryByText(/Purchase/)).not.toBeInTheDocument()
  })

  it('names the characters who know the recipe', () => {
    renderWithProviders(<ResultsTable results={[robe, { ...robe, recipe_id: 101, crafters: [] }]} items={items} />)
    expect(screen.getByText('Tailor Guy')).toBeInTheDocument()
    expect(screen.getByText('not learned')).toBeInTheDocument()
  })

  it('expands a row into a flow chart of the reagents, crafts and sale', async () => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    expect(screen.getByText('Buy on the AH · -0g 02s 00c')).toBeInTheDocument()
    expect(screen.getByText('Buy from a vendor · -0g 01s 00c')).toBeInTheDocument()
    expect(screen.getByText('Craft 1x Green Robe')).toBeInTheDocument()
    expect(screen.getByText('Sell to a vendor')).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.textContent === '+0g 05s 00c · profit 0g 02s 00c')).toBeInTheDocument()
    expect(screen.queryByText(/Purchase/)).not.toBeInTheDocument()
  })

  it('shows step-by-step instructions on the Steps tab', async () => {
    renderWithProviders(<ResultsTable results={[robe, disenchanted]} items={items} />)
    const [first, second] = screen.getAllByRole('button', { name: 'Details for Green Robe' })

    await userEvent.click(first)
    expect(first).toHaveAttribute('aria-expanded', 'true')
    await showSteps()
    expect(line('Purchase 10x Linen Cloth on the AH (-0g 02s 00c)')).toBeInTheDocument()
    expect(line('Purchase 1x Coarse Thread from a vendor (-0g 01s 00c)')).toBeInTheDocument()
    expect(line('Craft 1x Green Robe')).toBeInTheDocument()
    expect(line('Sell 1x Green Robe to a vendor (+0g 05s 00c)')).toBeInTheDocument()

    await userEvent.click(second)
    await showSteps(1)
    expect(line('Purchase 2x Medium Hide on the AH (-1g 26s 48c)')).toBeInTheDocument()
    expect(line('Craft 2x Cured Medium Hide')).toBeInTheDocument()
    expect(line('Disenchant Green Robe')).toBeInTheDocument()
    expect(line('Sell materials (+7g 59s 88c)')).toBeInTheDocument()
  })

  it('shows the expected disenchant materials on the Steps sell line', async () => {
    renderWithProviders(<ResultsTable results={[disenchanted]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    await showSteps()
    await userEvent.hover(screen.getByText('Sell materials'))
    await expectDisenchantTooltip()
  })

  it('shows the expected disenchant materials on the flow chart sell node', async () => {
    renderWithProviders(<ResultsTable results={[disenchanted]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    await userEvent.hover(screen.getByText('Disenchant, sell the materials'))
    await expectDisenchantTooltip()
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

  it.each([false, true])('links flow and step items to their tooltips (steps: %s)', async (steps) => {
    renderWithProviders(<ResultsTable results={[robe]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    if (steps) await showSteps()
    await userEvent.hover(screen.getByText('Linen Cloth'))
    expect(await screen.findByText((_, el) => el?.textContent === 'Auction: 20')).toBeInTheDocument()
  })
})
