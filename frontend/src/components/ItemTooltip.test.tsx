import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/utils'
import { linen, robe, thread } from '../test/items'
import { ItemLink, ItemTooltip, RecipeTooltip } from './ItemTooltip'

/** The element whose own text content (including children) is exactly `text`. */
const line = (text: string) => screen.getByText((_, el) => el?.textContent === text && el.children.length > 0)

describe('ItemTooltip', () => {
  it('shows the in-game lines for an item', () => {
    renderWithProviders(<ItemTooltip item={robe} />)
    expect(screen.getByText('Green Robe')).toHaveStyle({ color: '#1eff00' })
    expect(screen.getByText('Binds when equipped')).toBeInTheDocument()
    expect(screen.getByText('Chest')).toBeInTheDocument()
    expect(screen.getByText('Cloth')).toBeInTheDocument()
    expect(screen.getByText('Requires Level 12')).toBeInTheDocument()
    expect(screen.getByText('Requires Tailoring (50)')).toBeInTheDocument()
    expect(screen.getByText('"Soft and green."')).toBeInTheDocument()
    expect(line('Sell Price: 2 16')).toBeInTheDocument()
    expect(screen.queryByText(/Auction:|Vendor:/)).not.toBeInTheDocument()
    expect(screen.getByRole('presentation')).toHaveAttribute(
      'src',
      'https://wow.zamimg.com/images/wow/icons/large/inv_chest_cloth_39.jpg',
    )
  })

  it('adds the auction price and leaves out empty lines', () => {
    renderWithProviders(<ItemTooltip item={linen} />)
    expect(line('Auction: 20')).toBeInTheDocument()
    expect(screen.queryByText(/Binds|Requires/)).not.toBeInTheDocument()
    expect(screen.queryByRole('presentation')).not.toBeInTheDocument()
  })

  it('adds the vendor price of vendor-sold items', () => {
    renderWithProviders(<ItemTooltip item={thread} />)
    expect(line('Vendor: 1')).toBeInTheDocument()
  })

  it('shows reagents above the crafted item on a recipe', () => {
    const items = { '1': linen, '2': thread, '3': robe }
    const reagents = [
      { item_id: 1, count: 10 },
      { item_id: 2, count: 1 },
    ]
    renderWithProviders(
      <RecipeTooltip name="Green Robe" profession="Tailoring" reagents={reagents} output={robe} items={items} />,
    )
    expect(screen.getByText('Tailoring')).toBeInTheDocument()
    expect(screen.getByText('Reagents: Linen Cloth (10), Coarse Thread')).toBeInTheDocument()
    expect(screen.getByText('Binds when equipped')).toBeInTheDocument()
  })

  it('opens on hover of an item link', async () => {
    renderWithProviders(<ItemLink item={robe} />)
    expect(screen.queryByText('Binds when equipped')).not.toBeInTheDocument()
    await userEvent.hover(screen.getByText('Green Robe'))
    expect(await screen.findByText('Binds when equipped')).toBeInTheDocument()
  })
})
