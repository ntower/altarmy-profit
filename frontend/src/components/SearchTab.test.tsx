import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { characters, status } from '../test/status'
import { mockApi, renderWithProviders } from '../test/utils'
import { SearchTab } from './SearchTab'

const noResults = { results: [], items: {} }

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
    localStorage.setItem('wowprofit.search.includeUnlearned', 'true')
    localStorage.setItem('wowprofit.search.minGold', JSON.stringify(1.5))
    localStorage.setItem('wowprofit.search.top', JSON.stringify(10))
    const fetch = mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    expect(await screen.findByLabelText('Min profit (gold)')).toHaveValue('1.5')
    expect(screen.getByLabelText('Show top')).toHaveValue('10')
    expect(screen.getByRole('switch', { name: /Include recipes not learned yet/ })).toBeChecked()
    expect(await screen.findByText('Tailor Guy')).toBeInTheDocument() // characters load after the status
    expect(screen.getByText(/Cooking 1\/75, Tailoring 50\/75/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Realm and faction' })).toHaveValue('Classic Beta PvE (Horde)')
    await screen.findByText(/No profitable recipes found/)
    const [rank] = urls(fetch, '/api/rank')
    expect(rank?.searchParams.get('include_unlearned')).toBe('true')
    expect(rank?.searchParams.get('min_profit')).toBe('15000')
    expect(rank?.searchParams.get('top')).toBe('10')
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
    localStorage.setItem('wowprofit.search.includeUnlearned', '"yes"')
    localStorage.setItem('wowprofit.search.top', 'garbage')
    mockApi({ '/api/status': status(), '/api/characters': characters, '/api/rank': noResults })
    renderWithProviders(<SearchTab />)
    const top = await screen.findByLabelText('Show top')
    expect(top).toHaveValue('25')
    const unlearned = screen.getByRole('switch', { name: /Include recipes not learned yet/ })
    expect(unlearned).not.toBeChecked()
    fireEvent.change(top, { target: { value: '40' } })
    expect(localStorage.getItem('wowprofit.search.top')).toBe('40')
    fireEvent.click(unlearned)
    expect(localStorage.getItem('wowprofit.search.includeUnlearned')).toBe('true')
  })
})
