import { Notifications, notifications } from '@mantine/notifications'
import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { UpdateResult } from './api/client'
import { SYNC_SEEN_KEY, syncSeen } from './lib/syncNotice'
import { characters, status } from './test/status'
import { mockApi, renderWithProviders } from './test/utils'

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
    localStorage.setItem(SYNC_SEEN_KEY, JSON.stringify(syncSeen(before)))
    mockApi({
      ...stale(),
      '/api/status': status({ data_version: 2, last_auctionator_sync: '2026-09-24 11:00:00' }),
    })
    renderApp()
    expect(await screen.findByText('Addon data imported')).toBeInTheDocument()
    expect(screen.getByText('Loaded Auctionator prices for ClassicBetaPvE.')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(SYNC_SEEN_KEY) ?? '')).toMatchObject({ data_version: 2 })
  })

  it('does not announce the data it finds on a first visit', async () => {
    mockApi({ ...stale(), '/api/status': status() })
    renderApp()
    await waitFor(() => expect(localStorage.getItem(SYNC_SEEN_KEY)).not.toBeNull())
    expect(screen.queryByText('Addon data imported')).not.toBeInTheDocument()
  })
})
