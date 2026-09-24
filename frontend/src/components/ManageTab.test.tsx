import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { status } from '../test/status'
import { mockApi, renderWithProviders } from '../test/utils'
import { ManageTab } from './ManageTab'

const files = (path: string) => ({ files: [path], default: path })

function requests(fetch: ReturnType<typeof mockApi>, pathname: string) {
  return fetch.mock.calls.map(([r]) => r).filter((r) => new URL(r.url).pathname === pathname)
}

describe('ManageTab addon data', () => {
  it('shows the files in use, what they hold, and sync warnings', async () => {
    const s = status({ warnings: ['Auctionator has no prices for Dreamscythe (Horde).'] })
    mockApi({
      '/api/status': s,
      '/api/altarmy/files': files(s.altarmy_path ?? ''),
      '/api/auctionator/files': files(s.auctionator_path ?? ''),
    })
    renderWithProviders(<ManageTab />)
    expect(await screen.findByRole('combobox', { name: /AltArmy_TBC\.lua/ })).toHaveValue(s.altarmy_path)
    expect(screen.getByRole('combobox', { name: /Auctionator\.lua/ })).toHaveValue(s.auctionator_path)
    expect(screen.getByText(/characters, last read/)).toHaveTextContent('3 characters, last read 2026-09-24 10:01:00 UTC.')
    expect(screen.getByText(/Prices from/)).toHaveTextContent('Prices from ClassicBetaPvE (for Classic Beta PvE, Horde)')
    expect(screen.getByText(/no prices for Dreamscythe/)).toBeInTheDocument()
    for (const button of screen.getAllByRole('button', { name: 'Use this file' })) expect(button).toBeDisabled()
  })

  it('switches to a pasted file and syncs on demand', async () => {
    const fetch = mockApi({
      '/api/status': status(),
      '/api/altarmy/files': { files: [], default: null },
      '/api/auctionator/files': { files: [], default: null },
      '/api/sources': status({ altarmy_path: 'D:\\AltArmy_TBC.lua', data_version: 2 }),
      '/api/sync': status({ data_version: 3 }),
    })
    renderWithProviders(<ManageTab />)
    const input = await screen.findByRole('combobox', { name: /AltArmy_TBC\.lua/ })
    await userEvent.clear(input)
    await userEvent.type(input, 'D:\\AltArmy_TBC.lua')
    const [useAltArmy] = screen.getAllByRole('button', { name: 'Use this file' })
    await userEvent.click(useAltArmy!)
    await waitFor(() => expect(requests(fetch, '/api/sources')).toHaveLength(1))
    const [put] = requests(fetch, '/api/sources')
    expect(put?.method).toBe('PUT')
    expect(await put?.json()).toEqual({ altarmy_path: 'D:\\AltArmy_TBC.lua' })

    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    await waitFor(() => expect(requests(fetch, '/api/sync')).toHaveLength(1))
    expect(requests(fetch, '/api/sync')[0]?.method).toBe('POST')
  })
})
