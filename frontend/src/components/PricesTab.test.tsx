import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { AuctionHouse, PriceHistory, Prices } from '../api/client'
import { linen, robe, thread } from '../test/items'
import { status } from '../test/status'
import { GUEST, mockApi, renderWithProviders, shown } from '../test/utils'
import { PricesTab } from './PricesTab'

const realms: AuctionHouse[] = [
  { id: 1, realm: 'Classic Beta PvE', faction: '', prices: 3, last_scan: '2026-09-24 10:00:00' },
  { id: 2, realm: 'Dreamscythe', faction: 'Horde', prices: 1, last_scan: null },
]

const noStats = { median_7d: null, avail_7d: null, scans_7d: null }

const history: PriceHistory = {
  item: linen,
  stats: noStats,
  days: [
    { day: '2026-09-24', low: 20, high: 35, available: 40 },
    { day: '2026-09-23', low: 18, high: 30, available: null },
  ],
}

function prices(url: URL): Prices {
  const q = url.searchParams.get('q')?.toLowerCase() ?? ''
  const items = [thread, robe, linen].filter((i) => i.name.toLowerCase().includes(q))
  const stats = Object.fromEntries(items.map((i) => [i.id, i === linen ? { median_7d: 18, avail_7d: 40, scans_7d: 5 } : noStats]))
  return { items, stats, total: items.length, gated: false }
}

function requests(fetch: ReturnType<typeof mockApi>, pathname: string) {
  return fetch.mock.calls.map(([r]) => new URL(r.url)).filter((u) => u.pathname === pathname)
}

describe('PricesTab', () => {
  afterEach(() => localStorage.clear())

  it("lists the selection's auction house prices and searches by name", async () => {
    const fetch = mockApi({ '/api/status': status(), '/api/realms': realms, '/api/prices': prices })
    renderWithProviders(<PricesTab />)
    expect(await screen.findByText('Linen Cloth')).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Auction house' })).toHaveValue('Classic Beta PvE: 3 prices')
    const row = screen.getByText('Linen Cloth').closest('tr')
    expect(shown(row)).toContain('20')
    expect(shown(row)).toContain('18') // the 7-day median, over 5 days
    expect(row).toHaveTextContent('5d')
    expect(requests(fetch, '/api/prices')[0]?.searchParams.get('auction_house_id')).toBe('1')

    await userEvent.type(screen.getByRole('textbox', { name: 'Item' }), 'robe')
    await waitFor(() => expect(screen.queryByText('Linen Cloth')).not.toBeInTheDocument())
    expect(screen.getByText('Green Robe')).toBeInTheDocument()
    expect(requests(fetch, '/api/prices').at(-1)?.searchParams.get('q')).toBe('robe')
    expect(screen.getByText('1 items.')).toBeInTheDocument()
  })

  it("shows an item's daily history", async () => {
    const fetch = mockApi({
      '/api/status': status(),
      '/api/realms': realms,
      '/api/prices': prices,
      '/api/prices/1': history,
    })
    renderWithProviders(<PricesTab />)
    await userEvent.click(await screen.findByRole('button', { name: 'History of Linen Cloth' }))
    const table = await screen.findByRole('table', { name: 'Price history' })
    const rows = within(table).getAllByRole('row')
    expect(rows.map((r) => r.textContent?.slice(0, 10))).toEqual(['DayLowHigh', '2026-09-24', '2026-09-23'])
    expect(requests(fetch, '/api/prices/1')[0]?.searchParams.get('auction_house_id')).toBe('1')
  })

  it('remembers another auction house', async () => {
    const fetch = mockApi({ '/api/status': status(), '/api/realms': realms, '/api/prices': prices })
    renderWithProviders(<PricesTab />)
    await userEvent.click(await screen.findByRole('combobox', { name: 'Auction house' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Dreamscythe (Horde): 1 prices' }))
    await waitFor(() => expect(requests(fetch, '/api/prices').at(-1)?.searchParams.get('auction_house_id')).toBe('2'))
    expect(localStorage.getItem('altarmy-profit.pricesAuctionHouse.forever')).toBe('2')
  })

  it('tells guests that higher-level items need a linked account', async () => {
    mockApi({
      '/api/status': status({ characters: 0, selection: null, auction_house_id: null }),
      '/api/realms': realms,
      '/api/prices': { items: [linen], stats: { 1: noStats }, total: 1, gated: true },
    })
    renderWithProviders(<PricesTab />, GUEST)
    expect(await screen.findByText(/Guests see prices of items up to level 30/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Auction house' })).toHaveValue('Classic Beta PvE: 3 prices')
  })

  it('says when there are no prices at all', async () => {
    mockApi({ '/api/status': status(), '/api/realms': [] })
    renderWithProviders(<PricesTab />)
    expect(await screen.findByText(/No auction house has prices/)).toBeInTheDocument()
  })
})
