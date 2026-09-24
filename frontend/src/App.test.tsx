import { Notifications, notifications } from '@mantine/notifications'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { UpdateResult } from './api/client'
import { GAME_VERSION_KEY } from './lib/gameVersion'
import { syncSeen, syncSeenKey } from './lib/syncNotice'
import { characters, status } from './test/status'
import { GUEST, LINKED, mockApi, renderWithProviders } from './test/utils'

const result: UpdateResult = {
  build: '1.60.1.70000',
  updated: true,
  items: 1234,
  recipes: 56,
  disenchant_rows: 0,
  vendor_items: 7,
}

function renderApp() {
  return renderWithProviders(
    <>
      <Notifications />
      <App />
    </>,
  )
}

function updateCalls(fetch: ReturnType<typeof mockApi>) {
  return fetch.mock.calls.map(([r]) => new URL(r.url)).filter((u) => u.pathname === '/api/game-data/update')
}

describe('automatic game data update', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    notifications.clean()
  })

  it('asks for the newest build once on load and toasts when it downloaded one', async () => {
    const fetch = mockApi({ '/api/game-data/update': result, '/api/status': status(), '/api/characters': characters })
    renderApp()
    expect(await screen.findByText('New game data downloaded')).toBeInTheDocument()
    expect(screen.getByText(/Loaded build 1\.60\.1\.70000: 1,234 items, 56 recipes/)).toBeInTheDocument()
    const calls = updateCalls(fetch)
    expect(calls).toHaveLength(1)
    expect(calls[0]?.searchParams.get('only_if_new')).toBe('true')
  })

  it('stays quiet when the database already has the newest build', async () => {
    const fetch = mockApi({ '/api/game-data/update': { ...result, updated: false }, '/api/status': status(), '/api/characters': characters })
    renderApp()
    await waitFor(() => expect(updateCalls(fetch)).toHaveLength(1))
    await new Promise((resolve) => setTimeout(resolve, 50)) // let the mutation settle
    expect(screen.queryByText('New game data downloaded')).not.toBeInTheDocument()
  })
})

describe('addon sync notifications', () => {
  afterEach(() => notifications.clean())

  function stale() {
    return { '/api/game-data/update': { ...result, updated: false }, '/api/characters': characters }
  }

  it('toasts what the sync imported since the page last saw the status', async () => {
    const before = status()
    localStorage.setItem(syncSeenKey('forever'), JSON.stringify(syncSeen(before)))
    mockApi({
      ...stale(),
      '/api/status': status({ data_version: 2, last_auctionator_sync: '2026-09-24 11:00:00' }),
    })
    renderApp()
    expect(await screen.findByText('Addon data imported')).toBeInTheDocument()
    expect(screen.getByText('Loaded Auctionator prices for ClassicBetaPvE.')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(syncSeenKey('forever')) ?? '')).toMatchObject({ data_version: 2 })
  })

  it('does not announce the data it finds on a first visit', async () => {
    mockApi({ ...stale(), '/api/status': status() })
    renderApp()
    await waitFor(() => expect(localStorage.getItem(syncSeenKey('forever'))).not.toBeNull())
    expect(screen.queryByText('Addon data imported')).not.toBeInTheDocument()
  })
})

describe('game version switch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    notifications.clean()
    localStorage.clear()
  })

  const versionsOf = (fetch: ReturnType<typeof mockApi>, path: string) =>
    fetch.mock.calls
      .map(([r]) => new URL(r.url))
      .filter((u) => u.pathname === path)
      .map((u) => u.searchParams.get('game_version'))

  it('asks the API about the chosen game and remembers the choice', async () => {
    const fetch = mockApi({
      '/api/game-data/update': { ...result, updated: false },
      '/api/status': status(),
      '/api/characters': characters,
    })
    renderApp()
    await waitFor(() => expect(versionsOf(fetch, '/api/status')).toContain('forever'))
    expect(versionsOf(fetch, '/api/status')).not.toContain('tbc')

    fireEvent.click(screen.getByText('TBC Anniversary'))
    await waitFor(() => expect(versionsOf(fetch, '/api/status')).toContain('tbc'))
    await waitFor(() => expect(versionsOf(fetch, '/api/game-data/update')).toEqual(['forever', 'tbc']))
    expect(JSON.parse(localStorage.getItem(GAME_VERSION_KEY) ?? '')).toBe('tbc')
  })
})


describe('the shell by mode and tier', () => {
  const tabs = () => screen.getAllByRole('tab').map((t) => t.textContent)
  const hostedApi = () =>
    mockApi({
      '/api/status': status(),
      '/api/characters': characters,
      '/api/realms': [],
      '/api/ah-blocked': { items: [], details: {} },
    })

  it('shows everything in local mode, with no account controls', async () => {
    mockApi({ '/api/game-data/update': result, '/api/status': status(), '/api/characters': characters, '/api/realms': [] })
    renderApp()
    expect(tabs()).toEqual(['Search', 'Prices', 'Manage'])
    expect(screen.queryByText('Guest')).not.toBeInTheDocument()
  })

  it('gives guests only prices and a way to link, and never syncs or updates game data', async () => {
    const fetch = hostedApi()
    renderWithProviders(<App />, GUEST)
    expect(tabs()).toEqual(['Prices'])
    expect(screen.getByText('You are browsing as a guest')).toBeInTheDocument()
    expect(await screen.findByText(/No auction house has prices/)).toBeInTheDocument()
    expect(updateCalls(fetch)).toEqual([])
  })

  it('gives linked users search and their AH blocks, without the local file sync', async () => {
    const fetch = hostedApi()
    renderWithProviders(<App />, LINKED)
    expect(tabs()).toEqual(['Search', 'Prices', 'Manage'])
    expect(screen.getByText('Linked account')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Manage' }))
    expect(await screen.findByText('Never sold on the auction house')).toBeInTheDocument()
    expect(screen.queryByText('Addon data')).not.toBeInTheDocument()
    expect(screen.queryByText('Game data')).not.toBeInTheDocument()
    expect(updateCalls(fetch)).toEqual([])
  })
})
