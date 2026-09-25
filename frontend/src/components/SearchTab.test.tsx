import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { robeResult } from '../test/results'
import { characters, status } from '../test/status'
import { mockApi, renderWithProviders } from '../test/utils'
import { SearchTab } from './SearchTab'

// Tests that only check paging swap the results table for one line per row: rendering 150 full rows
// in jsdom takes seconds on a loaded machine.
const table = vi.hoisted(() => ({ stub: false }))
vi.mock('./ResultsTable', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./ResultsTable')>()
  return {
    ...actual,
    ResultsTable: (props: Parameters<typeof actual.ResultsTable>[0]) =>
      table.stub ? <div>{props.results.length} rows</div> : <actual.ResultsTable {...props} />,
  }
})
afterEach(() => {
  table.stub = false
})

const noResults = { results: [], total: 0, items: {}, classes: {} }

function urls(fetch: ReturnType<typeof mockApi>, pathname: string) {
  return fetch.mock.calls.map(([request]) => new URL(request.url)).filter((u) => u.pathname === pathname)
}

describe('SearchTab', () => {
  it('points to the Manage tab when there are no recipes', async () => {
    mockApi({ '/api/status': status({ recipes: 0 }), '/api/characters': characters })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByText(/Download game data on the Manage tab/)).toBeInTheDocument()
  })

  it('asks for Alt Army characters before ranking, and shows sync warnings', async () => {
    const fetch = mockApi({
      '/api/status': status({
        characters: 0,
        selection: null,
        prices: 0,
        warnings: ['No Alt Army file found. Pick AltArmy_TBC.lua on the Manage tab.'],
      }),
      '/api/characters': { groups: [], selection: null },
    })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByText(/No characters yet/)).toBeInTheDocument()
    expect(screen.getByText(/No Alt Army file found/)).toBeInTheDocument()
    expect(screen.getByText(/No prices yet/)).toBeInTheDocument()
    expect(urls(fetch, '/api/rank')).toEqual([])
  })

  it("shows the selected realm's characters and ranks with the stored parameters", async () => {
    localStorage.setItem('altarmy-profit.search.includeUnlearned', 'true')
    localStorage.setItem('altarmy-profit.search.includeTrivial', 'false')
    localStorage.setItem('altarmy-profit.search.open', JSON.stringify(['advanced', 'characters']))
    localStorage.setItem('altarmy-profit.search.exits', JSON.stringify(['ah', 'vendor']))
    localStorage.setItem('altarmy-profit.search.minCost', JSON.stringify(0.5))
    localStorage.setItem('altarmy-profit.search.maxCost', JSON.stringify(20))
    localStorage.setItem('altarmy-profit.search.minRoi', 'null')
    localStorage.setItem('altarmy-profit.search.maxRoi', JSON.stringify(250))
    const fetch = mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByLabelText('Min cost (gold)')).toHaveValue('0.5')
    expect(screen.getByLabelText('Max cost (gold)')).toHaveValue('20')
    expect(screen.getByLabelText('Min profit (gold)')).toHaveValue('0.0001')
    expect(screen.getByLabelText('Min ROI (%)')).toHaveValue('')
    expect(screen.getByRole('checkbox', { name: 'Auction house' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Disenchant' })).not.toBeChecked()
    expect(screen.getByRole('switch', { name: /Include recipes not learned yet/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Include Trivial Recipes/ })).not.toBeChecked()
    expect(await screen.findByText('Tailor Guy')).toBeInTheDocument() // characters load after the status
    expect(screen.getByText(/Cooking 1\/75, Tailoring 50\/75/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Characters (1)' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Realm and faction' })).toHaveValue('Classic Beta PvE (Horde)')
    await screen.findByText(/No recipes match these filters/)
    const [rank] = urls(fetch, '/api/rank')
    expect(rank?.searchParams.toString()).toBe(
      'game_version=forever&include_unlearned=true&include_trivial=false&exits=vendor&exits=ah&min_cost=5000&max_cost=200000&min_profit=1&max_roi=2.5&top=50',
    )
  })

  it('opens and closes the sections, remembering which are open', async () => {
    mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    const advanced = await screen.findByRole('button', { name: 'Advanced Options' })
    expect(advanced).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(advanced)
    expect(advanced).toHaveAttribute('aria-expanded', 'true')
    expect(localStorage.getItem('altarmy-profit.search.open')).toBe('["advanced"]')
    await userEvent.click(await screen.findByRole('button', { name: /^Characters/ }))
    expect(localStorage.getItem('altarmy-profit.search.open')).toBe('["advanced","characters"]')
    await userEvent.click(advanced)
    expect(localStorage.getItem('altarmy-profit.search.open')).toBe('["characters"]')
  })

  it('asks for a way to sell instead of ranking when none is ticked', async () => {
    localStorage.setItem('altarmy-profit.search.exits', '[]')
    const fetch = mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByText(/Pick at least one way to sell/)).toBeInTheDocument()
    expect(urls(fetch, '/api/rank')).toEqual([])
  })

  it('shows 50 more results at a time', { timeout: 15_000 }, async () => {
    table.stub = true
    // As many results as asked for, out of 120.
    const rank = (url: URL) => {
      const top = Math.min(Number(url.searchParams.get('top')), 120)
      const results = Array.from({ length: top }, (_, i) => ({ ...robeResult, recipe_id: i }))
      return { results, total: 120, items: {}, classes: {} }
    }
    const fetch = mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': rank })
    renderWithProviders(<SearchTab />)
    const slow = { timeout: 5000 }
    expect(await screen.findByText('Showing 50 of 120', {}, slow)).toBeInTheDocument()
    expect(screen.getByText('50 rows')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))
    expect(await screen.findByText('Showing 100 of 120', {}, slow)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show more' }))
    await waitFor(
      () => expect(screen.queryByRole('button', { name: 'Show more' })).not.toBeInTheDocument(),
      slow,
    )
    expect(screen.getByText('120 rows')).toBeInTheDocument()
    expect(urls(fetch, '/api/rank').map((u) => u.searchParams.get('top'))).toEqual(['50', '100', '150'])
  })

  it('switches realm on the server', async () => {
    const fetch = mockApi({
      '/api/status': status(),
      '/api/characters': characters,
      '/api/rank': noResults,
      '/api/selection': status({ selection: { realm: 'Dreamscythe', faction: 'Horde' } }),
    })
    renderWithProviders(<SearchTab />)
    await screen.findByText('Tailor Guy')
    await userEvent.click(screen.getByRole('combobox', { name: 'Realm and faction' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Dreamscythe (Horde)' }))
    await waitFor(() => expect(urls(fetch, '/api/selection')).toHaveLength(1))
    const put = fetch.mock.calls.map(([r]) => r).find((r) => new URL(r.url).pathname === '/api/selection')
    expect(put?.method).toBe('PUT')
    expect(await put?.json()).toEqual({ realm: 'Dreamscythe', faction: 'Horde' })
    expect(await screen.findByText('Frell')).toBeInTheDocument()
  })

  it('saves changed parameters and ignores malformed stored values', async () => {
    localStorage.setItem('altarmy-profit.search.includeUnlearned', '"yes"')
    localStorage.setItem('altarmy-profit.search.maxProfit', 'garbage')
    localStorage.setItem('altarmy-profit.search.exits', '["trade"]')
    mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    const maxProfit = await screen.findByLabelText('Max profit (gold)')
    expect(maxProfit).toHaveValue('')
    for (const name of ['Vendor', 'Disenchant', 'Auction house']) {
      expect(screen.getByRole('checkbox', { name, hidden: true })).toBeChecked()
    }
    const unlearned = screen.getByRole('switch', { name: /Include recipes not learned yet/ })
    expect(unlearned).not.toBeChecked()
    const trivial = screen.getByRole('checkbox', { name: /Include Trivial Recipes/, hidden: true })
    expect(trivial).toBeChecked()
    fireEvent.change(maxProfit, { target: { value: '40' } })
    expect(localStorage.getItem('altarmy-profit.search.maxProfit')).toBe('40')
    fireEvent.change(maxProfit, { target: { value: '' } })
    expect(localStorage.getItem('altarmy-profit.search.maxProfit')).toBe('null')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Disenchant', hidden: true }))
    expect(localStorage.getItem('altarmy-profit.search.exits')).toBe('["vendor","ah"]')
    fireEvent.click(unlearned)
    expect(localStorage.getItem('altarmy-profit.search.includeUnlearned')).toBe('true')
    fireEvent.click(trivial)
    expect(localStorage.getItem('altarmy-profit.search.includeTrivial')).toBe('false')
  })
})
