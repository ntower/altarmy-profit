import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RankResult } from '../api/client'
import { linen, robe as robeItem, thread } from '../test/items'
import { bought, robeResult as robe } from '../test/results'
import { mockApi, renderWithProviders } from '../test/utils'
import { ResultsTable } from './ResultsTable'

const items = { '1': linen, '2': thread, '3': robeItem }

const disenchanted: RankResult = {
  ...robe,
  recipe_id: 101,
  best_exit: 'disenchant',
  revenue: 75988,
  postage: 30,
  mail_to: 'Enchy',
  exits: [
    { kind: 'vendor', value: 500, materials: [], postage: 0, mail_to: '' },
    {
      kind: 'disenchant',
      value: 75988,
      postage: 30,
      mail_to: 'Enchy',
      materials: [
        { item_id: 1, name: 'Linen Cloth', chance: 0.75, min_count: 1, max_count: 2, value: 75988 },
        { item_id: 2, name: 'Coarse Thread', chance: 0.25, min_count: 1, max_count: 1, value: null },
      ],
    },
  ],
  steps: [
    { action: 'buy', item_id: 4, name: 'Medium Hide', quantity: 2, value: -12648, via: 'ah', who: '' },
    { action: 'craft', item_id: 5, name: 'Cured Medium Hide', quantity: 2, value: 0, via: 'Cure', who: '' },
    { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe', who: '' },
    { action: 'mail', item_id: 3, name: 'Green Robe', quantity: 1, value: -30, via: 'Enchy', who: '' },
    { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 75988, via: 'disenchant', who: '' },
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
    // flow chart item names truncate rather than push the quantity out of the box
    expect(screen.getByText('Linen Cloth').closest('[data-truncate]')).not.toBeNull()
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
    expect(line('Mail 1x Green Robe to Enchy (-0g 00s 30c)')).toBeInTheDocument()
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

  it('names who does each step and mails intermediates between them', async () => {
    const split: RankResult = {
      ...robe,
      recipe_id: 102,
      crafter: 'Smithy',
      steps: [
        { action: 'buy', item_id: 1, name: 'Linen Cloth', quantity: 6, value: -120, via: 'ah', who: 'Leathery' },
        { action: 'craft', item_id: 2, name: 'Coarse Thread', quantity: 2, value: 0, via: 'Thread', who: 'Leathery' },
        { action: 'mail', item_id: 2, name: 'Coarse Thread', quantity: 2, value: -30, via: 'Smithy', who: 'Leathery' },
        { action: 'craft', item_id: 3, name: 'Green Robe', quantity: 1, value: 0, via: 'Green Robe', who: 'Smithy' },
        { action: 'sell', item_id: 3, name: 'Green Robe', quantity: 1, value: 500, via: 'vendor', who: 'Smithy' },
      ],
    }
    renderWithProviders(<ResultsTable results={[split]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    await showSteps()
    expect(line('Leathery: Purchase 6x Linen Cloth on the AH (-0g 01s 20c)')).toBeInTheDocument()
    expect(line('Leathery: Craft 2x Coarse Thread')).toBeInTheDocument()
    expect(line('Leathery: Mail 2x Coarse Thread to Smithy (-0g 00s 30c)')).toBeInTheDocument()
    expect(line('Smithy: Craft 1x Green Robe')).toBeInTheDocument()
    expect(line('Smithy: Sell 1x Green Robe to a vendor (+0g 05s 00c)')).toBeInTheDocument()
  })

  it('shows the chosen crafter first among those who know the recipe, in class colours', () => {
    renderWithProviders(
      <ResultsTable
        results={[{ ...robe, crafters: ['Alice', 'Tailor Guy'] }]}
        items={items}
        classes={{ 'Tailor Guy': 'MAGE', Alice: 'ROGUE' }}
      />,
    )
    expect(line('Tailor Guy, Alice')).toBeInTheDocument()
    expect(screen.getByText('Tailor Guy')).toHaveAttribute('data-class', 'MAGE')
    expect(screen.getByText('Alice')).toHaveAttribute('data-class', 'ROGUE')
  })

  it('puts the character on its own line in flow chart nodes', async () => {
    const named: RankResult = { ...robe, tree: { ...robe.tree, crafter: 'Smithy' } }
    renderWithProviders(<ResultsTable results={[named]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    expect(screen.getByText('Craft 1x Green Robe')).toBeInTheDocument()
    expect(screen.getByText('Smithy')).toBeInTheDocument()
  })

  it('shows mailing to an enchanter on the flow chart', async () => {
    renderWithProviders(<ResultsTable results={[disenchanted]} items={items} />)
    await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
    expect(screen.getByText((_, el) => el?.tagName === 'SPAN' && el.textContent === 'Mail 1x to Enchy')).toBeInTheDocument()
    expect(screen.getAllByText('Enchy')).toHaveLength(2) // mail recipient, and the disenchanter under the sale
    expect(screen.getByText('Postage · -0g 00s 30c')).toBeInTheDocument()
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

  describe('sorting', () => {
    const rows: RankResult[] = [
      { ...robe, recipe_id: 1, recipe: 'Bolt', cost: 50, profit: 300, best_exit: 'ah' },
      { ...robe, recipe_id: 2, recipe: 'Axe', cost: 900, profit: 100, best_exit: 'vendor' },
      { ...robe, recipe_id: 3, recipe: 'Cape', cost: 400, profit: 200, best_exit: 'disenchant' },
    ]
    const order = () =>
      screen.getAllByRole('button', { name: /^Details for / }).map((b) => b.getAttribute('aria-label')?.slice(12))
    const header = (name: string) => screen.getByRole('columnheader', { name: new RegExp(`^${name}`) })
    const sortBy = async (name: string) => await userEvent.click(screen.getByRole('button', { name: `Sort by ${name}` }))

    it('keeps the given order until a column is picked', () => {
      renderWithProviders(<ResultsTable results={rows} items={items} />)
      expect(order()).toEqual(['Bolt', 'Axe', 'Cape'])
      expect(header('Profit')).toHaveAttribute('aria-sort', 'none')
    })

    it('sorts numbers largest first, then reverses on a second click', async () => {
      renderWithProviders(<ResultsTable results={rows} items={items} />)
      await sortBy('Cost')
      expect(order()).toEqual(['Axe', 'Cape', 'Bolt'])
      expect(header('Cost')).toHaveAttribute('aria-sort', 'descending')
      await sortBy('Cost')
      expect(order()).toEqual(['Bolt', 'Cape', 'Axe'])
      expect(header('Cost')).toHaveAttribute('aria-sort', 'ascending')
    })

    it('sorts text alphabetically first', async () => {
      renderWithProviders(<ResultsTable results={rows} items={items} />)
      await sortBy('Recipe')
      expect(order()).toEqual(['Axe', 'Bolt', 'Cape'])
      await sortBy('Sell via')
      expect(order()).toEqual(['Bolt', 'Cape', 'Axe'])
      expect(header('Recipe')).toHaveAttribute('aria-sort', 'none')
    })

    it('sorts profit ascending to surface the losers', async () => {
      renderWithProviders(<ResultsTable results={rows} items={items} />)
      await sortBy('Profit')
      expect(order()).toEqual(['Bolt', 'Cape', 'Axe'])
      await sortBy('Profit')
      expect(order()).toEqual(['Axe', 'Cape', 'Bolt'])
    })
  })

  describe('changing the plan', () => {
    const [linenNode, threadNode] = robe.tree.inputs
    /** The robe with its thread bought on the AH instead, as the server re-costs it. */
    const fromAh: RankResult = {
      ...robe,
      cost: 350,
      profit: 150,
      roi: 150 / 350,
      steps: robe.steps.map((s) => (s.item_id === 2 ? { ...s, value: -150, via: 'ah' } : s)),
      tree: {
        ...robe.tree,
        cost: 350,
        inputs: [linenNode!, { ...bought(2, 'Coarse Thread', 1, 150, 'ah', threadNode!.options) }],
      },
      sell_options: [
        { kind: 'vendor', profit: 150 },
        { kind: 'ah', profit: 125 },
      ],
    }
    async function open() {
      const fetch = mockApi({ '/api/evaluate': { result: fromAh, items } })
      renderWithProviders(<ResultsTable results={[robe]} items={items} />)
      await userEvent.click(screen.getByRole('button', { name: 'Details for Green Robe' }))
      return fetch
    }

    it('offers a menu only where there is a choice, best first', async () => {
      await open()
      expect(screen.queryByRole('button', { name: 'Change source of Linen Cloth' })).not.toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Change source of Coarse Thread' }))
      expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
        '✓Buy from a vendor-0g 01s 00c',
        'Buy on the AH-0g 01s 50c',
      ])
    })

    it('offers the other ways to sell on the sale', async () => {
      await open()
      await userEvent.click(screen.getByRole('button', { name: 'Change how it is sold' }))
      expect(screen.getAllByRole('menuitem').map((i) => i.textContent)).toEqual([
        '✓Sell to a vendorprofit 0g 02s 00c',
        'Sell on the AHprofit 0g 01s 75c',
      ])
    })

    it('re-costs the recipe with the choice, and Reset brings back the best plan', async () => {
      const fetch = await open()
      expect(screen.queryByRole('button', { name: 'Reset' })).not.toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: 'Change source of Coarse Thread' }))
      await userEvent.click(screen.getByRole('menuitem', { name: /Buy on the AH/ }))

      expect(await screen.findByText('Buy on the AH · -0g 01s 50c')).toBeInTheDocument()
      const request = fetch.mock.calls[0]![0]
      expect([request.method, new URL(request.url).pathname]).toEqual(['POST', '/api/evaluate'])
      expect(await request.json()).toEqual({
        recipe_id: 100,
        include_unlearned: false,
        exits: ['vendor', 'ah', 'disenchant'],
        choices: { 'r.1': 'ah' },
      })
      expect(line('0g 01s 50c')).toBeInTheDocument() // the row's profit follows the changed plan
      expect(screen.getByLabelText('Changed plan')).toBeInTheDocument()

      await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
      expect(screen.getByText('Buy from a vendor · -0g 01s 00c')).toBeInTheDocument()
      expect(line('0g 02s 00c')).toBeInTheDocument()
      expect(screen.queryByLabelText('Changed plan')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Reset' })).not.toBeInTheDocument()
    })
  })
})
